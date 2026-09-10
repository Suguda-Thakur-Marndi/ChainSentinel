"""Foundational node implementations and contracts for LangGraph agent orchestration.

Includes initialization, termination, approval boundary, and safe placeholder nodes.
Placeholder nodes strictly report NOT_IMPLEMENTED and never fabricate intelligence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Union

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentStage,
    NodeContract,
)
from app.agents.errors import AgentTenantIsolationError, AgentValidationError


def initialization_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """Foundational graph entry node.
    
    Validates state identity and transitions graph status to RUNNING.
    """
    org_id = state.get("organization_id")
    if not org_id or not str(org_id).strip():
        raise AgentTenantIsolationError("Missing organization_id in initialization state.")

    run_id = state.get("run_id")
    if not run_id or not str(run_id).strip():
        raise AgentValidationError("Missing run_id in initialization state.")

    step_count = state.get("step_count", 0) + 1
    current_time = datetime.now(timezone.utc).isoformat()

    metadata = dict(state.get("metadata", {}))
    metadata["initialized_at"] = current_time

    route_history = list(state.get("route_history", []))
    route_history.append({
        "from_node": "START",
        "to_node": "initialization",
        "reason_code": "GRAPH_START",
        "step_number": step_count,
        "timestamp": current_time,
    })

    return {
        "status": AgentLifecycleStatus.RUNNING.value,
        "current_stage": AgentStage.INITIALIZATION.value,
        "current_node": "initialization",
        "step_count": step_count,
        "metadata": metadata,
        "route_history": route_history,
    }


def termination_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """Foundational graph exit node.
    
    Determines final terminal lifecycle status (COMPLETED, FAILED, WAITING_FOR_APPROVAL)
    and records completion timestamp.
    """
    current_time = datetime.now(timezone.utc).isoformat()
    errors = state.get("errors", [])
    requires_approval = state.get("requires_human_approval", False)
    current_status = state.get("status")

    if requires_approval:
        final_status = AgentLifecycleStatus.WAITING_FOR_APPROVAL.value
        termination_reason = state.get("termination_reason") or "Paused at approval boundary: awaiting human review."
    elif errors or current_status == AgentLifecycleStatus.FAILED.value:
        final_status = AgentLifecycleStatus.FAILED.value
        termination_reason = state.get("termination_reason") or f"Terminated due to {len(errors)} error(s)."
    elif current_status == AgentLifecycleStatus.MAX_STEPS_REACHED.value:
        final_status = AgentLifecycleStatus.MAX_STEPS_REACHED.value
        termination_reason = state.get("termination_reason") or "Execution limit reached: max steps exceeded."
    elif current_status == AgentLifecycleStatus.BLOCKED.value:
        final_status = AgentLifecycleStatus.BLOCKED.value
        termination_reason = state.get("termination_reason") or "Execution blocked by policy."
    elif current_status == AgentLifecycleStatus.NO_ACTION_REQUIRED.value:
        final_status = AgentLifecycleStatus.NO_ACTION_REQUIRED.value
        termination_reason = state.get("termination_reason") or "Evaluation complete: no action required."
    else:
        final_status = AgentLifecycleStatus.COMPLETED.value
        termination_reason = state.get("termination_reason") or "Agent graph execution completed successfully."

    step_count = state.get("step_count", 0) + 1
    result: Dict[str, Any] = {
        "status": final_status,
        "current_stage": AgentStage.TERMINATION.value,
        "current_node": "termination",
        "completed_at": current_time,
        "termination_reason": termination_reason,
        "step_count": step_count,
    }
    if errors:
        result["errors"] = errors
    return result


def approval_boundary_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """Halts graph execution prior to side-effecting operations to await human approval."""
    step_count = state.get("step_count", 0) + 1
    warnings = list(state.get("warnings", []))
    warnings.append("Approval boundary reached. Halting autonomous execution for human review.")

    return {
        "current_stage": AgentStage.APPROVAL.value,
        "current_node": "approval_boundary",
        "status": AgentLifecycleStatus.WAITING_FOR_APPROVAL.value,
        "requires_human_approval": True,
        "step_count": step_count,
        "warnings": warnings,
        "termination_reason": "Waiting for human authorization before executing actions.",
    }


def create_safe_placeholder_node(
    stage: Union[AgentStage, NodeContract],
    node_id: Optional[str] = None,
) -> Callable[[AgentGraphStateDict], Dict[str, Any]]:
    """Create a safe placeholder node representing future agent stages.
    
    CRITICAL: Strictly returns NOT_IMPLEMENTED metadata. Never fabricates intelligence,
    scores, simulated scenarios, or LLM text.
    """
    if isinstance(stage, NodeContract):
        actual_node_id = stage.node_id
        actual_stage = stage.stage
    else:
        actual_stage = stage
        actual_node_id = node_id or "placeholder_node"

    def placeholder_node(state: AgentGraphStateDict) -> Dict[str, Any]:
        step_count = state.get("step_count", 0) + 1
        warnings = list(state.get("warnings", []))
        warning_msg = (
            f"Node '{actual_node_id}' for stage '{actual_stage.value}' executed as an architectural placeholder. "
            "Business logic is NOT_IMPLEMENTED in Phase 9 Step 1."
        )
        warnings.append(warning_msg)

        findings = dict(state.get("findings", {}))
        findings[f"{actual_node_id}_status"] = "NOT_IMPLEMENTED"

        return {
            "current_stage": actual_stage.value,
            "current_node": actual_node_id,
            "step_count": step_count,
            "warnings": warnings,
            "findings": findings,
        }

    placeholder_node.__name__ = f"node_{actual_node_id}"
    return placeholder_node



# Contracts for standard foundational nodes
INITIALIZATION_NODE_CONTRACT = NodeContract(
    node_id="initialization",
    name="Initialization Node",
    description="Validates execution context and operational identity at graph start.",
    stage=AgentStage.INITIALIZATION,
    is_side_effecting=False,
    input_keys=["run_id", "organization_id", "objective"],
    output_keys=["status", "current_stage", "step_count", "metadata"],
)

TERMINATION_NODE_CONTRACT = NodeContract(
    node_id="termination",
    name="Termination Node",
    description="Evaluates termination criteria and sets final lifecycle status.",
    stage=AgentStage.TERMINATION,
    is_side_effecting=False,
    input_keys=["status", "errors", "requires_human_approval"],
    output_keys=["status", "current_stage", "completed_at", "termination_reason"],
)

APPROVAL_BOUNDARY_NODE_CONTRACT = NodeContract(
    node_id="approval_boundary",
    name="Approval Boundary Node",
    description="Halts autonomous graph execution before side-effecting operations.",
    stage=AgentStage.APPROVAL,
    is_side_effecting=False,
    input_keys=["requires_human_approval"],
    output_keys=["status", "current_stage", "requires_human_approval", "termination_reason"],
)

# Real Research Agent node contract and handler
from app.agents.research.node import RESEARCH_NODE_CONTRACT, research_node

# Real Risk Agent node contract and handler
from app.agents.risk.node import RISK_NODE_CONTRACT, risk_node

# Real Prediction Agent node contract and handler
from app.agents.prediction.node import PREDICTION_NODE_CONTRACT, prediction_node

# Real Scenario Agent node contract and handler
from app.agents.scenario.node import SCENARIO_NODE_CONTRACT, scenario_node

# Real Decision Agent node contract and handler
from app.agents.decision.node import DECISION_NODE_CONTRACT, decision_node

# Real Human Approval Agent node contract and handler
from app.agents.approval.node import HUMAN_APPROVAL_NODE_CONTRACT, human_approval_node


