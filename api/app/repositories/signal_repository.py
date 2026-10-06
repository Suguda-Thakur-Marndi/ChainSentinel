"""Repository for Signal entity data access (Normalized Risk Signals)."""
from __future__ import annotations

from typing import Any, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.risk import Signal
from app.repositories.base import BaseRepository
from app.repositories.query_utils import (
    apply_filters,
    apply_pagination,
    apply_search,
    apply_sorting,
)

SIGNAL_SEARCH_COLUMNS = ["title", "location_name", "provider", "domain", "signal_type", "summary"]

SIGNAL_SORT_ALLOWLIST = {
    "detected_at": Signal.detected_at,
    "created_at": Signal.created_at,
    "confidence": Signal.confidence,
    "title": Signal.title,
    "severity": Signal.severity,
}

SIGNAL_FILTER_ALLOWLIST = {
    "domain": Signal.domain,
    "signal_type": Signal.signal_type,
    "status": Signal.status,
    "severity": Signal.severity,
    "provider": Signal.provider,
    "source": Signal.source,
    "entity_type": Signal.entity_type,
    "entity_id": Signal.entity_id,
}


class SignalRepository(BaseRepository[Signal]):
    """Data access repository for Signal entities (Tenant scope, Ingested Signals)."""

    def __init__(self, session: Session):
        super().__init__(Signal, session)

    def get_by_signal_id(self, signal_id: str, org_id: Optional[str] = None) -> Optional[Signal]:
        """Find a signal by its unique signal_id with tenant isolation."""
        stmt = select(Signal).where(Signal.signal_id == signal_id)
        if org_id:
            stmt = stmt.where((Signal.org_id == org_id) | (Signal.org_id.is_(None)))
        return self.session.scalars(stmt).first()

    def upsert_signal(self, signal_data: dict[str, Any], auto_commit: bool = False) -> Tuple[Signal, bool]:
        """Insert or update a signal idempotently using signal_id fingerprint.
        
        Returns:
            Tuple of (Signal instance, is_new boolean)
        """
        existing = self.get_by_signal_id(signal_data["signal_id"], signal_data.get("org_id"))
        if existing:
            # Update mutable telemetry attributes
            for k, v in signal_data.items():
                if k not in ("id", "signal_id", "created_at") and v is not None:
                    setattr(existing, k, v)
            if auto_commit:
                self.session.commit()
                self.session.refresh(existing)
            return existing, False

        new_signal = Signal(**signal_data)
        created = self.create(new_signal, auto_commit=auto_commit)
        return created, True

    def list_signals(
        self,
        org_id: Optional[str] = None,
        domain: Optional[str] = None,
        provider: Optional[str] = None,
        severity: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[list[Signal], int]:
        """List signals with filtering, search, sorting, and pagination."""
        stmt = select(Signal)
        if org_id:
            stmt = stmt.where((Signal.org_id == org_id) | (Signal.org_id.is_(None)))

        filters = {}
        if domain:
            filters["domain"] = domain
        if provider:
            filters["provider"] = provider
        if severity:
            filters["severity"] = severity

        stmt = apply_filters(stmt, filters, SIGNAL_FILTER_ALLOWLIST)
        stmt = apply_search(stmt, Signal, search, SIGNAL_SEARCH_COLUMNS)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = self.session.scalar(count_stmt) or 0

        stmt = apply_sorting(
            stmt,
            Signal,
            sort_param,
            allowlist=SIGNAL_SORT_ALLOWLIST,
            default_field="detected_at",
            default_desc=True,
        )
        stmt = apply_pagination(stmt, page=page, limit=limit)

        items = list(self.session.scalars(stmt).all())
        return items, total
