"""RiskWise 2.0 Simulation Engine (Phase 13).

Provides deterministic what-if supply chain simulation, graph effect propagation,
and scenario comparison on top of the Phase 12 Digital Twin.
"""
from __future__ import annotations

from app.simulation.contracts import (
    MetricAvailability,
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationComparison,
    SimulationEffect,
    SimulationInput,
    SimulationMetric,
    SimulationOutcome,
    SimulationProvenance,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.engine import SimulationEngine
from app.simulation.errors import (
    SimulationError,
    SimulationPersistenceError,
    SimulationPropagationError,
    SimulationResourceLimitError,
    SimulationStateError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.fingerprints import (
    compute_change_fingerprint,
    compute_change_id,
    compute_effect_id,
    compute_scenario_fingerprint,
    compute_scenario_id,
    compute_simulation_fingerprint,
    compute_simulation_id,
)
from app.simulation.metrics import SimulationMetricsCalculator
from app.simulation.observability import SimulationObservability
from app.simulation.propagation import SimulationPropagationEngine
from app.simulation.repository import SimulationRepository
from app.simulation.scenario import SimulationScenarioBuilder
from app.simulation.service import SimulationService
from app.simulation.state import SimulationState
from app.simulation.validation import SimulationValidator

__all__ = [
    # Contracts
    "SimulationChangeType",
    "SimulationChangeUnit",
    "SimulationStatus",
    "MetricAvailability",
    "SimulationProvenance",
    "SimulationChange",
    "SimulationScenario",
    "SimulationEffect",
    "SimulationMetric",
    "SimulationOutcome",
    "SimulationInput",
    "SimulationResult",
    "SimulationComparison",
    # Errors
    "SimulationError",
    "SimulationValidationError",
    "SimulationTenantIsolationError",
    "SimulationStateError",
    "SimulationPropagationError",
    "SimulationResourceLimitError",
    "SimulationPersistenceError",
    # Fingerprints & IDs
    "compute_scenario_id",
    "compute_change_id",
    "compute_effect_id",
    "compute_simulation_id",
    "compute_change_fingerprint",
    "compute_scenario_fingerprint",
    "compute_simulation_fingerprint",
    # Components
    "SimulationScenarioBuilder",
    "SimulationValidator",
    "SimulationState",
    "SimulationPropagationEngine",
    "SimulationMetricsCalculator",
    "SimulationEngine",
    "SimulationRepository",
    "SimulationService",
    "SimulationObservability",
]
