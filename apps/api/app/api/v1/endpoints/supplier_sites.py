"""Supplier Sites API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/supplier-sites (Protected, Viewer+: list supplier sites with pagination, search, filter, sort)
- POST /api/v1/supplier-sites (Protected, OpsManager+: create supplier site within tenant)
- GET /api/v1/supplier-sites/{id} (Protected, Viewer+: get supplier site by ID with 404 masking)
- PATCH /api/v1/supplier-sites/{id} (Protected, OpsManager+: update supplier site)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.network_repositories import SUPPLIER_SITE_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    SupplierSiteCreate,
    SupplierSiteListResponse,
    SupplierSiteResponse,
    SupplierSiteUpdate,
)
from app.services.logistics_services import SupplierSiteService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_supplier_site_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> SupplierSiteService:
    """Dependency injecting configured SupplierSiteService."""
    return SupplierSiteService(uow=uow, context=context)


@router.get(
    "",
    response_model=SupplierSiteListResponse,
    status_code=status.HTTP_200_OK,
    summary="List supplier sites",
    description="Retrieve a paginated list of supplier sites within the authenticated tenant boundary.",
)
def list_supplier_sites(
    request: Request,
    params: PaginationParams = Depends(),
    supplier_id: Optional[str] = Query(None, description="Filter by parent supplier ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by operational status"),
    country: Optional[str] = Query(None, description="Filter by country"),
    site_type: Optional[str] = Query(None, description="Filter by site type"),
    search: Optional[str] = Query(None, description="Substring search across name, country, city, or site_type"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. name, -name, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: SupplierSiteService = Depends(get_supplier_site_service),
) -> SupplierSiteListResponse:
    """List supplier sites with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in SUPPLIER_SITE_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(SUPPLIER_SITE_FILTER_ALLOWLIST.keys()))

    return service.list_sites(
        params=params,
        supplier_id=supplier_id,
        status=status_filter,
        country=country,
        site_type=site_type,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=SupplierSiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create supplier site",
    description="Create a new supplier site attached to an organization supplier. Requires OpsManager role or higher.",
)
def create_supplier_site(
    body: SupplierSiteCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: SupplierSiteService = Depends(get_supplier_site_service),
) -> SupplierSiteResponse:
    """Create a new supplier site within the authenticated organization partition."""
    return service.create_site(body)


@router.get(
    "/{id}",
    response_model=SupplierSiteResponse,
    status_code=status.HTTP_200_OK,
    summary="Get supplier site by ID",
    description="Retrieve a single supplier site by ID. Returns 404 if missing or belonging to another organization.",
)
def get_supplier_site(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: SupplierSiteService = Depends(get_supplier_site_service),
) -> SupplierSiteResponse:
    """Retrieve an individual supplier site by ID enforcing tenant isolation."""
    return service.get_site(id)


@router.patch(
    "/{id}",
    response_model=SupplierSiteResponse,
    status_code=status.HTTP_200_OK,
    summary="Update supplier site",
    description="Update an existing supplier site's attributes. Requires OpsManager role or higher.",
)
def update_supplier_site(
    id: str,
    body: SupplierSiteUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: SupplierSiteService = Depends(get_supplier_site_service),
) -> SupplierSiteResponse:
    """Update an existing supplier site within the authenticated organization partition."""
    return service.update_site(id, body)
