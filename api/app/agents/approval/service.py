"""Domain service governing human approval operations, RBAC verification, and transactional audit trails.

Enforces zero-trust human-in-the-loop boundaries, multi-tenant isolation, idempotency,
and immutable persistence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.agents.approval.contract import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
    compute_approval_fingerprint,
    generate_deterministic_approval_id,
)
from app.agents.approval.errors import (
    ApprovalAlreadyFinalizedError,
    ApprovalAuthorizationError,
    ApprovalCandidateMismatchError,
    ApprovalExpiredError,
    ApprovalPersistenceError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
)
from app.db.unit_of_work import UnitOfWork
from app.models.governance import Approval as DBApproval
from app.models.governance import Recommendation as DBRecommendation
from app.schemas.governance import RecommendationStatus
from app.services.audit_service import AuditService

logger = logging.getLogger("riskwise.agents.approval.service")

# Authoritative approval roles under RiskWise enterprise governance
DEFAULT_AUTHORIZED_ROLES: Set[str] = {"RiskManager", "Admin"}


class HumanApprovalService:
    """Manages the lifecycle, RBAC enforcement, idempotency, and transactional persistence of human approvals."""

    def __init__(self, authorized_roles: Optional[Set[str]] = None) -> None:
        self.authorized_roles = authorized_roles or set(DEFAULT_AUTHORIZED_ROLES)
        self._in_memory_records: Dict[str, ApprovalResult] = {}

    def create_pending_approval(
        self,
        request: ApprovalRequest,
        uow: Optional[UnitOfWork] = None,
    ) -> ApprovalResult:
        """Initialize or retrieve a deterministic PENDING approval boundary record.

        Idempotent: Identical (org, decision, candidate) requests yield the identical approval record.
        """
        if not request.organization_id or not request.organization_id.strip():
            raise InvalidApprovalRequestError("ApprovalRequest organization_id must be non-empty.")
        if not request.decision_id or not request.decision_id.strip():
            raise InvalidApprovalRequestError("ApprovalRequest decision_id must be non-empty.")
        if not request.candidate_id or not request.candidate_id.strip():
            raise InvalidApprovalRequestError("ApprovalRequest candidate_id must be non-empty.")

        approval_id = request.approval_id or generate_deterministic_approval_id(
            organization_id=request.organization_id,
            decision_id=request.decision_id,
            candidate_id=request.candidate_id,
        )

        # Check existing record for idempotency
        if approval_id in self._in_memory_records:
            return self._in_memory_records[approval_id]

        fingerprint = compute_approval_fingerprint(
            organization_id=request.organization_id,
            decision_id=request.decision_id,
            candidate_id=request.candidate_id,
            status=ApprovalStatus.PENDING.value,
            evidence_references=request.evidence_references,
        )

        provenance: Dict[str, Any] = {
            "created_by": "HumanApprovalService",
            "decision_id": request.decision_id,
            "candidate_id": request.candidate_id,
            "required_role": request.required_role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        result = ApprovalResult(
            approval_id=approval_id,
            organization_id=request.organization_id,
            decision_id=request.decision_id,
            candidate_id=request.candidate_id,
            recommendation_id=request.recommendation_id,
            status=ApprovalStatus.PENDING.value,
            actor_id=None,
            actor_role=None,
            decided_at=None,
            reason=None,
            comments=None,
            evidence_references=request.evidence_references,
            audit_reference=None,
            provenance=provenance,
            requires_human_approval=True,
            side_effect_allowed=False,
            fingerprint=fingerprint,
        )

        self._in_memory_records[approval_id] = result
        return result

    def record_human_decision(
        self,
        approval_id: str,
        decision_input: ApprovalDecisionInput,
        request: ApprovalRequest,
        uow: Optional[UnitOfWork] = None,
    ) -> ApprovalResult:
        """Record an explicit, authorized human decision (APPROVE or REJECT).

        Enforces:
        - Multi-tenant isolation between actor and request.
        - RBAC authorization check against authorized roles.
        - Expiration checks if expiration_timestamp is set.
        - Lifecycle transition immutability and idempotency.
        - Atomic DB transaction and audit logging when UoW is available.
        """
        actor = decision_input.actor

        # 1. Multi-tenant isolation check
        if actor.organization_id.strip() != request.organization_id.strip():
            raise ApprovalTenantIsolationError(
                f"Actor organization '{actor.organization_id}' does not match "
                f"approval request organization '{request.organization_id}'."
            )

        # 2. RBAC authority check
        required_role = request.required_role or "RiskManager"
        is_authorized = (
            actor.role in self.authorized_roles
            or actor.role == required_role
            or actor.role == "Admin"
        )
        if not is_authorized:
            raise ApprovalAuthorizationError(
                f"Actor '{actor.actor_id}' with role '{actor.role}' is not authorized to decide on approval. "
                f"Required role: '{required_role}' or one of {sorted(list(self.authorized_roles))}."
            )

        # 3. Expiration validation
        if request.expiration_timestamp:
            current_utc = datetime.now(timezone.utc)
            exp_utc = (
                request.expiration_timestamp
                if request.expiration_timestamp.tzinfo
                else request.expiration_timestamp.replace(tzinfo=timezone.utc)
            )
            if current_utc > exp_utc:
                raise ApprovalExpiredError(
                    f"Approval request '{approval_id}' expired at '{exp_utc.isoformat()}', current time is '{current_utc.isoformat()}'."
                )

        # 4. Idempotency and transition immutability check
        target_status = (
            ApprovalStatus.APPROVED.value
            if decision_input.decision == ApprovalDecision.APPROVE
            else (
                ApprovalStatus.REJECTED.value
                if decision_input.decision == ApprovalDecision.REJECT
                else ApprovalStatus.EXPIRED.value
            )
        )
        existing = self._in_memory_records.get(approval_id)
        if existing and existing.status in (ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value):
            if existing.status == target_status:
                # Idempotent replay: return unchanged finalized result
                return existing
            else:
                # Conflicting replay: fail closed
                raise ApprovalAlreadyFinalizedError(
                    f"Approval '{approval_id}' was already finalized with status '{existing.status}' "
                    f"by actor '{existing.actor_id}'. Conflicting transition to '{decision_input.decision.value}' rejected."
                )

        decided_at = decision_input.decided_at or datetime.now(timezone.utc)
        decided_at_iso = decided_at.isoformat()
        decision_val = decision_input.decision.value

        if decision_val == ApprovalDecision.APPROVE.value:
            new_status = ApprovalStatus.APPROVED.value
            requires_human = False
            side_effect_allowed = True
            reason = "Human approval granted by authorized governance authority."
        elif decision_val == ApprovalDecision.REJECT.value:
            new_status = ApprovalStatus.REJECTED.value
            requires_human = False
            side_effect_allowed = False
            reason = "Human approval explicitly rejected by governance authority."
        else:
            new_status = ApprovalStatus.EXPIRED.value
            requires_human = False
            side_effect_allowed = False
            reason = "Approval request expired prior to human decision."

        fingerprint = compute_approval_fingerprint(
            organization_id=request.organization_id,
            decision_id=request.decision_id,
            candidate_id=request.candidate_id,
            status=new_status,
            actor_id=actor.actor_id,
            decision=decision_val,
            decided_at_str=decided_at_iso,
            evidence_references=request.evidence_references,
        )

        audit_ref = f"audit:approval:{approval_id}"

        # 5. Database transactional persistence if UnitOfWork is provided
        if uow is not None:
            try:
                with uow:
                    rec_id = request.recommendation_id
                    rec: Optional[DBRecommendation] = None
                    if rec_id:
                        rec = uow.recommendations.get_for_update(rec_id, org_id=request.organization_id)
                    
                    # If recommendation exists in DB, transition its status
                    if rec:
                        if new_status == ApprovalStatus.APPROVED.value:
                            rec.status = RecommendationStatus.APPROVED.value
                        elif new_status == ApprovalStatus.REJECTED.value:
                            rec.status = RecommendationStatus.REJECTED.value
                        uow.recommendations.update(rec, auto_commit=False)

                    # Create DB approval record if recommendation exists
                    if rec:
                        db_approval = DBApproval(
                            id=approval_id,
                            recommendation_id=rec.id,
                            decided_by_user_id=actor.actor_id,
                            decision=decision_val,
                            comments=decision_input.comments,
                            decided_at=decided_at,
                        )
                        uow.approvals.create(db_approval, auto_commit=False)

                    # Log immutable audit event
                    audit_log = AuditService.log_event(
                        uow=uow,
                        action=f"AGENT_APPROVAL_{decision_val}",
                        resource_type="Approval",
                        org_id=request.organization_id,
                        actor_id=actor.actor_id,
                        actor_type="USER",
                        resource_id=approval_id,
                        status="SUCCESS",
                        after_data={
                            "decision_id": request.decision_id,
                            "candidate_id": request.candidate_id,
                            "recommendation_id": rec_id,
                            "decision": decision_val,
                            "comments": decision_input.comments,
                            "fingerprint": fingerprint,
                        },
                        request_id=actor.request_id,
                        auto_commit=False,
                    )
                    audit_ref = str(audit_log.id) if (audit_log and hasattr(audit_log, "id")) else f"audit:approval:{approval_id}"
                    uow.commit()
            except Exception as exc:
                logger.error("Transactional persistence failed for approval '%s': %s", approval_id, exc)
                raise ApprovalPersistenceError(
                    f"Failed to persist approval transaction: {str(exc)}",
                    details={"approval_id": approval_id, "error": str(exc)},
                ) from exc

        provenance = {
            "created_by": "HumanApprovalService",
            "decision_id": request.decision_id,
            "candidate_id": request.candidate_id,
            "actor_id": actor.actor_id,
            "actor_role": actor.role,
            "decided_at": decided_at_iso,
            "decision": decision_val,
            "correlation_id": actor.correlation_id or request.correlation_id,
        }

        result = ApprovalResult(
            approval_id=approval_id,
            organization_id=request.organization_id,
            decision_id=request.decision_id,
            candidate_id=request.candidate_id,
            recommendation_id=request.recommendation_id,
            status=new_status,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            decided_at=decided_at,
            reason=reason,
            comments=decision_input.comments,
            evidence_references=request.evidence_references,
            audit_reference=audit_ref,
            provenance=provenance,
            requires_human_approval=requires_human,
            side_effect_allowed=side_effect_allowed,
            fingerprint=fingerprint,
        )

        self._in_memory_records[approval_id] = result
        return result

    def approve(
        self,
        approval_id: str,
        actor: ApprovalActor,
        request: ApprovalRequest,
        comments: Optional[str] = None,
        uow: Optional[UnitOfWork] = None,
    ) -> ApprovalResult:
        """Convenience wrapper to record an APPROVE decision."""
        decision_input = ApprovalDecisionInput(
            decision=ApprovalDecision.APPROVE,
            actor=actor,
            comments=comments,
            decided_at=datetime.now(timezone.utc),
        )
        return self.record_human_decision(approval_id, decision_input, request, uow=uow)

    def reject(
        self,
        approval_id: str,
        actor: ApprovalActor,
        request: ApprovalRequest,
        comments: Optional[str] = None,
        uow: Optional[UnitOfWork] = None,
    ) -> ApprovalResult:
        """Convenience wrapper to record a REJECT decision."""
        decision_input = ApprovalDecisionInput(
            decision=ApprovalDecision.REJECT,
            actor=actor,
            comments=comments,
            decided_at=datetime.now(timezone.utc),
        )
        return self.record_human_decision(approval_id, decision_input, request, uow=uow)

    def get_status(
        self,
        approval_id: str,
        organization_id: str,
        uow: Optional[UnitOfWork] = None,
    ) -> Optional[ApprovalResult]:
        """Retrieve an approval record by ID and verify tenant isolation."""
        res = self._in_memory_records.get(approval_id)
        if res:
            if res.organization_id != organization_id:
                raise ApprovalTenantIsolationError(
                    f"Approval '{approval_id}' belongs to organization '{res.organization_id}', "
                    f"query scoped to '{organization_id}'."
                )
            return res
        return None
