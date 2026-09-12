"""RiskWise Optimization Subsystem (Phase 14).

Production-grade, deterministic mathematical optimization powered by Google OR-Tools.
Enforces:
- Mathematical feasibility and optimality verification
- Strict data non-fabrication guarantees (costs, capacities, transit times)
- Multi-tenant isolation at all boundaries
- Read-only integration with Digital Twin, Simulation, Risk Engine, and ML
- Strict boundary separation from Phase 15 Decision Agent
"""
from app.optimization.config import (
    DEFAULT_SOLVER_TIMEOUT_SECONDS,
    HARD_MAX_CANDIDATES,
    HARD_MAX_CONSTRAINTS,
    HARD_MAX_OBJECTIVE_TERMS,
    HARD_MAX_SOLVER_TIME_SECONDS,
    HARD_MAX_VARIABLES,
    OPTIMIZATION_ENGINE_VERSION,
)
from app.optimization.contracts import (
    ConstraintType,
    ObjectiveDirection,
    OptimizationAlternative,
    OptimizationConstraint,
    OptimizationDomain,
    OptimizationErrorContract,
    OptimizationMetric,
    OptimizationMetricAvailability,
    OptimizationObjective,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationProvenance,
    OptimizationRequest,
    OptimizationResult,
    OptimizationSolverConfig,
    OptimizationStatus,
    OptimizationSummary,
    OptimizationVariable,
    SelectedAlternative,
    VariableType,
)
from app.optimization.errors import (
    OptimizationDataMissingError,
    OptimizationError,
    OptimizationExecutionError,
    OptimizationInfeasibleError,
    OptimizationResourceLimitError,
    OptimizationSolverUnavailableError,
    OptimizationTenantIsolationError,
    OptimizationValidationError,
)
from app.optimization.service import OptimizationService

__all__ = [
    # Config
    "OPTIMIZATION_ENGINE_VERSION",
    "HARD_MAX_VARIABLES",
    "HARD_MAX_CANDIDATES",
    "HARD_MAX_CONSTRAINTS",
    "HARD_MAX_OBJECTIVE_TERMS",
    "HARD_MAX_SOLVER_TIME_SECONDS",
    "DEFAULT_SOLVER_TIMEOUT_SECONDS",
    # Contracts & Enums
    "OptimizationStatus",
    "OptimizationDomain",
    "OptimizationObjectiveType",
    "ObjectiveDirection",
    "ConstraintType",
    "VariableType",
    "OptimizationMetricAvailability",
    "OptimizationSolverConfig",
    "OptimizationVariable",
    "OptimizationConstraint",
    "OptimizationObjective",
    "OptimizationAlternative",
    "OptimizationMetric",
    "OptimizationProvenance",
    "OptimizationProblem",
    "OptimizationRequest",
    "SelectedAlternative",
    "OptimizationSummary",
    "OptimizationResult",
    "OptimizationErrorContract",
    # Errors
    "OptimizationError",
    "OptimizationValidationError",
    "OptimizationTenantIsolationError",
    "OptimizationResourceLimitError",
    "OptimizationDataMissingError",
    "OptimizationSolverUnavailableError",
    "OptimizationInfeasibleError",
    "OptimizationExecutionError",
    # Service
    "OptimizationService",
]
