"""Extensive edge-case, boundary, and robustness tests for the Phase 11 ML subsystem."""

from __future__ import annotations

from datetime import datetime, timezone
import numpy as np
import pytest

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.prediction.contract import (
    ModelMetadata as AgentModelMetadata,
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
    PredictionUncertainty,
)
from app.ml.config import MLConfig
from app.ml.contracts import (
    FeatureSchema,
    FeatureSpec,
    FeatureType,
    MLModelMetadata,
    ModelArtifact,
    ModelFamily,
    ModelMetrics,
    TaskType,
    compute_artifact_fingerprint,
    compute_schema_fingerprint,
)
from app.ml.datasets.builder import ShipmentDatasetBuilder
from app.ml.datasets.contracts import DatasetRow, compute_dataset_fingerprint
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import (
    DataLeakageError,
    DatasetValidationError,
    FeatureEngineeringError,
    FeatureSchemaError,
    InsufficientTrainingDataError,
    MLTenantIsolationError,
    ModelArtifactError,
    ModelInferenceError,
    ModelRegistryError,
    ModelTrainingError,
    ModelValidationError,
    PredictionOutputValidationError,
)
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.inference.service import MLPredictionService
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.registry.registry import ModelRegistry
from app.ml.training.artifacts import ArtifactManager
from app.ml.training.pipeline import ShipmentDelayTrainingPipeline
from tests.test_phase11_ml_dataset import make_sample_rows, make_valid_feature_dict


class TestMLEdgeCasesAndBoundaries:
    """Rigorous boundary and robustness checks across ML components."""

    # 1. Feature schema fingerprint permutation invariance
    def test_schema_fingerprint_invariant_to_feature_list_ordering(self) -> None:
        spec1 = FeatureSpec(name="planned_duration_hours", feature_type=FeatureType.NUMERIC, source_field="s1")
        spec2 = FeatureSpec(name="route_distance_km", feature_type=FeatureType.NUMERIC, source_field="s2")
        spec3 = FeatureSpec(name="transport_mode", feature_type=FeatureType.CATEGORICAL, source_field="s3")

        fp1 = compute_schema_fingerprint([spec1, spec2, spec3], "delay_minutes")
        fp2 = compute_schema_fingerprint([spec3, spec1, spec2], "delay_minutes")
        fp3 = compute_schema_fingerprint([spec2, spec3, spec1], "delay_minutes")

        assert fp1 == fp2 == fp3

    # 2. Dataset fingerprint canonical sorting & mutation sensitivity
    def test_dataset_fingerprint_canonical_sorting_and_mutation_sensitivity(self) -> None:
        rows = make_sample_rows(5)
        fp_ordered = compute_dataset_fingerprint("ds1", "org_acme", "delay_minutes", rows)
        fp_reversed = compute_dataset_fingerprint("ds1", "org_acme", "delay_minutes", list(reversed(rows)))
        # Canonical sorting guarantees order-invariant fingerprint for identical content
        assert fp_ordered == fp_reversed

        # Any record content mutation alters the fingerprint
        mutated_rows = list(rows)
        mutated_rows[0] = mutated_rows[0].model_copy(update={"target": 999.0})
        fp_mutated = compute_dataset_fingerprint("ds1", "org_acme", "delay_minutes", mutated_rows)
        assert fp_ordered != fp_mutated

    # 3. Exactly zero delay is a valid target value (no delay)
    def test_zero_delay_target_is_valid(self) -> None:
        rows = make_sample_rows(20)
        # Set all delays to exactly 0.0 (on-time delivery)
        on_time_rows = [r.model_copy(update={"target": 0.0}) for r in rows]
        validated = DatasetValidator.validate_dataset(
            rows=on_time_rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_zero_delays",
        )
        assert validated.row_count == 20
        assert all(r.target == 0.0 for r in validated.rows)

    # 4. Fractional delay minutes is valid
    def test_fractional_delay_target_is_valid(self) -> None:
        rows = make_sample_rows(20)
        frac_rows = [r.model_copy(update={"target": 12.345}) for r in rows]
        validated = DatasetValidator.validate_dataset(
            rows=frac_rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_frac_delays",
        )
        assert validated.row_count == 20
        assert validated.rows[0].target == 12.345

    # 5. Negative delay target in training data is rejected as invalid/impossible
    def test_negative_delay_target_rejected(self) -> None:
        rows = make_sample_rows(20)
        bad_rows = list(rows)
        bad_rows[0] = bad_rows[0].model_copy(update={"target": -15.0})

        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=bad_rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_neg_delay",
            )
        assert "cannot be negative" in str(exc_info.value)

    # 6. Chronological sorting handles out-of-order input rows deterministically
    def test_builder_sorts_out_of_order_rows_chronologically(self) -> None:
        rows = make_sample_rows(30)
        import random
        shuffled = list(rows)
        random.Random(42).shuffle(shuffled)

        split = ShipmentDatasetBuilder.time_aware_split(
            rows=shuffled,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_shuffled",
            test_ratio=0.2,
            val_ratio=0.1,
            min_train_rows=15,
            min_test_rows=3,
        )

        train_times = [r.timestamp for r in split.train.rows]
        val_times = [r.timestamp for r in split.val.rows]
        test_times = [r.timestamp for r in split.test.rows]

        # Train must be sorted
        assert train_times == sorted(train_times)
        # Validation must be sorted
        assert val_times == sorted(val_times)
        # Test must be sorted
        assert test_times == sorted(test_times)
        # Boundaries: max(train) <= min(val) <= min(test)
        assert max(train_times) <= min(val_times)
        assert max(val_times) <= min(test_times)

    # 7. Ridge regression varying alpha hyperparameter
    def test_model_handles_different_regularization_alphas(self) -> None:
        rows = make_sample_rows(30)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X = pipe.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        m_low_alpha = ShipmentDelayModel(alpha=0.01, random_seed=42).fit(X, y)
        m_high_alpha = ShipmentDelayModel(alpha=100.0, random_seed=42).fit(X, y)

        preds_low = m_low_alpha.predict(X)
        preds_high = m_high_alpha.predict(X)

        assert np.all(preds_low >= 0.0)
        assert np.all(preds_high >= 0.0)
        # High regularization pushes weights toward zero, producing different predictions
        assert not np.allclose(preds_low, preds_high)

    # 8. Single observation predict vs batch predict consistency
    def test_single_predict_matches_batch_predict(self) -> None:
        rows = make_sample_rows(30)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X = pipe.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        model = ShipmentDelayModel(alpha=1.0, random_seed=42).fit(X, y)

        batch_preds = model.predict(X[:5])
        single_preds = [model.predict_single(X[i]) for i in range(5)]

        assert np.allclose(batch_preds, single_preds, rtol=1e-5, atol=1e-8)

    # 9. Predict on empty feature matrix returns empty array
    def test_predict_on_empty_matrix(self) -> None:
        model = ShipmentDelayModel(random_seed=42)
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X = pipe.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)
        model.fit(X, y)

        empty_X = np.empty((0, 16))
        preds = model.predict(empty_X)
        assert isinstance(preds, np.ndarray)
        assert len(preds) == 0

    # 10. Fit on 0 rows raises ModelTrainingError
    def test_fit_on_zero_rows_raises_error(self) -> None:
        model = ShipmentDelayModel(random_seed=42)
        empty_X = np.empty((0, 16))
        empty_y = np.empty((0,))
        with pytest.raises(ModelTrainingError) as exc_info:
            model.fit(empty_X, empty_y)
        assert "Cannot fit model on 0 training rows" in str(exc_info.value)

    # 11. Fit with mismatched X and y dimensions raises ModelTrainingError
    def test_fit_mismatched_dimensions_raises_error(self) -> None:
        model = ShipmentDelayModel(random_seed=42)
        X = np.zeros((10, 16))
        y = np.zeros(5)
        with pytest.raises(ModelTrainingError) as exc_info:
            model.fit(X, y)
        assert "Row count mismatch" in str(exc_info.value)

    # 12. Extremely large valid dataset validation
    def test_large_dataset_validation_efficiency(self) -> None:
        rows = make_sample_rows(200)
        validated = DatasetValidator.validate_dataset(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_large_200",
        )
        assert validated.row_count == 200
        assert len(validated.dataset_fingerprint) == 64

    # 13. MLConfig safe path resolution detects path traversal
    def test_ml_config_path_traversal_detection(self) -> None:
        cfg = MLConfig(artifact_dir="storage/ml_artifacts")
        with pytest.raises(ModelArtifactError) as exc_info:
            cfg.get_artifact_path("../../etc/shadow")
        assert "Path traversal detected" in str(exc_info.value)

    # 14. MLModelMetadata rejects negative MAE and RMSE
    def test_model_metadata_rejects_negative_metrics(self) -> None:
        with pytest.raises(ModelValidationError):
            ModelMetrics(is_calculated=True, mae=-1.0, rmse=5.0)

    # 15. FeatureSpec rejects invalid missing value strategies
    def test_feature_spec_validates_type_and_name(self) -> None:
        with pytest.raises(Exception):
            FeatureSpec(name="", feature_type=FeatureType.NUMERIC, source_field="field")

    # 16. All transport modes encoded properly
    def test_all_transport_modes_encoding(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)

        for mode in ["OCEAN", "AIR", "RAIL", "ROAD", "UNKNOWN", "OTHER"]:
            feat = make_valid_feature_dict(0)
            feat["transport_mode"] = mode
            vec = pipe.transform_single(feat)
            assert vec.shape == (1, 16)
            assert np.all(np.isfinite(vec))

    # 17. Extreme numeric feature values
    def test_extreme_numeric_feature_values(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)

        feat = make_valid_feature_dict(0)
        feat["route_distance_km"] = 40000.0  # Earth circumference!
        feat["planned_duration_hours"] = 1000.0
        vec = pipe.transform_single(feat)
        assert vec.shape == (1, 16)
        assert np.all(np.isfinite(vec))

    # 18. All zeros numeric feature values
    def test_all_zeros_numeric_feature_values(self) -> None:
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)

        feat = {
            "transport_mode": "ROAD",
            "planned_duration_hours": 0.0,
            "route_distance_km": 0.0,
            "route_lead_time_days": 0.0,
            "route_risk_score": 0.0,
            "carrier_reliability": 0.0,
            "origin_congestion": 0.0,
            "destination_congestion": 0.0,
            "events_count_before_cutoff": 0.0,
            "intermediate_delays_before_cutoff": 0.0,
            "weather_disruption_flag": 0.0,
            "port_disruption_flag": 0.0,
        }
        vec = pipe.transform_single(feat)
        assert vec.shape == (1, 16)
        assert np.all(np.isfinite(vec))

    # 19. PredictionResult provenance and created_by_node consistency
    def test_prediction_result_node_metadata(self) -> None:
        res = PredictionResult(
            prediction_id="pred_meta_test",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            predicted_value=18.5,
            model_metadata=AgentModelMetadata(model_name="m", model_version="1.0.0"),
            status=PredictionStatus.COMPLETED.value,
        )
        assert res.created_by_node == "prediction_agent"
        assert res.unit == "minutes"
        assert res.predicted_value == 18.5

    # 20. Registry model listing with empty registry
    def test_registry_empty_listing(self) -> None:
        reg = ModelRegistry()
        assert reg.list_models() == []
        assert reg.get_active_model() is None

    # 21. Multiple model versions for same tenant in registry
    def test_registry_multiple_versions_retrieval(self) -> None:
        reg = ModelRegistry()
        rows = make_sample_rows(20)
        pipe = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA).fit(rows)
        X = pipe.transform(rows)
        y = np.array([r.target for r in rows], dtype=np.float64)

        m1 = ShipmentDelayModel("m_v1", model_version="1.0.0", random_seed=42).fit(X, y)
        meta1 = MLModelMetadata(
            model_id="m_v1",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="1.0.0",
            task_type=TaskType.REGRESSION,
            metrics=m1.evaluate(X, y),
            organization_id="org_acme",
            is_production=False,
        )
        reg.register_model(m1, pipe, meta1)

        m2 = ShipmentDelayModel("m_v2", model_version="2.0.0", random_seed=42).fit(X, y)
        meta2 = MLModelMetadata(
            model_id="m_v2",
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version="2.0.0",
            task_type=TaskType.REGRESSION,
            metrics=m2.evaluate(X, y),
            organization_id="org_acme",
            is_production=True,
        )
        reg.register_model(m2, pipe, meta2)

        # Active model selects production version (m_v2)
        active = reg.get_active_model(ModelFamily.SHIPMENT_DELAY, organization_id="org_acme")
        assert active is not None
        assert active[2].model_id == "m_v2"
        assert active[2].model_version == "2.0.0"

        # Explicit lookup retrieves exact version
        v1_entry = reg.get_model("m_v1", organization_id="org_acme")
        assert v1_entry is not None
        assert v1_entry[2].model_version == "1.0.0"

    # 22. Deterministic mock produces valid metrics and uncertainty
    def test_mock_service_produces_consistent_results(self) -> None:
        from app.agents.prediction.service import DeterministicMockPredictionService
        mock_svc = DeterministicMockPredictionService()
        req = PredictionRequest(
            prediction_id="pred_mock_det",
            organization_id="org_acme",
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="shipment_delay_minutes",
            features=[
                PredictionFeature(
                    feature_name="route_risk_score",
                    value=50.0,
                    source="risk",
                    source_type="risk_engine",
                    organization_id="org_acme",
                )
            ],
            risk_assessment_id="ra_001",
        )
        res = mock_svc.predict(req)
        assert res.status == PredictionStatus.COMPLETED.value
        assert res.predicted_value is not None
        assert res.predicted_value >= 0.0
        assert res.model_metadata.is_production is False
