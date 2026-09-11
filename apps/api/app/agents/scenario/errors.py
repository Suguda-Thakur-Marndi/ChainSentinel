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


class ScenarioExplanationError(ScenarioAgentError):
    """Base exception for all Scenario Explanation Layer failures."""

    def __init__(
        self,
        message: str,
        error_code: str = "SCENARIO_EXPLANATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            error_code=error_code,
            details=details,
            retryable=retryable,
        )


class ScenarioTypeContradictionError(ScenarioExplanationError):
    """Raised when Claude asserts a scenario type contradicting the authoritative scenario."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_TYPE_CONTRADICTION",
            details=details,
            retryable=False,
        )


class ScenarioParameterContradictionError(ScenarioExplanationError):
    """Raised when Claude contradicts, alters, or fabricates scenario parameter values."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_PARAMETER_CONTRADICTION",
            details=details,
            retryable=False,
        )


class ScenarioSimulationOutputFabricationError(ScenarioExplanationError):
    """Raised when Claude invents simulation metrics (e.g. probability, expected loss, inventory shortages) without engine support."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_SIMULATION_FABRICATION",
            details=details,
            retryable=False,
        )


class ScenarioExplanationCitationIntegrityError(ScenarioExplanationError):
    """Raised when Claude cites an ungrounded or non-existent evidence ID or citation key."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_CITATION_INTEGRITY_ERROR",
            details=details,
            retryable=False,
        )


class ScenarioExplanationGroundingError(ScenarioExplanationError):
    """Raised when an assumption or parameter claim lacks required supporting evidence."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_GROUNDING_ERROR",
            details=details,
            retryable=False,
        )


class ScenarioExplanationLLMError(ScenarioExplanationError):
    """Raised when Claude invocation, parsing, or token budgeting encounters a failure."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_LLM_ERROR",
            details=details,
            retryable=retryable,
        )


# ==============================================================================
# Phase 10 Step 7 Typed Domain Error Extensions
# ==============================================================================

class ScenarioValueContradictionError(ScenarioParameterContradictionError):
    """Raised when Claude contradicts, alters, or misrepresents authoritative scenario values."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_VALUE_CONTRADICTION"


class ScenarioStatusContradictionError(ScenarioExplanationError):
    """Raised when Claude claims a scenario succeeded or has outcomes when authoritative status is failed/unavailable."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_STATUS_CONTRADICTION",
            details=details,
            retryable=False,
        )


class ScenarioParameterFabricationError(ScenarioParameterContradictionError):
    """Raised when Claude invents scenario parameters not present in authoritative input."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_PARAMETER_FABRICATION"


class ScenarioProbabilityFabricationError(ScenarioSimulationOutputFabricationError):
    """Raised when Claude fabricates scenario or event probabilities without authoritative calculation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_PROBABILITY_FABRICATION"


class ScenarioCostFabricationError(ScenarioSimulationOutputFabricationError):
    """Raised when Claude invents financial loss or cost values not present in authoritative scenario."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_COST_FABRICATION"


class ScenarioDurationFabricationError(ScenarioExplanationError):
    """Raised when Claude invents scenario durations not present in authoritative parameters."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_DURATION_FABRICATION",
            details=details,
            retryable=False,
        )


class ScenarioETAFabricationError(ScenarioExplanationError):
    """Raised when Claude invents arrival times or ETAs not present in authoritative prediction/scenario."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_ETA_FABRICATION",
            details=details,
            retryable=False,
        )


class ScenarioInventoryImpactFabricationError(ScenarioSimulationOutputFabricationError):
    """Raised when Claude fabricates stockouts, deficits, or inventory impacts without authoritative simulation."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_INVENTORY_IMPACT_FABRICATION"


class ScenarioCapacityImpactFabricationError(ScenarioSimulationOutputFabricationError):
    """Raised when Claude fabricates capacity constraints, warehouse deficits, or utilization metrics."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_CAPACITY_IMPACT_FABRICATION"


class ScenarioSimulationFabricationError(ScenarioSimulationOutputFabricationError):
    """Raised when Claude references ungrounded simulation results, Monte Carlo runs, or digital twins."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message=message, details=details)
        self.error_code = "SCENARIO_SIMULATION_FABRICATION"


class ScenarioOptimizationFabricationError(ScenarioExplanationError):
    """Raised when Claude claims to have run mathematical optimization, OR-Tools, or route optimization."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_OPTIMIZATION_FABRICATION",
            details=details,
            retryable=False,
        )


class ScenarioEntityFabricationError(ScenarioExplanationError):
    """Raised when Claude claims an entity is affected without evidence or authoritative reference."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            error_code="SCENARIO_ENTITY_FABRICATION",
            details=details,
            retryable=False,
        )

