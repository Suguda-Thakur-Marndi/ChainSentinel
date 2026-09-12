"""Phase 16 Test Suite: LangGraph Multi-Agent Pipeline Integration.

Validates:
- Decision Agent -> Human Approval Agent pipeline handoff
- human_approval_node execution:
    - Pending evaluation halts execution with requires_human_approval=True and side_effect_allowed=False
    - Approved evaluation sets requires_human_approval=False and side_effect_allowed=True
    - Rejected evaluation sets requires_human_approval=False and side_effect_allowed=False
- Zero autonomous approval invariant throughout the agent pipeline
- State validation and authoritative field ownership rules
"""

from __future__ import annotations

from typing import Any, Dict, cast
import pytest

from app.agents.approval.agent import HumanApprovalAgent
from app.agents.approval.contract import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalRequest,
    ApprovalStatus,
)
from app.agents.approval.node import human_approval_node
from app.agents.contracts import (
    AgentGraphStateDict,
    AgentStage,
    validate_state_update,
)
from app.agents.decision.node import decision_node


def test_decision_node_routes_to_approval_when_required():
    """Verify decision_node sets route to approval_boundary when candidates require sign-off."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_integ_001",
            "organization_id": "tenant_alpha",
            "actor_id": "user_analyst",
            "current_stage": AgentStage.DECISION.value,
            "objective": "Mitigate severe port disruption",
            "candidate_alternatives": [
                {
                    "alternative_id": "alt_expensive_air",
                    "title": "Air Freight Expedite",
                    "cost": 50000.0,
                    "is_feasible": True,
                    "requires_approval": True,
                }
            ],
            "use_claude": False,
        },
    )
    update = decision_node(state)
    assert update["decision_id"] is not None
    assert update["selected_route"] == "approval_boundary"
    assert "Candidate requires human approval" in update["route_reason"]


def test_human_approval_node_pending_state_evaluation():
    """Verify human_approval_node without human decision halts and sets pending governance flags."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_integ_002",
            "organization_id": "tenant_alpha",
            "actor_id": "user_analyst",
            "current_stage": AgentStage.APPROVAL.value,
            "decision_id": "dec_integ_002",
            "decision_result": {
                "decision_id": "dec_integ_002",
                "organization_id": "tenant_alpha",
                "status": "PENDING",
                "preferred_candidate": {
                    "candidate_id": "alt_reroute_ocean",
                    "action_type": "REROUTE_SHIPMENT",
                    "title": "Ocean Corridor Shift",
                },
            },
        },
    )

    update = human_approval_node(state)

    assert update["approval_id"] is not None
    assert update["approval_status"] == ApprovalStatus.PENDING.value
    assert update["requires_human_approval"] is True
    assert update["side_effect_allowed"] is False
    assert any(f["category"] == "WAITING_FOR_APPROVAL" for f in update["structured_findings"])

    # Validate state update rules
    validate_state_update(state, update, writer_node_id="human_approval", writer_stage=AgentStage.APPROVAL)


def test_human_approval_node_approved_state_evaluation():
    """Verify human_approval_node with human sign-off transitions to approved and allows side effects."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_integ_003",
            "organization_id": "tenant_alpha",
            "actor_id": "user_analyst",
            "current_stage": AgentStage.APPROVAL.value,
            "decision_id": "dec_integ_003",
            "decision_result": {
                "decision_id": "dec_integ_003",
                "organization_id": "tenant_alpha",
                "status": "PENDING",
                "preferred_candidate": {
                    "candidate_id": "alt_reroute_ocean",
                    "action_type": "REROUTE_SHIPMENT",
                },
            },
            "approval_input": {
                "decision": "APPROVE",
                "actor": {
                    "actor_id": "user_risk_lead",
                    "organization_id": "tenant_alpha",
                    "role": "RiskManager",
                },
                "comments": "Approved operational mitigation.",
            },
        },
    )

    update = human_approval_node(state)

    assert update["approval_id"] is not None
    assert update["approval_status"] == ApprovalStatus.APPROVED.value
    assert update["requires_human_approval"] is False
    assert update["side_effect_allowed"] is True
    assert any(f["category"] == "APPROVAL_RECORDED" for f in update["structured_findings"])

    # Validate state update rules
    validate_state_update(state, update, writer_node_id="human_approval", writer_stage=AgentStage.APPROVAL)


def test_human_approval_node_rejected_state_evaluation():
    """Verify human_approval_node with human rejection forbids side effects."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_integ_004",
            "organization_id": "tenant_alpha",
            "actor_id": "user_analyst",
            "current_stage": AgentStage.APPROVAL.value,
            "decision_id": "dec_integ_004",
            "decision_result": {
                "decision_id": "dec_integ_004",
                "organization_id": "tenant_alpha",
                "status": "PENDING",
                "preferred_candidate": {
                    "candidate_id": "alt_reroute_ocean",
                    "action_type": "REROUTE_SHIPMENT",
                },
            },
            "approval_input": {
                "decision": "REJECT",
                "actor": {
                    "actor_id": "user_risk_lead",
                    "organization_id": "tenant_alpha",
                    "role": "RiskManager",
                },
                "comments": "Cost prohibitive.",
            },
        },
    )

    update = human_approval_node(state)

    assert update["approval_status"] == ApprovalStatus.REJECTED.value
    assert update["requires_human_approval"] is False
    assert update["side_effect_allowed"] is False
    assert any(f["category"] == "APPROVAL_RECORDED" for f in update["structured_findings"])


def test_human_approval_agent_direct_evaluation():
    """Verify HumanApprovalAgent evaluate logic with both branches."""
    agent = HumanApprovalAgent()
    req = ApprovalRequest(
        organization_id="tenant_alpha",
        decision_id="dec_direct_01",
        candidate_id="cand_01",
        required_role="RiskManager",
    )

    # Branch 1: Pending
    res_pending, findings_pending = agent.evaluate(req)
    assert res_pending.status == ApprovalStatus.PENDING.value
    assert res_pending.requires_human_approval is True
    assert res_pending.side_effect_allowed is False
    assert len(findings_pending) == 1
    assert findings_pending[0].category == "WAITING_FOR_APPROVAL"

    # Branch 2: Approved
    dec_input = ApprovalDecisionInput(
        decision=ApprovalDecision.APPROVE,
        actor=ApprovalActor(actor_id="user_admin", organization_id="tenant_alpha", role="Admin"),
        comments="Approved by Admin",
    )
    res_approved, findings_approved = agent.evaluate(req, decision_input=dec_input)
    assert res_approved.status == ApprovalStatus.APPROVED.value
    assert res_approved.requires_human_approval is False
    assert res_approved.side_effect_allowed is True
    assert len(findings_approved) == 1
    assert findings_approved[0].category == "APPROVAL_RECORDED"
