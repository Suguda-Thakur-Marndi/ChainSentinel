"""LangGraph Scenario Agent node for Phase 9 Step 7.

Provides the scenario_node() function and SCENARIO_NODE_CONTRACT for registration
with the LangGraph NodeRegistry.

State ownership: writes ONLY Scenario-owned fields (scenario_id, scenario_reference, scenario_result).
Side effects: READ_ONLY (scenario definitions have zero operational side effects).
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentNodeContract,
    AgentStage,
    ToolSideEffectType,
    validate_state_update,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.scenario.agent import ScenarioAgent
from app.agents.scenario.claude_service import ClaudeScenarioExplanationService
from app.agents.scenario.contract import (
    ScenarioParameter,
    ScenarioRequest,
    ScenarioResult,
    ScenarioType,
)
from app.agents.scenario.errors import ScenarioTenantIsolationError
from app.agents.scenario.generator import ScenarioGenerator
from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger

logger = get_logger("agents.scenario.node")


def _emit_scenario_audit(
    action: str,
    organization_id: str,
    scenario_id: str,
    status: str = "SUCCESS",
    details: Optional[Dict[str, Any]] = None,
    uow: Optional[Any] = None,
) -> None:
    """Emit a scenario explanation audit event via structured logs and UnitOfWork if available."""
    clean_details = sanitize_sensitive_data(details or {})
    logger.info(
        "AUDIT_EVENT: action=%s org=%s scenario_id=%s status=%s details=%s",
        action,
        organization_id,
        scenario_id,
        status,
        clean_details,
    )
    if uow is not None and hasattr(uow, "audit_logs"):
        try:
            from app.services.audit_service import AuditService
            AuditService.log_event(
                uow=uow,
                action=action,
                resource_type="SCENARIO_AGENT",
                org_id=organization_id,
                resource_id=scenario_id,
                status=status,
                after_data=clean_details,
            )
        except Exception as audit_err:
            logger.warning("Failed to persist scenario audit log via UoW: %s", audit_err)


SCENARIO_NODE_CONTRACT = AgentNodeContract(
    node_id="scenario_agent",
    name="Scenario Agent",
    description=(
        "Orchestration node: converts validated upstream risk assessment and prediction findings "
        "into structured what-if scenario definitions."
    ),
    stage=AgentStage.SCENARIO_ANALYSIS,
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
        "risk_assessment_id",
        "risk_assessment_reference",
        "risk_assessment",
        "prediction_id",
        "prediction_reference",
        "prediction_result",
        "evidence_references",
    ],
    output_keys=[
        "scenario_id",
        "scenario_reference",
        "scenario_result",
        "scenario_explanation",
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


def scenario_node(
    state: AgentGraphStateDict,
    generator: Optional[ScenarioGenerator] = None,
) -> Dict[str, Any]:
    """Execute the Scenario Agent node within a LangGraph StateGraph pipeline.

    Extracts prediction and risk findings from state, constructs a validated ScenarioRequest,
    invokes ScenarioAgent, and writes only SCENARIO-owned fields into AgentGraphState.
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
            raise ScenarioTenantIsolationError("scenario_node requires non-empty 'organization_id' in state.")

        # 1. Gather upstream risk and prediction references
        risk_ref = state.get("risk_assessment_reference") or state.get("risk_assessment")
        risk_id = state.get("risk_assessment_id") or (risk_ref.get("assessment_id") if isinstance(risk_ref, dict) else None)

        pred_res = state.get("prediction_result")
        pred_ref = state.get("prediction_reference")
        pred_id = state.get("prediction_id") or (
            pred_res.get("prediction_id") if isinstance(pred_res, dict) else (
                pred_ref.get("prediction_id") if isinstance(pred_ref, dict) else None
            )
        )

        target_ref = state.get("input_reference") or (f"risk_{risk_id}" if risk_id else objective[:32]) or "default_target"
        evidence_refs = list(state.get("evidence_references", []))

        # 2. Build typed ScenarioRequest
        request = ScenarioRequest(
            organization_id=org_id.strip(),
            shipment_id=state.get("input_reference"),
            scenario_type=ScenarioType.SHIPMENT_DELAY,
            target_reference=target_ref,
            risk_assessment_id=risk_id,
            risk_assessment_reference=risk_ref if isinstance(risk_ref, dict) else None,
            prediction_id=pred_id,
            prediction_reference=pred_ref if isinstance(pred_ref, dict) else None,
            prediction_result=pred_res if isinstance(pred_res, dict) else None,
            evidence_references=evidence_refs,
            horizon_hours=24.0,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # 3. Execute ScenarioAgent
        agent = ScenarioAgent(generator=generator)
        result, findings = agent.execute(request)

        # 3b. Generate Claude Scenario Explanation (Phase 10 Step 5)
        use_claude = state.get("use_claude", True)
        explanation_payload: Optional[Dict[str, Any]] = None
        uow = state.get("uow") or (
            state.get("input_references", {}).get("uow")
            if isinstance(state.get("input_references"), dict)
            else None
        )

        scenario = result.scenario_definition
        warnings = list(state.get("warnings", []))
        if use_claude and scenario is not None and result.status == "READY":
            llm_provider = state.get("llm_provider")
            explanation_service = ClaudeScenarioExplanationService(llm_provider=llm_provider)
            _emit_scenario_audit(
                action="SCENARIO_LLM_EXPLANATION_STARTED",
                organization_id=org_id.strip(),
                scenario_id=result.scenario_id,
                status="STARTED",
                details={
                    "scenario_id": result.scenario_id,
                    "scenario_type": request.scenario_type.value,
                    "fingerprint": result.fingerprint,
                },
                uow=uow,
            )
            try:
                explanation_result = explanation_service.execute(
                    scenario=scenario,
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
                    _emit_scenario_audit(
                        action="SCENARIO_LLM_EXPLANATION_SUCCEEDED",
                        organization_id=org_id.strip(),
                        scenario_id=result.scenario_id,
                        status="SUCCESS",
                        details={
                            "status": explanation_result.status.value,
                            "fingerprint": explanation_result.fingerprint,
                        },
                        uow=uow,
                    )
                else:
                    _emit_scenario_audit(
                        action=(
                            "SCENARIO_LLM_EXPLANATION_REJECTED"
                            if explanation_result.status.value in ("INVALID", "UNSAFE")
                            else "SCENARIO_LLM_EXPLANATION_FAILED"
                        ),
                        organization_id=org_id.strip(),
                        scenario_id=result.scenario_id,
                        status="FAILED",
                        details={
                            "status": explanation_result.status.value,
                            "summary": explanation_result.summary,
                        },
                        uow=uow,
                    )
                    warnings.append(f"Scenario explanation unavailable: {explanation_result.summary}")
            except Exception as exp_err:
                # Failure isolation: NEVER fail the authoritative scenario definition because LLM failed!
                _emit_scenario_audit(
                    action="SCENARIO_LLM_EXPLANATION_FAILED",
                    organization_id=org_id.strip(),
                    scenario_id=result.scenario_id,
                    status="FAILED",
                    details={"error": str(exp_err)},
                    uow=uow,
                )
                warnings.append(f"Scenario explanation generation failed: {exp_err}")
                explanation_payload = {
                    "scenario_id": result.scenario_id,
                    "organization_id": org_id.strip(),
                    "status": "UNAVAILABLE",
                    "summary": f"Scenario explanation unavailable: {exp_err}",
                    "scenario_purpose": "Operational what-if scenario explanation unavailable.",
                    "scenario_type_statement": f"Authoritative scenario type: {scenario.scenario_type.value if hasattr(scenario.scenario_type, 'value') else scenario.scenario_type}",
                    "parameter_explanations": [],
                    "assumption_explanations": [],
                    "risk_relationship": "Explanation unavailable; authoritative risk assessment remains intact.",
                    "prediction_relationship": "Explanation unavailable; authoritative prediction remains intact.",
                    "evidence_explanations": [],
                    "uncertainty_analysis": "LLM explanation could not be completed.",
                    "limitations": ["LLM explanation failed; authoritative scenario remains valid."],
                    "citations": [],
                    "fingerprint": "unavailable",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "provenance": {"reason": str(exp_err)},
                }

        # 4. Assemble state update
        existing_findings = list(state.get("structured_findings", []))
        findings_serialized = [f.model_dump(mode="json") for f in findings]
        updated_structured_findings = existing_findings + findings_serialized

        existing_limitations = list(state.get("limitations", []))
        new_limitations = [lim.model_dump(mode="json") for lim in result.limitations]
        updated_limitations = existing_limitations + new_limitations

        current_findings = dict(state.get("findings", {}))
        current_findings["scenario"] = {
            "scenario_id": result.scenario_id,
            "status": result.status,
            "scenario_type": request.scenario_type.value,
            "fingerprint": result.fingerprint,
        }

        scenario_reference = {
            "scenario_id": result.scenario_id,
            "status": result.status,
            "scenario_type": request.scenario_type.value,
            "fingerprint": result.fingerprint,
            "organization_id": org_id.strip(),
        }

        step_count = state.get("step_count", 0) + 1

        update_payload: Dict[str, Any] = {
            "scenario_id": result.scenario_id,
            "scenario_reference": scenario_reference,
            "scenario_result": result.model_dump(mode="json"),
            "scenario_explanation": explanation_payload,
            "structured_findings": updated_structured_findings,
            "limitations": updated_limitations,
            "warnings": warnings,
            "findings": current_findings,
            "current_stage": AgentStage.SCENARIO_ANALYSIS.value,
            "current_node": "scenario_agent",
            "step_count": step_count,
        }

        # 5. Validate state update against authoritative ownership
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="scenario_agent",
            writer_stage=AgentStage.SCENARIO_ANALYSIS,
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
                request_id=request_id or "unknown_req",
                correlation_id=correlation_id or "unknown_corr",
                trace_id=trace_id or "unknown_trace",
                node_name="scenario_agent",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )
