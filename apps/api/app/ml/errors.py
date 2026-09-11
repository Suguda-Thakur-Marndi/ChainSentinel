"""Strongly typed error hierarchy for the RiskWise ML subsystem.

Security & Safety Rules:
- All exceptions inherit from MLError.
- Sensitive credentials, API keys, and private data must NEVER appear in error messages.
- Specific typed exceptions distinguish validation, leakage, training, registry, and inference errors.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class MLError(Exception):
    """Base exception for all machine learning errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class MLValidationError(MLError):
    """Base exception for ML input and contract validation failures."""
    pass


class DatasetValidationError(MLValidationError):
    """Raised when a dataset fails schema, column, nullability, or format validation."""
    pass


class InsufficientTrainingDataError(DatasetValidationError):
    """Raised when the dataset has fewer rows than the required minimum threshold."""
    pass


class FeatureSchemaError(MLValidationError):
    """Raised when input features violate the expected FeatureSchema."""
    pass


class FeatureEngineeringError(MLError):
    """Raised when a feature transformation or extraction computation fails."""
    pass


class DataLeakageError(MLError):
    """Raised when target or future temporal data leaks into training or inference features."""
    pass


class ModelTrainingError(MLError):
    """Raised when model fitting, hyperparameter optimization, or metric calculation fails."""
    pass


class ModelValidationError(MLError):
    """Raised when a trained model fails evaluation criteria, sanity checks, or produces invalid outputs."""
    pass


class ModelArtifactError(MLError):
    """Raised when model artifact serialization, deserialization, or fingerprint verification fails."""
    pass


class ModelRegistryError(MLError):
    """Raised when model registration, retrieval, or version resolution fails."""
    pass


class ModelInferenceError(MLError):
    """Raised during model execution when input is malformed or prediction computation fails."""
    pass


class PredictionInputError(MLValidationError):
    """Raised when prediction input features are missing, non-finite, or malformed."""
    pass


class PredictionOutputValidationError(MLValidationError):
    """Raised when model output is non-finite, negative, or fails post-prediction validation."""
    pass


class MLTenantIsolationError(MLError):
    """Raised when cross-tenant data, features, or models are accessed or mixed."""
    pass
