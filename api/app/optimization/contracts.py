"""Strongly typed Pydantic contracts for RiskWise Optimization Subsystem (Phase 14).

Enforces:
- Pydantic V2 strict validation (extra="forbid")
- Immutability for results and provenance (frozen=True)
- Deterministic, bounded mathematical problem representations
- Explicit, non-fabricated metrics and alternatives
- Strict separation from downstream Decision Agent (Phase 15)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class OptimizationStatus(str, Enum):
    """Mathematical solver execution status."""

    OPTIMAL = "OPTIMAL"          # Solver proved optimality
    FEASIBLE = "FEASIBLE"        # Valid feasible solution found, optimality not proven
    INFEASIBLE = "INFEASIBLE"    # No feasible solution exists under given constraints
    UNBOUNDED = "UNBOUNDED"      # Mathematical model is unbounded
    TIME_LIMIT = "TIME_LIMIT"    # Solver reached configured time limit
    NOT_AVAILABLE = "NOT_AVAILABLE"  # Solver, data, or dependency unavailable
    FAILED = "FAILED"            # Unexpected solver failure


class OptimizationDomain(str, Enum):
    """Supported supply chain mathematical optimization domains."""

    SHIPMENT_REROUTE = "SHIPMENT_REROUTE"
    ROUTE_SELECTION = "ROUTE_SELECTION"
    CARRIER_ALLOCATION = "CARRIER_ALLOCATION"
    FACILITY_ALLOCATION = "FACILITY_ALLOCATION"


class OptimizationObjectiveType(str, Enum):
    """Explicit objective function types."""

    MINIMIZE_DELAY = "MINIMIZE_DELAY"
    MINIMIZE_COST = "MINIMIZE_COST"
    MINIMIZE_RISK = "MINIMIZE_RISK"
    MINIMIZE_UNMET_DEMAND = "MINIMIZE_UNMET_DEMAND"
    MINIMIZE_ROUTE_DEVIATION = "MINIMIZE_ROUTE_DEVIATION"


class ObjectiveDirection(str, Enum):
    """Mathematical objective optimization direction."""

    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"


class ConstraintType(str, Enum):
    """Classification of mathematical constraint enforcement."""

    HARD = "HARD"  # Must never be violated; violation implies infeasibility
    SOFT = "SOFT"  # Penalized in the objective if violated


class VariableType(str, Enum):
    """Mathematical variable domain type."""

    BINARY = "BINARY"
    INTEGER = "INTEGER"
    CONTINUOUS = "CONTINUOUS"


class OptimizationMetricAvailability(str, Enum):
    """Explicit indicator of whether metric data is authoritative or missing."""

    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    ESTIMATED = "ESTIMATED"


class OptimizationSolverConfig(BaseModel):
    """Configurable solver execution parameters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    solver_backend: str = Field(default="CBC", max_length=32)
    time_limit_seconds: float = Field(default=10.0, ge=0.1, le=30.0)
    relative_gap_tolerance: float = Field(default=1e-4, ge=0.0, le=1.0)
    num_threads: int = Field(default=1, ge=1, le=16)


class OptimizationVariable(BaseModel):
    """Strongly typed mathematical decision variable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    variable_id: str = Field(..., min_length=1, max_length=128, description="Deterministic identifier")
    variable_type: VariableType = Field(default=VariableType.BINARY)
    domain: OptimizationDomain
    lower_bound: float = Field(default=0.0)
    upper_bound: float = Field(default=1.0)
    source_entity_type: str = Field(..., min_length=1, max_length=64)
    source_entity_id: str = Field(..., min_length=1, max_length=64)
    target_entity_type: Optional[str] = Field(default=None, max_length=64)
    target_entity_id: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = Field(default=None, max_length=255)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OptimizationConstraint(BaseModel):
    """Strongly typed mathematical constraint definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    constraint_id: str = Field(..., min_length=1, max_length=128, description="Deterministic identifier")
    constraint_type: ConstraintType = Field(default=ConstraintType.HARD)
    description: str = Field(..., min_length=1, max_length=255)
    variable_coefficients: Dict[str, float] = Field(
        default_factory=dict,
        description="Mapping of variable_id to numerical coefficient",
    )
    relation: str = Field(..., pattern="^(<=|>=|==)$")
    rhs_value: float = Field(..., description="Right-hand side scalar value")
    penalty_weight: Optional[float] = Field(default=None, ge=0.0, description="Penalty for soft constraints")


class OptimizationObjective(BaseModel):
    """Explicit mathematical objective function formulation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_type: OptimizationObjectiveType
    direction: ObjectiveDirection = Field(default=ObjectiveDirection.MINIMIZE)
    variable_coefficients: Dict[str, float] = Field(
        default_factory=dict,
        description="Linear cost/delay/risk coefficient per variable_id",
    )
    offset: float = Field(default=0.0)
    description: Optional[str] = Field(default=None, max_length=255)


class OptimizationAlternative(BaseModel):
    """Authoritative candidate alternative available for mathematical evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alternative_id: str = Field(..., min_length=1, max_length=128)
    entity_type: str = Field(..., min_length=1, max_length=64, description="E.g. ROUTE, CARRIER, FACILITY")
    entity_id: str = Field(..., min_length=1, max_length=64)
    is_available: bool = Field(default=True)
    capacity: Optional[float] = Field(default=None, ge=0.0)
    cost: Optional[float] = Field(default=None, ge=0.0)
    transit_time_hours: Optional[float] = Field(default=None, ge=0.0)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    properties: Dict[str, Any] = Field(default_factory=dict)
    provenance_reference: Optional[str] = Field(default=None, max_length=255)


class OptimizationMetric(BaseModel):
    """Standardized comparative metric evaluating baseline vs optimized solution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_name: str = Field(..., min_length=1, max_length=100)
    baseline_value: Optional[float] = None
    optimized_value: Optional[float] = None
    delta: Optional[float] = None
    unit: str = Field(..., min_length=1, max_length=50)
    availability: OptimizationMetricAvailability = OptimizationMetricAvailability.AVAILABLE


class OptimizationProvenance(BaseModel):
    """Audit metadata tracking the lineage and reproducible state of an optimization run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: str = Field(..., min_length=1, max_length=64)
    digital_twin_snapshot_fingerprint: str = Field(..., min_length=64, max_length=64)
    digital_twin_snapshot_id: Optional[str] = Field(default=None, max_length=64)
    scenario_id: Optional[str] = Field(default=None, max_length=64)
    simulation_id: Optional[str] = Field(default=None, max_length=64)
    simulation_fingerprint: Optional[str] = Field(default=None, min_length=64, max_length=64)
    engine_version: str = Field(default="2.0.0", max_length=32)
    solver_name: str = Field(default="Google-OR-Tools", max_length=64)
    solver_version: str = Field(default="9.15", max_length=32)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OptimizationProblem(BaseModel):
    """Canonicalized mathematical optimization problem representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    domain: OptimizationDomain
    variables: Dict[str, OptimizationVariable] = Field(default_factory=dict)
    constraints: Dict[str, OptimizationConstraint] = Field(default_factory=dict)
    objective: OptimizationObjective
    candidates: List[OptimizationAlternative] = Field(default_factory=list)
    solver_config: OptimizationSolverConfig = Field(default_factory=OptimizationSolverConfig)
    fingerprint: str = Field(..., min_length=64, max_length=64)


class OptimizationRequest(BaseModel):
    """Strongly typed input payload to trigger mathematical optimization."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(..., min_length=1, max_length=64)
    domain: OptimizationDomain = Field(default=OptimizationDomain.SHIPMENT_REROUTE)
    objective_type: OptimizationObjectiveType = Field(default=OptimizationObjectiveType.MINIMIZE_DELAY)
    digital_twin_snapshot_id: Optional[str] = Field(default=None, max_length=64)
    scenario_id: Optional[str] = Field(default=None, max_length=64)
    simulation_id: Optional[str] = Field(default=None, max_length=64)
    target_entity_ids: List[str] = Field(default_factory=list, max_length=100)
    candidate_alternatives: List[OptimizationAlternative] = Field(default_factory=list, max_length=500)
    solver_config: Optional[OptimizationSolverConfig] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class SelectedAlternative(BaseModel):
    """Mathematically selected candidate alternative from solver variable assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field(..., min_length=1, max_length=64)
    variable_id: str = Field(..., min_length=1, max_length=128)
    assigned_value: float = Field(..., description="Solver assignment value (e.g. 1.0 for binary)")
    associated_shipment_id: Optional[str] = Field(default=None, max_length=64)
    properties: Dict[str, Any] = Field(default_factory=dict)


class OptimizationSummary(BaseModel):
    """High-level summary of optimization solver outcome for audit and reporting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    optimization_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    domain: OptimizationDomain
    status: OptimizationStatus
    objective_type: OptimizationObjectiveType
    objective_value: Optional[float] = None
    selected_alternatives_count: int = Field(default=0, ge=0)
    total_variables: int = Field(default=0, ge=0)
    total_constraints: int = Field(default=0, ge=0)
    solver_wall_time_ms: float = Field(default=0.0, ge=0.0)
    request_fingerprint: str = Field(..., min_length=64, max_length=64)
    result_fingerprint: str = Field(..., min_length=64, max_length=64)


class OptimizationResult(BaseModel):
    """Authoritative output of an executed mathematical optimization run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    optimization_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    domain: OptimizationDomain
    status: OptimizationStatus
    objective: OptimizationObjective
    objective_value: Optional[float] = None
    selected_alternatives: List[SelectedAlternative] = Field(default_factory=list)
    variable_assignments: Dict[str, float] = Field(default_factory=dict)
    constraint_outcomes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    metrics: Dict[str, OptimizationMetric] = Field(default_factory=dict)
    summary: OptimizationSummary
    solver_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance: OptimizationProvenance
    request_fingerprint: str = Field(..., min_length=64, max_length=64)
    result_fingerprint: str = Field(..., min_length=64, max_length=64)
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: float = Field(default=0.0, ge=0.0)
    failure_reason: Optional[str] = Field(default=None, max_length=500)


class OptimizationErrorContract(BaseModel):
    """Typed serializable error representation for audit and API responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_code: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)
