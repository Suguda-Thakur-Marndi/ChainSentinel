"""Routes API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/routes (Protected, Viewer+: list routes with pagination, search, filter, sort)
- POST /api/v1/routes (Protected, OpsManager+: create route within tenant)
- GET /api/v1/routes/{id} (Protected, Viewer+: get route by ID with 404 masking)
- PATCH /api/v1/routes/{id} (Protected, OpsManager+: update route)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.network_repositories import ROUTE_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    RouteCreate,
    RouteListResponse,
    RouteResponse,
    RouteUpdate,
)
from app.services.logistics_services import RouteService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_route_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RouteService:
    """Dependency injecting configured RouteService."""
    return RouteService(uow=uow, context=context)


@router.get(
    "",
    response_model=RouteListResponse,
    status_code=status.HTTP_200_OK,
    summary="List routes",
    description="Retrieve a paginated list of shipping routes within the authenticated tenant boundary.",
)
def list_routes(
    request: Request,
    params: PaginationParams = Depends(),
    mode: Optional[str] = Query(None, description="Filter by transport mode (OCEAN, AIR, ROAD, RAIL)"),
    origin_facility_id: Optional[str] = Query(None, description="Filter by origin facility ID"),
    destination_facility_id: Optional[str] = Query(None, description="Filter by destination facility ID"),
    search: Optional[str] = Query(None, description="Substring search across route name or mode"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, distance_km, risk_score)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RouteService = Depends(get_route_service),
) -> RouteListResponse:
    """List routes with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in ROUTE_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(ROUTE_FILTER_ALLOWLIST.keys()))

    return service.list_routes(
        params=params,
        mode=mode,
        origin_facility_id=origin_facility_id,
        destination_facility_id=destination_facility_id,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=RouteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create route",
    description="Create a new shipping corridor/route. Requires OpsManager role or higher.",
)
def create_route(
    body: RouteCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: RouteService = Depends(get_route_service),
) -> RouteResponse:
    """Create a new route within the authenticated organization partition."""
    return service.create_route(body)


@router.get(
    "/{id}",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Get route by ID",
    description="Retrieve a single route by ID. Returns 404 if missing or belonging to another organization.",
)
def get_route(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RouteService = Depends(get_route_service),
) -> RouteResponse:
    """Retrieve an individual route by ID enforcing tenant isolation."""
    return service.get_route(id)


@router.patch(
    "/{id}",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update route",
    description="Update an existing route's details. Requires OpsManager role or higher.",
)
def update_route(
    id: str,
    body: RouteUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: RouteService = Depends(get_route_service),
) -> RouteResponse:
    """Update an existing route within the authenticated organization partition."""
    return service.update_route(id, body)
