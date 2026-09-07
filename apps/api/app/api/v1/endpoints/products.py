"""Products API endpoints for RiskWise 2.0 (Phase 4 Step 4).

Endpoints:
- GET /api/v1/products (Protected, Viewer+: list products with pagination, search, filter, sort)
- POST /api/v1/products (Protected, OpsManager+: create product within tenant)
- GET /api/v1/products/{id} (Protected, Viewer+: get product by ID with 404 masking)
- PATCH /api/v1/products/{id} (Protected, OpsManager+: update product)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.network_repositories import PRODUCT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.network import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.services.logistics_services import ProductService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_product_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ProductService:
    """Dependency injecting configured ProductService."""
    return ProductService(uow=uow, context=context)


@router.get(
    "",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="List products",
    description="Retrieve a paginated list of catalog products within the authenticated tenant boundary.",
)
def list_products(
    request: Request,
    params: PaginationParams = Depends(),
    category: Optional[str] = Query(None, description="Filter by product category"),
    currency: Optional[str] = Query(None, description="Filter by currency code"),
    sku: Optional[str] = Query(None, description="Filter by exact SKU"),
    search: Optional[str] = Query(None, description="Substring search across SKU, product name, or category"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. sku, -sku, name, unit_cost, -unit_cost)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ProductService = Depends(get_product_service),
) -> ProductListResponse:
    """List products with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in PRODUCT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(PRODUCT_FILTER_ALLOWLIST.keys()))

    return service.list_products(
        params=params,
        category=category,
        currency=currency,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create product",
    description="Create a new catalog product with a unique SKU. Requires OpsManager role or higher.",
)
def create_product(
    body: ProductCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Create a new product within the authenticated organization partition."""
    return service.create_product(body)


@router.get(
    "/{id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Get product by ID",
    description="Retrieve a single product by ID. Returns 404 if missing or belonging to another organization.",
)
def get_product(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Retrieve an individual product by ID enforcing tenant isolation."""
    return service.get_product(id)


@router.patch(
    "/{id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Update product",
    description="Update an existing product's details. Requires OpsManager role or higher.",
)
def update_product(
    id: str,
    body: ProductUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Update an existing product within the authenticated organization partition."""
    return service.update_product(id, body)
