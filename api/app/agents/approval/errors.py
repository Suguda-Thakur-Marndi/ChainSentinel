"""Strongly typed exceptions for the RiskWise Human Approval boundary (Phase 9 Step 9).

Guarantees fail-closed error semantics for tenant boundaries, authorization,
lifecycle transitions, and persistence integrity.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import (
    AgentNodeExecutionError,
    AgentTenantIsolationError,
    AgentValidationError,
)


class ApprovalAgentError(AgentNodeExecutionError):
    """Root base class for all Human Approval Agent exceptions."""

    def __init__(
        self,
        message: str,
        error_code: str = "APPROVAL_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            node_name="human_approval",
            retryable=retryable,
            details=details,
        )
        self.error_code = error_code
        self.retryable = retryable
        self.node_name = "human_approval"


class InvalidApprovalRequestError(ApprovalAgentError):
    """Raised when an approval request fails schema validation or contains forbidden inputs."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_APPROVAL_REQUEST",
            details=details,
            retryable=False,
        )


class ApprovalTenantIsolationError(ApprovalAgentError):
    """Raised when multi-tenant boundary isolation is breached during approval evaluation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_TENANT_ISOLATION_ERROR",
            details=details,
            retryable=False,
        )


class ApprovalAuthorizationError(ApprovalAgentError):
    """Raised when an unauthorized actor attempts an approval sign-off."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_UNAUTHORIZED",
            retryable=False,
            details=details,
        )


class ApprovalNotFoundError(ApprovalAgentError):
    """Raised when an approval record cannot be found for the specified identifier."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_NOT_FOUND",
            retryable=False,
            details=details,
        )


class InvalidApprovalTransitionError(ApprovalAgentError):
    """Raised when an invalid approval lifecycle transition is attempted."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_APPROVAL_TRANSITION",
            retryable=False,
            details=details,
        )


class ApprovalAlreadyFinalizedError(ApprovalAgentError):
    """Raised when attempting to modify or conflictingly re-decide an already finalized approval."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_ALREADY_FINALIZED",
            retryable=False,
            details=details,
        )


class ApprovalCandidateMismatchError(ApprovalAgentError):
    """Raised when the approval decision references a candidate not present in the upstream decision."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_CANDIDATE_MISMATCH",
            retryable=False,
            details=details,
        )


class ApprovalDecisionRequiredError(ApprovalAgentError):
    """Raised when an action is attempted without an explicit human approval decision."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_DECISION_REQUIRED",
            retryable=False,
            details=details,
        )


class ApprovalExpiredError(ApprovalAgentError):
    """Raised when attempting to approve an expired approval request."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_EXPIRED",
            retryable=False,
            details=details,
        )


class ApprovalPersistenceError(ApprovalAgentError):
    """Raised when transactional database persistence fails for an approval mutation."""

    def __init__(self, message: str, retryable: bool = False, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_PERSISTENCE_ERROR",
            retryable=retryable,
            details=details,
        )


class ApprovalStateOwnershipViolationError(ApprovalAgentError):
    """Raised when an unauthorized node attempts to mutate approval state fields."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="APPROVAL_STATE_OWNERSHIP_VIOLATION",
            retryable=False,
            details=details,
        )
