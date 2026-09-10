"""Strongly typed exceptions for the RiskWise Decision Agent (Phase 9 Step 8).

Guarantees fail-closed error semantics for tenant boundaries, input validation,
missing scenario prerequisites, candidate generation, and evidence lineage.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import (
    AgentNodeExecutionError,
    AgentTenantIsolationError,
    AgentValidationError,
)


class DecisionAgentError(AgentNodeExecutionError):
    """Base exception for all Decision Agent execution failures."""

    def __init__(
        self,
        message: str,
        error_code: str = "DECISION_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            node_name="decision_agent",
            retryable=retryable,
            details=details,
        )
        self.error_code = error_code


class InvalidDecisionRequestError(AgentValidationError):
    """Raised when a DecisionRequest fails schema validation or contains forbidden fields."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "INVALID_DECISION_REQUEST"


class DecisionTenantIsolationError(AgentTenantIsolationError):
    """Raised when tenant boundaries are violated across decision inputs or candidates."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "DECISION_TENANT_VIOLATION"


class MissingScenarioError(DecisionAgentError):
    """Raised when required upstream scenario context is missing."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="MISSING_SCENARIO_CONTEXT",
            details=details,
            retryable=False,
        )


class InvalidScenarioReferenceError(DecisionAgentError):
    """Raised when an upstream scenario reference is malformed or unverified."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_SCENARIO_REFERENCE",
            details=details,
            retryable=False,
        )


class InvalidDecisionCandidateError(DecisionAgentError):
    """Raised when a decision candidate has invalid parameters, bounds, or forbidden operational commands."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_DECISION_CANDIDATE",
            details=details,
            retryable=False,
        )


class InsufficientEvidenceError(DecisionAgentError):
    """Raised when required upstream evidence/lineage is missing and a candidate cannot be formed."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INSUFFICIENT_EVIDENCE",
            details=details,
            retryable=False,
        )


class UnsupportedDecisionTypeError(DecisionAgentError):
    """Raised when a requested decision type is outside the supported taxonomy."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_DECISION_TYPE",
            details=details,
            retryable=False,
        )


class DecisionGenerationError(DecisionAgentError):
    """Raised when deterministic decision rule evaluation encounters a structural failure."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_GENERATION_FAILED",
            details=details,
            retryable=False,
        )


class DecisionAuthorizationError(DecisionAgentError):
    """Raised when execution context lacks required roles for decision evaluation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_AUTHORIZATION_FAILED",
            details=details,
            retryable=False,
        )
