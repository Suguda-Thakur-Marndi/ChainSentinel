"""Warehouses API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/warehouses (Protected, Viewer+: list warehouses with pagination, search, filter, sort)
- POST /api/v1/warehouses (Protected, OpsManager+: create warehouse within tenant)
- GET /api/v1/warehouses/{id} (Protected, Viewer+: get warehouse by ID with 404 masking)
- PATCH /api/v1/warehouses/{id} (Protected, OpsManager+: update warehouse)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.network_repositories import WAREHOUSE_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    WarehouseCreate,
    WarehouseListResponse,
    WarehouseResponse,
    WarehouseUpdate,
)
from app.services.logistics_services import WarehouseService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_warehouse_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> WarehouseService:
    """Dependency injecting configured WarehouseService."""
    return WarehouseService(uow=uow, context=context)


@router.get(
    "",
    response_model=WarehouseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List warehouses",
    description="Retrieve a paginated list of warehouses within the authenticated tenant boundary.",
)
def list_warehouses(
    request: Request,
    params: PaginationParams = Depends(),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by operational status"),
    country: Optional[str] = Query(None, description="Filter by country"),
    search: Optional[str] = Query(None, description="Substring search across name, code, country, or city"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseListResponse:
    """List warehouses with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in WAREHOUSE_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(WAREHOUSE_FILTER_ALLOWLIST.keys()))

    return service.list_warehouses(
        params=params,
        status=status_filter,
        country=country,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create warehouse",
    description="Create a new warehouse with capacity validation. Requires OpsManager role or higher.",
)
def create_warehouse(
    body: WarehouseCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """Create a new warehouse within the authenticated organization partition."""
    return service.create_warehouse(body)


@router.get(
    "/{id}",
    response_model=WarehouseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get warehouse by ID",
    description="Retrieve a single warehouse by ID. Returns 404 if missing or belonging to another organization.",
)
def get_warehouse(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """Retrieve an individual warehouse by ID enforcing tenant isolation."""
    return service.get_warehouse(id)


@router.patch(
    "/{id}",
    response_model=WarehouseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update warehouse",
    description="Update an existing warehouse's details with capacity validation. Requires OpsManager role or higher.",
)
def update_warehouse(
    id: str,
    body: WarehouseUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """Update an existing warehouse within the authenticated organization partition."""
    return service.update_warehouse(id, body)
