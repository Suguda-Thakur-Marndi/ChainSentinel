"""LangGraph Node implementation for the RiskWise Action Agent (Phase 17).

Coordinates:
- State extraction of approved decision and human sign-off
- Execution of allowlisted operational adapters via ActionAgent
- Authoritative stage updates for AgentStage.ACTION
- Routing to termination (halting before Phase 18 verification)
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
import uuid

from app.agents.action.agent import ActionAgent
from app.agents.action.contract import (
    ActionActor,
    ActionCommand,
    ActionResult,
    ActionType,
    ExecutionStatus,
    TargetEntityType,
)
from app.agents.action.errors import (
    ActionAgentError,
    ActionApprovalInvalidError,
    ActionApprovalMissingError,
    ActionTenantIsolationError,
)
from app.agents.contracts import (
    AgentFinding,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentStage,
    NodeContract,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.db.unit_of_work import UnitOfWork


ACTION_NODE_CONTRACT = NodeContract(
    node_id="action_agent",
    name="Action Agent Node",
    description="Executes approved operational mitigation actions within strict governance boundaries.",
    stage=AgentStage.ACTION,
    is_side_effecting=True,
    input_keys=["approval_result", "approval_id", "decision_result", "decision_id", "organization_id"],
    output_keys=[
        "action_id",
        "action_reference",
        "action_result",
        "action_status",
        "findings",
        "structured_findings",
        "current_stage",
        "current_node",
        "selected_route",
        "route_reason",
        "step_count",
    ],
)


def action_node(
    state: AgentGraphStateDict,
    uow: Optional[UnitOfWork] = None,
    agent: Optional[ActionAgent] = None,
) -> Dict[str, Any]:
    """Execute the approved operational action within the LangGraph StateGraph pipeline.

    Receives the approved decision and human approval from state, validates approval binding,
    executes the allowlisted adapter, and records the authoritative ActionResult.
    """
    start_time = time.perf_counter()
    telemetry_status = "SUCCESS"
    error_code: Optional[str] = None
    action_id_for_telemetry = "unknown_action"

    org_id = str(state.get("organization_id", "")).strip()
    run_id = str(state.get("run_id", "run_action_default"))
    actor_id = str(state.get("actor_id", "user_operator"))
    correlation_id = str(state.get("correlation_id", "corr_action"))
    trace_id = str(state.get("trace_id", "trace_action"))

    try:
        # 1. Tenant boundary validation
        if not org_id:
            raise ActionTenantIsolationError("organization_id is missing from agent state.")

        # 2. Extract and validate human approval from state
        approval_result = state.get("approval_result")
        approval_id = state.get("approval_id")

        if not approval_result and not approval_id:
            raise ActionApprovalMissingError(
                "Cannot execute operational action without prior human approval. Halting at approval boundary."
            )

        appr_status = ""
        if isinstance(approval_result, dict):
            appr_status = str(approval_result.get("status", "")).upper()
            if not approval_id:
                approval_id = approval_result.get("approval_id")

        if appr_status not in ("APPROVED", "APPROVE"):
            raise ActionApprovalInvalidError(
                f"Approval status is '{appr_status or 'MISSING'}'. Operational actions strictly require APPROVED status."
            )

        # 3. Extract decision and candidate details
        decision_result = state.get("decision_result") or {}
        decision_id = state.get("decision_id") or decision_result.get("decision_id", f"dec_{uuid.uuid4().hex[:12]}")
        
        pref_candidate = decision_result.get("preferred_candidate") or {}
        candidate_id = (
            pref_candidate.get("candidate_id")
            or (approval_result.get("candidate_id") if isinstance(approval_result, dict) else None)
            or "cand_approved"
        )
        action_type_raw = pref_candidate.get("action_type") or "SHIPMENT_REROUTE"
        try:
            action_type = ActionType(action_type_raw)
        except ValueError:
            action_type = ActionType.SHIPMENT_REROUTE

        target_entity_type_raw = pref_candidate.get("target_entity_type") or "SHIPMENT"
        try:
            target_entity_type = TargetEntityType(target_entity_type_raw)
        except ValueError:
            target_entity_type = TargetEntityType.SHIPMENT

        target_entity_id = (
            pref_candidate.get("target_entity_id")
            or pref_candidate.get("parameters", {}).get("shipment_id")
            or state.get("target_reference")
            or state.get("shipment_id")
            or "target_default"
        )

        parameters = dict(pref_candidate.get("parameters", {}))
        # Ensure reroute has a new_route_id if missing in candidate parameters
        if action_type == ActionType.SHIPMENT_REROUTE and "new_route_id" not in parameters:
            parameters["new_route_id"] = state.get("selected_route_id", "route_alt_corridor")

        # 4. Check for explicit command override in state
        raw_command = state.get("action_command")
        if isinstance(raw_command, ActionCommand):
            command = raw_command
        elif isinstance(raw_command, dict):
            command = ActionCommand.model_validate(raw_command)
        else:
            idempotency_key = state.get("idempotency_key") or f"idemp_{run_id}_{candidate_id}"
            command = ActionCommand(
                decision_id=str(decision_id),
                approval_id=str(approval_id),
                candidate_id=str(candidate_id),
                organization_id=org_id,
                action_type=action_type,
                target_entity_type=target_entity_type,
                target_entity_id=str(target_entity_id),
                parameters=parameters,
                idempotency_key=str(idempotency_key),
                trace_id=trace_id,
                run_id=run_id,
                actor=ActionActor(actor_id=actor_id, organization_id=org_id, role="RiskManager"),
            )

        action_id_for_telemetry = command.action_id or "pending_action"

        # 5. Execute ActionAgent
        action_agent = agent or ActionAgent()
        db_session = uow.session if uow else None
        result, findings = action_agent.execute(command=command, approval=approval_result, db=db_session, uow=uow)

        # 6. Assemble state updates
        existing_findings = list(state.get("structured_findings", []))
        findings_serialized = [f.model_dump(mode="json") for f in findings]
        updated_findings = existing_findings + findings_serialized

        current_findings = dict(state.get("findings", {}))
        current_findings["action"] = {
            "action_id": result.action_id,
            "status": result.status,
            "action_type": result.action_type,
            "target_entity_id": result.target_entity_id,
            "adapter": result.adapter,
            "provider": result.provider,
            "fingerprint": result.fingerprint,
        }

        step_count = state.get("step_count", 0) + 1
        warnings = list(state.get("warnings", []))
        warnings.append(f"Operational action '{result.action_type}' executed with status '{result.status}'.")

        update_payload: Dict[str, Any] = {
            "action_id": result.action_id,
            "action_reference": f"{org_id}:action:{result.action_id}",
            "action_result": result.model_dump(mode="json"),
            "action_status": result.status,
            "structured_findings": updated_findings,
            "findings": current_findings,
            "current_stage": AgentStage.ACTION.value,
            "current_node": "action_agent",
            "selected_route": "termination",
            "route_reason": "Action execution completed. Ready for verification.",
            "step_count": step_count,
            "warnings": warnings,
        }

        return update_payload

    except ActionAgentError as aae:
        telemetry_status = "FAILED"
        error_code = aae.error_code
        raise
    except Exception as exc:
        telemetry_status = "FAILED"
        error_code = "ACTION_NODE_UNEXPECTED_ERROR"
        raise ActionAgentError(f"Action node execution failed unexpectedly: {exc}", error_code=error_code) from exc
    finally:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        try:
            telemetry = NodeExecutionTelemetry(
                node_name="action_agent",
                stage=AgentStage.ACTION,
                run_id=run_id,
                organization_id=org_id or "unknown",
                actor_id=actor_id,
                request_id=str(state.get("request_id", "req_action_default")),
                correlation_id=correlation_id,
                trace_id=trace_id,
                status=telemetry_status,
                duration_ms=latency_ms,
                error_code=error_code,
                metadata={
                    "action_id": action_id_for_telemetry,
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                },
            )
            AgentObservability.emit_node_telemetry(telemetry)
        except Exception:
            pass
