"""Unit tests for deterministic feature engineering and transformation pipelines."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.errors import FeatureEngineeringError, FeatureSchemaError
from app.ml.features.shipment_delay import (
    SHIPMENT_DELAY_SCHEMA,
    SUPPORTED_TRANSPORT_MODES,
    ShipmentDelayFeaturePipeline,
)
from tests.test_phase11_ml_dataset import make_sample_rows, make_valid_feature_dict


class TestShipmentDelayFeaturePipeline:
    def test_pipeline_fit_and_transform_dimensions(self) -> None:
        rows = make_sample_rows(25)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        assert pipeline.is_fitted is False

        pipeline.fit(rows)
        assert pipeline.is_fitted is True

        X = pipeline.transform(rows)
        assert isinstance(X, np.ndarray)
        assert X.shape[0] == 25
        # 11 numeric/boolean features + 5 one-hot mode categories = 16 columns
        assert X.shape[1] == 16
        assert np.all(np.isfinite(X))

    def test_transform_before_fit_raises_error(self) -> None:
        rows = make_sample_rows(5)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        with pytest.raises(FeatureEngineeringError) as exc_info:
            pipeline.transform(rows)
        assert "must be fitted before transform" in str(exc_info.value)

    def test_transform_single_before_fit_raises_error(self) -> None:
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        with pytest.raises(FeatureEngineeringError) as exc_info:
            pipeline.transform_single(make_valid_feature_dict(0))
        assert "must be fitted before transform_single" in str(exc_info.value)

    def test_transform_single_matches_batch_transform(self) -> None:
        rows = make_sample_rows(25)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        # Batch transform first row
        batch_out = pipeline.transform([rows[0]])
        # Single transform first row dict
        single_out = pipeline.transform_single(rows[0].features)

        assert np.allclose(batch_out, single_out, rtol=1e-5, atol=1e-8)

    def test_categorical_one_hot_encoding_supported_modes(self) -> None:
        rows = make_sample_rows(20)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        # Test each supported transport mode
        for mode in ["OCEAN", "AIR", "RAIL", "ROAD"]:
            feat = make_valid_feature_dict(0)
            feat["transport_mode"] = mode
            vec = pipeline.transform_single(feat)[0]
            # Categorical slice is the last 5 elements
            cat_slice = vec[-len(SUPPORTED_TRANSPORT_MODES):]
            expected_idx = SUPPORTED_TRANSPORT_MODES.index(mode)
            assert cat_slice[expected_idx] == 1.0
            assert np.sum(cat_slice) == 1.0

    def test_unknown_categorical_mode_fallback(self) -> None:
        rows = make_sample_rows(20)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        feat = make_valid_feature_dict(0)
        feat["transport_mode"] = "SPACE_SHUTTLE"  # Unknown!
        vec = pipeline.transform_single(feat)[0]
        cat_slice = vec[-len(SUPPORTED_TRANSPORT_MODES):]
        unknown_idx = SUPPORTED_TRANSPORT_MODES.index("UNKNOWN")
        assert cat_slice[unknown_idx] == 1.0
        assert np.sum(cat_slice) == 1.0

    def test_feature_aliases_support(self) -> None:
        rows = make_sample_rows(20)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        # Provide feature dict using PredictionFeatureExtractor aliases
        aliased_dict = {
            "transport_mode": "AIR",
            "scheduled_transit_hours": 18.0,  # alias for planned_duration_hours
            "route_distance_km": 1200.0,
            "route_lead_time_days": 2.0,
            "risk_composite_score": 45.0,  # alias for route_risk_score
            "carrier_on_time_reliability": 0.95,  # alias for carrier_reliability
            "origin_congestion": 10.0,
            "destination_congestion": 5.0,
            "events_count_before_cutoff": 1.0,
            "intermediate_delays_before_cutoff": 0.0,
            "weather_disruption_detected": 1.0,  # alias for weather_disruption_flag
            "port_disruption_detected": 0.0,  # alias for port_disruption_flag
        }

        X = pipeline.transform_single(aliased_dict)
        assert X.shape == (1, 16)
        assert np.all(np.isfinite(X))

    def test_non_finite_feature_raises_error(self) -> None:
        rows = make_sample_rows(20)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        bad_dict = make_valid_feature_dict(0)
        bad_dict["route_distance_km"] = float("inf")
        with pytest.raises(FeatureEngineeringError) as exc_info:
            pipeline.transform_single(bad_dict)
        assert "Non-finite value for feature 'route_distance_km'" in str(exc_info.value)

    def test_nan_feature_raises_error(self) -> None:
        rows = make_sample_rows(20)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        bad_dict = make_valid_feature_dict(0)
        bad_dict["route_risk_score"] = float("nan")
        with pytest.raises(FeatureEngineeringError) as exc_info:
            pipeline.transform_single(bad_dict)
        assert "Non-finite value for feature 'route_risk_score'" in str(exc_info.value)

    def test_fit_empty_rows_raises_error(self) -> None:
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        with pytest.raises(FeatureEngineeringError) as exc_info:
            pipeline.fit([])
        assert "Cannot fit feature pipeline on 0 rows" in str(exc_info.value)


    def test_feature_names_and_output_dimension(self) -> None:
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        out_names = pipeline.get_output_feature_names()
        assert len(out_names) == 16
        assert "mode_OCEAN" in out_names
        assert "mode_AIR" in out_names
        assert "mode_UNKNOWN" in out_names
        assert "planned_duration_hours" in out_names

    def test_pipeline_determinism_identical_input(self) -> None:
        rows = make_sample_rows(25)
        pipeline1 = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline1.fit(rows)

        pipeline2 = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline2.fit(rows)

        feat = make_valid_feature_dict(42)
        out1 = pipeline1.transform_single(feat)
        out2 = pipeline2.transform_single(feat)

        assert np.array_equal(out1, out2)

    def test_missing_feature_imputes_with_fitted_mean(self) -> None:
        rows = make_sample_rows(25)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(rows)

        feat = make_valid_feature_dict(0)
        del feat["origin_congestion"]  # Omit optional/missing feature

        out = pipeline.transform_single(feat)
        assert out.shape == (1, 16)
        assert np.all(np.isfinite(out))

