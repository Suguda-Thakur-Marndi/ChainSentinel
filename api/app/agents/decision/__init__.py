"""Public interface for the RiskWise Decision Agent (Phase 9 Step 8 & Phase 10 Step 7).

Exports strongly typed decision contracts, deterministic rule engine, orchestration agent,
LangGraph execution node, Claude explanation contracts & service, and typed exceptions.
"""

from __future__ import annotations

from app.agents.decision.agent import DecisionAgent
from app.agents.decision.claude_contract import (
    ClaudeCandidateTradeoff,
    ClaudeDecisionExplanation,
    DecisionCandidateExplanationInput,
    DecisionConstraintExplanationInput,
    DecisionExplanationInput,
    DecisionExplanationResult,
    DecisionExplanationStatus,
    DecisionRationaleExplanationInput,
    compute_decision_explanation_fingerprint,
)
from app.agents.decision.claude_service import (
    ClaudeDecisionExplanationService,
    DECISION_EXPLANATION_PROMPT_VERSION,
    MAX_DECISION_EXPLANATION_CONTEXT_CHARS,
)
from app.agents.decision.contract import (
    AlternativeEvaluation,
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
    DecisionOptimizationSummary,
    DecisionPredictionSummary,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionRiskSummary,
    DecisionScenarioSummary,
    DecisionStatus,
    DecisionType,
    compute_decision_fingerprint,
    generate_deterministic_decision_id,
)
from app.agents.decision.errors import (
    DecisionActionContradictionError,
    DecisionAgentError,
    DecisionApprovalViolationError,
    DecisionAuthorizationError,
    DecisionCandidateContradictionError,
    DecisionExecutionViolationError,
    DecisionExplanationCitationIntegrityError,
    DecisionExplanationError,
    DecisionExplanationGroundingError,
    DecisionExplanationLLMError,
    DecisionFreshnessError,
    DecisionGenerationError,
    DecisionIdempotencyConflictError,
    DecisionInfeasibleError,
    DecisionInputValidationError,
    DecisionOptionFabricationError,
    DecisionOptimizationFabricationError,
    DecisionPolicyError,
    DecisionQuantitativeFabricationError,
    DecisionStatusContradictionError,
    DecisionTenantIsolationError,
    DecisionValueContradictionError,
    InsufficientEvidenceError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
    InvalidScenarioReferenceError,
    MissingScenarioError,
    UnsupportedDecisionTypeError,
)
from app.agents.decision.node import DECISION_NODE_CONTRACT, decision_node
from app.agents.decision.persistence import DecisionRepository
from app.agents.decision.policy import (
    DECISION_POLICY_VERSION,
    DecisionPolicy,
    DecisionPolicyConfig,
)
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
    # Phase 15 Synthesis Models
    "AlternativeEvaluation",
    "DecisionOptimizationSummary",
    "DecisionRiskSummary",
    "DecisionPredictionSummary",
    "DecisionScenarioSummary",
    # Claude Explanation Contracts
    "DecisionExplanationStatus",
    "DecisionCandidateExplanationInput",
    "DecisionConstraintExplanationInput",
    "DecisionRationaleExplanationInput",
    "DecisionExplanationInput",
    "ClaudeCandidateTradeoff",
    "ClaudeDecisionExplanation",
    "DecisionExplanationResult",
    "compute_decision_explanation_fingerprint",
    # Claude Explanation Service
    "ClaudeDecisionExplanationService",
    "DECISION_EXPLANATION_PROMPT_VERSION",
    "MAX_DECISION_EXPLANATION_CONTEXT_CHARS",
    # Rule Engine & Policy
    "DecisionRuleEngine",
    "RULE_VERSION",
    "DECISION_RULE_VERSION",
    "DecisionPolicy",
    "DecisionPolicyConfig",
    "DECISION_POLICY_VERSION",
    # Persistence
    "DecisionRepository",
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
    "DecisionExplanationError",
    "DecisionValueContradictionError",
    "DecisionStatusContradictionError",
    "DecisionActionContradictionError",
    "DecisionCandidateContradictionError",
    "DecisionOptionFabricationError",
    "DecisionApprovalViolationError",
    "DecisionExecutionViolationError",
    "DecisionOptimizationFabricationError",
    "DecisionQuantitativeFabricationError",
    "DecisionExplanationCitationIntegrityError",
    "DecisionExplanationGroundingError",
    "DecisionExplanationLLMError",
    "DecisionPolicyError",
    "DecisionInfeasibleError",
    "DecisionFreshnessError",
    "DecisionIdempotencyConflictError",
    "DecisionInputValidationError",
]

