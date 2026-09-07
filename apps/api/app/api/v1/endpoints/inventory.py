"""Inventory API endpoints for RiskWise 2.0 (Phase 4 Step 5).

Facility-level stock levels, reorder points, and days-of-supply.
Organization-scoped with optimistic/pessimistic concurrency handling.

Endpoints:
- GET /api/v1/inventory (Protected, Viewer+: list inventory with pagination, search, filter, sort)
- POST /api/v1/inventory (Protected, OpsManager+: create inventory stock record)
- GET /api/v1/inventory/{id} (Protected, Viewer+: get inventory by ID with 404 masking)
- PATCH /api/v1/inventory/{id} (Protected, OpsManager+: update inventory levels and thresholds)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.inventory import INVENTORY_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.logistics import (
    InventoryCreate,
    InventoryListResponse,
    InventoryResponse,
    InventoryUpdate,
)
from app.services.inventory_services import InventoryService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_inventory_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> InventoryService:
    """Dependency injecting configured InventoryService."""
    return InventoryService(uow=uow, context=context)


@router.get(
    "",
    response_model=InventoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List inventory",
    description="Retrieve a paginated list of inventory stock records within the authenticated organization boundary.",
)
def list_inventory(
    request: Request,
    params: PaginationParams = Depends(),
    product_id: Optional[str] = Query(None, description="Filter by product ID"),
    facility_id: Optional[str] = Query(None, description="Filter by facility ID"),
    search: Optional[str] = Query(None, description="Substring search across product_id or facility_id"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. quantity_on_hand, -quantity_on_hand, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryListResponse:
    """List inventory with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in INVENTORY_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(INVENTORY_FILTER_ALLOWLIST.keys()))

    return service.list_inventory(
        params=params,
        product_id=product_id,
        facility_id=facility_id,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create inventory",
    description="Create a new inventory stock record. Requires OpsManager role or higher.",
)
def create_inventory(
    body: InventoryCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    """Create a new inventory stock record within the authenticated organization boundary."""
    return service.create_inventory(body)


@router.get(
    "/{id}",
    response_model=InventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get inventory by ID",
    description="Retrieve a single inventory record by ID. Returns 404 if missing or belonging to another organization.",
)
def get_inventory(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    """Retrieve an individual inventory record by ID enforcing tenant isolation."""
    return service.get_inventory(id)


@router.patch(
    "/{id}",
    response_model=InventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update inventory",
    description="Update inventory stock levels and thresholds. Requires OpsManager role or higher.",
)
def update_inventory(
    id: str,
    body: InventoryUpdate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    """Update an existing inventory stock record within the authenticated organization partition."""
    return service.update_inventory(id, body)
