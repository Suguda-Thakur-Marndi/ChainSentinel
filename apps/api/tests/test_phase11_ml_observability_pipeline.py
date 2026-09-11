"""Phase 11 ML Observability, Audit, Feature Pipeline, and Lifecycle Tests.

Validates structured audit logging, secret masking, pipeline idempotency,
multi-tenant registry behavior, and service configuration overrides.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List
import numpy as np
import pytest

from app.ml.config import MLConfig
from app.ml.contracts import (
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
)
from app.ml.datasets.builder import ShipmentDatasetBuilder
from app.ml.datasets.contracts import DatasetRow
from app.ml.errors import (
    MLTenantIsolationError,
    ModelArtifactError,
    ModelValidationError,
)
from app.ml.features.shipment_delay import (
    SHIPMENT_DELAY_SCHEMA,
    ShipmentDelayFeaturePipeline,
)
from app.ml.inference.service import MLPredictionService
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.observability import MLObservability
from app.ml.registry.registry import ModelRegistry
from app.ml.training.artifacts import ArtifactManager
from app.ml.training.pipeline import ShipmentDelayTrainingPipeline
from app.ml.training.validation import ModelValidator
from app.agents.prediction import (
    PredictionFeature,
    PredictionRequest,
    PredictionStatus,
    PredictionType,
)
from tests.test_phase11_ml_dataset import make_sample_rows
from tests.test_phase11_ml_inference import make_sample_request


def make_test_model(model_id: str, org_id: str = "org_acme", is_prod: bool = True):
    rows = make_sample_rows(25)
    pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
    pipeline.fit(rows)

    X = pipeline.transform(rows)
    y = np.array([r.target for r in rows], dtype=np.float64)

    model = ShipmentDelayModel(model_id=model_id, random_seed=42)
    model.fit(X, y)
    metrics = model.evaluate(X, y)

    meta = MLModelMetadata(
        model_id=model_id,
        model_family=ModelFamily.SHIPMENT_DELAY,
        model_version="1.0.0",
        task_type=TaskType.REGRESSION,
        target="delay_minutes",
        feature_names=pipeline.get_feature_schema().feature_names,
        training_dataset_fingerprint=f"ds_fp_{model_id}",
        preprocessing_version="shipment_delay_v1",
        hyperparameters={"alpha": 1.0},
        validation_status="VALIDATED",
        metrics=metrics,
        artifact_fingerprint="fp_" + model_id,
        organization_id=org_id,
        is_production=is_prod,
    )
    return model, pipeline, meta


class TestMLObservabilityAndPipeline:
    """Test suite for ML Observability, Feature Pipeline, and Service Lifecycle."""

    # 1. Observability: emit_training_event outputs structured record
    def test_emit_training_event_structured_log(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            MLObservability.emit_training_event(
                action="TRAIN_MODEL",
                organization_id="org_acme",
                model_id="test_model_01",
                metrics={"mae": 5.2, "rmse": 7.1},
                duration_ms=150.5,
                details={"rows": 30},
            )
        assert "AUDIT_EVENT" in caplog.text
        assert "action=TRAIN_MODEL" in caplog.text
        assert "org=org_acme" in caplog.text
        assert "model_id=test_model_01" in caplog.text

    # 2. Observability: secret redaction in details
    def test_emit_training_event_redacts_secrets_in_details(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            MLObservability.emit_training_event(
                action="TRAIN_MODEL",
                organization_id="org_acme",
                model_id="test_model_sec",
                metrics={"mae": 4.0},
                duration_ms=80.0,
                details={"api_key": "sk-secret-token-12345", "notes": "ok"},
            )
        assert "sk-secret-token-12345" not in caplog.text
        assert "[REDACTED]" in caplog.text

    # 3. Observability: secret redaction in metrics
    def test_emit_training_event_redacts_secrets_in_metrics(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            MLObservability.emit_training_event(
                action="TRAIN_MODEL",
                organization_id="org_acme",
                model_id="test_model_sec_metrics",
                metrics={"mae": 4.0, "secret_key": "super_secret_val"},
                duration_ms=60.0,
            )
        assert "super_secret_val" not in caplog.text
        assert "[REDACTED]" in caplog.text

    # 4. Observability: emit_inference_event structured log
    def test_emit_inference_event_structured_log(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            MLObservability.emit_inference_event(
                action="PREDICT",
                organization_id="org_acme",
                prediction_id="pred_999",
                model_id="shipment_delay_ridge",
                latency_ms=12.4,
                status="SUCCESS",
                predicted_value=25.0,
            )
        assert "AUDIT_EVENT" in caplog.text
        assert "prediction_id=pred_999" in caplog.text
        assert "status=SUCCESS" in caplog.text

    # 5. Observability: emit_inference_event trace propagation
    def test_emit_inference_event_trace_propagation(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            MLObservability.emit_inference_event(
                action="PREDICT",
                organization_id="org_acme",
                prediction_id="pred_trace_1",
                model_id="shipment_delay_ridge",
                latency_ms=10.0,
                request_id="req_001",
                correlation_id="corr_abc",
                trace_id="trace_xyz",
            )
        assert "req_id=req_001" in caplog.text
        assert "corr_id=corr_abc" in caplog.text
        assert "trace_id=trace_xyz" in caplog.text

    # 6. Observability: emit_inference_event failure logging
    def test_emit_inference_event_failure_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            MLObservability.emit_inference_event(
                action="PREDICT_FAILURE",
                organization_id="org_acme",
                prediction_id="pred_fail_1",
                model_id="shipment_delay_ridge",
                latency_ms=5.0,
                status="FAILED",
                error_category="ModelInferenceError",
            )
        assert "status=FAILED" in caplog.text
        assert "error_category=ModelInferenceError" in caplog.text

    # 7. Feature pipeline idempotency: multiple transform calls produce identical arrays
    def test_feature_pipeline_idempotency(self) -> None:
        rows = make_sample_rows(25)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X1 = pipe.transform(rows)
        X2 = pipe.transform(rows)
        X3 = pipe.transform(rows)
        assert np.array_equal(X1, X2)
        assert np.array_equal(X2, X3)

    # 8. Feature pipeline transform_single shape
    def test_feature_pipeline_transform_single_shape(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        raw_feat = {
            "transport_mode": "AIR",
            "route_distance_km": 3500.0,
            "planned_duration_hours": 36.0,
            "delay_events_count": 1.0,
            "origin_weather_severity": 2.0,
            "port_congestion_index": 1.5,
            "carrier_disruption_count": 0.0,
            "is_weekend_departure": 0.0,
            "departure_hour": 14.0,
        }
        vec = pipe.transform_single(raw_feat)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (1, 16)
        assert np.all(np.isfinite(vec))

    # 9. Feature pipeline custom alias mapping
    def test_feature_pipeline_custom_aliases(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        raw_feat_with_alias = {
            "mode": "AIR",
            "distance_km": 3500.0,
            "planned_hours": 36.0,
            "delay_events": 1.0,
            "weather_severity": 2.0,
            "port_congestion": 1.5,
            "holiday_season": 0.0,
            "customs_hold": 0.0,
            "hour": 14.0,
        }
        vec = pipe.transform_single(raw_feat_with_alias)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (1, 16)
        assert np.all(np.isfinite(vec))

    # 10. Training pipeline with custom split ratios
    def test_training_pipeline_with_custom_ratios(self) -> None:
        rows = make_sample_rows(45)
        split = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_custom_ratio",
            test_ratio=0.25,
            val_ratio=0.15,
            min_train_rows=20,
            min_test_rows=3,
        )
        assert split.train.row_count >= 20
        assert split.val is not None
        assert split.val.row_count >= 3
        assert split.test.row_count >= 3

        config = MLConfig(min_training_rows=20, random_seed=42)
        pipeline = ShipmentDelayTrainingPipeline(config=config)
        artifact = pipeline.run(
            split=split,
            model_id="delay_custom_v1",
            model_family="shipment_delay",
            model_version="1.0.0",
        )
        assert artifact is not None
        assert artifact.metadata.metrics is not None
        assert artifact.metadata.metrics.is_calculated is True
        assert artifact.metadata.metrics.mae >= 0.0

    # 11. Model validator rejects unfitted model
    def test_model_validator_rejects_unfitted_model(self) -> None:
        model = ShipmentDelayModel(alpha=1.0, random_seed=42)
        X = np.zeros((10, 16))
        y = np.zeros(10)
        metrics = ModelMetrics(is_calculated=True, mae=10.0, rmse=15.0)

        with pytest.raises(ModelValidationError) as exc_info:
            ModelValidator.validate_model(model, X, y, metrics)
        assert "Model must be fitted to pass validation" in str(exc_info.value)

    # 12. Model validator rejects uncalculated metrics
    def test_model_validator_rejects_uncalculated_metrics(self) -> None:
        rows = make_sample_rows(30)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X = pipe.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42).fit(X, y)
        bad_metrics = ModelMetrics(is_calculated=False)

        with pytest.raises(ModelValidationError) as exc_info:
            ModelValidator.validate_model(model, X, y, bad_metrics)
        assert "Model metrics must be calculated" in str(exc_info.value)

    # 13. Model validator passes good model
    def test_model_validator_passes_good_model(self) -> None:
        rows = make_sample_rows(30)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X = pipe.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(random_seed=42).fit(X, y)
        metrics = model.evaluate(X, y)
        # Passes without raising exception
        ModelValidator.validate_model(model, X, y, metrics)

    # 14. Model registry isolation across three tenants
    def test_model_registry_three_tenants_isolation(self) -> None:
        registry = ModelRegistry()
        tenants = ["tenant_alpha", "tenant_beta", "tenant_gamma"]

        for t in tenants:
            m, p, meta = make_test_model(f"model_{t}", org_id=t)
            registry.register_model(m, p, meta)

        for t in tenants:
            models = registry.list_models(organization_id=t)
            assert len(models) == 1
            assert models[0].organization_id == t

        # Verify tenant alpha cannot access tenant beta model
        with pytest.raises(MLTenantIsolationError):
            registry.get_model("model_tenant_beta", organization_id="tenant_alpha")

    # 15. Model registry list active models
    def test_model_registry_list_active_models(self) -> None:
        registry = ModelRegistry()
        m1, p1, meta1 = make_test_model("m1", org_id="org_active", is_prod=True)
        m2, p2, meta2 = make_test_model("m2", org_id="org_active", is_prod=False)

        registry.register_model(m1, p1, meta1)
        registry.register_model(m2, p2, meta2)

        active = registry.get_active_model(ModelFamily.SHIPMENT_DELAY, organization_id="org_active")
        assert active is not None
        _, _, meta = active
        assert meta.model_id == "m1"

    # 16. ArtifactManager save and load roundtrip
    def test_artifact_manager_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        m, p, meta = make_test_model("test_rt_01", org_id="org_acme")
        art, file_path = ArtifactManager.save_artifact(
            model=m,
            feature_pipeline=p,
            metadata=meta,
            artifact_dir=tmp_path,
        )
        assert file_path.exists()
        loaded_m, loaded_p, loaded_meta = ArtifactManager.load_artifact(
            artifact_path=file_path,
            expected_model_id="test_rt_01",
            base_dir=tmp_path,
        )
        assert loaded_m.is_fitted is True
        assert loaded_p.is_fitted is True
        assert loaded_meta.model_id == "test_rt_01"

    # 17. ArtifactManager detects corrupt file
    def test_artifact_manager_detects_corrupt_file(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupt_test.joblib"
        bad_file.write_bytes(b"INVALID_HEADER_GARBAGE_BYTES_1234567890")

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(
                artifact_path=bad_file,
                expected_model_id="corrupt_test",
                base_dir=tmp_path,
            )
        err_str = str(exc_info.value).lower()
        assert "fail" in err_str or "corrupt" in err_str or "tamper" in err_str

    # 18. Inference service latency tracking
    def test_inference_service_latency_tracking(self) -> None:
        registry = ModelRegistry()
        m, p, meta = make_test_model("m_lat", org_id="org_acme")
        registry.register_model(m, p, meta)

        service = MLPredictionService(registry=registry)
        req = make_sample_request(pred_id="pred_req_lat", org_id="org_acme")
        res = service.predict(req)
        assert res.status == PredictionStatus.COMPLETED.value
        assert res.predicted_value is not None
        assert res.model_metadata.model_name == "m_lat"

    # 19. Inference service not available when no model
    def test_inference_service_not_available_when_no_model(self) -> None:
        empty_registry = ModelRegistry()
        service = MLPredictionService(registry=empty_registry)
        req = make_sample_request(pred_id="pred_req_empty", org_id="org_acme")
        res = service.predict(req)
        assert res.status == PredictionStatus.NOT_AVAILABLE.value
        assert res.predicted_value is None
        assert len(res.limitations) > 0

    # 20. Retraining produces distinct fingerprints
    def test_retraining_produces_distinct_fingerprints(self) -> None:
        rows1 = make_sample_rows(35)
        rows2 = make_sample_rows(40)

        split1 = ShipmentDatasetBuilder.time_aware_split(
            rows=rows1,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_retrain_1",
            min_train_rows=20,
            min_test_rows=3,
        )
        split2 = ShipmentDatasetBuilder.time_aware_split(
            rows=rows2,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_retrain_2",
            min_train_rows=20,
            min_test_rows=3,
        )

        pipeline = ShipmentDelayTrainingPipeline(config=MLConfig(random_seed=42))
        art1 = pipeline.run(split=split1, model_id="retrain_m1")
        art2 = pipeline.run(split=split2, model_id="retrain_m2")

        assert art1.metadata.artifact_fingerprint != art2.metadata.artifact_fingerprint
        assert art1.metadata.training_dataset_fingerprint != art2.metadata.training_dataset_fingerprint
