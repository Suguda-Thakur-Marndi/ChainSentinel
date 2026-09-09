"""RiskWise 2.0 RAG (Retrieval-Augmented Generation) Subsystem.

Provides grounded, traceable, organization-isolated contextual knowledge to
downstream AI agents while preserving the deterministic Risk Engine as the authoritative
source of risk truth.
"""

from app.rag.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DeterministicChunker,
    estimate_token_count,
    find_section_headings,
)
from app.rag.contracts import (
    ChunkIdentity,
    ChunkMetadata,
    DataTrustBoundary,
    DistanceMetric,
    DocumentChunkContract,
    DocumentContract,
    DocumentIdentity,
    DocumentMetadata,
    DocumentStatus,
    EmbeddingMetadata,
    EmbeddingProvider,
    EmbeddingVector,
    RAGContext,
    RAGContextCitation,
    RetrievalFilter,
    RetrievalProvenance,
    RetrievalQuery,
    RetrievalResultSet,
    RetrievedChunk,
    detect_prompt_injection_indicators,
    format_rag_data_envelope,
    generate_deterministic_chunk_id,
    generate_deterministic_context_id,
    generate_deterministic_document_id,
    generate_deterministic_retrieval_id,
    validate_no_secrets_in_metadata,
)
from app.rag.embeddings import (
    TARGET_EMBEDDING_DIMENSION,
    BaseEmbeddingProvider,
    BedrockEmbeddingProvider,
    LocalMockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    compute_embedding_fingerprint,
    get_embedding_provider,
)
from app.rag.errors import (
    RAGChunkNotFoundError,
    RAGDocumentNotFoundError,
    RAGDocumentTooLargeError,
    RAGEmbeddingDimensionError,
    RAGEmbeddingError,
    RAGEmptyDocumentError,
    RAGError,
    RAGInvalidQueryError,
    RAGMalformedInputError,
    RAGPathTraversalError,
    RAGProvenanceLineageError,
    RAGSecurityPolicyViolationError,
    RAGTenantIsolationError,
    RAGUnsupportedFormatError,
)
from app.rag.ingestion import (
    DocumentIngestionPayload,
    DocumentIngestionResult,
    DocumentIngestionService,
)
from app.rag.parsers import (
    MAX_DOCUMENT_SIZE_BYTES,
    SUPPORTED_MIME_TYPES,
    ExtractedDocumentData,
    SafeHTMLTextExtractor,
    extract_text_from_payload,
    normalize_file_type,
    validate_filename_safety,
)
from app.rag.retrieval import RAGRetrievalService
from app.rag.vector_store import (
    ChunkEmbeddingResult,
    ChunkEmbeddingService,
    extract_embedding_metadata,
    extract_embedding_vector,
)

__all__ = [
    # Errors
    "RAGError",
    "RAGTenantIsolationError",
    "RAGMalformedInputError",
    "RAGInvalidQueryError",
    "RAGDocumentNotFoundError",
    "RAGChunkNotFoundError",
    "RAGEmbeddingDimensionError",
    "RAGEmbeddingError",
    "RAGProvenanceLineageError",
    "RAGSecurityPolicyViolationError",
    "RAGUnsupportedFormatError",
    "RAGDocumentTooLargeError",
    "RAGEmptyDocumentError",
    "RAGPathTraversalError",
    # Enums
    "DocumentStatus",
    "EmbeddingProvider",
    "DistanceMetric",
    # Document contracts
    "DocumentIdentity",
    "DocumentMetadata",
    "DocumentContract",
    # Chunk contracts
    "ChunkIdentity",
    "ChunkMetadata",
    "DocumentChunkContract",
    # Embedding contracts
    "EmbeddingVector",
    "EmbeddingMetadata",
    # Retrieval contracts
    "RetrievalFilter",
    "RetrievalQuery",
    "RetrievalProvenance",
    "RetrievedChunk",
    "RetrievalResultSet",
    # Context & Trust contracts
    "RAGContextCitation",
    "DataTrustBoundary",
    "RAGContext",
    # Deterministic & Security utilities
    "generate_deterministic_document_id",
    "generate_deterministic_chunk_id",
    "generate_deterministic_retrieval_id",
    "generate_deterministic_context_id",
    "format_rag_data_envelope",
    "detect_prompt_injection_indicators",
    "validate_no_secrets_in_metadata",
    # Parsers & Extractors
    "MAX_DOCUMENT_SIZE_BYTES",
    "SUPPORTED_MIME_TYPES",
    "ExtractedDocumentData",
    "SafeHTMLTextExtractor",
    "extract_text_from_payload",
    "normalize_file_type",
    "validate_filename_safety",
    # Chunking
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    "DeterministicChunker",
    "estimate_token_count",
    "find_section_headings",
    # Ingestion service
    "DocumentIngestionPayload",
    "DocumentIngestionResult",
    "DocumentIngestionService",
    # Embedding Providers & Vector Storage (Phase 8 Step 3)
    "TARGET_EMBEDDING_DIMENSION",
    "BaseEmbeddingProvider",
    "LocalMockEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "BedrockEmbeddingProvider",
    "get_embedding_provider",
    "compute_embedding_fingerprint",
    "ChunkEmbeddingResult",
    "ChunkEmbeddingService",
    "extract_embedding_vector",
    "extract_embedding_metadata",
    # Retrieval & Similarity Search (Phase 8 Step 4)
    "RAGRetrievalService",
]
