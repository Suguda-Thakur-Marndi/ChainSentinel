"""Centralized typed exception definitions for RiskWise RAG subsystem.

Provides domain-specific exceptions inheriting from AppError to ensure consistent
error envelopes and HTTP status codes across the RAG layer.
"""

from __future__ import annotations

from typing import Any, Optional
from fastapi import status

from app.core.errors import AppError

HTTP_422_UNPROCESSABLE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class RAGError(AppError):
    """Base exception for all RAG foundation operations."""

    def __init__(
        self,
        message: str = "A RAG subsystem error occurred",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "RAG_ERROR",
        details: Optional[Any] = None,
    ):
        super().__init__(message=message, status_code=status_code, code=code, details=details)


class RAGTenantIsolationError(RAGError):
    """Raised when a document, chunk, query, or retrieval violates organization tenant isolation."""

    def __init__(
        self,
        message: str = "Cross-tenant access violation in RAG subsystem.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="TENANT_ISOLATION_VIOLATION",
            details=details,
        )


class RAGMalformedInputError(RAGError):
    """Raised when an invalid or malformed data payload enters the RAG boundary."""

    def __init__(
        self,
        message: str = "Malformed data rejected at RAG contract boundary.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="MALFORMED_RAG_INPUT",
            details=details,
        )


class RAGInvalidQueryError(RAGError):
    """Raised when retrieval query parameters are invalid (e.g., negative top_k, invalid threshold)."""

    def __init__(
        self,
        message: str = "Invalid retrieval query parameters.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="INVALID_RETRIEVAL_QUERY",
            details=details,
        )


class RAGDocumentNotFoundError(RAGError):
    """Raised when a requested knowledge document does not exist or is masked by tenancy."""

    def __init__(
        self,
        message: str = "Document not found or inaccessible.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="DOCUMENT_NOT_FOUND",
            details=details,
        )


class RAGChunkNotFoundError(RAGError):
    """Raised when a referenced document chunk cannot be found."""

    def __init__(
        self,
        message: str = "Document chunk not found.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            code="CHUNK_NOT_FOUND",
            details=details,
        )


class RAGEmbeddingDimensionError(RAGError):
    """Raised when embedding vector dimensions do not match the expected specification."""

    def __init__(
        self,
        message: str = "Embedding vector dimension mismatch.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="EMBEDDING_DIMENSION_MISMATCH",
            details=details,
        )


class RAGProvenanceLineageError(RAGError):
    """Raised when a retrieved item lacks required provenance or violates lineage traceability."""

    def __init__(
        self,
        message: str = "Retrieved chunk has broken or unverifiable provenance lineage.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="PROVENANCE_LINEAGE_BROKEN",
            details=details,
        )


class RAGSecurityPolicyViolationError(RAGError):
    """Raised when a RAG operation violates security policy (e.g., secret leakage, instruction hijacking)."""

    def __init__(
        self,
        message: str = "Security policy violation detected in RAG operation.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="RAG_SECURITY_VIOLATION",
            details=details,
        )


class RAGUnsupportedFormatError(RAGError):
    """Raised when an unsupported document MIME type or file format is ingested."""

    def __init__(
        self,
        message: str = "Unsupported document format.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="UNSUPPORTED_DOCUMENT_FORMAT",
            details=details,
        )


class RAGDocumentTooLargeError(RAGError):
    """Raised when a document payload exceeds the maximum permitted size limit."""

    def __init__(
        self,
        message: str = "Document payload exceeds maximum allowed size.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413),
            code="DOCUMENT_TOO_LARGE",
            details=details,
        )


class RAGEmptyDocumentError(RAGError):
    """Raised when a document contains no extractable or readable text."""

    def __init__(
        self,
        message: str = "Document contains no readable text content.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="EMPTY_DOCUMENT",
            details=details,
        )


class RAGPathTraversalError(RAGError):
    """Raised when a filename or title contains path traversal or directory escaping sequences."""

    def __init__(
        self,
        message: str = "Path traversal sequence detected in filename or title.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="PATH_TRAVERSAL_DETECTED",
            details=details,
        )

