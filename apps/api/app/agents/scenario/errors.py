"""Strongly typed exceptions for the RiskWise Scenario Agent.

Guarantees fail-closed error semantics for tenant boundaries, input validation,
unsupported scenario types, parameter bounds, and missing evidence.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import (
    AgentNodeExecutionError,
    AgentTenantIsolationError,
    AgentValidationError,
)


class ScenarioAgentError(AgentNodeExecutionError):
    """Base exception for all Scenario Agent execution failures."""

    def __init__(
        self,
        message: str,
        error_code: str = "SCENARIO_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            node_name="scenario_agent",
            retryable=retryable,
            details=details,
        )
        self.error_code = error_code


class InvalidScenarioRequestError(AgentValidationError):
    """Raised when a ScenarioRequest fails validation or contains illegal fields."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "INVALID_SCENARIO_REQUEST"


class ScenarioTenantIsolationError(AgentTenantIsolationError):
    """Raised when tenant boundaries are violated across scenario references."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_TENANT_VIOLATION"


class InvalidScenarioParameterError(ScenarioAgentError):
    """Raised when a scenario parameter has invalid values, non-finite numbers, or bad units."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INVALID_SCENARIO_PARAMETER",
            details=details,
            retryable=False,
        )


class UnsupportedScenarioTypeError(ScenarioAgentError):
    """Raised when a requested scenario type is not supported by the taxonomy."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_SCENARIO_TYPE",
            details=details,
            retryable=False,
        )


class InsufficientEvidenceError(ScenarioAgentError):
    """Raised when required upstream evidence/prediction is absent and cannot be fabricated."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="INSUFFICIENT_EVIDENCE",
            details=details,
            retryable=False,
        )


class ScenarioGenerationError(ScenarioAgentError):
    """Raised when deterministic scenario generation encounters a structural failure."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_GENERATION_FAILED",
            details=details,
            retryable=False,
        )
