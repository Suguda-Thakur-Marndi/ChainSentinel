"""Strongly typed error taxonomy for the RiskWise Research Agent.

All errors inherit from the foundational AgentGraphError and classify failures
as RETRYABLE or NON_RETRYABLE, ensuring security and evidence integrity violations
fail closed immediately.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import AgentGraphError, ErrorClassification


class ResearchError(AgentGraphError):
    """Base exception for all research agent operational failures."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "RESEARCH_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
        )


class InvalidResearchRequestError(ResearchError):
    """Raised when a research request is malformed, missing an objective, or invalid."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="INVALID_RESEARCH_REQUEST",
            details=details,
        )


class MissingEvidenceError(ResearchError):
    """Raised when required research evidence bundle or items are absent."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="MISSING_EVIDENCE_ERROR",
            details=details,
        )


class InvalidEvidenceError(ResearchError):
    """Raised when an evidence bundle is corrupted, unparseable, or schema-invalid."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="INVALID_EVIDENCE_ERROR",
            details=details,
        )


class EvidenceIntegrityError(ResearchError):
    """Raised when evidence fails cryptographic, provenance, or citation integrity checks."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="EVIDENCE_INTEGRITY_ERROR",
            details=details,
        )


class ResearchTenantIsolationError(ResearchError):
    """Raised when a cross-tenant evidence bundle, citation, or request is detected.
    
    CRITICAL: Must always fail closed immediately.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RESEARCH_TENANT_ISOLATION_ERROR",
            details=details,
        )


class ResearchCitationIntegrityError(ResearchError):
    """Raised when an LLM finding or conflict references a hallucinated, unverified, or cross-tenant citation/evidence ID."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RESEARCH_CITATION_INTEGRITY_ERROR",
            details=details,
        )


class ResearchGroundingError(ResearchError):
    """Raised when an ungrounded or unsupported claim is represented as a verified fact."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RESEARCH_GROUNDING_ERROR",
            details=details,
        )


class ResearchLLMError(ResearchError):
    """Raised when LLM invocation, parsing, or schema validation encounters a failure."""

    def __init__(
        self,
        message: str,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE if retryable else ErrorClassification.NON_RETRYABLE,
            error_code="RESEARCH_LLM_ERROR",
            details=details,
        )
