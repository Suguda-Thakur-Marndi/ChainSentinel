"""LangGraph node handler and architectural contract for the Research Agent.

Executes within the LangGraph StateGraph pipeline at AgentStage.RESEARCH,
enforcing state ownership, evidence requirements, and read-only boundaries.
"""

from __future__ import annotations

import logging
import time
import uuid
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
    if uow is not None:
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
    service: Optional[Any] = None,
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

        provider_status = "UNCONFIGURED"
        if bundle is None:
            # 1a. Attempt external research via Tavily adapter if configured
            try:
                from app.integrations.providers.tavily import TavilyAdapter, TavilySearchRequest
                from app.rag.contracts import GroundingStatus, RAGContextCitation, RAGEvidenceItem, RetrievalProvenance
                adapter = TavilyAdapter()
                api_key = adapter.resolve_api_key()
                if api_key:
                    search_resp = adapter.search(
                        TavilySearchRequest(query=objective, max_results=5),
                        org_id=organization_id,
                    )
                    if search_resp and search_resp.results:
                        provider_status = "LIVE"
                        items: List[RAGEvidenceItem] = []
                        citations: List[RAGContextCitation] = []
                        for idx, res in enumerate(search_resp.results, start=1):
                            ev_id = f"ev_tavily_{idx}"
                            cit_key = f"[CIT-TAV-{idx}]"
                            cit_id = f"cit_tavily_{idx}"
                            excerpt = (res.content[:250] + "...") if len(res.content) > 250 else res.content
                            ret_id = f"ret_tavily_{idx}"
                            prov = RetrievalProvenance(
                                retrieval_id=ret_id,
                                document_id=f"doc_tavily_{idx}",
                                chunk_id=f"chk_tavily_{idx}",
                                organization_id=organization_id,
                                chunk_index=idx,
                                document_title=res.title or "External Intelligence",
                                source_url=res.url,
                                similarity_score=round(res.score, 4) if res.score is not None else 0.85,
                                rank=idx,
                            )
                            items.append(
                                RAGEvidenceItem(
                                    evidence_id=ev_id,
                                    citation_id=cit_id,
                                    citation_key=cit_key,
                                    document_id=prov.document_id,
                                    chunk_id=prov.chunk_id,
                                    organization_id=organization_id,
                                    document_title=prov.document_title,
                                    excerpt=excerpt or "External report findings.",
                                    source_url=res.url,
                                    confidence_score=round(res.score, 2) if res.score is not None else 0.85,
                                    provenance=prov,
                                )
                            )
                            citations.append(
                                RAGContextCitation(
                                    citation_key=cit_key,
                                    citation_id=cit_id,
                                    organization_id=organization_id,
                                    document_id=prov.document_id,
                                    chunk_id=prov.chunk_id,
                                    document_title=prov.document_title,
                                    chunk_index=idx,
                                    source_url=res.url,
                                    excerpt=excerpt,
                                )
                            )
                        bundle = RAGEvidenceBundle(
                            bundle_id=f"bnd_tavily_{uuid.uuid4().hex[:8]}",
                            organization_id=organization_id,
                            query_text=objective,
                            context_id=f"ctx_tavily_{uuid.uuid4().hex[:8]}",
                            retrieval_id=f"ret_tavily_{uuid.uuid4().hex[:8]}",
                            evidence_items=items,
                            citations=citations,
                            grounding_status=GroundingStatus.GROUNDED,
                            total_evidence_units=len(items),
                        )
                    else:
                        provider_status = "DEGRADED"
                else:
                    provider_status = "UNCONFIGURED"
            except Exception as search_err:
                logger.warning("External research adapter search failed: %s", search_err)
                provider_status = "DEGRADED"

            # 1b. Fallback to local RAG if external search produced no bundle
            if bundle is None:
                try:
                    from app.db.session import SessionLocal
                    from app.rag.embeddings import get_embedding_provider
                    from app.rag.pipeline import RAGEvidencePipelineService
                    from app.rag.contracts import RetrievalQuery
                    db = SessionLocal()
                    try:
                        rag_pipeline = RAGEvidencePipelineService(session=db, embedding_provider=get_embedding_provider())
                        rag_query = RetrievalQuery(
                            query_id=f"query_{uuid.uuid4().hex[:8]}",
                            organization_id=organization_id,
                            query_text=objective,
                            top_k=3,
                            similarity_threshold=0.35,
                        )
                        rag_bundle = rag_pipeline.execute_pipeline(
                            query=rag_query,
                            current_user_org_id=organization_id,
                            actor_id=actor_id or "system",
                        )
                        if rag_bundle and rag_bundle.evidence_items:
                            bundle = rag_bundle
                            if provider_status == "UNCONFIGURED":
                                provider_status = "COMPLETED"
                    finally:
                        db.close()
                except Exception as rag_err:
                    logger.debug("RAG fallback retrieval found no chunks: %s", rag_err)

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

        if service is not None:
            # Service execution path (when an explicit research service is injected)
            _emit_research_audit(
                action="RESEARCH_LLM_STARTED",
                organization_id=organization_id,
                research_id=research_id,
                status="SUCCESS",
                details={"objective": objective, "evidence_bundle_id": evidence_bundle_id},
                uow=uow,
            )

            try:
                result = service.execute(
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
        else:
            # Deterministic execution path via authoritative ResearchAgent
            agent = ResearchAgent()
            result = agent.execute(
                request=request,
                bundle=bundle if isinstance(bundle, RAGEvidenceBundle) else None,
                require_evidence=False,
            )

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
                "status": "LIVE" if provider_status == "LIVE" else result.status,
                "provider_status": provider_status,
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

