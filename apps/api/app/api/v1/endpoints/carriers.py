"""Carriers API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/carriers (Protected, Viewer+: list carriers with pagination, search, filter, sort)
- POST /api/v1/carriers (Protected, OpsManager+: create carrier within tenant)
- GET /api/v1/carriers/{id} (Protected, Viewer+: get carrier by ID with 404 masking)
- PATCH /api/v1/carriers/{id} (Protected, OpsManager+: update carrier)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.network_repositories import CARRIER_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    CarrierCreate,
    CarrierListResponse,
    CarrierResponse,
    CarrierUpdate,
)
from app.services.logistics_services import CarrierService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_carrier_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> CarrierService:
    """Dependency injecting configured CarrierService."""
    return CarrierService(uow=uow, context=context)


@router.get(
    "",
    response_model=CarrierListResponse,
    status_code=status.HTTP_200_OK,
    summary="List carriers",
    description="Retrieve a paginated list of freight and transport carriers within the authenticated tenant boundary.",
)
def list_carriers(
    request: Request,
    params: PaginationParams = Depends(),
    mode: Optional[str] = Query(None, description="Filter by transport mode (OCEAN, AIR, ROAD, RAIL)"),
    search: Optional[str] = Query(None, description="Substring search across carrier name or code"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, on_time_reliability, -on_time_reliability)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: CarrierService = Depends(get_carrier_service),
) -> CarrierListResponse:
    """List carriers with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in CARRIER_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(CARRIER_FILTER_ALLOWLIST.keys()))

    return service.list_carriers(
        params=params,
        mode=mode,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=CarrierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create carrier",
    description="Create a new freight carrier within the authenticated organization. Requires OpsManager role or higher.",
)
def create_carrier(
    body: CarrierCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: CarrierService = Depends(get_carrier_service),
) -> CarrierResponse:
    """Create a new carrier within the authenticated organization partition."""
    return service.create_carrier(body)


@router.get(
    "/{id}",
    response_model=CarrierResponse,
    status_code=status.HTTP_200_OK,
    summary="Get carrier by ID",
    description="Retrieve a single carrier by ID. Returns 404 if missing or belonging to another organization.",
)
def get_carrier(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: CarrierService = Depends(get_carrier_service),
) -> CarrierResponse:
    """Retrieve an individual carrier by ID enforcing tenant isolation."""
    return service.get_carrier(id)


@router.patch(
    "/{id}",
    response_model=CarrierResponse,
    status_code=status.HTTP_200_OK,
    summary="Update carrier",
    description="Update an existing carrier's details. Requires OpsManager role or higher.",
)
def update_carrier(
    id: str,
    body: CarrierUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: CarrierService = Depends(get_carrier_service),
) -> CarrierResponse:
    """Update an existing carrier within the authenticated organization partition."""
    return service.update_carrier(id, body)
