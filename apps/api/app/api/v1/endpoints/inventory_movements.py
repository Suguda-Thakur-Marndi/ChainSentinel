"""Inventory Movements API endpoints for RiskWise 2.0 (Phase 4 Step 5).

Audit ledger of stock receipts, transfers, and consumption.
Append-only transaction ledger. Strictly immutable.

Endpoints:
- GET /api/v1/inventory-movements (Protected, Viewer+: list inventory movements with pagination, search, filter, sort)
- POST /api/v1/inventory-movements (Protected, OpsManager+: record new inventory movement)
- GET /api/v1/inventory-movements/{id} (Protected, Viewer+: get single inventory movement by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.inventory import INVENTORY_MOVEMENT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.logistics import (
    InventoryMovementCreate,
    InventoryMovementListResponse,
    InventoryMovementResponse,
)
from app.services.inventory_services import InventoryMovementService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_inventory_movement_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> InventoryMovementService:
    """Dependency injecting configured InventoryMovementService."""
    return InventoryMovementService(uow=uow, context=context)


@router.get(
    "",
    response_model=InventoryMovementListResponse,
    status_code=status.HTTP_200_OK,
    summary="List inventory movements",
    description="Retrieve a paginated list of immutable stock movement ledger entries for tenant inventory.",
)
def list_inventory_movements(
    request: Request,
    params: PaginationParams = Depends(),
    product_id: Optional[str] = Query(None, description="Filter by product ID"),
    movement_type: Optional[str] = Query(None, description="Filter by movement type (RECEIPT, SHIPMENT, ADJUSTMENT, TRANSFER)"),
    reference_id: Optional[str] = Query(None, description="Filter by reference ID (e.g. inventory ID or PO/SO reference)"),
    search: Optional[str] = Query(None, description="Substring search across reference_id, from_location, or to_location"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. timestamp, -timestamp, quantity, -quantity)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: InventoryMovementService = Depends(get_inventory_movement_service),
) -> InventoryMovementListResponse:
    """List inventory movements with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in INVENTORY_MOVEMENT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(INVENTORY_MOVEMENT_FILTER_ALLOWLIST.keys()))

    return service.list_movements(
        params=params,
        product_id=product_id,
        movement_type=movement_type,
        reference_id=reference_id,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=InventoryMovementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create inventory movement",
    description="Record an append-only stock movement entry. Reconciles linked inventory atomically if reference_id matches an inventory ID. Requires OpsManager role or higher.",
)
def create_inventory_movement(
    body: InventoryMovementCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: InventoryMovementService = Depends(get_inventory_movement_service),
) -> InventoryMovementResponse:
    """Append a new stock movement record to the immutable transaction ledger."""
    return service.create_movement(body)


@router.get(
    "/{id}",
    response_model=InventoryMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Get inventory movement by ID",
    description="Retrieve an individual inventory movement entry by ID ensuring tenant ownership.",
)
def get_inventory_movement(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: InventoryMovementService = Depends(get_inventory_movement_service),
) -> InventoryMovementResponse:
    """Retrieve a single inventory movement record enforcing tenant isolation."""
    return service.get_movement(id)
