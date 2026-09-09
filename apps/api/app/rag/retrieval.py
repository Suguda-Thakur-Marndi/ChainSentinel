"""RAG Retrieval & Similarity Search service for RiskWise 2.0 subsystem.

Handles semantic query embedding, tenant-scoped candidate querying, distance/similarity computation,
threshold filtering, deterministic ranking, unbroken provenance preservation, prompt-injection
tagging, and contextual assembly within the existing PostgreSQL 34-table schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.governance import AuditLog
from app.models.knowledge import Document, DocumentChunk
from app.rag.contracts import (
    DistanceMetric,
    EmbeddingVector,
    RAGContext,
    RetrievalFilter,
    RetrievalProvenance,
    RetrievalQuery,
    RetrievalResultSet,
    RetrievedChunk,
    detect_prompt_injection_indicators,
    validate_no_secrets_in_metadata,
)
from app.rag.embeddings import (
    TARGET_EMBEDDING_DIMENSION,
    BaseEmbeddingProvider,
    LocalMockEmbeddingProvider,
)
from app.rag.errors import (
    RAGEmbeddingDimensionError,
    RAGInvalidQueryError,
    RAGTenantIsolationError,
)
from app.rag.vector_store import extract_embedding_vector
from app.repositories.audit_log import AuditLogRepository


class RAGRetrievalService:
    """Service orchestrating semantic retrieval, deterministic ranking, tenant isolation, and provenance tracking."""

    def __init__(
        self,
        session: Session,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider or LocalMockEmbeddingProvider()

    def retrieve(
        self,
        query: RetrievalQuery,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> RetrievalResultSet:
        """Execute a tenant-isolated semantic retrieval query against stored chunk embeddings.

        Guarantees:
        1. Strict server-side tenant isolation: cross-tenant access is rejected with RAGTenantIsolationError.
        2. Query embedding dimension strictly verified against target dimension (1536).
        3. Deterministic ranking: ties are stably broken by (chunk_index ASC, chunk_id ASC).
        4. Bounded retrieval: respects top_k (1..100) and similarity_threshold (0.0..1.0).
        5. Unbroken provenance: every retrieved chunk preserves complete lineage to source Document.
        6. Untrusted data boundary: all retrieved content is flagged with is_untrusted_data=True.
        7. Audit logging: emits append-only AuditLog record (action: RAG_RETRIEVAL).
        """
        start_time = time.perf_counter()

        # 1. Enforce server-side tenant isolation
        org_id = query.organization_id.strip() if query.organization_id else ""
        if not org_id:
            raise RAGTenantIsolationError("organization_id is strictly mandatory for retrieval.")

        if current_user_org_id and current_user_org_id.strip() != org_id:
            raise RAGTenantIsolationError(
                f"User tenant '{current_user_org_id}' cannot execute retrieval for tenant '{org_id}'."
            )

        # 2. Resolve query embedding vector
        expected_dimension = self.embedding_provider.dimension
        query_vector: EmbeddingVector

        if query.query_embedding is not None:
            if query.query_embedding.dimension != expected_dimension:
                raise RAGEmbeddingDimensionError(
                    f"Provided query_embedding dimension ({query.query_embedding.dimension}) does not match provider dimension ({expected_dimension})."
                )
            query_vector = query.query_embedding
        else:
            clean_text = query.query_text.strip()
            if not clean_text:
                raise RAGInvalidQueryError("query_text cannot be blank or whitespace.")
            query_vector = self.embedding_provider.embed_text(clean_text)
            if query_vector.dimension != expected_dimension:
                raise RAGEmbeddingDimensionError(
                    f"Provider returned vector of dimension {query_vector.dimension}, expected {expected_dimension}."
                )

        # 3. Query tenant-scoped candidate chunks from database
        db_query = (
            self.session.query(DocumentChunk, Document)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(
                Document.org_id == org_id,
                DocumentChunk.embedding_json.is_not(None),
            )
        )

        # Apply structural filters at database query level where possible
        if query.filter:
            if query.filter.document_ids:
                db_query = db_query.filter(Document.id.in_(query.filter.document_ids))
            if query.filter.file_types:
                clean_ft = [ft.lower().strip() for ft in query.filter.file_types if ft and ft.strip()]
                if clean_ft:
                    db_query = db_query.filter(func.lower(Document.file_type).in_(clean_ft))

        candidates: List[Tuple[DocumentChunk, Document]] = db_query.all()

        # 4. Evaluate metadata-level filters & compute similarity scores
        scored_candidates: List[Tuple[float, DocumentChunk, Document]] = []

        for chunk, doc in candidates:
            # Metadata filter: tags
            if query.filter and query.filter.tags:
                doc_tags: List[str] = []
                if doc.metadata_json and isinstance(doc.metadata_json, dict):
                    raw_tags = doc.metadata_json.get("tags", [])
                    if isinstance(raw_tags, list):
                        doc_tags = [str(t).lower().strip() for t in raw_tags]
                filter_tags = [t.lower().strip() for t in query.filter.tags]
                if not any(t in doc_tags for t in filter_tags):
                    continue

            # Metadata filter: scope_entity_type & scope_entity_id
            if query.filter and (query.filter.scope_entity_type or query.filter.scope_entity_id):
                doc_meta = doc.metadata_json if isinstance(doc.metadata_json, dict) else {}
                if query.filter.scope_entity_type:
                    if doc_meta.get("scope_entity_type") != query.filter.scope_entity_type:
                        continue
                if query.filter.scope_entity_id:
                    if doc_meta.get("scope_entity_id") != query.filter.scope_entity_id:
                        continue

            # Extract stored embedding vector
            chunk_vec = extract_embedding_vector(chunk)
            if not chunk_vec or chunk_vec.dimension != expected_dimension:
                continue

            # Compute similarity score bounded in [0.0, 1.0]
            if query.distance_metric == DistanceMetric.COSINE:
                raw_score = query_vector.cosine_similarity(chunk_vec)
                score = max(0.0, min(1.0, raw_score))
            elif query.distance_metric == DistanceMetric.DOT_PRODUCT:
                raw_score = query_vector.dot_product(chunk_vec)
                score = max(0.0, min(1.0, raw_score))
            elif query.distance_metric == DistanceMetric.EUCLIDEAN:
                dist = query_vector.l2_distance(chunk_vec)
                score = max(0.0, min(1.0, 1.0 / (1.0 + dist)))
            else:
                raw_score = query_vector.cosine_similarity(chunk_vec)
                score = max(0.0, min(1.0, raw_score))

            # Filter candidates below similarity threshold
            if score < query.similarity_threshold:
                continue

            scored_candidates.append((score, chunk, doc))

        # 5. Deterministic sorting: (-score, chunk_index ASC, chunk_id ASC)
        scored_candidates.sort(
            key=lambda item: (-item[0], item[1].chunk_index, item[1].id)
        )

        # Slice top_k
        top_candidates = scored_candidates[: query.top_k]

        # 6. Assemble RetrievedChunk instances with complete provenance
        retrieved_chunks: List[RetrievedChunk] = []
        for rank, (score, chunk, doc) in enumerate(top_candidates, start=1):
            injection_flags = detect_prompt_injection_indicators(chunk.content)

            prov = RetrievalProvenance(
                document_id=doc.id,
                chunk_id=chunk.id,
                organization_id=org_id,
                chunk_index=chunk.chunk_index,
                document_title=doc.title,
                file_type=doc.file_type,
                s3_uri=doc.s3_uri,
                source_url=doc.source_url,
                retrieval_id=query.query_id,
                similarity_score=round(score, 4),
                rank=rank,
                retrieved_at=datetime.now(timezone.utc),
            )

            ret_chunk = RetrievedChunk(
                chunk_id=chunk.id,
                document_id=doc.id,
                organization_id=org_id,
                content=chunk.content,
                score=round(score, 4),
                rank=rank,
                token_count=chunk.token_count,
                provenance=prov,
                is_untrusted_data=True,
                prompt_injection_flags=injection_flags,
            )
            retrieved_chunks.append(ret_chunk)

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # 7. Construct result set (validates tenant isolation and deterministic ordering)
        result_set = RetrievalResultSet(
            retrieval_id=query.query_id,
            organization_id=org_id,
            query_text=query.query_text,
            chunks=retrieved_chunks,
            total_retrieved=len(retrieved_chunks),
            latency_ms=elapsed_ms,
            retrieved_at=datetime.now(timezone.utc),
        )

        # 8. Record safe operational telemetry into audit logs
        audit_repo = AuditLogRepository(self.session)
        audit_payload = {
            "query_id": query.query_id,
            "top_k": query.top_k,
            "similarity_threshold": query.similarity_threshold,
            "distance_metric": query.distance_metric.value,
            "total_retrieved": len(retrieved_chunks),
            "latency_ms": elapsed_ms,
            "provider": self.embedding_provider.provider.value,
            "model_name": self.embedding_provider.default_model,
        }
        validate_no_secrets_in_metadata(audit_payload)

        audit_repo.append_log(
            org_id=org_id,
            actor_id=actor_id or "system",
            action="RAG_RETRIEVAL",
            resource_type="RetrievalQuery",
            resource_id=query.query_id,
            status="SUCCESS",
            actor_type="SYSTEM" if not actor_id else "USER",
            after_json=audit_payload,
            auto_commit=True,
        )

        return result_set

    def retrieve_context(
        self,
        query: RetrievalQuery,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        grounding_signal_id: Optional[str] = None,
        grounding_assessment_id: Optional[str] = None,
    ) -> RAGContext:
        """Execute semantic retrieval and assemble a safe, XML-demarcated RAGContext for downstream agents."""
        result_set = self.retrieve(
            query=query,
            current_user_org_id=current_user_org_id,
            actor_id=actor_id,
        )
        return RAGContext.assemble(
            organization_id=query.organization_id,
            query=query,
            result_set=result_set,
            grounding_signal_id=grounding_signal_id,
            grounding_assessment_id=grounding_assessment_id,
        )
