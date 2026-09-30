"""REST and WebSocket endpoints for RiskWise Live Geospatial Map."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.services.tracking import (
    LiveMapResponse,
    ProvidersHealthResponse,
    get_tracking_aggregator,
)

logger = logging.getLogger("riskwise.api.map")

router = APIRouter()


@router.get("/objects", response_model=LiveMapResponse, summary="Query live map objects")
async def get_map_objects(
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

    return await aggregator.get_objects(
        types=parsed_types,
        source=source,
        bbox=parsed_bbox,
        since=since,
    )


@router.get("/providers/health", response_model=ProvidersHealthResponse, summary="Telemetry provider health metrics")
async def get_providers_health() -> ProvidersHealthResponse:
    """Check connectivity, latency, and transponder record counts across all configured telemetry providers."""
    aggregator = get_tracking_aggregator()
    return await aggregator.get_providers_health()


@router.websocket("/live")
async def websocket_map_live(websocket: WebSocket):
    """Real-time bi-directional telemetry stream.

    Pushes:
    - Initial state snapshot on connect
    - 'position_update' frames as vessels move and weather updates
    - 'remove' frames when transponders age out
    - 'provider_status' notifications
    """
    await websocket.accept()
    aggregator = get_tracking_aggregator()
    await aggregator.register_client(websocket)

    try:
        # 1. Send initial state snapshot
        initial_data = await aggregator.get_objects()
        await websocket.send_text(
            json.dumps({
                "event": "initial_snapshot",
                "objects": [obj.model_dump() for obj in initial_data.items],
                "sources": initial_data.sources,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        )

        # 2. Keep connection open, handle client heartbeats/pings
        while True:
            # Wait for client messages (e.g. ping, filter adjustments)
            data = await websocket.receive_text()
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
