"""Live Map Aggregator & Real-Time Broadcast Subsystem.

Collects telemetry from registered tracking providers, performs strict coordinate
validation (-90 <= lat <= 90, -180 <= lon <= 180, rejects 0,0 null islands),
deduplicates, indexes in a high-speed spatial/temporal cache, and broadcasts
live positional frames to connected WebSocket clients.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket

from app.services.tracking.base import TrackingProvider
from app.services.tracking.models import (
    LiveMapObject,
    LiveMapResponse,
    ProviderHealth,
    ProviderHealthStatus,
    ProvidersHealthResponse,
)

logger = logging.getLogger("riskwise.tracking.aggregator")


class LiveMapAggregator:
    """Central orchestrator for live multi-source geospatial tracking."""

    def __init__(self):
        self._providers: Dict[str, TrackingProvider] = {}
        self._active_clients: Set[WebSocket] = set()
        self._cache_lock = asyncio.Lock()
        self._client_lock = asyncio.Lock()
        # In-memory primary cache: { id: LiveMapObject }
        self._objects_cache: Dict[str, LiveMapObject] = {}
        self._stale_cleanup_task: Optional[asyncio.Task] = None
        self._is_running = False

    def register_provider(self, provider: TrackingProvider) -> None:
        """Register a tracking provider."""
        self._providers[provider.name] = provider
        logger.info(f"[Aggregator] Registered tracking provider: {provider.name}")

    async def start(self) -> None:
        """Start all registered providers and the background cleanup worker."""
        if self._is_running:
            return
        self._is_running = True
        logger.info("[Aggregator] Starting tracking providers...")
        for name, provider in self._providers.items():
            try:
                await provider.start()
            except Exception as e:
                logger.error(f"[Aggregator] Failed to start provider {name}: {e}")

        self._stale_cleanup_task = asyncio.create_task(
            self._stale_evaluation_loop(), name="aggregator_stale_cleaner"
        )
        logger.info("[Aggregator] LiveMapAggregator fully initialized.")

    async def stop(self) -> None:
        """Stop all providers and background tasks."""
        self._is_running = False
        if self._stale_cleanup_task:
            self._stale_cleanup_task.cancel()
            try:
                await self._stale_cleanup_task
            except asyncio.CancelledError:
                pass
            self._stale_cleanup_task = None

        for name, provider in self._providers.items():
            try:
                await provider.stop()
            except Exception as e:
                logger.error(f"[Aggregator] Error stopping provider {name}: {e}")

        # Disconnect all active WebSocket clients gracefully
        async with self._client_lock:
            for ws in list(self._active_clients):
                try:
                    await ws.close(code=1001, reason="Server shutting down")
                except Exception:
                    pass
            self._active_clients.clear()
        logger.info("[Aggregator] LiveMapAggregator stopped.")

    async def handle_provider_update(self, new_objects: List[LiveMapObject]) -> None:
        """Callback invoked by providers when fresh telemetry frames arrive."""
        valid_objects: List[LiveMapObject] = []
        for obj in new_objects:
            # Validate coordinates strictly
            if not self._is_valid_coordinate(obj.latitude, obj.longitude):
                continue
            valid_objects.append(obj)

        if not valid_objects:
            return

        async with self._cache_lock:
            for obj in valid_objects:
                self._objects_cache[obj.id] = obj

            # Memory bound: cap active in-memory cache to 3,500 most recently seen objects
            if len(self._objects_cache) > 3500:
                sorted_keys = sorted(
                    self._objects_cache.keys(),
                    key=lambda k: self._objects_cache[k].last_seen,
                    reverse=True,
                )
                self._objects_cache = {k: self._objects_cache[k] for k in sorted_keys[:3000]}

        # Broadcast update to connected WebSockets in real time
        await self.broadcast({
            "event": "position_update",
            "objects": [obj.model_dump() for obj in valid_objects],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _is_valid_coordinate(self, lat: float, lon: float) -> bool:
        """Validate WGS84 range and reject 0,0 null islands."""
        if lat is None or lon is None:
            return False
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return False
        if abs(lat) < 1e-5 and abs(lon) < 1e-5:
            return False
        return True

    async def register_client(self, websocket: WebSocket) -> None:
        """Register a new active WebSocket subscriber."""
        async with self._client_lock:
            self._active_clients.add(websocket)
        logger.debug(f"[Aggregator] WebSocket client connected. Active: {len(self._active_clients)}")

    async def unregister_client(self, websocket: WebSocket) -> None:
        """Unregister a disconnected WebSocket subscriber."""
        async with self._client_lock:
            self._active_clients.discard(websocket)
        logger.debug(f"[Aggregator] WebSocket client disconnected. Active: {len(self._active_clients)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message payload to all connected clients."""
        async with self._client_lock:
            clients = list(self._active_clients)

        if not clients:
            return

        json_text = json.dumps(message)
        dead_clients = []
        for ws in clients:
            try:
                await ws.send_text(json_text)
            except Exception:
                dead_clients.append(ws)

        if dead_clients:
            async with self._client_lock:
                for ws in dead_clients:
                    self._active_clients.discard(ws)

    async def get_objects(
        self,
        types: Optional[List[str]] = None,
        source: Optional[str] = None,
        bbox: Optional[List[float]] = None,
        since: Optional[str] = None,
    ) -> LiveMapResponse:
        """Query normalized objects with type, source, spatial bounding box, and temporal filtering."""
        # 1. Collect from all providers
        all_objects: List[LiveMapObject] = []
        for provider in self._providers.values():
            try:
                items = await provider.get_objects()
                all_objects.extend(items)
            except Exception as e:
                logger.error(f"[Aggregator] Error querying {provider.name}: {e}")

        # Update cache with any fresh items
        async with self._cache_lock:
            for item in all_objects:
                self._objects_cache[item.id] = item
            current_cache = list(self._objects_cache.values())

        # 2. Filter by parameters
        filtered: List[LiveMapObject] = []
        for obj in current_cache:
            if types and obj.type.lower() not in [t.lower() for t in types]:
                continue
            if source and obj.source.lower() != source.lower():
                continue
            if bbox and len(bbox) == 4:
                # bbox format: [minLon, minLat, maxLon, maxLat]
                min_lon, min_lat, max_lon, max_lat = bbox
                if not (min_lat <= obj.latitude <= max_lat and min_lon <= obj.longitude <= max_lon):
                    continue
            if since:
                try:
                    obj_dt = datetime.fromisoformat(obj.timestamp.replace("Z", "+00:00"))
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                    if obj_dt < since_dt:
                        continue
                except Exception:
                    pass
            filtered.append(obj)

        # 3. Compile sources status dictionary
        sources_meta: Dict[str, Dict[str, Any]] = {}
        for name, provider in self._providers.items():
            health = await provider.health_check()
            is_live = health.status == ProviderHealthStatus.CONNECTED
            if is_live:
                data_source_badge = "LIVE TELEMETRY"
                freshness = "LIVE"
            elif health.objects > 0:
                data_source_badge = "CACHED TELEMETRY"
                freshness = "CACHED"
            elif "fixture" in name.lower() or "mock" in name.lower():
                data_source_badge = "SIMULATED FIXTURES"
                freshness = "SIMULATED"
            else:
                data_source_badge = "UNAVAILABLE"
                freshness = "UNAVAILABLE"

            sources_meta[name] = {
                "status": health.status.value,
                "purpose": health.purpose,
                "last_update": health.last_success,
                "object_count": health.objects,
                "reason": health.reason,
                "is_live": is_live,
                "data_source": data_source_badge,
                "freshness": freshness,
            }

        return LiveMapResponse(
            items=filtered,
            sources=sources_meta,
            total_count=len(filtered),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def get_providers_health(self) -> ProvidersHealthResponse:
        """Return runtime health status across all registered providers."""
        results: List[ProviderHealth] = []
        for provider in self._providers.values():
            try:
                h = await provider.health_check()
                results.append(h)
            except Exception as e:
                results.append(
                    ProviderHealth(
                        name=provider.name,
                        status=ProviderHealthStatus.ERROR,
                        reason=str(e),
                    )
                )
        return ProvidersHealthResponse(providers=results)

    async def _stale_evaluation_loop(self) -> None:
        """Background routine checking and broadcasting removal of stale entities (> 15m)."""
        while self._is_running:
            try:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)
                stale_ids = []
                async with self._cache_lock:
                    for obj_id, obj in list(self._objects_cache.items()):
                        # Only prune high-velocity transponders (vessels), preserve static ports/facilities
                        if obj.type not in ("vessel", "aircraft"):
                            continue
                        try:
                            last_seen_dt = datetime.fromisoformat(obj.last_seen.replace("Z", "+00:00"))
                            age_seconds = (now - last_seen_dt).total_seconds()
                            if age_seconds > 900:  # 15 minutes
                                stale_ids.append(obj_id)
                                del self._objects_cache[obj_id]
                        except Exception:
                            pass

                if stale_ids:
                    logger.debug(f"[Aggregator] Pruned {len(stale_ids)} stale transponders.")
                    await self.broadcast({
                        "event": "remove",
                        "ids": stale_ids,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[Aggregator] Stale cleaner error: {e}")
