"""Strongly typed contracts for the RiskWise Prediction Agent.

Defines PredictionRequest, PredictionResult, PredictionFeature, PredictionUncertainty,
and ModelMetadata — the typed boundary between the LangGraph orchestration layer
and ML prediction services.

Security & Architectural Invariants:
- extra="forbid" strictly rejects user-supplied predicted values, probabilities, or arbitrary outputs.
- Output predicted_value must be a finite non-negative number for delay_minutes.
- Uncertainty semantics must be explicit; confidence score is NEVER called a probability.
- All features must belong strictly to the same organization_id as the request.
- No secrets or credentials in features, metadata, or provenance.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import (
    AgentLimitation,
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.prediction.errors import (
    FeatureValidationError,
    InvalidModelOutputError,
    InvalidPredictionRequestError,
    PredictionTenantIsolationError,
)
from app.rag.contracts import RAG_UUID_NAMESPACE


class PredictionType(str, Enum):
    """Supported prediction task categories."""

    SHIPMENT_DELAY = "SHIPMENT_DELAY"


class PredictionStatus(str, Enum):
    """Execution status for prediction results."""

    COMPLETED = "COMPLETED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    INSUFFICIENT_FEATURES = "INSUFFICIENT_FEATURES"
    FAILED = "FAILED"


def generate_deterministic_prediction_id(
    organization_id: str,
    prediction_type: str,
    target_reference: str,
    feature_fingerprint: str,
    model_name: str,
    model_version: str,
) -> str:
    """Generate a reproducible UUIDv5 prediction identifier from stable inputs.

    Never incorporates volatile timestamps, request IDs, or trace IDs.
    """
    if not organization_id or not organization_id.strip():
        raise PredictionTenantIsolationError("organization_id must be non-empty to generate prediction_id")
    token = (
        f"{organization_id.strip()}:{prediction_type.strip()}:{target_reference.strip()}:"
        f"{feature_fingerprint.strip()}:{model_name.strip()}:{model_version.strip()}"
    )
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


class ModelMetadata(BaseModel):
    """Descriptive metadata for the prediction model.

    Distinguishes production models from deterministic test mocks.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_name: str = Field(..., min_length=1, max_length=128)
    model_version: str = Field(..., min_length=1, max_length=64)
    model_type: Optional[str] = Field(default=None, max_length=64)
    feature_version: Optional[str] = Field(default=None, max_length=64)
    training_data_version: Optional[str] = Field(default=None, max_length=64)
    is_production: bool = Field(default=False)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="after")
    @classmethod
    def validate_metadata_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "ModelMetadata.metadata")
        return v


class PredictionUncertainty(BaseModel):
    """Explicit representation of prediction uncertainty.

    IMPORTANT: A confidence_score is NEVER a calibrated statistical probability
    unless explicit empirical calibration evidence is documented.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_interval: Optional[Tuple[float, float]] = None
    confidence_interval: Optional[Tuple[float, float]] = None
    standard_error: Optional[float] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    method: str = Field(default="UNSPECIFIED", min_length=1, max_length=128)

    @field_validator("prediction_interval", "confidence_interval", mode="after")
    @classmethod
    def validate_intervals(cls, v: Optional[Tuple[float, float]], info: Any) -> Optional[Tuple[float, float]]:
        if v is not None:
            lower, upper = v
            if math.isnan(lower) or math.isinf(lower) or math.isnan(upper) or math.isinf(upper):
                raise InvalidModelOutputError(f"{info.field_name} boundaries must be finite numbers.")
            if lower > upper:
                raise InvalidModelOutputError(f"{info.field_name} lower bound ({lower}) cannot exceed upper bound ({upper}).")
        return v

    @field_validator("standard_error", mode="before")
    @classmethod
    def validate_standard_error(cls, v: Any) -> Optional[float]:
        if v is not None:
            try:
                val = float(v)
            except (ValueError, TypeError):
                raise InvalidModelOutputError("standard_error must be a valid float.")
            if math.isnan(val) or math.isinf(val):
                raise InvalidModelOutputError("standard_error must be a finite number.")
            if val < 0.0:
                raise InvalidModelOutputError("standard_error must be non-negative.")
            return val
        return None


class PredictionFeature(BaseModel):
    """A strongly typed feature input for the prediction service.

    Every feature maintains strict source provenance, tenant isolation, and units.
    Arbitrary unvalidated dictionaries are strictly forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    feature_name: str = Field(..., min_length=1, max_length=128)
    value: Union[float, int, str, bool]
    unit: Optional[str] = Field(default=None, max_length=32)
    source: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., min_length=1, max_length=64)
    timestamp: Optional[datetime] = None
    evidence_references: List[str] = Field(default_factory=list)
    organization_id: str = Field(..., min_length=1, max_length=64)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("value", mode="after")
    @classmethod
    def validate_feature_value(cls, v: Union[float, int, str, bool], info: Any) -> Union[float, int, str, bool]:
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                raise FeatureValidationError(f"Feature '{info.data.get('feature_name', 'unknown')}' has non-finite float value.")
        return v

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise FeatureValidationError("PredictionFeature organization_id must be a non-empty string.")
        return v.strip()

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "PredictionFeature.provenance")
        for val in v.values():
            if isinstance(val, str):
                validate_no_sensitive_values(val, "PredictionFeature.provenance")
        return v


class PredictionRequest(BaseModel):
    """Strongly typed request dispatched to a BasePredictionService.

    Strictly forbids client-injected predictions, arbitrary outputs, or cross-tenant features.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    prediction_type: PredictionType = Field(default=PredictionType.SHIPMENT_DELAY)
    target: str = Field(default="delay_minutes", min_length=1, max_length=64)
    shipment_id: Optional[str] = Field(default=None, max_length=64)
    risk_assessment_id: Optional[str] = Field(default=None, max_length=64)
    risk_assessment_reference: Optional[Dict[str, Any]] = None
    evidence_bundle_id: Optional[str] = Field(default=None, max_length=64)
    features: List[PredictionFeature] = Field(default_factory=list)
    prediction_horizon_hours: Optional[float] = None
    model_name: Optional[str] = Field(default=None, max_length=128)
    model_version: Optional[str] = Field(default=None, max_length=64)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    trace_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidPredictionRequestError("PredictionRequest organization_id must be a non-empty string.")
        return v.strip()

    @field_validator("prediction_horizon_hours", mode="before")
    @classmethod
    def validate_horizon(cls, v: Any) -> Optional[float]:
        if v is not None:
            try:
                val = float(v)
            except (ValueError, TypeError):
                raise InvalidPredictionRequestError("prediction_horizon_hours must be a valid float.")
            if math.isnan(val) or math.isinf(val):
                raise InvalidPredictionRequestError("prediction_horizon_hours must be a finite number.")
            if val < 0.0:
                raise InvalidPredictionRequestError("prediction_horizon_hours must be non-negative.")
            return val
        return None

    @model_validator(mode="after")
    def validate_tenant_consistency(self) -> "PredictionRequest":
        """Enforce absolute tenant isolation across all features and references."""
        for feat in self.features:
            if feat.organization_id != self.organization_id:
                raise PredictionTenantIsolationError(
                    f"Feature '{feat.feature_name}' tenant '{feat.organization_id}' "
                    f"does not match request organization_id '{self.organization_id}'."
                )

        if self.risk_assessment_reference:
            ref_org = self.risk_assessment_reference.get("organization_id")
            if ref_org and ref_org != self.organization_id:
                raise PredictionTenantIsolationError(
                    f"Risk assessment reference tenant '{ref_org}' does not match "
                    f"request organization_id '{self.organization_id}'."
                )
        return self


class PredictionResult(BaseModel):
    """Strongly typed output returned from a BasePredictionService.

    Output delay must be a non-negative finite number when status is COMPLETED.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    prediction_type: PredictionType = Field(default=PredictionType.SHIPMENT_DELAY)
    target: str = Field(default="delay_minutes", min_length=1, max_length=64)
    predicted_value: Optional[float] = None
    unit: str = Field(default="minutes", min_length=1, max_length=32)
    uncertainty: Optional[PredictionUncertainty] = None
    model_metadata: ModelMetadata
    feature_references: List[str] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)
    risk_assessment_reference: Optional[str] = Field(default=None, max_length=64)
    limitations: List[AgentLimitation] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default=PredictionStatus.COMPLETED.value, min_length=1, max_length=64)
    created_by_node: str = Field(default="prediction_agent", min_length=1, max_length=64)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("predicted_value", mode="after")
    @classmethod
    def validate_predicted_value(cls, v: Optional[float], info: Any) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise InvalidModelOutputError("predicted_value must be a finite number.")
            if v < 0.0:
                raise InvalidModelOutputError(f"predicted_value cannot be negative (got {v}).")
        return v

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidModelOutputError("PredictionResult organization_id must be non-empty.")
        return v.strip()

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "PredictionResult.provenance")
        for val in v.values():
            if isinstance(val, str):
                validate_no_sensitive_values(val, "PredictionResult.provenance")
        return v

    @model_validator(mode="after")
    def validate_status_value_consistency(self) -> "PredictionResult":
        """If status is COMPLETED, predicted_value must be present."""
        if self.status == PredictionStatus.COMPLETED.value and self.predicted_value is None:
            raise InvalidModelOutputError("PredictionResult with status COMPLETED must have a non-None predicted_value.")
        return self
