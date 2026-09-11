"""Shipments API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/shipments (Protected, Viewer+: list shipments with pagination, search, filter, sort)
- POST /api/v1/shipments (Protected, OpsManager+: create shipment within tenant)
- GET /api/v1/shipments/{id} (Protected, Viewer+: get shipment by ID with 404 masking)
- PATCH /api/v1/shipments/{id} (Protected, OpsManager+: update shipment)
- GET /api/v1/shipments/{id}/events (Protected, Viewer+: list telemetry events for this shipment)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.shipment import SHIPMENT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.logistics import (
    ShipmentCreate,
    ShipmentEventListResponse,
    ShipmentListResponse,
    ShipmentResponse,
    ShipmentUpdate,
)
from app.services.logistics_services import ShipmentEventService, ShipmentService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_shipment_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ShipmentService:
    """Dependency injecting configured ShipmentService."""
    return ShipmentService(uow=uow, context=context)


def get_shipment_event_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ShipmentEventService:
    """Dependency injecting configured ShipmentEventService."""
    return ShipmentEventService(uow=uow, context=context)


@router.get(
    "",
    response_model=ShipmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List shipments",
    description="Retrieve a paginated list of shipments within the authenticated tenant boundary.",
)
def list_shipments(
    request: Request,
    params: PaginationParams = Depends(),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by operational status"),
    mode: Optional[str] = Query(None, description="Filter by transport mode (OCEAN, AIR, ROAD, RAIL)"),
    carrier_id: Optional[str] = Query(None, description="Filter by carrier ID"),
    product_id: Optional[str] = Query(None, description="Filter by product ID"),
    data_provenance: Optional[str] = Query(None, description="Filter by provenance (REAL, SYNTHETIC, ESTIMATED)"),
    search: Optional[str] = Query(None, description="Substring search across tracking number, origin, destination"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. tracking_number, -tracking_number, eta)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentListResponse:
    """List shipments with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in SHIPMENT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(SHIPMENT_FILTER_ALLOWLIST.keys()))

    return service.list_shipments(
        params=params,
        status=status_filter,
        mode=mode,
        carrier_id=carrier_id,
        product_id=product_id,
        data_provenance=data_provenance,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create shipment",
    description="Create a new freight shipment consignment. Requires OpsManager role or higher.",
)
def create_shipment(
    body: ShipmentCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentResponse:
    """Create a new shipment within the authenticated organization partition."""
    return service.create_shipment(body)


@router.get(
    "/{id}",
    response_model=ShipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get shipment by ID",
    description="Retrieve a single shipment by ID. Returns 404 if missing or belonging to another organization.",
)
def get_shipment(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentResponse:
    """Retrieve an individual shipment by ID enforcing tenant isolation."""
    return service.get_shipment(id)


@router.patch(
    "/{id}",
    response_model=ShipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update shipment",
    description="Update an existing shipment's operational details or status. Requires OpsManager role or higher.",
)
def update_shipment(
    id: str,
    body: ShipmentUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentResponse:
    """Update an existing shipment within the authenticated organization partition."""
    return service.update_shipment(id, body)


@router.get(
    "/{id}/events",
    response_model=ShipmentEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List events for shipment",
    description="Retrieve all milestone telemetry events for a given shipment owned by the tenant.",
)
def list_shipment_events_for_shipment(
    id: str,
    params: PaginationParams = Depends(),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    source_type: Optional[str] = Query(None, description="Filter by source type"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. timestamp, -timestamp)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    event_service: ShipmentEventService = Depends(get_shipment_event_service),
) -> ShipmentEventListResponse:
    """Retrieve all chronological events associated with a shipment."""
    return event_service.list_events(
        params=params,
        shipment_id=id,
        event_type=event_type,
        source_type=source_type,
        sort_param=sort,
    )
