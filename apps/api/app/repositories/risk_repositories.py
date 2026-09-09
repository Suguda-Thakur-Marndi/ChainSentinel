"""Repositories for Risk intelligence, RiskFactor child entity, RiskAssessment, and Incident resources."""
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.risk import Incident, Risk, RiskAssessment, RiskFactor
from app.repositories.base import BaseRepository
from app.repositories.query_utils import (
    apply_filters,
    apply_pagination,
    apply_search,
    apply_sorting,
)

# ==============================================================================
# 1. RISK ALLOWLISTS
# ==============================================================================
RISK_SEARCH_COLUMNS = ["title", "location", "risk_type", "source"]

RISK_SORT_ALLOWLIST = {
    "detected_at": Risk.detected_at,
    "risk_score": Risk.risk_score,
    "impact": Risk.impact,
    "probability": Risk.probability,
    "title": Risk.title,
    "severity": Risk.severity,
    "confidence": Risk.confidence,
    "updated_at": Risk.updated_at,
}

RISK_FILTER_ALLOWLIST = {
    "severity": Risk.severity,
    "trend": Risk.trend,
    "risk_type": Risk.risk_type,
    "source": Risk.source,
    "detected_at_after": Risk.detected_at,
    "detected_at_before": Risk.detected_at,
}

# ==============================================================================
# 2. RISK FACTOR ALLOWLISTS (CHILD ENTITY OF RISK)
# ==============================================================================
RISK_FACTOR_SEARCH_COLUMNS = ["name", "category"]

RISK_FACTOR_SORT_ALLOWLIST = {
    "created_at": RiskFactor.created_at,
    "score": RiskFactor.score,
    "weight": RiskFactor.weight,
    "name": RiskFactor.name,
}

RISK_FACTOR_FILTER_ALLOWLIST = {
    "risk_id": RiskFactor.risk_id,
    "category": RiskFactor.category,
}

# ==============================================================================
# 3. RISK ASSESSMENT ALLOWLISTS (IMMUTABLE EVALUATION)
# ==============================================================================
RISK_ASSESSMENT_SEARCH_COLUMNS = ["methodology", "assessor_type", "assessor_id"]

RISK_ASSESSMENT_SORT_ALLOWLIST = {
    "created_at": RiskAssessment.created_at,
    "score": RiskAssessment.score,
    "confidence": RiskAssessment.confidence,
}

RISK_ASSESSMENT_FILTER_ALLOWLIST = {
    "risk_id": RiskAssessment.risk_id,
    "assessor_type": RiskAssessment.assessor_type,
    "created_at_after": RiskAssessment.created_at,
    "created_at_before": RiskAssessment.created_at,
}

# ==============================================================================
# 4. INCIDENT ALLOWLISTS
# ==============================================================================
INCIDENT_SEARCH_COLUMNS = ["title", "location", "source"]

INCIDENT_SORT_ALLOWLIST = {
    "detected_at": Incident.detected_at,
    "severity": Incident.severity,
    "title": Incident.title,
    "updated_at": Incident.updated_at,
    "resolved_at": Incident.resolved_at,
}

INCIDENT_FILTER_ALLOWLIST = {
    "status": Incident.status,
    "severity": Incident.severity,
    "risk_id": Incident.risk_id,
    "detected_at_after": Incident.detected_at,
    "detected_at_before": Incident.detected_at,
}


# ==============================================================================
# REPOSITORIES
# ==============================================================================
class RiskRepository(BaseRepository[Risk]):
    """Data access repository for Risk entities with tenant isolation."""

    def __init__(self, session: Session):
        super().__init__(Risk, session)


class RiskFactorRepository(BaseRepository[RiskFactor]):
    """Data access repository for RiskFactor entities scoped via parent Risk.org_id."""

    def __init__(self, session: Session):
        super().__init__(RiskFactor, session)

    def get_factor_in_org(self, factor_id: str, org_id: str) -> Optional[RiskFactor]:
        """Retrieve a risk factor verifying that its parent risk belongs to the tenant."""
        stmt = (
            select(RiskFactor)
            .join(Risk, Risk.id == RiskFactor.risk_id)
            .where(RiskFactor.id == factor_id, Risk.org_id == org_id)
        )
        return self.session.scalars(stmt).first()

    def list_factors_for_org(
        self,
        org_id: str,
        risk_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[RiskFactor], int]:
        """List risk factors belonging to tenant risks with pagination, filters, sorting, and search."""
        base_stmt = (
            select(RiskFactor)
            .join(Risk, Risk.id == RiskFactor.risk_id)
            .where(Risk.org_id == org_id)
        )
        count_stmt = (
            select(func.count())
            .select_from(RiskFactor)
            .join(Risk, Risk.id == RiskFactor.risk_id)
            .where(Risk.org_id == org_id)
        )

        if risk_id:
            base_stmt = base_stmt.where(RiskFactor.risk_id == risk_id)
            count_stmt = count_stmt.where(RiskFactor.risk_id == risk_id)

        # Apply safe filters, search, sorting
        base_stmt = apply_filters(base_stmt, RiskFactor, filters, RISK_FACTOR_FILTER_ALLOWLIST)
        count_stmt = apply_filters(count_stmt, RiskFactor, filters, RISK_FACTOR_FILTER_ALLOWLIST)

        base_stmt = apply_search(base_stmt, RiskFactor, search, RISK_FACTOR_SEARCH_COLUMNS)
        count_stmt = apply_search(count_stmt, RiskFactor, search, RISK_FACTOR_SEARCH_COLUMNS)

        base_stmt = apply_sorting(
            base_stmt,
            RiskFactor,
            sort_param,
            RISK_FACTOR_SORT_ALLOWLIST,
            default_field="created_at",
            default_desc=True,
        )
        base_stmt = apply_pagination(base_stmt, page, limit)

        total = self.session.scalar(count_stmt) or 0
        items = list(self.session.scalars(base_stmt).all())
        return items, total


class RiskAssessmentRepository(BaseRepository[RiskAssessment]):
    """Data access repository for RiskAssessment evaluation records with tenant isolation."""

    def __init__(self, session: Session):
        super().__init__(RiskAssessment, session)

    def get_assessment(self, org_id: str, assessment_id: str) -> Optional[RiskAssessment]:
        """Retrieve a risk assessment strictly scoped to the tenant organization."""
        stmt = select(RiskAssessment).where(
            RiskAssessment.id == assessment_id,
            RiskAssessment.org_id == org_id,
        )
        return self.session.scalars(stmt).first()

    def find_by_fingerprint(self, org_id: str, fingerprint: str) -> Optional[RiskAssessment]:
        """Find an existing assessment by deterministic semantic fingerprint within tenant boundary."""
        try:
            stmt = select(RiskAssessment).where(
                RiskAssessment.org_id == org_id,
                RiskAssessment.findings["deterministic_fingerprint"].as_string() == fingerprint,
            )
            found = self.session.scalars(stmt).first()
            if found is not None:
                return found
        except Exception:
            pass

        # Fallback inspection over recent tenant assessments
        stmt = (
            select(RiskAssessment)
            .where(RiskAssessment.org_id == org_id)
            .order_by(RiskAssessment.created_at.desc())
        )
        for item in self.session.scalars(stmt).all():
            if (item.findings or {}).get("deterministic_fingerprint") == fingerprint:
                return item
        return None

    def get_latest_for_risk(self, org_id: str, risk_id: str) -> Optional[RiskAssessment]:
        """Retrieve the latest assessment evaluation for a specific risk entity in tenant scope."""
        stmt = (
            select(RiskAssessment)
            .where(RiskAssessment.org_id == org_id, RiskAssessment.risk_id == risk_id)
            .order_by(RiskAssessment.created_at.desc())
        )
        return self.session.scalars(stmt).first()

    def get_latest_for_entity(
        self,
        org_id: str,
        scope: str,
        scope_entity_id: str,
    ) -> Optional[RiskAssessment]:
        """Retrieve the latest assessment for a given scope and target entity ID in tenant scope."""
        stmt = (
            select(RiskAssessment)
            .where(RiskAssessment.org_id == org_id)
            .order_by(RiskAssessment.created_at.desc())
        )
        for item in self.session.scalars(stmt).all():
            f = item.findings or {}
            if (
                f.get("scope", "").upper() == scope.upper()
                and f.get("scope_entity_id") == scope_entity_id
            ):
                return item
        return None

    def get_latest_for_org(
        self,
        org_id: str,
        scope: Optional[str] = None,
    ) -> Optional[RiskAssessment]:
        """Retrieve the most recent assessment for the organization, optionally filtered by scope."""
        stmt = (
            select(RiskAssessment)
            .where(RiskAssessment.org_id == org_id)
            .order_by(RiskAssessment.created_at.desc())
        )
        if not scope:
            return self.session.scalars(stmt).first()

        for item in self.session.scalars(stmt).all():
            if (item.findings or {}).get("scope", "").upper() == scope.upper():
                return item
        return None

    def get_assessment_history(
        self,
        org_id: str,
        risk_id: Optional[str] = None,
        scope: Optional[str] = None,
        scope_entity_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        ascending: bool = True,
    ) -> list[RiskAssessment]:
        """Retrieve deterministic chronological assessment history for tenant partition.

        Enforces server-side tenant isolation, date range filtering, and deterministic
        ordering (created_at ASC, id ASC).
        """
        stmt = select(RiskAssessment).where(RiskAssessment.org_id == org_id)

        if risk_id:
            stmt = stmt.where(RiskAssessment.risk_id == risk_id)
        if start_time:
            stmt = stmt.where(RiskAssessment.created_at >= start_time)
        if end_time:
            stmt = stmt.where(RiskAssessment.created_at <= end_time)

        # Deterministic ordering: primary created_at, secondary id tie-breaker
        if ascending:
            stmt = stmt.order_by(RiskAssessment.created_at.asc(), RiskAssessment.id.asc())
        else:
            stmt = stmt.order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.asc())

        bounded_limit = max(1, min(limit, 100))
        candidates = list(self.session.scalars(stmt).all())

        results: list[RiskAssessment] = []
        for item in candidates:
            f = item.findings or {}
            if scope and f.get("scope", "").upper() != scope.upper():
                continue
            if scope_entity_id and str(f.get("scope_entity_id")) != str(scope_entity_id):
                continue
            results.append(item)
            if len(results) >= bounded_limit:
                break

        return results

    def list_assessments_for_org(
        self,
        org_id: str,
        risk_id: Optional[str] = None,
        assessor_type: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[RiskAssessment], int]:
        """List tenant risk assessments with filters, search, pagination, and sorting."""
        base_stmt = select(RiskAssessment).where(RiskAssessment.org_id == org_id)
        count_stmt = (
            select(func.count())
            .select_from(RiskAssessment)
            .where(RiskAssessment.org_id == org_id)
        )

        filters: dict[str, Any] = {}
        if risk_id:
            filters["risk_id"] = risk_id
        if assessor_type:
            filters["assessor_type"] = assessor_type

        base_stmt = apply_filters(base_stmt, RiskAssessment, filters, RISK_ASSESSMENT_FILTER_ALLOWLIST)
        count_stmt = apply_filters(count_stmt, RiskAssessment, filters, RISK_ASSESSMENT_FILTER_ALLOWLIST)

        base_stmt = apply_search(base_stmt, RiskAssessment, search, RISK_ASSESSMENT_SEARCH_COLUMNS)
        count_stmt = apply_search(count_stmt, RiskAssessment, search, RISK_ASSESSMENT_SEARCH_COLUMNS)

        base_stmt = apply_sorting(
            base_stmt,
            RiskAssessment,
            sort_param,
            RISK_ASSESSMENT_SORT_ALLOWLIST,
            default_field="created_at",
            default_desc=True,
        )
        base_stmt = apply_pagination(base_stmt, page, limit)

        total = self.session.scalar(count_stmt) or 0
        items = list(self.session.scalars(base_stmt).all())
        return items, total


class IncidentRepository(BaseRepository[Incident]):
    """Data access repository for Incident entities with tenant isolation and status management."""

    def __init__(self, session: Session):
        super().__init__(Incident, session)
