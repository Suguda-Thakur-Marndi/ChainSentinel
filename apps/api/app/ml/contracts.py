"""Strongly typed contracts for the RiskWise ML subsystem.

Enforces Pydantic v2 validation, extra="forbid", frozen immutability where appropriate,
reproducible fingerprints, and prevents metric or uncertainty fabrication.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import validate_no_forbidden_keys, validate_no_sensitive_values
from app.ml.errors import MLValidationError, ModelValidationError


class TaskType(str, Enum):
    """Machine learning prediction task categories."""

    REGRESSION = "REGRESSION"
    CLASSIFICATION = "CLASSIFICATION"


class ModelFamily(str, Enum):
    """Machine learning model families across the RiskWise roadmap."""

    SHIPMENT_DELAY = "SHIPMENT_DELAY"
    SUPPLIER_RISK = "SUPPLIER_RISK"
    DISRUPTION_PREDICTION = "DISRUPTION_PREDICTION"
    DEMAND_FORECASTING = "DEMAND_FORECASTING"
    STOCKOUT_PREDICTION = "STOCKOUT_PREDICTION"


class DatasetSplit(str, Enum):
    """Dataset partition types."""

    TRAIN = "TRAIN"
    VAL = "VAL"
    TEST = "TEST"


class ModelStatus(str, Enum):
    """Status flags for models in registry or inference services."""

    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"


class FeatureType(str, Enum):
    """Data types for feature columns."""

    NUMERIC = "NUMERIC"
    CATEGORICAL = "CATEGORICAL"
    BOOLEAN = "BOOLEAN"


class FeatureSpec(BaseModel):
    """Specification of a single engineered feature."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(..., min_length=1, max_length=128)
    feature_type: FeatureType
    unit: Optional[str] = Field(default=None, max_length=32)
    description: str = Field(default="", max_length=256)
    source_field: str = Field(..., min_length=1, max_length=128)
    missing_value_strategy: str = Field(default="zero", max_length=64)
    allow_future_leakage: bool = Field(default=False)

    @model_validator(mode="after")
    def validate_no_leakage_permission(self) -> "FeatureSpec":
        if self.allow_future_leakage:
            raise MLValidationError(f"Feature '{self.name}' cannot set allow_future_leakage=True.")
        return self


def compute_schema_fingerprint(features: List[FeatureSpec], target_name: str) -> str:
    """Deterministic SHA-256 fingerprint for a feature schema."""
    parts = [f"target:{target_name}"]
    for f in sorted(features, key=lambda x: x.name):
        parts.append(f"{f.name}:{f.feature_type.value}:{f.unit or 'none'}:{f.source_field}")
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FeatureSchema(BaseModel):
    """Complete specification of input features and target for a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(..., min_length=1, max_length=64)
    features: List[FeatureSpec] = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1, max_length=64)
    target_type: FeatureType = Field(default=FeatureType.NUMERIC)
    schema_fingerprint: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _ensure_fingerprint(cls, data: Any) -> Any:
        if isinstance(data, dict):
            feats = data.get("features", [])
            target = data.get("target_name", "")
            if not data.get("schema_fingerprint") and feats and target:
                spec_objs = [f if isinstance(f, FeatureSpec) else FeatureSpec(**f) for f in feats]
                data["schema_fingerprint"] = compute_schema_fingerprint(spec_objs, target)
        return data

    @property
    def feature_names(self) -> List[str]:
        return [f.name for f in self.features]


class ModelMetrics(BaseModel):
    """True evaluated model performance metrics. Never fabricated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2: Optional[float] = None
    sample_count: int = Field(default=0, ge=0)
    is_calculated: bool = Field(default=False)

    @field_validator("mae", "rmse", "r2", mode="after")
    @classmethod
    def validate_metric_values(cls, v: Optional[float], info: Any) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ModelValidationError(f"Metric '{info.field_name}' must be a finite number.")
            if info.field_name in ("mae", "rmse") and v < 0.0:
                raise ModelValidationError(f"Metric '{info.field_name}' cannot be negative.")
        return v

    @model_validator(mode="after")
    def validate_calculation_status(self) -> "ModelMetrics":
        if (self.mae is not None or self.rmse is not None) and not self.is_calculated:
            raise ModelValidationError("ModelMetrics has values but is_calculated is False.")
        return self


class MLModelMetadata(BaseModel):
    """Metadata describing a trained ML model artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(..., min_length=1, max_length=128)
    model_family: ModelFamily
    model_version: str = Field(..., min_length=1, max_length=64)
    task_type: TaskType = Field(default=TaskType.REGRESSION)
    target: str = Field(default="delay_minutes", min_length=1, max_length=64)
    feature_names: List[str] = Field(default_factory=list)
    feature_schema_fingerprint: str = Field(default="")
    training_dataset_fingerprint: str = Field(default="", min_length=1)
    training_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    preprocessing_version: str = Field(default="1.0.0", min_length=1)
    hyperparameters: Dict[str, Any] = Field(default_factory=dict)
    validation_status: str = Field(default="VALIDATED")
    metrics: ModelMetrics
    artifact_fingerprint: str = Field(default="", min_length=1)
    organization_id: Optional[str] = Field(default=None, max_length=64)
    is_production: bool = Field(default=False)


    @field_validator("hyperparameters", mode="after")
    @classmethod
    def validate_hyperparams_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "MLModelMetadata.hyperparameters")
        for val in v.values():
            if isinstance(val, str):
                validate_no_sensitive_values(val, "MLModelMetadata.hyperparameters")
        return v


def compute_artifact_fingerprint(
    model_id: str,
    model_version: str,
    dataset_fingerprint: str,
    feature_names: List[str],
    serialized_weights_bytes: bytes,
) -> str:
    """Compute deterministic SHA-256 digest of model artifact and its weights."""
    hasher = hashlib.sha256()
    hasher.update(f"{model_id}:{model_version}:{dataset_fingerprint}:".encode("utf-8"))
    hasher.update(",".join(sorted(feature_names)).encode("utf-8"))
    hasher.update(b":")
    hasher.update(serialized_weights_bytes)
    return hasher.hexdigest()


class ModelArtifact(BaseModel):
    """Container holding model metadata, schema, and serialized pipeline bytes."""

    model_config = ConfigDict(extra="forbid")

    metadata: MLModelMetadata
    feature_schema: FeatureSchema
    serialized_pipeline: bytes
    artifact_fingerprint: str

    @model_validator(mode="after")
    def verify_fingerprint_match(self) -> "ModelArtifact":
        if self.metadata.artifact_fingerprint != self.artifact_fingerprint:
            raise ModelValidationError(
                f"Artifact fingerprint mismatch: metadata={self.metadata.artifact_fingerprint} "
                f"vs container={self.artifact_fingerprint}."
            )
        return self
