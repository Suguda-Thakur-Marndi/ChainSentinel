"""Generic Base Repository providing standardized, tenant-safe CRUD operations."""
from typing import Any, Generic, Optional, Type, TypeVar
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.errors import DatabaseError, NotFoundError
from app.core.logging import get_logger
from app.repositories.query_utils import (
    apply_filters,
    apply_pagination,
    apply_search,
    apply_sorting,
    apply_tenant_isolation,
)

logger = get_logger("repositories")

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    """Abstract generic repository implementing standardized data access and tenant isolation."""

    def __init__(self, model: Type[ModelType], session: Session):
        self.model = model
        self.session = session

    def get(self, id: str, org_id: Optional[str] = None) -> Optional[ModelType]:
        """Retrieve a single entity by its primary key ID with tenant verification.

        If org_id is provided and the resource is tenant-scoped, cross-tenant records
        return None (masking existence).
        """
        entity = self.session.get(self.model, id)
        if not entity:
            return None

        # If org_id is specified and model has org_id attribute, verify boundary
        if org_id and hasattr(entity, "org_id"):
            if getattr(entity, "org_id") != org_id:
                return None

        return entity

    def get_or_404(self, id: str, org_id: Optional[str] = None) -> ModelType:
        """Retrieve a single entity or raise NotFoundError (404) if absent or cross-tenant."""
        entity = self.get(id, org_id=org_id)
        if not entity:
            raise NotFoundError(
                message=f"{self.model.__name__} not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": self.model.__name__, "resource_id": id},
            )
        return entity

    def exists(self, id: str, org_id: Optional[str] = None) -> bool:
        """Check whether an entity exists within the tenant scope."""
        stmt = select(func.count()).select_from(self.model).where(getattr(self.model, "id") == id)
        stmt = apply_tenant_isolation(stmt, self.model, org_id)
        return (self.session.scalar(stmt) or 0) > 0

    def find_one(self, org_id: Optional[str] = None, **criteria: Any) -> Optional[ModelType]:
        """Retrieve the first record matching explicit keyword criteria within tenant scope."""
        stmt = select(self.model)
        stmt = apply_tenant_isolation(stmt, self.model, org_id)
        for key, val in criteria.items():
            if hasattr(self.model, key):
                stmt = stmt.where(getattr(self.model, key) == val)
        return self.session.scalars(stmt).first()

    def count(
        self,
        org_id: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
        search: Optional[str] = None,
        filter_allowlist: Optional[dict[str, Any]] = None,
        search_columns: Optional[list[str]] = None,
    ) -> int:
        """Count entities matching criteria within tenant scope."""
        stmt = select(func.count()).select_from(self.model)
        stmt = apply_tenant_isolation(stmt, self.model, org_id)
        stmt = apply_filters(stmt, self.model, filters, filter_allowlist)
        stmt = apply_search(stmt, self.model, search, search_columns)
        return self.session.scalar(stmt) or 0

    def list(
        self,
        org_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
        filter_allowlist: Optional[dict[str, Any]] = None,
        sort_allowlist: Optional[dict[str, Any]] = None,
        search_columns: Optional[list[str]] = None,
        default_sort_field: str = "created_at",
        default_sort_desc: bool = True,
    ) -> list[ModelType]:
        """List entities with tenant isolation, safe filtering, sorting, search, and pagination."""
        stmt = select(self.model)
        stmt = apply_tenant_isolation(stmt, self.model, org_id)
        stmt = apply_filters(stmt, self.model, filters, filter_allowlist)
        stmt = apply_search(stmt, self.model, search, search_columns)
        stmt = apply_sorting(stmt, self.model, sort_param, sort_allowlist, default_sort_field, default_sort_desc)
        stmt = apply_pagination(stmt, page, limit)
        return list(self.session.scalars(stmt).all())

    def create(self, entity: ModelType, auto_commit: bool = True) -> ModelType:
        """Persist a new entity.

        If auto_commit is True: commits immediately (legacy / standalone usage).
        If auto_commit is False: flushes to session for unit-of-work transaction orchestration.
        """
        try:
            self.session.add(entity)
            if auto_commit:
                self.session.commit()
                self.session.refresh(entity)
            else:
                self.session.flush()
            return entity
        except SQLAlchemyError as e:
            if auto_commit:
                self.session.rollback()
            logger.error("Failed to create %s: %s", self.model.__name__, e)
            raise

    def update(self, entity: ModelType, auto_commit: bool = True) -> ModelType:
        """Persist modifications to an existing entity.

        If auto_commit is True: commits immediately (legacy / standalone usage).
        If auto_commit is False: flushes to session for unit-of-work transaction orchestration.
        """
        try:
            if auto_commit:
                self.session.commit()
                self.session.refresh(entity)
            else:
                self.session.flush()
            return entity
        except SQLAlchemyError as e:
            if auto_commit:
                self.session.rollback()
            logger.error("Failed to update %s: %s", self.model.__name__, e)
            raise

    def delete(self, id: str, org_id: Optional[str] = None, auto_commit: bool = True) -> bool:
        """Remove an entity by ID after verifying tenant ownership.

        Returns False if entity does not exist or belongs to another tenant.
        """
        try:
            entity = self.get(id, org_id=org_id)
            if not entity:
                return False
            self.session.delete(entity)
            if auto_commit:
                self.session.commit()
            else:
                self.session.flush()
            return True
        except SQLAlchemyError as e:
            if auto_commit:
                self.session.rollback()
            logger.error("Failed to delete %s id=%s: %s", self.model.__name__, id, e)
            raise
