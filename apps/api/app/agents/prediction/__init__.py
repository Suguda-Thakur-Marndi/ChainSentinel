"""Prediction Agent package for RiskWise 2.0 (Phase 9 Step 6).

Provides:
- prediction_node, PREDICTION_NODE_CONTRACT
- PredictionAgent
- PredictionRequest, PredictionResult, PredictionFeature, PredictionUncertainty, ModelMetadata
- BasePredictionService, UnavailablePredictionService, DeterministicMockPredictionService
- PredictionType, PredictionStatus
- generate_deterministic_prediction_id
- PredictionAgentError, FeatureValidationError, InvalidPredictionRequestError, etc.
"""

from app.agents.prediction.adapter import PredictionFeatureExtractor
from app.agents.prediction.agent import PredictionAgent
from app.agents.prediction.contract import (
    ModelMetadata,
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
    PredictionUncertainty,
    generate_deterministic_prediction_id,
)
from app.agents.prediction.errors import (
    FeatureValidationError,
    InvalidModelOutputError,
    InvalidPredictionRequestError,
    ModelExecutionError,
    ModelTimeoutError,
    ModelUnavailableError,
    PredictionAgentError,
    PredictionAuthorizationError,
    PredictionTenantIsolationError,
)
from app.agents.prediction.node import PREDICTION_NODE_CONTRACT, prediction_node
from app.agents.prediction.service import (
    BasePredictionService,
    DeterministicMockPredictionService,
    UnavailablePredictionService,
)

__all__ = [
    "prediction_node",
    "PREDICTION_NODE_CONTRACT",
    "PredictionAgent",
    "PredictionFeatureExtractor",
    "PredictionRequest",
    "PredictionResult",
    "PredictionFeature",
    "PredictionUncertainty",
    "ModelMetadata",
    "BasePredictionService",
    "UnavailablePredictionService",
    "DeterministicMockPredictionService",
    "PredictionType",
    "PredictionStatus",
    "generate_deterministic_prediction_id",
    "PredictionAgentError",
    "InvalidPredictionRequestError",
    "PredictionTenantIsolationError",
    "FeatureValidationError",
    "ModelUnavailableError",
    "ModelTimeoutError",
    "ModelExecutionError",
    "InvalidModelOutputError",
    "PredictionAuthorizationError",
]
