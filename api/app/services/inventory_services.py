"""Domain services for Inventory and InventoryMovement entities with atomic concurrency and ledger immutability."""
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel
from app.core.context import AuthenticatedContext
from app.core.errors import (
    ImmutableResourceError,
    LifecycleStateError,
    NotFoundError,
    ValidationDomainError,
)
from app.db.unit_of_work import UnitOfWork
from app.models.logistics import Inventory, InventoryMovement
from app.repositories.inventory import (
    INVENTORY_FILTER_ALLOWLIST,
    INVENTORY_MOVEMENT_FILTER_ALLOWLIST,
    INVENTORY_MOVEMENT_SEARCH_COLUMNS,
    INVENTORY_MOVEMENT_SORT_ALLOWLIST,
    INVENTORY_SEARCH_COLUMNS,
    INVENTORY_SORT_ALLOWLIST,
)
from app.schemas.common import PaginationParams
from app.schemas.logistics import (
    InventoryCreate,
    InventoryListResponse,
    InventoryMovementCreate,
    InventoryMovementListResponse,
    InventoryMovementResponse,
    InventoryResponse,
    InventoryUpdate,
)
from app.services.audit_service import AuditService
from app.services.base import BaseService


def _clean_payload(data: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Extract dict and convert Enum attributes to raw string values."""
    payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)
    for k, v in payload.items():
        if hasattr(v, "value"):
            payload[k] = v.value
    return payload


# ==============================================================================
# 1. INVENTORY SERVICE
# ==============================================================================
class InventoryService(BaseService[Inventory]):
    """Domain service managing Inventory levels, facility validation, and atomic reconciliation."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Inventory, uow, context)

    def _validate_facility_ownership(self, facility_id: str, org_id: str) -> None:
        """Verify that a referenced facility does not belong to another tenant."""
        # Check factory
        factory = self.uow.factories.get(facility_id)
        if factory and getattr(factory, "org_id", None) != org_id:
            raise NotFoundError(
                message=f"Referenced facility '{facility_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Factory", "resource_id": facility_id},
            )

        # Check warehouse
        warehouse = self.uow.warehouses.get(facility_id)
        if warehouse and getattr(warehouse, "org_id", None) != org_id:
            raise NotFoundError(
                message=f"Referenced facility '{facility_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Warehouse", "resource_id": facility_id},
            )

    def create_inventory(self, data: InventoryCreate) -> InventoryResponse:
        """Create an inventory stock record validating tenant-owned product and facility."""
        org_id = self._enforce_tenant_scope()

        # Validate product exists and belongs to current tenant
        product = self.uow.products.get(data.product_id, org_id=org_id)
        if not product:
            raise NotFoundError(
                message=f"Product with ID '{data.product_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Product", "resource_id": data.product_id},
            )

        # Validate facility reference
        if data.facility_id:
            self._validate_facility_ownership(data.facility_id, org_id)

        # Enforce non-negative quantity
        if data.quantity_on_hand < 0:
            raise ValidationDomainError(
                message="Inventory quantity_on_hand cannot be negative",
                code="INVALID_QUANTITY",
                details={"quantity_on_hand": data.quantity_on_hand},
            )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            inventory = Inventory(**payload)
            self.uow.inventory.create(inventory, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Inventory",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=inventory.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return InventoryResponse.model_validate(inventory)

    def get_inventory(self, inventory_id: str) -> InventoryResponse:
        """Retrieve inventory by ID enforcing tenant isolation and 404 masking."""
        inventory = self.get_by_id(inventory_id)
        return InventoryResponse.model_validate(inventory)

    def list_inventory(
        self,
        params: PaginationParams,
        product_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> InventoryListResponse:
        """List inventory records with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if product_id:
            filters["product_id"] = product_id
        if facility_id:
            filters["facility_id"] = facility_id

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=INVENTORY_FILTER_ALLOWLIST,
            sort_allowlist=INVENTORY_SORT_ALLOWLIST,
            search_columns=INVENTORY_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [InventoryResponse.model_validate(item) for item in paginated.items]
        return InventoryListResponse(items=items, pagination=paginated.pagination)

    def update_inventory(self, inventory_id: str, data: InventoryUpdate) -> InventoryResponse:
        """Update inventory stock levels and thresholds with audit logging."""
        inventory = self.get_by_id(inventory_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "product_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        # Validate non-negative quantity if updated
        if "quantity_on_hand" in update_dict and update_dict["quantity_on_hand"] is not None:
            if update_dict["quantity_on_hand"] < 0:
                raise ValidationDomainError(
                    message="Inventory quantity_on_hand cannot be negative",
                    code="INVALID_QUANTITY",
                    details={"quantity_on_hand": update_dict["quantity_on_hand"]},
                )

        before_data = {
            "quantity_on_hand": inventory.quantity_on_hand,
            "safety_stock": inventory.safety_stock,
            "reorder_point": inventory.reorder_point,
            "days_of_supply": inventory.days_of_supply,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(inventory, k, v)
            inventory.updated_at = datetime.now(timezone.utc)
            self.uow.inventory.update(inventory, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Inventory",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=inventory.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return InventoryResponse.model_validate(inventory)

    def reconcile_stock(self, inventory_id: str, delta: float) -> InventoryResponse:
        """Atomically adjust inventory stock levels protecting against race conditions."""
        org_id = self._enforce_tenant_scope()

        with self.uow:
            inventory = self.uow.inventory.get_for_update(inventory_id, org_id=org_id)
            if not inventory:
                raise NotFoundError(
                    message=f"Inventory with ID '{inventory_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Inventory", "resource_id": inventory_id},
                )

            if inventory.quantity_on_hand + delta < 0:
                raise ValidationDomainError(
                    message=(
                        f"Insufficient inventory quantity ({inventory.quantity_on_hand}) "
                        f"for requested deduction ({delta})"
                    ),
                    code="INSUFFICIENT_INVENTORY",
                    details={
                        "current_quantity": inventory.quantity_on_hand,
                        "delta": delta,
                    },
                )

            before_data = {"quantity_on_hand": inventory.quantity_on_hand}
            inventory.quantity_on_hand += delta
            inventory.updated_at = datetime.now(timezone.utc)
            self.uow.inventory.update(inventory, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Inventory",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=inventory.id,
                before_data=before_data,
                after_data={"quantity_on_hand": inventory.quantity_on_hand, "delta": delta},
                auto_commit=False,
            )
            self.uow.commit()

        return InventoryResponse.model_validate(inventory)


# ==============================================================================
# 2. INVENTORY MOVEMENT SERVICE (APPEND-ONLY LEDGER)
# ==============================================================================
class InventoryMovementService(BaseService[InventoryMovement]):
    """Domain service managing InventoryMovement append-only transaction ledger."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(InventoryMovement, uow, context)

    def create_movement(self, data: InventoryMovementCreate) -> InventoryMovementResponse:
        """Create an append-only stock movement entry with atomic stock adjustment where applicable."""
        org_id = self._enforce_tenant_scope()

        # Validate product exists and belongs to current tenant
        product = self.uow.products.get(data.product_id, org_id=org_id)
        if not product:
            raise NotFoundError(
                message=f"Product with ID '{data.product_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Product", "resource_id": data.product_id},
            )

        if data.quantity == 0:
            raise ValidationDomainError(
                message="Inventory movement quantity cannot be zero",
                code="INVALID_QUANTITY",
                details={"quantity": data.quantity},
            )

        payload = _clean_payload(data)
        payload["org_id"] = org_id
        if "timestamp" not in payload or payload["timestamp"] is None:
            payload["timestamp"] = datetime.now(timezone.utc)

        with self.uow:
            # If reference_id points to an inventory record, adjust stock atomically under row lock
            if data.reference_id:
                inv = self.uow.inventory.get_for_update(data.reference_id, org_id=org_id)
                if not inv:
                    # Check if it exists in another organization to mask
                    cross_inv = self.uow.inventory.get(data.reference_id)
                    if cross_inv and getattr(cross_inv, "org_id", None) != org_id:
                        raise NotFoundError(
                            message=f"Referenced inventory '{data.reference_id}' not found",
                            code="RESOURCE_NOT_FOUND",
                            details={"resource_type": "Inventory", "resource_id": data.reference_id},
                        )
                else:
                    # Determine adjustment direction based on movement type
                    m_type = payload.get("movement_type", "ADJUSTMENT")
                    if m_type == "RECEIPT":
                        delta = abs(data.quantity)
                    elif m_type == "SHIPMENT":
                        delta = -abs(data.quantity)
                    else:
                        delta = data.quantity

                    if inv.quantity_on_hand + delta < 0:
                        raise ValidationDomainError(
                            message=(
                                f"Insufficient stock ({inv.quantity_on_hand}) on inventory "
                                f"'{inv.id}' for movement deduction ({delta})"
                            ),
                            code="INSUFFICIENT_INVENTORY",
                            details={
                                "inventory_id": inv.id,
                                "current_stock": inv.quantity_on_hand,
                                "delta": delta,
                            },
                        )

                    inv.quantity_on_hand += delta
                    inv.updated_at = datetime.now(timezone.utc)
                    self.uow.inventory.update(inv, auto_commit=False)

            movement = InventoryMovement(**payload)
            self.uow.inventory_movements.create(movement, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="InventoryMovement",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=movement.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return InventoryMovementResponse.model_validate(movement)

    def get_movement(self, movement_id: str) -> InventoryMovementResponse:
        """Retrieve an individual inventory movement by ID enforcing tenant isolation."""
        movement = self.get_by_id(movement_id)
        return InventoryMovementResponse.model_validate(movement)

    def list_movements(
        self,
        params: PaginationParams,
        product_id: Optional[str] = None,
        movement_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> InventoryMovementListResponse:
        """List inventory movements with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if product_id:
            filters["product_id"] = product_id
        if movement_type:
            filters["movement_type"] = movement_type
        if reference_id:
            filters["reference_id"] = reference_id

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=INVENTORY_MOVEMENT_FILTER_ALLOWLIST,
            sort_allowlist=INVENTORY_MOVEMENT_SORT_ALLOWLIST,
            search_columns=INVENTORY_MOVEMENT_SEARCH_COLUMNS,
            default_sort_field="timestamp",
            default_sort_desc=True,
        )
        items = [InventoryMovementResponse.model_validate(item) for item in paginated.items]
        return InventoryMovementListResponse(items=items, pagination=paginated.pagination)

    def update_movement(self, movement_id: str, data: Any) -> None:
        """Attempting to modify an immutable movement ledger entry raises 405/ImmutableResourceError."""
        raise ImmutableResourceError(
            message="InventoryMovement is an immutable transaction ledger record and cannot be modified."
        )

    def delete_movement(self, movement_id: str) -> None:
        """Attempting to delete an immutable movement ledger entry raises 405/ImmutableResourceError."""
        raise ImmutableResourceError(
            message="InventoryMovement is an immutable transaction ledger record and cannot be deleted."
        )
