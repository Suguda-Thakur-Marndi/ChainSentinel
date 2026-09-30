"""Mobility Database GTFS/Transit tracking provider.

Validates the configured Mobility Database credentials. When tokens are invalid or expired,
truthfully reports the authentication error and provides zero synthetic/fabricated transit records.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import time
from typing import Callable, Coroutine, Dict, List, Optional

import httpx
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.mobility")


class MobilityTrackingProvider(TrackingProvider):
    """Mobility Database GTFS transit provider."""

    name: str = "mobility"
    purpose: str = "Public Transit & Rail Network Telemetry"

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None,
    ):
        super().__init__(on_update=on_update)
        self._api_key = api_key or os.getenv("MOBILITY_DATABASE_API_KEY", "")
        self._access_token = access_token or os.getenv("MOBILITY_DATABASE_ACCESS_TOKEN", "")
        self._objects: Dict[str, LiveMapObject] = {}
        self._lock = asyncio.Lock()

        self._status = ProviderHealthStatus.UNCONFIGURED
        self._reason: Optional[str] = None
        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None

    async def start(self) -> None:
        """Start provider probe."""
        if not self._api_key and not self._access_token:
            self._status = ProviderHealthStatus.UNCONFIGURED
            self._reason = "Mobility Database credentials not configured"
            return

        self._is_running = True
        await self._probe()

    async def stop(self) -> None:
        """Stop provider."""
        self._is_running = False

    async def health_check(self) -> ProviderHealth:
        """Return runtime health status."""
        async with self._lock:
            count = len(self._objects)
        return ProviderHealth(
            name=self.name,
            purpose=self.purpose,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            latency_ms=self._latency_ms,
            objects=count,
            reason=self._reason or self._last_error,
        )

    async def get_objects(self) -> List[LiveMapObject]:
        """Return active transit objects (empty if unauthorized, no fake transit)."""
        async with self._lock:
            return list(self._objects.values())

    async def _probe(self) -> None:
        """Probe Mobility Database API endpoint."""
        url = "https://api.mobilitydatabase.org/v1/feeds?limit=2"
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        elif self._api_key:
            headers["x-api-key"] = self._api_key

        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(url, headers=headers)
                self._latency_ms = round((time.monotonic() - start_time) * 1000, 2)
                if res.status_code == 200:
                    self._status = ProviderHealthStatus.CONNECTED
                    self._last_success = datetime.now(timezone.utc).isoformat()
                    self._last_error = None
                    self._reason = None
                else:
                    self._status = ProviderHealthStatus.ERROR
                    err_msg = f"HTTP {res.status_code}: GCIP token invalid or expired"
                    self._last_error = err_msg
                    self._reason = f"Mobility Database token rejected ({err_msg})"
                    logger.warning(f"[MobilityProvider] Probe failed: {self._reason}")
        except Exception as e:
            self._status = ProviderHealthStatus.ERROR
            self._last_error = f"{type(e).__name__}: {str(e)}"
            self._reason = self._last_error
