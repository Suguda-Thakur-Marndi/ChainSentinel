"""Strongly typed Pydantic contracts for RiskWise Simulation Engine (Phase 13).

Provides deterministic, immutable, and strictly validated data structures for:
- Hypothetical scenario changes (Node/Edge outages, Delays, Capacity adjustments)
- Explainable effect propagation
- Metric calculation & comparisons
- Entity-level impact tracking
- Provenance and audit tracking
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SimulationChangeType(str, Enum):
    """Supported deterministic change types for what-if scenarios."""

    NODE_UNAVAILABLE = "NODE_UNAVAILABLE"
    EDGE_UNAVAILABLE = "EDGE_UNAVAILABLE"
    DELAY = "DELAY"
    DELAY_INCREASE = "DELAY_INCREASE"
    CAPACITY_REDUCTION = "CAPACITY_REDUCTION"
    CAPACITY_INCREASE = "CAPACITY_INCREASE"
    TRANSIT_TIME_INCREASE = "TRANSIT_TIME_INCREASE"
    DEMAND_CHANGE = "DEMAND_CHANGE"
    INVENTORY_CHANGE = "INVENTORY_CHANGE"


class SimulationChangeUnit(str, Enum):
    """Standardized physical and operational units for change magnitude."""

    MINUTES = "MINUTES"
    HOURS = "HOURS"
    DAYS = "DAYS"
    PERCENT = "PERCENT"
    UNITS = "UNITS"
    CURRENCY = "CURRENCY"
    RATIO = "RATIO"
    BOOLEAN = "BOOLEAN"


class SimulationStatus(str, Enum):
    """Lifecycle execution status of a simulation."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MetricAvailability(str, Enum):
    """Explicit indicator of whether metric data is authoritative or missing."""

    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    ESTIMATED = "ESTIMATED"


class SimulationProvenance(BaseModel):
    """Audit metadata tracking the lineage of a scenario and simulation execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_snapshot_fingerprint: str = Field(..., min_length=64, max_length=64)
    base_snapshot_id: Optional[str] = Field(None, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    source_system: str = Field(default="DIGITAL_TWIN_SNAPSHOT", max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SimulationChange(BaseModel):
    """Strongly typed declaration of a hypothetical operational change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    change_id: str = Field(..., min_length=1, max_length=64, description="Deterministic or assigned ID")
    change_type: SimulationChangeType
    target_entity_type: str = Field(..., min_length=1, max_length=64, description="E.g. PORT, FACTORY, ROUTE, SHIPMENT")
    target_entity_id: str = Field(..., min_length=1, max_length=64, description="Node ID, Edge ID, or operational entity ID")
    magnitude: float = Field(..., description="Numerical value of the change (e.g. 72.0 hours, 30.0 percent)")
    unit: SimulationChangeUnit
    duration_minutes: Optional[float] = Field(None, ge=0.0, description="Duration of the outage/change in minutes")
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=500)
    source_type: str = Field(default="SIMULATED", pattern="^SIMULATED$")


class SimulationScenario(BaseModel):
    """Definition of a what-if supply chain scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    base_snapshot_fingerprint: str = Field(..., min_length=64, max_length=64)
    changes: List[SimulationChange] = Field(default_factory=list, max_length=50)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    fingerprint: str = Field(..., min_length=64, max_length=64)


class SimulationEffect(BaseModel):
    """Explainable operational effect resulting from hypothetical change propagation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect_id: str = Field(..., min_length=1, max_length=64)
    originating_change_id: str = Field(..., min_length=1, max_length=64)
    affected_entity_id: str = Field(..., min_length=1, max_length=64)
    affected_entity_type: str = Field(..., min_length=1, max_length=64)
    effect_type: str = Field(..., min_length=1, max_length=64, description="E.g. DELAY, CAPACITY_BOTTLENECK, STOCKOUT_RISK")
    magnitude: Optional[float] = None
    unit: Optional[SimulationChangeUnit] = None
    propagation_path: List[str] = Field(default_factory=list, description="Sequence of node/edge IDs in the propagation chain")
    rule_applied: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    is_simulated: bool = True


class SimulationEntityImpact(BaseModel):
    """Detailed operational impact evaluated on a single supply chain entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(..., min_length=1, max_length=64)
    entity_type: str = Field(..., min_length=1, max_length=64)
    impact_type: str = Field(..., min_length=1, max_length=64)
    is_direct: bool = Field(default=False)
    effective_delay_minutes: float = Field(default=0.0, ge=0.0)
    capacity_lost: Optional[float] = None
    is_available: bool = True
    propagation_depth: int = Field(default=0, ge=0)
    simulated_tags: List[str] = Field(default_factory=list)


class SimulationPropagation(BaseModel):
    """Deterministic graph propagation summary and execution trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    origin_nodes: List[str] = Field(default_factory=list)
    max_depth_reached: int = Field(default=0, ge=0)
    nodes_visited_count: int = Field(default=0, ge=0)
    edges_traversed_count: int = Field(default=0, ge=0)
    effects_generated_count: int = Field(default=0, ge=0)
    propagation_paths: List[List[str]] = Field(default_factory=list)


class SimulationMetric(BaseModel):
    """Standardized comparative metric representing baseline vs simulated state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_name: str = Field(..., min_length=1, max_length=100)
    baseline_value: Optional[float] = None
    simulated_value: Optional[float] = None
    delta: Optional[float] = None
    unit: str = Field(..., min_length=1, max_length=50)
    availability: MetricAvailability = MetricAvailability.AVAILABLE


class SimulationOutcome(BaseModel):
    """High-level aggregated summary of scenario simulation results."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    affected_nodes_count: int = Field(default=0, ge=0)
    affected_edges_count: int = Field(default=0, ge=0)
    affected_shipments_count: int = Field(default=0, ge=0)
    affected_warehouses_count: int = Field(default=0, ge=0)
    affected_suppliers_count: int = Field(default=0, ge=0)
    affected_factories_count: int = Field(default=0, ge=0)
    total_added_delay_minutes: float = Field(default=0.0, ge=0.0)
    average_delay_minutes: Optional[float] = None
    maximum_delay_minutes: Optional[float] = None
    unavailable_capacity_units: Optional[float] = None
    inventory_exposure_units: Optional[float] = None
    baseline_risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    simulated_risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    risk_delta: Optional[float] = None
    severity: str = Field(default="LOW", max_length=50)


# SimulationImpact contract alias/equivalent for SimulationOutcome
SimulationImpact = SimulationOutcome


class SimulationSummary(BaseModel):
    """Compact summary of an executed simulation run for reporting and audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    simulation_id: str = Field(..., min_length=1, max_length=64)
    scenario_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    status: SimulationStatus
    severity: str = Field(default="LOW", max_length=50)
    affected_nodes_count: int = Field(default=0, ge=0)
    affected_edges_count: int = Field(default=0, ge=0)
    affected_shipments_count: int = Field(default=0, ge=0)
    total_added_delay_minutes: float = Field(default=0.0, ge=0.0)
    risk_delta: Optional[float] = None
    execution_duration_ms: float = Field(default=0.0, ge=0.0)
    simulation_fingerprint: str = Field(..., min_length=64, max_length=64)


class SimulationInput(BaseModel):
    """Execution input payload to trigger scenario simulation."""

    model_config = ConfigDict(extra="forbid")

    scenario: Optional[SimulationScenario] = None
    scenario_id: Optional[str] = Field(None, max_length=64)
    max_depth: int = Field(default=5, ge=1, le=10)
    max_nodes: int = Field(default=200, ge=1, le=1000)
    max_edges: int = Field(default=500, ge=1, le=2000)
    max_effects: int = Field(default=100, ge=1, le=500)
    evaluate_risk: bool = True
    evaluate_ml: bool = False


# SimulationRequest alias and contract
class SimulationRequest(BaseModel):
    """Execution request specification for what-if scenario simulations."""

    model_config = ConfigDict(extra="forbid")

    scenario: Optional[SimulationScenario] = None
    scenario_id: Optional[str] = Field(None, max_length=64)
    max_depth: int = Field(default=5, ge=1, le=10)
    max_nodes: int = Field(default=200, ge=1, le=1000)
    max_edges: int = Field(default=500, ge=1, le=2000)
    max_effects: int = Field(default=100, ge=1, le=500)
    evaluate_risk: bool = True
    evaluate_ml: bool = False


class SimulationResult(BaseModel):
    """Authoritative output of an executed what-if simulation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    simulation_id: str = Field(..., min_length=1, max_length=64)
    scenario_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    base_snapshot_fingerprint: str = Field(..., min_length=64, max_length=64)
    simulation_fingerprint: str = Field(..., min_length=64, max_length=64)
    status: SimulationStatus
    outcome: SimulationOutcome
    impact: Optional[SimulationImpact] = None
    summary: Optional[SimulationSummary] = None
    changes: List[SimulationChange] = Field(default_factory=list)
    effects: List[SimulationEffect] = Field(default_factory=list)
    entity_impacts: List[SimulationEntityImpact] = Field(default_factory=list)
    propagation: Optional[SimulationPropagation] = None
    metrics: Dict[str, SimulationMetric] = Field(default_factory=dict)
    provenance: SimulationProvenance
    executed_at: datetime = Field(default_factory=datetime.utcnow)
    execution_duration_ms: float = Field(default=0.0, ge=0.0)


class SimulationComparison(BaseModel):
    """Deterministic comparison between two scenario outcomes or baseline vs scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: str
    scenario_a_id: str
    scenario_b_id: str
    metric_comparisons: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    summary_findings: List[str] = Field(default_factory=list)


class SimulationErrorContract(BaseModel):
    """Typed serializable error representation for audit and API responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_code: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)
