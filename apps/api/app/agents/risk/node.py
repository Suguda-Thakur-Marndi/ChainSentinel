"""LangGraph Risk Agent node for Phase 9 Step 5.

Provides the risk_node() function and RISK_NODE_CONTRACT for registration
with the LangGraph NodeRegistry. Mirrors the research_node() structural pattern:
single try/except/finally ensures telemetry is always emitted.

State ownership: writes only RISK_ASSESSMENT-owned fields.
Side effects: READ_ONLY (Risk Engine evaluation is an internal business operation).
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, Optional

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentStage,
    validate_state_update,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.research.contract import ResearchFinding, ResearchResult
from app.agents.risk.agent import RiskAgent
from app.agents.risk.claude_service import ClaudeRiskExplanationService
from app.agents.risk.contract import RiskAgentRequest, RiskAgentResult, generate_deterministic_risk_request_id
from app.agents.risk.errors import InvalidRiskRequestError, RiskTenantIsolationError
from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger

logger = get_logger("agents.risk.node")


def _emit_risk_audit(
    action: str,
    organization_id: str,
    assessment_id: str,
    status: str = "SUCCESS",
    details: Optional[Dict[str, Any]] = None,
    uow: Optional[Any] = None,
) -> None:
    """Emit a risk explanation audit event via structured logs and UnitOfWork if available."""
    clean_details = sanitize_sensitive_data(details or {})
    logger.info(
        "AUDIT_EVENT: action=%s org=%s assessment_id=%s status=%s details=%s",
        action,
        organization_id,
        assessment_id,
        status,
        clean_details,
    )
    if uow is not None and hasattr(uow, "audit_logs"):
        try:
            from app.services.audit_service import AuditService
            AuditService.log_event(
                uow=uow,
                action=action,
                resource_type="RISK_AGENT",
                org_id=organization_id,
                resource_id=assessment_id,
                status=status,
                after_data=clean_details,
            )
        except Exception as audit_err:
            logger.warning("Failed to persist risk audit log via UoW: %s", audit_err)

try:
    from app.agents.contracts import AgentNodeContract
    _HAS_NODE_CONTRACT = True
except ImportError:
    from app.agents.contracts import NodeContract as AgentNodeContract  # type: ignore
    _HAS_NODE_CONTRACT = False


# ---------------------------------------------------------------------------
# RISK_NODE_CONTRACT
# ---------------------------------------------------------------------------
RISK_NODE_CONTRACT = AgentNodeContract(
    node_id="risk_agent",
    name="Risk Agent",
    description=(
        "Orchestration node: translates Research Agent findings into NormalizedRiskSignal "
        "inputs, invokes Phase 7 BaselineRiskEngine, and writes authoritative risk references "
        "into AgentGraphState. Never computes risk scores independently."
    ),
    stage=AgentStage.RISK_ASSESSMENT,
    is_side_effecting=False,
    input_keys=[
        "organization_id",
        "actor_id",
        "run_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "objective",
        "structured_findings",
        "evidence_bundle_id",
        "evidence_references",
        "citation_references",
    ],
    output_keys=[
        "risk_assessment_id",
        "risk_assessment_reference",
        "risk_assessment",
        "risk_alert_references",
        "risk_explanation",
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
    retryable=True,
    max_retries=3,
    timeout_seconds=120.0,
)


def _extract_research_result_from_state(state: AgentGraphStateDict) -> Optional[ResearchResult]:
    """Reconstruct a ResearchResult from structured_findings in graph state, if present."""
    organization_id = state.get("organization_id", "")
    findings_dicts = state.get("structured_findings", [])
    raw_findings = state.get("findings", {})

    if not findings_dicts and not raw_findings:
        return None

    # Re-hydrate ResearchFinding objects from serialized AgentFinding dicts in state
    research_findings = []
    for f in findings_dicts:
        if isinstance(f, dict):
            try:
                # AgentFinding stored as dict: extract fields we can map back
                category_raw = f.get("category", "GENERAL")
                # Strip finding_type suffix if present (research stores "CATEGORY:TYPE")
                if ":" in category_raw:
                    parts = category_raw.split(":", 1)
                    category = parts[0]
                    finding_type_str = parts[1] if len(parts) > 1 else "FACT"
                else:
                    category = category_raw
                    finding_type_str = "FACT"

                from app.agents.research.contract import FindingType
                try:
                    finding_type = FindingType(finding_type_str)
                except ValueError:
                    finding_type = FindingType.FACT

                evidence_ids = f.get("evidence_ids", [])

                # FACT findings require at least one evidence_id
                if finding_type == FindingType.FACT and not evidence_ids:
                    finding_type = FindingType.INFERENCE

                rf = ResearchFinding(
                    finding_id=f.get("finding_id", "unknown"),
                    category=category,
                    finding_type=finding_type,
                    title=f.get("title", "Research Finding"),
                    summary=f.get("summary", "No summary available."),
                    evidence_ids=evidence_ids,
                    citation_ids=f.get("source_references", []),
                    confidence=f.get("confidence"),
                    created_by_node=f.get("created_by_node", "research_agent"),
                )
                research_findings.append(rf)
            except Exception:
                # Skip malformed findings — don't fail the whole run
                continue

    if not research_findings:
        return None

    # Build a minimal ResearchResult from state context
    findings_summary = raw_findings if isinstance(raw_findings, dict) else {}
    return ResearchResult(
        research_id=state.get("run_id", "unknown_run"),
        organization_id=organization_id,
        status=findings_summary.get("status", "COMPLETED"),
        summary=str(findings_summary.get("summary", "Research findings from graph state.")),
        findings=research_findings,
        evidence_ids=list(state.get("evidence_references", [])),
        citation_ids=list(state.get("citation_references", [])),
        fingerprint=str(findings_summary.get("fingerprint", "state_derived")),
        confidence=findings_summary.get("confidence"),
        source_summary=dict(findings_summary.get("source_summary", {})),
        provenance={"source": "graph_state", "run_id": state.get("run_id", "")},
    )


def risk_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """LangGraph node function executing Risk Agent orchestration.

    Reads research output from AgentGraphState, translates findings to Risk Engine inputs,
    invokes Phase 7 BaselineRiskEngine, and writes authorized risk references to state.
    """
    start_time = time.perf_counter()
    status = "SUCCESS"
    error_code: Optional[str] = None

    organization_id = state.get("organization_id", "")
    run_id = state.get("run_id", "")
    actor_id = state.get("actor_id", "")
    request_id = state.get("request_id", "")
    correlation_id = state.get("correlation_id", "")
    trace_id = state.get("trace_id", "")
    objective = state.get("objective", "")
    warnings: List[str] = list(state.get("warnings", []))

    try:
        if not organization_id or not organization_id.strip():
            raise RiskTenantIsolationError(
                "State is missing organization_id required for risk evaluation."
            )
        if not objective or not objective.strip():
            raise InvalidRiskRequestError(
                "State is missing a valid 'objective' required for risk evaluation.",
                details={"run_id": run_id, "organization_id": organization_id},
            )

        # 1. Extract research result from graph state
        research_result = _extract_research_result_from_state(state)
        if research_result is None:
            raise InvalidRiskRequestError(
                "No research findings available in AgentGraphState for risk evaluation. "
                "Research Agent must execute before Risk Agent.",
                details={"run_id": run_id, "organization_id": organization_id},
            )

        # 2. Build typed RiskAgentRequest
        risk_request_id = generate_deterministic_risk_request_id(
            organization_id=organization_id,
            research_id=research_result.research_id,
            objective=objective,
        )

        request = RiskAgentRequest(
            risk_request_id=risk_request_id,
            organization_id=organization_id,
            objective=objective,
            actor_id=actor_id or None,
            research_id=research_result.research_id,
            research_result=research_result,
            evidence_bundle_id=state.get("evidence_bundle_id"),
            evidence_references=list(state.get("evidence_references", [])),
            citation_references=list(state.get("citation_references", [])),
            scope="GLOBAL",
            correlation_id=correlation_id or None,
            trace_id=trace_id or None,
        )

        # 3. Execute Risk Agent
        agent = RiskAgent()
        result: RiskAgentResult = agent.execute(request=request)

        # 4. Build RiskAssessmentReference for state (if we have a real assessment)
        risk_assessment_reference = None
        if result.assessment_id and not result.assessment_id.startswith("assessment_none_"):
            from app.agents.contracts import RiskAssessmentReference
            risk_assessment_reference = RiskAssessmentReference(
                assessment_id=result.assessment_id,
                organization_id=organization_id,
                assessment_fingerprint=result.assessment_fingerprint or result.assessment_id[:32],
                risk_score=result.risk_score,
                risk_level=result.risk_level,
                factor_count=result.factor_count,
            )

        # 4b. Generate Claude Risk Explanation (Phase 10 Step 4)
        use_claude = state.get("use_claude", True)
        explanation_payload: Optional[Dict[str, Any]] = None
        uow = state.get("uow") or (
            state.get("input_references", {}).get("uow")
            if isinstance(state.get("input_references"), dict)
            else None
        )

        assessment = result.assessment
        if use_claude and assessment is not None and result.status != "INSUFFICIENT_EVIDENCE":
            llm_provider = state.get("llm_provider")
            explanation_service = ClaudeRiskExplanationService(llm_provider=llm_provider)
            _emit_risk_audit(
                action="RISK_LLM_EXPLANATION_STARTED",
                organization_id=organization_id,
                assessment_id=result.assessment_id,
                status="STARTED",
                details={"assessment_id": result.assessment_id, "score": result.risk_score, "level": result.risk_level},
                uow=uow,
            )
            try:
                explanation_result = explanation_service.execute(
                    assessment=assessment,
                    research_result=research_result,
                    evidence_bundle=state.get("evidence_bundle"),
                    objective=objective,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    agent_run_id=run_id,
                    fail_closed=False,
                )
                explanation_payload = explanation_result.model_dump(mode="json")
                if explanation_result.status.value == "AVAILABLE":
                    _emit_risk_audit(
                        action="RISK_LLM_EXPLANATION_SUCCEEDED",
                        organization_id=organization_id,
                        assessment_id=result.assessment_id,
                        status="SUCCESS",
                        details={"status": explanation_result.status.value, "fingerprint": explanation_result.fingerprint},
                        uow=uow,
                    )
                else:
                    _emit_risk_audit(
                        action="RISK_LLM_EXPLANATION_REJECTED" if "REJECTED" in explanation_result.status.value else "RISK_LLM_EXPLANATION_FAILED",
                        organization_id=organization_id,
                        assessment_id=result.assessment_id,
                        status="FAILED",
                        details={"status": explanation_result.status.value, "summary": explanation_result.summary},
                        uow=uow,
                    )
                    warnings.append(f"Risk explanation unavailable: {explanation_result.summary}")
            except Exception as exp_err:
                # Failure isolation: NEVER fail the authoritative risk assessment because LLM failed!
                _emit_risk_audit(
                    action="RISK_LLM_EXPLANATION_FAILED",
                    organization_id=organization_id,
                    assessment_id=result.assessment_id,
                    status="FAILED",
                    details={"error": str(exp_err)},
                    uow=uow,
                )
                warnings.append(f"Risk explanation generation failed: {exp_err}")
                explanation_payload = {
                    "assessment_id": result.assessment_id,
                    "organization_id": organization_id,
                    "status": "UNAVAILABLE",
                    "summary": f"Risk explanation unavailable: {exp_err}",
                    "risk_level_statement": f"Authoritative risk level: {result.risk_level or 'UNSPECIFIED'}",
                    "score_statement": f"Authoritative composite score: {result.risk_score if result.risk_score is not None else 'N/A'}",
                    "key_drivers": [],
                    "evidence_explanations": [],
                    "uncertainty_analysis": "LLM explanation could not be completed.",
                    "conflict_explanations": [],
                    "limitations": ["LLM explanation failed; authoritative assessment remains valid."],
                    "citations": [],
                    "fingerprint": "unavailable",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "provenance": {"reason": str(exp_err)},
                }

        # 5. Build state update payload (only RISK_ASSESSMENT-owned fields)
        step_count = state.get("step_count", 0) + 1

        existing_limitations = list(state.get("limitations", []))
        new_limitations = [lim.model_dump(mode="json") for lim in result.limitations]

        if result.status == "INSUFFICIENT_EVIDENCE":
            warnings.append(
                "Risk evaluation completed with INSUFFICIENT_EVIDENCE: "
                "no research findings could be mapped to Risk Engine signals."
            )

        existing_structured = list(state.get("structured_findings", []))

        update_payload: Dict[str, Any] = {
            "current_stage": AgentStage.RISK_ASSESSMENT.value,
            "current_node": "risk_agent",
            "step_count": step_count,
            "risk_assessment_id": result.assessment_id,
            "risk_assessment_reference": risk_assessment_reference.model_dump(mode="json")
            if risk_assessment_reference else None,
            "risk_assessment": risk_assessment_reference.model_dump(mode="json")
            if risk_assessment_reference else None,
            "risk_alert_references": result.alert_ids,
            "risk_explanation": explanation_payload,
            "limitations": existing_limitations + new_limitations,
            "warnings": warnings,
            "findings": {
                **dict(state.get("findings", {})),
                "risk_status": result.status,
                "risk_score": result.risk_score,
                "risk_level": result.risk_level,
                "risk_confidence": result.confidence,
                "risk_factor_count": result.factor_count,
                "risk_assessment_id": result.assessment_id,
                "risk_recommendation_ids": result.recommendation_ids,
            },
        }

        # 6. Validate state write boundaries before returning
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="risk_agent",
            writer_stage=AgentStage.RISK_ASSESSMENT,
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
                organization_id=organization_id or "unknown_org",
                actor_id=actor_id or "unknown_actor",
                request_id=request_id or "unknown_req",
                correlation_id=correlation_id or "unknown_corr",
                trace_id=trace_id or "unknown_trace",
                node_name="risk_agent",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )
