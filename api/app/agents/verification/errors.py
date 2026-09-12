"""Error hierarchy for the Verification Agent (Phase 18).

Provides strongly typed exceptions for:
- Tenant isolation boundaries
- Action / approval mismatch
- Stale or invalid evidence
- Conflicting operational signals
- Observation window expiry
- Security policy violations
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import (
    AgentErrorCategory,
    AgentGraphError,
    AgentSecurityError,
    AgentTenantIsolationError,
    AgentValidationError,
    ErrorClassification,
)


class VerificationAgentError(AgentGraphError):
    """Base exception for all verification agent operations."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "VERIFICATION_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
        category: Optional[AgentErrorCategory] = None,
        public_message: Optional[str] = None,
        node_id: Optional[str] = "verification_agent",
        stage: Optional[str] = "VERIFICATION",
        retryable: bool = False,
        **kwargs: Any,
    ) -> None:
        effective_classification = (
            ErrorClassification.RETRYABLE if retryable else classification
        )
        super().__init__(
            message=message,
            classification=effective_classification,
            error_code=error_code,
            details=details or {},
            category=category or AgentErrorCategory.VALIDATION_ERROR,
            public_message=public_message,
            node_id=node_id,
            stage=stage,
            **kwargs,
        )
        self.error_code = error_code


class VerificationActionNotFoundError(VerificationAgentError):
    """Raised when the specified action record cannot be found."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details, error_code="ACTION_NOT_FOUND")


class VerificationActionNotExecutedError(VerificationAgentError):
    """Raised when attempting to verify an action that has not been executed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details, error_code="ACTION_NOT_EXECUTED")


class VerificationTenantIsolationError(AgentTenantIsolationError, VerificationAgentError):
    """Raised when cross-tenant action, approval, or evidence is detected."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "TENANT_ISOLATION_VIOLATION"


class VerificationApprovalMismatchError(VerificationAgentError):
    """Raised when action does not match the approved decision or candidate."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details, error_code="APPROVAL_MISMATCH")


class VerificationEvidenceConflictError(VerificationAgentError):
    """Raised when contradictory authoritative evidence is detected."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details, error_code="EVIDENCE_CONFLICT")


class VerificationObservationWindowExpiredError(VerificationAgentError):
    """Raised when verification is attempted after observation window expiration."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details, error_code="OBSERVATION_WINDOW_EXPIRED")


class VerificationSecurityViolationError(AgentSecurityError, VerificationAgentError):
    """Raised when arbitrary URLs, injection, or code execution patterns are detected."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SECURITY_VIOLATION"
