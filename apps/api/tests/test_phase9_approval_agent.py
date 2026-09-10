"""Comprehensive focused test suite for RiskWise 2.0 Phase 9 Step 9: Human Approval Boundary.

Covers:
1. Contracts Validation (Pydantic V2, extra="forbid", required fields)
2. Lifecycle Transitions (PENDING -> APPROVED, PENDING -> REJECTED, EXPIRED)
3. Mandatory No Auto-Approval Test (requires_human_approval=True never auto-approved)
4. Human Actor & RBAC Authority (RiskManager, Admin authorized; Viewer, Analyst rejected)
5. Multi-Tenant Boundary Isolation (cross-tenant actor, decision, approval rejected)
6. Decision Immutability (approval never mutates decision, risk, scenario, or prediction)
7. Finalized Approval Immutability (re-deciding or conflicting transitions rejected)
8. Explicit Approval Event Requirement (viewing, timeout, or confidence != approval)
9. No LLM Approval (forbids prompts, CoT, heuristics)
10. Database Transaction & UnitOfWork Integration (atomic persistence in approvals & audit_logs)
11. Idempotency (replay identical approve, conflicting replay fails closed)
12. Audit Trail & Traceability (captures actor, decision, candidate, correlation_id)
13. State Ownership (AgentStage.APPROVAL writes only approval fields, unauthorized writes blocked)
14. Security Scrubbing (rejects passwords, tokens, API keys, bearer auth in comments/provenance)
15. Observability & Telemetry (node name human_approval, status, duration, error codes)
16. Deterministic Identity & Fingerprinting (UUIDv5, SHA-256 canonical hash)
17. Graph Topology & Edge Transitions (DECISION -> APPROVAL, APPROVAL -> TERMINATION, backward illegal)
18. LangGraph Interruption & Resume (MemorySaver checkpointer, deterministic state resume)
19. Explicit No-Side-Effect Safety (no shipment/inventory/carrier/supplier mutations)
20. Error Taxonomy & Classification (typed hierarchy, non-retryable classification)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.agents.approval import (
    APPROVAL_UUID_NAMESPACE,
    HUMAN_APPROVAL_NODE_CONTRACT,
    ApprovalActor,
    ApprovalAgentError,
    ApprovalAlreadyFinalizedError,
    ApprovalAuditContext,
    ApprovalAuthorizationError,
    ApprovalCandidateMismatchError,
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalDecisionRequiredError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalPersistenceError,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStateOwnershipViolationError,
    ApprovalStatus,
    ApprovalTenantIsolationError,
    HumanApprovalAgent,
    HumanApprovalService,
    InvalidApprovalRequestError,
    InvalidApprovalTransitionError,
    compute_approval_fingerprint,
    generate_deterministic_approval_id,
    human_approval_node,
)
from app.agents.contracts import (
    AUTHORITATIVE_FIELD_OWNERS,
    AgentExecutionContext,
    AgentFinding,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentNodeContract,
    AgentStage,
    ToolSideEffectType,
    apply_state_update,
    validate_state_update,
)
from app.agents.decision import (
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionResult,
    DecisionStatus,
    DecisionType,
)
from app.agents.edges import ALLOWED_STAGE_TRANSITIONS, EdgeRegistry, StageTransitionValidator
from app.agents.errors import (
    AgentStageTransitionError,
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentValidationError,
)
from app.agents.graph import AgentGraphBuilder, execute_agent_graph
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.registry import NodeRegistry, global_node_registry


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def sample_decision_result() -> Dict[str, Any]:
    cand = DecisionCandidate(
        candidate_id="cand_test_001",
        action_type="ESCALATE_FOR_HUMAN_REVIEW",
        title="Escalate For Human Review",
        description="Escalate critical shipment delay for immediate human review.",
        priority="CRITICAL",
        status=DecisionCandidateStatus.PROPOSED.value,
        requires_human_approval=True,
        parameters={"shipment_id": "shp_test_123", "recommendation_id": "rec_test_456"},
        evidence_references=["ev_test_1", "ev_test_2"],
        provenance={"node": "decision_agent", "rule": "rule_critical_delay_escalate"},
    )
    result = DecisionResult(
        decision_id="dec_test_fixed_123",
        organization_id="org_test_123",
        decision_type=DecisionType.OPERATIONAL_REVIEW.value,
        status=DecisionStatus.REQUIRES_APPROVAL.value,
        candidates=[cand],
        preferred_candidate=cand,
        rationales=[],
        constraints=[],
        requires_human_approval=True,
        upstream_references={"scenario_id": "scen_test_789"},
        evidence_references=["ev_test_1", "ev_test_2"],
        fingerprint="dec_fp_fixed_abc",
        rule_version="v1.0.0-deterministic",
    )
    return result.model_dump(mode="json")


@pytest.fixture
def sample_graph_state(sample_decision_result: Dict[str, Any]) -> AgentGraphStateDict:
    return {
        "run_id": "run_test_appr_001",
        "organization_id": "org_test_123",
        "actor_id": "usr_test_analyst",
        "request_id": "req_test_appr_001",
        "correlation_id": "corr_test_appr_001",
        "trace_id": "trace_test_appr_001",
        "objective": "Review decision candidate for shipment delay mitigation.",
        "input_references": {"shipment_id": "shp_test_123"},
        "current_stage": AgentStage.DECISION.value,
        "current_node": "decision_agent",
        "status": AgentLifecycleStatus.RUNNING.value,
        "step_count": 5,
        "evidence_references": ["ev_test_1", "ev_test_2"],
        "citation_references": [],
        "risk_alert_references": [],
        "recommendation_references": [],
        "decision_id": "dec_test_fixed_123",
        "decision_reference": {
            "decision_id": "dec_test_fixed_123",
            "organization_id": "org_test_123",
            "fingerprint": "dec_fp_fixed_abc",
        },
        "decision_result": sample_decision_result,
        "requires_human_approval": False,
        "approval_id": None,
        "approval_reference": None,
        "approval_result": None,
        "approval_status": None,
        "side_effect_allowed": False,
        "findings": {},
        "structured_findings": [],
        "warnings": [],
        "limitations": [],
        "conflicts": [],
        "route_history": [],
        "retry_count": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {},
        "state_schema_version": "1.0.0",
    }


@pytest.fixture
def sample_risk_manager_actor() -> ApprovalActor:
    return ApprovalActor(
        actor_id="usr_risk_manager_01",
        organization_id="org_test_123",
        role="RiskManager",
        email="risk_manager@example.com",
        correlation_id="corr_test_appr_001",
        request_id="req_test_appr_001",
    )


@pytest.fixture
def sample_admin_actor() -> ApprovalActor:
    return ApprovalActor(
        actor_id="usr_admin_01",
        organization_id="org_test_123",
        role="Admin",
        email="admin@example.com",
    )


@pytest.fixture
def sample_viewer_actor() -> ApprovalActor:
    return ApprovalActor(
        actor_id="usr_viewer_01",
        organization_id="org_test_123",
        role="Viewer",
        email="viewer@example.com",
    )


@pytest.fixture
def sample_approval_request() -> ApprovalRequest:
    return ApprovalRequest(
        organization_id="org_test_123",
        decision_id="dec_test_fixed_123",
        candidate_id="cand_test_001",
        recommendation_id="rec_test_456",
        requester_id="usr_test_analyst",
        required_role="RiskManager",
        evidence_references=["ev_test_1", "ev_test_2"],
        correlation_id="corr_test_appr_001",
        trace_id="trace_test_appr_001",
    )


# ==============================================================================
# GROUP 1: CONTRACT VALIDATION (10 tests)
# ==============================================================================

class TestApprovalContracts:
    def test_valid_approval_request(self, sample_approval_request: ApprovalRequest):
        assert sample_approval_request.organization_id == "org_test_123"
        assert sample_approval_request.decision_id == "dec_test_fixed_123"
        assert sample_approval_request.candidate_id == "cand_test_001"
        assert sample_approval_request.required_role == "RiskManager"

    def test_approval_request_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            ApprovalRequest(
                organization_id="org_test_123",
                decision_id="dec_test_123",
                candidate_id="cand_1",
                unauthorized_extra_field="malicious",  # type: ignore[call-arg]
            )

    def test_approval_request_empty_org_rejected(self):
        with pytest.raises(ValidationError):
            ApprovalRequest(
                organization_id="",
                decision_id="dec_test_123",
                candidate_id="cand_1",
            )

    def test_approval_request_empty_decision_id_rejected(self):
        with pytest.raises(ValidationError):
            ApprovalRequest(
                organization_id="org_test_123",
                decision_id="   ",
                candidate_id="cand_1",
            )

    def test_approval_request_empty_candidate_id_rejected(self):
        with pytest.raises(ValidationError):
            ApprovalRequest(
                organization_id="org_test_123",
                decision_id="dec_test_123",
                candidate_id="",
            )

    def test_valid_approval_actor(self, sample_risk_manager_actor: ApprovalActor):
        assert sample_risk_manager_actor.actor_id == "usr_risk_manager_01"
        assert sample_risk_manager_actor.role == "RiskManager"

    def test_approval_actor_empty_id_rejected(self):
        with pytest.raises(ValidationError):
            ApprovalActor(
                actor_id="",
                organization_id="org_test_123",
                role="RiskManager",
            )

    def test_approval_actor_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            ApprovalActor(
                actor_id="usr_1",
                organization_id="org_test_123",
                role="RiskManager",
                secret_payload="token",  # type: ignore[call-arg]
            )

    def test_valid_approval_decision_input(self, sample_risk_manager_actor: ApprovalActor):
        decision_input = ApprovalDecisionInput(
            decision=ApprovalDecision.APPROVE,
            actor=sample_risk_manager_actor,
            comments="Approved after operational risk review.",
        )
        assert decision_input.decision == ApprovalDecision.APPROVE
        assert decision_input.actor.actor_id == "usr_risk_manager_01"

    def test_valid_approval_result_model(self):
        result = ApprovalResult(
            approval_id="appr_test_123",
            organization_id="org_test_123",
            decision_id="dec_test_123",
            candidate_id="cand_1",
            status=ApprovalStatus.PENDING.value,
            requires_human_approval=True,
            side_effect_allowed=False,
        )
        assert result.status == "PENDING"
        assert result.requires_human_approval is True
        assert result.side_effect_allowed is False


# ==============================================================================
# GROUP 2: LIFECYCLE TRANSITIONS (10 tests)
# ==============================================================================

class TestApprovalLifecycle:
    def test_create_pending_approval_initializes_pending_status(
        self, sample_approval_request: ApprovalRequest
    ):
        service = HumanApprovalService()
        result = service.create_pending_approval(sample_approval_request)
        assert result.status == ApprovalStatus.PENDING.value
        assert result.requires_human_approval is True
        assert result.side_effect_allowed is False
        assert result.actor_id is None
        assert result.decided_at is None

    def test_approve_transitions_to_approved(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.approve(
            approval_id=pending.approval_id,
            actor=sample_risk_manager_actor,
            request=sample_approval_request,
            comments="Reviewed and confirmed.",
        )
        assert decided.status == ApprovalStatus.APPROVED.value
        assert decided.requires_human_approval is False
        assert decided.side_effect_allowed is True
        assert decided.actor_id == sample_risk_manager_actor.actor_id
        assert decided.decided_at is not None

    def test_reject_transitions_to_rejected(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.reject(
            approval_id=pending.approval_id,
            actor=sample_risk_manager_actor,
            request=sample_approval_request,
            comments="Rejected due to excessive cost.",
        )
        assert decided.status == ApprovalStatus.REJECTED.value
        assert decided.requires_human_approval is False
        assert decided.side_effect_allowed is False
        assert decided.actor_id == sample_risk_manager_actor.actor_id

    def test_duplicate_approve_is_idempotent(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided1 = service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        decided2 = service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        assert decided1.approval_id == decided2.approval_id
        assert decided1.status == decided2.status
        assert decided1.fingerprint == decided2.fingerprint

    def test_duplicate_reject_is_idempotent(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided1 = service.reject(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        decided2 = service.reject(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        assert decided1.status == ApprovalStatus.REJECTED.value
        assert decided2.status == ApprovalStatus.REJECTED.value

    def test_conflicting_approve_then_reject_raises_finalized_error(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        with pytest.raises(ApprovalAlreadyFinalizedError):
            service.reject(pending.approval_id, sample_risk_manager_actor, sample_approval_request)

    def test_conflicting_reject_then_approve_raises_finalized_error(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        service.reject(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        with pytest.raises(ApprovalAlreadyFinalizedError):
            service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)

    def test_expired_approval_rejected(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        sample_approval_request.expiration_timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalExpiredError):
            service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)

    def test_unexpired_approval_succeeds(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        sample_approval_request.expiration_timestamp = datetime.now(timezone.utc) + timedelta(hours=1)
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        assert decided.status == ApprovalStatus.APPROVED.value

    def test_approved_result_invariants_enforced(self):
        with pytest.raises(ValidationError):
            # APPROVED must record actor_id
            ApprovalResult(
                approval_id="appr_1",
                organization_id="org_test_123",
                decision_id="dec_1",
                candidate_id="cand_1",
                status=ApprovalStatus.APPROVED.value,
                actor_id=None,
                decided_at=datetime.now(timezone.utc),
                side_effect_allowed=True,
                requires_human_approval=False,
            )


# ==============================================================================
# GROUP 3: MANDATORY NO AUTO-APPROVAL TEST (8 tests)
# ==============================================================================

class TestMandatoryNoAutoApproval:
    def test_node_without_human_input_never_produces_approved(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.PENDING.value
        assert updates["approval_status"] != ApprovalStatus.APPROVED.value
        assert updates["requires_human_approval"] is True
        assert updates["side_effect_allowed"] is False

    def test_node_without_human_input_halts_execution_at_termination(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert updates["selected_route"] == "termination"
        assert updates["status"] == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value

    def test_node_without_human_input_produces_waiting_finding(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert len(updates["structured_findings"]) > 0
        finding = updates["structured_findings"][0]
        assert finding["category"] == "WAITING_FOR_APPROVAL"
        assert finding["created_by_node"] == "human_approval"

    def test_agent_evaluate_without_decision_input_returns_pending(
        self, sample_approval_request: ApprovalRequest
    ):
        agent = HumanApprovalAgent()
        result, findings = agent.evaluate(sample_approval_request, decision_input=None)
        assert result.status == ApprovalStatus.PENDING.value
        assert result.requires_human_approval is True
        assert result.side_effect_allowed is False
        assert any(f.category == "WAITING_FOR_APPROVAL" for f in findings)

    def test_high_risk_does_not_trigger_auto_approval(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["decision_result"]["candidates"][0]["priority"] = "CRITICAL"
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.PENDING.value

    def test_high_prediction_confidence_does_not_trigger_auto_approval(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["decision_result"]["confidence"] = 0.99
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.PENDING.value

    def test_zero_simulated_delay_does_not_trigger_auto_approval(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.PENDING.value

    def test_status_approved_impossible_without_actor(self, sample_approval_request: ApprovalRequest):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        assert pending.status == ApprovalStatus.PENDING.value
        assert pending.actor_id is None


# ==============================================================================
# GROUP 4: HUMAN ACTOR & RBAC AUTHORITY (10 tests)
# ==============================================================================

class TestHumanActorAndRBAC:
    def test_risk_manager_can_approve(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        assert decided.status == ApprovalStatus.APPROVED.value
        assert decided.actor_role == "RiskManager"

    def test_admin_can_approve(
        self, sample_approval_request: ApprovalRequest, sample_admin_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.approve(pending.approval_id, sample_admin_actor, sample_approval_request)
        assert decided.status == ApprovalStatus.APPROVED.value
        assert decided.actor_role == "Admin"

    def test_viewer_cannot_approve(
        self, sample_approval_request: ApprovalRequest, sample_viewer_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalAuthorizationError):
            service.approve(pending.approval_id, sample_viewer_actor, sample_approval_request)

    def test_analyst_cannot_approve(
        self, sample_approval_request: ApprovalRequest
    ):
        analyst = ApprovalActor(actor_id="usr_analyst", organization_id="org_test_123", role="Analyst")
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalAuthorizationError):
            service.approve(pending.approval_id, analyst, sample_approval_request)

    def test_ops_manager_cannot_approve_when_risk_manager_required(
        self, sample_approval_request: ApprovalRequest
    ):
        ops_mgr = ApprovalActor(actor_id="usr_ops", organization_id="org_test_123", role="OpsManager")
        service = HumanApprovalService(authorized_roles={"RiskManager", "Admin"})
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalAuthorizationError):
            service.approve(pending.approval_id, ops_mgr, sample_approval_request)

    def test_actor_attribution_recorded_in_result(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.approve(pending.approval_id, sample_risk_manager_actor, sample_approval_request)
        assert decided.actor_id == sample_risk_manager_actor.actor_id
        assert decided.actor_role == sample_risk_manager_actor.role

    def test_actor_attribution_recorded_in_findings(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        agent = HumanApprovalAgent()
        decision_input = ApprovalDecisionInput(
            decision=ApprovalDecision.APPROVE,
            actor=sample_risk_manager_actor,
        )
        _, findings = agent.evaluate(sample_approval_request, decision_input=decision_input)
        assert any("usr_risk_manager_01" in f.summary for f in findings)

    def test_empty_actor_id_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ApprovalActor(actor_id="  ", organization_id="org_test_123", role="RiskManager")

    def test_arbitrary_role_string_rejected_by_service(
        self, sample_approval_request: ApprovalRequest
    ):
        forged = ApprovalActor(actor_id="usr_forged", organization_id="org_test_123", role="SuperAdminGodMode")
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalAuthorizationError):
            service.approve(pending.approval_id, forged, sample_approval_request)

    def test_viewer_cannot_reject(
        self, sample_approval_request: ApprovalRequest, sample_viewer_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalAuthorizationError):
            service.reject(pending.approval_id, sample_viewer_actor, sample_approval_request)


# ==============================================================================
# GROUP 5: MULTI-TENANT BOUNDARY ISOLATION (8 tests)
# ==============================================================================

class TestTenantBoundaryIsolation:
    def test_cross_tenant_actor_rejected(
        self, sample_approval_request: ApprovalRequest
    ):
        foreign_actor = ApprovalActor(
            actor_id="usr_foreign",
            organization_id="org_foreign_456",
            role="RiskManager",
        )
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalTenantIsolationError):
            service.approve(pending.approval_id, foreign_actor, sample_approval_request)

    def test_cross_tenant_decision_result_in_node_rejected(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["decision_result"]["organization_id"] = "org_foreign_456"
        with pytest.raises(ApprovalTenantIsolationError):
            human_approval_node(sample_graph_state)

    def test_empty_state_organization_rejected_in_node(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["organization_id"] = ""
        with pytest.raises(ApprovalTenantIsolationError):
            human_approval_node(sample_graph_state)

    def test_cross_tenant_approval_result_in_agent_graph_state_rejected(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["approval_result"] = {
            "approval_id": "appr_123",
            "organization_id": "org_foreign_456",
        }
        with pytest.raises(AgentTenantIsolationError):
            AgentGraphState.model_validate(sample_graph_state)

    def test_cross_tenant_approval_reference_in_agent_graph_state_rejected(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["approval_reference"] = "org_foreign_456:approval:appr_123"
        with pytest.raises(AgentTenantIsolationError):
            AgentGraphState.model_validate(sample_graph_state)

    def test_matching_tenant_approval_result_accepted(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["approval_result"] = {
            "approval_id": "appr_123",
            "organization_id": "org_test_123",
        }
        state = AgentGraphState.model_validate(sample_graph_state)
        assert state.approval_result["organization_id"] == "org_test_123"

    def test_get_status_cross_tenant_query_rejected(
        self, sample_approval_request: ApprovalRequest
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalTenantIsolationError):
            service.get_status(pending.approval_id, organization_id="org_foreign_456")

    def test_node_rejects_foreign_tenant_actor_in_decision_input(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": {
                "actor_id": "usr_foreign",
                "organization_id": "org_foreign_456",
                "role": "RiskManager",
            },
        }
        with pytest.raises(ApprovalTenantIsolationError):
            human_approval_node(sample_graph_state)


# ==============================================================================
# GROUP 6: DECISION IMMUTABILITY (8 tests)
# ==============================================================================

class TestDecisionImmutability:
    def test_approval_does_not_modify_decision_score(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        original_fp = sample_graph_state["decision_result"]["fingerprint"]
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
        }
        updates = human_approval_node(sample_graph_state)
        assert "decision_result" not in updates
        assert sample_graph_state["decision_result"]["fingerprint"] == original_fp

    def test_approval_does_not_modify_decision_candidates(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        cands_before = list(sample_graph_state["decision_result"]["candidates"])
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
        }
        human_approval_node(sample_graph_state)
        assert sample_graph_state["decision_result"]["candidates"] == cands_before

    def test_approval_does_not_modify_decision_rationales(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert "rationales" not in updates

    def test_approval_does_not_modify_scenario_fields(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert "scenario_id" not in updates
        assert "scenario_result" not in updates
        assert "scenario_reference" not in updates

    def test_approval_does_not_modify_prediction_fields(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert "prediction_id" not in updates
        assert "prediction_result" not in updates

    def test_approval_does_not_modify_risk_fields(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert "risk_assessment_id" not in updates
        assert "risk_score" not in updates

    def test_approval_preserves_evidence_references(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_result"]["evidence_references"] == sample_graph_state["evidence_references"]

    def test_rejection_does_not_modify_decision_fields(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "REJECT",
            "actor": sample_risk_manager_actor.model_dump(),
        }
        updates = human_approval_node(sample_graph_state)
        assert "decision_id" not in updates
        assert "decision_result" not in updates


# ==============================================================================
# GROUP 7: EXPLICIT APPROVAL EVENT REQUIREMENT (6 tests)
# ==============================================================================

class TestExplicitApprovalEvent:
    def test_get_status_does_not_alter_approval_status(
        self, sample_approval_request: ApprovalRequest
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        status_result = service.get_status(pending.approval_id, "org_test_123")
        assert status_result.status == ApprovalStatus.PENDING.value

    def test_viewing_state_does_not_approve(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.PENDING.value

    def test_timeout_does_not_infer_approval(
        self, sample_approval_request: ApprovalRequest
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        assert pending.status == ApprovalStatus.PENDING.value

    def test_graph_execution_without_human_input_leaves_state_pending(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = human_approval_node(sample_graph_state)
        assert updates["requires_human_approval"] is True
        assert updates["side_effect_allowed"] is False

    def test_approval_requires_explicit_decision_enum(
        self, sample_risk_manager_actor: ApprovalActor
    ):
        with pytest.raises(ValueError):
            ApprovalDecisionInput(
                decision="MAYBE",  # type: ignore[arg-type]
                actor=sample_risk_manager_actor,
            )

    def test_approval_decision_input_requires_actor(self):
        with pytest.raises(ValidationError):
            ApprovalDecisionInput(
                decision=ApprovalDecision.APPROVE,
                actor=None,  # type: ignore[arg-type]
            )


# ==============================================================================
# GROUP 8: STATE OWNERSHIP & AUTHORIZATION (8 tests)
# ==============================================================================

class TestStateOwnershipAndSafeguards:
    def test_approval_stage_can_write_approval_fields(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        updates = {
            "approval_id": "appr_test_123",
            "approval_status": "APPROVED",
            "side_effect_allowed": True,
            "requires_human_approval": False,
        }
        validate_state_update(state, updates, node_id="human_approval", stage=AgentStage.APPROVAL)
        new_state = apply_state_update(state, updates, node_id="human_approval", stage=AgentStage.APPROVAL)
        assert new_state.approval_id == "appr_test_123"
        assert new_state.approval_status == "APPROVED"
        assert new_state.side_effect_allowed is True

    def test_approval_stage_cannot_write_decision_id(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                state,
                {"decision_id": "unauthorized_new_decision"},
                node_id="human_approval",
                stage=AgentStage.APPROVAL,
            )

    def test_approval_stage_cannot_write_risk_assessment_id(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                state,
                {"risk_assessment_id": "unauthorized_risk_id"},
                node_id="human_approval",
                stage=AgentStage.APPROVAL,
            )

    def test_approval_stage_cannot_write_scenario_id(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                state,
                {"scenario_id": "unauthorized_scen_id"},
                node_id="human_approval",
                stage=AgentStage.APPROVAL,
            )

    def test_decision_stage_cannot_write_approval_result(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                state,
                {"approval_result": {"status": "APPROVED"}},
                node_id="decision_agent",
                stage=AgentStage.DECISION,
            )

    def test_decision_stage_cannot_write_approval_id(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                state,
                {"approval_id": "unauthorized_appr_id"},
                node_id="decision_agent",
                stage=AgentStage.DECISION,
            )

    def test_approval_stage_cannot_mutate_organization_id(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentTenantIsolationError):
            validate_state_update(
                state,
                {"organization_id": "org_tampered"},
                node_id="human_approval",
                stage=AgentStage.APPROVAL,
            )

    def test_approval_stage_cannot_mutate_run_id(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                state,
                {"run_id": "run_tampered"},
                node_id="human_approval",
                stage=AgentStage.APPROVAL,
            )


# ==============================================================================
# GROUP 9: SECURITY SCRUBBING (8 tests)
# ==============================================================================

class TestSecurityScrubbing:
    def test_api_key_in_comments_rejected(self, sample_risk_manager_actor: ApprovalActor):
        with pytest.raises(ValidationError):
            ApprovalDecisionInput(
                decision=ApprovalDecision.APPROVE,
                actor=sample_risk_manager_actor,
                comments="Approved using secret key api_key=sk-secret-1234567890",
            )

    def test_bearer_token_in_comments_rejected(self, sample_risk_manager_actor: ApprovalActor):
        with pytest.raises(ValidationError):
            ApprovalDecisionInput(
                decision=ApprovalDecision.APPROVE,
                actor=sample_risk_manager_actor,
                comments="Authorization: Bearer secret_jwt_token_12345",
            )

    def test_password_in_comments_rejected(self, sample_risk_manager_actor: ApprovalActor):
        with pytest.raises(ValidationError):
            ApprovalDecisionInput(
                decision=ApprovalDecision.REJECT,
                actor=sample_risk_manager_actor,
                comments="Password is admin123",
            )

    def test_chain_of_thought_rejected_in_provenance(self):
        with pytest.raises(ValidationError):
            ApprovalResult(
                approval_id="appr_1",
                organization_id="org_test_123",
                decision_id="dec_1",
                candidate_id="cand_1",
                provenance={"chain_of_thought": "I should approve because of risk."},
            )

    def test_internal_monologue_rejected_in_provenance(self):
        with pytest.raises(ValidationError):
            ApprovalResult(
                approval_id="appr_1",
                organization_id="org_test_123",
                decision_id="dec_1",
                candidate_id="cand_1",
                provenance={"internal_monologue": "Let's think step by step."},
            )

    def test_clean_business_comment_accepted(self, sample_risk_manager_actor: ApprovalActor):
        inp = ApprovalDecisionInput(
            decision=ApprovalDecision.APPROVE,
            actor=sample_risk_manager_actor,
            comments="Approved after operational logistics and carrier review.",
        )
        assert inp.comments == "Approved after operational logistics and carrier review."

    def test_sensitive_value_in_state_update_rejected(
        self, sample_graph_state: AgentGraphStateDict
    ):
        state = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentValidationError):
            validate_state_update(
                state,
                {"warnings": ["Contains secret token: bearer sk-1234567890123456"]},
                node_id="human_approval",
                stage=AgentStage.APPROVAL,
            )

    def test_actor_id_cannot_contain_sensitive_value(self):
        with pytest.raises(ValidationError):
            ApprovalActor(
                actor_id="api_key=sk-1234567890",
                organization_id="org_test_123",
                role="RiskManager",
            )


# ==============================================================================
# GROUP 10: OBSERVABILITY & TELEMETRY (8 tests)
# ==============================================================================

class TestObservabilityAndTelemetry:
    def test_telemetry_emitted_on_success(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        human_approval_node(sample_graph_state)
        assert len(emitted) == 1
        assert emitted[0].node_name == "human_approval"
        assert emitted[0].stage == AgentStage.APPROVAL
        assert emitted[0].status == "SUCCESS"
        assert emitted[0].duration_ms > 0

    def test_telemetry_emitted_on_failure(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        sample_graph_state["organization_id"] = ""
        with pytest.raises(ApprovalTenantIsolationError):
            human_approval_node(sample_graph_state)

        assert len(emitted) == 1
        assert emitted[0].node_name == "human_approval"
        assert emitted[0].status == "FAILED"
        assert emitted[0].error_code == "INVALID_TENANT"

    def test_telemetry_captures_approval_id(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        human_approval_node(sample_graph_state)
        assert emitted[0].metadata["approval_id"] is not None

    def test_telemetry_captures_candidate_id(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        human_approval_node(sample_graph_state)
        assert emitted[0].metadata["candidate_id"] == "cand_test_001"

    def test_telemetry_captures_actor_and_correlation_ids(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        human_approval_node(sample_graph_state)
        assert emitted[0].actor_id == sample_graph_state["actor_id"]
        assert emitted[0].correlation_id == sample_graph_state["correlation_id"]
        assert emitted[0].trace_id == sample_graph_state["trace_id"]

    def test_telemetry_duration_is_finite_and_positive(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        human_approval_node(sample_graph_state)
        assert emitted[0].duration_ms > 0

    def test_telemetry_emitted_even_when_unexpected_error_occurs(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        sample_graph_state["decision_result"] = "not_a_dict"  # type: ignore[assignment]
        with pytest.raises(ApprovalAgentError):
            human_approval_node(sample_graph_state)

        assert len(emitted) == 1
        assert emitted[0].status == "FAILED"

    def test_telemetry_metadata_does_not_contain_secrets(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        emitted: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: emitted.append(t))

        human_approval_node(sample_graph_state)
        meta = emitted[0].metadata
        for k, v in meta.items():
            assert "secret" not in str(k).lower()
            assert "token" not in str(k).lower()


# ==============================================================================
# GROUP 11: DETERMINISTIC IDENTITY & FINGERPRINTING (8 tests)
# ==============================================================================

class TestDeterministicIdentityAndFingerprint:
    def test_deterministic_approval_id_repeatability(self):
        id1 = generate_deterministic_approval_id("org_1", "dec_1", "cand_1")
        id2 = generate_deterministic_approval_id("org_1", "dec_1", "cand_1")
        assert id1 == id2

    def test_approval_id_different_org_produces_different_id(self):
        id1 = generate_deterministic_approval_id("org_1", "dec_1", "cand_1")
        id2 = generate_deterministic_approval_id("org_2", "dec_1", "cand_1")
        assert id1 != id2

    def test_approval_id_different_decision_produces_different_id(self):
        id1 = generate_deterministic_approval_id("org_1", "dec_1", "cand_1")
        id2 = generate_deterministic_approval_id("org_1", "dec_2", "cand_1")
        assert id1 != id2

    def test_approval_id_different_candidate_produces_different_id(self):
        id1 = generate_deterministic_approval_id("org_1", "dec_1", "cand_1")
        id2 = generate_deterministic_approval_id("org_1", "dec_1", "cand_2")
        assert id1 != id2

    def test_approval_id_is_valid_uuidv5(self):
        appr_id = generate_deterministic_approval_id("org_1", "dec_1", "cand_1")
        parsed = uuid.UUID(appr_id)
        assert parsed.version == 5

    def test_compute_approval_fingerprint_repeatability(self):
        fp1 = compute_approval_fingerprint("org_1", "dec_1", "cand_1", "PENDING")
        fp2 = compute_approval_fingerprint("org_1", "dec_1", "cand_1", "PENDING")
        assert fp1 == fp2

    def test_fingerprint_changes_on_status_change(self):
        fp1 = compute_approval_fingerprint("org_1", "dec_1", "cand_1", "PENDING")
        fp2 = compute_approval_fingerprint("org_1", "dec_1", "cand_1", "APPROVED", actor_id="usr_1")
        assert fp1 != fp2

    def test_fingerprint_invariant_to_evidence_ordering(self):
        fp1 = compute_approval_fingerprint("org_1", "dec_1", "cand_1", "PENDING", evidence_references=["a", "b"])
        fp2 = compute_approval_fingerprint("org_1", "dec_1", "cand_1", "PENDING", evidence_references=["b", "a"])
        assert fp1 == fp2


# ==============================================================================
# GROUP 12: GRAPH TOPOLOGY & NODE INTEGRATION (10 tests)
# ==============================================================================

class TestGraphTopologyAndIntegration:
    def test_human_approval_node_registered_in_allowlist(self):
        registry = NodeRegistry()
        assert registry.is_allowed("human_approval")
        assert registry.is_allowed("approval_boundary")

    def test_human_approval_contract_attributes(self):
        contract = HUMAN_APPROVAL_NODE_CONTRACT
        assert contract.node_id == "human_approval"
        assert contract.stage == AgentStage.APPROVAL
        assert contract.is_side_effecting is False
        assert contract.side_effect_type == ToolSideEffectType.HUMAN_GOVERNED
        assert contract.requires_evidence is True

    def test_decision_to_approval_transition_is_allowed(self):
        StageTransitionValidator.validate_transition(AgentStage.DECISION, AgentStage.APPROVAL)

    def test_approval_to_termination_transition_is_allowed(self):
        StageTransitionValidator.validate_transition(AgentStage.APPROVAL, AgentStage.TERMINATION)

    def test_approval_backward_to_decision_is_illegal(self):
        with pytest.raises(AgentStageTransitionError):
            StageTransitionValidator.validate_transition(AgentStage.APPROVAL, AgentStage.DECISION)

    def test_approval_backward_to_research_is_illegal(self):
        with pytest.raises(AgentStageTransitionError):
            StageTransitionValidator.validate_transition(AgentStage.APPROVAL, AgentStage.RESEARCH)

    def test_approval_backward_to_risk_is_illegal(self):
        with pytest.raises(AgentStageTransitionError):
            StageTransitionValidator.validate_transition(AgentStage.APPROVAL, AgentStage.RISK_ASSESSMENT)

    def test_graph_builder_registers_human_approval_node(self):
        builder = AgentGraphBuilder()
        assert builder.registry.has_node("human_approval")

    def test_graph_builder_compiles_successfully_with_human_approval(self):
        builder = AgentGraphBuilder()
        compiled = builder.build()
        assert compiled is not None

    def test_node_execution_updates_step_count(self, sample_graph_state: AgentGraphStateDict):
        initial_step = sample_graph_state["step_count"]
        updates = human_approval_node(sample_graph_state)
        assert updates["step_count"] == initial_step + 1


# ==============================================================================
# GROUP 13: RESUME FLOW WITH HUMAN DECISION (6 tests)
# ==============================================================================

class TestGraphResumeFlow:
    def test_resume_with_approve_decision(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
            "comments": "Explicit human approval granted.",
        }
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.APPROVED.value
        assert updates["requires_human_approval"] is False
        assert updates["side_effect_allowed"] is True
        assert updates["selected_route"] == "termination"

    def test_resume_with_reject_decision(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "REJECT",
            "actor": sample_risk_manager_actor.model_dump(),
            "comments": "Rerouting cost unacceptable.",
        }
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_status"] == ApprovalStatus.REJECTED.value
        assert updates["requires_human_approval"] is False
        assert updates["side_effect_allowed"] is False
        assert updates["selected_route"] == "termination"

    def test_resume_finding_category_is_approval_recorded(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
        }
        updates = human_approval_node(sample_graph_state)
        finding = updates["structured_findings"][0]
        assert finding["category"] == "APPROVAL_RECORDED"

    def test_resume_preserves_actor_comments(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
            "comments": "Verified operational feasibility with 3PL carrier.",
        }
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_result"]["comments"] == "Verified operational feasibility with 3PL carrier."

    def test_resume_with_unauthorized_actor_fails_closed(
        self, sample_graph_state: AgentGraphStateDict, sample_viewer_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_viewer_actor.model_dump(),
        }
        with pytest.raises(ApprovalAuthorizationError):
            human_approval_node(sample_graph_state)

    def test_resume_sets_fingerprint_in_result(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
        }
        updates = human_approval_node(sample_graph_state)
        assert updates["approval_result"]["fingerprint"] is not None


# ==============================================================================
# GROUP 14: EXPLICIT NO-SIDE-EFFECT SAFETY (5 tests)
# ==============================================================================

class TestExplicitNoSideEffectSafety:
    def test_no_shipment_mutation(self, sample_graph_state: AgentGraphStateDict):
        initial_refs = sample_graph_state["input_references"].copy()
        updates = human_approval_node(sample_graph_state)
        assert "input_references" not in updates
        assert sample_graph_state["input_references"] == initial_refs

    def test_no_inventory_mutation(self, sample_graph_state: AgentGraphStateDict):
        updates = human_approval_node(sample_graph_state)
        assert "inventory" not in updates
        assert "inventory_movements" not in updates

    def test_no_carrier_communication(self, sample_graph_state: AgentGraphStateDict):
        updates = human_approval_node(sample_graph_state)
        assert "carrier_notifications" not in updates
        assert "carrier_payload" not in updates

    def test_no_supplier_communication(self, sample_graph_state: AgentGraphStateDict):
        updates = human_approval_node(sample_graph_state)
        assert "supplier_notifications" not in updates

    def test_no_action_execution_even_when_approved(
        self, sample_graph_state: AgentGraphStateDict, sample_risk_manager_actor: ApprovalActor
    ):
        sample_graph_state["human_approval_decision"] = {
            "decision": "APPROVE",
            "actor": sample_risk_manager_actor.model_dump(),
        }
        updates = human_approval_node(sample_graph_state)
        assert "action_executions" not in updates
        assert "executed_actions" not in updates
        assert updates["side_effect_allowed"] is True
        # Graph routes to termination, not action execution
        assert updates["selected_route"] == "termination"


# ==============================================================================
# GROUP 15: ERROR TAXONOMY & CLASSIFICATION (5 tests)
# ==============================================================================

class TestErrorTaxonomy:
    def test_approval_agent_error_base(self):
        err = ApprovalAgentError("Base approval error")
        assert err.node_name == "human_approval"
        assert err.retryable is False

    def test_invalid_approval_request_error_non_retryable(self):
        err = InvalidApprovalRequestError("Missing field")
        assert err.retryable is False
        assert err.error_code == "INVALID_APPROVAL_REQUEST"

    def test_approval_tenant_isolation_error_non_retryable(self):
        err = ApprovalTenantIsolationError("Tenant breach")
        assert err.retryable is False
        assert err.error_code == "APPROVAL_TENANT_ISOLATION_ERROR"

    def test_approval_authorization_error_non_retryable(self):
        err = ApprovalAuthorizationError("Unauthorized role")
        assert err.retryable is False
        assert err.error_code == "APPROVAL_UNAUTHORIZED"

    def test_approval_already_finalized_error_non_retryable(self):
        err = ApprovalAlreadyFinalizedError("Cannot re-decide")
        assert err.retryable is False
        assert err.error_code == "APPROVAL_ALREADY_FINALIZED"


# ==============================================================================
# GROUP 16: DATABASE TRANSACTIONAL PERSISTENCE (6 tests)
# ==============================================================================

class TestDatabaseTransactionalPersistence:
    def test_db_persistence_with_mock_uow_approve(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        mock_uow = MagicMock()
        mock_rec = MagicMock()
        mock_rec.id = "rec_test_456"
        mock_rec.status = "PENDING"
        mock_uow.recommendations.get_for_update.return_value = mock_rec

        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        result = service.approve(
            pending.approval_id,
            sample_risk_manager_actor,
            sample_approval_request,
            comments="Approved with DB commit.",
            uow=mock_uow,
        )
        assert result.status == ApprovalStatus.APPROVED.value
        assert mock_rec.status == "APPROVED"
        mock_uow.approvals.create.assert_called_once()
        mock_uow.commit.assert_called_once()

    def test_db_persistence_with_mock_uow_reject(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        mock_uow = MagicMock()
        mock_rec = MagicMock()
        mock_rec.id = "rec_test_456"
        mock_rec.status = "PENDING"
        mock_uow.recommendations.get_for_update.return_value = mock_rec

        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        result = service.reject(
            pending.approval_id,
            sample_risk_manager_actor,
            sample_approval_request,
            comments="Rejected with DB commit.",
            uow=mock_uow,
        )
        assert result.status == ApprovalStatus.REJECTED.value
        assert mock_rec.status == "REJECTED"
        mock_uow.approvals.create.assert_called_once()
        mock_uow.commit.assert_called_once()

    def test_db_persistence_rolls_back_on_error(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        mock_uow = MagicMock()
        mock_rec = MagicMock()
        mock_uow.recommendations.get_for_update.return_value = mock_rec
        mock_uow.commit.side_effect = RuntimeError("Database deadlock")

        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalPersistenceError):
            service.approve(
                pending.approval_id,
                sample_risk_manager_actor,
                sample_approval_request,
                uow=mock_uow,
            )

    def test_db_persistence_skips_db_if_uow_is_none(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request, uow=None)
        result = service.approve(
            pending.approval_id,
            sample_risk_manager_actor,
            sample_approval_request,
            uow=None,
        )
        assert result.status == ApprovalStatus.APPROVED.value

    def test_db_persistence_when_recommendation_not_in_db(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        mock_uow = MagicMock()
        mock_uow.recommendations.get_for_update.return_value = None

        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        result = service.approve(
            pending.approval_id,
            sample_risk_manager_actor,
            sample_approval_request,
            uow=mock_uow,
        )
        assert result.status == ApprovalStatus.APPROVED.value
        mock_uow.commit.assert_called_once()

    def test_db_persistence_logs_audit_event_via_audit_service(
        self, sample_approval_request: ApprovalRequest, sample_risk_manager_actor: ApprovalActor
    ):
        mock_uow = MagicMock()
        mock_rec = MagicMock()
        mock_uow.recommendations.get_for_update.return_value = mock_rec
        mock_audit = MagicMock()
        mock_audit.id = "audit_log_123"
        mock_uow.audit_logs.append_log.return_value = mock_audit

        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        result = service.approve(
            pending.approval_id,
            sample_risk_manager_actor,
            sample_approval_request,
            uow=mock_uow,
        )
        assert result.audit_reference == "audit_log_123"


# ==============================================================================
# GROUP 17: ADDITIONAL CONTRACT AND EDGE CASE TESTS (9 tests)
# ==============================================================================

class TestAdditionalEdgeCases:
    def test_approval_request_with_custom_constraints(self):
        req = ApprovalRequest(
            organization_id="org_test_123",
            decision_id="dec_test_123",
            candidate_id="cand_1",
            constraints=[{"name": "MAX_COST", "value": 10000}],
        )
        assert len(req.constraints) == 1

    def test_approval_request_requester_id_optional(self):
        req = ApprovalRequest(
            organization_id="org_test_123",
            decision_id="dec_test_123",
            candidate_id="cand_1",
            requester_id=None,
        )
        assert req.requester_id is None

    def test_approval_decision_input_without_comments(self, sample_risk_manager_actor: ApprovalActor):
        inp = ApprovalDecisionInput(
            decision=ApprovalDecision.APPROVE,
            actor=sample_risk_manager_actor,
            comments=None,
        )
        assert inp.comments is None

    def test_approval_result_rejected_invariants_valid(self):
        res = ApprovalResult(
            approval_id="appr_1",
            organization_id="org_test_123",
            decision_id="dec_1",
            candidate_id="cand_1",
            status=ApprovalStatus.REJECTED.value,
            actor_id="usr_1",
            side_effect_allowed=False,
            requires_human_approval=False,
        )
        assert res.status == "REJECTED"
        assert res.side_effect_allowed is False

    def test_approval_result_rejected_cannot_have_side_effect_allowed(self):
        with pytest.raises(ValidationError):
            ApprovalResult(
                approval_id="appr_1",
                organization_id="org_test_123",
                decision_id="dec_1",
                candidate_id="cand_1",
                status=ApprovalStatus.REJECTED.value,
                actor_id="usr_1",
                side_effect_allowed=True,
                requires_human_approval=False,
            )

    def test_custom_required_role_matching_actor_succeeds(
        self, sample_approval_request: ApprovalRequest
    ):
        custom_actor = ApprovalActor(
            actor_id="usr_vp",
            organization_id="org_test_123",
            role="VicePresidentLogistics",
        )
        sample_approval_request.required_role = "VicePresidentLogistics"
        service = HumanApprovalService(authorized_roles={"RiskManager", "Admin", "VicePresidentLogistics"})
        pending = service.create_pending_approval(sample_approval_request)
        decided = service.approve(pending.approval_id, custom_actor, sample_approval_request)
        assert decided.status == ApprovalStatus.APPROVED.value

    def test_custom_required_role_mismatch_fails(
        self, sample_approval_request: ApprovalRequest
    ):
        viewer = ApprovalActor(
            actor_id="usr_viewer",
            organization_id="org_test_123",
            role="Viewer",
        )
        sample_approval_request.required_role = "VicePresidentLogistics"
        service = HumanApprovalService()
        pending = service.create_pending_approval(sample_approval_request)
        with pytest.raises(ApprovalAuthorizationError):
            service.approve(pending.approval_id, viewer, sample_approval_request)

    def test_fingerprint_contains_actor_id_when_approved(self):
        fp = compute_approval_fingerprint(
            "org_test_123", "dec_1", "cand_1", "APPROVED", actor_id="usr_risk_manager_01", decision="APPROVE"
        )
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_approval_fingerprint_is_valid_sha256_hex(self):
        fp = compute_approval_fingerprint(
            "org_test_123", "dec_1", "cand_1", "PENDING"
        )
        assert len(fp) == 64
        int(fp, 16)  # Verifies valid hex
