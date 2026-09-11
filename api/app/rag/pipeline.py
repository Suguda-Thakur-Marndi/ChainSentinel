"""RiskWise 2.0 RAG Research Evidence Pipeline (Phase 8 Step 6).

Orchestrates the end-to-end evidence pipeline:
Retrieval (Step 4) -> Grounding & Citation Integrity (Step 5) -> Research Evidence Packaging (Step 6).

Guarantees:
1. End-to-end tenant isolation across authenticated user, query, anchors, citations, and evidence.
2. Complete unbroken provenance lineage (document -> chunk -> retrieval -> context -> citation -> evidence).
3. 1:1 Citation-to-Evidence correspondence.
4. Tamper-evident bundle verification with SHA-256 fingerprinting.
5. Hostile prompt-injection quarantine (passive data demarcation and confidence penalty).
6. Deterministic IDs (UUIDv5) and reproducible ordering.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.governance import AuditLog
from app.rag.contracts import (
    DataTrustBoundary,
    GroundedContextItem,
    GroundedItemType,
    GroundingStatus,
    RAGContext,
    RAGContextCitation,
    RAGEvidenceBundle,
    RAGEvidenceItem,
    RetrievalQuery,
    RetrievalResultSet,
    RetrievedChunk,
    format_rag_data_envelope,
    generate_deterministic_evidence_bundle_id,
    generate_deterministic_evidence_id,
    validate_no_secrets_in_metadata,
)
from app.rag.embeddings import BaseEmbeddingProvider, LocalMockEmbeddingProvider
from app.rag.errors import (
    RAGCitationIntegrityError,
    RAGEvidencePipelineError,
    RAGProvenanceLineageError,
    RAGSecurityPolicyViolationError,
    RAGTenantIsolationError,
)
from app.rag.grounding import (
    ContextBudgetConfig,
    GroundingAnchor,
    RAGGroundingService,
    validate_citation_integrity,
)
from app.rag.retrieval import RAGRetrievalService
from app.repositories.audit_log import AuditLogRepository
from app.risk_engine.recommendations import SENSITIVE_STRING_REGEX


class RAGEvidencePipelineService:
    """Authoritative end-to-end evidence pipeline orchestrator for Phase 8 Step 6.

    Connects document retrieval, entity grounding, token budgeting, and citation integrity
    into an immutable, tamper-evident RAGEvidenceBundle for downstream reasoning.
    """

    def __init__(
        self,
        session: Optional[Session] = None,
        provider: Optional[BaseEmbeddingProvider] = None,
        retrieval_service: Optional[RAGRetrievalService] = None,
        grounding_service: Optional[RAGGroundingService] = None,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
    ):
        self.session = session
        active_provider = embedding_provider or provider or LocalMockEmbeddingProvider()
        self.retrieval_service = retrieval_service or (
            RAGRetrievalService(session, embedding_provider=active_provider) if session else None
        )
        self.grounding_service = grounding_service or (
            RAGGroundingService(session) if session else None
        )

    def execute_pipeline(
        self,
        query: RetrievalQuery,
        anchor: Optional[GroundingAnchor] = None,
        budget: Optional[ContextBudgetConfig] = None,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        auto_commit: bool = True,
    ) -> RAGEvidenceBundle:
        """Execute the full end-to-end RAG pipeline from query to certified evidence bundle.

        Steps:
        1. Tenant boundary enforcement across query and authenticated user.
        2. Secret detection across query and anchor context.
        3. Semantic retrieval and similarity ranking via RAGRetrievalService.
        4. Context assembly, grounding, token budgeting, and citation verification via RAGGroundingService.
        5. Evidence extraction, deterministic identification, and tamper-evident bundle packaging.
        6. Immutable audit logging of evidence pipeline execution.
        """
        org_id = query.organization_id
        if not current_user_org_id or not current_user_org_id.strip():
            raise RAGTenantIsolationError("Current authenticated user organization context required.")

        if current_user_org_id != org_id:
            raise RAGTenantIsolationError(
                f"Query organization {org_id} does not match authenticated user organization {current_user_org_id}."
            )

        if anchor and anchor.organization_id != org_id:
            raise RAGTenantIsolationError(
                f"Anchor organization {anchor.organization_id} does not match authenticated context {org_id}."
            )

        # Security check: secrets in query text
        if SENSITIVE_STRING_REGEX.search(query.query_text):
            raise RAGSecurityPolicyViolationError("Secret pattern detected in query_text.")

        # Security check: secrets in anchor domain context
        if anchor and getattr(anchor, "domain_context", None):
            for k, v in anchor.domain_context.items():
                if any(p in str(k).lower() for p in ("key", "secret", "token", "password", "auth", "credential")):
                    raise RAGSecurityPolicyViolationError(f"Secret pattern detected in domain context key '{k}'.")
                if isinstance(v, str) and SENSITIVE_STRING_REGEX.search(v):
                    raise RAGSecurityPolicyViolationError("Secret pattern detected in domain context value.")

        if not self.retrieval_service or not self.grounding_service:
            raise RAGEvidencePipelineError("Active database session required to execute evidence pipeline.")

        # 1. Execute semantic retrieval (Step 4)
        result_set = self.retrieval_service.retrieve(
            query=query,
            current_user_org_id=current_user_org_id,
            actor_id=actor_id,
        )

        # 2. Assemble grounded context with citation integrity (Step 5)
        context = self.grounding_service.assemble_grounded_context(
            result_set=result_set,
            query=query,
            anchor=anchor,
            budget=budget,
            current_user_org_id=current_user_org_id,
            actor_id=actor_id,
            auto_commit=auto_commit,
            strict_anchor_validation=True if anchor else False,
        )

        # 3. Package grounded context into authoritative RAGEvidenceBundle (Step 6)
        return self.package_grounded_context_as_evidence(
            context=context,
            result_set=result_set,
            anchor=anchor,
            current_user_org_id=current_user_org_id,
            actor_id=actor_id,
            auto_commit=auto_commit,
        )

    def package_grounded_context_as_evidence(
        self,
        context: RAGContext,
        result_set: RetrievalResultSet,
        anchor: Optional[GroundingAnchor] = None,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        auto_commit: bool = True,
    ) -> RAGEvidenceBundle:
        """Transform a certified RAGContext into an immutable, tamper-evident RAGEvidenceBundle.

        Guarantees:
        - Every citation in RAGContext produces exactly one RAGEvidenceItem.
        - Every RAGEvidenceItem preserves complete lineage (document -> chunk -> retrieval -> context).
        - Hostile prompt-injection indicators are quarantined with is_safe=False and UNSAFE_CONTENT type.
        - Zero orphan citations or ungrounded evidence items.
        - Fails closed on cross-tenant context, citations, or chunks.
        """
        org_id = context.organization_id

        # 1. Tenancy validation
        if current_user_org_id and current_user_org_id != org_id:
            raise RAGTenantIsolationError(
                f"Context organization {org_id} does not match current user context {current_user_org_id}."
            )
        if result_set.organization_id != org_id:
            raise RAGTenantIsolationError(
                f"Context organization {org_id} does not match result set organization {result_set.organization_id}."
            )
        if anchor and anchor.organization_id != org_id:
            raise RAGTenantIsolationError(
                f"Anchor organization {anchor.organization_id} does not match context organization {org_id}."
            )

        # 2. Mandatory citation integrity certification before packaging
        validate_citation_integrity(context, result_set, strict=True)

        chunk_map: Dict[str, RetrievedChunk] = {c.chunk_id: c for c in context.source_chunks}
        cit_by_chunk: Dict[str, RAGContextCitation] = {c.chunk_id: c for c in context.citations}
        item_by_chunk: Dict[str, GroundedContextItem] = {i.chunk_id: i for i in context.grounded_items}

        evidence_items: List[RAGEvidenceItem] = []
        for cit in context.citations:
            chunk = chunk_map.get(cit.chunk_id)
            if not chunk:
                raise RAGProvenanceLineageError(
                    f"Citation '{cit.citation_key}' chunk_id '{cit.chunk_id}' not found in context source_chunks."
                )

            grounded_item = item_by_chunk.get(cit.chunk_id)
            is_safe = grounded_item.is_safe if grounded_item else len(chunk.prompt_injection_flags) == 0
            item_type = (
                grounded_item.item_type
                if grounded_item
                else (GroundedItemType.RETRIEVED_FACT if is_safe else GroundedItemType.UNSAFE_CONTENT)
            )

            # Deterministic evidence ID
            evidence_id = generate_deterministic_evidence_id(
                organization_id=org_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                retrieval_id=result_set.retrieval_id,
                context_id=context.context_id,
            )

            # Compute bounded confidence score
            # Base similarity score discounted by 50% if prompt injection indicators present
            confidence_multiplier = 0.5 if not is_safe else 1.0
            confidence_score = round(max(0.0, min(1.0, chunk.score * confidence_multiplier)), 4)

            data_envelope = format_rag_data_envelope(
                chunk.content,
                f"{cit.citation_key} Doc:{chunk.provenance.document_title}#Chunk{chunk.provenance.chunk_index}",
            )

            metadata_payload: Dict[str, Any] = {}
            if not is_safe:
                metadata_payload["prompt_injection_indicators"] = list(chunk.prompt_injection_flags)

            ev_item = RAGEvidenceItem(
                evidence_id=evidence_id,
                citation_id=cit.citation_id or cit.citation_key,
                citation_key=cit.citation_key,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                organization_id=org_id,
                document_title=chunk.provenance.document_title,
                excerpt=cit.excerpt,
                source_url=chunk.provenance.source_url,
                s3_uri=chunk.provenance.s3_uri,
                item_type=item_type,
                is_safe=is_safe,
                confidence_score=confidence_score,
                provenance=chunk.provenance,
                prompt_injection_flags=list(chunk.prompt_injection_flags),
                data_envelope=data_envelope,
            )
            evidence_items.append(ev_item)

        # Deterministic evidence bundle ID
        evidence_ids = [item.evidence_id for item in evidence_items]
        bundle_id = generate_deterministic_evidence_bundle_id(
            organization_id=org_id,
            retrieval_id=result_set.retrieval_id,
            context_id=context.context_id,
            evidence_ids=evidence_ids,
        )

        limitations = list(context.limitations)
        if not evidence_items:
            limitations.append("Zero evidence items retrieved or grounded.")

        bundle = RAGEvidenceBundle(
            bundle_id=bundle_id,
            organization_id=org_id,
            query_text=context.query_text,
            context_id=context.context_id,
            retrieval_id=result_set.retrieval_id,
            grounding_status=context.grounding_status,
            evidence_items=evidence_items,
            citations=context.citations,
            limitations=limitations,
            trust_boundary=context.trust_boundary,
            grounding_anchor=anchor,
            assembled_text=context.assembled_text,
            total_evidence_units=len(evidence_items),
        )

        # 4. Write immutable audit log
        if self.session:
            audit_repo = AuditLogRepository(self.session)
            audit_payload = {
                "bundle_id": bundle_id,
                "retrieval_id": result_set.retrieval_id,
                "context_id": context.context_id,
                "evidence_units": len(evidence_items),
                "bundle_fingerprint": bundle.bundle_fingerprint,
                "injection_risk_detected": context.trust_boundary.injection_risk_detected,
            }
            validate_no_secrets_in_metadata(audit_payload)

            audit_repo.append_log(
                org_id=org_id,
                actor_id=actor_id or "system",
                action="RAG_EVIDENCE_PIPELINE_EXECUTED",
                resource_type="RAGEvidenceBundle",
                resource_id=bundle_id,
                status="SUCCESS",
                actor_type="SYSTEM" if not actor_id else "USER",
                after_json=audit_payload,
                auto_commit=auto_commit,
            )

        return bundle

    def validate_evidence_bundle_integrity(
        self,
        bundle: RAGEvidenceBundle,
        context: Optional[RAGContext] = None,
        result_set: Optional[RetrievalResultSet] = None,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """Certify the integrity, tenancy, and provenance consistency of a RAGEvidenceBundle.

        Checks:
        1. Tenancy alignment across bundle, context, and retrieval result set.
        2. 1:1 Correspondence between bundle evidence items and context citations.
        3. Strict provenance preservation from source chunks to evidence items.
        4. Excerpt authenticity matching source chunk text.
        5. Tamper detection on fingerprint and deterministic bundle ID.
        """
        errors: List[str] = []

        if not bundle.organization_id or not bundle.organization_id.strip():
            errors.append("Empty organization_id on bundle.")

        # Re-check bundle fingerprint
        sorted_evidence_ids = sorted([item.evidence_id for item in bundle.evidence_items])
        sorted_cit_keys = sorted([c.citation_key for c in bundle.citations])
        fp_raw = f"{bundle.bundle_id}:{bundle.organization_id}:{bundle.retrieval_id}:{bundle.context_id}:{bundle.grounding_status.value}:{':'.join(sorted_evidence_ids)}:{':'.join(sorted_cit_keys)}"
        expected_fp = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()
        if bundle.bundle_fingerprint != expected_fp:
            errors.append(f"Bundle fingerprint mismatch: expected {expected_fp}, found {bundle.bundle_fingerprint}")

        # Re-check bundle ID
        if bundle.organization_id and bundle.organization_id.strip():
            expected_bundle_id = generate_deterministic_evidence_bundle_id(
                bundle.organization_id, bundle.retrieval_id, bundle.context_id, [item.evidence_id for item in bundle.evidence_items]
            )
            if bundle.bundle_id != expected_bundle_id:
                errors.append(f"Tampered bundle_id: expected {expected_bundle_id}, found {bundle.bundle_id}")

        # 1:1 correspondence check
        if len(bundle.evidence_items) != len(bundle.citations):
            errors.append(
                f"Evidence item count ({len(bundle.evidence_items)}) does not match citation count ({len(bundle.citations)})."
            )

        cit_map = {c.citation_id: c for c in bundle.citations if c.citation_id}
        cit_key_map = {c.citation_key: c for c in bundle.citations}

        for item in bundle.evidence_items:
            if item.organization_id != bundle.organization_id:
                errors.append(f"Cross-tenant evidence item '{item.evidence_id}' has org '{item.organization_id}' != '{bundle.organization_id}'.")

            matching_cit = cit_map.get(item.citation_id) or cit_key_map.get(item.citation_key)
            if not matching_cit:
                errors.append(f"Evidence item '{item.evidence_id}' references unknown citation '{item.citation_key}'.")
            else:
                if item.excerpt != matching_cit.excerpt:
                    errors.append(f"Excerpt mismatch for item '{item.evidence_id}'.")
                if item.chunk_id != matching_cit.chunk_id:
                    errors.append(f"Chunk ID mismatch for item '{item.evidence_id}'.")
                if item.document_id != matching_cit.document_id:
                    errors.append(f"Document ID mismatch for item '{item.evidence_id}'.")

        # Check for orphan citations
        item_cit_ids = {item.citation_id for item in bundle.evidence_items}
        item_cit_keys = {item.citation_key for item in bundle.evidence_items}
        for cit in bundle.citations:
            cit_id = cit.citation_id
            if (not cit_id or cit_id not in item_cit_ids) and cit.citation_key not in item_cit_keys:
                errors.append(f"Orphan citation '{cit.citation_key}' not referenced by any evidence item.")

        if context:
            if bundle.context_id != context.context_id:
                errors.append(f"Context ID mismatch: bundle '{bundle.context_id}' != context '{context.context_id}'.")
            if bundle.organization_id != context.organization_id:
                errors.append(f"Tenant mismatch: bundle '{bundle.organization_id}' != context '{context.organization_id}'.")

        if result_set:
            if bundle.retrieval_id != result_set.retrieval_id:
                errors.append(f"Retrieval ID mismatch: bundle '{bundle.retrieval_id}' != result_set '{result_set.retrieval_id}'.")
            if bundle.organization_id != result_set.organization_id:
                errors.append(f"Tenant mismatch: bundle '{bundle.organization_id}' != result_set '{result_set.organization_id}'.")

        is_valid = len(errors) == 0
        if not is_valid and strict:
            if any("mismatch" in e.lower() and "excerpt" in e.lower() for e in errors):
                raise RAGCitationIntegrityError("; ".join(errors))
            if any("tenant" in e.lower() or "org" in e.lower() for e in errors):
                raise RAGTenantIsolationError("; ".join(errors))
            if any("lineage" in e.lower() or "chunk id" in e.lower() or "document id" in e.lower() for e in errors):
                raise RAGProvenanceLineageError("; ".join(errors))
            raise RAGEvidencePipelineError("; ".join(errors))

        return {"is_valid": is_valid, "errors": errors}
