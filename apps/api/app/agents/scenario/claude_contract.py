"""Strongly typed contracts for Claude Scenario Analysis & Explanation Layer (Phase 10 Step 5).

Enforces strict authority boundaries:
- The Phase 9 Scenario Agent deterministically creates authoritative ScenarioDefinitions.
- Claude acts exclusively as an explanatory layer that interprets why the scenario was structured.
- Claude never simulates, optimizes, or calculates probabilities, costs, or inventory shortages.
- All input snapshots provided to Claude are immutable (frozen).
- Claude structured output must conform strictly to ClaudeScenarioExplanation (extra="forbid").
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import (
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.errors import AgentTenantIsolationError, AgentValidationError


class ScenarioExplanationStatus(str, Enum):
    """Operational status of the Claude scenario explanation artifact."""

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


class ScenarioParameterExplanationInput(BaseModel):
    """Immutable snapshot of an authoritative scenario parameter provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=128, description="Parameter name.")
    value: Union[float, int, str, bool] = Field(..., description="Authoritative parameter value.")
    unit: Optional[str] = Field(default=None, max_length=32, description="Physical/business unit.")
    source: str = Field(..., min_length=1, max_length=128, description="Authoritative parameter source.")
    source_type: str = Field(..., min_length=1, max_length=64, description="Parameter origin classification.")
    evidence_references: List[str] = Field(default_factory=list, description="Associated evidence IDs.")


class ScenarioConstraintExplanationInput(BaseModel):
    """Immutable snapshot of an authoritative scenario constraint provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    constraint_type: str = Field(..., min_length=1, max_length=64, description="Constraint category.")
    name: str = Field(..., min_length=1, max_length=128, description="Constraint name.")
    value: Union[float, int, str, bool] = Field(..., description="Constraint boundary value.")
    unit: Optional[str] = Field(default=None, max_length=32, description="Constraint unit.")


class ScenarioTriggerExplanationInput(BaseModel):
    """Immutable snapshot of an authoritative scenario trigger condition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trigger_type: str = Field(..., min_length=1, max_length=64, description="Trigger category.")
    condition: str = Field(..., min_length=1, max_length=32, description="Deterministic trigger condition.")
    threshold: Optional[float] = Field(default=None, description="Authoritative threshold value.")
    evidence_references: List[str] = Field(default_factory=list, description="Trigger evidence IDs.")


class ScenarioExplanationInput(BaseModel):
    """Strongly typed, immutable read-only snapshot of the authoritative ScenarioDefinition.
    
    Passed into Claude prompt builder to guarantee zero mutation of authoritative state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(..., min_length=1, max_length=64, description="Deterministic scenario identifier.")
    organization_id: str = Field(..., min_length=1, max_length=64, description="Tenant organization scope.")
    scenario_type: str = Field(..., min_length=1, max_length=64, description="Authoritative scenario taxonomy type.")
    target_reference: str = Field(..., min_length=1, max_length=128, description="Target entity or shipment reference.")
    horizon_hours: Optional[float] = Field(default=None, description="Scenario horizon duration in hours.")
    parameters: List[ScenarioParameterExplanationInput] = Field(default_factory=list, description="Authoritative parameters.")
    trigger: Optional[ScenarioTriggerExplanationInput] = Field(default=None, description="Authoritative trigger condition.")
    constraints: List[ScenarioConstraintExplanationInput] = Field(default_factory=list, description="Authoritative constraints.")
    upstream_risk_id: Optional[str] = Field(default=None, max_length=64, description="Upstream RiskAssessment ID.")
    risk_level: Optional[str] = Field(default=None, max_length=32, description="Upstream authoritative risk level.")
    risk_score: Optional[float] = Field(default=None, description="Upstream authoritative risk score.")
    upstream_prediction_id: Optional[str] = Field(default=None, max_length=64, description="Upstream PredictionResult ID.")
    prediction_status: Optional[str] = Field(default=None, max_length=32, description="Prediction execution status.")
    predicted_delay_minutes: Optional[float] = Field(default=None, description="Predicted delay in minutes if available.")
    evidence_references: List[str] = Field(default_factory=list, description="All valid evidence IDs.")
    citation_references: List[str] = Field(default_factory=list, description="All valid citation keys.")
    limitations: List[str] = Field(default_factory=list, description="Upstream caveats and limitations.")
    scenario_fingerprint: str = Field(..., min_length=1, max_length=64, description="Deterministic SHA-256 fingerprint.")
    objective: Optional[str] = Field(default=None, max_length=4096, description="Evaluation objective.")
    scenario_status: Optional[str] = Field(default=None, max_length=64, description="Authoritative scenario execution status.")
    affected_entities: List[str] = Field(default_factory=list, description="Authoritative affected entity IDs.")
    correlation_id: Optional[str] = Field(default=None, max_length=128, description="Distributed correlation ID.")
    request_id: Optional[str] = Field(default=None, max_length=128, description="Distributed request ID.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Context metadata.")

    @model_validator(mode="before")
    @classmethod
    def _normalize_scenario_input(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Allow scenario_parameters alias for parameters
            if "scenario_parameters" in data and "parameters" not in data:
                data["parameters"] = data.pop("scenario_parameters")
            if "fingerprint" in data and "scenario_fingerprint" not in data:
                data["scenario_fingerprint"] = data.pop("fingerprint")
        return data

    @field_validator("scenario_id", "organization_id", mode="after")
    @classmethod
    def validate_non_empty(cls, v: str, info: Any) -> str:
        if not v or not v.strip():
            raise AgentTenantIsolationError(f"{info.field_name} must be non-empty.")
        return v.strip()

    @field_validator("objective", mode="after")
    @classmethod
    def validate_objective_safety(cls, v: Optional[str]) -> Optional[str]:
        if v:
            validate_no_sensitive_values(v, "ScenarioExplanationInput.objective")
            validate_no_reasoning_text(v, "ScenarioExplanationInput.objective")
        return v


class ClaudeAssumptionExplanation(BaseModel):
    """Claude's structured explanation of a specific scenario assumption or condition."""

    model_config = ConfigDict(extra="forbid")

    assumption_name: str = Field(..., min_length=1, max_length=128, description="Name or title of assumption.")
    explanation: str = Field(..., min_length=1, max_length=2048, description="Contextual explanation of assumption.")
    evidence_ids: List[str] = Field(default_factory=list, description="Supporting evidence references.")

    @field_validator("assumption_name", "explanation", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeAssumptionExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeAssumptionExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeAssumptionExplanation.{info.field_name}")
        return v


class ClaudeScenarioParameterExplanation(BaseModel):
    """Claude's structured explanation of an authoritative scenario parameter."""

    model_config = ConfigDict(extra="forbid")

    parameter_name: str = Field(..., min_length=1, max_length=128, description="Authoritative parameter name.")
    authoritative_value: Union[float, int, str, bool] = Field(..., description="Authoritative value reiterated by Claude.")
    unit: Optional[str] = Field(default=None, max_length=32, description="Physical/business unit.")
    purpose: str = Field(..., min_length=1, max_length=2048, description="Why this parameter was posited in the scenario.")

    @field_validator("parameter_name", "purpose", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeScenarioParameterExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeScenarioParameterExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeScenarioParameterExplanation.{info.field_name}")
        return v


class ClaudeScenarioExplanation(BaseModel):
    """Pydantic contract for structured response generated by Claude explaining a scenario.
    
    Must conform strictly to extra='forbid' to prevent ungrounded simulation or optimization fields.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", description="Contract schema version.")
    summary: str = Field(..., min_length=1, max_length=8192, description="Executive narrative explanation.")
    scenario_purpose: str = Field(..., min_length=1, max_length=2048, description="Why this what-if scenario is meaningful.")
    scenario_type_statement: str = Field(..., min_length=1, max_length=256, description="Reiteration of authoritative scenario type.")
    parameter_explanations: List[ClaudeScenarioParameterExplanation] = Field(default_factory=list, description="Breakdowns of parameters.")
    assumption_explanations: List[ClaudeAssumptionExplanation] = Field(default_factory=list, description="Explanations of key assumptions.")
    risk_relationship: str = Field(..., min_length=1, max_length=2048, description="How scenario relates to authoritative risk assessment.")
    prediction_relationship: str = Field(..., min_length=1, max_length=2048, description="How scenario relates to predictions or prediction gaps.")
    evidence_explanations: List[str] = Field(default_factory=list, description="Grounded evidence narratives.")
    uncertainty_analysis: str = Field(..., min_length=1, max_length=4096, description="Discussion of data gaps and uncertainty.")
    limitations: List[str] = Field(default_factory=list, description="Known operational caveats.")
    citations: List[str] = Field(default_factory=list, description="All citation keys or evidence IDs referenced.")
    scenario_interpretation: Optional[str] = Field(default=None, max_length=4096, description="Detailed operational scenario interpretation.")
    key_drivers: List[str] = Field(default_factory=list, description="Key operational drivers behind the scenario.")
    affected_entities: List[str] = Field(default_factory=list, description="Affected entities identified in scenario.")
    assumptions: List[str] = Field(default_factory=list, description="High-level scenario assumptions.")
    evidence_references: List[str] = Field(default_factory=list, description="Associated evidence references.")
    prediction_references: List[str] = Field(default_factory=list, description="Associated prediction references.")
    risk_references: List[str] = Field(default_factory=list, description="Associated risk references.")
    research_references: List[str] = Field(default_factory=list, description="Associated research references.")

    @field_validator(
        "summary",
        "scenario_purpose",
        "scenario_type_statement",
        "risk_relationship",
        "prediction_relationship",
        "uncertainty_analysis",
        mode="after",
    )
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeScenarioExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeScenarioExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeScenarioExplanation.{info.field_name}")
        return v

    @field_validator("scenario_interpretation", mode="after")
    @classmethod
    def validate_interpretation_safety(cls, v: Optional[str]) -> Optional[str]:
        if v:
            validate_no_forbidden_keys({"scenario_interpretation": v}, "ClaudeScenarioExplanation.scenario_interpretation")
            validate_no_sensitive_values(v, "ClaudeScenarioExplanation.scenario_interpretation")
            validate_no_reasoning_text(v, "ClaudeScenarioExplanation.scenario_interpretation")
        return v

    @field_validator("limitations", "evidence_explanations", "key_drivers", "affected_entities", "assumptions", mode="after")
    @classmethod
    def validate_list_safety(cls, v: List[str], info: Any) -> List[str]:
        for idx, item in enumerate(v):
            validate_no_sensitive_values(item, f"ClaudeScenarioExplanation.{info.field_name}[{idx}]")
            validate_no_reasoning_text(item, f"ClaudeScenarioExplanation.{info.field_name}[{idx}]")
        return v


def compute_scenario_explanation_fingerprint(
    scenario_id: str,
    organization_id: str,
    summary: str,
    citations: List[str],
) -> str:
    """Generate deterministic SHA-256 semantic fingerprint for a scenario explanation."""
    sorted_citations = sorted(c.strip() for c in citations)
    payload = {
        "scenario_id": scenario_id.strip(),
        "organization_id": organization_id.strip(),
        "summary": summary.strip(),
        "citations": sorted_citations,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ScenarioExplanationResult(BaseModel):
    """Canonical domain representation of the verified Claude scenario explanation.
    
    Stored in AgentGraphState as scenario_explanation.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    scenario_id: str = Field(..., min_length=1, max_length=64, description="Associated scenario ID.")
    organization_id: str = Field(..., min_length=1, max_length=64, description="Tenant organization scope.")
    status: ScenarioExplanationStatus = Field(default=ScenarioExplanationStatus.AVAILABLE)
    summary: str = Field(..., min_length=1, description="Narrative summary.")
    scenario_purpose: str = Field(..., min_length=1, description="Scenario operational purpose.")
    scenario_type_statement: str = Field(..., min_length=1, description="Reiteration of scenario type.")
    parameter_explanations: List[ClaudeScenarioParameterExplanation] = Field(default_factory=list)
    assumption_explanations: List[ClaudeAssumptionExplanation] = Field(default_factory=list)
    risk_relationship: str = Field(..., min_length=1)
    prediction_relationship: str = Field(..., min_length=1)
    evidence_explanations: List[str] = Field(default_factory=list)
    uncertainty_analysis: str = Field(..., min_length=1)
    limitations: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    fingerprint: str = Field(..., min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: Dict[str, Any] = Field(default_factory=dict)
    explanation: Optional[str] = Field(default=None, description="Direct explanation narrative.")
    scenario_interpretation: Optional[str] = Field(default=None, description="Detailed operational scenario interpretation.")
    key_drivers: List[str] = Field(default_factory=list, description="Key operational drivers behind the scenario.")
    affected_entities: List[str] = Field(default_factory=list, description="Affected entities.")
    evidence_references: List[str] = Field(default_factory=list, description="Evidence references.")
    prediction_references: List[str] = Field(default_factory=list, description="Prediction references.")
    risk_references: List[str] = Field(default_factory=list, description="Risk references.")
    research_references: List[str] = Field(default_factory=list, description="Research references.")
    authoritative_scenario_fingerprint: Optional[str] = Field(default=None, description="Authoritative scenario fingerprint.")
    prompt_fingerprint: Optional[str] = Field(default=None, description="Fingerprint of prompt passed to Claude.")
    validation_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata recorded during validation.")
    failure_category: Optional[str] = Field(default=None, description="Failure categorization if unavailable.")

    @model_validator(mode="before")
    @classmethod
    def _normalize_result(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "explanation" not in data and "summary" in data:
                data["explanation"] = data["summary"]
            elif "summary" not in data and "explanation" in data:
                data["summary"] = data["explanation"]
        return data

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
