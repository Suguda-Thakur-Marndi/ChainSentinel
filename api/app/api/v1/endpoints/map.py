"""REST and WebSocket endpoints for RiskWise Live Geospatial Map."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response, WebSocket, WebSocketDisconnect, status

from app.core.config import settings
from app.services.session_service import get_session_service
from app.services.tracking import (
    LiveMapResponse,
    ProvidersHealthResponse,
    get_tracking_aggregator,
)

logger = logging.getLogger("riskwise.api.map")

router = APIRouter()


@router.get("/objects", response_model=LiveMapResponse, summary="Query live map objects")
async def get_map_objects(
    response: Response,
    types: Optional[str] = Query(None, description="Comma-separated list of types: vessel,aircraft,shipment,weather,incident,port"),
    source: Optional[str] = Query(None, description="Filter by telemetry source (e.g. aisstream, openweather)"),
    bbox: Optional[str] = Query(None, description="Bounding box: minLon,minLat,maxLon,maxLat"),
    since: Optional[str] = Query(None, description="ISO-8601 timestamp for incremental telemetry fetch"),
) -> LiveMapResponse:
    """Retrieve normalized geospatial telemetry objects from active providers.

    All coordinates undergo strict WGS84 boundary checks. Zero synthetic/fabricated data.
    """
    aggregator = get_tracking_aggregator()

    parsed_types: Optional[List[str]] = None
    if types:
        parsed_types = [t.strip().lower() for t in types.split(",") if t.strip()]

    parsed_bbox: Optional[List[float]] = None
    if bbox:
        try:
            parts = [float(p.strip()) for p in bbox.split(",")]
            if len(parts) == 4:
                parsed_bbox = parts
        except ValueError:
            parsed_bbox = None

    result = await aggregator.get_objects(
        types=parsed_types,
        source=source,
        bbox=parsed_bbox,
        since=since,
    )

    # Determine aggregated data source provenance
    has_live = any(s.get("is_live", False) for s in result.sources.values())
    if has_live:
        response.headers["X-Data-Source"] = "live"
    elif result.total_count > 0:
        response.headers["X-Data-Source"] = "cached"
    else:
        response.headers["X-Data-Source"] = "unavailable"

    return result


@router.get("/providers/health", response_model=ProvidersHealthResponse, summary="Telemetry provider health metrics")
async def get_providers_health() -> ProvidersHealthResponse:
    """Check connectivity, latency, and transponder record counts across all configured telemetry providers."""
    aggregator = get_tracking_aggregator()
    return await aggregator.get_providers_health()


@router.websocket("/live")
async def websocket_map_live(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="Optional session token for authentication"),
):
    """Real-time bi-directional telemetry stream.

    Pushes:
    - Initial state snapshot on connect
    - 'position_update' frames as vessels move and weather updates
    - 'remove' frames when transponders age out
    - 'provider_status' notifications
    """
    # 1. Validate Origin header to prevent Cross-Site WebSocket Hijacking (CSWSH)
    origin = websocket.headers.get("origin")
    if origin:
        allowed_origins = set(settings.CORS_ORIGINS) if isinstance(settings.CORS_ORIGINS, list) else set()
        if settings.FRONTEND_URL:
            allowed_origins.add(settings.FRONTEND_URL.rstrip("/"))
        is_dev = settings.APP_ENV.lower() in ("development", "dev", "test", "testing")

        origin_clean = origin.rstrip("/")
        is_allowed = origin_clean in allowed_origins or any(
            origin_clean.startswith(allowed.rstrip("/")) for allowed in allowed_origins
        )
        if is_dev and ("localhost" in origin_clean or "127.0.0.1" in origin_clean):
            is_allowed = True

        if not is_allowed:
            logger.warning(f"[MapWebSocket] Rejected connection from unauthorized origin: {origin}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized origin")
            return

    # 2. Authenticate session
    session_id = websocket.cookies.get(settings.SESSION_COOKIE_NAME) or token or websocket.query_params.get("session_id")
    is_prod = settings.APP_ENV.lower() in ("production", "prod")
    session = None
    if session_id:
        session_svc = get_session_service()
        session = await session_svc.get_session(session_id)

    if is_prod and not session:
        logger.warning("[MapWebSocket] Rejected unauthenticated connection in production.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        return

    await websocket.accept()
    aggregator = get_tracking_aggregator()
    await aggregator.register_client(websocket)

    try:
        # Send initial state snapshot
        initial_data = await aggregator.get_objects()
        await websocket.send_text(
            json.dumps({
                "event": "initial_snapshot",
                "objects": [obj.model_dump() for obj in initial_data.items],
                "sources": initial_data.sources,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        )

        # Keep connection open, handle client heartbeats/pings with size bounds
        while True:
            data = await websocket.receive_text()
            if len(data) > 4096:
                logger.warning(f"[MapWebSocket] Client sent oversized frame ({len(data)} bytes). Closing.")
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG, reason="Message too large")
                break
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_text(json.dumps({"event": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}))
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.debug("[MapWebSocket] Client disconnected.")
    except Exception as e:
        logger.debug(f"[MapWebSocket] WebSocket error: {e}")
    finally:
        await aggregator.unregister_client(websocket)
