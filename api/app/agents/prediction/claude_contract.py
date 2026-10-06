"""Strongly typed contracts for Claude Prediction Analysis & Explanation Layer (Phase 10 Step 6).

Enforces strict authority boundaries:
- The Phase 9 Prediction Agent / BasePredictionService deterministically creates authoritative PredictionResults.
- Claude acts exclusively as an explanatory layer that interprets what the prediction means.
- Claude never generates predictions, changes values, or recalculates uncertainty.
- Claude never turns NOT_AVAILABLE into an invented prediction.
- Claude never fabricates confidence scores, probability numbers, confidence intervals, or error metrics.
- All input snapshots provided to Claude are immutable (frozen).
- Claude structured output must conform strictly to ClaudePredictionExplanation (extra="forbid").
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import (
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.errors import AgentTenantIsolationError, AgentValidationError


class PredictionExplanationStatus(str, Enum):
    """Operational status of the Claude prediction explanation artifact."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    INVALID = "INVALID"
    UNSAFE = "UNSAFE"


# Prohibited chain-of-thought and internal monologue patterns
REASONING_TEXT_PATTERNS = [
    re.compile(r"chain[\s_]+of[\s_]+thought", re.IGNORECASE),
    re.compile(r"internal[\s_]+monologue", re.IGNORECASE),
    re.compile(r"private[\s_]+reasoning", re.IGNORECASE),
    re.compile(r"hidden[\s_]+reasoning", re.IGNORECASE),
]


def validate_no_reasoning_text(text: str, field_name: str = "field") -> None:
    """Ensure no chain-of-thought, internal monologue, or private reasoning is embedded."""
    validate_no_reasoning_content(text, field_name)
    if not text or not isinstance(text, str):
        return
    for pattern in REASONING_TEXT_PATTERNS:
        if pattern.search(text):
            raise AgentValidationError(
                f"Prohibited reasoning content detected in '{field_name}'."
            )


class PredictionFeatureExplanationInput(BaseModel):
    """Immutable snapshot of an authoritative prediction feature provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_name: str = Field(..., min_length=1, max_length=128, description="Feature name.")
    value: Union[float, int, str, bool] = Field(..., description="Authoritative feature value.")
    unit: Optional[str] = Field(default=None, max_length=32, description="Physical or business unit.")
    source: str = Field(..., min_length=1, max_length=128, description="Feature origin.")
    source_type: str = Field(..., min_length=1, max_length=64, description="Feature classification.")
    evidence_references: List[str] = Field(default_factory=list, description="Associated evidence IDs.")


class PredictionUncertaintyExplanationInput(BaseModel):
    """Immutable snapshot of authoritative prediction uncertainty values provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prediction_interval: Optional[Tuple[float, float]] = Field(default=None, description="Prediction interval (lower, upper).")
    confidence_interval: Optional[Tuple[float, float]] = Field(default=None, description="Confidence interval (lower, upper).")
    standard_error: Optional[float] = Field(default=None, description="Model standard error.")
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Model confidence score [0.0, 1.0].")
    method: str = Field(default="UNSPECIFIED", min_length=1, max_length=128, description="Uncertainty quantification method.")


class ModelMetadataExplanationInput(BaseModel):
    """Immutable snapshot of authoritative model metadata provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_name: str = Field(..., min_length=1, max_length=128, description="Model identifier.")
    model_version: str = Field(..., min_length=1, max_length=64, description="Model release version.")
    model_type: Optional[str] = Field(default=None, max_length=64, description="Model category.")
    feature_version: Optional[str] = Field(default=None, max_length=64, description="Feature set version.")
    training_data_version: Optional[str] = Field(default=None, max_length=64, description="Training dataset version.")
    is_production: bool = Field(default=False, description="Whether this is a live production model.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Safe model configuration metadata.")


class PredictionExplanationInput(BaseModel):
    """Strongly typed, immutable read-only snapshot of the authoritative PredictionResult.
    
    Passed into Claude prompt builder to guarantee zero mutation of authoritative prediction state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prediction_id: str = Field(..., min_length=1, max_length=64, description="Deterministic prediction ID.")
    organization_id: str = Field(..., min_length=1, max_length=64, description="Tenant organization scope.")
    prediction_type: str = Field(..., min_length=1, max_length=64, description="Prediction category (e.g., SHIPMENT_DELAY).")
    target: str = Field(default="delay_minutes", min_length=1, max_length=64, description="Prediction target metric.")
    status: str = Field(..., min_length=1, max_length=64, description="Authoritative execution status (e.g., COMPLETED, NOT_AVAILABLE).")
    predicted_value: Optional[float] = Field(default=None, description="Authoritative predicted numeric value if available.")
    unit: str = Field(default="minutes", min_length=1, max_length=32, description="Target physical unit.")
    prediction_horizon_hours: Optional[float] = Field(default=None, description="Forecast horizon duration.")
    uncertainty: Optional[PredictionUncertaintyExplanationInput] = Field(default=None, description="Authoritative uncertainty snapshot.")
    model_metadata: ModelMetadataExplanationInput = Field(..., description="Authoritative model metadata.")
    feature_references: List[str] = Field(default_factory=list, description="Names of features used.")
    features: List[PredictionFeatureExplanationInput] = Field(default_factory=list, description="Authoritative feature snapshots.")
    evidence_references: List[str] = Field(default_factory=list, description="All valid evidence IDs.")
    citation_references: List[str] = Field(default_factory=list, description="All valid citation keys.")
    risk_assessment_id: Optional[str] = Field(default=None, max_length=64, description="Upstream RiskAssessment ID.")
    risk_level: Optional[str] = Field(default=None, max_length=32, description="Upstream authoritative risk level.")
    risk_score: Optional[float] = Field(default=None, description="Upstream authoritative risk score.")
    limitations: List[str] = Field(default_factory=list, description="Authoritative caveats and limitations.")
    prediction_fingerprint: str = Field(..., min_length=1, max_length=64, description="Deterministic SHA-256 fingerprint.")
    objective: Optional[str] = Field(default=None, max_length=4096, description="Evaluation objective.")

    @field_validator("prediction_id", "organization_id", mode="after")
    @classmethod
    def validate_non_empty(cls, v: str, info: Any) -> str:
        if not v or not v.strip():
            raise AgentTenantIsolationError(f"{info.field_name} must be non-empty.")
        return v.strip()

    @field_validator("objective", mode="after")
    @classmethod
    def validate_objective_safety(cls, v: Optional[str]) -> Optional[str]:
        if v:
            validate_no_sensitive_values(v, "PredictionExplanationInput.objective")
            validate_no_reasoning_text(v, "PredictionExplanationInput.objective")
        return v


class FeatureExplanation(BaseModel):
    """Structured explanation of an authoritative prediction feature."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    feature_name: str = Field(..., min_length=1, max_length=128, description="Feature identifier.")
    explanation: str = Field(..., min_length=1, max_length=2048, description="Contextual role and meaning of this feature.")
    evidence_ids: List[str] = Field(default_factory=list, description="Supporting evidence references.")

    @field_validator("feature_name", "explanation", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"FeatureExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"FeatureExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"FeatureExplanation.{info.field_name}")
        return v


ClaudeFeatureExplanation = FeatureExplanation


class PredictionExplanation(BaseModel):
    """Provider-neutral Pydantic contract for structured response explaining a prediction."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    schema_version: str = Field(default="1.0.0", description="Contract schema version.")
    summary: str = Field(..., min_length=1, max_length=8192, description="Executive narrative explanation.")
    prediction_statement: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Clear description of the prediction output or its absence.",
    )
    status_statement: str = Field(
        default="COMPLETED",
        min_length=1,
        max_length=256,
        description="Reiteration of authoritative status.",
    )
    feature_explanations: List[FeatureExplanation] = Field(
        default_factory=list,
        description="Breakdowns of features.",
    )
    uncertainty_explanation: str = Field(
        default="Model uncertainty metrics unavailable.",
        min_length=1,
        max_length=4096,
        description="Explanation of model uncertainty or explicit statement that uncertainty is unavailable.",
    )
    risk_relationship: str = Field(
        default="Directly correlated with upstream risk factors.",
        min_length=1,
        max_length=2048,
        description="How prediction relates to upstream risk assessment.",
    )
    evidence_explanations: List[str] = Field(default_factory=list, description="Grounded evidence narratives.")
    limitations: List[str] = Field(default_factory=list, description="Known operational caveats.")
    citations: List[str] = Field(default_factory=list, description="All citation keys or evidence IDs referenced.")

    @model_validator(mode="before")
    @classmethod
    def unwrap_envelope(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 1. Unwrap top-level envelope if present
            for key in ("prediction_explanation", "explanation", "prediction", "data", "result", "output", "response"):
                if key in data and isinstance(data[key], dict) and "summary" not in data and "executive_summary" not in data:
                    data = dict(data[key])
                    break

            d = dict(data)
            # 2. Support safe semantic aliases
            if "summary" not in d:
                if "executive_summary" in d:
                    d["summary"] = d["executive_summary"]
                elif "narrative" in d:
                    d["summary"] = d["narrative"]
                elif "overview" in d:
                    d["summary"] = d["overview"]

            details = d.get("prediction_details")
            if isinstance(details, dict):
                if "prediction_statement" not in d:
                    d["prediction_statement"] = details.get("prediction_statement") or details.get("predicted_value_explanation")
                if "uncertainty_explanation" not in d and "uncertainty_explanation" in details:
                    d["uncertainty_explanation"] = details["uncertainty_explanation"]
                if "risk_relationship" not in d and "risk_assessment_relationship" in details:
                    d["risk_relationship"] = details["risk_assessment_relationship"]
                if "limitations" not in d and "model_limitations_caveats" in details:
                    lim = details["model_limitations_caveats"]
                    d["limitations"] = [lim] if isinstance(lim, str) else list(lim)

            if "prediction_statement" not in d:
                if "predicted_value_explanation" in d:
                    d["prediction_statement"] = d["predicted_value_explanation"]
                elif "statement" in d:
                    d["prediction_statement"] = d["statement"]
                elif "forecast_statement" in d:
                    d["prediction_statement"] = d["forecast_statement"]

            if "status_statement" not in d:
                if "prediction_status" in d:
                    d["status_statement"] = str(d["prediction_status"])
                elif "status" in d:
                    d["status_statement"] = str(d["status"])

            return d
        return data

    @field_validator(
        "summary",
        "prediction_statement",
        "status_statement",
        "uncertainty_explanation",
        "risk_relationship",
        mode="after",
    )
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"PredictionExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"PredictionExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"PredictionExplanation.{info.field_name}")
        return v

    @field_validator("limitations", "evidence_explanations", mode="after")
    @classmethod
    def validate_list_safety(cls, v: List[str], info: Any) -> List[str]:
        for idx, item in enumerate(v):
            validate_no_sensitive_values(item, f"PredictionExplanation.{info.field_name}[{idx}]")
            validate_no_reasoning_text(item, f"PredictionExplanation.{info.field_name}[{idx}]")
        return v


ClaudePredictionExplanation = PredictionExplanation


def compute_prediction_explanation_fingerprint(
    prediction_id: str,
    organization_id: str,
    summary: str,
    citations: List[str],
) -> str:
    """Generate deterministic SHA-256 semantic fingerprint for a prediction explanation."""
    sorted_citations = sorted(c.strip() for c in citations)
    payload = {
        "prediction_id": prediction_id.strip(),
        "organization_id": organization_id.strip(),
        "summary": summary.strip(),
        "citations": sorted_citations,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PredictionExplanationResult(BaseModel):
    """Canonical domain representation of the verified Claude prediction explanation.
    
    Stored in AgentGraphState as prediction_explanation.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_id: str = Field(..., min_length=1, max_length=64, description="Associated prediction ID.")
    organization_id: str = Field(..., min_length=1, max_length=64, description="Tenant organization scope.")
    status: PredictionExplanationStatus = Field(default=PredictionExplanationStatus.AVAILABLE)
    summary: str = Field(..., min_length=1, description="Narrative summary.")
    prediction_statement: str = Field(..., min_length=1, description="Clear statement of prediction.")
    status_statement: str = Field(..., min_length=1, description="Reiteration of status.")
    feature_explanations: List[ClaudeFeatureExplanation] = Field(default_factory=list)
    uncertainty_explanation: str = Field(..., min_length=1)
    risk_relationship: str = Field(..., min_length=1)
    evidence_explanations: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    fingerprint: str = Field(..., min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
