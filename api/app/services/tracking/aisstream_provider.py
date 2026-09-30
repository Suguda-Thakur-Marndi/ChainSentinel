"""AISStream live maritime vessel telemetry provider.

Connects to the official AISStream WebSocket (wss://stream.aisstream.io/v0/stream)
in a dedicated background task, parses real-time transponder frames (MMSI, position,
heading, speed, ship name), normalizes them into LiveMapObject (type="vessel"),
and pushes incremental updates to the LiveMapAggregator.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

import websockets
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.aisstream")

DEFAULT_AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"
MAX_CACHED_VESSELS = 3000
STALE_VESSEL_SECONDS = 900  # 15 minutes


class AISStreamProvider(TrackingProvider):
    """Production live maritime tracking provider backed by AISStream WebSocket."""

    name: str = "aisstream"
    purpose: str = "Maritime Vessel Telemetry"

    def __init__(
        self,
        api_key: Optional[str] = None,
        ws_url: Optional[str] = None,
        on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None,
    ):
        super().__init__(on_update=on_update)
        self._api_key = api_key or os.getenv("AISSTREAM_API_KEY", "")
        self._ws_url = ws_url or os.getenv("AISSTREAM_WS_URL", DEFAULT_AISSTREAM_WS_URL)
        self._vessels: Dict[str, LiveMapObject] = {}
        self._task: Optional[asyncio.Task] = None
        self._status = ProviderHealthStatus.UNCONFIGURED
        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None
        self._total_messages: int = 0
        self._lock = asyncio.Lock()

        if self._api_key:
            self._status = ProviderHealthStatus.DISCONNECTED
        else:
            self._status = ProviderHealthStatus.UNCONFIGURED

    async def start(self) -> None:
        """Start the background streaming worker."""
        if self._task and not self._task.done():
            return
        if not self._api_key:
            self._status = ProviderHealthStatus.UNCONFIGURED
            self._last_error = "AISSTREAM_API_KEY is not configured"
            logger.warning("[AISStream] Cannot start: AISSTREAM_API_KEY not configured.")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._run_loop(), name="aisstream_ws_worker")
        logger.info("[AISStream] Background WebSocket worker started.")

    async def stop(self) -> None:
        """Stop the background worker."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._status = ProviderHealthStatus.DISCONNECTED
        logger.info("[AISStream] Background worker stopped.")

    async def health_check(self) -> ProviderHealth:
        """Return runtime health status."""
        async with self._lock:
            count = len(self._vessels)
        return ProviderHealth(
            name=self.name,
            purpose=self.purpose,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            latency_ms=self._latency_ms,
            objects=count,
            reason=self._last_error if self._status != ProviderHealthStatus.CONNECTED else None,
        )

    async def get_objects(self) -> List[LiveMapObject]:
        """Return list of active vessels."""
        async with self._lock:
            # Return current list of vessels
            return list(self._vessels.values())

    async def _run_loop(self) -> None:
        """Maintain persistent connection with exponential backoff."""
        backoff = 2.0
        while self._is_running:
            start_connect = time.monotonic()
            try:
                logger.info(f"[AISStream] Connecting to WebSocket: {self._ws_url}")
                async with websockets.connect(
                    self._ws_url,
                    open_timeout=15,
                    close_timeout=10,
                    ping_interval=30,
                    ping_timeout=20,
                ) as ws:
                    self._latency_ms = round((time.monotonic() - start_connect) * 1000, 2)
                    self._status = ProviderHealthStatus.CONNECTED
                    self._last_error = None
                    backoff = 2.0

                    # Send subscription request (covering global waters)
                    subscription = {
                        "APIKey": self._api_key,
                        "BoundingBoxes": [[[-90.0, -180.0], [90.0, 180.0]]],
                        "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
                    }
                    await ws.send(json.dumps(subscription))
                    logger.info("[AISStream] Authenticated & subscribed to live maritime telemetry.")

                    while self._is_running:
                        raw_msg = await ws.recv()
                        self._total_messages += 1
                        now_iso = datetime.now(timezone.utc).isoformat()
                        self._last_success = now_iso

                        try:
                            data = json.loads(raw_msg)
                            vessel = self._parse_ais_frame(data, now_iso)
                            if vessel:
                                async with self._lock:
                                    self._vessels[vessel.id] = vessel
                                    # Prune if cache grows too large
                                    if len(self._vessels) > MAX_CACHED_VESSELS:
                                        self._prune_stale_vessels()

                                if self._on_update:
                                    try:
                                        await self._on_update([vessel])
                                    except Exception as exc:
                                        logger.debug(f"[AISStream] Update callback error: {exc}")
                        except Exception as parse_err:
                            logger.debug(f"[AISStream] Frame parse skipped: {parse_err}")

            except asyncio.CancelledError:
                break
            except Exception as conn_err:
                self._status = ProviderHealthStatus.ERROR
                self._last_error = f"Connection drop: {type(conn_err).__name__}"
                logger.warning(f"[AISStream] WebSocket disconnected ({conn_err}), reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 60.0)

    def _parse_ais_frame(self, data: Dict[str, Any], receive_time: str) -> Optional[LiveMapObject]:
        """Convert raw AISStream payload into canonical LiveMapObject."""
        msg_type = data.get("MessageType")
        meta = data.get("MetaData", {}) or {}
        msg_body = data.get("Message", {}) or {}

        lat = meta.get("latitude")
        lon = meta.get("longitude")
        mmsi = meta.get("MMSI")

        if lat is None or lon is None or mmsi is None:
            return None

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (ValueError, TypeError):
            return None

        # Disallow exact 0,0 null island
        if abs(lat_f) < 1e-5 and abs(lon_f) < 1e-5:
            return None

        raw_name = meta.get("ShipName")
        ship_name = str(raw_name).strip() if raw_name else f"Vessel-{mmsi}"
        if not ship_name:
            ship_name = f"Vessel-{mmsi}"

        # Extract heading and SOG from message type
        heading: Optional[float] = None
        speed: Optional[float] = None
        nav_status: Optional[str] = None

        if msg_type == "PositionReport":
            pr = msg_body.get("PositionReport", {})
            raw_heading = pr.get("TrueHeading")
            if raw_heading is not None and 0 <= raw_heading <= 360:
                heading = float(raw_heading)
            elif pr.get("Cog") is not None and 0 <= pr.get("Cog") <= 360:
                heading = float(pr.get("Cog"))

            raw_sog = pr.get("Sog")
            if raw_sog is not None and raw_sog < 102.0:
                speed = round(float(raw_sog), 1)

            nav_code = pr.get("NavigationalStatus")
            status_map = {
                0: "Under way using engine",
                1: "At anchor",
                2: "Not under command",
                3: "Restricted manoeuvrability",
                4: "Constrained by her draught",
                5: "Moored",
                6: "Aground",
                7: "Engaged in fishing",
                8: "Under way sailing",
            }
            if nav_code in status_map:
                nav_status = status_map[nav_code]

        elif msg_type == "StandardClassBPositionReport":
            b_rep = msg_body.get("StandardClassBPositionReport", {})
            raw_cog = b_rep.get("Cog")
            if raw_cog is not None and 0 <= raw_cog <= 360:
                heading = float(raw_cog)
            raw_sog = b_rep.get("Sog")
            if raw_sog is not None and raw_sog < 102.0:
                speed = round(float(raw_sog), 1)

        source_ts = meta.get("time_utc") or receive_time

        return LiveMapObject(
            id=f"vessel-{mmsi}",
            type="vessel",
            source="aisstream",
            latitude=lat_f,
            longitude=lon_f,
            heading=heading,
            speed=speed,
            status=nav_status or "Under way",
            name=ship_name,
            identifier=str(mmsi),
            timestamp=source_ts,
            last_seen=receive_time,
            metadata={
                "mmsi": mmsi,
                "msg_type": msg_type,
                "provenance": "REAL",
            },
        )

    def _prune_stale_vessels(self) -> None:
        """Remove vessels older than retention limit to control memory."""
        # Keep the most recently updated items
        sorted_items = sorted(
            self._vessels.items(),
            key=lambda item: item[1].last_seen,
            reverse=True,
        )
        self._vessels = dict(sorted_items[:MAX_CACHED_VESSELS])
