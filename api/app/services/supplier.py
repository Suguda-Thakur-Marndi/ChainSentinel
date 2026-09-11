from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from app.core.context import AuthenticatedContext
from app.core.errors import ConflictError, ValidationDomainError

if TYPE_CHECKING:
    from app.db.unit_of_work import UnitOfWork
from app.models.network import Supplier
from app.repositories.supplier import (
    SUPPLIER_FILTER_ALLOWLIST,
    SUPPLIER_SEARCH_COLUMNS,
    SUPPLIER_SORT_ALLOWLIST,
)
from app.schemas.common import PaginationParams
from app.schemas.network import SupplierCreate, SupplierListResponse, SupplierResponse, SupplierUpdate
from app.services.audit_service import AuditService
from app.services.base import BaseService


class SupplierService(BaseService[Supplier]):
    """Domain service managing Supplier lifecycle, business validations, and audit trails."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Supplier, uow, context)

    def create_supplier(self, data: SupplierCreate) -> SupplierResponse:
        """Create a new Supplier within the authenticated tenant partition."""
        org_id = self._enforce_tenant_scope()

        # Business validation: Unique supplier code within tenant
        if data.code:
            existing = self.uow.suppliers.get_by_code(data.code, org_id=org_id)
            if existing:
                raise ConflictError(
                    message=f"Supplier with code '{data.code}' already exists in this organization",
                    code="SUPPLIER_CODE_EXISTS",
                    details={"code": data.code},
                )

        # Prepare payload
        payload = data.model_dump(exclude_unset=True)
        payload["org_id"] = org_id
        if "tier" in payload and hasattr(payload["tier"], "value"):
            payload["tier"] = payload["tier"].value
        if "criticality" in payload and hasattr(payload["criticality"], "value"):
            payload["criticality"] = payload["criticality"].value

        with self.uow:
            supplier = Supplier(**payload)
            self.uow.suppliers.create(supplier, auto_commit=False)

            # Audit event logging
            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Supplier",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=supplier.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return SupplierResponse.model_validate(supplier)

    def get_supplier(self, supplier_id: str) -> SupplierResponse:
        """Retrieve a supplier by ID enforcing tenant isolation and 404 masking."""
        supplier = self.get_by_id(supplier_id)
        return SupplierResponse.model_validate(supplier)

    def list_suppliers(
        self,
        params: PaginationParams,
        tier: Optional[str] = None,
        criticality: Optional[str] = None,
        country: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> SupplierListResponse:
        """List suppliers with pagination, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if tier:
            filters["tier"] = tier
        if criticality:
            filters["criticality"] = criticality
        if country:
            filters["country"] = country

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=SUPPLIER_FILTER_ALLOWLIST,
            sort_allowlist=SUPPLIER_SORT_ALLOWLIST,
            search_columns=SUPPLIER_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )

        items = [SupplierResponse.model_validate(item) for item in paginated.items]
        return SupplierListResponse(items=items, pagination=paginated.pagination)

    def update_supplier(self, supplier_id: str, data: SupplierUpdate) -> SupplierResponse:
        """Update an existing supplier with business validation and audit logging."""
        supplier = self.get_by_id(supplier_id)
        org_id = self._enforce_tenant_scope()

        update_dict = data.model_dump(exclude_unset=True)

        # Protect server-controlled fields
        for forbidden in ("id", "org_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        # Business validation: Unique code check if code is modified
        new_code = update_dict.get("code")
        if new_code and new_code != supplier.code:
            existing = self.uow.suppliers.get_by_code(new_code, org_id=org_id)
            if existing and existing.id != supplier.id:
                raise ConflictError(
                    message=f"Supplier with code '{new_code}' already exists in this organization",
                    code="SUPPLIER_CODE_EXISTS",
                    details={"code": new_code},
                )

        # Capture before state for audit trail
        before_data = {
            "name": supplier.name,
            "code": supplier.code,
            "country": supplier.country,
            "tier": supplier.tier,
            "criticality": supplier.criticality,
            "reliability_score": supplier.reliability_score,
            "financial_exposure": supplier.financial_exposure,
            "lead_time_days": supplier.lead_time_days,
        }

        with self.uow:
            for key, val in update_dict.items():
                val_to_set = val.value if hasattr(val, "value") else val
                setattr(supplier, key, val_to_set)

            supplier.updated_at = datetime.now(timezone.utc)
            self.uow.suppliers.update(supplier, auto_commit=False)

            # Audit event logging
            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Supplier",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=supplier.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return SupplierResponse.model_validate(supplier)
