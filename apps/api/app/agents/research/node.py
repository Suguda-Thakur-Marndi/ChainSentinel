"""LangGraph node handler and architectural contract for the Research Agent.

Executes within the LangGraph StateGraph pipeline at AgentStage.RESEARCH,
enforcing state ownership, evidence requirements, and read-only boundaries.
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
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.research.agent import ResearchAgent
from app.agents.research.contract import (
    ResearchRequest,
    generate_deterministic_research_id,
)
from app.agents.research.errors import (
    InvalidResearchRequestError,
    ResearchError,
)
from app.rag.contracts import RAGEvidenceBundle


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


def research_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """LangGraph node function executing deterministic research analysis.

    Consumes objective and evidence from AgentGraphState, validates tenant
    and evidence boundaries, runs ResearchAgent, and returns a verified state update.
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

    try:
        if not objective or not objective.strip():
            raise InvalidResearchRequestError(
                "State is missing a valid 'objective' required for research analysis.",
                details={"run_id": run_id, "organization_id": organization_id},
            )

        # 1. Extract Evidence Bundle from state (may be stored directly or under input_references)
        bundle = state.get("evidence_bundle")
        if not isinstance(bundle, RAGEvidenceBundle):
            # Check input_references for bundle instance
            input_refs = state.get("input_references", {})
            if isinstance(input_refs, dict) and isinstance(input_refs.get("evidence_bundle"), RAGEvidenceBundle):
                bundle = input_refs["evidence_bundle"]

        evidence_bundle_id = (
            bundle.bundle_id if isinstance(bundle, RAGEvidenceBundle)
            else state.get("evidence_bundle_id")
        )

        # 2. Build Research Request
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

        agent = ResearchAgent()

        # 3. Execute Research
        result = agent.execute(
            request=request,
            bundle=bundle if isinstance(bundle, RAGEvidenceBundle) else None,
            require_evidence=False,  # If no bundle, agent gracefully produces INSUFFICIENT_EVIDENCE finding
        )

        step_count = state.get("step_count", 0) + 1

        existing_conflicts = list(state.get("conflicts", []))
        new_conflicts = [c.model_dump(mode="json") for c in result.conflicts]

        existing_limitations = list(state.get("limitations", []))
        new_limitations = [l.model_dump(mode="json") for l in result.limitations]

        warnings = list(state.get("warnings", []))
        if result.status == "INSUFFICIENT_EVIDENCE":
            warnings.append("Research completed with insufficient evidence; findings marked UNKNOWN.")

        # 4. Construct validated state update
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

        # 5. Authoritative state ownership check
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
