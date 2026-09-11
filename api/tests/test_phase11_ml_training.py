"""Unit tests for ML model training, evaluation, validation, and pipeline reproducibility."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.config import MLConfig
from app.ml.contracts import ModelMetrics
from app.ml.datasets.builder import ShipmentDatasetBuilder
from app.ml.errors import (
    InsufficientTrainingDataError,
    ModelInferenceError,
    ModelValidationError,
)
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.training.pipeline import ShipmentDelayTrainingPipeline
from app.ml.training.validation import ModelValidator
from tests.test_phase11_ml_dataset import make_sample_rows


class TestShipmentDelayModel:
    def test_model_fit_and_predict(self) -> None:
        rows = make_sample_rows(30)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)
        X = pipeline.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        assert model.is_fitted is False

        model.fit(X, y)
        assert model.is_fitted is True

        preds = model.predict(X)
        assert isinstance(preds, np.ndarray)
        assert len(preds) == 30
        assert np.all(np.isfinite(preds))
        # Delays must be clipped non-negative
        assert np.all(preds >= 0.0)

    def test_predict_before_fit_raises_error(self) -> None:
        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        X = np.zeros((5, 16))
        with pytest.raises(ModelInferenceError) as exc_info:
            model.predict(X)
        assert "Cannot predict with an unfitted model" in str(exc_info.value)

    def test_evaluate_before_fit_raises_error(self) -> None:
        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        X = np.zeros((5, 16))
        y = np.zeros(5)
        with pytest.raises(ModelValidationError) as exc_info:
            model.evaluate(X, y)
        assert "Cannot evaluate an unfitted model" in str(exc_info.value)

    def test_evaluate_returns_real_metrics_without_fabrication(self) -> None:
        rows = make_sample_rows(30)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)
        X = pipeline.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        model.fit(X, y)

        metrics = model.evaluate(X, y)
        assert isinstance(metrics, ModelMetrics)
        assert metrics.is_calculated is True
        assert metrics.sample_count == 30
        assert metrics.mae is not None and metrics.mae >= 0.0
        assert metrics.rmse is not None and metrics.rmse >= 0.0
        assert metrics.r2 is not None

    def test_evaluate_on_empty_test_returns_uncalculated_metrics(self) -> None:
        rows = make_sample_rows(25)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)
        X = pipeline.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        model.fit(X, y)

        empty_X = np.empty((0, 16))
        empty_y = np.empty((0,))
        metrics = model.evaluate(empty_X, empty_y)
        assert metrics.is_calculated is False
        assert metrics.sample_count == 0
        assert metrics.mae is None
        assert metrics.rmse is None

    def test_model_determinism_with_same_seed(self) -> None:
        rows = make_sample_rows(30)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)
        X = pipeline.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        m1 = ShipmentDelayModel(alpha=1.0, random_seed=42)
        m1.fit(X, y)
        preds1 = m1.predict(X)

        m2 = ShipmentDelayModel(alpha=1.0, random_seed=42)
        m2.fit(X, y)
        preds2 = m2.predict(X)

        assert np.allclose(preds1, preds2, rtol=1e-6, atol=1e-9)


class TestModelValidator:
    def test_validator_passes_good_model(self) -> None:
        rows = make_sample_rows(30)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)
        X = pipeline.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        model.fit(X, y)
        metrics = model.evaluate(X, y)

        # Should pass without raising exception
        ModelValidator.validate_model(model, X, y, metrics)

    def test_validator_rejects_unfitted_model(self) -> None:
        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        X = np.zeros((10, 16))
        y = np.zeros(10)
        metrics = ModelMetrics(is_calculated=True, mae=10.0, rmse=15.0)

        with pytest.raises(ModelValidationError) as exc_info:
            ModelValidator.validate_model(model, X, y, metrics)
        assert "Model must be fitted to pass validation" in str(exc_info.value)

    def test_validator_rejects_uncalculated_metrics(self) -> None:
        rows = make_sample_rows(30)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)
        X = pipeline.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        model.fit(X, y)
        bad_metrics = ModelMetrics(is_calculated=False)

        with pytest.raises(ModelValidationError) as exc_info:
            ModelValidator.validate_model(model, X, y, bad_metrics)
        assert "Model metrics must be calculated" in str(exc_info.value)


class TestShipmentDelayTrainingPipeline:
    def test_pipeline_trains_and_produces_artifact(self) -> None:
        rows = make_sample_rows(40)
        split = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_train_001",
            test_ratio=0.2,
            val_ratio=0.0,
            min_train_rows=20,
            min_test_rows=3,
        )

        config = MLConfig(min_training_rows=20, random_seed=42)
        pipeline = ShipmentDelayTrainingPipeline(config=config)

        artifact = pipeline.run(
            split=split,
            model_id="delay_baseline_v1",
            model_family="shipment_delay",
            model_version="1.0.0",
        )

        assert artifact is not None
        assert artifact.metadata.model_id == "delay_baseline_v1"
        assert artifact.metadata.organization_id == "org_acme"
        assert artifact.metadata.task_type.value == "REGRESSION"
        assert artifact.metadata.target == "delay_minutes"
        assert artifact.metadata.metrics.is_calculated is True

        assert artifact.metadata.metrics.mae is not None and artifact.metadata.metrics.mae >= 0.0
        assert artifact.metadata.metrics.rmse is not None and artifact.metadata.metrics.rmse >= 0.0
        assert artifact.metadata.validation_status == "VALIDATED"
        assert len(artifact.artifact_fingerprint) == 64



    def test_pipeline_insufficient_training_data_raises_error(self) -> None:
        # Create a split with only 15 train rows when config expects at least 20
        rows = make_sample_rows(20)
        split = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_train_small",
            test_ratio=0.2,
            val_ratio=0.0,
            min_train_rows=15,
            min_test_rows=3,
        )

        config = MLConfig(min_training_rows=20, random_seed=42)
        pipeline = ShipmentDelayTrainingPipeline(config=config)

        with pytest.raises(InsufficientTrainingDataError) as exc_info:
            pipeline.run(
                split=split,
                model_id="delay_small",
                model_family="shipment_delay",
                model_version="1.0.0",
            )
        assert "Insufficient training data" in str(exc_info.value)
        assert "minimum: 20" in str(exc_info.value)

    def test_training_reproducibility_identical_fingerprint(self) -> None:
        rows = make_sample_rows(40)
        split = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_repro",
            test_ratio=0.2,
            val_ratio=0.0,
            min_train_rows=20,
            min_test_rows=3,
        )

        config = MLConfig(min_training_rows=20, random_seed=42)
        p1 = ShipmentDelayTrainingPipeline(config=config)
        art1 = p1.run(split=split, model_id="repro_m", model_family="shipment_delay", model_version="1.0.0")

        p2 = ShipmentDelayTrainingPipeline(config=config)
        art2 = p2.run(split=split, model_id="repro_m", model_family="shipment_delay", model_version="1.0.0")

        assert art1.metadata.metrics.mae == art2.metadata.metrics.mae
        assert art1.metadata.metrics.rmse == art2.metadata.metrics.rmse
        assert art1.metadata.feature_schema_fingerprint == art2.metadata.feature_schema_fingerprint
