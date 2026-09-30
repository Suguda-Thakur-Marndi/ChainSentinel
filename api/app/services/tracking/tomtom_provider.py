"""TomTom live road freight, border & port gate traffic incident provider.

Fetches real-time highway congestion, road closures, and port gate incidents
using the TomTom Incident Details REST API.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.tomtom")

# Monitored port freight clusters and logistics gate corridors
FREIGHT_CORRIDORS = [
    # Rotterdam Gateway (Europe's largest container port)
    {"name": "Port of Rotterdam Gate Corridor", "bbox": "4.20,51.85,4.60,52.05"},
    # Singapore Tuas / Jurong Logistics Corridor
    {"name": "Singapore Tuas Logistics Corridor", "bbox": "103.60,1.25,103.85,1.40"},
    # Los Angeles / Long Beach Harbor Corridor
    {"name": "LA/Long Beach Harbor Corridor", "bbox": "-118.30,33.70,-118.15,33.85"},
]


class TomTomTrackingProvider(TrackingProvider):
    """TomTom live traffic and freight delay provider."""

    name: str = "tomtom"
    purpose: str = "Port Gate & Highway Freight Traffic"

    def __init__(
        self,
        api_key: Optional[str] = None,
        poll_interval_seconds: int = 300,
        on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None,
    ):
        super().__init__(on_update=on_update)
        self._api_key = api_key or os.getenv("TOMTOM_API_KEY", "")
        self._poll_interval = poll_interval_seconds
        self._incidents: Dict[str, LiveMapObject] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        if self._api_key:
            self._status = ProviderHealthStatus.CONNECTED
        else:
            self._status = ProviderHealthStatus.UNCONFIGURED

        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None

    async def start(self) -> None:
        """Start TomTom traffic monitoring."""
        if not self._api_key:
            self._status = ProviderHealthStatus.UNCONFIGURED
            self._last_error = "TOMTOM_API_KEY not configured"
            return

        self._is_running = True
        self._task = asyncio.create_task(self._poll_loop(), name="tomtom_poll_worker")
        logger.info("[TomTomProvider] Background freight monitoring started.")

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

    async def health_check(self) -> ProviderHealth:
        """Return runtime health status."""
        async with self._lock:
            count = len(self._incidents)
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
        """Return active traffic incidents."""
        async with self._lock:
            return list(self._incidents.values())

    async def _poll_loop(self) -> None:
        """Periodic poll of traffic corridors."""
        while self._is_running:
            await self._fetch_incidents()
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _fetch_incidents(self) -> None:
        """Fetch incidents from TomTom REST API."""
        start_time = time.monotonic()
        updated: List[LiveMapObject] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                for corridor in FREIGHT_CORRIDORS:
                    if not self._is_running:
                        break
                    # TomTom traffic incidentDetails endpoint
                    # bbox format: minLon,minLat,maxLon,maxLat
                    url = (
                        f"https://api.tomtom.com/traffic/services/5/incidentDetails"
                        f"?key={self._api_key}&bbox={corridor['bbox']}"
                        f"&fields={{incidents{{type,geometry{{type,coordinates}},properties{{iconCategory,magnitudeOfDelay,events{{description}}}}}}}}"
                    )
                    try:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            data = resp.json()
                            raw_incidents = data.get("incidents", [])
                            for inc in raw_incidents[:15]:  # Take top 15 significant incidents per corridor
                                obj = self._parse_incident(inc, corridor["name"])
                                if obj:
                                    updated.append(obj)
                        elif resp.status_code == 429:
                            self._status = ProviderHealthStatus.RATE_LIMITED
                            self._last_error = "TomTom rate limit reached"
                            break
                        else:
                            logger.debug(f"[TomTomProvider] HTTP {resp.status_code} on {corridor['name']}")
                    except Exception as corr_err:
                        logger.debug(f"[TomTomProvider] Corridor {corridor['name']} fetch error: {corr_err}")

                    await asyncio.sleep(0.2)

            self._latency_ms = round((time.monotonic() - start_time) * 1000, 2)
            if updated:
                now_iso = datetime.now(timezone.utc).isoformat()
                self._last_success = now_iso
                self._status = ProviderHealthStatus.CONNECTED
                self._last_error = None
                async with self._lock:
                    self._incidents = {obj.id: obj for obj in updated}

                if self._on_update:
                    try:
                        await self._on_update(updated)
                    except Exception as e:
                        logger.debug(f"[TomTomProvider] Callback error: {e}")

        except Exception as e:
            self._status = ProviderHealthStatus.ERROR
            self._last_error = f"{type(e).__name__}: {str(e)}"
            logger.warning(f"[TomTomProvider] Cycle failed: {e}")

    def _parse_incident(self, inc: Dict[str, Any], corridor_name: str) -> Optional[LiveMapObject]:
        """Convert TomTom incident dictionary into LiveMapObject."""
        geom = inc.get("geometry", {})
        props = inc.get("properties", {})

        coords = geom.get("coordinates")
        if not coords:
            return None

        # Coordinates can be [lon, lat] or [[lon, lat], ...]
        if isinstance(coords[0], (int, float)):
            lon, lat = float(coords[0]), float(coords[1])
        elif isinstance(coords[0], (list, tuple)) and len(coords[0]) >= 2:
            lon, lat = float(coords[0][0]), float(coords[0][1])
        else:
            return None

        events = props.get("events", [])
        desc = events[0].get("description", "Road freight delay") if events else "Congestion / Lane Block"
        magnitude = props.get("magnitudeOfDelay", 1)
        severity_map = {0: "LOW", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}
        severity = severity_map.get(magnitude, "MEDIUM")

        inc_id = hashlib.sha256(f"{corridor_name}_{lat}_{lon}_{desc}".encode()).hexdigest()[:12]
        now_iso = datetime.now(timezone.utc).isoformat()

        return LiveMapObject(
            id=f"incident-tomtom-{inc_id}",
            type="incident",
            source="tomtom",
            latitude=lat,
            longitude=lon,
            heading=None,
            speed=None,
            status=f"Delay Magnitude {magnitude}: {desc}",
            name=f"Traffic Incident ({corridor_name})",
            identifier=str(inc_id),
            timestamp=now_iso,
            last_seen=now_iso,
            metadata={
                "corridor": corridor_name,
                "description": desc,
                "magnitude": magnitude,
                "severity": severity,
                "provenance": "REAL",
            },
        )
