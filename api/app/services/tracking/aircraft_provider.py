"""Aircraft live tracking provider interface.

Adheres strictly to the invariant:
- If a real aircraft telemetry provider (such as OpenSky Network with credentials) is configured,
  polls real state vectors.
- If no aircraft provider credentials are configured, reports unavailable with exact reason
  and returns ZERO objects.
- NEVER manufactures or fabricates aircraft.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from typing import Callable, Coroutine, Dict, List, Optional

import httpx
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.aircraft")


class AircraftTrackingProvider(TrackingProvider):
    """Aviation telemetry provider supporting OpenSky Network with zero fabrication."""

    name: str = "aircraft"
    purpose: str = "Aviation Cargo & Transponder Telemetry"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        poll_interval_seconds: int = 60,
        on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None,
    ):
        super().__init__(on_update=on_update)
        self._client_id = client_id or os.getenv("OPENSKY_CLIENT_ID") or os.getenv("OPENSKY_USERNAME")
        self._client_secret = client_secret or os.getenv("OPENSKY_CLIENT_SECRET") or os.getenv("OPENSKY_PASSWORD")
        self._poll_interval = poll_interval_seconds
        self._aircraft: Dict[str, LiveMapObject] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._adapter: Optional[Any] = None

        if self._client_id and self._client_secret:
            from app.integrations.providers.opensky import OpenSkyAdapter
            self._adapter = OpenSkyAdapter(client_id=self._client_id, secret=self._client_secret)
            self._status = ProviderHealthStatus.DISCONNECTED
            self._reason = None
        else:
            self._status = ProviderHealthStatus.UNAVAILABLE
            self._reason = "No aircraft telemetry provider configured"

        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None

    async def start(self) -> None:
        """Start polling if configured."""
        if not self._client_id or not self._client_secret:
            self._status = ProviderHealthStatus.UNAVAILABLE
            self._reason = "No aircraft telemetry provider configured"
            logger.info("[AircraftProvider] Aircraft telemetry provider is not configured.")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._poll_loop(), name="aircraft_poll_worker")
        logger.info("[AircraftProvider] Background polling worker started.")

    async def stop(self) -> None:
        """Stop background worker."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._adapter:
            try:
                self._adapter.close()
            except Exception:
                pass
        logger.info("[AircraftProvider] Background worker stopped.")

    def _fetch_aircraft_sync(self) -> tuple[List[LiveMapObject], float]:
        """Synchronously invoke OpenSkyAdapter and normalize state vectors into LiveMapObjects."""
        import time
        t0 = time.perf_counter()
        if not self._adapter:
            return [], 0.0

        batch = self._adapter.fetch(extended=True)
        latency = (time.perf_counter() - t0) * 1000.0

        now_utc = datetime.now(timezone.utc)
        objects: List[LiveMapObject] = []
        for evt in batch.events:
            p = evt.raw_payload
            lat = p.get("latitude")
            lon = p.get("longitude")
            if lat is None or lon is None:
                continue
            if abs(lat) < 1e-6 and abs(lon) < 1e-6:
                continue
            icao = p.get("icao24")
            if not icao:
                continue

            callsign = p.get("callsign") or f"ICAO-{icao.upper()}"
            speed_val = p.get("velocity")
            speed_knots = round(speed_val * 1.94384, 1) if speed_val is not None else None

            obs_ts = evt.source_timestamp.isoformat() if evt.source_timestamp else now_utc.isoformat()

            try:
                obj = LiveMapObject(
                    id=f"aircraft-{icao.lower()}",
                    type="aircraft",
                    source="opensky",
                    latitude=round(float(lat), 6),
                    longitude=round(float(lon), 6),
                    heading=p.get("true_track"),
                    speed=speed_knots,
                    status="airborne" if not p.get("on_ground") else "ground",
                    name=callsign.strip(),
                    identifier=icao.lower(),
                    timestamp=obs_ts,
                    last_seen=now_utc.isoformat(),
                    metadata={
                        "altitude_m": p.get("baro_altitude"),
                        "geo_altitude_m": p.get("geo_altitude"),
                        "origin_country": p.get("origin_country"),
                        "vertical_rate": p.get("vertical_rate"),
                        "squawk": p.get("squawk"),
                        "on_ground": p.get("on_ground", False),
                        "category": p.get("category"),
                    },
                )
                objects.append(obj)
            except Exception:
                continue

        return objects, latency

    async def _poll_loop(self) -> None:
        """Periodic polling of real OpenSky state vectors."""
        while self._is_running:
            try:
                objects, latency = await asyncio.to_thread(self._fetch_aircraft_sync)
                async with self._lock:
                    self._aircraft = {obj.id: obj for obj in objects}
                    self._status = ProviderHealthStatus.CONNECTED
                    self._last_success = datetime.now(timezone.utc).isoformat()
                    self._last_error = None
                    self._latency_ms = round(latency, 2)
                    self._reason = None

                if self._on_update and objects:
                    await self._on_update(objects)

                logger.info(
                    "[AircraftProvider] Polled %d live aircraft state vectors (latency: %.1fms).",
                    len(objects),
                    latency,
                )
            except Exception as exc:
                logger.warning("[AircraftProvider] Polling failure: %s", exc)
                async with self._lock:
                    self._status = ProviderHealthStatus.ERROR
                    self._last_error = str(exc)
                    self._reason = f"OpenSky polling error: {str(exc)}"

            await asyncio.sleep(self._poll_interval)

    async def health_check(self) -> ProviderHealth:
        """Return runtime health status."""
        async with self._lock:
            count = len(self._aircraft)
            status = self._status
            last_success = self._last_success
            last_error = self._last_error
            latency_ms = self._latency_ms
            reason = self._reason

        if status == ProviderHealthStatus.DISCONNECTED and self._adapter:
            try:
                h_res = await asyncio.to_thread(self._adapter.health_check)
                from app.integrations.base import ProviderHealthStatus as InStatus
                if h_res.status == InStatus.HEALTHY:
                    status = ProviderHealthStatus.CONNECTED
                    reason = None
                elif h_res.status == InStatus.UNHEALTHY:
                    status = ProviderHealthStatus.ERROR
                    reason = h_res.message
                latency_ms = h_res.latency_ms
            except Exception as e:
                status = ProviderHealthStatus.ERROR
                reason = str(e)

        return ProviderHealth(
            name=self.name,
            purpose=self.purpose,
            status=status,
            last_success=last_success,
            last_error=last_error,
            latency_ms=latency_ms,
            objects=count,
            reason=reason or last_error,
        )

    async def get_objects(self) -> List[LiveMapObject]:
        """Return active aircraft objects (empty if unconfigured, no fake planes)."""
        async with self._lock:
            return list(self._aircraft.values())
