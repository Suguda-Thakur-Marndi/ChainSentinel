"""Contracts for ML datasets and data partitions."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ml.errors import DatasetValidationError, MLTenantIsolationError


class DatasetRow(BaseModel):
    """A single validated observation row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(..., min_length=1, max_length=128)
    organization_id: str = Field(..., min_length=1, max_length=64)
    timestamp: datetime
    features: Dict[str, Union[float, int, str, bool]]
    target: Optional[float] = None

    @field_validator("target", mode="after")
    @classmethod
    def validate_target_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise DatasetValidationError("Target value must be a finite number.")
        return v


def compute_dataset_fingerprint(
    dataset_id: str,
    organization_id: str,
    target_name: str,
    rows: List[DatasetRow],
) -> str:
    """Compute deterministic SHA-256 hash of dataset content."""
    hasher = hashlib.sha256()
    hasher.update(f"{dataset_id}:{organization_id}:{target_name}:{len(rows)}:".encode("utf-8"))
    for row in sorted(rows, key=lambda r: (r.timestamp, r.record_id)):
        feat_str = json.dumps(row.features, sort_keys=True)
        hasher.update(f"{row.record_id}:{row.timestamp.isoformat()}:{row.target}:{feat_str}\n".encode("utf-8"))
    return hasher.hexdigest()


class ValidatedDataset(BaseModel):
    """Immutable, validated dataset container ready for training or testing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(..., min_length=1, max_length=128)
    organization_id: str = Field(..., min_length=1, max_length=64)
    feature_names: List[str] = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1, max_length=64)
    row_count: int = Field(..., ge=1)
    dataset_version: str = Field(default="1.0.0", min_length=1)
    source_info: str = Field(default="operational_shipments", max_length=256)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    schema_fingerprint: str = Field(..., min_length=1)
    dataset_fingerprint: str = Field(..., min_length=1)
    validation_status: str = Field(default="VALIDATED")
    rows: List[DatasetRow] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_row_count_and_tenant(self) -> "ValidatedDataset":
        if len(self.rows) != self.row_count:
            raise DatasetValidationError(
                f"Row count mismatch: declared {self.row_count} but received {len(self.rows)} rows."
            )
        for r in self.rows:
            if r.organization_id != self.organization_id:
                raise MLTenantIsolationError(
                    f"Row '{r.record_id}' organization_id '{r.organization_id}' "
                    f"does not match dataset organization_id '{self.organization_id}'."
                )
        return self


class DatasetSplitData(BaseModel):
    """Time-aware partitioned dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    train: ValidatedDataset
    val: Optional[ValidatedDataset] = None
    test: ValidatedDataset
