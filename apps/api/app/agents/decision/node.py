"""LangGraph Decision Agent node for Phase 9 Step 8.

Provides decision_node() function and DECISION_NODE_CONTRACT for registration
with the LangGraph NodeRegistry.

State ownership: writes ONLY Decision-owned fields (decision_id, decision_reference, decision_result, recommendation_references).
Side effects: READ_ONLY (identifies decision candidates; executes zero operational side effects).
Human approval: Enforces requires_human_approval = True to pause execution before action.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentNodeContract,
    AgentStage,
    ToolSideEffectType,
    validate_state_update,
)
from app.agents.decision.agent import DecisionAgent
from app.agents.decision.contract import (
    DecisionRequest,
    DecisionResult,
    DecisionType,
)
from app.agents.decision.errors import DecisionTenantIsolationError
from app.agents.decision.rules import DecisionRuleEngine
from app.agents.observability import AgentObservability, NodeExecutionTelemetry

DECISION_NODE_CONTRACT = AgentNodeContract(
    node_id="decision_agent",
    name="Decision Agent",
    description=(
        "Orchestration node: evaluates validated scenario definitions, predictions, "
        "and risk assessments to formulate structured, rule-ranked decision candidates."
    ),
    stage=AgentStage.DECISION,
    is_side_effecting=False,
    side_effect_type=ToolSideEffectType.READ_ONLY,
    input_keys=[
        "organization_id",
        "actor_id",
        "run_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "objective",
        "structured_findings",
        "scenario_id",
        "scenario_reference",
        "scenario_result",
        "risk_assessment_id",
        "risk_assessment_reference",
        "risk_assessment",
        "prediction_id",
        "prediction_reference",
        "prediction_result",
        "recommendation_references",
        "evidence_references",
    ],
    output_keys=[
        "decision_id",
        "decision_reference",
        "decision_result",
        "recommendation_references",
        "requires_human_approval",
        "structured_findings",
        "limitations",
        "warnings",
        "findings",
        "current_stage",
        "current_node",
        "step_count",
    ],
    required_roles=["analyst", "admin"],
    requires_evidence=True,
    retryable=False,
    max_retries=0,
    timeout_seconds=30.0,
)


def decision_node(
    state: AgentGraphStateDict,
    rule_engine: Optional[DecisionRuleEngine] = None,
) -> Dict[str, Any]:
    """Execute the Decision Agent node within a LangGraph StateGraph pipeline.

    Extracts scenario and risk findings from state, constructs a validated DecisionRequest,
    invokes DecisionAgent, and writes only DECISION-owned fields into AgentGraphState.
    """
    start_time = time.perf_counter()
    status = "SUCCESS"
    error_code: Optional[str] = None

    # Extract operational identity from state
    org_id = state.get("organization_id", "")
    run_id = state.get("run_id", "")
    actor_id = state.get("actor_id", "")
    request_id = state.get("request_id", "")
    correlation_id = state.get("correlation_id", "")
    trace_id = state.get("trace_id", "")
    objective = state.get("objective", "")

    try:
        if not org_id or not str(org_id).strip():
            raise DecisionTenantIsolationError("decision_node requires non-empty 'organization_id' in state.")

        # 1. Gather upstream references
        scen_res = state.get("scenario_result")
        scen_ref = state.get("scenario_reference")
        scen_id = state.get("scenario_id") or (
            scen_res.get("scenario_id") if isinstance(scen_res, dict) else (
                scen_ref.get("scenario_id") if isinstance(scen_ref, dict) else None
            )
        )
        scen_def = scen_res.get("scenario_definition") if isinstance(scen_res, dict) else None

        risk_ref = state.get("risk_assessment_reference") or state.get("risk_assessment")
        risk_id = state.get("risk_assessment_id") or (risk_ref.get("assessment_id") if isinstance(risk_ref, dict) else None)

        pred_res = state.get("prediction_result")
        pred_ref = state.get("prediction_reference")
        pred_id = state.get("prediction_id") or (
            pred_res.get("prediction_id") if isinstance(pred_res, dict) else (
                pred_ref.get("prediction_id") if isinstance(pred_ref, dict) else None
            )
        )

        rec_refs = list(state.get("recommendation_references", []))
        evidence_refs = list(state.get("evidence_references", []))
        target_ref = state.get("input_reference") or (f"scen_{scen_id}" if scen_id else objective[:32]) or "default_target"

        # 2. Build typed DecisionRequest
        request = DecisionRequest(
            organization_id=org_id.strip(),
            decision_type=DecisionType.OPERATIONAL_REVIEW,
            target_reference=target_ref,
            scenario_id=scen_id,
            scenario_reference=scen_ref if isinstance(scen_ref, dict) else None,
            scenario_result=scen_res if isinstance(scen_res, dict) else None,
            scenario_definition=scen_def if isinstance(scen_def, dict) else None,
            risk_assessment_id=risk_id,
            risk_assessment_reference=risk_ref if isinstance(risk_ref, dict) else None,
            prediction_id=pred_id,
            prediction_reference=pred_ref if isinstance(pred_ref, dict) else None,
            prediction_result=pred_res if isinstance(pred_res, dict) else None,
            recommendation_references=rec_refs,
            evidence_references=evidence_refs,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # 3. Execute DecisionAgent
        agent = DecisionAgent(rule_engine=rule_engine)
        result, findings = agent.execute(request)

        # 4. Assemble state update
        existing_findings = list(state.get("structured_findings", []))
        findings_serialized = [f.model_dump(mode="json") for f in findings]
        updated_structured_findings = existing_findings + findings_serialized

        existing_limitations = list(state.get("limitations", []))
        new_limitations = [lim.model_dump(mode="json") for lim in result.limitations]
        updated_limitations = existing_limitations + new_limitations

        current_findings = dict(state.get("findings", {}))
        current_findings["decision"] = {
            "decision_id": result.decision_id,
            "status": result.status,
            "candidate_count": len(result.candidates),
            "preferred_candidate": result.preferred_candidate.action_type if result.preferred_candidate else None,
            "fingerprint": result.fingerprint,
        }

        decision_reference = {
            "decision_id": result.decision_id,
            "status": result.status,
            "fingerprint": result.fingerprint,
            "candidate_count": len(result.candidates),
            "preferred_candidate_id": result.preferred_candidate.candidate_id if result.preferred_candidate else None,
            "organization_id": org_id.strip(),
        }

        step_count = state.get("step_count", 0) + 1
        requires_approval = bool(result.requires_human_approval or any(c.requires_human_approval for c in result.candidates))

        update_payload: Dict[str, Any] = {
            "decision_id": result.decision_id,
            "decision_reference": decision_reference,
            "decision_result": result.model_dump(mode="json"),
            "structured_findings": updated_structured_findings,
            "limitations": updated_limitations,
            "findings": current_findings,
            "current_stage": AgentStage.DECISION.value,
            "current_node": "decision_agent",
            "step_count": step_count,
        }

        warnings = list(state.get("warnings", []))
        if requires_approval:
            warnings.append("Decision candidate requires human approval before execution.")
            update_payload["selected_route"] = "approval_boundary"
            update_payload["route_reason"] = "Candidate requires human approval before execution."
        else:
            update_payload["selected_route"] = "termination"
            update_payload["route_reason"] = "Decision evaluation complete: no approval required."
        update_payload["warnings"] = warnings

        # 5. Validate state update against authoritative ownership
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="decision_agent",
            writer_stage=AgentStage.DECISION,
        )

        return update_payload

    except Exception as exc:
        status = "FAILED"
        error_code = exc.__class__.__name__
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        AgentObservability.emit_node_telemetry(
            NodeExecutionTelemetry(
                run_id=run_id or "unknown_run",
                organization_id=org_id or "unknown_org",
                actor_id=actor_id or "unknown_actor",
                request_id=request_id or "unknown_request",
                correlation_id=correlation_id or "unknown_corr",
                trace_id=trace_id or "unknown_trace",
                node_name="decision_agent",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )
