"""Human Approval orchestration agent producing structured governance findings.

Enforces zero autonomous approval, decision immutability, role-based governance,
and auditable human decision capture.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from app.agents.approval.contract import (
    ApprovalDecisionInput,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
)
from app.agents.approval.errors import (
    ApprovalAuthorizationError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
)
from app.agents.approval.service import HumanApprovalService
from app.agents.contracts import AgentFinding
from app.db.unit_of_work import UnitOfWork

logger = logging.getLogger("riskwise.agents.approval.agent")


class HumanApprovalAgent:
    """Orchestrates the Human Approval boundary for LangGraph agent pipelines."""

    def __init__(self, service: Optional[HumanApprovalService] = None) -> None:
        self.service = service or HumanApprovalService()

    def evaluate(
        self,
        request: ApprovalRequest,
        decision_input: Optional[ApprovalDecisionInput] = None,
        uow: Optional[UnitOfWork] = None,
    ) -> Tuple[ApprovalResult, List[AgentFinding]]:
        """Evaluate approval state based on presence or absence of an explicit human decision.

        If decision_input is None:
            Returns PENDING result with requires_human_approval=True and emits WAITING_FOR_APPROVAL finding.
        If decision_input is provided:
            Evaluates human decision, enforces RBAC, records decision via service, and emits APPROVAL_RECORDED finding.
        """
        if not request.organization_id or not request.organization_id.strip():
            raise InvalidApprovalRequestError("ApprovalRequest organization_id must be non-empty.")
        if not request.decision_id or not request.decision_id.strip():
            raise InvalidApprovalRequestError("ApprovalRequest decision_id must be non-empty.")
        if not request.candidate_id or not request.candidate_id.strip():
            raise InvalidApprovalRequestError("ApprovalRequest candidate_id must be non-empty.")

        findings: List[AgentFinding] = []

        # Branch 1: No human decision supplied -> Default PENDING state (NEVER AUTO-APPROVE)
        if decision_input is None:
            result = self.service.create_pending_approval(request, uow=uow)

            finding = AgentFinding(
                finding_id=f"find-appr-wait-{result.approval_id[:8]}",
                category="WAITING_FOR_APPROVAL",
                title=f"Human Approval Required: {request.candidate_id}",
                summary=(
                    f"Operational decision candidate '{request.candidate_id}' requires formal human sign-off. "
                    f"Required role: '{request.required_role}'. Halting autonomous pipeline execution."
                ),
                severity="HIGH",
                confidence=1.0,
                evidence_ids=request.evidence_references,
                source_references=[f"decision:{request.decision_id}", f"candidate:{request.candidate_id}"],
                limitations=[],
                created_by_node="human_approval",
            )
            findings.append(finding)
            return result, findings

        # Branch 2: Explicit human decision supplied -> Record and transition
        result = self.service.record_human_decision(
            approval_id=request.approval_id or result_id_fallback(request),
            decision_input=decision_input,
            request=request,
            uow=uow,
        )

        sev = "INFO" if result.status == ApprovalStatus.APPROVED.value else "MEDIUM"
        finding = AgentFinding(
            finding_id=f"find-appr-dec-{result.approval_id[:8]}",
            category="APPROVAL_RECORDED",
            title=f"Human Approval Decision: {result.status}",
            summary=(
                f"Authorized human actor '{decision_input.actor.actor_id}' ({decision_input.actor.role}) "
                f"recorded decision '{result.status}' for candidate '{request.candidate_id}'."
                + (f" Comments: {decision_input.comments}" if decision_input.comments else "")
            ),
            severity=sev,
            confidence=1.0,
            evidence_ids=request.evidence_references,
            source_references=[f"approval:{result.approval_id}", f"decision:{request.decision_id}"],
            limitations=[],
            created_by_node="human_approval",
        )
        findings.append(finding)
        return result, findings


def result_id_fallback(request: ApprovalRequest) -> str:
    from app.agents.approval.contract import generate_deterministic_approval_id
    return generate_deterministic_approval_id(
        organization_id=request.organization_id,
        decision_id=request.decision_id,
        candidate_id=request.candidate_id,
    )
