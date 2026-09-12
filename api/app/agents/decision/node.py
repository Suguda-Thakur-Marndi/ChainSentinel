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
from app.agents.decision.claude_service import ClaudeDecisionExplanationService
from app.agents.decision.contract import (
    DecisionRequest,
    DecisionResult,
    DecisionType,
)
from app.agents.decision.errors import DecisionTenantIsolationError
from app.agents.decision.rules import DecisionRuleEngine
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger

logger = get_logger("agents.decision.node")


def _emit_decision_audit(
    action: str,
    organization_id: str,
    decision_id: str,
    status: str = "SUCCESS",
    details: Optional[Dict[str, Any]] = None,
    uow: Optional[Any] = None,
) -> None:
    """Emit a decision explanation audit event via structured logs and UnitOfWork if available."""
    clean_details = sanitize_sensitive_data(details or {})
    logger.info(
        "AUDIT_EVENT: action=%s org=%s decision_id=%s status=%s details=%s",
        action,
        organization_id,
        decision_id,
        status,
        clean_details,
    )
    if uow is not None and hasattr(uow, "audit_logs"):
        try:
            from app.services.audit_service import AuditService
            AuditService.log_event(
                uow=uow,
                action=action,
                resource_type="DECISION_AGENT",
                org_id=organization_id,
                resource_id=decision_id,
                status=status,
                after_data=clean_details,
            )
        except Exception as audit_err:
            logger.warning("Failed to persist decision audit log via UoW: %s", audit_err)


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
        "optimization_id",
        "optimization_reference",
        "optimization_result",
        "simulation_id",
        "simulation_reference",
        "simulation_result",
        "recommendation_references",
        "evidence_references",
    ],
    output_keys=[
        "decision_id",
        "decision_reference",
        "decision_result",
        "decision_explanation",
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
    explanation_service: Optional[ClaudeDecisionExplanationService] = None,
) -> Dict[str, Any]:
    """Execute the Decision Agent node within a LangGraph StateGraph pipeline.

    Extracts scenario, risk, prediction, and optimization findings from state,
    constructs a validated DecisionRequest, invokes DecisionAgent, and writes
    only DECISION-owned fields into AgentGraphState.
    """
    start_time = time.perf_counter()
    status = "SUCCESS"
    error_code: Optional[str] = None

    # Extract operational identity from state
    org_id = state.get("organization_id") or state.get("tenant_id") or ""
    run_id = state.get("run_id") or state.get("agent_run_id") or ""
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

        # Optimization context (Phase 14)
        input_refs = state.get("input_references", {}) if isinstance(state.get("input_references"), dict) else {}
        opt_res = state.get("optimization_result") or input_refs.get("optimization_result")
        opt_ref = state.get("optimization_reference") or input_refs.get("optimization_reference")
        opt_id = state.get("optimization_id") or input_refs.get("optimization_id") or (
            opt_res.get("optimization_id") if isinstance(opt_res, dict) else (
                opt_ref.get("optimization_id") if isinstance(opt_ref, dict) else None
            )
        )

        # Simulation context (Phase 13)
        sim_res = state.get("simulation_result") or input_refs.get("simulation_result")
        sim_ref = state.get("simulation_reference") or input_refs.get("simulation_reference")
        sim_id = state.get("simulation_id") or input_refs.get("simulation_id") or (
            sim_res.get("simulation_id") if isinstance(sim_res, dict) else (
                sim_ref.get("simulation_id") if isinstance(sim_ref, dict) else None
            )
        )

        obj_type = state.get("objective_type") or input_refs.get("objective_type")
        cand_alts = list(state.get("candidate_alternatives", []) or input_refs.get("candidate_alternatives", []))
        shipment_id = state.get("shipment_id") or input_refs.get("shipment_id")
        shipment_ids = list(state.get("shipment_ids", []) or input_refs.get("shipment_ids", []))
        supplier_id = state.get("supplier_id") or input_refs.get("supplier_id")
        supplier_ids = list(state.get("supplier_ids", []) or input_refs.get("supplier_ids", []))

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
            optimization_id=opt_id,
            optimization_reference=opt_ref if isinstance(opt_ref, dict) else None,
            optimization_result=opt_res if isinstance(opt_res, dict) else None,
            simulation_id=sim_id,
            simulation_reference=sim_ref if isinstance(sim_ref, dict) else None,
            simulation_result=sim_res if isinstance(sim_res, dict) else None,
            objective_type=obj_type,
            candidate_alternatives=cand_alts,
            shipment_id=shipment_id,
            shipment_ids=shipment_ids,
            supplier_id=supplier_id,
            supplier_ids=supplier_ids,
            recommendation_references=rec_refs,
            evidence_references=evidence_refs,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # 3. Execute DecisionAgent
        agent = DecisionAgent(rule_engine=rule_engine)
        result, findings = agent.execute(request)


        # 3b. Generate Claude Decision Explanation (Phase 10 Step 7)
        use_claude = state.get("use_claude", True)
        explanation_payload: Optional[Dict[str, Any]] = None
        uow = state.get("uow") or (
            state.get("input_references", {}).get("uow")
            if isinstance(state.get("input_references"), dict)
            else None
        )

        warnings = list(state.get("warnings", []))
        if use_claude and result.candidates:
            if explanation_service is None:
                llm_provider = state.get("llm_provider")
                explanation_service = ClaudeDecisionExplanationService(llm_provider=llm_provider)
            _emit_decision_audit(
                action="DECISION_LLM_EXPLANATION_STARTED",
                organization_id=org_id.strip(),
                decision_id=result.decision_id,
                status="STARTED",
                details={
                    "decision_id": result.decision_id,
                    "decision_type": request.decision_type.value,
                    "fingerprint": result.fingerprint,
                    "candidate_count": len(result.candidates),
                },
                uow=uow,
            )
            try:
                explanation_result = explanation_service.execute(
                    decision=result,
                    scenario_result=scen_res or scen_def,
                    risk_assessment=state.get("risk_assessment")
                    or (state.get("risk_assessment_reference") if isinstance(state.get("risk_assessment_reference"), dict) else None),
                    prediction_result=state.get("prediction_result")
                    or (state.get("prediction_reference") if isinstance(state.get("prediction_reference"), dict) else None),
                    research_result=state.get("research_result"),
                    evidence_bundle=state.get("evidence_bundle"),
                    objective=objective,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    agent_run_id=run_id,
                    fail_closed=False,
                )
                explanation_payload = explanation_result.model_dump(mode="json")
                if explanation_result.status.value == "AVAILABLE":
                    _emit_decision_audit(
                        action="DECISION_LLM_EXPLANATION_SUCCEEDED",
                        organization_id=org_id.strip(),
                        decision_id=result.decision_id,
                        status="SUCCESS",
                        details={
                            "status": explanation_result.status.value,
                            "fingerprint": explanation_result.fingerprint,
                        },
                        uow=uow,
                    )
                else:
                    _emit_decision_audit(
                        action=(
                            "DECISION_LLM_EXPLANATION_REJECTED"
                            if explanation_result.status.value in ("INVALID", "UNSAFE")
                            else "DECISION_LLM_EXPLANATION_FAILED"
                        ),
                        organization_id=org_id.strip(),
                        decision_id=result.decision_id,
                        status="FAILED",
                        details={
                            "status": explanation_result.status.value,
                            "summary": explanation_result.summary,
                        },
                        uow=uow,
                    )
                    warnings.append(f"Decision explanation unavailable: {explanation_result.summary}")
            except Exception as exp_err:
                # Failure isolation: NEVER fail the authoritative DecisionResult because LLM failed!
                _emit_decision_audit(
                    action="DECISION_LLM_EXPLANATION_FAILED",
                    organization_id=org_id.strip(),
                    decision_id=result.decision_id,
                    status="FAILED",
                    details={"error": str(exp_err)},
                    uow=uow,
                )
                warnings.append(f"Decision explanation generation failed: {exp_err}")

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
            "decision_explanation": explanation_payload,
            "structured_findings": updated_structured_findings,
            "limitations": updated_limitations,
            "findings": current_findings,
            "current_stage": AgentStage.DECISION.value,
            "current_node": "decision_agent",
            "step_count": step_count,
        }

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
