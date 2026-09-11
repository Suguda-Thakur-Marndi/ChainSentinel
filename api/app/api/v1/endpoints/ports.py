"""Ports API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Ports represent global reference catalog data (UN/LOCODE transit hubs, maritime terminals, airports).
Read-only to all authenticated tenants.

Endpoints:
- GET /api/v1/ports (Protected, Viewer+: list global ports with pagination, search, filter, sort)
- GET /api/v1/ports/{id} (Protected, Viewer+: get port by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.port import PORT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import PortListResponse, PortResponse
from app.services.logistics_services import PortService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_port_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> PortService:
    """Dependency injecting configured PortService."""
    return PortService(uow=uow, context=context)


@router.get(
    "",
    response_model=PortListResponse,
    status_code=status.HTTP_200_OK,
    summary="List ports",
    description="Retrieve a paginated list of global trade ports and transit terminals. Read-only reference catalog.",
)
def list_ports(
    request: Request,
    params: PaginationParams = Depends(),
    country: Optional[str] = Query(None, description="Filter by country code or name"),
    port_type: Optional[str] = Query(None, description="Filter by port type (SEA, AIR, INLAND)"),
    search: Optional[str] = Query(None, description="Substring search across port name, code, or country"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, congestion_score, -congestion_score)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: PortService = Depends(get_port_service),
) -> PortListResponse:
    """List global ports with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in PORT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(PORT_FILTER_ALLOWLIST.keys()))

    return service.list_ports(
        params=params,
        country=country,
        port_type=port_type,
        search=search,
        sort_param=sort,
    )


@router.get(
    "/{id}",
    response_model=PortResponse,
    status_code=status.HTTP_200_OK,
    summary="Get port by ID",
    description="Retrieve an individual global port reference by its ID.",
)
def get_port(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: PortService = Depends(get_port_service),
) -> PortResponse:
    """Retrieve an individual global port reference by ID."""
    return service.get_port(id)
