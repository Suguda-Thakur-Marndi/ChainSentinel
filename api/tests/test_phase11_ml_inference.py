"""Unit tests for MLPredictionService inference, tenant isolation, uncertainty, and fallback."""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from app.agents.contracts import AgentLimitation
from app.agents.prediction.contract import (
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
)
from app.ml.contracts import (
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
)
from app.ml.errors import MLTenantIsolationError
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.inference.service import MLPredictionService
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.registry.registry import ModelRegistry
from tests.test_phase11_ml_dataset import make_sample_rows


def make_sample_request(
    pred_id: str = "pred_req_001",
    org_id: str = "org_acme",
    feature_org_id: str | None = None,
) -> PredictionRequest:
    f_org = feature_org_id or org_id
    features = [
        PredictionFeature(
            feature_name="transport_mode",
            value="OCEAN",
            unit="category",
            source="shipment.mode",
            source_type="database",
            organization_id=f_org,
            evidence_references=["ev_1"],
        ),
        PredictionFeature(
            feature_name="planned_duration_hours",
            value=24.0,
            unit="hours",
            source="shipment.duration",
            source_type="database",
            organization_id=f_org,
            evidence_references=["ev_2"],
        ),
        PredictionFeature(
            feature_name="route_distance_km",
            value=1500.0,
            unit="km",
            source="route.distance",
            source_type="database",
            organization_id=f_org,
            evidence_references=["ev_3"],
        ),
        PredictionFeature(
            feature_name="route_risk_score",
            value=45.0,
            unit="score",
            source="risk.score",
            source_type="risk_engine",
            organization_id=f_org,
            evidence_references=["ev_4"],
        ),
        PredictionFeature(
            feature_name="carrier_reliability",
            value=0.92,
            unit="ratio",
            source="carrier.reliability",
            source_type="database",
            organization_id=f_org,
            evidence_references=["ev_5"],
        ),
    ]


    return PredictionRequest(
        prediction_id=pred_id,
        organization_id=org_id,
        prediction_type=PredictionType.SHIPMENT_DELAY,
        target="shipment_delay_minutes",
        features=features,
        risk_assessment_id="risk_assess_001",
    )



def setup_service_with_model(org_id: str = "org_acme") -> MLPredictionService:
    registry = ModelRegistry()

    rows = make_sample_rows(30)
    pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
    pipeline.fit(rows)

    X = pipeline.transform(rows)
    y = np.array([r.target for r in rows], dtype=np.float64)

    model = ShipmentDelayModel(model_id="delay_test_model", random_seed=42)
    model.fit(X, y)
    metrics = model.evaluate(X, y)

    meta = MLModelMetadata(
        model_id="delay_test_model",
        model_family=ModelFamily.SHIPMENT_DELAY,
        model_version="1.0.0",
        task_type=TaskType.REGRESSION,
        target="delay_minutes",
        feature_names=pipeline.get_feature_schema().feature_names,
        training_dataset_fingerprint="ds_fp_123",
        preprocessing_version="shipment_delay_v1",
        hyperparameters={"alpha": 1.0},
        validation_status="VALIDATED",
        metrics=metrics,
        artifact_fingerprint="art_fp_delay_001",
        organization_id=org_id,
        is_production=True,
    )
    registry.register_model(model, pipeline, meta)
    return MLPredictionService(registry=registry)


class TestMLPredictionService:
    def test_service_availability(self) -> None:
        empty_registry = ModelRegistry()
        svc_empty = MLPredictionService(registry=empty_registry)
        assert svc_empty.is_available() is False

        svc_ready = setup_service_with_model("org_acme")
        assert svc_ready.is_available() is True

    def test_fallback_when_no_active_model_for_tenant(self) -> None:
        empty_registry = ModelRegistry()
        svc = MLPredictionService(registry=empty_registry)

        req = make_sample_request()
        result = svc.predict(req)

        assert isinstance(result, PredictionResult)
        assert result.status == PredictionStatus.NOT_AVAILABLE.value
        assert result.predicted_value is None
        assert len(result.limitations) > 0
        assert "unavailable or not deployed" in result.limitations[0].description


    def test_predict_success_with_valid_features(self) -> None:
        svc = setup_service_with_model("org_acme")
        req = make_sample_request(pred_id="pred_101", org_id="org_acme")

        result = svc.predict(req)

        assert isinstance(result, PredictionResult)
        assert result.status == PredictionStatus.COMPLETED.value
        assert result.prediction_id == "pred_101"
        assert result.organization_id == "org_acme"
        assert result.predicted_value is not None
        assert result.predicted_value >= 0.0  # Physical constraint
        assert result.unit == "minutes"
        assert result.model_metadata.model_name == "delay_test_model"

    def test_predict_uncertainty_is_grounded_in_rmse_not_fabricated(self) -> None:
        svc = setup_service_with_model("org_acme")
        req = make_sample_request()

        result = svc.predict(req)

        assert result.uncertainty is not None
        assert result.uncertainty.method == "EMPIRICAL_TEST_RMSE"
        # Confidence score must not be fabricated without probability calibration
        assert result.uncertainty.confidence_score is None
        assert result.uncertainty.standard_error is not None
        assert result.uncertainty.standard_error >= 0.0
        assert result.uncertainty.prediction_interval is not None
        low, high = result.uncertainty.prediction_interval
        assert low <= result.predicted_value <= high

    def test_predict_with_feature_aliases(self) -> None:
        svc = setup_service_with_model("org_acme")
        # Features using PredictionFeatureExtractor aliases
        aliased_features = [
            PredictionFeature(
                feature_name="scheduled_transit_hours",
                value=36.0,
                source="test",
                source_type="test",
                organization_id="org_acme",
            ),
            PredictionFeature(
                feature_name="risk_composite_score",
                value=60.0,
                source="test",
                source_type="test",
                organization_id="org_acme",
            ),
            PredictionFeature(
                feature_name="port_disruption_detected",
                value=1.0,
                source="test",
                source_type="test",
                organization_id="org_acme",
            ),
            PredictionFeature(
                feature_name="weather_disruption_detected",
                value=0.0,
                source="test",
                source_type="test",
                organization_id="org_acme",
            ),
        ]

        req = PredictionRequest(
            prediction_id="pred_alias_001",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=aliased_features,
            risk_assessment_id="risk_assess_002",
        )

        result = svc.predict(req)
        assert result.status == PredictionStatus.COMPLETED.value
        assert result.predicted_value is not None
        assert result.predicted_value >= 0.0

    def test_cross_tenant_feature_rejected(self) -> None:
        from app.agents.prediction.errors import PredictionTenantIsolationError
        svc = setup_service_with_model("org_acme")
        # Feature with tenant mismatch: request is org_acme, but feature is org_evil
        with pytest.raises((MLTenantIsolationError, PredictionTenantIsolationError)) as exc_info:
            make_sample_request(pred_id="pred_bad_tenant", org_id="org_acme", feature_org_id="org_evil")
        assert "org_evil" in str(exc_info.value)
        assert "org_acme" in str(exc_info.value)


    def test_cross_tenant_model_request_falls_back_or_isolates(self) -> None:
        # Model belongs strictly to org_acme
        svc = setup_service_with_model("org_acme")

        # Request from org_other
        req = make_sample_request(org_id="org_other")
        result = svc.predict(req)

        # Since org_acme model cannot serve org_other and there is no global model,
        # it gracefully falls back to NOT_AVAILABLE
        assert result.status == PredictionStatus.NOT_AVAILABLE.value

    def test_predict_determinism(self) -> None:
        svc = setup_service_with_model("org_acme")
        req1 = make_sample_request(pred_id="det_001")
        req2 = make_sample_request(pred_id="det_001")

        res1 = svc.predict(req1)
        res2 = svc.predict(req2)

        assert res1.predicted_value == res2.predicted_value
        assert res1.uncertainty.prediction_interval == res2.uncertainty.prediction_interval
        assert res1.uncertainty.standard_error == res2.uncertainty.standard_error
