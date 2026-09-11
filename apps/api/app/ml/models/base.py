"""Abstract base model contract for all RiskWise ML prediction models."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Optional
import numpy as np

from app.ml.contracts import MLModelMetadata
from app.ml.errors import ModelInferenceError, PredictionOutputValidationError


class BasePredictionModel(ABC):
    """Provider-independent abstraction for all machine learning models."""

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> "BasePredictionModel":
        """Fit the underlying estimator on training feature matrix and target vector."""
        raise NotImplementedError

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Generate predictions for a 2D feature matrix."""
        raise NotImplementedError

    @abstractmethod
    def predict_single(self, x: np.ndarray) -> float:
        """Generate a validated scalar prediction for a single feature vector."""
        raise NotImplementedError

    @abstractmethod
    def get_metadata(self) -> MLModelMetadata:
        """Retrieve the immutable MLModelMetadata describing this model."""
        raise NotImplementedError

    @property
    @abstractmethod
    def is_fitted(self) -> bool:
        """Whether the model is fitted and ready for inference."""
        raise NotImplementedError

    def validate_prediction(self, value: float) -> float:
        """Validate that a single prediction output is finite and non-negative."""
        try:
            val = float(value)
        except (ValueError, TypeError) as exc:
            raise PredictionOutputValidationError(f"Model returned non-numeric prediction: {value}") from exc

        if math.isnan(val) or math.isinf(val):
            raise PredictionOutputValidationError(f"Model returned non-finite prediction: {val}")

        # Post-prediction physical constraint: delays cannot be negative
        return max(0.0, val)
