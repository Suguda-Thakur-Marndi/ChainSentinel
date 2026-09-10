"""Public interface for the RiskWise Scenario Agent (Phase 9 Step 7).

Exports strongly typed scenario contracts, deterministic generator, orchestration agent,
LangGraph execution node, and typed exceptions.
"""

from __future__ import annotations

from app.agents.scenario.agent import ScenarioAgent
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
    ScenarioGenerationError,
    ScenarioTenantIsolationError,
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
    # Errors
    "ScenarioAgentError",
    "InvalidScenarioRequestError",
    "ScenarioTenantIsolationError",
    "InvalidScenarioParameterError",
    "UnsupportedScenarioTypeError",
    "InsufficientEvidenceError",
    "ScenarioGenerationError",
    # Generator
    "ScenarioGenerator",
    # Agent
    "ScenarioAgent",
    # Node
    "SCENARIO_NODE_CONTRACT",
    "scenario_node",
]
