"""Model validation and qualification checks before registration."""

from __future__ import annotations

import math
import numpy as np

from app.ml.contracts import ModelMetrics
from app.ml.errors import ModelValidationError
from app.ml.models.base import BasePredictionModel


class ModelValidator:
    """Validates that a trained model satisfies all mathematical, sanity, and determinism criteria."""

    @classmethod
    def validate_model(
        cls,
        model: BasePredictionModel,
        X_test: np.ndarray,
        y_test: np.ndarray,
        metrics: ModelMetrics,
    ) -> None:
        """Perform comprehensive model sanity and validation checks."""
        if not model.is_fitted:
            raise ModelValidationError("Model must be fitted to pass validation.")

        if not metrics.is_calculated or metrics.mae is None or metrics.rmse is None:
            raise ModelValidationError("Model metrics must be calculated with non-None MAE and RMSE.")

        if math.isnan(metrics.mae) or metrics.mae < 0.0:
            raise ModelValidationError(f"Invalid MAE metric: {metrics.mae}")

        if math.isnan(metrics.rmse) or metrics.rmse < 0.0:
            raise ModelValidationError(f"Invalid RMSE metric: {metrics.rmse}")

        # Predict on test set
        preds = model.predict(X_test)
        if preds.shape[0] != X_test.shape[0]:
            raise ModelValidationError(f"Prediction output count {preds.shape[0]} does not match input count {X_test.shape[0]}.")

        if not np.all(np.isfinite(preds)):
            raise ModelValidationError("Model produced non-finite predictions during validation.")

        if np.any(preds < 0.0):
            raise ModelValidationError("Model produced negative predictions, violating shipment delay domain constraints.")

        # Determinism check: repeated prediction on identical input must yield identical output
        preds_second = model.predict(X_test)
        if not np.allclose(preds, preds_second, rtol=1e-5, atol=1e-8):
            raise ModelValidationError("Model inference is non-deterministic on identical input.")
