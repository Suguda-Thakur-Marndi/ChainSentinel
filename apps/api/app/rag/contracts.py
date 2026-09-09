"""Core strongly typed application contracts for RiskWise RAG subsystem.

Defines domain contracts for Documents, Chunks, Embeddings, Retrieval,
Provenance Lineage, RAG Context, and Data Trust Boundaries with strict
tenant isolation, unbroken provenance, deterministic identities, and
zero-hallucination guarantees.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.rag.errors import (
    RAGEmbeddingDimensionError,
    RAGInvalidQueryError,
    RAGMalformedInputError,
    RAGProvenanceLineageError,
    RAGSecurityPolicyViolationError,
    RAGTenantIsolationError,
)

# Namespace for deterministic UUIDv5 generation
RAG_UUID_NAMESPACE = uuid.NAMESPACE_DNS

# Security: prohibited keys in metadata that might leak credentials
PROHIBITED_METADATA_KEYS = {
    "api_key",
    "secret",
    "password",
    "token",
    "authorization",
    "bearer",
    "private_key",
    "client_secret",
}

# Heuristic prompt-injection adversarial indicators
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+(rules|prompts|instructions)", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?\w*\s*policy", re.IGNORECASE),
    re.compile(r"system\s+(prompt|message)\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?unrestricted", re.IGNORECASE),
    re.compile(r"override\s+instructions", re.IGNORECASE),
    re.compile(r"call\s+(the\s+)?([a-z0-9_]+\s+)?([a-z0-9_]+_)?tool", re.IGNORECASE),
    re.compile(r"<script[\s>]", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"exec\s*\(", re.IGNORECASE),
]


# ==============================================================================
# DETERMINISTIC IDENTIFIER & ENVELOPE GENERATORS
# ==============================================================================

def generate_deterministic_document_id(
    organization_id: str,
    title: str,
    content_hash: str,
) -> str:
    """Generate a reproducible UUIDv5 document identifier based on tenant, title, and content hash."""
    if not organization_id or not organization_id.strip():
        raise RAGTenantIsolationError("organization_id must be non-empty to generate document_id")
    token = f"{organization_id.strip()}:document:{title.strip().lower()}:{content_hash.strip()}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def generate_deterministic_chunk_id(
    organization_id: str,
    document_id: str,
    chunk_index: int,
) -> str:
    """Generate a reproducible UUIDv5 chunk identifier based on tenant, document, and chunk index."""
    if not organization_id or not organization_id.strip():
        raise RAGTenantIsolationError("organization_id must be non-empty to generate chunk_id")
    token = f"{organization_id.strip()}:chunk:{document_id.strip()}:{chunk_index}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def generate_deterministic_retrieval_id(
    organization_id: str,
    query_text: str,
    hour_bucket: str,
) -> str:
    """Generate a reproducible UUIDv5 retrieval identifier based on tenant, query, and temporal bucket."""
    if not organization_id or not organization_id.strip():
        raise RAGTenantIsolationError("organization_id must be non-empty to generate retrieval_id")
    token = f"{organization_id.strip()}:retrieval:{query_text.strip().lower()}:{hour_bucket}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def generate_deterministic_context_id(
    organization_id: str,
    retrieval_id: str,
    chunk_ids: List[str],
) -> str:
    """Generate a reproducible UUIDv5 RAG context identifier based on tenant, retrieval, and sorted chunks."""
    if not organization_id or not organization_id.strip():
        raise RAGTenantIsolationError("organization_id must be non-empty to generate context_id")
    sorted_chunks_key = ",".join(sorted(chunk_ids)) if chunk_ids else "empty"
    token = f"{organization_id.strip()}:rag_context:{retrieval_id.strip()}:{sorted_chunks_key}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def generate_deterministic_citation_id(
    organization_id: str,
    document_id: str,
    chunk_id: str,
    retrieval_id: str,
) -> str:
    """Generate a reproducible UUIDv5 citation identifier based on tenant, document, chunk, and retrieval."""
    if not organization_id or not organization_id.strip():
        raise RAGTenantIsolationError("organization_id must be non-empty to generate citation_id")
    token = f"{organization_id.strip()}:citation:{document_id.strip()}:{chunk_id.strip()}:{retrieval_id.strip()}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def format_rag_data_envelope(content: str, chunk_ref: str) -> str:
    """Encapsulate retrieved text in a safe XML demarcation envelope.

    Ensures downstream models treat the text strictly as passive UNTRUSTED_DATA,
    never as executable system prompts or user instructions.
    """
    safe_content = content.replace("]]>", "]]&gt;")
    return (
        f'<retrieved_context chunk_ref="{chunk_ref}" trust="UNTRUSTED_PASSIVE_DATA">\n'
        f"<![CDATA[\n{safe_content}\n]]>\n"
        f"</retrieved_context>"
    )


def detect_prompt_injection_indicators(text: str) -> List[str]:
    """Inspect text for heuristic prompt-injection or adversarial instruction patterns."""
    detected = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            detected.append(match.group(0))
    return detected


def validate_no_secrets_in_metadata(metadata: Optional[Dict[str, Any]]) -> None:
    """Validate that metadata does not leak credentials or sensitive tokens."""
    if not metadata:
        return
    for key in metadata.keys():
        key_lower = str(key).lower()
        for prohibited in PROHIBITED_METADATA_KEYS:
            if prohibited in key_lower:
                raise RAGSecurityPolicyViolationError(
                    f"Prohibited sensitive key detected in metadata: '{key}'"
                )


# ==============================================================================
# ENUMS
# ==============================================================================

class DocumentStatus(str, Enum):
    """Lifecycle status of an ingested knowledge base document."""
    PENDING = "PENDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class EmbeddingProvider(str, Enum):
    """Supported embedding model provider backends."""
    OPENAI = "OPENAI"
    BEDROCK = "BEDROCK"
    COHERE = "COHERE"
    LOCAL_MOCK = "LOCAL_MOCK"


class DistanceMetric(str, Enum):
    """Vector distance metrics for semantic similarity."""
    COSINE = "COSINE"
    DOT_PRODUCT = "DOT_PRODUCT"
    EUCLIDEAN = "EUCLIDEAN"


class GroundingStatus(str, Enum):
    """Authoritative deterministic grounding classification for a RAG context."""
    GROUNDED = "GROUNDED"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    UNGROUNDED = "UNGROUNDED"
    UNSAFE_SOURCE = "UNSAFE_SOURCE"


class GroundedItemType(str, Enum):
    """Categorical classification of information elements within grounded context."""
    RETRIEVED_FACT = "RETRIEVED_FACT"
    SOURCE_METADATA = "SOURCE_METADATA"
    CITATION = "CITATION"
    LIMITATION = "LIMITATION"
    UNSAFE_CONTENT = "UNSAFE_CONTENT"


# ==============================================================================
# DOCUMENT CONTRACTS
# ==============================================================================

class DocumentMetadata(BaseModel):
    """Validated structured metadata attached to an ingested document."""
    model_config = ConfigDict(extra="forbid")

    source_uri: Optional[str] = Field(None, max_length=500)
    content_hash: Optional[str] = Field(None, max_length=128)
    author_or_source: Optional[str] = Field(None, max_length=255)
    classification: Optional[str] = Field("INTERNAL", max_length=50)
    tags: List[str] = Field(default_factory=list)
    extra_attributes: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra_attributes")
    @classmethod
    def validate_extra_attributes(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_secrets_in_metadata(v)
        return v


class DocumentIdentity(BaseModel):
    """Immutable identity and tenancy coordinates for a document."""
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    file_type: Optional[str] = Field(None, max_length=50)
    s3_uri: Optional[str] = Field(None, max_length=500)
    source_url: Optional[str] = Field(None, max_length=500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be a non-empty string.")
        return v.strip()


class DocumentContract(BaseModel):
    """Authoritative domain contract representing a knowledge document.

    Bidirectionally compatible with the PostgreSQL `documents` table model.
    """
    model_config = ConfigDict(extra="forbid")

    identity: DocumentIdentity
    status: DocumentStatus = DocumentStatus.INDEXED
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    chunk_count: int = Field(default=0, ge=0)

    @property
    def id(self) -> str:
        return self.identity.document_id

    @property
    def org_id(self) -> str:
        return self.identity.organization_id

    @property
    def title(self) -> str:
        return self.identity.title

    @classmethod
    def from_orm_model(cls, doc: Any) -> DocumentContract:
        """Convert a SQLAlchemy Document model instance to DocumentContract."""
        meta_dict = getattr(doc, "metadata_json", None) or {}
        validate_no_secrets_in_metadata(meta_dict)

        doc_meta = DocumentMetadata(
            source_uri=meta_dict.get("source_uri") or getattr(doc, "source_url", None),
            content_hash=meta_dict.get("content_hash"),
            author_or_source=meta_dict.get("author_or_source"),
            classification=meta_dict.get("classification", "INTERNAL"),
            tags=meta_dict.get("tags", []),
            extra_attributes={
                k: v for k, v in meta_dict.items()
                if k not in ("source_uri", "content_hash", "author_or_source", "classification", "tags")
            },
        )

        org_id = getattr(doc, "org_id", None)
        if not org_id:
            raise RAGTenantIsolationError(f"Document {doc.id} missing mandatory org_id.")

        identity = DocumentIdentity(
            document_id=str(doc.id),
            organization_id=str(org_id),
            title=str(doc.title),
            file_type=getattr(doc, "file_type", None),
            s3_uri=getattr(doc, "s3_uri", None),
            source_url=getattr(doc, "source_url", None),
            created_at=getattr(doc, "created_at", None) or datetime.now(timezone.utc),
        )

        raw_status = getattr(doc, "status", "INDEXED")
        try:
            status_enum = DocumentStatus(raw_status)
        except ValueError:
            status_enum = DocumentStatus.INDEXED

        chunks_list = getattr(doc, "chunks", None)
        chunk_count = len(chunks_list) if chunks_list is not None else 0

        return cls(
            identity=identity,
            status=status_enum,
            metadata=doc_meta,
            chunk_count=chunk_count,
        )

    def to_orm_kwargs(self) -> Dict[str, Any]:
        """Produce dictionary suitable for instantiating SQLAlchemy Document."""
        meta_dict = {
            "source_uri": self.metadata.source_uri,
            "content_hash": self.metadata.content_hash,
            "author_or_source": self.metadata.author_or_source,
            "classification": self.metadata.classification,
            "tags": self.metadata.tags,
            **self.metadata.extra_attributes,
        }
        return {
            "id": self.identity.document_id,
            "org_id": self.identity.organization_id,
            "title": self.identity.title,
            "file_type": self.identity.file_type,
            "s3_uri": self.identity.s3_uri,
            "source_url": self.identity.source_url,
            "status": self.status.value,
            "metadata_json": meta_dict,
            "created_at": self.identity.created_at,
        }


# ==============================================================================
# CHUNK & EMBEDDING CONTRACTS
# ==============================================================================

class EmbeddingVector(BaseModel):
    """Strongly typed vector embedding representation with strict dimension validation."""
    model_config = ConfigDict(extra="forbid")

    values: List[float] = Field(..., min_length=1)
    dimension: int = Field(..., gt=0)
    is_normalized: bool = False

    @model_validator(mode="after")
    def validate_dimension_consistency(self) -> EmbeddingVector:
        if len(self.values) != self.dimension:
            raise RAGEmbeddingDimensionError(
                f"Embedding vector values length ({len(self.values)}) does not match dimension ({self.dimension})."
            )
        return self

    def cosine_similarity(self, other: EmbeddingVector) -> float:
        """Compute cosine similarity bounded in [-1.0, 1.0]."""
        if self.dimension != other.dimension:
            raise RAGEmbeddingDimensionError(
                f"Cannot compute similarity between vectors of dimensions {self.dimension} and {other.dimension}."
            )
        dot = sum(a * b for a, b in zip(self.values, other.values))
        if self.is_normalized and other.is_normalized:
            return max(-1.0, min(1.0, dot))
        norm_a = math.sqrt(sum(a * a for a in self.values))
        norm_b = math.sqrt(sum(b * b for b in other.values))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(-1.0, min(1.0, dot / (norm_a * norm_b)))

    def l2_distance(self, other: EmbeddingVector) -> float:
        """Compute Euclidean (L2) distance."""
        if self.dimension != other.dimension:
            raise RAGEmbeddingDimensionError(
                f"Cannot compute L2 distance between vectors of dimensions {self.dimension} and {other.dimension}."
            )
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(self.values, other.values)))

    def dot_product(self, other: EmbeddingVector) -> float:
        """Compute raw dot product."""
        if self.dimension != other.dimension:
            raise RAGEmbeddingDimensionError(
                f"Cannot compute dot product between vectors of dimensions {self.dimension} and {other.dimension}."
            )
        return sum(a * b for a, b in zip(self.values, other.values))


class EmbeddingMetadata(BaseModel):
    """Metadata describing the generation of an embedding vector."""
    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(..., min_length=1, max_length=128)
    provider: EmbeddingProvider = EmbeddingProvider.OPENAI
    dimension: int = Field(default=1536, gt=0)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChunkMetadata(BaseModel):
    """Structural and contextual metadata for a document chunk."""
    model_config = ConfigDict(extra="forbid")

    section_title: Optional[str] = Field(None, max_length=255)
    start_char_idx: Optional[int] = Field(None, ge=0)
    end_char_idx: Optional[int] = Field(None, ge=0)
    language: Optional[str] = Field("en", max_length=10)
    content_type: Optional[str] = Field("text/plain", max_length=50)
    extra_attributes: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra_attributes")
    @classmethod
    def validate_extra(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_secrets_in_metadata(v)
        return v


class ChunkIdentity(BaseModel):
    """Identity, document parentage, and tenant coordinates for a chunk."""
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., min_length=1, max_length=64)
    document_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    chunk_index: int = Field(..., ge=0)
    token_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be a non-empty string.")
        return v.strip()


class DocumentChunkContract(BaseModel):
    """Authoritative domain contract representing a text chunk.

    Bidirectionally compatible with the PostgreSQL `document_chunks` table model.
    """
    model_config = ConfigDict(extra="forbid")

    identity: ChunkIdentity
    content: str = Field(..., min_length=1)
    metadata: ChunkMetadata = Field(default_factory=ChunkMetadata)
    embedding: Optional[EmbeddingVector] = None

    @property
    def id(self) -> str:
        return self.identity.chunk_id

    @property
    def document_id(self) -> str:
        return self.identity.document_id

    @property
    def org_id(self) -> str:
        return self.identity.organization_id

    @property
    def chunk_index(self) -> int:
        return self.identity.chunk_index

    @property
    def token_count(self) -> int:
        return self.identity.token_count

    @classmethod
    def from_orm_model(cls, chunk: Any, organization_id: str) -> DocumentChunkContract:
        """Convert a SQLAlchemy DocumentChunk model instance to DocumentChunkContract."""
        if not organization_id or not organization_id.strip():
            raise RAGTenantIsolationError("organization_id is mandatory to instantiate DocumentChunkContract.")

        embedding_vector = None
        emb_json = getattr(chunk, "embedding_json", None)
        if emb_json:
            if isinstance(emb_json, list):
                embedding_vector = EmbeddingVector(values=emb_json, dimension=len(emb_json))
            elif isinstance(emb_json, dict) and "values" in emb_json:
                embedding_vector = EmbeddingVector(
                    values=emb_json["values"],
                    dimension=emb_json.get("dimension", len(emb_json["values"])),
                    is_normalized=emb_json.get("is_normalized", False),
                )

        identity = ChunkIdentity(
            chunk_id=str(chunk.id),
            document_id=str(chunk.document_id),
            organization_id=organization_id.strip(),
            chunk_index=int(chunk.chunk_index),
            token_count=int(getattr(chunk, "token_count", 0) or 0),
            created_at=getattr(chunk, "created_at", None) or datetime.now(timezone.utc),
        )

        return cls(
            identity=identity,
            content=str(chunk.content),
            metadata=ChunkMetadata(),
            embedding=embedding_vector,
        )

    def to_orm_kwargs(self) -> Dict[str, Any]:
        """Produce dictionary suitable for instantiating SQLAlchemy DocumentChunk."""
        emb_json = None
        if self.embedding is not None:
            emb_json = {
                "values": self.embedding.values,
                "dimension": self.embedding.dimension,
                "is_normalized": self.embedding.is_normalized,
            }
        return {
            "id": self.identity.chunk_id,
            "document_id": self.identity.document_id,
            "chunk_index": self.identity.chunk_index,
            "content": self.content,
            "embedding_json": emb_json,
            "token_count": self.identity.token_count,
            "created_at": self.identity.created_at,
        }


# ==============================================================================
# RETRIEVAL CONTRACTS
# ==============================================================================

class RetrievalFilter(BaseModel):
    """Scoped query filtering criteria."""
    model_config = ConfigDict(extra="forbid")

    file_types: Optional[List[str]] = None
    document_ids: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    scope_entity_type: Optional[str] = None
    scope_entity_id: Optional[str] = None


class RetrievalQuery(BaseModel):
    """Input contract for a semantic or hybrid knowledge retrieval request."""
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    query_text: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    filter: Optional[RetrievalFilter] = None
    query_embedding: Optional[EmbeddingVector] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id is strictly mandatory for retrieval.")
        return v.strip()

    @field_validator("query_text", mode="before")
    @classmethod
    def validate_query_text(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGInvalidQueryError("query_text must contain non-whitespace text.")
        return v.strip()


class RetrievalProvenance(BaseModel):
    """Full unbroken lineage tracing a retrieved chunk back to its source document and tenant."""
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(..., min_length=1, max_length=64)
    chunk_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    chunk_index: int = Field(..., ge=0)
    document_title: str = Field(..., min_length=1, max_length=255)
    file_type: Optional[str] = Field(None, max_length=50)
    s3_uri: Optional[str] = Field(None, max_length=500)
    source_url: Optional[str] = Field(None, max_length=500)
    retrieval_id: str = Field(..., min_length=1, max_length=64)
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    rank: int = Field(..., ge=1)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be non-empty in provenance.")
        return v.strip()


class RetrievedChunk(BaseModel):
    """Retrieved text passage bundled with similarity score, rank, and unbroken provenance."""
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., min_length=1, max_length=64)
    document_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1)
    score: float = Field(..., ge=0.0, le=1.0)
    rank: int = Field(..., ge=1)
    token_count: int = Field(default=0, ge=0)
    provenance: RetrievalProvenance
    is_untrusted_data: bool = True
    prompt_injection_flags: List[str] = Field(default_factory=list)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be non-empty in retrieved chunk.")
        return v.strip()

    @model_validator(mode="after")
    def validate_provenance_consistency(self) -> RetrievedChunk:
        # Check tenant consistency between chunk and provenance
        if self.organization_id != self.provenance.organization_id:
            raise RAGTenantIsolationError(
                f"RetrievedChunk org '{self.organization_id}' does not match provenance org '{self.provenance.organization_id}'."
            )
        # Check chunk ID and document ID consistency
        if self.chunk_id != self.provenance.chunk_id:
            raise RAGProvenanceLineageError(
                f"RetrievedChunk chunk_id '{self.chunk_id}' does not match provenance chunk_id '{self.provenance.chunk_id}'."
            )
        if self.document_id != self.provenance.document_id:
            raise RAGProvenanceLineageError(
                f"RetrievedChunk doc_id '{self.document_id}' does not match provenance doc_id '{self.provenance.document_id}'."
            )
        # Invariant: retrieved text is DATA, never instructions
        if not self.is_untrusted_data:
            raise RAGSecurityPolicyViolationError(
                "Retrieved text must strictly have is_untrusted_data=True."
            )
        return self


class RetrievalResultSet(BaseModel):
    """Collection of retrieved chunks ordered deterministically by relevance."""
    model_config = ConfigDict(extra="forbid")

    retrieval_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    query_text: str = Field(..., min_length=1)
    chunks: List[RetrievedChunk] = Field(default_factory=list)
    total_retrieved: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be non-empty in result set.")
        return v.strip()

    @model_validator(mode="after")
    def enforce_tenant_isolation_and_deterministic_order(self) -> RetrievalResultSet:
        # Enforce server-side tenant isolation: all chunks must belong to organization_id
        for chunk in self.chunks:
            if chunk.organization_id != self.organization_id:
                raise RAGTenantIsolationError(
                    f"Cross-tenant retrieval detected: chunk {chunk.chunk_id} belongs to '{chunk.organization_id}', query is scoped to '{self.organization_id}'."
                )

        # Enforce deterministic ordering: (score DESC, chunk_index ASC, chunk_id ASC)
        self.chunks.sort(
            key=lambda c: (-c.score, c.provenance.chunk_index, c.chunk_id)
        )
        # Re-assign ranks 1..N based on deterministic sort
        for idx, chunk in enumerate(self.chunks, start=1):
            chunk.rank = idx

        self.total_retrieved = len(self.chunks)
        return self


# ==============================================================================
# RAG CONTEXT ASSEMBLY & SECURITY BOUNDARIES
# ==============================================================================

class RAGContextCitation(BaseModel):
    """Grounded citation directly linked to an actual retrieved chunk."""
    model_config = ConfigDict(extra="forbid")

    citation_key: str = Field(..., min_length=1, max_length=64)
    document_id: str = Field(..., min_length=1, max_length=64)
    chunk_id: str = Field(..., min_length=1, max_length=64)
    document_title: str = Field(..., min_length=1, max_length=255)
    chunk_index: int = Field(..., ge=0)
    source_url: Optional[str] = Field(None, max_length=500)
    s3_uri: Optional[str] = Field(None, max_length=500)
    excerpt: str = Field(..., min_length=1)
    citation_id: Optional[str] = Field(None, max_length=64)
    organization_id: Optional[str] = Field(None, max_length=64)


class GroundedContextItem(BaseModel):
    """Structured, attributed unit of contextual knowledge with strict provenance linkage."""
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., min_length=1, max_length=64)
    item_type: GroundedItemType = GroundedItemType.RETRIEVED_FACT
    content: str = Field(..., min_length=1)
    chunk_id: str = Field(..., min_length=1, max_length=64)
    document_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    citation_id: str = Field(..., min_length=1, max_length=64)
    citation_key: str = Field(..., min_length=1, max_length=64)
    provenance: RetrievalProvenance
    is_safe: bool = True
    prompt_injection_flags: List[str] = Field(default_factory=list)


class DataTrustBoundary(BaseModel):
    """Security envelope defining trust demarcation for retrieved context."""
    model_config = ConfigDict(extra="forbid")

    is_untrusted_data: bool = True
    contains_instructions: bool = False
    sanitized: bool = True
    injection_risk_detected: bool = False
    detected_risk_indicators: List[str] = Field(default_factory=list)
    safety_envelope_format: str = "XML_ENCLOSED_PASSIVE_DATA"

    @model_validator(mode="after")
    def validate_safety_invariants(self) -> DataTrustBoundary:
        if not self.is_untrusted_data:
            raise RAGSecurityPolicyViolationError("RAG context is untrusted data; is_untrusted_data must be True.")
        if self.contains_instructions:
            raise RAGSecurityPolicyViolationError("RAG context cannot declare contains_instructions=True.")
        return self


class RAGContext(BaseModel):
    """Assembled contextual knowledge bundle ready for downstream AI agents."""
    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    query_text: str = Field(..., min_length=1)
    assembled_text: str = Field(default="")
    citations: List[RAGContextCitation] = Field(default_factory=list)
    source_chunks: List[RetrievedChunk] = Field(default_factory=list)
    total_tokens: int = Field(default=0, ge=0)
    assembled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trust_boundary: DataTrustBoundary = Field(default_factory=DataTrustBoundary)
    grounding_status: GroundingStatus = Field(default=GroundingStatus.GROUNDED)
    grounded_items: List[GroundedContextItem] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    # Optional grounding references to Phase 6 and Phase 7 entities
    grounding_signal_id: Optional[str] = None
    grounding_assessment_id: Optional[str] = None

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise RAGTenantIsolationError("organization_id must be non-empty in RAG context.")
        return v.strip()

    @model_validator(mode="after")
    def validate_tenancy_and_grounding_invariants(self) -> RAGContext:
        # Enforce tenant isolation across all source chunks
        for chunk in self.source_chunks:
            if chunk.organization_id != self.organization_id:
                raise RAGTenantIsolationError(
                    f"Cross-tenant chunk {chunk.chunk_id} in RAGContext scoped to '{self.organization_id}'."
                )

        # Invariant: Zero hallucinated citations.
        # Every citation MUST match a chunk in source_chunks.
        valid_chunk_ids = {c.chunk_id for c in self.source_chunks}
        for citation in self.citations:
            if citation.chunk_id not in valid_chunk_ids:
                raise RAGProvenanceLineageError(
                    f"Citation {citation.citation_key} references chunk_id '{citation.chunk_id}' not present in source_chunks. Hallucinated sources are prohibited."
                )
            if citation.organization_id and citation.organization_id != self.organization_id:
                raise RAGTenantIsolationError(
                    f"Cross-tenant citation {citation.citation_key} belongs to '{citation.organization_id}', context scoped to '{self.organization_id}'."
                )

        # Enforce tenant isolation and provenance linkage across grounded items
        for item in self.grounded_items:
            if item.organization_id != self.organization_id:
                raise RAGTenantIsolationError(
                    f"Cross-tenant grounded item {item.item_id} in RAGContext scoped to '{self.organization_id}'."
                )
            if item.chunk_id not in valid_chunk_ids:
                raise RAGProvenanceLineageError(
                    f"Grounded item {item.item_id} references chunk_id '{item.chunk_id}' not present in source_chunks."
                )

        return self

    @classmethod
    def assemble(
        cls,
        organization_id: str,
        query: RetrievalQuery,
        result_set: RetrievalResultSet,
        grounding_signal_id: Optional[str] = None,
        grounding_assessment_id: Optional[str] = None,
    ) -> RAGContext:
        """Deterministically assemble a safe, cited RAGContext from a RetrievalResultSet."""
        if query.organization_id != organization_id:
            raise RAGTenantIsolationError(
                f"Query org '{query.organization_id}' does not match context org '{organization_id}'."
            )
        if result_set.organization_id != organization_id:
            raise RAGTenantIsolationError(
                f"ResultSet org '{result_set.organization_id}' does not match context org '{organization_id}'."
            )

        citations: List[RAGContextCitation] = []
        grounded_items: List[GroundedContextItem] = []
        envelope_sections: List[str] = []
        total_tokens = 0
        all_injection_indicators: List[str] = []

        # Chunks are already deterministically sorted in result_set
        for idx, chunk in enumerate(result_set.chunks, start=1):
            citation_key = f"[CIT-{idx}]"
            citation_id = generate_deterministic_citation_id(
                organization_id=organization_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                retrieval_id=result_set.retrieval_id,
            )
            excerpt = chunk.content[:150].strip() + ("..." if len(chunk.content) > 150 else "")

            citation = RAGContextCitation(
                citation_key=citation_key,
                citation_id=citation_id,
                organization_id=organization_id,
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
                organization_id=organization_id,
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
            total_tokens += chunk.token_count

        assembled_text = "\n\n".join(envelope_sections)

        chunk_ids = [c.chunk_id for c in result_set.chunks]
        context_id = generate_deterministic_context_id(
            organization_id=organization_id,
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

        # Determine grounding status
        if len(result_set.chunks) == 0:
            grounding_status = GroundingStatus.UNGROUNDED
        elif all(len(c.prompt_injection_flags) > 0 for c in result_set.chunks):
            grounding_status = GroundingStatus.UNSAFE_SOURCE
        elif any(len(c.prompt_injection_flags) > 0 for c in result_set.chunks):
            grounding_status = GroundingStatus.PARTIALLY_GROUNDED
        else:
            grounding_status = GroundingStatus.GROUNDED

        return cls(
            context_id=context_id,
            organization_id=organization_id,
            query_text=query.query_text,
            assembled_text=assembled_text,
            citations=citations,
            source_chunks=result_set.chunks,
            total_tokens=total_tokens,
            assembled_at=datetime.now(timezone.utc),
            trust_boundary=trust_boundary,
            grounding_status=grounding_status,
            grounded_items=grounded_items,
            limitations=[],
            grounding_signal_id=grounding_signal_id,
            grounding_assessment_id=grounding_assessment_id,
        )
