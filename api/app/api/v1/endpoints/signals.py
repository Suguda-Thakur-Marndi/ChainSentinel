"""Signals API endpoints for RiskWise (Telemetry Ingestion & Normalized Signals).

Endpoints:
- GET /api/v1/signals (Protected, Viewer+: list normalized risk signals with filtering and pagination)
- GET /api/v1/signals/{id_or_signal_id} (Protected, Viewer+: retrieve a single signal)
"""
from __future__ import annotations

import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.db.unit_of_work import UnitOfWork, get_uow
from app.schemas.common import PaginationMeta, PaginationParams
from app.schemas.signal import SignalCreate, SignalListResponse, SignalResponse

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")


@router.get(
    "",
    response_model=SignalListResponse,
    status_code=status.HTTP_200_OK,
    summary="List normalized risk signals",
    description="Retrieve paginated normalized risk signals from external telemetry ingestion.",
)
def list_signals(
    params: PaginationParams = Depends(),
    domain: Optional[str] = Query(None, description="Filter by domain (WEATHER, ROAD, OCEAN, AIR, RAIL, LOGISTICS)"),
    provider: Optional[str] = Query(None, description="Filter by provider (aisstream, opensky, openweather, tomtom)"),
    severity: Optional[str] = Query(None, description="Filter by severity (LOW, MEDIUM, HIGH, CRITICAL)"),
    search: Optional[str] = Query(None, description="Search across title, location, provider, summary"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. detected_at, -detected_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> SignalListResponse:
    """Retrieve normalized signals with pagination, search, and filtering."""
    items, total = uow.signals.list_signals(
        org_id=context.organization_id,
        domain=domain,
        provider=provider,
        severity=severity,
        search=search,
        sort_param=sort,
        page=params.page,
        limit=params.limit,
    )

    pages = math.ceil(total / params.limit) if total > 0 else 0
    pagination = PaginationMeta(
        total=total,
        page=params.page,
        limit=params.limit,
        pages=pages,
    )

    return SignalListResponse(
        items=[SignalResponse.model_validate(item) for item in items],
        pagination=pagination,
    )


@router.get(
    "/{signal_id}",
    response_model=SignalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get signal by ID",
    description="Retrieve a single normalized signal by internal ID or signal_id.",
)
def get_signal(
    signal_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> SignalResponse:
    """Retrieve a single normalized signal."""
    # First attempt lookup by signal_id fingerprint
    sig = uow.signals.get_by_signal_id(signal_id, org_id=context.organization_id)
    if not sig:
        # Fallback lookup by primary key id
        sig = uow.signals.get(signal_id, org_id=context.organization_id)

    if not sig:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SIGNAL_NOT_FOUND", "message": f"Signal '{signal_id}' not found."},
        )

    return SignalResponse.model_validate(sig)


WRITE_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")


@router.post(
    "",
    response_model=SignalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest normalized risk signal",
    description="Persist a normalized telemetry risk signal directly into the signals repository.",
)
def create_signal(
    payload: SignalCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> SignalResponse:
    """Ingest or update a normalized risk signal."""
    import uuid
    from datetime import datetime, timezone

    data = payload.model_dump()
    if not data.get("signal_id"):
        data["signal_id"] = f"sig-{uuid.uuid4().hex[:12]}"
    if not data.get("detected_at"):
        data["detected_at"] = datetime.now(timezone.utc)
    data["org_id"] = context.organization_id

    sig, _ = uow.signals.upsert_signal(data, auto_commit=True)
    return SignalResponse.model_validate(sig)

