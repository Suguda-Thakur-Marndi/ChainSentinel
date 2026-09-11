"""Dataset validation with strict temporal leakage and data quality checks.

Prevents training on malformed, corrupted, cross-tenant, or temporally leaked datasets.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Set

from app.ml.contracts import FeatureSchema, FeatureType
from app.ml.datasets.contracts import DatasetRow, ValidatedDataset, compute_dataset_fingerprint
from app.ml.errors import (
    DataLeakageError,
    DatasetValidationError,
    InsufficientTrainingDataError,
    MLTenantIsolationError,
)

# Explicit prohibited leakage columns that would only be known after shipment outcome
PROHIBITED_LEAKAGE_COLUMNS = {
    "actual_delivery_time",
    "final_delivery_delay",
    "delivery_timestamp",
    "actual_arrival_time",
    "final_arrival_time",
    "post_outcome_delay",
    "delivered_status",
    "post_delivery_corrective_action",
    "carrier_penalty_applied",
}


class DatasetValidator:
    """Validates data quality, integrity, tenant isolation, and temporal non-leakage."""

    @classmethod
    def validate_dataset(
        cls,
        rows: List[DatasetRow],
        schema: FeatureSchema,
        organization_id: str,
        dataset_id: str,
        min_rows: int = 20,
        is_training: bool = True,
        source_info: str = "operational_shipments",
    ) -> ValidatedDataset:
        """Validate an observation set against a FeatureSchema.

        Raises:
            MLTenantIsolationError: If tenant isolation is breached.
            InsufficientTrainingDataError: If rows < min_rows.
            DataLeakageError: If future/target information leaks into features.
            DatasetValidationError: If schema, column, or nullability invariants are violated.
        """
        if not organization_id or not organization_id.strip():
            raise MLTenantIsolationError("organization_id must be non-empty for dataset validation.")

        if not rows:
            raise InsufficientTrainingDataError(
                f"Dataset '{dataset_id}' has 0 rows. Minimum required is {min_rows}."
            )

        if len(rows) < min_rows:
            raise InsufficientTrainingDataError(
                f"Dataset '{dataset_id}' contains {len(rows)} rows, which is less than "
                f"the minimum required threshold of {min_rows} rows for reliable training."
            )

        seen_ids: Set[str] = set()
        expected_features = {f.name: f for f in schema.features}

        # 1. Prohibited leakage check in schema features
        for f in schema.features:
            lower_name = f.name.lower().strip()
            if lower_name in PROHIBITED_LEAKAGE_COLUMNS or "delivery_delay" in lower_name:
                raise DataLeakageError(
                    f"Feature '{f.name}' violates temporal leakage boundary. "
                    "Features must only represent information known prior to prediction."
                )

        # 2. Row by row validation
        for idx, row in enumerate(rows):
            # Tenant isolation
            if row.organization_id != organization_id:
                raise MLTenantIsolationError(
                    f"Row at index {idx} (record '{row.record_id}') belongs to tenant '{row.organization_id}', "
                    f"violating dataset organization_id '{organization_id}'."
                )

            # Duplicate check
            if row.record_id in seen_ids:
                raise DatasetValidationError(
                    f"Duplicate record_id '{row.record_id}' detected at index {idx}."
                )
            seen_ids.add(row.record_id)

            # Target check for training
            if is_training:
                if row.target is None:
                    raise DatasetValidationError(
                        f"Target value '{schema.target_name}' is None for training row '{row.record_id}'."
                    )
                if math.isnan(row.target) or math.isinf(row.target):
                    raise DatasetValidationError(
                        f"Target value for row '{row.record_id}' is non-finite ({row.target})."
                    )
                if schema.target_name == "delay_minutes" and row.target < 0.0:
                    raise DatasetValidationError(
                        f"Target value '{schema.target_name}' cannot be negative ({row.target}) for row '{row.record_id}'."
                    )

            # Feature columns and types check
            for feat_name, spec in expected_features.items():
                if feat_name not in row.features:
                    raise DatasetValidationError(
                        f"Required feature '{feat_name}' missing from row '{row.record_id}'."
                    )
                val = row.features[feat_name]
                if val is None:
                    raise DatasetValidationError(
                        f"Feature '{feat_name}' in row '{row.record_id}' has unhandled None value."
                    )

                if spec.feature_type == FeatureType.NUMERIC:
                    if not isinstance(val, (int, float)) or isinstance(val, bool):
                        raise DatasetValidationError(
                            f"Numeric feature '{feat_name}' has non-numeric value '{val}' (type: {type(val).__name__}) in row '{row.record_id}'."
                        )
                    if math.isnan(float(val)) or math.isinf(float(val)):
                        raise DatasetValidationError(
                            f"Numeric feature '{feat_name}' has non-finite value in row '{row.record_id}'."
                        )

                elif spec.feature_type == FeatureType.CATEGORICAL:
                    if not isinstance(val, str):
                        raise DatasetValidationError(
                            f"Categorical feature '{feat_name}' has non-string value in row '{row.record_id}'."
                        )

                elif spec.feature_type == FeatureType.BOOLEAN:
                    if not (isinstance(val, bool) or val in (0, 1, 0.0, 1.0)):
                        raise DatasetValidationError(
                            f"Boolean feature '{feat_name}' has invalid type in row '{row.record_id}'."
                        )

            # Prohibited future leakage in row.features
            for k in row.features.keys():
                if k.lower() in PROHIBITED_LEAKAGE_COLUMNS:
                    raise DataLeakageError(
                        f"Forbidden post-outcome feature '{k}' detected in row '{row.record_id}'."
                    )

        # 3. Construct validated dataset
        dataset_fingerprint = compute_dataset_fingerprint(
            dataset_id=dataset_id,
            organization_id=organization_id,
            target_name=schema.target_name,
            rows=rows,
        )

        return ValidatedDataset(
            dataset_id=dataset_id,
            organization_id=organization_id,
            feature_names=schema.feature_names,
            target_name=schema.target_name,
            row_count=len(rows),
            dataset_version=schema.version,
            source_info=source_info,
            schema_fingerprint=schema.schema_fingerprint,
            dataset_fingerprint=dataset_fingerprint,
            validation_status="VALIDATED",
            rows=rows,
        )
