"""Strongly typed exceptions for the RiskWise Action Agent (Phase 17).

Guarantees fail-closed error semantics for tenant boundaries, mandatory human approval,
approval-action binding, idempotency conflicts, target validation, provider failures,
and security violation protections.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import (
    AgentNodeExecutionError,
    AgentTenantIsolationError,
    AgentValidationError,
)


class ActionAgentError(AgentNodeExecutionError):
    """Base exception for all Action Agent execution failures."""

    def __init__(
        self,
        message: str,
        error_code: str = "ACTION_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            node_name="action_agent",
            retryable=retryable,
            details=details,
        )
        self.error_code = error_code


class InvalidActionRequestError(AgentValidationError):
    """Raised when an ActionCommand / ActionRequest fails schema validation or contains forbidden fields."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "INVALID_ACTION_REQUEST"


class ActionTenantIsolationError(AgentTenantIsolationError):
    """Raised when tenant boundaries are violated across action inputs, approvals, or target entities."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "ACTION_TENANT_VIOLATION"


class ActionApprovalMissingError(ActionAgentError):
    """Raised when an operational action request is missing an approval reference."""

    def __init__(self, message: str = "Operational action execution strictly requires human approval.", details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_APPROVAL_MISSING", details=details, retryable=False)


class ActionApprovalInvalidError(ActionAgentError):
    """Raised when the referenced approval is not in APPROVED status (e.g. PENDING, REJECTED, EXPIRED)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_APPROVAL_INVALID", details=details, retryable=False)


class ActionApprovalMismatchError(ActionAgentError):
    """Raised when the action payload or target does not match the exact approved candidate."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_APPROVAL_MISMATCH", details=details, retryable=False)


class ActionAuthorizationError(ActionAgentError):
    """Raised when the actor attempting to execute the action lacks authorized role (RiskManager, Admin)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_AUTHORIZATION_DENIED", details=details, retryable=False)


class ActionIdempotencyConflictError(ActionAgentError):
    """Raised when an idempotency key is reused with a conflicting payload or target."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_IDEMPOTENCY_CONFLICT", details=details, retryable=False)


class ActionStaleDecisionError(ActionAgentError):
    """Raised when the decision or approval has expired or is too stale to safely execute."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_STALE_DECISION", details=details, retryable=False)


class ActionTargetNotFoundError(ActionAgentError):
    """Raised when the target entity (shipment, carrier, facility, route) does not exist in the tenant."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_TARGET_NOT_FOUND", details=details, retryable=False)


class ActionTargetStateConflictError(ActionAgentError):
    """Raised when the operational state of the target entity conflicts with execution (e.g. already rerouted/delivered)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_TARGET_STATE_CONFLICT", details=details, retryable=False)


class ActionUnsupportedTypeError(ActionAgentError):
    """Raised when the requested action type is not supported or not in the allowlist."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_UNSUPPORTED_TYPE", details=details, retryable=False)


class ActionSecurityViolationError(ActionAgentError):
    """Raised when security violations are detected (arbitrary URLs, SSRF, eval/exec, prompt injection)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_SECURITY_VIOLATION", details=details, retryable=False)


class ActionProviderUnavailableError(ActionAgentError):
    """Raised when an external logistics provider / adapter is unreachable or offline."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_PROVIDER_UNAVAILABLE", details=details, retryable=True)


class ActionProviderTimeoutError(ActionAgentError):
    """Raised when external provider communication times out."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_PROVIDER_TIMEOUT", details=details, retryable=True)


class ActionProviderRejectedError(ActionAgentError):
    """Raised when external provider explicitly rejects the action dispatch."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_PROVIDER_REJECTED", details=details, retryable=False)


class ActionExecutionFailedError(ActionAgentError):
    """Raised when action execution fails unexpectedly."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, error_code="ACTION_EXECUTION_FAILED", details=details, retryable=False)
