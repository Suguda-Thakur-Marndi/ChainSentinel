"""Unit tests for ML dataset validation, data quality, tenant isolation, and row integrity."""

from __future__ import annotations

import math
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.ml.datasets.contracts import DatasetRow, compute_dataset_fingerprint
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import (
    DatasetValidationError,
    InsufficientTrainingDataError,
    MLTenantIsolationError,
)
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA


def make_valid_feature_dict(i: int = 0) -> dict:
    return {
        "transport_mode": "OCEAN",
        "planned_duration_hours": 48.0 + i,
        "route_distance_km": 1500.0 + (i * 10),
        "route_lead_time_days": 5.0,
        "route_risk_score": 25.0,
        "carrier_reliability": 0.92,
        "origin_congestion": 10.0,
        "destination_congestion": 5.0,
        "events_count_before_cutoff": 3.0,
        "intermediate_delays_before_cutoff": 0.0,
        "weather_disruption_flag": 0.0,
        "port_disruption_flag": 0.0,
    }


def make_sample_rows(count: int = 25, org_id: str = "org_acme") -> list[DatasetRow]:
    rows = []
    base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    for i in range(count):
        row_time = datetime.fromtimestamp(base_time.timestamp() + i * 3600, tz=timezone.utc)
        rows.append(
            DatasetRow(
                record_id=f"rec_shipment_{i:04d}",
                organization_id=org_id,
                timestamp=row_time,
                features=make_valid_feature_dict(i),
                target=15.0 + (i * 0.5),
            )
        )
    return rows


class TestDatasetValidation:
    def test_valid_dataset_validation_passes(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        dataset = DatasetValidator.validate_dataset(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_test_01",
            min_rows=20,
            is_training=True,
        )
        assert dataset.row_count == 25
        assert dataset.dataset_id == "ds_test_01"
        assert dataset.organization_id == "org_acme"
        assert len(dataset.dataset_fingerprint) == 64
        assert dataset.validation_status == "VALIDATED"

    def test_insufficient_rows_raises_error(self) -> None:
        rows = make_sample_rows(10, org_id="org_acme")
        with pytest.raises(InsufficientTrainingDataError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_small",
                min_rows=20,
            )
        assert "less than the minimum required threshold of 20 rows" in str(exc_info.value)

    def test_zero_rows_raises_insufficient_data_error(self) -> None:
        with pytest.raises(InsufficientTrainingDataError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=[],
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_empty",
                min_rows=20,
            )
        assert "has 0 rows" in str(exc_info.value)

    def test_missing_required_feature_column_raises_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        # Corrupt one row by removing a required feature
        corrupted_dict = dict(rows[5].features)
        del corrupted_dict["route_distance_km"]
        corrupted_row = DatasetRow(
            record_id=rows[5].record_id,
            organization_id=rows[5].organization_id,
            timestamp=rows[5].timestamp,
            features=corrupted_dict,
            target=rows[5].target,
        )
        rows[5] = corrupted_row

        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_corrupted",
                min_rows=20,
            )
        assert "Required feature 'route_distance_km' missing" in str(exc_info.value)

    def test_invalid_feature_data_type_raises_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        # Put string inside numeric feature
        corrupted_dict = dict(rows[2].features)
        corrupted_dict["planned_duration_hours"] = "not_a_number"
        corrupted_row = DatasetRow(
            record_id=rows[2].record_id,
            organization_id=rows[2].organization_id,
            timestamp=rows[2].timestamp,
            features=corrupted_dict,
            target=rows[2].target,
        )
        rows[2] = corrupted_row

        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_bad_type",
                min_rows=20,
            )
        assert "has non-numeric value" in str(exc_info.value)

    def test_non_finite_numeric_feature_raises_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        corrupted_dict = dict(rows[3].features)
        corrupted_dict["route_risk_score"] = float("nan")
        corrupted_row = DatasetRow(
            record_id=rows[3].record_id,
            organization_id=rows[3].organization_id,
            timestamp=rows[3].timestamp,
            features=corrupted_dict,
            target=rows[3].target,
        )
        rows[3] = corrupted_row

        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_nan",
                min_rows=20,
            )
        assert "has non-finite value" in str(exc_info.value)

    def test_duplicate_record_ids_raises_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        # Duplicate row ID
        corrupted_row = DatasetRow(
            record_id=rows[0].record_id,  # Same as index 0!
            organization_id=rows[10].organization_id,
            timestamp=rows[10].timestamp,
            features=rows[10].features,
            target=rows[10].target,
        )
        rows[10] = corrupted_row

        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_dup",
                min_rows=20,
            )
        assert "Duplicate record_id" in str(exc_info.value)

    def test_missing_target_in_training_raises_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        corrupted_row = DatasetRow(
            record_id=rows[4].record_id,
            organization_id=rows[4].organization_id,
            timestamp=rows[4].timestamp,
            features=rows[4].features,
            target=None,  # Missing target!
        )
        rows[4] = corrupted_row

        with pytest.raises(DatasetValidationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_no_target",
                min_rows=20,
                is_training=True,
            )
        assert "Target value 'delay_minutes' is None" in str(exc_info.value)

    def test_tenant_mismatch_raises_isolation_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        # Inject foreign tenant in row 8
        corrupted_row = DatasetRow(
            record_id=rows[8].record_id,
            organization_id="org_competitor",
            timestamp=rows[8].timestamp,
            features=rows[8].features,
            target=rows[8].target,
        )
        rows[8] = corrupted_row

        with pytest.raises(MLTenantIsolationError) as exc_info:
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="org_acme",
                dataset_id="ds_cross_tenant",
                min_rows=20,
            )
        assert "belongs to tenant 'org_competitor'" in str(exc_info.value)

    def test_empty_organization_id_raises_isolation_error(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        with pytest.raises(MLTenantIsolationError):
            DatasetValidator.validate_dataset(
                rows=rows,
                schema=SHIPMENT_DELAY_SCHEMA,
                organization_id="",
                dataset_id="ds_empty_org",
                min_rows=20,
            )

    def test_dataset_fingerprint_is_deterministic(self) -> None:
        rows1 = make_sample_rows(25, org_id="org_acme")
        rows2 = make_sample_rows(25, org_id="org_acme")

        fp1 = compute_dataset_fingerprint("ds_1", "org_acme", "delay_minutes", rows1)
        fp2 = compute_dataset_fingerprint("ds_1", "org_acme", "delay_minutes", rows2)
        assert fp1 == fp2

    def test_validated_dataset_immutability(self) -> None:
        rows = make_sample_rows(25, org_id="org_acme")
        dataset = DatasetValidator.validate_dataset(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id="org_acme",
            dataset_id="ds_frozen",
            min_rows=20,
        )
        with pytest.raises(ValidationError):
            dataset.row_count = 50  # type: ignore
