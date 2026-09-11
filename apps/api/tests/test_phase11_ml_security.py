"""Security, sanitization, tampering, and tenant isolation tests for the ML subsystem."""

from __future__ import annotations

import io
from pathlib import Path
import joblib
import pytest

from app.ml.contracts import (
    FeatureSchema,
    FeatureSpec,
    FeatureType,
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
)
from app.ml.datasets.contracts import DatasetRow
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import (
    DataLeakageError,
    DatasetValidationError,
    MLTenantIsolationError,
    ModelArtifactError,
    ModelInferenceError,
)
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.observability import MLObservability
from app.ml.registry.registry import ModelRegistry
from app.ml.training.artifacts import ArtifactManager
from tests.test_phase11_ml_dataset import make_sample_rows, make_valid_feature_dict


class TestMLSecurity:
    def test_secret_redaction_in_observability(self, monkeypatch) -> None:
        captured_events = []
        monkeypatch.setattr(
            "app.ml.observability.logger.info",
            lambda *args, **kwargs: captured_events.append(args),
        )

        MLObservability.emit_training_event(
            action="ML_MODEL_TRAINED",
            organization_id="org_test",
            model_id="model_secret_test",
            metrics={"mae": 12.5, "api_key": "sk-secret-12345", "token": "Bearer abcde"},
            duration_ms=150.0,
        )

        assert len(captured_events) == 1
        args = captured_events[0]
        # args: (format_str, action, org_id, model_id, duration_ms, clean_metrics, clean_details)
        metrics_dict = args[5]
        assert metrics_dict["api_key"] == "[REDACTED]"
        assert metrics_dict["token"] == "[REDACTED]"
        assert metrics_dict["mae"] == 12.5


    def test_path_traversal_in_model_id_during_save_rejected(self, tmp_path: Path) -> None:
        rows = make_sample_rows(20)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        model = ShipmentDelayModel(model_id="../../root_hijack", random_seed=42)
        meta = MLModelMetadata(
            model_id="../../root_hijack",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="1.0.0",
            task_type=TaskType.REGRESSION,
            target="delay_minutes",
            training_dataset_fingerprint="fp_123",
            validation_status="VALIDATED",
            metrics=ModelMetrics(is_calculated=True, mae=10.0, rmse=15.0),
            artifact_fingerprint="fp",
        )

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.save_artifact(
                model=model,
                feature_pipeline=pipeline,
                metadata=meta,
                artifact_dir=tmp_path,
            )
        assert "Path traversal detected" in str(exc_info.value)

    def test_path_traversal_in_load_rejected(self, tmp_path: Path) -> None:
        malicious_path = tmp_path.parent.parent / "etc" / "passwd.joblib"
        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(malicious_path, base_dir=tmp_path)
        assert "Artifact file not found" in str(exc_info.value) or "Path traversal detected" in str(exc_info.value)

    def test_cross_tenant_dataset_validation_strictly_rejected(self) -> None:
        rows = make_sample_rows(20)
        # Inject an alien tenant in one row
        alien_row = rows[5].model_copy(update={"organization_id": "org_alien"})
        rows[5] = alien_row

        with pytest.raises(MLTenantIsolationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_cross_tenant",
            )
        assert "belongs to tenant 'org_alien'" in str(exc_info.value)
        assert "violating dataset organization_id 'org_acme'" in str(exc_info.value)


    def test_cross_tenant_registry_access_strictly_rejected(self) -> None:
        registry = ModelRegistry()
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        model = ShipmentDelayModel("m_tenant_secret", random_seed=42)
        meta = MLModelMetadata(
            model_id="m_tenant_secret",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="1.0.0",
            task_type=TaskType.REGRESSION,
            target="delay_minutes",
            training_dataset_fingerprint="fp_sec",
            validation_status="VALIDATED",
            metrics=ModelMetrics(is_calculated=True, mae=5.0, rmse=8.0),
            artifact_fingerprint="fp_sec",
            organization_id="org_victim",
        )
        registry.register_model(model, pipe, meta)

        # Attacker organization tries to retrieve victim's model
        with pytest.raises(MLTenantIsolationError) as exc_info:
            registry.get_model("m_tenant_secret", organization_id="org_attacker")
        assert "org_victim" in str(exc_info.value)
        assert "org_attacker" in str(exc_info.value)

    def test_non_finite_nan_inf_feature_injection_rejected(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)

        # 1. Infinity injection
        bad_inf = make_valid_feature_dict(0)
        bad_inf["route_distance_km"] = float("inf")
        with pytest.raises(Exception):
            pipe.transform_single(bad_inf)

        # 2. NaN injection
        bad_nan = make_valid_feature_dict(0)
        bad_nan["route_risk_score"] = float("nan")
        with pytest.raises(Exception):
            pipe.transform_single(bad_nan)

    def test_corrupted_artifact_tampering_rejected(self, tmp_path: Path) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        model = ShipmentDelayModel("m_safe", random_seed=42)
        meta = MLModelMetadata(
            model_id="m_safe",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="1.0.0",
            task_type=TaskType.REGRESSION,
            target="delay_minutes",
            training_dataset_fingerprint="fp_safe",
            validation_status="VALIDATED",
            metrics=ModelMetrics(is_calculated=True, mae=10.0, rmse=15.0),
            artifact_fingerprint="placeholder",
            organization_id="org_acme",
        )

        _, file_path = ArtifactManager.save_artifact(model, pipe, meta, artifact_dir=tmp_path)

        # Invalidate file by replacing middle bytes
        with open(file_path, "r+b") as f:
            f.seek(50)
            f.write(b"CORRUPTED_TAMPERED_INJECTED_PAYLOAD")

        with pytest.raises(ModelArtifactError):
            ArtifactManager.load_artifact(file_path, base_dir=tmp_path)
