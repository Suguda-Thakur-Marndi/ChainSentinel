"""Repositories for Decision & Governance resources (Phase 4 Step 7).

Resources:
- Recommendation (mitigation proposals)
- Approval (human-in-the-loop sign-off, scoped via parent recommendation)
- Action (operational mitigation executions)
- VerificationResult (post-action observational verifications, scoped via parent action)
- Notification (user and team alerts)
"""
from typing import Any, Optional
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import ImmutableResourceError
from app.models.governance import (
    Action,
    Approval,
    Notification,
    Recommendation,
    VerificationResult,
)
from app.repositories.base import BaseRepository
from app.repositories.query_utils import (
    apply_filters,
    apply_pagination,
    apply_search,
    apply_sorting,
)

# ==============================================================================
# 1. RECOMMENDATION ALLOWLISTS
# ==============================================================================
RECOMMENDATION_SEARCH_COLUMNS = ["title", "rationale"]

RECOMMENDATION_SORT_ALLOWLIST = {
    "created_at": Recommendation.created_at,
    "confidence": Recommendation.confidence,
    "estimated_cost": Recommendation.estimated_cost,
    "title": Recommendation.title,
    "status": Recommendation.status,
}

RECOMMENDATION_FILTER_ALLOWLIST = {
    "incident_id": Recommendation.incident_id,
    "status": Recommendation.status,
}

# ==============================================================================
# 2. APPROVAL ALLOWLISTS (CHILD ENTITY OF RECOMMENDATION)
# ==============================================================================
APPROVAL_SEARCH_COLUMNS = ["decision", "comments"]

APPROVAL_SORT_ALLOWLIST = {
    "decided_at": Approval.decided_at,
    "decision": Approval.decision,
}

APPROVAL_FILTER_ALLOWLIST = {
    "recommendation_id": Approval.recommendation_id,
    "decision": Approval.decision,
    "decided_by_user_id": Approval.decided_by_user_id,
}

# ==============================================================================
# 3. ACTION ALLOWLISTS
# ==============================================================================
ACTION_SEARCH_COLUMNS = ["action_type", "target_entity_type", "target_entity_id"]

ACTION_SORT_ALLOWLIST = {
    "executed_at": Action.executed_at,
    "status": Action.status,
    "action_type": Action.action_type,
}

ACTION_FILTER_ALLOWLIST = {
    "status": Action.status,
    "action_type": Action.action_type,
    "target_entity_type": Action.target_entity_type,
    "recommendation_id": Action.recommendation_id,
}

# ==============================================================================
# 4. VERIFICATION RESULT ALLOWLISTS (CHILD ENTITY OF ACTION)
# ==============================================================================
VERIFICATION_RESULT_SEARCH_COLUMNS = ["observation_summary"]

VERIFICATION_RESULT_SORT_ALLOWLIST = {
    "verified_at": VerificationResult.verified_at,
    "verified": VerificationResult.verified,
    "risk_score_after": VerificationResult.risk_score_after,
}

VERIFICATION_RESULT_FILTER_ALLOWLIST = {
    "action_id": VerificationResult.action_id,
    "verified": VerificationResult.verified,
}

# ==============================================================================
# 5. NOTIFICATION ALLOWLISTS
# ==============================================================================
NOTIFICATION_SEARCH_COLUMNS = ["title", "summary", "category"]

NOTIFICATION_SORT_ALLOWLIST = {
    "created_at": Notification.created_at,
    "severity": Notification.severity,
    "category": Notification.category,
}

NOTIFICATION_FILTER_ALLOWLIST = {
    "category": Notification.category,
    "severity": Notification.severity,
    "is_read": Notification.is_read,
    "user_id": Notification.user_id,
}


# ==============================================================================
# REPOSITORIES
# ==============================================================================
class RecommendationRepository(BaseRepository[Recommendation]):
    """Data access repository for Recommendation entities with tenant isolation."""

    def __init__(self, session: Session):
        super().__init__(Recommendation, session)

    def get_for_update(self, id: str, org_id: Optional[str] = None) -> Optional[Recommendation]:
        """Fetch a recommendation with row-level lock for concurrent decision transitions."""
        stmt = select(Recommendation).where(Recommendation.id == id).with_for_update()
        if org_id:
            stmt = stmt.where(Recommendation.org_id == org_id)
        return self.session.scalars(stmt).first()


class ApprovalRepository(BaseRepository[Approval]):
    """Data access repository for Approval entities scoped via parent Recommendation.org_id."""

    def __init__(self, session: Session):
        super().__init__(Approval, session)

    def get_approval_in_org(self, approval_id: str, org_id: str) -> Optional[Approval]:
        """Retrieve an approval verifying that its parent recommendation belongs to the tenant."""
        stmt = (
            select(Approval)
            .join(Recommendation, Recommendation.id == Approval.recommendation_id)
            .where(Approval.id == approval_id, Recommendation.org_id == org_id)
        )
        return self.session.scalars(stmt).first()

    def list_approvals_for_org(
        self,
        org_id: str,
        recommendation_id: Optional[str] = None,
        decision: Optional[str] = None,
        decided_by_user_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Approval], int]:
        """List approvals belonging to tenant recommendations with pagination, filters, sorting, and search."""
        base_stmt = (
            select(Approval)
            .join(Recommendation, Recommendation.id == Approval.recommendation_id)
            .where(Recommendation.org_id == org_id)
        )
        count_stmt = (
            select(func.count())
            .select_from(Approval)
            .join(Recommendation, Recommendation.id == Approval.recommendation_id)
            .where(Recommendation.org_id == org_id)
        )

        if recommendation_id:
            base_stmt = base_stmt.where(Approval.recommendation_id == recommendation_id)
            count_stmt = count_stmt.where(Approval.recommendation_id == recommendation_id)

        if decision:
            base_stmt = base_stmt.where(Approval.decision == decision)
            count_stmt = count_stmt.where(Approval.decision == decision)

        if decided_by_user_id:
            base_stmt = base_stmt.where(Approval.decided_by_user_id == decided_by_user_id)
            count_stmt = count_stmt.where(Approval.decided_by_user_id == decided_by_user_id)

        base_stmt = apply_filters(base_stmt, Approval, filters, APPROVAL_FILTER_ALLOWLIST)
        count_stmt = apply_filters(count_stmt, Approval, filters, APPROVAL_FILTER_ALLOWLIST)

        base_stmt = apply_search(base_stmt, Approval, search, APPROVAL_SEARCH_COLUMNS)
        count_stmt = apply_search(count_stmt, Approval, search, APPROVAL_SEARCH_COLUMNS)

        base_stmt = apply_sorting(
            base_stmt,
            Approval,
            sort_param,
            APPROVAL_SORT_ALLOWLIST,
            default_field="decided_at",
            default_desc=True,
        )
        base_stmt = apply_pagination(base_stmt, page, limit)

        total = self.session.scalar(count_stmt) or 0
        items = list(self.session.scalars(base_stmt).all())
        return items, total

    def update(self, entity: Approval, auto_commit: bool = True) -> Approval:
        """Approvals are immutable records."""
        raise ImmutableResourceError("Approval records are immutable and cannot be updated")

    def delete(self, id: str, org_id: Optional[str] = None, auto_commit: bool = True) -> bool:
        """Approvals are immutable records."""
        raise ImmutableResourceError("Approval records are immutable and cannot be deleted")


class ActionRepository(BaseRepository[Action]):
    """Data access repository for Action entities with tenant isolation."""

    def __init__(self, session: Session):
        super().__init__(Action, session)

    def get_for_update(self, id: str, org_id: Optional[str] = None) -> Optional[Action]:
        """Fetch an action with row-level lock for concurrent state transitions."""
        stmt = select(Action).where(Action.id == id).with_for_update()
        if org_id:
            stmt = stmt.where(Action.org_id == org_id)
        return self.session.scalars(stmt).first()


class VerificationResultRepository(BaseRepository[VerificationResult]):
    """Data access repository for VerificationResult entities scoped via parent Action.org_id."""

    def __init__(self, session: Session):
        super().__init__(VerificationResult, session)

    def get_result_in_org(self, result_id: str, org_id: str) -> Optional[VerificationResult]:
        """Retrieve a verification result verifying that its parent action belongs to the tenant."""
        stmt = (
            select(VerificationResult)
            .join(Action, Action.id == VerificationResult.action_id)
            .where(VerificationResult.id == result_id, Action.org_id == org_id)
        )
        return self.session.scalars(stmt).first()

    def get_by_action_id_in_org(self, action_id: str, org_id: str) -> Optional[VerificationResult]:
        """Retrieve the verification result for an action within the tenant boundary."""
        stmt = (
            select(VerificationResult)
            .join(Action, Action.id == VerificationResult.action_id)
            .where(VerificationResult.action_id == action_id, Action.org_id == org_id)
        )
        return self.session.scalars(stmt).first()

    def list_results_for_org(
        self,
        org_id: str,
        action_id: Optional[str] = None,
        verified: Optional[bool] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[VerificationResult], int]:
        """List verification results belonging to tenant actions with pagination, filters, sorting, and search."""
        base_stmt = (
            select(VerificationResult)
            .join(Action, Action.id == VerificationResult.action_id)
            .where(Action.org_id == org_id)
        )
        count_stmt = (
            select(func.count())
            .select_from(VerificationResult)
            .join(Action, Action.id == VerificationResult.action_id)
            .where(Action.org_id == org_id)
        )

        if action_id:
            base_stmt = base_stmt.where(VerificationResult.action_id == action_id)
            count_stmt = count_stmt.where(VerificationResult.action_id == action_id)

        if verified is not None:
            base_stmt = base_stmt.where(VerificationResult.verified == verified)
            count_stmt = count_stmt.where(VerificationResult.verified == verified)

        base_stmt = apply_filters(base_stmt, VerificationResult, filters, VERIFICATION_RESULT_FILTER_ALLOWLIST)
        count_stmt = apply_filters(count_stmt, VerificationResult, filters, VERIFICATION_RESULT_FILTER_ALLOWLIST)

        base_stmt = apply_search(base_stmt, VerificationResult, search, VERIFICATION_RESULT_SEARCH_COLUMNS)
        count_stmt = apply_search(count_stmt, VerificationResult, search, VERIFICATION_RESULT_SEARCH_COLUMNS)

        base_stmt = apply_sorting(
            base_stmt,
            VerificationResult,
            sort_param,
            VERIFICATION_RESULT_SORT_ALLOWLIST,
            default_field="verified_at",
            default_desc=True,
        )
        base_stmt = apply_pagination(base_stmt, page, limit)

        total = self.session.scalar(count_stmt) or 0
        items = list(self.session.scalars(base_stmt).all())
        return items, total

    def update(self, entity: VerificationResult, auto_commit: bool = True) -> VerificationResult:
        """Verification results are strictly immutable."""
        raise ImmutableResourceError("Verification result records are immutable and cannot be updated")

    def delete(self, id: str, org_id: Optional[str] = None, auto_commit: bool = True) -> bool:
        """Verification results are strictly immutable."""
        raise ImmutableResourceError("Verification result records are immutable and cannot be deleted")


class NotificationRepository(BaseRepository[Notification]):
    """Data access repository for Notification entities with user and organization scoping."""

    def __init__(self, session: Session):
        super().__init__(Notification, session)

    def list_for_user(
        self,
        org_id: str,
        user_id: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        is_read: Optional[bool] = None,
        page: int = 1,
        limit: int = 20,
        filters: Optional[dict[str, Any]] = None,
        sort_param: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[Notification], int]:
        """List notifications for user or tenant broadcast with pagination, filters, sorting, and search."""
        base_stmt = select(Notification).where(Notification.org_id == org_id)
        count_stmt = select(func.count()).select_from(Notification).where(Notification.org_id == org_id)

        # Scoped to authenticated user or org broadcast notifications
        if user_id:
            user_clause = (Notification.user_id == user_id) | (Notification.user_id.is_(None))
            base_stmt = base_stmt.where(user_clause)
            count_stmt = count_stmt.where(user_clause)

        if category:
            base_stmt = base_stmt.where(Notification.category == category)
            count_stmt = count_stmt.where(Notification.category == category)

        if severity:
            base_stmt = base_stmt.where(Notification.severity == severity)
            count_stmt = count_stmt.where(Notification.severity == severity)

        if is_read is not None:
            base_stmt = base_stmt.where(Notification.is_read == is_read)
            count_stmt = count_stmt.where(Notification.is_read == is_read)

        base_stmt = apply_filters(base_stmt, Notification, filters, NOTIFICATION_FILTER_ALLOWLIST)
        count_stmt = apply_filters(count_stmt, Notification, filters, NOTIFICATION_FILTER_ALLOWLIST)

        base_stmt = apply_search(base_stmt, Notification, search, NOTIFICATION_SEARCH_COLUMNS)
        count_stmt = apply_search(count_stmt, Notification, search, NOTIFICATION_SEARCH_COLUMNS)

        base_stmt = apply_sorting(
            base_stmt,
            Notification,
            sort_param,
            NOTIFICATION_SORT_ALLOWLIST,
            default_field="created_at",
            default_desc=True,
        )
        base_stmt = apply_pagination(base_stmt, page, limit)

        total = self.session.scalar(count_stmt) or 0
        items = list(self.session.scalars(base_stmt).all())
        return items, total

    def mark_all_read_for_user(self, org_id: str, user_id: Optional[str] = None) -> int:
        """Mark all unread notifications for a user/tenant as read."""
        stmt = (
            update(Notification)
            .where(Notification.org_id == org_id, Notification.is_read == False)  # noqa: E712
            .values(is_read=True)
        )
        if user_id:
            stmt = stmt.where((Notification.user_id == user_id) | (Notification.user_id.is_(None)))

        result = self.session.execute(stmt)
        return result.rowcount or 0
