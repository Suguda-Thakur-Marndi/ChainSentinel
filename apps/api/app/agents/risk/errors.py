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
