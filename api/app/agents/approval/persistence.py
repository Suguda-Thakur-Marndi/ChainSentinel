"""Transactional persistence and query repository for RiskWise Human Approval Subsystem (Phase 16).

Governs human sign-off on decision candidates stored in recommendations and approvals tables:
- recommendations table: stores decision candidate records and their lifecycle status (PENDING, APPROVED, REJECTED)
- approvals table: stores immutable formal human sign-offs (decided_by_user_id, decision, comments, decided_at)
- audit_logs table: records immutable compliance and provenance audit trails

Invariants:
- Zero schema changes, strictly 34 tables maintained, 0 migrations
- Multi-tenant isolation enforced on every query and transaction
- Zero autonomous approval: requires a verified human actor_id and authorized role (RiskManager or Admin)
- Idempotency & Immutability: finalized approvals (APPROVED or REJECTED) cannot be modified or re-decided
- Row-level concurrency locking: prevents race conditions or duplicate sign-offs
- Strict fail-closed semantics on all boundaries
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agents.approval.contract import (
    ApprovalDecision,
    ApprovalDossier,
    ApprovalStatus,
    PendingApprovalItem,
    compute_approval_fingerprint,
    generate_deterministic_approval_id,
)
from app.agents.approval.errors import (
    ApprovalAlreadyFinalizedError,
    ApprovalAuthorizationError,
    ApprovalNotFoundError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
    InvalidApprovalTransitionError,
)
from app.models.governance import Approval as DBApproval
from app.models.governance import AuditLog as DBAuditLog
from app.models.governance import Recommendation as DBRecommendation

logger = logging.getLogger("riskwise.approval.persistence")

AUTHORIZED_APPROVAL_ROLES: Set[str] = {"RiskManager", "Admin"}


class ApprovalRepository:
    """Repository handling database operations for the Human Approval Subsystem."""

    @staticmethod
    def list_pending_approvals(
        db: Session,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> Tuple[List[PendingApprovalItem], int]:
        """List all decision candidates pending human approval for the specified tenant."""
        org_id = organization_id.strip()

        # Build base filter: tenant scoped and PENDING status
        conditions = [
            DBRecommendation.org_id == org_id,
            DBRecommendation.status == ApprovalStatus.PENDING.value,
        ]

        if search and search.strip():
            term = f"%{search.strip()}%"
            conditions.append(
                or_(
                    DBRecommendation.title.ilike(term),
                    DBRecommendation.rationale.ilike(term),
                    DBRecommendation.id.ilike(term),
                )
            )

        # Count total
        count_stmt = select(func.count(DBRecommendation.id)).where(*conditions)
        total = db.scalar(count_stmt) or 0

        # Query items ordered newest first
        stmt = (
            select(DBRecommendation)
            .where(*conditions)
            .order_by(DBRecommendation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        records = db.scalars(stmt).all()

        items: List[PendingApprovalItem] = []
        for rec in records:
            payload: Dict[str, Any] = rec.expected_benefit_json or {}
            preferred_cand = payload.get("preferred_candidate") or {}
            candidate_id = preferred_cand.get("candidate_id") or "candidate_default"
            action_type = preferred_cand.get("action_type") or "OPERATIONAL_MITIGATION"

            tradeoffs = payload.get("tradeoffs") or {}
            if not tradeoffs and preferred_cand:
                tradeoffs = preferred_cand.get("tradeoffs") or {}

            # Generate deterministic approval_id
            approval_id = generate_deterministic_approval_id(
                organization_id=org_id,
                decision_id=rec.id,
                candidate_id=candidate_id,
            )

            created_at_dt = rec.created_at or datetime.now(timezone.utc)

            items.append(
                PendingApprovalItem(
                    approval_id=approval_id,
                    decision_id=rec.id,
                    organization_id=org_id,
                    title=rec.title,
                    rationale=rec.rationale,
                    estimated_cost=rec.estimated_cost,
                    confidence=rec.confidence,
                    status=rec.status,
                    preferred_candidate_id=candidate_id,
                    action_type=action_type,
                    tradeoffs=tradeoffs,
                    requires_human_approval=True,
                    created_at=created_at_dt,
                )
            )

        return items, total

    @staticmethod
    def get_approval_dossier(
        db: Session,
        organization_id: str,
        id_or_decision_id: str,
    ) -> ApprovalDossier:
        """Retrieve comprehensive review dossier for a decision candidate.

        Looks up by decision_id (recommendation.id) or approval.id.
        Enforces strict multi-tenant isolation.
        """
        org_id = organization_id.strip()
        target_id = id_or_decision_id.strip()

        # 1. Try finding Recommendation by ID
        stmt = select(DBRecommendation).where(DBRecommendation.id == target_id)
        rec = db.scalars(stmt).first()

        # 2. If not found, check if target_id is an approval.id
        approval_rec: Optional[DBApproval] = None
        if not rec:
            appr_stmt = select(DBApproval).where(DBApproval.id == target_id)
            approval_rec = db.scalars(appr_stmt).first()
            if approval_rec:
                rec_stmt = select(DBRecommendation).where(DBRecommendation.id == approval_rec.recommendation_id)
                rec = db.scalars(rec_stmt).first()

        if not rec:
            raise ApprovalNotFoundError(f"Approval or decision candidate '{target_id}' not found.")

        # Enforce tenant isolation
        if rec.org_id and rec.org_id != org_id:
            raise ApprovalTenantIsolationError(
                f"Decision candidate '{target_id}' belongs to another organization."
            )

        payload: Dict[str, Any] = rec.expected_benefit_json or {}
        preferred_cand = payload.get("preferred_candidate")
        candidate_id = preferred_cand.get("candidate_id") if preferred_cand else "candidate_default"

        approval_id = approval_rec.id if approval_rec else generate_deterministic_approval_id(
            organization_id=org_id,
            decision_id=rec.id,
            candidate_id=candidate_id,
        )

        # Check for any existing formal approval records
        if not approval_rec:
            existing_appr_stmt = (
                select(DBApproval)
                .where(DBApproval.recommendation_id == rec.id)
                .order_by(DBApproval.decided_at.desc())
            )
            approval_rec = db.scalars(existing_appr_stmt).first()

        # Collect audit history for this decision/approval
        audit_stmt = (
            select(DBAuditLog)
            .where(
                DBAuditLog.org_id == org_id,
                or_(
                    DBAuditLog.resource_id == rec.id,
                    DBAuditLog.resource_id == approval_id,
                ),
            )
            .order_by(DBAuditLog.timestamp.asc())
        )
        audit_rows = db.scalars(audit_stmt).all()
        audit_history: List[Dict[str, Any]] = [
            {
                "audit_id": a.id,
                "action": a.action,
                "actor_type": a.actor_type,
                "actor_id": a.actor_id,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "status": a.status,
                "details": a.after_json or {},
            }
            for a in audit_rows
        ]

        # Extract structured trade-offs and candidates
        candidates = payload.get("candidates") or []
        tradeoffs = payload.get("tradeoffs") or (preferred_cand.get("tradeoffs") if preferred_cand else {}) or {}
        evidence_refs = payload.get("evidence_references") or []
        explanation = payload.get("decision_explanation")

        created_at_dt = rec.created_at or datetime.now(timezone.utc)
        decided_at_dt = approval_rec.decided_at if approval_rec else None

        return ApprovalDossier(
            approval_id=approval_id,
            decision_id=rec.id,
            organization_id=org_id,
            title=rec.title,
            rationale=rec.rationale,
            status=rec.status,
            confidence=rec.confidence,
            decision_result=payload,
            decision_explanation=explanation,
            candidates=candidates,
            preferred_candidate=preferred_cand,
            tradeoffs=tradeoffs,
            evidence_references=evidence_refs,
            audit_history=audit_history,
            created_at=created_at_dt,
            decided_at=decided_at_dt,
            decided_by_user_id=approval_rec.decided_by_user_id if approval_rec else None,
            decision=approval_rec.decision if approval_rec else None,
            comments=approval_rec.comments if approval_rec else None,
        )

    @staticmethod
    def record_human_decision(
        db: Session,
        organization_id: str,
        id_or_decision_id: str,
        decision: ApprovalDecision | str,
        actor_id: str,
        actor_role: str,
        comments: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> ApprovalDossier:
        """Execute atomic human governance sign-off with row-level concurrency lock.

        Invariants enforced:
        - Zero autonomous approval: actor_id and role strictly validated
        - Tenant isolation: verified against parent recommendation
        - Idempotency & Immutability: already decided records cannot be overwritten
        """
        org_id = organization_id.strip()
        target_id = id_or_decision_id.strip()

        # 1. Zero Autonomous Approval / Actor validation
        if not actor_id or not actor_id.strip():
            raise InvalidApprovalRequestError("Approval sign-off requires a valid human actor_id.")
        clean_actor_id = actor_id.strip()
        if clean_actor_id.lower() in ("system", "agent", "bot", "auto", "automated", "llm"):
            raise ApprovalAuthorizationError(
                f"Autonomous approval prohibited: '{clean_actor_id}' is not an authorized human actor."
            )

        # 2. RBAC check: Only RiskManager and Admin can approve
        clean_role = actor_role.strip() if actor_role else "Viewer"
        if clean_role not in AUTHORIZED_APPROVAL_ROLES:
            raise ApprovalAuthorizationError(
                f"Role '{clean_role}' is not authorized to sign off on approvals. Required: {AUTHORIZED_APPROVAL_ROLES}."
            )

        # 3. Decision validation
        decision_val = decision.value if isinstance(decision, ApprovalDecision) else str(decision).strip().upper()
        if decision_val not in (ApprovalDecision.APPROVE.value, ApprovalDecision.REJECT.value):
            raise InvalidApprovalTransitionError(
                f"Invalid human approval decision '{decision_val}'. Must be APPROVE or REJECT."
            )

        # 4. Acquire row-level lock on the target recommendation
        stmt = (
            select(DBRecommendation)
            .where(DBRecommendation.id == target_id)
            .with_for_update()
        )
        rec = db.scalars(stmt).first()

        # If target_id was approval_id, find parent recommendation
        if not rec:
            appr_stmt = select(DBApproval).where(DBApproval.id == target_id)
            existing_appr = db.scalars(appr_stmt).first()
            if existing_appr:
                rec_stmt = (
                    select(DBRecommendation)
                    .where(DBRecommendation.id == existing_appr.recommendation_id)
                    .with_for_update()
                )
                rec = db.scalars(rec_stmt).first()

        if not rec:
            raise ApprovalNotFoundError(f"Decision candidate '{target_id}' not found.")

        # 5. Multi-tenant isolation check
        if rec.org_id and rec.org_id != org_id:
            raise ApprovalTenantIsolationError(
                f"Decision candidate '{target_id}' belongs to another organization."
            )

        # 6. Immutability check: Only PENDING recommendations can be decided
        current_status = (rec.status or "").upper()
        if current_status != ApprovalStatus.PENDING.value:
            raise ApprovalAlreadyFinalizedError(
                f"Decision '{rec.id}' has already been finalized with status '{rec.status}'. Re-deciding is strictly prohibited."
            )

        payload: Dict[str, Any] = rec.expected_benefit_json or {}
        preferred_cand = payload.get("preferred_candidate")
        candidate_id = preferred_cand.get("candidate_id") if preferred_cand else "candidate_default"

        approval_id = generate_deterministic_approval_id(
            organization_id=org_id,
            decision_id=rec.id,
            candidate_id=candidate_id,
        )

        now_utc = datetime.now(timezone.utc)
        clean_comments = comments.strip() if comments else None

        # 7. Create or finalize Approval record
        approval = DBApproval(
            id=approval_id,
            recommendation_id=rec.id,
            decided_by_user_id=clean_actor_id,
            decision=decision_val,
            comments=clean_comments,
            decided_at=now_utc,
        )
        db.add(approval)

        # 8. Transition recommendation status
        new_status = (
            ApprovalStatus.APPROVED.value
            if decision_val == ApprovalDecision.APPROVE.value
            else ApprovalStatus.REJECTED.value
        )
        rec.status = new_status

        # Update embedded payload
        payload["status"] = new_status
        payload["approval_result"] = {
            "approval_id": approval_id,
            "status": new_status,
            "decision": decision_val,
            "actor_id": clean_actor_id,
            "actor_role": clean_role,
            "decided_at": now_utc.isoformat(),
            "comments": clean_comments,
            "side_effect_allowed": (new_status == ApprovalStatus.APPROVED.value),
        }
        rec.expected_benefit_json = payload

        # 9. Cryptographic fingerprint
        evidence_refs = payload.get("evidence_references") or []
        fingerprint = compute_approval_fingerprint(
            organization_id=org_id,
            decision_id=rec.id,
            candidate_id=candidate_id,
            status=new_status,
            actor_id=clean_actor_id,
            decision=decision_val,
            decided_at_str=now_utc.isoformat(),
            evidence_references=evidence_refs,
        )

        # 10. Immutable Audit Trail record
        audit = DBAuditLog(
            org_id=org_id,
            actor_type="USER",
            actor_id=clean_actor_id,
            action=f"APPROVAL_{decision_val}",
            resource_type="APPROVAL",
            resource_id=approval_id,
            status="SUCCESS",
            request_id=request_id,
            after_json={
                "approval_id": approval_id,
                "decision_id": rec.id,
                "decision": decision_val,
                "status": new_status,
                "actor_id": clean_actor_id,
                "actor_role": clean_role,
                "comments": clean_comments,
                "fingerprint": fingerprint,
                "side_effect_allowed": (new_status == ApprovalStatus.APPROVED.value),
            },
        )
        db.add(audit)
        db.flush()

        logger.info(
            f"Human approval recorded: org='{org_id}', decision_id='{rec.id}', "
            f"approval_id='{approval_id}', decision='{decision_val}', actor='{clean_actor_id}' ({clean_role})"
        )

        return ApprovalRepository.get_approval_dossier(db, org_id, rec.id)
