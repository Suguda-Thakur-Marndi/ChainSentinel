"""Phase 17 Test Suite: LangGraph Multi-Agent Pipeline Integration.

Validates:
- Decision Agent -> Human Approval Agent -> Action Agent handoff
- action_node execution:
    - Successfully executes when approval is APPROVED
    - Halts with ActionApprovalMissingError or ActionApprovalInvalidError if unapproved
    - Updates authoritative state fields (action_id, action_reference, action_status, action_result)
    - Routes to termination (selected_route="termination"), strictly halting before Phase 18 verification
- State validation and authoritative field ownership rules (validate_state_update)
"""

from __future__ import annotations

from typing import Any, Dict, cast
import pytest

from app.agents.action.contract import (
    ActionActor,
    ActionCommand,
    ActionType,
    ExecutionStatus,
    TargetEntityType,
)
from app.agents.action.errors import (
    ActionApprovalInvalidError,
    ActionApprovalMissingError,
)
from app.agents.action.node import action_node
from app.agents.approval.node import human_approval_node
from app.agents.contracts import (
    AgentGraphStateDict,
    AgentStage,
    validate_state_update,
)
from app.agents.decision.node import decision_node


def test_action_node_execution_success():
    """Verify action_node executes approved candidate and routes to termination."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_act_integ_001",
            "organization_id": "tenant_alpha",
            "actor_id": "user_risk_lead",
            "current_stage": AgentStage.ACTION.value,
            "decision_id": "dec_integ_001",
            "approval_id": "appr_integ_001",
            "approval_result": {
                "approval_id": "appr_integ_001",
                "organization_id": "tenant_alpha",
                "decision_id": "dec_integ_001",
                "candidate_id": "alt_reroute_ocean",
                "status": "APPROVED",
                "side_effect_allowed": True,
            },
            "decision_result": {
                "decision_id": "dec_integ_001",
                "organization_id": "tenant_alpha",
                "status": "RECOMMENDED",
                "preferred_candidate": {
                    "candidate_id": "alt_reroute_ocean",
                    "action_type": "SHIPMENT_REROUTE",
                    "target_entity_type": "SHIPMENT",
                    "target_entity_id": "ship_integ_001",
                    "parameters": {"new_route_id": "route_alt_corridor"},
                },
            },
        },
    )

    update = action_node(state)

    assert update["action_id"] is not None
    assert update["action_status"] == ExecutionStatus.SUCCEEDED.value
    assert update["current_stage"] == AgentStage.ACTION.value
    assert update["current_node"] == "action_agent"
    assert update["selected_route"] == "termination"
    assert "Ready for verification" in update["route_reason"]
    assert any(f["category"] == "ACTION_EXECUTED" for f in update["structured_findings"])

    # Authoritative state update validation
    validate_state_update(state, update, writer_node_id="action_agent", writer_stage=AgentStage.ACTION)


def test_action_node_halts_without_approved_state():
    """Verify action_node raises ActionApprovalMissingError when approval is absent."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_act_integ_002",
            "organization_id": "tenant_alpha",
            "actor_id": "user_risk_lead",
            "current_stage": AgentStage.ACTION.value,
            "decision_id": "dec_integ_002",
            # Missing approval_result and approval_id!
        },
    )

    with pytest.raises(ActionApprovalMissingError) as exc_info:
        action_node(state)
    assert "Cannot execute operational action without prior human approval" in str(exc_info.value)


def test_action_node_halts_on_pending_approval():
    """Verify action_node raises ActionApprovalInvalidError when approval is in PENDING state."""
    state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_act_integ_003",
            "organization_id": "tenant_alpha",
            "actor_id": "user_risk_lead",
            "current_stage": AgentStage.ACTION.value,
            "decision_id": "dec_integ_003",
            "approval_id": "appr_integ_003",
            "approval_result": {
                "approval_id": "appr_integ_003",
                "organization_id": "tenant_alpha",
                "decision_id": "dec_integ_003",
                "candidate_id": "alt_reroute_ocean",
                "status": "PENDING",  # Not approved!
            },
        },
    )

    with pytest.raises(ActionApprovalInvalidError) as exc_info:
        action_node(state)
    assert "strictly require APPROVED status" in str(exc_info.value)


def test_pipeline_handoff_decision_to_approval_to_action():
    """Verify end-to-end multi-agent handoff: Decision -> Approval -> Action Node."""
    # Step 1: Decision Node Formulation
    decision_input_state = cast(
        AgentGraphStateDict,
        {
            "run_id": "run_pipeline_01",
            "organization_id": "tenant_alpha",
            "actor_id": "user_analyst",
            "current_stage": AgentStage.DECISION.value,
            "objective": "Mitigate canal blockage",
            "candidate_alternatives": [
                {
                    "alternative_id": "alt_reroute_cape",
                    "title": "Cape Reroute",
                    "cost": 12000.0,
                    "is_feasible": True,
                    "requires_approval": True,
                }
            ],
            "use_claude": False,
        },
    )
    dec_update = decision_node(decision_input_state)
    assert dec_update["selected_route"] == "approval_boundary"

    # Step 2: Human Approval Evaluation with explicit human sign-off
    approval_input_state = cast(
        AgentGraphStateDict,
        {
            **decision_input_state,
            **dec_update,
            "current_stage": AgentStage.APPROVAL.value,
            "approval_input": {
                "decision": "APPROVE",
                "actor": {
                    "actor_id": "user_risk_director",
                    "organization_id": "tenant_alpha",
                    "role": "RiskManager",
                },
                "comments": "Approved after corridor pilot check.",
            },
        },
    )
    appr_update = human_approval_node(approval_input_state)
    assert appr_update["approval_status"] == "APPROVED"
    assert appr_update["side_effect_allowed"] is True

    # Step 3: Action Agent Execution
    action_input_state = cast(
        AgentGraphStateDict,
        {
            **approval_input_state,
            **appr_update,
            "current_stage": AgentStage.ACTION.value,
        },
    )
    act_update = action_node(action_input_state)
    assert act_update["action_id"] is not None
    assert act_update["action_status"] == ExecutionStatus.SUCCEEDED.value
    assert act_update["selected_route"] == "termination"
    assert any(f["category"] == "ACTION_EXECUTED" for f in act_update["structured_findings"])
