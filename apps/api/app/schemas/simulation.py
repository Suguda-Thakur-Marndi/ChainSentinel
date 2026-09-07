"""Pydantic schemas for scenarios, simulation projections, and prescriptive optimization runs."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class SimulationMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    MONTE_CARLO = "MONTE_CARLO"
    AGENT_BASED = "AGENT_BASED"


class SimulationStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OptimizationObjective(str, Enum):
    MINIMIZE_DELAY_AND_COST = "MINIMIZE_DELAY_AND_COST"
    MINIMIZE_COST = "MINIMIZE_COST"
    MINIMIZE_LEAD_TIME = "MINIMIZE_LEAD_TIME"
    MAXIMIZE_RESILIENCE = "MAXIMIZE_RESILIENCE"


# Scenario
class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    variables_json: dict[str, Any] = Field(default_factory=dict)


class ScenarioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    variables_json: Optional[dict[str, Any]] = None


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    variables_json: dict[str, Any]
    created_by_user_id: Optional[str] = None
    created_at: datetime


class ScenarioListResponse(PaginatedResponse[ScenarioResponse]):
    pass


# Simulation (Execution Run)
class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(..., max_length=64)
    mode: SimulationMode = SimulationMode.DETERMINISTIC
    status: SimulationStatus = SimulationStatus.PENDING
    baseline_metrics: dict[str, Any] = Field(default_factory=dict)
    projected_metrics: dict[str, Any] = Field(default_factory=dict)
    confidence_interval_lower: Optional[float] = None
    confidence_interval_upper: Optional[float] = None


class SimulationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scenario_id: str
    mode: str
    status: str
    baseline_metrics: dict[str, Any]
    projected_metrics: dict[str, Any]
    confidence_interval_lower: Optional[float] = None
    confidence_interval_upper: Optional[float] = None
    executed_at: datetime


class SimulationListResponse(PaginatedResponse[SimulationResponse]):
    pass


# OptimizationRun
class OptimizationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: OptimizationObjective = OptimizationObjective.MINIMIZE_DELAY_AND_COST
    candidate_actions: list[Any] = Field(default_factory=list)
    recommended_plan: dict[str, Any] = Field(default_factory=dict)
    cost_savings_estimate: float = Field(default=0.0, ge=0.0)
    delay_reduction_days: float = Field(default=0.0, ge=0.0)


class OptimizationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    objective: str
    candidate_actions: list[Any]
    recommended_plan: dict[str, Any]
    cost_savings_estimate: float
    delay_reduction_days: float
    created_at: datetime


class OptimizationRunListResponse(PaginatedResponse[OptimizationRunResponse]):
    pass
