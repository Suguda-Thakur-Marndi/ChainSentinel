"""Canonical provider-neutral prediction explanation contract.

Re-exports canonical models and aliases for backwards compatibility.
"""
from app.agents.prediction.claude_contract import (
    FeatureExplanation,
    PredictionExplanation,
    PredictionExplanationResult,
    PredictionExplanationStatus,
    PredictionExplanationInput,
    PredictionFeatureExplanationInput,
    PredictionUncertaintyExplanationInput,
    ModelMetadataExplanationInput,
    compute_prediction_explanation_fingerprint,
    ClaudeFeatureExplanation,
    ClaudePredictionExplanation,
)

__all__ = [
    "FeatureExplanation",
    "PredictionExplanation",
    "PredictionExplanationResult",
    "PredictionExplanationStatus",
    "PredictionExplanationInput",
    "PredictionFeatureExplanationInput",
    "PredictionUncertaintyExplanationInput",
    "ModelMetadataExplanationInput",
    "compute_prediction_explanation_fingerprint",
    "ClaudeFeatureExplanation",
    "ClaudePredictionExplanation",
]
