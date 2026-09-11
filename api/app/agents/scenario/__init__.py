"""Public interface for the RiskWise Scenario Agent (Phase 9 Step 7).

Exports strongly typed scenario contracts, deterministic generator, orchestration agent,
LangGraph execution node, and typed exceptions.
"""

from __future__ import annotations

from app.agents.scenario.agent import ScenarioAgent
from app.agents.scenario.claude_contract import (
    ClaudeAssumptionExplanation,
    ClaudeScenarioExplanation,
    ClaudeScenarioParameterExplanation,
    ScenarioConstraintExplanationInput,
    ScenarioExplanationInput,
    ScenarioExplanationResult,
    ScenarioExplanationStatus,
    ScenarioParameterExplanationInput,
    ScenarioTriggerExplanationInput,
    compute_scenario_explanation_fingerprint,
)
from app.agents.scenario.claude_service import ClaudeScenarioExplanationService
from app.agents.scenario.contract import (
    ScenarioConstraint,
    ScenarioDefinition,
    ScenarioParameter,
    ScenarioRequest,
    ScenarioResult,
    ScenarioStatus,
    ScenarioTrigger,
    ScenarioType,
    compute_scenario_fingerprint,
    generate_deterministic_scenario_id,
)
from app.agents.scenario.errors import (
    InsufficientEvidenceError,
    InvalidScenarioParameterError,
    InvalidScenarioRequestError,
    ScenarioAgentError,
    ScenarioCapacityImpactFabricationError,
    ScenarioCostFabricationError,
    ScenarioDurationFabricationError,
    ScenarioEntityFabricationError,
    ScenarioETAFabricationError,
    ScenarioExplanationCitationIntegrityError,
    ScenarioExplanationError,
    ScenarioExplanationGroundingError,
    ScenarioExplanationLLMError,
    ScenarioGenerationError,
    ScenarioInventoryImpactFabricationError,
    ScenarioOptimizationFabricationError,
    ScenarioParameterContradictionError,
    ScenarioParameterFabricationError,
    ScenarioProbabilityFabricationError,
    ScenarioSimulationFabricationError,
    ScenarioSimulationOutputFabricationError,
    ScenarioStatusContradictionError,
    ScenarioTenantIsolationError,
    ScenarioTypeContradictionError,
    ScenarioValueContradictionError,
    UnsupportedScenarioTypeError,
)
from app.agents.scenario.generator import ScenarioGenerator
from app.agents.scenario.node import SCENARIO_NODE_CONTRACT, scenario_node

__all__ = [
    # Contracts
    "ScenarioType",
    "ScenarioStatus",
    "ScenarioParameter",
    "ScenarioTrigger",
    "ScenarioConstraint",
    "ScenarioDefinition",
    "ScenarioRequest",
    "ScenarioResult",
    "generate_deterministic_scenario_id",
    "compute_scenario_fingerprint",
    # Claude Explanation Contracts
    "ScenarioExplanationStatus",
    "ScenarioParameterExplanationInput",
    "ScenarioTriggerExplanationInput",
    "ScenarioConstraintExplanationInput",
    "ScenarioExplanationInput",
    "ClaudeScenarioParameterExplanation",
    "ClaudeAssumptionExplanation",
    "ClaudeScenarioExplanation",
    "ScenarioExplanationResult",
    "compute_scenario_explanation_fingerprint",
    # Claude Explanation Service
    "ClaudeScenarioExplanationService",
    # Errors
    "ScenarioAgentError",
    "InvalidScenarioRequestError",
    "ScenarioTenantIsolationError",
    "InvalidScenarioParameterError",
    "UnsupportedScenarioTypeError",
    "InsufficientEvidenceError",
    "ScenarioGenerationError",
    "ScenarioExplanationError",
    "ScenarioTypeContradictionError",
    "ScenarioParameterContradictionError",
    "ScenarioValueContradictionError",
    "ScenarioStatusContradictionError",
    "ScenarioParameterFabricationError",
    "ScenarioProbabilityFabricationError",
    "ScenarioCostFabricationError",
    "ScenarioDurationFabricationError",
    "ScenarioETAFabricationError",
    "ScenarioInventoryImpactFabricationError",
    "ScenarioCapacityImpactFabricationError",
    "ScenarioSimulationFabricationError",
    "ScenarioSimulationOutputFabricationError",
    "ScenarioOptimizationFabricationError",
    "ScenarioEntityFabricationError",
    "ScenarioExplanationCitationIntegrityError",
    "ScenarioExplanationGroundingError",
    "ScenarioExplanationLLMError",
    # Generator
    "ScenarioGenerator",
    # Agent
    "ScenarioAgent",
    # Node
    "SCENARIO_NODE_CONTRACT",
    "scenario_node",
]

