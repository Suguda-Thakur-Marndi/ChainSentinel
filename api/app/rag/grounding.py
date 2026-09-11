"""RAG Context Assembly, Grounding & Citation Integrity service for RiskWise 2.0.

Provides rigorous citation verification, authentic substring excerpt validation, domain anchor
grounding to RiskWise entities (RiskAssessment, Supplier, Shipment, Facility), token budgeting
with synchronized citation pruning, untrusted data demarcation, and audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.models.governance import AuditLog
from app.models.knowledge import Document, DocumentChunk
from app.rag.contracts import (
    DataTrustBoundary,
    GroundedContextItem,
    GroundedItemType,
    GroundingStatus,
    RAGContext,
    RAGContextCitation,
    RetrievalProvenance,
    RetrievalQuery,
    RetrievalResultSet,
    RetrievedChunk,
    detect_prompt_injection_indicators,
    format_rag_data_envelope,
    generate_deterministic_citation_id,
    generate_deterministic_context_id,
    validate_no_secrets_in_metadata,
)
from app.rag.errors import (
    RAGCitationIntegrityError,
    RAGProvenanceLineageError,
    RAGSecurityPolicyViolationError,
    RAGTenantIsolationError,
)
from app.repositories.audit_log import AuditLogRepository


class GroundingAnchor(BaseModel):
    """Domain grounding anchors tying contextual knowledge to RiskWise business entities."""
    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(..., min_length=1, max_length=64)
    signal_id: Optional[str] = Field(None, max_length=64)
    assessment_id: Optional[str] = Field(None, max_length=64)
    entity_type: Optional[str] = Field(None, max_length=50)  # "SUPPLIER", "SHIPMENT", "PORT", "FACILITY", "ROUTE"
    entity_id: Optional[str] = Field(None, max_length=64)
    extra_anchors: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be a non-empty string in GroundingAnchor.")
        return v.strip()

    @field_validator("extra_anchors")
    @classmethod
    def validate_anchor_secrets(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_secrets_in_metadata(v)
        return v


class ContextBudgetConfig(BaseModel):
    """Configuration governing context token budgets, chunk limits, and truncation rules."""
    model_config = ConfigDict(extra="forbid")

    max_context_tokens: int = Field(default=4000, ge=10, le=32000)
    max_chunks: int = Field(default=10, ge=1, le=50)
    preserve_minimum_chunks: int = Field(default=1, ge=1)
    truncation_strategy: str = Field(default="RANK_PRIORITY")  # "RANK_PRIORITY"


class CitationVerificationResult(BaseModel):
    """Authoritative validation report certifying the integrity and authenticity of citations."""
    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    total_citations: int = Field(..., ge=0)
    valid_citations: int = Field(..., ge=0)
    invalid_citations: int = Field(..., ge=0)
    unresolvable_citations: List[str] = Field(default_factory=list)
    hallucinated_excerpts: List[str] = Field(default_factory=list)
    grounding_coverage_score: float = Field(..., ge=0.0, le=1.0)
    details: List[Dict[str, Any]] = Field(default_factory=list)


def validate_citation_integrity(
    context: RAGContext,
    retrieved_result_set: RetrievalResultSet,
    strict: bool = True,
) -> CitationVerificationResult:
    """Validate that every citation and grounded item resolves to an actual retrieved chunk with unbroken provenance.

    Rejects:
    - Tenant mismatches across query, result set, context, citations, and chunks
    - Unknown / fabricated chunk IDs not in retrieved_result_set
    - Unknown document IDs or mismatched document/chunk parentage
    - Citations to filtered-out / pruned chunks not present in context.source_chunks
    - Missing retrieval provenance
    - Malformed citation structures
    - Hallucinated or non-verbatim excerpts
    """
    # 1. Strict tenant boundary validation
    if context.organization_id != retrieved_result_set.organization_id:
        if strict:
            raise RAGTenantIsolationError(
                f"Context tenant '{context.organization_id}' does not match retrieval result set tenant '{retrieved_result_set.organization_id}'."
            )

    total_citations = len(context.citations)
    if total_citations == 0:
        return CitationVerificationResult(
            is_valid=True,
            total_citations=0,
            valid_citations=0,
            invalid_citations=0,
            grounding_coverage_score=1.0,
        )

    retrieved_map: Dict[str, RetrievedChunk] = {c.chunk_id: c for c in retrieved_result_set.chunks}
    source_map: Dict[str, RetrievedChunk] = {c.chunk_id: c for c in context.source_chunks}

    # Verify that all chunks in context.source_chunks originated in retrieved_result_set
    for chunk in context.source_chunks:
        if chunk.organization_id != context.organization_id:
            if strict:
                raise RAGTenantIsolationError(
                    f"Cross-tenant chunk '{chunk.chunk_id}' belongs to '{chunk.organization_id}', context scoped to '{context.organization_id}'."
                )
        if chunk.chunk_id not in retrieved_map:
            if strict:
                raise RAGProvenanceLineageError(
                    f"Source chunk '{chunk.chunk_id}' was not found in the authoritative retrieval result set."
                )

    unresolvable: List[str] = []
    hallucinated_excerpts: List[str] = []
    details: List[Dict[str, Any]] = []
    valid_count = 0

    for cit in context.citations:
        # A. Malformed citation check
        if not cit.citation_key or not cit.chunk_id or not cit.document_id:
            if strict:
                raise RAGCitationIntegrityError(
                    f"Malformed citation reference: key='{cit.citation_key}', chunk_id='{cit.chunk_id}', doc_id='{cit.document_id}'."
                )
            unresolvable.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "MALFORMED_CITATION",
                "reason": "Citation has missing key, chunk_id, or document_id.",
            })
            continue

        # B. Tenant check on citation
        if cit.organization_id and cit.organization_id != context.organization_id:
            if strict:
                raise RAGTenantIsolationError(
                    f"Cross-tenant citation '{cit.citation_key}' belongs to '{cit.organization_id}', context scoped to '{context.organization_id}'."
                )
            unresolvable.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "CROSS_TENANT_CITATION",
                "reason": f"Citation belongs to '{cit.organization_id}', context is '{context.organization_id}'.",
            })
            continue

        # C. Unknown / Non-retrieved chunk check
        retrieved_chunk = retrieved_map.get(cit.chunk_id)
        if not retrieved_chunk:
            if strict:
                raise RAGCitationIntegrityError(
                    f"Citation '{cit.citation_key}' references non-retrieved chunk_id '{cit.chunk_id}'."
                )
            unresolvable.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "UNRESOLVABLE_CHUNK",
                "reason": f"Chunk ID '{cit.chunk_id}' was never retrieved in result set '{retrieved_result_set.retrieval_id}'.",
            })
            continue

        # D. Citation to filtered-out chunk check
        if cit.chunk_id not in source_map:
            if strict:
                raise RAGCitationIntegrityError(
                    f"Citation '{cit.citation_key}' references chunk_id '{cit.chunk_id}' that was filtered out or pruned from context source_chunks."
                )
            unresolvable.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "FILTERED_OUT_CHUNK",
                "reason": f"Chunk ID '{cit.chunk_id}' was pruned from context during token budgeting and cannot be cited.",
            })
            continue

        # E. Document / Chunk parentage relationship check
        if cit.document_id != retrieved_chunk.document_id:
            if strict:
                raise RAGCitationIntegrityError(
                    f"Citation '{cit.citation_key}' claims document_id '{cit.document_id}', but chunk belongs to '{retrieved_chunk.document_id}'."
                )
            unresolvable.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "DOCUMENT_CHUNK_MISMATCH",
                "reason": f"Document ID mismatch: citation '{cit.document_id}' vs chunk '{retrieved_chunk.document_id}'.",
            })
            continue

        # F. Missing provenance check
        if not retrieved_chunk.provenance:
            if strict:
                raise RAGProvenanceLineageError(
                    f"Retrieved chunk '{cit.chunk_id}' has missing provenance metadata."
                )
            unresolvable.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "MISSING_PROVENANCE",
                "reason": f"Retrieved chunk '{cit.chunk_id}' has no provenance record.",
            })
            continue

        if cit.chunk_index is not None and cit.chunk_index != retrieved_chunk.provenance.chunk_index:
            if strict:
                raise RAGProvenanceLineageError(
                    f"Citation '{cit.citation_key}' chunk_index ({cit.chunk_index}) does not match provenance chunk_index ({retrieved_chunk.provenance.chunk_index})."
                )

        # G. Authentic excerpt verification
        clean_excerpt = re.sub(r"\s+", " ", cit.excerpt.rstrip(". \t\n\r")).strip().lower()
        clean_content = re.sub(r"\s+", " ", retrieved_chunk.content).strip().lower()

        if clean_excerpt and clean_excerpt not in clean_content:
            if strict:
                raise RAGCitationIntegrityError(
                    f"Citation '{cit.citation_key}' excerpt is not an authentic substring of chunk '{cit.chunk_id}'."
                )
            hallucinated_excerpts.append(cit.citation_key)
            details.append({
                "citation_key": cit.citation_key,
                "status": "HALLUCINATED_EXCERPT",
                "reason": "Citation excerpt does not appear as an authentic substring of referenced chunk content.",
            })
            continue

        valid_count += 1
        details.append({
            "citation_key": cit.citation_key,
            "status": "VERIFIED",
            "chunk_id": cit.chunk_id,
            "document_title": cit.document_title,
        })

    # Validate grounded context items if present
    for item in context.grounded_items:
        if item.organization_id != context.organization_id:
            if strict:
                raise RAGTenantIsolationError(
                    f"Cross-tenant grounded item '{item.item_id}' belongs to '{item.organization_id}', context scoped to '{context.organization_id}'."
                )
        if item.chunk_id not in source_map:
            if strict:
                raise RAGProvenanceLineageError(
                    f"Grounded item '{item.item_id}' references chunk_id '{item.chunk_id}' not present in context source_chunks."
                )
        item_chunk = source_map[item.chunk_id]
        if item.document_id != item_chunk.document_id:
            if strict:
                raise RAGCitationIntegrityError(
                    f"Grounded item '{item.item_id}' document_id '{item.document_id}' does not match chunk document_id '{item_chunk.document_id}'."
                )

    invalid_count = len(unresolvable) + len(hallucinated_excerpts)
    coverage_score = round(valid_count / total_citations, 4) if total_citations > 0 else 1.0
    is_valid = (invalid_count == 0)

    return CitationVerificationResult(
        is_valid=is_valid,
        total_citations=total_citations,
        valid_citations=valid_count,
        invalid_citations=invalid_count,
        unresolvable_citations=unresolvable,
        hallucinated_excerpts=hallucinated_excerpts,
        grounding_coverage_score=coverage_score,
        details=details,
    )


class RAGGroundingService:
    """Service orchestrating context assembly, citation integrity verification, and domain grounding."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def verify_grounding_anchors(
        self,
        anchor: GroundingAnchor,
        current_user_org_id: Optional[str] = None,
        strict_existence: bool = True,
    ) -> bool:
        """Verify that referenced domain entities (RiskAssessment, Supplier, Shipment, etc.) exist and belong to the tenant.

        Raises RAGTenantIsolationError on cross-tenant references, and RAGProvenanceLineageError if the entity does not exist.
        """
        org_id = anchor.organization_id.strip()

        # Enforce server-side tenant isolation
        if current_user_org_id and current_user_org_id.strip() != org_id:
            raise RAGTenantIsolationError(
                f"User tenant '{current_user_org_id}' cannot ground context to tenant '{org_id}'."
            )

        # 1. Verify RiskAssessment anchor if present
        if anchor.assessment_id:
            from app.models.risk import RiskAssessment

            assessment = self.session.query(RiskAssessment).filter(
                RiskAssessment.id == anchor.assessment_id
            ).first()

            if not assessment:
                if strict_existence:
                    raise RAGProvenanceLineageError(
                        f"Grounding anchor RiskAssessment '{anchor.assessment_id}' not found."
                    )
            elif assessment.org_id != org_id:
                raise RAGTenantIsolationError(
                    f"Cross-tenant grounding attack: RiskAssessment '{anchor.assessment_id}' belongs to organization '{assessment.org_id}', not '{org_id}'."
                )

        # 2. Verify domain entity anchor if present
        if anchor.entity_type and anchor.entity_id:
            entity_type_upper = anchor.entity_type.strip().upper()

            if entity_type_upper == "SUPPLIER":
                from app.models.network import Supplier

                sup = self.session.query(Supplier).filter(Supplier.id == anchor.entity_id).first()
                if not sup:
                    if strict_existence:
                        raise RAGProvenanceLineageError(f"Grounding anchor Supplier '{anchor.entity_id}' not found.")
                elif sup.org_id != org_id:
                    raise RAGTenantIsolationError(
                        f"Cross-tenant grounding attack: Supplier '{anchor.entity_id}' belongs to '{sup.org_id}', not '{org_id}'."
                    )

            elif entity_type_upper == "SHIPMENT":
                from app.models.logistics import Shipment

                shipment = self.session.query(Shipment).filter(Shipment.id == anchor.entity_id).first()
                if not shipment:
                    if strict_existence:
                        raise RAGProvenanceLineageError(f"Grounding anchor Shipment '{anchor.entity_id}' not found.")
                elif shipment.org_id != org_id:
                    raise RAGTenantIsolationError(
                        f"Cross-tenant grounding attack: Shipment '{anchor.entity_id}' belongs to '{shipment.org_id}', not '{org_id}'."
                    )

            elif entity_type_upper in ("FACILITY", "WAREHOUSE", "FACTORY"):
                from app.models.network import Factory, Warehouse

                wh = self.session.query(Warehouse).filter(Warehouse.id == anchor.entity_id).first()
                fac = wh or self.session.query(Factory).filter(Factory.id == anchor.entity_id).first()

                if not fac:
                    if strict_existence:
                        raise RAGProvenanceLineageError(f"Grounding anchor Facility '{anchor.entity_id}' not found.")
                elif fac.org_id != org_id:
                    raise RAGTenantIsolationError(
                        f"Cross-tenant grounding attack: Facility '{anchor.entity_id}' belongs to '{fac.org_id}', not '{org_id}'."
                    )

            elif entity_type_upper == "PORT":
                from app.models.network import Port

                port = self.session.query(Port).filter(Port.id == anchor.entity_id).first()
                if not port:
                    if strict_existence:
                        raise RAGProvenanceLineageError(f"Grounding anchor Port '{anchor.entity_id}' not found.")

            elif entity_type_upper == "ROUTE":
                from app.models.network import Route

                route = self.session.query(Route).filter(Route.id == anchor.entity_id).first()
                if not route:
                    if strict_existence:
                        raise RAGProvenanceLineageError(f"Grounding anchor Route '{anchor.entity_id}' not found.")
                elif route.org_id and route.org_id != org_id:
                    raise RAGTenantIsolationError(
                        f"Cross-tenant grounding attack: Route '{anchor.entity_id}' belongs to '{route.org_id}', not '{org_id}'."
                    )

        return True

    def verify_citation_integrity(
        self,
        context: RAGContext,
    ) -> CitationVerificationResult:
        """Verify that every citation in a RAGContext resolves 1:1 to a source chunk with authentic excerpt text.

        Backward-compatible non-strict verification against context.source_chunks.
        """
        total = len(context.citations)
        if total == 0:
            return CitationVerificationResult(
                is_valid=True,
                total_citations=0,
                valid_citations=0,
                invalid_citations=0,
                grounding_coverage_score=1.0,
            )

        source_map: Dict[str, RetrievedChunk] = {c.chunk_id: c for c in context.source_chunks}
        unresolvable: List[str] = []
        hallucinated_excerpts: List[str] = []
        details: List[Dict[str, Any]] = []
        valid_count = 0

        for cit in context.citations:
            # 1. Chunk existence verification
            chunk = source_map.get(cit.chunk_id)
            if not chunk:
                unresolvable.append(cit.citation_key)
                details.append({
                    "citation_key": cit.citation_key,
                    "status": "UNRESOLVABLE_CHUNK",
                    "reason": f"Chunk ID '{cit.chunk_id}' not found in source_chunks.",
                })
                continue

            # 2. Excerpt authenticity verification
            clean_excerpt = re.sub(r"\s+", " ", cit.excerpt.rstrip(". \t\n\r")).strip().lower()
            clean_content = re.sub(r"\s+", " ", chunk.content).strip().lower()

            if clean_excerpt and clean_excerpt not in clean_content:
                hallucinated_excerpts.append(cit.citation_key)
                details.append({
                    "citation_key": cit.citation_key,
                    "status": "HALLUCINATED_EXCERPT",
                    "reason": "Citation excerpt does not appear as an authentic substring of referenced chunk content.",
                })
                continue

            valid_count += 1
            details.append({
                "citation_key": cit.citation_key,
                "status": "VERIFIED",
                "chunk_id": cit.chunk_id,
                "document_title": cit.document_title,
            })

        invalid_count = len(unresolvable) + len(hallucinated_excerpts)
        coverage_score = round(valid_count / total, 4) if total > 0 else 1.0
        is_valid = (invalid_count == 0)

        return CitationVerificationResult(
            is_valid=is_valid,
            total_citations=total,
            valid_citations=valid_count,
            invalid_citations=invalid_count,
            unresolvable_citations=unresolvable,
            hallucinated_excerpts=hallucinated_excerpts,
            grounding_coverage_score=coverage_score,
            details=details,
        )

    def validate_citation_integrity(
        self,
        context: RAGContext,
        retrieved_result_set: RetrievalResultSet,
        strict: bool = True,
    ) -> CitationVerificationResult:
        """Validate citation integrity against the authoritative retrieval result set."""
        return validate_citation_integrity(context, retrieved_result_set, strict=strict)

    def assemble_grounded_context(
        self,
        result_set: RetrievalResultSet,
        query: RetrievalQuery,
        anchor: Optional[GroundingAnchor] = None,
        budget: Optional[ContextBudgetConfig] = None,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        auto_commit: bool = True,
        strict_anchor_validation: bool = True,
    ) -> RAGContext:
        """Assemble a grounded, cited, tenant-isolated, and token-budgeted RAGContext.

        Orchestrates:
        1. Tenant validation across query, result set, and grounding anchor.
        2. Token budgeting and prioritized chunk pruning with limitations recording.
        3. Strict citation synchronization (pruned chunks have citations eliminated).
        4. Deterministic citation IDs and GroundedContextItem mapping.
        5. Authentic excerpt generation and 100% citation integrity certification.
        6. Heuristic prompt-injection scanning and XML CDATA trust demarcation.
        7. Deterministic context ID generation and immutable audit logging.
        """
        org_id = query.organization_id.strip()

        # Enforce server-side tenant isolation
        if result_set.organization_id != org_id:
            raise RAGTenantIsolationError(
                f"ResultSet org '{result_set.organization_id}' does not match query org '{org_id}'."
            )

        if current_user_org_id and current_user_org_id.strip() != org_id:
            raise RAGTenantIsolationError(
                f"User tenant '{current_user_org_id}' cannot assemble context for tenant '{org_id}'."
            )

        # Verify grounding anchors if provided
        if anchor:
            if anchor.organization_id != org_id:
                raise RAGTenantIsolationError(
                    f"GroundingAnchor org '{anchor.organization_id}' does not match context org '{org_id}'."
                )
            self.verify_grounding_anchors(
                anchor,
                current_user_org_id=current_user_org_id,
                strict_existence=strict_anchor_validation,
            )

        budget_cfg = budget or ContextBudgetConfig()

        # 1. Apply budget constraints (chunks are already ordered deterministically by score DESC)
        candidate_chunks = result_set.chunks[: budget_cfg.max_chunks]
        pruned_chunks: List[RetrievedChunk] = []
        accumulated_tokens = 0
        limitations: List[str] = []

        for chunk in candidate_chunks:
            chunk_tokens = chunk.token_count if chunk.token_count > 0 else max(1, len(chunk.content.split()))

            # Check if adding this chunk exceeds token ceiling (unless preserving minimum chunks)
            if len(pruned_chunks) >= budget_cfg.preserve_minimum_chunks:
                if accumulated_tokens + chunk_tokens > budget_cfg.max_context_tokens:
                    limitations.append(
                        f"Context token budget exceeded ({budget_cfg.max_context_tokens} tokens); pruned remaining retrieved chunks."
                    )
                    break

            pruned_chunks.append(chunk)
            accumulated_tokens += chunk_tokens

        if len(result_set.chunks) > len(pruned_chunks) and not limitations:
            limitations.append(
                f"Candidate chunk limit reached ({budget_cfg.max_chunks} max chunks); truncated {len(result_set.chunks) - len(pruned_chunks)} lower-ranked chunks."
            )

        # 2. Build citations, grounded items, and XML sections synchronized with preserved chunks
        citations: List[RAGContextCitation] = []
        grounded_items: List[GroundedContextItem] = []
        envelope_sections: List[str] = []
        all_injection_indicators: List[str] = []

        for idx, chunk in enumerate(pruned_chunks, start=1):
            citation_key = f"[CIT-{idx}]"
            citation_id = generate_deterministic_citation_id(
                organization_id=org_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                retrieval_id=result_set.retrieval_id,
            )

            # Derive clean authentic excerpt directly from chunk text
            raw_text = chunk.content.strip()
            if len(raw_text) > 150:
                excerpt_candidate = raw_text[:150]
                last_space = excerpt_candidate.rfind(" ")
                if last_space > 80:
                    excerpt = excerpt_candidate[:last_space].strip()
                else:
                    excerpt = excerpt_candidate.strip()
            else:
                excerpt = raw_text

            citation = RAGContextCitation(
                citation_key=citation_key,
                citation_id=citation_id,
                organization_id=org_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                document_title=chunk.provenance.document_title,
                chunk_index=chunk.provenance.chunk_index,
                source_url=chunk.provenance.source_url,
                s3_uri=chunk.provenance.s3_uri,
                excerpt=excerpt,
            )
            citations.append(citation)

            # Check prompt injection markers
            injection_indicators = detect_prompt_injection_indicators(chunk.content)
            if injection_indicators:
                chunk.prompt_injection_flags.extend(injection_indicators)
                all_injection_indicators.extend(injection_indicators)

            is_safe = len(chunk.prompt_injection_flags) == 0
            item = GroundedContextItem(
                item_id=f"ITEM-{idx}",
                item_type=GroundedItemType.RETRIEVED_FACT if is_safe else GroundedItemType.UNSAFE_CONTENT,
                content=chunk.content,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                organization_id=org_id,
                citation_id=citation_id,
                citation_key=citation_key,
                provenance=chunk.provenance,
                is_safe=is_safe,
                prompt_injection_flags=list(chunk.prompt_injection_flags),
            )
            grounded_items.append(item)

            # Format data inside safe XML envelope
            chunk_ref = f"{citation_key} Doc:{chunk.provenance.document_title}#Chunk{chunk.provenance.chunk_index}"
            envelope_sections.append(format_rag_data_envelope(chunk.content, chunk_ref))

        assembled_text = "\n\n".join(envelope_sections)
        chunk_ids = [c.chunk_id for c in pruned_chunks]

        # 3. Deterministic context ID
        context_id = generate_deterministic_context_id(
            organization_id=org_id,
            retrieval_id=result_set.retrieval_id,
            chunk_ids=chunk_ids,
        )

        trust_boundary = DataTrustBoundary(
            is_untrusted_data=True,
            contains_instructions=False,
            sanitized=True,
            injection_risk_detected=len(all_injection_indicators) > 0,
            detected_risk_indicators=sorted(list(set(all_injection_indicators))),
            safety_envelope_format="XML_ENCLOSED_PASSIVE_DATA",
        )

        # 4. Compute authoritative GroundingStatus
        if len(pruned_chunks) == 0:
            grounding_status = GroundingStatus.UNGROUNDED
        elif all(not item.is_safe for item in grounded_items):
            grounding_status = GroundingStatus.UNSAFE_SOURCE
        elif any(not item.is_safe for item in grounded_items) or len(pruned_chunks) < len(result_set.chunks) or len(limitations) > 0:
            grounding_status = GroundingStatus.PARTIALLY_GROUNDED
        else:
            grounding_status = GroundingStatus.GROUNDED

        rag_context = RAGContext(
            context_id=context_id,
            organization_id=org_id,
            query_text=query.query_text,
            assembled_text=assembled_text,
            citations=citations,
            source_chunks=pruned_chunks,
            total_tokens=accumulated_tokens,
            assembled_at=datetime.now(timezone.utc),
            trust_boundary=trust_boundary,
            grounding_status=grounding_status,
            grounded_items=grounded_items,
            limitations=limitations,
            grounding_signal_id=anchor.signal_id if anchor else None,
            grounding_assessment_id=anchor.assessment_id if anchor else None,
        )

        # 5. Mandatory Citation & Grounding Integrity Certification
        validate_citation_integrity(rag_context, result_set, strict=True)

        # 6. Append immutable audit log
        audit_repo = AuditLogRepository(self.session)
        audit_payload = {
            "context_id": context_id,
            "retrieval_id": result_set.retrieval_id,
            "query_id": query.query_id,
            "citation_count": len(citations),
            "chunk_count": len(pruned_chunks),
            "context_units": accumulated_tokens,
            "grounding_status": grounding_status.value,
            "grounding_signal_id": rag_context.grounding_signal_id,
            "grounding_assessment_id": rag_context.grounding_assessment_id,
            "injection_risk_detected": trust_boundary.injection_risk_detected,
        }
        validate_no_secrets_in_metadata(audit_payload)

        audit_repo.append_log(
            org_id=org_id,
            actor_id=actor_id or "system",
            action="RAG_CONTEXT_ASSEMBLED",
            resource_type="RAGContext",
            resource_id=context_id,
            status="SUCCESS",
            actor_type="SYSTEM" if not actor_id else "USER",
            after_json=audit_payload,
            auto_commit=auto_commit,
        )

        return rag_context

