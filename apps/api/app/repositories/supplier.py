"""Repository for Supplier entity data access and lifecycle operations."""
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.network import Supplier
from app.repositories.base import BaseRepository

SUPPLIER_SEARCH_COLUMNS = ["name", "code", "country"]

SUPPLIER_SORT_ALLOWLIST = {
    "name": Supplier.name,
    "code": Supplier.code,
    "country": Supplier.country,
    "tier": Supplier.tier,
    "criticality": Supplier.criticality,
    "reliability_score": Supplier.reliability_score,
    "financial_exposure": Supplier.financial_exposure,
    "lead_time_days": Supplier.lead_time_days,
    "created_at": Supplier.created_at,
    "updated_at": Supplier.updated_at,
}

SUPPLIER_FILTER_ALLOWLIST = {
    "tier": Supplier.tier,
    "criticality": Supplier.criticality,
    "country": Supplier.country,
    "created_at_after": Supplier.created_at,
    "created_at_before": Supplier.created_at,
}


class SupplierRepository(BaseRepository[Supplier]):
    """Data access repository for Supplier entities."""

    def __init__(self, session: Session):
        super().__init__(Supplier, session)

    def get_by_code(self, code: str, org_id: Optional[str] = None) -> Optional[Supplier]:
        """Look up a supplier by its business code within an organization."""
        stmt = select(Supplier).where(Supplier.code == code)
        if org_id:
            stmt = stmt.where(Supplier.org_id == org_id)
        return self.session.scalars(stmt).first()

    def create_supplier(
        self,
        name: str,
        code: Optional[str] = None,
        country: Optional[str] = None,
        tier: str = "MEDIUM",
        criticality: str = "MEDIUM",
        reliability_score: Optional[float] = None,
        financial_exposure: Optional[float] = None,
        lead_time_days: Optional[float] = None,
        org_id: Optional[str] = None,
        metadata_json: Optional[dict[str, Any]] = None,
        auto_commit: bool = True,
    ) -> Supplier:
        """Create and persist a new Supplier entity."""
        supplier = Supplier(
            name=name,
            code=code,
            country=country,
            tier=tier,
            criticality=criticality,
            reliability_score=reliability_score,
            financial_exposure=financial_exposure,
            lead_time_days=lead_time_days,
            org_id=org_id,
            metadata_json=metadata_json or {},
        )
        return self.create(supplier, auto_commit=auto_commit)

    def update_supplier(self, supplier_id: str, auto_commit: bool = True, **kwargs: Any) -> Optional[Supplier]:
        """Update fields of an existing Supplier."""
        supplier = self.get(supplier_id)
        if not supplier:
            return None
        for key, value in kwargs.items():
            if hasattr(supplier, key):
                setattr(supplier, key, value)
        return self.update(supplier, auto_commit=auto_commit)
