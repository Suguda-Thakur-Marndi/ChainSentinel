"""Shipment Events API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Shipment Events represent append-only telemetry milestones (AIS vessel pings, gate-in, departures).
Strictly immutable. Scoped hierarchically through parent shipment's organization ownership.

Endpoints:
- GET /api/v1/shipment-events (Protected, Viewer+: list shipment events with pagination, search, filter, sort)
- POST /api/v1/shipment-events (Protected, OpsManager+: record new telemetry event)
- GET /api/v1/shipment-events/{id} (Protected, Viewer+: get single telemetry event by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.shipment import EVENT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.logistics import (
    ShipmentEventCreate,
    ShipmentEventListResponse,
    ShipmentEventResponse,
)
from app.services.logistics_services import ShipmentEventService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_shipment_event_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ShipmentEventService:
    """Dependency injecting configured ShipmentEventService."""
    return ShipmentEventService(uow=uow, context=context)


@router.get(
    "",
    response_model=ShipmentEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List shipment events",
    description="Retrieve a paginated list of telemetry events for tenant shipments.",
)
def list_shipment_events(
    request: Request,
    params: PaginationParams = Depends(),
    shipment_id: Optional[str] = Query(None, description="Filter by parent shipment ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    search: Optional[str] = Query(None, description="Substring search across event_type, source_type, status"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. timestamp, -timestamp, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ShipmentEventService = Depends(get_shipment_event_service),
) -> ShipmentEventListResponse:
    """List shipment events with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in EVENT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(EVENT_FILTER_ALLOWLIST.keys()))

    return service.list_events(
        params=params,
        shipment_id=shipment_id,
        event_type=event_type,
        source_type=source_type,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=ShipmentEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create shipment event",
    description="Record an append-only milestone telemetry event for a tenant shipment. Requires OpsManager role or higher.",
)
def create_shipment_event(
    body: ShipmentEventCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: ShipmentEventService = Depends(get_shipment_event_service),
) -> ShipmentEventResponse:
    """Append a new milestone telemetry event to a shipment owned by the authenticated tenant."""
    return service.create_event(body)


@router.get(
    "/{id}",
    response_model=ShipmentEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get shipment event by ID",
    description="Retrieve an individual shipment event by ID ensuring parent shipment belongs to the tenant.",
)
def get_shipment_event(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ShipmentEventService = Depends(get_shipment_event_service),
) -> ShipmentEventResponse:
    """Retrieve a single shipment event enforcing parent shipment tenant isolation."""
    return service.get_event(id)
