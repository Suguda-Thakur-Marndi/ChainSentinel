"""Factories API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/factories (Protected, Viewer+: list factories with pagination, search, filter, sort)
- POST /api/v1/factories (Protected, OpsManager+: create factory within tenant)
- GET /api/v1/factories/{id} (Protected, Viewer+: get factory by ID with 404 masking)
- PATCH /api/v1/factories/{id} (Protected, OpsManager+: update factory)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.network_repositories import FACTORY_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    FactoryCreate,
    FactoryListResponse,
    FactoryResponse,
    FactoryUpdate,
)
from app.services.logistics_services import FactoryService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_factory_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> FactoryService:
    """Dependency injecting configured FactoryService."""
    return FactoryService(uow=uow, context=context)


@router.get(
    "",
    response_model=FactoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List factories",
    description="Retrieve a paginated list of factories within the authenticated tenant boundary.",
)
def list_factories(
    request: Request,
    params: PaginationParams = Depends(),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by operational status"),
    country: Optional[str] = Query(None, description="Filter by country"),
    search: Optional[str] = Query(None, description="Substring search across name, code, country, or city"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: FactoryService = Depends(get_factory_service),
) -> FactoryListResponse:
    """List factories with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in FACTORY_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(FACTORY_FILTER_ALLOWLIST.keys()))

    return service.list_factories(
        params=params,
        status=status_filter,
        country=country,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=FactoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create factory",
    description="Create a new factory within the authenticated organization. Requires OpsManager role or higher.",
)
def create_factory(
    body: FactoryCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: FactoryService = Depends(get_factory_service),
) -> FactoryResponse:
    """Create a new factory within the authenticated organization partition."""
    return service.create_factory(body)


@router.get(
    "/{id}",
    response_model=FactoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get factory by ID",
    description="Retrieve a single factory by ID. Returns 404 if missing or belonging to another organization.",
)
def get_factory(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: FactoryService = Depends(get_factory_service),
) -> FactoryResponse:
    """Retrieve an individual factory by ID enforcing tenant isolation."""
    return service.get_factory(id)


@router.patch(
    "/{id}",
    response_model=FactoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update factory",
    description="Update an existing factory's details. Requires OpsManager role or higher.",
)
def update_factory(
    id: str,
    body: FactoryUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: FactoryService = Depends(get_factory_service),
) -> FactoryResponse:
    """Update an existing factory within the authenticated organization partition."""
    return service.update_factory(id, body)
