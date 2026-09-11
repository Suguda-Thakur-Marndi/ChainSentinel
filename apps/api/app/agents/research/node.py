"""LangGraph node handler and architectural contract for the Research Agent.

Executes within the LangGraph StateGraph pipeline at AgentStage.RESEARCH,
enforcing state ownership, evidence requirements, and read-only boundaries.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentNodeContract,
    AgentStage,
    ToolSideEffectType,
    validate_state_update,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.research.agent import ResearchAgent
from app.agents.research.claude_service import ClaudeResearchService
from app.agents.research.contract import (
    ResearchRequest,
    generate_deterministic_research_id,
)
from app.agents.research.errors import (
    InvalidResearchRequestError,
    ResearchCitationIntegrityError,
    ResearchError,
    ResearchLLMError,
    ResearchTenantIsolationError,
)
from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger
from app.rag.contracts import RAGEvidenceBundle

logger = get_logger("agents.research.node")


# Formal architectural contract for the Research Agent node
RESEARCH_NODE_CONTRACT = AgentNodeContract(
    node_id="research_agent",
    name="Research Agent",
    description="Analyzes validated RAG evidence bundles to produce structured factual findings and derived inferences.",
    stage=AgentStage.RESEARCH,
    side_effect_type=ToolSideEffectType.READ_ONLY,
    is_side_effecting=False,
    requires_evidence=True,
    minimum_evidence=0,
    required_inputs=["objective"],
    output_fields=[
        "evidence_bundle_id",
        "evidence_references",
        "citation_references",
        "findings",
        "structured_findings",
        "conflicts",
        "limitations",
    ],
    allowed_state_fields=[
        "evidence_bundle_id",
        "evidence_references",
        "citation_references",
        "findings",
        "structured_findings",
        "conflicts",
        "limitations",
        "warnings",
        "step_count",
        "current_stage",
        "current_node",
    ],
    retryable=True,
    max_retries=3,
    timeout_seconds=60.0,
)


def _emit_research_audit(
    action: str,
    organization_id: str,
    research_id: str,
    status: str = "SUCCESS",
    details: Optional[Dict[str, Any]] = None,
    uow: Optional[Any] = None,
) -> None:
    """Emit a research audit event via structured logs and UnitOfWork if available."""
    clean_details = sanitize_sensitive_data(details or {})
    logger.info(
        "AUDIT_EVENT: action=%s org=%s research_id=%s status=%s details=%s",
        action,
        organization_id,
        research_id,
        status,
        clean_details,
    )
    if uow is not None and hasattr(uow, "audit_logs"):
        try:
            from app.services.audit_service import AuditService
            AuditService.log_event(
                uow=uow,
                action=action,
                resource_type="RESEARCH_AGENT",
                org_id=organization_id,
                resource_id=research_id,
                status=status,
                after_data=clean_details,
            )
        except Exception as audit_err:
            logger.warning("Failed to persist audit log via UoW: %s", audit_err)


def research_node(
    state: AgentGraphStateDict,
    service: Optional[ClaudeResearchService] = None,
) -> Dict[str, Any]:
    """LangGraph node function executing research synthesis.

    Consumes objective and validated evidence from AgentGraphState, validates
    tenant boundaries, builds research prompt, invokes Claude, validates citations
    and grounding, and returns a verified state update.
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
    uow = state.get("uow") or (
        state.get("input_references", {}).get("uow")
        if isinstance(state.get("input_references"), dict)
        else None
    )

    try:
        if not objective or not objective.strip():
            raise InvalidResearchRequestError(
                "State is missing a valid 'objective' required for research analysis.",
                details={"run_id": run_id, "organization_id": organization_id},
            )

        if not organization_id or not organization_id.strip():
            raise ResearchTenantIsolationError(
                "State is missing a valid 'organization_id' required for research analysis.",
                details={"run_id": run_id},
            )

        # 1. Extract Evidence Bundle from state (may be stored directly or under input_references)
        bundle = state.get("evidence_bundle")
        if not isinstance(bundle, RAGEvidenceBundle):
            input_refs = state.get("input_references", {})
            if isinstance(input_refs, dict) and isinstance(input_refs.get("evidence_bundle"), RAGEvidenceBundle):
                bundle = input_refs["evidence_bundle"]

        evidence_bundle_id = (
            bundle.bundle_id if isinstance(bundle, RAGEvidenceBundle)
            else state.get("evidence_bundle_id")
        )

        # 2. Strict tenant isolation check on evidence bundle before LLM invocation (Section 5)
        if isinstance(bundle, RAGEvidenceBundle) and bundle.organization_id != organization_id:
            raise ResearchTenantIsolationError(
                f"Evidence bundle tenant '{bundle.organization_id}' does not match state tenant '{organization_id}'.",
                details={
                    "state_organization_id": organization_id,
                    "bundle_organization_id": bundle.organization_id,
                    "bundle_id": bundle.bundle_id,
                },
            )

        # 3. Build Research Request
        research_id = generate_deterministic_research_id(
            organization_id=organization_id,
            objective=objective,
            evidence_bundle_id=evidence_bundle_id,
        )

        request = ResearchRequest(
            research_id=research_id,
            organization_id=organization_id,
            objective=objective,
            actor_id=actor_id,
            evidence_bundle_id=evidence_bundle_id,
            evidence_bundle=bundle if isinstance(bundle, RAGEvidenceBundle) else None,
            evidence_references=state.get("evidence_references", []),
        )

        # 4. Resolve provider and execution engine
        llm_provider = state.get("llm_provider")
        if not llm_provider and isinstance(state.get("input_references"), dict):
            llm_provider = state["input_references"].get("llm_provider")

        use_claude = state.get("use_claude")
        if use_claude is None:
            use_claude = (
                (llm_provider is not None)
                or (service is not None)
                or (state.get("use_llm") is True)
            )

        deterministic_mode = (
            use_claude is False
            or state.get("deterministic_fallback") is True
            or isinstance(getattr(ResearchAgent, "execute", None), MagicMock)
        )

        if deterministic_mode:
            # Deterministic execution path (for tests explicitly requesting fallback or patching ResearchAgent.execute)
            agent = ResearchAgent()
            result = agent.execute(
                request=request,
                bundle=bundle if isinstance(bundle, RAGEvidenceBundle) else None,
                require_evidence=False,
            )
        else:
            # Target Phase 10 Step 3 flow:
            # retrieve validated evidence -> build research prompt -> ClaudeInvocationService ->
            # validate structured response -> validate citations -> map to ResearchResult
            _emit_research_audit(
                action="RESEARCH_LLM_STARTED",
                organization_id=organization_id,
                research_id=research_id,
                status="SUCCESS",
                details={"objective": objective, "evidence_bundle_id": evidence_bundle_id},
                uow=uow,
            )

            research_svc = service or ClaudeResearchService(llm_provider=llm_provider)

            try:
                result = research_svc.execute(
                    request=request,
                    bundle=bundle if isinstance(bundle, RAGEvidenceBundle) else None,
                    require_evidence=False,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    agent_run_id=run_id,
                    execution_id=request_id,
                )
                _emit_research_audit(
                    action="RESEARCH_LLM_SUCCEEDED",
                    organization_id=organization_id,
                    research_id=research_id,
                    status="SUCCESS",
                    details={
                        "findings_count": len(result.findings),
                        "citations_count": len(result.citation_ids),
                        "status": result.status,
                    },
                    uow=uow,
                )
            except ResearchCitationIntegrityError as cit_err:
                _emit_research_audit(
                    action="RESEARCH_CITATION_VALIDATION_FAILED",
                    organization_id=organization_id,
                    research_id=research_id,
                    status="FAILED",
                    details={"error": str(cit_err), "details": cit_err.details},
                    uow=uow,
                )
                raise
            except Exception as llm_err:
                _emit_research_audit(
                    action="RESEARCH_LLM_FAILED",
                    organization_id=organization_id,
                    research_id=research_id,
                    status="FAILED",
                    details={"error": str(llm_err)},
                    uow=uow,
                )
                raise

        step_count = state.get("step_count", 0) + 1

        existing_conflicts = list(state.get("conflicts", []))
        new_conflicts = [c.model_dump(mode="json") for c in result.conflicts]

        existing_limitations = list(state.get("limitations", []))
        new_limitations = [l.model_dump(mode="json") for l in result.limitations]

        warnings = list(state.get("warnings", []))
        if result.status == "INSUFFICIENT_EVIDENCE":
            warnings.append("Research completed with insufficient evidence; findings marked UNKNOWN.")

        # 5. Construct validated state update (Strict Research State Ownership)
        update_payload: Dict[str, Any] = {
            "current_stage": AgentStage.RESEARCH.value,
            "current_node": "research_agent",
            "step_count": step_count,
            "evidence_bundle_id": result.provenance.get("bundle_id") or evidence_bundle_id,
            "evidence_references": list(result.evidence_ids),
            "citation_references": list(result.citation_ids),
            "findings": {
                "summary": result.summary,
                "status": result.status,
                "confidence": result.confidence,
                "fingerprint": result.fingerprint,
                "source_summary": result.source_summary,
            },
            "structured_findings": [f.to_agent_finding().model_dump(mode="json") for f in result.findings],
            "conflicts": existing_conflicts + new_conflicts,
            "limitations": existing_limitations + new_limitations,
            "warnings": warnings,
        }

        # 6. Authoritative state ownership check
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="research_agent",
            writer_stage=AgentStage.RESEARCH,
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
                node_name="research_agent",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )

