"""Unit tests for temporal data leakage defenses and time-aware dataset splitting."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.ml.contracts import FeatureSchema, FeatureSpec, FeatureType
from app.ml.datasets.builder import ShipmentDatasetBuilder
from app.ml.datasets.contracts import DatasetRow
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import DataLeakageError, InsufficientTrainingDataError
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA
from tests.test_phase11_ml_dataset import make_sample_rows, make_valid_feature_dict


class TestTemporalLeakageDefense:
    @pytest.mark.parametrize(
        "prohibited_col",
        [
            "actual_delivery_time",
            "final_delivery_delay",
            "delivery_timestamp",
            "actual_arrival_time",
            "final_arrival_time",
            "post_outcome_delay",
            "delivered_status",
            "post_delivery_corrective_action",
            "carrier_penalty_applied",
        ],
    )
    def test_prohibited_future_features_in_schema_rejected(self, prohibited_col: str) -> None:
        """Mandatory Invariant: No future post-outcome information can leak into feature definitions."""
        leaky_specs = list(SHIPMENT_DELAY_SCHEMA.features) + [
            FeatureSpec(
                name=prohibited_col,
                feature_type=FeatureType.NUMERIC,
                source_field=f"shipment.{prohibited_col}",
            )
        ]
        leaky_schema = FeatureSchema(
            version="leaky_v1",
            features=leaky_specs,
            target_name="delay_minutes",
        )
        rows = make_sample_rows(25)

        with pytest.raises(DataLeakageError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=leaky_schema,
                organization_id="org_acme",
                dataset_id="ds_leaky_schema",
                min_rows=20,
            )
        assert "violates temporal leakage boundary" in str(exc_info.value)

    def test_prohibited_future_column_in_row_features_rejected(self) -> None:
        """Mandatory Invariant: Even if schema does not list it, row dictionary containing post-outcome data is blocked."""
        rows = make_sample_rows(25)
        # Inject future field into row 0
        leaky_features = dict(rows[0].features)
        leaky_features["final_delivery_delay"] = 120.0
        leaky_row = DatasetRow(
            record_id=rows[0].record_id,
            organization_id=rows[0].organization_id,
            timestamp=rows[0].timestamp,
            features=leaky_features,
            target=rows[0].target,
        )
        rows[0] = leaky_row

        with pytest.raises(DataLeakageError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_leaky_row",
                min_rows=20,
            )
        assert "Forbidden post-outcome feature 'final_delivery_delay' detected" in str(exc_info.value)

    def test_cutoff_time_violation_in_row_builder_raises_error(self) -> None:
        """Row creation after cutoff timestamp violates inference boundary."""
        cutoff = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
        future_time = datetime(2026, 9, 6, 8, 0, tzinfo=timezone.utc)

        with pytest.raises(DataLeakageError) as exc_info:
            ShipmentDatasetBuilder.create_row_from_shipment(
                shipment_id="ship_future_01",
                organization_id="org_acme",
                created_at=future_time,
                features=make_valid_feature_dict(0),
                target_delay_minutes=25.0,
                cutoff_time=cutoff,
            )
        assert "is after inference cutoff" in str(exc_info.value)

    def test_time_aware_split_strictly_preserves_chronological_ordering(self) -> None:
        """Time-aware split ensures train timestamps strictly precede test timestamps."""
        rows = make_sample_rows(30, org_id="org_acme")
        split_data = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_time_split",
            test_ratio=0.2,
            val_ratio=0.1,
            min_train_rows=15,
            min_test_rows=3,
        )

        train_max_time = max(r.timestamp for r in split_data.train.rows)
        test_min_time = min(r.timestamp for r in split_data.test.rows)

        assert train_max_time <= test_min_time
        assert split_data.train.row_count > 0
        assert split_data.test.row_count >= 3
        if split_data.val:
            val_min_time = min(r.timestamp for r in split_data.val.rows)
            val_max_time = max(r.timestamp for r in split_data.val.rows)
            assert train_max_time <= val_min_time
            assert val_max_time <= test_min_time

    def test_time_aware_split_fails_if_insufficient_train_rows(self) -> None:
        """Fails closed if the chronological train partition has fewer than min_train_rows."""
        rows = make_sample_rows(15, org_id="org_acme")
        with pytest.raises(InsufficientTrainingDataError) as exc_info:
            ShipmentDatasetBuilder.time_aware_split(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_insufficient",
                test_ratio=0.3,
                min_train_rows=15,
            )
        assert "Insufficient historical data" in str(exc_info.value)
