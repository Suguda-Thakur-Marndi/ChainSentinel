"""Public interface for the RiskWise Decision Agent (Phase 9 Step 8).

Exports strongly typed decision contracts, deterministic rule engine, orchestration agent,
LangGraph execution node, and typed exceptions.
"""

from __future__ import annotations

from app.agents.decision.agent import DecisionAgent
from app.agents.decision.contract import (
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionType,
    compute_decision_fingerprint,
    generate_deterministic_decision_id,
)
from app.agents.decision.errors import (
    DecisionAgentError,
    DecisionAuthorizationError,
    DecisionGenerationError,
    DecisionTenantIsolationError,
    InsufficientEvidenceError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
    InvalidScenarioReferenceError,
    MissingScenarioError,
    UnsupportedDecisionTypeError,
)
from app.agents.decision.node import DECISION_NODE_CONTRACT, decision_node
from app.agents.decision.rules import DecisionRuleEngine, RULE_VERSION

DECISION_RULE_VERSION = RULE_VERSION

__all__ = [
    # Contracts
    "DecisionType",
    "DecisionStatus",
    "DecisionCandidateStatus",
    "DecisionBasis",
    "DecisionConstraint",
    "DecisionCandidate",
    "DecisionRationale",
    "DecisionRequest",
    "DecisionResult",
    "generate_deterministic_decision_id",
    "compute_decision_fingerprint",
    # Rule Engine
    "DecisionRuleEngine",
    "RULE_VERSION",
    "DECISION_RULE_VERSION",
    # Agent
    "DecisionAgent",
    # Node
    "DECISION_NODE_CONTRACT",
    "decision_node",
    # Errors
    "DecisionAgentError",
    "InvalidDecisionRequestError",
    "DecisionTenantIsolationError",
    "MissingScenarioError",
    "InvalidScenarioReferenceError",
    "InvalidDecisionCandidateError",
    "InsufficientEvidenceError",
    "UnsupportedDecisionTypeError",
    "DecisionGenerationError",
    "DecisionAuthorizationError",
]
