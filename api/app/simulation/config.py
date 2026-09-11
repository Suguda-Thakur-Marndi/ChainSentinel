"""Configuration and hard safety limits for RiskWise Simulation Engine (Phase 13)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Resource and execution safety bounds to prevent unbounded graph explosion
MAX_SCENARIO_CHANGES: int = 50
HARD_MAX_DEPTH: int = 10
HARD_MAX_NODES: int = 1000
HARD_MAX_EDGES: int = 2000
HARD_MAX_EFFECTS: int = 500

DEFAULT_MAX_DEPTH: int = 5
DEFAULT_MAX_NODES: int = 200
DEFAULT_MAX_EDGES: int = 500
DEFAULT_MAX_EFFECTS: int = 100

DEFAULT_SIMULATION_TIMEOUT_SECONDS: float = 30.0
SOURCE_TYPE_SIMULATED: str = "SIMULATED"
SIMULATION_ENGINE_VERSION: str = "13.0.0"


@dataclass(frozen=True)
class SimulationConfig:
    """Immutable operational configuration for a simulation run."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int = DEFAULT_MAX_NODES
    max_edges: int = DEFAULT_MAX_EDGES
    max_effects: int = DEFAULT_MAX_EFFECTS
    max_scenario_changes: int = MAX_SCENARIO_CHANGES
    timeout_seconds: float = DEFAULT_SIMULATION_TIMEOUT_SECONDS
    engine_version: str = SIMULATION_ENGINE_VERSION
    source_type: str = SOURCE_TYPE_SIMULATED
    evaluate_risk: bool = True
    evaluate_ml: bool = False
