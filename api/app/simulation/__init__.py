"""RiskWise 2.0 Simulation Engine (Phase 13).

Provides deterministic what-if supply chain simulation, graph effect propagation,
scenario comparison, and read-only risk/ML enrichment on top of the Phase 12 Digital Twin.
"""
from __future__ import annotations

from app.simulation.config import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_EFFECTS,
    DEFAULT_MAX_NODES,
    HARD_MAX_DEPTH,
    HARD_MAX_EDGES,
    HARD_MAX_EFFECTS,
    HARD_MAX_NODES,
    MAX_SCENARIO_CHANGES,
    SIMULATION_ENGINE_VERSION,
    SOURCE_TYPE_SIMULATED,
    SimulationConfig,
)
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationComparison,
    SimulationEffect,
    SimulationEntityImpact,
    SimulationErrorContract,
    SimulationImpact,
    SimulationInput,
    SimulationMetric,
    SimulationOutcome,
    SimulationPropagation,
    SimulationProvenance,
    SimulationRequest,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
    SimulationSummary,
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
from app.simulation.integration import (
    SimulationMLIntegration,
    SimulationRiskIntegration,
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
    "SimulationEntityImpact",
    "SimulationPropagation",
    "SimulationMetric",
    "SimulationOutcome",
    "SimulationImpact",
    "SimulationSummary",
    "SimulationInput",
    "SimulationRequest",
    "SimulationResult",
    "SimulationComparison",
    "SimulationErrorContract",
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
    # Configuration
    "SimulationConfig",
    "MAX_SCENARIO_CHANGES",
    "HARD_MAX_DEPTH",
    "HARD_MAX_NODES",
    "HARD_MAX_EDGES",
    "HARD_MAX_EFFECTS",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_EDGES",
    "DEFAULT_MAX_EFFECTS",
    "SOURCE_TYPE_SIMULATED",
    "SIMULATION_ENGINE_VERSION",
    # Integrations
    "SimulationRiskIntegration",
    "SimulationMLIntegration",
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
