"""Vector storage service and chunk embedding orchestration for RiskWise RAG subsystem.

Handles transactional vector persistence, batch embedding generation, idempotent deduplication,
strict tenant boundary enforcement, and immutable audit logging within the existing PostgreSQL
34-table schema (table `document_chunks.embedding_json`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models.governance import AuditLog
from app.models.knowledge import Document, DocumentChunk
from app.rag.contracts import (
    EmbeddingMetadata,
    EmbeddingProvider,
    EmbeddingVector,
    validate_no_secrets_in_metadata,
)
from app.rag.embeddings import (
    TARGET_EMBEDDING_DIMENSION,
    BaseEmbeddingProvider,
    LocalMockEmbeddingProvider,
    compute_embedding_fingerprint,
    get_embedding_provider,
)
from app.rag.errors import (
    RAGChunkNotFoundError,
    RAGDocumentNotFoundError,
    RAGEmbeddingDimensionError,
    RAGEmbeddingError,
    RAGMalformedInputError,
    RAGTenantIsolationError,
)
from app.repositories.audit_log import AuditLogRepository


def extract_embedding_vector(chunk: DocumentChunk) -> Optional[EmbeddingVector]:
    """Safely extract strongly typed EmbeddingVector from a DocumentChunk model instance."""
    emb_json = getattr(chunk, "embedding_json", None)
    if not emb_json:
        return None

    if isinstance(emb_json, list):
        return EmbeddingVector(
            values=emb_json,
            dimension=len(emb_json),
            is_normalized=False,
        )
    elif isinstance(emb_json, dict) and "values" in emb_json:
        return EmbeddingVector(
            values=emb_json["values"],
            dimension=emb_json.get("dimension", len(emb_json["values"])),
            is_normalized=emb_json.get("is_normalized", False),
        )
    return None


def extract_embedding_metadata(chunk: DocumentChunk) -> Optional[EmbeddingMetadata]:
    """Safely extract EmbeddingMetadata from a DocumentChunk model instance."""
    emb_json = getattr(chunk, "embedding_json", None)
    if not emb_json or not isinstance(emb_json, dict):
        return None

    model_name = emb_json.get("model_name")
    if not model_name:
        return None

    provider_str = emb_json.get("provider", "LOCAL_MOCK")
    try:
        provider = EmbeddingProvider(provider_str)
    except ValueError:
        provider = EmbeddingProvider.LOCAL_MOCK

    return EmbeddingMetadata(
        model_name=str(model_name),
        provider=provider,
        dimension=int(emb_json.get("dimension", TARGET_EMBEDDING_DIMENSION)),
    )


class ChunkEmbeddingResult(BaseModel):
    """Result of embedding one or more document chunks with provenance and idempotency telemetry."""
    model_config = ConfigDict(extra="forbid")

    document_id: str
    organization_id: str
    chunks_embedded: int = Field(..., ge=0)
    total_chunks: int = Field(..., ge=0)
    dimension: int = Field(default=TARGET_EMBEDDING_DIMENSION, gt=0)
    provider: str
    model_name: str
    is_idempotent_duplicate: bool
    idempotency_status: str  # "EMBEDDED" or "IDEMPOTENT_HIT"
    audit_log_id: Optional[str] = None
    embedded_chunk_ids: List[str] = Field(default_factory=list)


class ChunkEmbeddingService:
    """Service orchestrating batch embedding generation and vector storage for document chunks."""

    def __init__(
        self,
        session: Session,
        provider: Optional[BaseEmbeddingProvider] = None,
    ) -> None:
        self.session = session
        self.provider = provider or LocalMockEmbeddingProvider()

    def embed_document_chunks(
        self,
        document_id: str,
        organization_id: str,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        batch_size: int = 16,
        force_reembed: bool = False,
        auto_commit: bool = True,
    ) -> ChunkEmbeddingResult:
        """Embed all chunks of a document in batches and transactionally update `document_chunks.embedding_json`.

        Guarantees:
        1. Tenant boundary enforcement: Cross-tenant operations are rejected with RAGTenantIsolationError.
        2. Idempotency: Unchanged chunks with identical fingerprints are reused without redundant provider calls.
        3. Strict 1536 dimension: Returned vectors must match exactly or trigger RAGEmbeddingDimensionError.
        4. Atomic rollback: Any provider failure or dimension mismatch rolls back changes completely.
        5. Zero orphan vectors: Embeddings are stored directly on the chunk linked to the parent document.
        6. Immutable audit trail: Emits an append-only AuditLog entry for compliance.
        """
        if not organization_id or not isinstance(organization_id, str) or not organization_id.strip():
            raise RAGTenantIsolationError("organization_id must be a non-empty string.")
        org_id = organization_id.strip()

        if not document_id or not isinstance(document_id, str) or not document_id.strip():
            raise RAGMalformedInputError("document_id must be a non-empty string.")
        doc_id = document_id.strip()

        # Enforce server-side tenant isolation
        if current_user_org_id and current_user_org_id.strip() != org_id:
            raise RAGTenantIsolationError(
                f"User tenant '{current_user_org_id}' cannot embed chunks belonging to tenant '{org_id}'."
            )

        if batch_size <= 0:
            raise RAGMalformedInputError("batch_size must be a positive integer.")

        # Verify document exists and belongs to the specified organization
        document = self.session.query(Document).filter(
            Document.id == doc_id,
            Document.org_id == org_id,
        ).first()

        if not document:
            # Check if document exists under another organization (cross-tenant attempt)
            other_doc = self.session.query(Document).filter(Document.id == doc_id).first()
            if other_doc and other_doc.org_id != org_id:
                raise RAGTenantIsolationError(
                    f"Cross-tenant access violation: document '{doc_id}' belongs to organization '{other_doc.org_id}'."
                )
            raise RAGDocumentNotFoundError(f"Document '{doc_id}' not found in organization '{org_id}'.")

        # Query all chunks belonging to this document ordered deterministically
        chunks: List[DocumentChunk] = (
            self.session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )

        if not chunks:
            raise RAGChunkNotFoundError(f"No chunks found for document '{doc_id}'.")

        expected_dimension = self.provider.dimension
        provider_name = self.provider.provider.value
        model_name = self.provider.default_model

        # Determine which chunks require embedding
        chunks_to_embed: List[DocumentChunk] = []
        for chunk in chunks:
            if force_reembed:
                chunks_to_embed.append(chunk)
                continue

            expected_fp = compute_embedding_fingerprint(
                chunk.content,
                model_name=model_name,
                dimension=expected_dimension,
            )

            emb_json = chunk.embedding_json
            if (
                isinstance(emb_json, dict)
                and emb_json.get("fingerprint") == expected_fp
                and emb_json.get("dimension") == expected_dimension
                and isinstance(emb_json.get("values"), list)
                and len(emb_json["values"]) == expected_dimension
            ):
                # Chunk already has a valid, identical embedding
                continue

            chunks_to_embed.append(chunk)

        # Idempotency check: If no chunks require re-embedding, return IDEMPOTENT_HIT immediately
        if not chunks_to_embed:
            return ChunkEmbeddingResult(
                document_id=doc_id,
                organization_id=org_id,
                chunks_embedded=0,
                total_chunks=len(chunks),
                dimension=expected_dimension,
                provider=provider_name,
                model_name=model_name,
                is_idempotent_duplicate=True,
                idempotency_status="IDEMPOTENT_HIT",
                audit_log_id=None,
                embedded_chunk_ids=[c.id for c in chunks],
            )

        # Process batches deterministically
        try:
            for i in range(0, len(chunks_to_embed), batch_size):
                batch = chunks_to_embed[i : i + batch_size]
                texts = [c.content for c in batch]

                # Invoke provider abstraction
                vectors = self.provider.embed_batch(texts, model=model_name)

                if len(vectors) != len(batch):
                    raise RAGEmbeddingError(
                        f"Provider returned {len(vectors)} vectors for {len(batch)} chunks in batch."
                    )

                for chunk, vec in zip(batch, vectors):
                    if vec.dimension != expected_dimension:
                        raise RAGEmbeddingDimensionError(
                            f"Returned vector dimension {vec.dimension} does not match expected {expected_dimension}."
                        )

                    fp = compute_embedding_fingerprint(
                        chunk.content,
                        model_name=model_name,
                        dimension=expected_dimension,
                    )

                    # Persist vector and safe metadata into embedding_json
                    payload = {
                        "values": vec.values,
                        "dimension": vec.dimension,
                        "is_normalized": vec.is_normalized,
                        "model_name": model_name,
                        "provider": provider_name,
                        "fingerprint": fp,
                        "embedded_at": datetime.now(timezone.utc).isoformat(),
                    }
                    validate_no_secrets_in_metadata(payload)
                    chunk.embedding_json = payload

        except Exception:
            if auto_commit:
                self.session.rollback()
            raise

        # Append immutable audit log
        audit_repo = AuditLogRepository(self.session)
        audit_log = audit_repo.append_log(
            org_id=org_id,
            actor_id=actor_id or "system",
            action="CHUNKS_EMBEDDED",
            resource_type="Document",
            resource_id=doc_id,
            status="SUCCESS",
            actor_type="SYSTEM" if not actor_id else "USER",
            after_json={
                "document_id": doc_id,
                "chunks_embedded": len(chunks_to_embed),
                "total_chunks": len(chunks),
                "dimension": expected_dimension,
                "provider": provider_name,
                "model_name": model_name,
            },
            auto_commit=False,
        )

        if auto_commit:
            self.session.commit()

        return ChunkEmbeddingResult(
            document_id=doc_id,
            organization_id=org_id,
            chunks_embedded=len(chunks_to_embed),
            total_chunks=len(chunks),
            dimension=expected_dimension,
            provider=provider_name,
            model_name=model_name,
            is_idempotent_duplicate=False,
            idempotency_status="EMBEDDED",
            audit_log_id=audit_log.id if audit_log else None,
            embedded_chunk_ids=[c.id for c in chunks_to_embed],
        )

    def embed_chunk_ids(
        self,
        chunk_ids: List[str],
        organization_id: str,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        batch_size: int = 16,
        force_reembed: bool = False,
        auto_commit: bool = True,
    ) -> ChunkEmbeddingResult:
        """Embed specific document chunk IDs while strictly verifying tenant ownership."""
        if not organization_id or not isinstance(organization_id, str) or not organization_id.strip():
            raise RAGTenantIsolationError("organization_id must be a non-empty string.")
        org_id = organization_id.strip()

        if current_user_org_id and current_user_org_id.strip() != org_id:
            raise RAGTenantIsolationError(
                f"User tenant '{current_user_org_id}' cannot embed chunks belonging to tenant '{org_id}'."
            )

        if not chunk_ids:
            raise RAGMalformedInputError("chunk_ids list cannot be empty.")

        # Query chunks with their parent documents to verify tenancy
        chunks: List[DocumentChunk] = (
            self.session.query(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(
                DocumentChunk.id.in_(chunk_ids),
                Document.org_id == org_id,
            )
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )

        if len(chunks) != len(chunk_ids):
            # Check if any chunk belongs to a different organization
            other_chunks = (
                self.session.query(DocumentChunk)
                .join(Document, DocumentChunk.document_id == Document.id)
                .filter(DocumentChunk.id.in_(chunk_ids))
                .all()
            )
            for oc in other_chunks:
                if oc.document.org_id != org_id:
                    raise RAGTenantIsolationError(
                        f"Cross-tenant access violation: chunk '{oc.id}' belongs to organization '{oc.document.org_id}'."
                    )
            raise RAGChunkNotFoundError("One or more requested chunks were not found.")

        expected_dimension = self.provider.dimension
        provider_name = self.provider.provider.value
        model_name = self.provider.default_model

        chunks_to_embed: List[DocumentChunk] = []
        for chunk in chunks:
            if force_reembed:
                chunks_to_embed.append(chunk)
                continue

            expected_fp = compute_embedding_fingerprint(
                chunk.content,
                model_name=model_name,
                dimension=expected_dimension,
            )
            emb_json = chunk.embedding_json
            if (
                isinstance(emb_json, dict)
                and emb_json.get("fingerprint") == expected_fp
                and emb_json.get("dimension") == expected_dimension
                and isinstance(emb_json.get("values"), list)
                and len(emb_json["values"]) == expected_dimension
            ):
                continue
            chunks_to_embed.append(chunk)

        doc_id = chunks[0].document_id

        if not chunks_to_embed:
            return ChunkEmbeddingResult(
                document_id=doc_id,
                organization_id=org_id,
                chunks_embedded=0,
                total_chunks=len(chunks),
                dimension=expected_dimension,
                provider=provider_name,
                model_name=model_name,
                is_idempotent_duplicate=True,
                idempotency_status="IDEMPOTENT_HIT",
                audit_log_id=None,
                embedded_chunk_ids=[c.id for c in chunks],
            )

        try:
            for i in range(0, len(chunks_to_embed), batch_size):
                batch = chunks_to_embed[i : i + batch_size]
                texts = [c.content for c in batch]
                vectors = self.provider.embed_batch(texts, model=model_name)

                if len(vectors) != len(batch):
                    raise RAGEmbeddingError("Provider returned mismatched vector count.")

                for chunk, vec in zip(batch, vectors):
                    if vec.dimension != expected_dimension:
                        raise RAGEmbeddingDimensionError("Vector dimension mismatch.")

                    fp = compute_embedding_fingerprint(
                        chunk.content,
                        model_name=model_name,
                        dimension=expected_dimension,
                    )
                    chunk.embedding_json = {
                        "values": vec.values,
                        "dimension": vec.dimension,
                        "is_normalized": vec.is_normalized,
                        "model_name": model_name,
                        "provider": provider_name,
                        "fingerprint": fp,
                        "embedded_at": datetime.now(timezone.utc).isoformat(),
                    }

        except Exception:
            if auto_commit:
                self.session.rollback()
            raise

        audit_repo = AuditLogRepository(self.session)
        audit_log = audit_repo.append_log(
            org_id=org_id,
            actor_id=actor_id or "system",
            action="CHUNKS_EMBEDDED",
            resource_type="DocumentChunk",
            resource_id=doc_id,
            status="SUCCESS",
            actor_type="SYSTEM" if not actor_id else "USER",
            after_json={
                "document_id": doc_id,
                "chunks_embedded": len(chunks_to_embed),
                "total_chunks": len(chunks),
                "dimension": expected_dimension,
                "provider": provider_name,
                "model_name": model_name,
            },
            auto_commit=False,
        )

        if auto_commit:
            self.session.commit()

        return ChunkEmbeddingResult(
            document_id=doc_id,
            organization_id=org_id,
            chunks_embedded=len(chunks_to_embed),
            total_chunks=len(chunks),
            dimension=expected_dimension,
            provider=provider_name,
            model_name=model_name,
            is_idempotent_duplicate=False,
            idempotency_status="EMBEDDED",
            audit_log_id=audit_log.id if audit_log else None,
            embedded_chunk_ids=[c.id for c in chunks_to_embed],
        )
