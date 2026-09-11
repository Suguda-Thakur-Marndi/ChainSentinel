"""Dataset builder for shipment delay prediction.

Constructs strongly typed dataset rows from operational shipment entities,
ensuring strict temporal ordering and non-leakage time-aware partitioning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.ml.contracts import FeatureSchema
from app.ml.datasets.contracts import DatasetRow, DatasetSplitData, ValidatedDataset
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import DataLeakageError, InsufficientTrainingDataError


class ShipmentDatasetBuilder:
    """Constructs and splits datasets for shipment delay regression."""

    @staticmethod
    def create_row_from_shipment(
        shipment_id: str,
        organization_id: str,
        created_at: datetime,
        features: Dict[str, Any],
        target_delay_minutes: Optional[float] = None,
        cutoff_time: Optional[datetime] = None,
    ) -> DatasetRow:
        """Create a single DatasetRow, verifying that no event features exceed cutoff_time."""
        if cutoff_time and created_at > cutoff_time:
            raise DataLeakageError(
                f"Shipment '{shipment_id}' creation time {created_at} is after inference cutoff {cutoff_time}."
            )

        return DatasetRow(
            record_id=shipment_id,
            organization_id=organization_id,
            timestamp=created_at,
            features=features,
            target=target_delay_minutes,
        )

    @classmethod
    def time_aware_split(
        cls,
        rows: List[DatasetRow],
        schema: FeatureSchema,
        organization_id: str,
        dataset_id: str,
        test_ratio: float = 0.2,
        val_ratio: float = 0.1,
        min_train_rows: int = 15,
        min_test_rows: int = 3,
    ) -> DatasetSplitData:
        """Partition observations chronologically into train, val, and test sets.

        CRITICAL LEAKAGE INVARIANT:
        Rows are ordered strictly by timestamp.
        Train period precedes Validation period, which precedes Test period.
        """
        if not rows:
            raise InsufficientTrainingDataError(f"No rows available for dataset '{dataset_id}'.")

        # Sort chronologically by timestamp
        sorted_rows = sorted(rows, key=lambda r: (r.timestamp, r.record_id))
        total_rows = len(sorted_rows)

        test_count = max(min_test_rows, int(total_rows * test_ratio))
        val_count = int(total_rows * val_ratio) if val_ratio > 0 else 0
        train_count = total_rows - test_count - val_count

        if train_count < min_train_rows:
            raise InsufficientTrainingDataError(
                f"Insufficient historical data: total {total_rows} rows yields only {train_count} "
                f"training observations (minimum required is {min_train_rows})."
            )

        train_rows = sorted_rows[:train_count]
        val_rows = sorted_rows[train_count : train_count + val_count] if val_count > 0 else []
        test_rows = sorted_rows[train_count + val_count :]

        # Verify temporal boundary (latest train <= earliest test)
        if train_rows and test_rows:
            max_train_time = max(r.timestamp for r in train_rows)
            min_test_time = min(r.timestamp for r in test_rows)
            if max_train_time > min_test_time:
                raise DataLeakageError(
                    f"Temporal leakage in partition: max train timestamp {max_train_time} "
                    f"exceeds min test timestamp {min_test_time}."
                )

        train_dataset = DatasetValidator.validate_dataset(
            rows=train_rows,
            schema=schema,
            organization_id=organization_id,
            dataset_id=f"{dataset_id}_train",
            min_rows=min_train_rows,
            is_training=True,
            source_info="time_split_train",
        )

        val_dataset: Optional[ValidatedDataset] = None
        if val_rows:
            val_dataset = DatasetValidator.validate_dataset(
                rows=val_rows,
                schema=schema,
                organization_id=organization_id,
                dataset_id=f"{dataset_id}_val",
                min_rows=1,
                is_training=True,
                source_info="time_split_val",
            )

        test_dataset = DatasetValidator.validate_dataset(
            rows=test_rows,
            schema=schema,
            organization_id=organization_id,
            dataset_id=f"{dataset_id}_test",
            min_rows=min_test_rows,
            is_training=True,
            source_info="time_split_test",
        )

        return DatasetSplitData(
            train=train_dataset,
            val=val_dataset,
            test=test_dataset,
        )
