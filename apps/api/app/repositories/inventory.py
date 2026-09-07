"""Repositories for Inventory and InventoryMovement data access, query allowlists, and atomic concurrency."""
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.logistics import Inventory, InventoryMovement
from app.repositories.base import BaseRepository
from app.services.concurrency import atomic_adjust_numeric, get_with_for_update

# ==============================================================================
# INVENTORY ALLOWLISTS
# ==============================================================================
INVENTORY_SEARCH_COLUMNS = ["product_id", "facility_id"]

INVENTORY_SORT_ALLOWLIST = {
    "quantity_on_hand": Inventory.quantity_on_hand,
    "days_of_supply": Inventory.days_of_supply,
    "safety_stock": Inventory.safety_stock,
    "reorder_point": Inventory.reorder_point,
    "created_at": Inventory.created_at,
    "updated_at": Inventory.updated_at,
}

INVENTORY_FILTER_ALLOWLIST = {
    "product_id": Inventory.product_id,
    "facility_id": Inventory.facility_id,
    "created_at_after": Inventory.created_at,
    "created_at_before": Inventory.created_at,
}

# ==============================================================================
# INVENTORY MOVEMENT ALLOWLISTS
# ==============================================================================
INVENTORY_MOVEMENT_SEARCH_COLUMNS = ["reference_id", "from_location", "to_location"]

INVENTORY_MOVEMENT_SORT_ALLOWLIST = {
    "timestamp": InventoryMovement.timestamp,
    "quantity": InventoryMovement.quantity,
}

INVENTORY_MOVEMENT_FILTER_ALLOWLIST = {
    "product_id": InventoryMovement.product_id,
    "movement_type": InventoryMovement.movement_type,
    "reference_id": InventoryMovement.reference_id,
    "timestamp_after": InventoryMovement.timestamp,
    "timestamp_before": InventoryMovement.timestamp,
}


class InventoryRepository(BaseRepository[Inventory]):
    """Data access repository for Inventory entities with concurrency row locking."""

    def __init__(self, session: Session):
        super().__init__(Inventory, session)

    def get_by_product_and_facility(
        self,
        product_id: str,
        facility_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Optional[Inventory]:
        """Look up inventory for a given product and facility within tenant scope."""
        stmt = select(Inventory).where(Inventory.product_id == product_id)
        if facility_id:
            stmt = stmt.where(Inventory.facility_id == facility_id)
        if org_id:
            stmt = stmt.where(Inventory.org_id == org_id)
        return self.session.scalars(stmt).first()

    def get_for_update(self, inventory_id: str, org_id: Optional[str] = None) -> Optional[Inventory]:
        """Retrieve inventory record with exclusive database row lock."""
        return get_with_for_update(self.session, Inventory, inventory_id, org_id=org_id)

    def adjust_stock(
        self,
        inventory_id: str,
        delta: float,
        org_id: Optional[str] = None,
        allow_negative: bool = False,
    ) -> int:
        """Atomically adjust quantity_on_hand in-database without read-modify-write race conditions.
        
        Returns 1 if updated, 0 if row not found or would become negative.
        """
        return atomic_adjust_numeric(
            session=self.session,
            model=Inventory,
            id=inventory_id,
            field_name="quantity_on_hand",
            delta=delta,
            org_id=org_id,
            allow_negative=allow_negative,
        )


class InventoryMovementRepository(BaseRepository[InventoryMovement]):
    """Data access repository for InventoryMovement append-only ledger entries."""

    def __init__(self, session: Session):
        super().__init__(InventoryMovement, session)

    def add_movement(
        self,
        product_id: str,
        quantity: float,
        movement_type: Optional[str] = None,
        from_location: Optional[str] = None,
        to_location: Optional[str] = None,
        reference_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        org_id: Optional[str] = None,
        auto_commit: bool = True,
    ) -> InventoryMovement:
        """Append an immutable transaction movement record to the ledger."""
        movement = InventoryMovement(
            product_id=product_id,
            quantity=quantity,
            movement_type=movement_type,
            from_location=from_location,
            to_location=to_location,
            reference_id=reference_id,
            timestamp=timestamp or datetime.now(timezone.utc),
            org_id=org_id,
        )
        return self.create(movement, auto_commit=auto_commit)
