from __future__ import annotations

"""Generic Base Service encapsulating business validation, tenant scoping, lifecycle rules, and transaction boundaries."""
from typing import TYPE_CHECKING, Any, Generic, Optional, Type, TypeVar
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.context import AuthenticatedContext
from app.core.errors import (
    AuthorizationError,
    ImmutableResourceError,
    LifecycleStateError,
    NotFoundError,
    ValidationDomainError,
)
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.db.unit_of_work import UnitOfWork
from app.repositories.base import BaseRepository
from app.repositories.query_utils import ResourceScope, get_resource_scope
from app.schemas.common import PaginatedResponse, PaginationMeta, PaginationParams

logger = get_logger("services")

ModelType = TypeVar("ModelType")
SchemaType = TypeVar("SchemaType", bound=BaseModel)

# Authoritative lists of operational and immutable models
IMMUTABLE_MODELS = {
    "shipment_events",
    "inventory_movements",
    "audit_logs",
    "verification_results",
}

OPERATIONAL_MODELS = {
    "suppliers",
    "shipments",
    "inventory",
}


class BaseService(Generic[ModelType]):
    """Abstract generic service providing domain logic, tenant isolation, and lifecycle enforcement."""

    def __init__(
        self,
        model: Type[ModelType],
        uow: UnitOfWork,
        context: Optional[AuthenticatedContext] = None,
    ):
        self.model = model
        self.uow = uow
        self.context = context
        self.scope = get_resource_scope(model)

    @property
    def repository(self) -> BaseRepository[ModelType]:
        """Accessor for the corresponding model repository."""
        return self.uow.repository(self.model)

    @property
    def tenant_id(self) -> Optional[str]:
        """Derive the authoritative organization ID from authenticated context."""
        if self.context:
            return self.context.organization_id
        return None

    def _enforce_tenant_scope(self) -> Optional[str]:
        """Ensure tenant-scoped operations have a valid authenticated organization boundary."""
        if self.scope in (ResourceScope.TENANT, ResourceScope.CHILD):
            org_id = self.tenant_id
            if not org_id:
                raise AuthorizationError(
                    message="Authenticated organization context is required",
                    code="ORGANIZATION_CONTEXT_REQUIRED",
                )
            return org_id
        return None

    def get_by_id(self, id: str) -> ModelType:
        """Retrieve a single entity by ID enforcing tenant isolation.

        If entity does not exist or belongs to another organization, returns 404
        to prevent resource enumeration.
        """
        org_id = self._enforce_tenant_scope()
        entity = self.repository.get(id, org_id=org_id)
        if not entity:
            raise NotFoundError(
                message=f"{self.model.__name__} not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": self.model.__name__, "resource_id": id},
            )
        return entity

    def list_paginated(
        self,
        params: PaginationParams,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
        filter_allowlist: Optional[dict[str, Any]] = None,
        sort_allowlist: Optional[dict[str, Any]] = None,
        search_columns: Optional[list[str]] = None,
        default_sort_field: str = "created_at",
        default_sort_desc: bool = True,
    ) -> PaginatedResponse[Any]:
        """List entities with pagination, tenant isolation, and query protections."""
        org_id = self._enforce_tenant_scope()

        total = self.repository.count(
            org_id=org_id,
            filters=filters,
            search=search,
            filter_allowlist=filter_allowlist,
            search_columns=search_columns,
        )

        items = self.repository.list(
            org_id=org_id,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=filter_allowlist,
            sort_allowlist=sort_allowlist,
            search_columns=search_columns,
            default_sort_field=default_sort_field,
            default_sort_desc=default_sort_desc,
        )

        pages = (total + params.limit - 1) // params.limit if total > 0 else 0

        return PaginatedResponse(
            items=items,
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=pages,
            ),
        )

    def create(
        self,
        schema_in: BaseModel | dict[str, Any],
        auto_commit: bool = True,
    ) -> ModelType:
        """Create a new domain entity.

        Automatically injects authoritative context.organization_id for tenant-owned models.
        Client-supplied org_id or server-owned fields are rejected or ignored.
        """
        table_name = getattr(self.model, "__tablename__", "")
        if table_name in IMMUTABLE_MODELS:
            # Creation of immutable ledgers is allowed, but deletion/updates are forbidden
            pass

        data = schema_in.model_dump(exclude_unset=True) if isinstance(schema_in, BaseModel) else dict(schema_in)

        # Enforce server-owned tenant boundary
        if self.scope == ResourceScope.TENANT:
            org_id = self._enforce_tenant_scope()
            data["org_id"] = org_id

        entity = self.model(**data)
        saved = self.repository.create(entity, auto_commit=auto_commit)
        return saved

    def update(
        self,
        id: str,
        schema_in: BaseModel | dict[str, Any],
        auto_commit: bool = True,
    ) -> ModelType:
        """Update an existing domain entity.

        Immutable models cannot be updated. Client-supplied org_id is forbidden.
        """
        table_name = getattr(self.model, "__tablename__", "")
        if table_name in IMMUTABLE_MODELS:
            raise ImmutableResourceError(
                message=f"{self.model.__name__} is an immutable ledger entity and cannot be updated"
            )

        entity = self.get_by_id(id)

        data = schema_in.model_dump(exclude_unset=True) if isinstance(schema_in, BaseModel) else dict(schema_in)

        # Forbidden fields to mutate
        for forbidden in ("id", "org_id", "created_at"):
            data.pop(forbidden, None)

        for key, val in data.items():
            if hasattr(entity, key):
                setattr(entity, key, val)

        return self.repository.update(entity, auto_commit=auto_commit)

    def delete(self, id: str, auto_commit: bool = True) -> bool:
        """Delete an entity obeying domain deletion policy.

        - Immutable ledgers: deletion forbidden (ImmutableResourceError).
        - Operational entities (suppliers, shipments, inventory): hard deletion forbidden (LifecycleStateError).
        - Ephemeral entities: hard deletion allowed with tenant verification.
        """
        table_name = getattr(self.model, "__tablename__", "")

        if table_name in IMMUTABLE_MODELS:
            raise ImmutableResourceError(
                message=f"{self.model.__name__} is an immutable ledger and cannot be deleted"
            )

        if table_name in OPERATIONAL_MODELS:
            raise LifecycleStateError(
                message=(
                    f"{self.model.__name__} is an operational entity and cannot be hard deleted. "
                    "Use status lifecycle transitions (e.g. status='CANCELLED' or 'INACTIVE') instead."
                )
            )

        # Ephemeral models: verify existence and tenant ownership
        org_id = self._enforce_tenant_scope()
        self.get_by_id(id)  # Raises 404 if not found or cross-tenant

        return self.repository.delete(id, org_id=org_id, auto_commit=auto_commit)
