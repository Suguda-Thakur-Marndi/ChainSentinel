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


# ==============================================================================
# Phase 10 Step 7 Typed Domain Error Extensions for Decision Explanation
# ==============================================================================

class DecisionExplanationError(DecisionAgentError):
    """Base exception for all Decision Explanation Layer failures."""

    def __init__(
        self,
        message: str,
        error_code: str = "DECISION_EXPLANATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            details=details,
            retryable=retryable,
        )


class DecisionValueContradictionError(DecisionExplanationError):
    """Raised when Claude contradicts or alters authoritative decision values."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_VALUE_CONTRADICTION",
            details=details,
            retryable=False,
        )


class DecisionStatusContradictionError(DecisionExplanationError):
    """Raised when Claude claims a decision status contradicting authoritative status."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_STATUS_CONTRADICTION",
            details=details,
            retryable=False,
        )


class DecisionActionContradictionError(DecisionExplanationError):
    """Raised when Claude asserts an action type contradicting authoritative candidate."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_ACTION_CONTRADICTION",
            details=details,
            retryable=False,
        )


class DecisionCandidateContradictionError(DecisionExplanationError):
    """Raised when Claude contradicts the selected candidate or candidate set."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_CANDIDATE_CONTRADICTION",
            details=details,
            retryable=False,
        )


class DecisionOptionFabricationError(DecisionExplanationError):
    """Raised when Claude invents candidates or options not present in authoritative decision."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_OPTION_FABRICATION",
            details=details,
            retryable=False,
        )


class DecisionApprovalViolationError(DecisionExplanationError):
    """Raised when Claude claims approval was granted, bypasses approval, or claims authority to approve."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_APPROVAL_VIOLATION",
            details=details,
            retryable=False,
        )


class DecisionExecutionViolationError(DecisionExplanationError):
    """Raised when Claude claims an operational action was executed or dispatches commands."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_EXECUTION_VIOLATION",
            details=details,
            retryable=False,
        )


class DecisionOptimizationFabricationError(DecisionExplanationError):
    """Raised when Claude fabricates mathematical optimization (OR-Tools, LP, MIP, solver claims)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_OPTIMIZATION_FABRICATION",
            details=details,
            retryable=False,
        )


class DecisionQuantitativeFabricationError(DecisionExplanationError):
    """Raised when Claude invents quantitative metrics, savings, costs, or probabilities without grounding."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_QUANTITATIVE_FABRICATION",
            details=details,
            retryable=False,
        )


class DecisionExplanationCitationIntegrityError(DecisionExplanationError):
    """Raised when Claude cites an ungrounded or non-existent evidence or candidate ID."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_CITATION_INTEGRITY_ERROR",
            details=details,
            retryable=False,
        )


class DecisionExplanationGroundingError(DecisionExplanationError):
    """Raised when a rationale or trade-off claim lacks required supporting evidence or references."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_GROUNDING_ERROR",
            details=details,
            retryable=False,
        )


class DecisionExplanationLLMError(DecisionExplanationError):
    """Raised when Claude invocation, parsing, or token budgeting encounters a failure."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DECISION_LLM_ERROR",
            details=details,
            retryable=retryable,
        )
