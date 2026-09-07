"""Supplier API endpoints for RiskWise 2.0 (Phase 4 Step 3).

Endpoints:
- GET /api/v1/suppliers (Protected, Viewer+: list suppliers with pagination, search, filter, sort)
- POST /api/v1/suppliers (Protected, OpsManager+: create supplier within tenant)
- GET /api/v1/suppliers/{id} (Protected, Viewer+: get supplier by ID with 404 masking)
- PATCH /api/v1/suppliers/{id} (Protected, OpsManager+: update supplier)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.supplier import SUPPLIER_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    SupplierUpdate,
)
from app.services.supplier import SupplierService

router = APIRouter()

# RBAC permission groups per docs/core-api-contract.md §9.3
READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_supplier_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> SupplierService:
    """Dependency injecting configured SupplierService."""
    return SupplierService(uow=uow, context=context)


@router.get(
    "",
    response_model=SupplierListResponse,
    status_code=status.HTTP_200_OK,
    summary="List suppliers",
    description="Retrieve a paginated list of suppliers within the authenticated tenant boundary.",
)
def list_suppliers(
    request: Request,
    params: PaginationParams = Depends(),
    tier: Optional[str] = Query(None, description="Filter by criticality tier (LOW, MEDIUM, HIGH, CRITICAL)"),
    criticality: Optional[str] = Query(None, description="Filter by criticality (LOW, MEDIUM, HIGH, CRITICAL)"),
    country: Optional[str] = Query(None, description="Filter by country name or code"),
    search: Optional[str] = Query(None, description="Substring search across supplier name, code, or country"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: SupplierService = Depends(get_supplier_service),
) -> SupplierListResponse:
    """List suppliers with pagination, safe filters, sorting, and search."""
    # Enforce explicit filter allowlist
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in SUPPLIER_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(SUPPLIER_FILTER_ALLOWLIST.keys()))

    return service.list_suppliers(
        params=params,
        tier=tier,
        criticality=criticality,
        country=country,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create supplier",
    description="Create a new supplier within the authenticated organization. Requires OpsManager role or higher.",
)
def create_supplier(
    body: SupplierCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: SupplierService = Depends(get_supplier_service),
) -> SupplierResponse:
    """Create a new supplier within the authenticated organization partition."""
    return service.create_supplier(body)


@router.get(
    "/{id}",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Get supplier by ID",
    description="Retrieve a single supplier by ID. Returns 404 if missing or belonging to another organization.",
)
def get_supplier(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: SupplierService = Depends(get_supplier_service),
) -> SupplierResponse:
    """Retrieve an individual supplier by ID enforcing tenant isolation."""
    return service.get_supplier(id)


@router.patch(
    "/{id}",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Update supplier",
    description="Update an existing supplier's details. Requires OpsManager role or higher.",
)
def update_supplier(
    id: str,
    body: SupplierUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: SupplierService = Depends(get_supplier_service),
) -> SupplierResponse:
    """Update an existing supplier within the authenticated organization partition."""
    return service.update_supplier(id, body)
