"""Document ingestion and orchestration service for RiskWise RAG subsystem.

Handles validation, parsing, hashing, idempotent deduplication, deterministic chunking,
transactional database persistence, and immutable audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.models.governance import AuditLog
from app.models.knowledge import Document, DocumentChunk
from app.rag.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DeterministicChunker,
)
from app.rag.contracts import (
    DocumentChunkContract,
    DocumentContract,
    DocumentIdentity,
    DocumentMetadata,
    DocumentStatus,
    generate_deterministic_document_id,
    validate_no_secrets_in_metadata,
)
from app.rag.errors import (
    RAGEmptyDocumentError,
    RAGMalformedInputError,
    RAGSecurityPolicyViolationError,
    RAGTenantIsolationError,
)
from app.rag.parsers import (
    extract_text_from_payload,
    validate_filename_safety,
)
from app.repositories.audit_log import AuditLogRepository


class DocumentIngestionPayload(BaseModel):
    """Input payload for ingesting an enterprise document into the RAG knowledge base."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    content: Union[str, bytes]
    organization_id: str = Field(..., min_length=1, max_length=64)
    file_type: Optional[str] = Field(None, max_length=50)
    filename: Optional[str] = Field(None, max_length=255)
    s3_uri: Optional[str] = Field(None, max_length=500)
    source_url: Optional[str] = Field(None, max_length=500)
    classification: Optional[str] = Field("INTERNAL", max_length=50)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=50, le=4000)
    chunk_overlap: int = Field(default=DEFAULT_CHUNK_OVERLAP, ge=0, le=500)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be a non-empty string.")
        return v.strip()

    @field_validator("title")
    @classmethod
    def validate_title_safety(cls, v: str) -> str:
        clean_title = v.strip()
        if not clean_title:
            raise RAGMalformedInputError("Document title cannot be blank.")
        validate_filename_safety(clean_title)
        return clean_title

    @field_validator("metadata")
    @classmethod
    def validate_meta_secrets(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_secrets_in_metadata(v)
        return v


class DocumentIngestionResult(BaseModel):
    """Result of document ingestion containing authoritative contracts, chunk count, and idempotency status."""
    model_config = ConfigDict(extra="forbid")

    document: DocumentContract
    chunks: List[DocumentChunkContract]
    chunk_count: int = Field(..., ge=0)
    is_idempotent_duplicate: bool
    idempotency_status: str  # "CREATED" or "IDEMPOTENT_HIT"
    audit_log_id: Optional[str] = None


class DocumentIngestionService:
    """Service orchestrating document validation, parsing, chunking, and persistence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def ingest_document(
        self,
        payload: DocumentIngestionPayload,
        current_user_org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        auto_commit: bool = True,
    ) -> DocumentIngestionResult:
        """Ingest a document into the tenant's knowledge base.

        Enforces server-side tenant isolation, content parsing, idempotent deduplication,
        deterministic chunking, atomic database insertion, and immutable audit logging.
        """
        org_id = payload.organization_id.strip()

        # Enforce server-side tenant validation
        if current_user_org_id and current_user_org_id.strip() != org_id:
            raise RAGTenantIsolationError(
                f"User tenant '{current_user_org_id}' cannot ingest documents into tenant '{org_id}'."
            )

        # Parse and sanitize raw payload
        extracted = extract_text_from_payload(
            raw_payload=payload.content,
            file_type=payload.file_type,
            filename=payload.filename,
        )

        # Generate deterministic document identity
        doc_id = generate_deterministic_document_id(
            organization_id=org_id,
            title=payload.title,
            content_hash=extracted.content_hash,
        )

        # Check for existing document (idempotency check)
        existing_doc = self.session.query(Document).filter(
            Document.id == doc_id,
            Document.org_id == org_id,
        ).first()

        if existing_doc:
            # Idempotent hit: return existing document and its chunks without re-inserting
            existing_chunks = self.session.query(DocumentChunk).filter(
                DocumentChunk.document_id == doc_id
            ).order_by(DocumentChunk.chunk_index.asc()).all()

            doc_contract = DocumentContract.from_orm_model(existing_doc)
            chunk_contracts = [
                DocumentChunkContract.from_orm_model(c, organization_id=org_id)
                for c in existing_chunks
            ]

            return DocumentIngestionResult(
                document=doc_contract,
                chunks=chunk_contracts,
                chunk_count=len(chunk_contracts),
                is_idempotent_duplicate=True,
                idempotency_status="IDEMPOTENT_HIT",
                audit_log_id=None,
            )

        # Deterministically chunk document
        chunker = DeterministicChunker(
            chunk_size=payload.chunk_size,
            chunk_overlap=payload.chunk_overlap,
        )
        chunk_contracts = chunker.chunk_document(
            document_id=doc_id,
            organization_id=org_id,
            text=extracted.content,
        )

        # Assemble DocumentMetadata
        metadata_dict = {
            "source_uri": payload.s3_uri or payload.source_url,
            "content_hash": extracted.content_hash,
            "author_or_source": payload.metadata.get("author_or_source", "INGESTION_SERVICE"),
            "classification": payload.classification or "INTERNAL",
            "tags": payload.tags,
            **{k: v for k, v in payload.metadata.items() if k != "author_or_source"},
            **extracted.detected_metadata,
        }
        validate_no_secrets_in_metadata(metadata_dict)

        doc_meta = DocumentMetadata(
            source_uri=metadata_dict.get("source_uri"),
            content_hash=extracted.content_hash,
            author_or_source=metadata_dict.get("author_or_source"),
            classification=metadata_dict.get("classification", "INTERNAL"),
            tags=payload.tags,
            extra_attributes={
                k: v for k, v in metadata_dict.items()
                if k not in ("source_uri", "content_hash", "author_or_source", "classification", "tags")
            },
        )

        doc_identity = DocumentIdentity(
            document_id=doc_id,
            organization_id=org_id,
            title=payload.title,
            file_type=extracted.file_type,
            s3_uri=payload.s3_uri,
            source_url=payload.source_url,
            created_at=datetime.now(timezone.utc),
        )

        doc_contract = DocumentContract(
            identity=doc_identity,
            status=DocumentStatus.INDEXED,
            metadata=doc_meta,
            chunk_count=len(chunk_contracts),
        )

        # Persist Document entity
        orm_doc_kwargs = doc_contract.to_orm_kwargs()
        orm_document = Document(**orm_doc_kwargs)
        self.session.add(orm_document)

        # Persist DocumentChunk entities
        for chunk in chunk_contracts:
            chunk_kwargs = chunk.to_orm_kwargs()
            orm_chunk = DocumentChunk(**chunk_kwargs)
            self.session.add(orm_chunk)

        # Audit log creation
        audit_repo = AuditLogRepository(self.session)
        audit_log = audit_repo.append_log(
            org_id=org_id,
            actor_id=actor_id or "system",
            action="DOCUMENT_INGESTED",
            resource_type="Document",
            resource_id=doc_id,
            status="SUCCESS",
            actor_type="SYSTEM" if not actor_id else "USER",
            after_json={
                "document_id": doc_id,
                "title": payload.title,
                "file_type": extracted.file_type,
                "chunk_count": len(chunk_contracts),
                "content_hash": extracted.content_hash,
            },
            auto_commit=False,
        )

        if auto_commit:
            self.session.commit()
            self.session.refresh(orm_document)

        return DocumentIngestionResult(
            document=doc_contract,
            chunks=chunk_contracts,
            chunk_count=len(chunk_contracts),
            is_idempotent_duplicate=False,
            idempotency_status="CREATED",
            audit_log_id=audit_log.id if audit_log else None,
        )
