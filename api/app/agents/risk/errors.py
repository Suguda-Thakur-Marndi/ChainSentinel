"""Strongly typed error taxonomy for the RiskWise Risk Agent.

All errors inherit from AgentGraphError and are classified as RETRYABLE
or NON_RETRYABLE. Security, tenant, and evidence integrity violations
always fail closed immediately (NON_RETRYABLE).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import AgentGraphError, ErrorClassification


class RiskAgentError(AgentGraphError):
    """Base exception for all Risk Agent operational failures."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "RISK_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
        )


class InvalidRiskRequestError(RiskAgentError):
    """Raised when a risk request is malformed, missing required fields, or invalid."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="INVALID_RISK_REQUEST",
            details=details,
        )


class RiskTenantIsolationError(RiskAgentError):
    """Raised when a cross-tenant research result, evidence, or risk assessment is detected.

    CRITICAL: Must always fail closed immediately. Never retryable.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_TENANT_ISOLATION_ERROR",
            details=details,
        )


class RiskEvidenceBoundaryError(RiskAgentError):
    """Raised when evidence fails tenant, integrity, or provenance boundary checks."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_EVIDENCE_BOUNDARY_ERROR",
            details=details,
        )


class RiskEngineAdapterError(RiskAgentError):
    """Raised when the Risk Engine adapter encounters an internal evaluation failure.

    Classified as RETRYABLE — transient engine failures may resolve on retry.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code="RISK_ENGINE_ADAPTER_ERROR",
            details=details,
        )


class RiskInputValidationError(RiskAgentError):
    """Raised when risk engine inputs fail schema or boundary validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_INPUT_VALIDATION_ERROR",
            details=details,
        )


class UnsupportedFindingMappingError(RiskAgentError):
    """Raised when a research finding category cannot be safely mapped to a Risk Engine signal.

    This results in a structured UNSUPPORTED_MAPPING limitation, not an unhandled failure.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="UNSUPPORTED_FINDING_MAPPING",
            details=details,
        )


class RiskExplanationError(RiskAgentError):
    """Base exception for all Claude Risk Explanation operations."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "RISK_EXPLANATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
        )


class RiskScoreContradictionError(RiskExplanationError):
    """Raised when Claude explanation contradicts authoritative Phase 7 risk score or level."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_SCORE_CONTRADICTION",
            details=details,
        )


class RiskFactorContradictionError(RiskExplanationError):
    """Raised when Claude references fabricated or non-existent risk factors."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_FACTOR_CONTRADICTION",
            details=details,
        )


class RiskExplanationCitationIntegrityError(RiskExplanationError):
    """Raised when Claude explanation cites evidence IDs not in the authoritative assessment or bundle."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_EXPLANATION_CITATION_INTEGRITY_ERROR",
            details=details,
        )


class RiskExplanationGroundingError(RiskExplanationError):
    """Raised when an explanation statement is presented as factual without supporting evidence."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_EXPLANATION_GROUNDING_ERROR",
            details=details,
        )


class RiskExplanationLLMError(RiskExplanationError):
    """Raised when the LLM invocation, network, or schema parsing fails."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="RISK_EXPLANATION_LLM_ERROR",
            details=details,
        )
