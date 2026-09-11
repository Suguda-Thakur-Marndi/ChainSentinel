"""Shipment delay prediction model implementation.

Utilizes a reproducible, regularized regression baseline with strict non-negative output
constraints, exact evaluation metrics, and deterministic metadata generation.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score

from app.ml.contracts import (
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
)
from app.ml.errors import ModelInferenceError, ModelTrainingError, ModelValidationError
from app.ml.models.base import BasePredictionModel


class ShipmentDelayModel(BasePredictionModel):
    """Deterministic linear regression baseline for shipment delay minutes."""

    def __init__(
        self,
        model_id: str = "shipment_delay_ridge_v1",
        model_version: str = "1.0.0",
        alpha: float = 1.0,
        random_seed: int = 42,
        organization_id: Optional[str] = None,
    ) -> None:
        self._model_id = model_id
        self._model_version = model_version
        self._alpha = alpha
        self._random_seed = random_seed
        self._organization_id = organization_id
        self._estimator = Ridge(alpha=alpha, random_state=random_seed)
        self._is_fitted = False
        self._metadata: Optional[MLModelMetadata] = None

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def get_metadata(self) -> MLModelMetadata:
        if self._metadata is None:
            raise ModelValidationError("Model metadata requested before model was trained.")
        return self._metadata

    def set_metadata(self, metadata: MLModelMetadata) -> None:
        self._metadata = metadata

    def fit(self, X: np.ndarray, y: np.ndarray) -> "ShipmentDelayModel":
        """Fit estimator on training feature matrix and delay targets."""
        if X.shape[0] == 0 or y.shape[0] == 0:
            raise ModelTrainingError("Cannot fit model on 0 training rows.")
        if X.shape[0] != y.shape[0]:
            raise ModelTrainingError(f"Row count mismatch between X ({X.shape[0]}) and y ({y.shape[0]}).")

        # Validate non-finite inputs
        if not np.all(np.isfinite(X)):
            raise ModelTrainingError("Training feature matrix contains NaN or Inf.")
        if not np.all(np.isfinite(y)):
            raise ModelTrainingError("Training target vector contains NaN or Inf.")

        try:
            self._estimator.fit(X, y)
            self._is_fitted = True
        except Exception as exc:
            raise ModelTrainingError(f"Failed to fit Ridge estimator: {exc}") from exc

        return self

    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> ModelMetrics:
        """Evaluate model on held-out test data and compute exact metrics without fabrication."""
        if not self._is_fitted:
            raise ModelValidationError("Cannot evaluate an unfitted model.")
        if X_test.shape[0] == 0 or y_test.shape[0] == 0:
            return ModelMetrics(is_calculated=False)

        preds = self.predict(X_test)
        mae = float(mean_absolute_error(y_test, preds))
        rmse = float(root_mean_squared_error(y_test, preds))
        r2 = float(r2_score(y_test, preds)) if len(y_test) > 1 else None

        return ModelMetrics(
            mae=round(mae, 4),
            rmse=round(rmse, 4),
            r2=round(r2, 4) if r2 is not None else None,
            sample_count=len(y_test),
            is_calculated=True,
        )

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Generate validated batch predictions clipped to non-negative delays."""
        if not self._is_fitted:
            raise ModelInferenceError("Cannot predict with an unfitted model.")
        if X.shape[0] == 0:
            return np.empty((0,), dtype=np.float64)

        if not np.all(np.isfinite(X)):
            raise ModelInferenceError("Inference feature matrix contains NaN or Inf.")

        raw_preds = self._estimator.predict(X)
        # Apply physical constraint: shipment delays cannot be negative
        clipped = np.maximum(0.0, raw_preds)
        return clipped

    def predict_single(self, x: np.ndarray) -> float:
        """Generate and validate a single prediction value."""
        if x.ndim == 1:
            x = x.reshape(1, -1)
        preds = self.predict(x)
        return self.validate_prediction(float(preds[0]))
