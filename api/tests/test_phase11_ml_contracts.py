"""Unit tests for Phase 11 ML contracts, schemas, immutability, and fingerprints."""

from __future__ import annotations

import math
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.ml.contracts import (
    FeatureSchema,
    FeatureSpec,
    FeatureType,
    MLModelMetadata,
    ModelArtifact,
    ModelFamily,
    ModelMetrics,
    ModelStatus,
    TaskType,
    compute_artifact_fingerprint,
    compute_schema_fingerprint,
)
from app.ml.errors import MLValidationError, ModelValidationError
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA


class TestFeatureSpecContracts:
    def test_valid_feature_spec_creation(self) -> None:
        spec = FeatureSpec(
            name="route_distance_km",
            feature_type=FeatureType.NUMERIC,
            unit="km",
            description="Distance in km",
            source_field="route.distance_km",
        )
        assert spec.name == "route_distance_km"
        assert spec.feature_type == FeatureType.NUMERIC
        assert spec.unit == "km"

    def test_feature_spec_immutability(self) -> None:
        spec = FeatureSpec(
            name="route_distance_km",
            feature_type=FeatureType.NUMERIC,
            source_field="route.distance_km",
        )
        with pytest.raises(ValidationError):
            spec.name = "mutated_name"  # type: ignore

    def test_feature_spec_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            FeatureSpec(
                name="distance",
                feature_type=FeatureType.NUMERIC,
                source_field="route.distance",
                unauthorized_field="malicious",  # type: ignore
            )

    def test_feature_spec_rejects_leakage_permission(self) -> None:
        with pytest.raises(MLValidationError) as exc_info:
            FeatureSpec(
                name="leakage_feature",
                feature_type=FeatureType.NUMERIC,
                source_field="delivery.time",
                allow_future_leakage=True,
            )
        assert "cannot set allow_future_leakage=True" in str(exc_info.value)


class TestFeatureSchemaContracts:
    def test_schema_fingerprint_generation(self) -> None:
        schema = SHIPMENT_DELAY_SCHEMA
        assert schema.schema_fingerprint is not None
        assert len(schema.schema_fingerprint) == 64
        assert len(schema.features) == 12

    def test_schema_fingerprint_deterministic_and_order_invariant(self) -> None:
        f1 = FeatureSpec(name="feat_a", feature_type=FeatureType.NUMERIC, source_field="s.a")
        f2 = FeatureSpec(name="feat_b", feature_type=FeatureType.CATEGORICAL, source_field="s.b")

        s1 = FeatureSchema(version="v1", features=[f1, f2], target_name="target")
        s2 = FeatureSchema(version="v1", features=[f2, f1], target_name="target")

        assert s1.schema_fingerprint == s2.schema_fingerprint

    def test_schema_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            FeatureSchema(
                version="v1",
                features=[],
                target_name="target",
                extra_forbidden_field=123,  # type: ignore
            )


class TestModelMetricsContracts:
    def test_valid_metrics_creation(self) -> None:
        m = ModelMetrics(mae=12.4, rmse=16.8, r2=0.82, sample_count=100, is_calculated=True)
        assert m.mae == 12.4
        assert m.rmse == 16.8
        assert m.r2 == 0.82
        assert m.sample_count == 100
        assert m.is_calculated is True

    def test_metrics_cannot_be_negative(self) -> None:
        with pytest.raises(ModelValidationError):
            ModelMetrics(mae=-5.0, rmse=10.0, is_calculated=True)

        with pytest.raises(ModelValidationError):
            ModelMetrics(mae=5.0, rmse=-1.0, is_calculated=True)

    def test_metrics_cannot_be_non_finite(self) -> None:
        with pytest.raises(ModelValidationError):
            ModelMetrics(mae=float("nan"), rmse=10.0, is_calculated=True)

        with pytest.raises(ModelValidationError):
            ModelMetrics(mae=10.0, rmse=float("inf"), is_calculated=True)

    def test_metrics_cannot_have_values_if_not_calculated(self) -> None:
        with pytest.raises(ModelValidationError) as exc_info:
            ModelMetrics(mae=10.0, rmse=15.0, is_calculated=False)
        assert "is_calculated is False" in str(exc_info.value)

    def test_metrics_immutability(self) -> None:
        m = ModelMetrics(mae=10.0, rmse=15.0, is_calculated=True)
        with pytest.raises(ValidationError):
            m.mae = 20.0  # type: ignore


class TestMLModelMetadataContracts:
    def test_valid_metadata_creation(self) -> None:
        metrics = ModelMetrics(mae=10.5, rmse=14.2, r2=0.75, sample_count=50, is_calculated=True)
        meta = MLModelMetadata(
            model_id="test_model_v1",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="1.0.0",
            task_type=TaskType.REGRESSION,
            target="delay_minutes",
            feature_names=["f1", "f2"],
            training_dataset_fingerprint="fp_data_123",
            preprocessing_version="1.0.0",
            hyperparameters={"alpha": 1.0},
            metrics=metrics,
            artifact_fingerprint="fp_art_456",
            organization_id="org_acme",
        )
        assert meta.model_id == "test_model_v1"
        assert meta.model_family == ModelFamily.SHIPMENT_DELAY
        assert meta.hyperparameters["alpha"] == 1.0

    def test_metadata_secrets_forbidden(self) -> None:
        from app.agents.errors import AgentValidationError
        metrics = ModelMetrics(is_calculated=False)
        with pytest.raises((ValidationError, AgentValidationError)):
            MLModelMetadata(
                model_id="test_model",
                model_family=ModelFamily.SHIPMENT_DELAY,
                model_version="1.0.0",
                training_dataset_fingerprint="fp_data",
                metrics=metrics,
                artifact_fingerprint="fp_art",
                hyperparameters={"api_key": "sk-secret-1234567890"},  # Forbidden secret key
            )

    def test_metadata_extra_forbidden(self) -> None:
        metrics = ModelMetrics(is_calculated=False)
        with pytest.raises(ValidationError):
            MLModelMetadata(
                model_id="test_model",
                model_family=ModelFamily.SHIPMENT_DELAY,
                model_version="1.0.0",
                training_dataset_fingerprint="fp_data",
                metrics=metrics,
                artifact_fingerprint="fp_art",
                unauthorized_extra_field=True,  # type: ignore
            )


class TestModelArtifactContracts:
    def test_artifact_fingerprint_mismatch_raises_error(self) -> None:
        metrics = ModelMetrics(is_calculated=False)
        meta = MLModelMetadata(
            model_id="test_model",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="1.0.0",
            training_dataset_fingerprint="fp_data",
            metrics=metrics,
            artifact_fingerprint="expected_fingerprint_abc",
        )
        with pytest.raises(ModelValidationError) as exc_info:
            ModelArtifact(
                metadata=meta,
                feature_schema=SHIPMENT_DELAY_SCHEMA,
                serialized_pipeline=b"dummy_bytes",
                artifact_fingerprint="different_tampered_fingerprint_xyz",
            )
        assert "Artifact fingerprint mismatch" in str(exc_info.value)
