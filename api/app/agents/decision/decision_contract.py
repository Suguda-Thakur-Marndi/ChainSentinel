"""Canonical provider-neutral decision explanation contract.

Re-exports canonical models and aliases for backwards compatibility.
"""
from app.agents.decision.claude_contract import (
    CandidateTradeoff,
    DecisionExplanation,
    DecisionExplanationResult,
    DecisionExplanationStatus,
    DecisionExplanationInput,
    compute_decision_explanation_fingerprint,
    ClaudeCandidateTradeoff,
    ClaudeDecisionExplanation,
)

__all__ = [
    "CandidateTradeoff",
    "DecisionExplanation",
    "DecisionExplanationResult",
    "DecisionExplanationStatus",
    "DecisionExplanationInput",
    "compute_decision_explanation_fingerprint",
    "ClaudeCandidateTradeoff",
    "ClaudeDecisionExplanation",
]
