"""The 20 Mandatory Critical Tests and End-to-End Integration for Phase 11 ML.

Validates all 20 explicit architectural, security, mathematical, and invariant requirements
prescribed in Section 41 of the Phase 11 Specification.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import numpy as np
import pytest

from app.agents.contracts import (
    AgentGraphState,
    AgentGraphStateDict,
    AgentLimitation,
    AgentStage,
    LimitationCategory,
)
from app.agents.prediction.claude_contract import PredictionExplanationInput
from app.agents.prediction.contract import (
    ModelMetadata as AgentModelMetadata,
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
    PredictionUncertainty,
)
from app.agents.prediction.errors import PredictionTenantIsolationError
from app.agents.prediction.node import prediction_node
from app.agents.prediction.service import (
    DeterministicMockPredictionService,
    UnavailablePredictionService,
)


from app.db.base import Base
import app.models as db_models
from app.ml.config import MLConfig
from app.ml.contracts import (
    FeatureSchema,
    FeatureSpec,
    FeatureType,
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
)
from app.ml.datasets.builder import ShipmentDatasetBuilder
from app.ml.datasets.contracts import DatasetRow
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import (
    DataLeakageError,
    InsufficientTrainingDataError,
    MLTenantIsolationError,
    ModelArtifactError,
    ModelValidationError,
)
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.inference.service import MLPredictionService
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.registry.registry import ModelRegistry
from app.ml.training.artifacts import ArtifactManager
from app.ml.training.pipeline import ShipmentDelayTrainingPipeline
from tests.test_phase11_ml_dataset import make_sample_rows


def build_trained_service(org_id: str = "org_acme", tmp_path: Path | None = None) -> tuple[MLPredictionService, ModelRegistry]:
    registry = ModelRegistry(artifact_dir=tmp_path)
    rows = make_sample_rows(40)
    split = ShipmentDatasetBuilder.time_aware_split(
        rows=rows,
        schema=SHIPMENT_DELAY_SCHEMA,
        organization_id=org_id,
        dataset_id="ds_crit_train",
        test_ratio=0.2,
        val_ratio=0.0,
        min_train_rows=20,
        min_test_rows=3,
    )
    pipeline = ShipmentDelayTrainingPipeline(
        config=MLConfig(min_training_rows=20, random_seed=42),
        artifact_dir=tmp_path,
    )
    model, feat_pipeline, artifact, _ = pipeline.train_from_split(split=split)
    registry.register_model(model, feat_pipeline, artifact.metadata)
    service = MLPredictionService(registry=registry)
    return service, registry


def make_valid_features(org_id: str = "org_acme") -> list[PredictionFeature]:
    return [
        PredictionFeature(
            feature_name="transport_mode",
            value="OCEAN",
            unit="category",
            source="shipment.mode",
            source_type="database",
            organization_id=org_id,
        ),
        PredictionFeature(
            feature_name="planned_duration_hours",
            value=24.0,
            unit="hours",
            source="shipment.duration",
            source_type="database",
            organization_id=org_id,
        ),
        PredictionFeature(
            feature_name="route_distance_km",
            value=1200.0,
            unit="km",
            source="route.distance",
            source_type="database",
            organization_id=org_id,
        ),
        PredictionFeature(
            feature_name="route_risk_score",
            value=35.0,
            unit="score",
            source="risk.score",
            source_type="risk_engine",
            organization_id=org_id,
        ),
        PredictionFeature(
            feature_name="carrier_reliability",
            value=0.95,
            unit="ratio",
            source="carrier.reliability",
            source_type="database",
            organization_id=org_id,
        ),
    ]


def make_sample_graph_state(
    run_id: str = "run_test_001",
    org_id: str = "org_acme",
    incident_id: str = "inc_test_001",
) -> AgentGraphStateDict:
    return {
        "run_id": run_id,
        "organization_id": org_id,
        "actor_id": "usr_001",
        "request_id": "req_001",
        "correlation_id": "corr_001",
        "trace_id": "trace_001",
        "objective": "Predict shipment delay",
        "input_reference": incident_id,
        "input_references": {"scheduled_transit_hours": 48.0, "route_distance_km": 1200.0},
        "current_stage": AgentStage.RISK_ASSESSMENT.value,
        "current_node": "risk_agent",
        "status": "RUNNING",
        "step_count": 3,
        "evidence_bundle_id": "bundle_001",
        "evidence_references": ["ev_001"],
        "citation_references": ["cit_001"],
        "risk_assessment_id": "ra_001",
        "risk_assessment_reference": {
            "assessment_id": "ra_001",
            "organization_id": org_id,
            "assessment_fingerprint": "fp_ra_001",
            "risk_score": 50.0,
            "risk_level": "MEDIUM",
            "factor_count": 2,
        },
        "structured_findings": [],
        "findings": {},
        "warnings": [],
        "limitations": [],
        "conflicts": [],
        "route_history": [],
        "retry_count": 0,
        "errors": [],
        "metadata": {},
        "state_schema_version": "1.0.0",
    }


class TestPhase11MandatoryCriticalTests:
    """The 20 Mandatory Critical Tests required by Section 41."""

    # 1. No future data can leak into training features.
    def test_critical_01_no_future_data_leaks_into_training_features(self) -> None:
        rows = make_sample_rows(20)
        # Attempt to inject post-delivery / future outcome columns into feature dictionary
        leaky_features = dict(rows[0].features)
        leaky_features["actual_delivery_time"] = "2026-09-02T14:00:00Z"
        bad_row = rows[0].model_copy(update={"features": leaky_features})
        rows[0] = bad_row

        with pytest.raises(DataLeakageError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_leaky",
            )
        assert "Forbidden post-outcome feature" in str(exc_info.value)
        assert "actual_delivery_time" in str(exc_info.value)

    # 2. Insufficient historical data does not produce a fake model.
    def test_critical_02_insufficient_historical_data_does_not_produce_fake_model(self) -> None:
        rows = make_sample_rows(8)  # Only 8 rows, well below minimum requirement of 20
        pipeline = ShipmentDelayTrainingPipeline(config=MLConfig(min_training_rows=20))

        with pytest.raises(InsufficientTrainingDataError) as exc_info:
            pipeline.train_from_rows(rows=rows, organization_id="org_acme")
        assert "Insufficient historical data" in str(exc_info.value) or "minimum" in str(exc_info.value)

    # 3. Missing model returns NOT_AVAILABLE rather than fabricated prediction.
    def test_critical_03_missing_model_returns_not_available(self) -> None:
        empty_registry = ModelRegistry()
        service = MLPredictionService(registry=empty_registry)
        req = PredictionRequest(
            prediction_id="pred_missing_001",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=make_valid_features("org_acme"),
            risk_assessment_id="risk_assess_001",
        )
        result = service.predict(req)
        assert result.status == PredictionStatus.NOT_AVAILABLE.value
        assert result.predicted_value is None
        assert len(result.limitations) > 0
        assert result.limitations[0].category == LimitationCategory.PREDICTION_MODEL_UNAVAILABLE

    # 4. Model inference cannot return non-finite/invalid prediction values.
    def test_critical_04_model_inference_cannot_return_non_finite_or_negative_values(self) -> None:
        from app.ml.errors import PredictionOutputValidationError
        model = ShipmentDelayModel(random_seed=42)
        # Verify validate_prediction constraints
        assert model.validate_prediction(25.4) == 25.4
        # Negative delay must be clamped to 0.0
        assert model.validate_prediction(-12.5) == 0.0

        with pytest.raises(PredictionOutputValidationError):
            model.validate_prediction(float("nan"))
        with pytest.raises(PredictionOutputValidationError):
            model.validate_prediction(float("inf"))
        with pytest.raises(PredictionOutputValidationError):
            model.validate_prediction(float("-inf"))

    # 5. ML cannot modify unrelated authoritative domain state.
    def test_critical_05_ml_cannot_modify_unrelated_authoritative_domain_state(self) -> None:
        state = make_sample_graph_state(incident_id="inc_domain_001", org_id="org_acme")
        service, _ = build_trained_service("org_acme")
        # Run prediction node
        updated_state = prediction_node(state, service=service)

        # Invariants: prediction_node writes only PREDICTION-owned fields, never touches domain state
        assert "input_reference" not in updated_state
        assert "organization_id" not in updated_state
        assert "prediction_result" in updated_state
        assert updated_state["prediction_result"]["predicted_value"] is not None



    # 6. PredictionResult remains compatible with Phase 9.
    def test_critical_06_prediction_result_remains_compatible_with_phase_9(self) -> None:
        service, _ = build_trained_service("org_acme")
        req = PredictionRequest(
            prediction_id="pred_p9_001",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=make_valid_features("org_acme"),
            risk_assessment_id="risk_assess_001",
        )
        result = service.predict(req)
        # Must be valid Pydantic v2 PredictionResult
        assert isinstance(result, PredictionResult)
        dumped = result.model_dump(mode="json")
        assert "prediction_id" in dumped
        assert "organization_id" in dumped
        assert "predicted_value" in dumped
        assert "uncertainty" in dumped
        assert "status" in dumped
        # Re-validate
        re_validated = PredictionResult.model_validate(dumped)
        assert re_validated.prediction_id == result.prediction_id

    # 7. Phase 10 Claude Prediction Explanation remains compatible.
    def test_critical_07_phase_10_claude_prediction_explanation_compatibility(self) -> None:
        service, _ = build_trained_service("org_acme")
        req = PredictionRequest(
            prediction_id="pred_p10_001",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=make_valid_features("org_acme"),
            risk_assessment_id="risk_assess_001",
        )
        result = service.predict(req)

        # Build PredictionExplanationInput using Phase 10 snapshot builder
        from app.agents.prediction.claude_service import ClaudePredictionExplanationService
        from unittest.mock import MagicMock
        claude_svc = ClaudePredictionExplanationService(llm_provider=MagicMock())
        expl_input = claude_svc.build_snapshot(prediction=result)

        assert expl_input.prediction_id == "pred_p10_001"
        assert expl_input.predicted_value == result.predicted_value
        assert expl_input.unit == "minutes"
        assert len(expl_input.prediction_fingerprint) == 64


    # 8. Claude cannot become the prediction authority.
    def test_critical_08_claude_cannot_become_prediction_authority(self) -> None:
        # Prediction authority resides strictly in MLPredictionService / BasePredictionService.
        # Claude service is explanation-only and cannot calculate or inject predictions.
        service, _ = build_trained_service("org_acme")
        assert issubclass(MLPredictionService, UnavailablePredictionService.__bases__[0])
        # Claude services do NOT implement BasePredictionService
        from app.agents.prediction.claude_service import ClaudePredictionExplanationService
        assert not issubclass(ClaudePredictionExplanationService, UnavailablePredictionService.__bases__[0])

    # 9. Cross-tenant training data is rejected.
    def test_critical_09_cross_tenant_training_data_is_rejected(self) -> None:
        rows = make_sample_rows(25)
        # Alien tenant in one row
        rows[10] = rows[10].model_copy(update={"organization_id": "org_intruder"})

        with pytest.raises(MLTenantIsolationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_cross",
            )
        assert "org_intruder" in str(exc_info.value)
        assert "org_acme" in str(exc_info.value)

    # 10. Cross-tenant inference is rejected.
    def test_critical_10_cross_tenant_inference_is_rejected(self) -> None:
        # Attempt to pass a feature with org_intruder into an org_acme request
        with pytest.raises((MLTenantIsolationError, PredictionTenantIsolationError)):
            PredictionRequest(
                prediction_id="pred_cross_inf",
                organization_id="org_acme",
                prediction_type=PredictionType.SHIPMENT_DELAY,
                target="shipment_delay_minutes",
                features=[
                    PredictionFeature(
                        feature_name="route_distance_km",
                        value=500.0,
                        source="route.distance",
                        source_type="database",
                        organization_id="org_intruder",  # Cross-tenant!
                    )
                ],
                risk_assessment_id="risk_assess_001",
            )

    # 11. Untrusted serialized artifacts cannot be loaded.
    def test_critical_11_untrusted_serialized_artifacts_cannot_be_loaded(self, tmp_path: Path) -> None:
        fake_artifact = tmp_path / "untrusted_payload.joblib"
        with open(fake_artifact, "wb") as f:
            f.write(b"MALICIOUS_UNTRUSTED_BYTE_SEQUENCE")

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(fake_artifact, base_dir=tmp_path)
        assert "Corrupted or invalid joblib artifact" in str(exc_info.value)

    # 12. Artifact fingerprint mismatch is rejected.
    def test_critical_12_artifact_fingerprint_mismatch_is_rejected(self, tmp_path: Path) -> None:
        _, registry = build_trained_service("org_acme", tmp_path=tmp_path)
        art_path = tmp_path / "shipment_delay_ridge_1.0.0_org_acme.joblib"
        if not art_path.exists():
            pytest.skip("Artifact path not on disk in this configuration")

        # Tamper with file
        with open(art_path, "ab") as f:
            f.write(b"\x00ROGUE")

        with pytest.raises(ModelArtifactError):
            ArtifactManager.load_artifact(art_path, base_dir=tmp_path)

    # 13. MAE/RMSE cannot be fabricated.
    def test_critical_13_mae_rmse_cannot_be_fabricated(self) -> None:
        # Negative MAE/RMSE is rejected by validation
        with pytest.raises(ModelValidationError):
            ModelMetrics(is_calculated=True, mae=-5.0, rmse=10.0)
        with pytest.raises(ModelValidationError):
            ModelMetrics(is_calculated=True, mae=5.0, rmse=-10.0)
        # NaN / Inf is rejected
        with pytest.raises(ModelValidationError):
            ModelMetrics(is_calculated=True, mae=float("nan"), rmse=10.0)
        with pytest.raises(ModelValidationError):
            ModelMetrics(is_calculated=True, mae=5.0, rmse=float("inf"))

    # 14. Uncertainty cannot be fabricated.
    def test_critical_14_uncertainty_cannot_be_fabricated(self) -> None:
        # PredictionUncertainty rejects inverted intervals or non-finite numbers
        with pytest.raises(Exception):
            PredictionUncertainty(
                prediction_interval=(100.0, 50.0),  # Inverted!
                method="TEST",
            )
        with pytest.raises(Exception):
            PredictionUncertainty(
                prediction_interval=(float("nan"), 50.0),  # NaN!
                method="TEST",
            )

    # 15. Model metadata cannot be fabricated.
    def test_critical_15_model_metadata_cannot_be_fabricated(self) -> None:
        # MLModelMetadata enforces extra="forbid" and validation
        with pytest.raises(Exception):
            MLModelMetadata(
                model_id="test_m",
                model_family=ModelFamily.SHIPMENT_DELAY,
                model_version="1.0.0",
                task_type=TaskType.REGRESSION,
                metrics=ModelMetrics(is_calculated=True, mae=10.0, rmse=15.0),
                fabricated_field="illegal_value",  # Forbidden extra field!
            )

    # 16. Feature schema mismatch fails safely.
    def test_critical_16_feature_schema_mismatch_fails_safely(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)

        # Missing required feature data handled safely with fitted imputation
        missing_feat = {"transport_mode": "AIR"}  # Omitted distance, lead time, etc.
        vec = pipe.transform_single(missing_feat)
        assert vec.shape == (1, 16)
        assert np.all(np.isfinite(vec))

    # 17. Model failure preserves existing authoritative state.
    def test_critical_17_model_failure_preserves_existing_authoritative_state(self) -> None:
        state = make_sample_graph_state(incident_id="inc_fail_safe_001", org_id="org_acme")
        empty_registry = ModelRegistry()
        service = MLPredictionService(registry=empty_registry)
        out_state = prediction_node(state, service=service)

        assert "input_reference" not in out_state
        assert "organization_id" not in out_state
        assert "prediction_result" in out_state
        assert out_state["prediction_result"]["status"] == PredictionStatus.NOT_AVAILABLE.value


    # 18. Deterministic mock requires no external service.
    def test_critical_18_deterministic_mock_requires_no_external_service(self) -> None:
        mock_svc = DeterministicMockPredictionService()
        req = PredictionRequest(
            prediction_id="pred_mock_001",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=make_valid_features("org_acme"),
            risk_assessment_id="risk_assess_001",
        )
        res1 = mock_svc.predict(req)
        res2 = mock_svc.predict(req)
        assert res1.predicted_value == res2.predicted_value
        assert res1.status == PredictionStatus.COMPLETED.value

    # 19. Same valid input/model produces deterministic behavior where specified.
    def test_critical_19_deterministic_behavior_on_identical_input(self) -> None:
        service, _ = build_trained_service("org_acme")
        req = PredictionRequest(
            prediction_id="pred_det_001",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=make_valid_features("org_acme"),
            risk_assessment_id="risk_assess_001",
        )
        res1 = service.predict(req)
        res2 = service.predict(req)
        assert res1.predicted_value == res2.predicted_value
        assert res1.uncertainty.prediction_interval == res2.uncertainty.prediction_interval
        assert res1.uncertainty.standard_error == res2.uncertainty.standard_error

    # 20. No database migration is created.
    def test_critical_20_no_database_migration_or_schema_mutation(self) -> None:
        # Verify Base.metadata has exactly 34 tables
        assert len(Base.metadata.tables) == 34
        # Verify alembic versions contains no new migration scripts
        alembic_versions_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
        py_migrations = [f for f in alembic_versions_dir.glob("*.py") if f.name != "__init__.py"]
        assert len(py_migrations) == 0, f"Found unexpected migrations: {py_migrations}"

    # End-to-End Integration
    def test_critical_end_to_end_ml_pipeline(self) -> None:
        """Complete workflow: raw operational data -> dataset validation -> feature engineering ->
        training -> artifact serialization -> registry -> inference -> PredictionResult -> Prediction Agent.
        """
        org_id = "org_acme"
        # 1. Historical data simulation
        rows = make_sample_rows(35)

        # 2. Dataset validation & time-aware split
        split = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id=org_id,
            dataset_id="ds_e2e",
            test_ratio=0.2,
            min_train_rows=20,
            min_test_rows=3,
        )
        assert len(split.train.rows) >= 20
        assert len(split.test.rows) >= 3

        # 3. Training pipeline
        pipeline = ShipmentDelayTrainingPipeline(
            config=MLConfig(min_training_rows=20, random_seed=42),
        )
        model, feat_pipeline, artifact, _ = pipeline.train_from_split(split=split)
        assert artifact.metadata.metrics.is_calculated is True

        # 4. Model Registry
        registry = ModelRegistry()
        registry.register_model(model, feat_pipeline, artifact.metadata)

        # 5. Inference Service
        service = MLPredictionService(registry=registry)
        assert service.is_available() is True

        # 6. Prediction Request
        req = PredictionRequest(
            prediction_id="pred_e2e_001",
            organization_id=org_id,
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=make_valid_features(org_id),
            risk_assessment_id="risk_assess_001",
        )
        pred_result = service.predict(req)
        assert pred_result.status == PredictionStatus.COMPLETED.value
        assert pred_result.predicted_value is not None
        assert pred_result.predicted_value >= 0.0

        # 7. Prediction Agent Node
        state = make_sample_graph_state(
            incident_id="inc_e2e_001",
            org_id=org_id,
        )
        updated_state = prediction_node(state, service=service)
        assert updated_state["prediction_result"] is not None
        assert updated_state["prediction_result"]["status"] == PredictionStatus.COMPLETED.value
        assert updated_state["prediction_result"]["predicted_value"] >= 0.0


