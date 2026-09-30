"""Project44 shipment and container logistics tracking provider.

Validates the configured Project44 sandbox/production environment against the
OAuth2 client credentials token endpoint. Handles authentication failure gracefully
without fabricating fake coordinates or shipments.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx
from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus

logger = logging.getLogger("riskwise.tracking.project44")

DEFAULT_P44_BASE_URL = "https://na12.api.sandbox.p-44.com"


class Project44TrackingProvider(TrackingProvider):
    """Project44 multi-modal logistics tracking provider."""

    name: str = "project44"
    purpose: str = "Multi-Modal Freight & Milestone Tracking"

    def __init__(
        self,
        base_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        env_name: Optional[str] = None,
        on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None,
    ):
        super().__init__(on_update=on_update)
        self._base_url = (base_url or os.getenv("PROJECT44_BASE_URL") or DEFAULT_P44_BASE_URL).rstrip("/")
        self._client_id = client_id if client_id is not None else os.getenv("PROJECT44_CLIENT_ID", "")
        self._client_secret = client_secret if client_secret is not None else os.getenv("PROJECT44_CLIENT_SECRET", "")
        self._env_name = env_name or os.getenv("PROJECT44_ENV", "sandbox")
        self._shipments: Dict[str, LiveMapObject] = {}
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        self._status = ProviderHealthStatus.UNCONFIGURED
        self._reason: Optional[str] = None
        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._latency_ms: Optional[float] = None

        if not self._client_id or not self._client_secret:
            self._status = ProviderHealthStatus.UNCONFIGURED
            self._reason = "Project44 client credentials not configured"
        else:
            self._status = ProviderHealthStatus.DISCONNECTED

    async def start(self) -> None:
        """Start provider check and polling task."""
        if not self._client_id or not self._client_secret:
            self._status = ProviderHealthStatus.UNCONFIGURED
            self._reason = "Project44 client credentials not configured"
            return

        self._is_running = True
        # Perform initial probe
        await self._probe_api()

    async def stop(self) -> None:
        """Stop provider background task."""
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
            count = len(self._shipments)
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
        """Return real tracked shipments."""
        async with self._lock:
            return list(self._shipments.values())

    async def _probe_api(self) -> None:
        """Verify credentials against the Project44 OAuth2 token endpoint."""
        token_url = f"{self._base_url}/api/v4/oauth2/token"
        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                self._latency_ms = round((time.monotonic() - start_time) * 1000, 2)
                if resp.status_code == 200:
                    self._status = ProviderHealthStatus.CONNECTED
                    self._last_success = datetime.now(timezone.utc).isoformat()
                    self._last_error = None
                    self._reason = None
                    logger.info("[Project44] OAuth2 authentication successful.")
                else:
                    self._status = ProviderHealthStatus.ERROR
                    err_msg = f"HTTP {resp.status_code}: client ID format invalid or unauthorized in {self._env_name}"
                    self._last_error = err_msg
                    self._reason = f"Project44 sandbox client credentials rejected ({err_msg})"
                    logger.warning(f"[Project44] Auth failed: {self._reason}")
        except Exception as e:
            self._status = ProviderHealthStatus.ERROR
            self._last_error = f"{type(e).__name__}: {str(e)}"
            self._reason = self._last_error
            logger.warning(f"[Project44] Probe failed: {e}")
