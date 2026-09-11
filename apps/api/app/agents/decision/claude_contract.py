"""Strongly typed contracts for Claude Decision Analysis & Explanation Layer (Phase 10 Step 7).

Enforces strict authority boundaries:
- The Phase 9 Decision Agent / DecisionRuleEngine deterministically creates authoritative DecisionResults.
- Claude acts exclusively as an explanatory layer that interprets why a candidate was selected.
- Claude never selects or overrides candidates, never approves actions, and never executes commands.
- Claude never changes decision status (e.g. from REQUIRES_APPROVAL to APPROVED).
- Claude never claims operational actions were executed (no shipment rerouting, no POs, no carrier dispatch).
- Claude never fabricates optimization results (no OR-Tools, linear programs, simplex solvers).
- All input snapshots provided to Claude are immutable (frozen).
- Claude structured output must conform strictly to ClaudeDecisionExplanation (extra="forbid").
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
from app.agents.decision.contract import DecisionBaseModel
from app.agents.errors import AgentTenantIsolationError, AgentValidationError


class DecisionExplanationStatus(str, Enum):
    """Operational status of the Claude decision explanation artifact."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
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


class DecisionCandidateExplanationInput(DecisionBaseModel):
    """Immutable snapshot of an authoritative decision candidate provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str = Field(..., min_length=1, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=2000)
    priority: Union[int, str] = Field(default="MEDIUM")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    prerequisites: List[str] = Field(default_factory=list)
    expected_effect: Optional[str] = Field(default=None, max_length=1000)
    evidence_references: List[str] = Field(default_factory=list)
    constraints: List[DecisionConstraintExplanationInput] = Field(default_factory=list)
    requires_human_approval: bool = Field(default=True)
    status: str = Field(default="REQUIRES_APPROVAL", min_length=1, max_length=32)


class DecisionConstraintExplanationInput(DecisionBaseModel):
    """Immutable snapshot of an authoritative decision constraint provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    constraint_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    value: Union[float, int, str, bool]
    unit: Optional[str] = Field(default=None, max_length=32)


class DecisionRationaleExplanationInput(DecisionBaseModel):
    """Immutable snapshot of an authoritative decision rationale provided to Claude."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    basis_type: str = Field(default="SCENARIO")
    source_reference: Optional[str] = Field(default=None, max_length=128)
    evidence_references: List[str] = Field(default_factory=list)
    rule_id: str = Field(..., min_length=1, max_length=128)
    finding_ids: List[str] = Field(default_factory=list)
    explanation_code: str = Field(default="DETERMINISTIC_EVALUATION", min_length=1, max_length=128)


class DecisionExplanationInput(DecisionBaseModel):
    """Strongly typed, immutable read-only snapshot of authoritative DecisionResult and context.

    Passed into Claude prompt builder to guarantee zero mutation of authoritative decision state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    decision_type: str = Field(default="OPERATIONAL_REVIEW", min_length=1, max_length=64)
    status: str = Field(default="REQUIRES_APPROVAL", min_length=1, max_length=64)
    candidates: List[DecisionCandidateExplanationInput] = Field(default_factory=list)
    preferred_candidate: Optional[DecisionCandidateExplanationInput] = None
    preferred_candidate_id: Optional[str] = Field(default=None, max_length=64)
    constraints: List[DecisionConstraintExplanationInput] = Field(default_factory=list)
    rationales: List[DecisionRationaleExplanationInput] = Field(default_factory=list)
    requires_human_approval: bool = Field(default=True)
    planning_horizon_hours: Optional[float] = None
    scenario_id: Optional[str] = Field(default=None, max_length=64)
    upstream_scenario_id: Optional[str] = Field(default=None, max_length=64)
    scenario_type: Optional[str] = Field(default=None, max_length=64)
    scenario_status: Optional[str] = Field(default=None, max_length=64)
    scenario_fingerprint: Optional[str] = Field(default=None, max_length=64)
    risk_assessment_id: Optional[str] = Field(default=None, max_length=64)
    upstream_risk_id: Optional[str] = Field(default=None, max_length=64)
    risk_score: Optional[float] = None
    risk_level: Optional[str] = Field(default=None, max_length=32)
    prediction_id: Optional[str] = Field(default=None, max_length=64)
    upstream_prediction_id: Optional[str] = Field(default=None, max_length=64)
    prediction_status: Optional[str] = Field(default=None, max_length=64)
    predicted_delay_minutes: Optional[float] = None
    predicted_value: Optional[float] = None
    decision_fingerprint: str = Field(..., min_length=1, max_length=64)
    objective: Optional[str] = Field(default=None, max_length=4096)
    evidence_references: List[str] = Field(default_factory=list)
    citation_references: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    request_id: Optional[str] = Field(default=None, max_length=64)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_id", "organization_id", mode="after")
    @classmethod
    def validate_non_empty(cls, v: str, info: Any) -> str:
        if not v or not v.strip():
            raise AgentTenantIsolationError(f"{info.field_name} must be non-empty.")
        return v.strip()

    @field_validator("objective", mode="after")
    @classmethod
    def validate_objective_safety(cls, v: Optional[str]) -> Optional[str]:
        if v:
            validate_no_sensitive_values(v, "DecisionExplanationInput.objective")
            validate_no_reasoning_text(v, "DecisionExplanationInput.objective")
        return v


class ClaudeCandidateTradeoff(BaseModel):
    """Claude's structured explanation of a candidate's operational trade-offs."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., min_length=1, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=64)
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    operational_impact: str = Field(..., min_length=1, max_length=1000)

    @field_validator("candidate_id", "action_type", "operational_impact", mode="after")
    @classmethod
    def validate_text_safety(cls, v: str, info: Any) -> str:
        validate_no_sensitive_values(v, f"ClaudeCandidateTradeoff.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeCandidateTradeoff.{info.field_name}")
        return v


class ClaudeDecisionExplanation(BaseModel):
    """Pydantic contract for structured response generated by Claude explaining a decision.

    Must conform strictly to extra='forbid' to prevent ungrounded decision modifications.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0")
    summary: str = Field(..., min_length=1, max_length=8192)
    decision_purpose: str = Field(..., min_length=1, max_length=2048)
    decision_type_statement: str = Field(..., min_length=1, max_length=256)
    selected_candidate_explanation: str = Field(..., min_length=1, max_length=4096)
    candidate_tradeoffs: List[ClaudeCandidateTradeoff] = Field(default_factory=list)
    approval_requirement_statement: str = Field(..., min_length=1, max_length=1000)
    scenario_relationship: str = Field(..., min_length=1, max_length=2048)
    risk_relationship: str = Field(..., min_length=1, max_length=2048)
    prediction_relationship: str = Field(..., min_length=1, max_length=2048)
    constraint_explanations: List[str] = Field(default_factory=list)
    uncertainty_and_gaps: str = Field(..., min_length=1, max_length=4096)
    limitations: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    candidate_references: List[str] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)
    prediction_references: List[str] = Field(default_factory=list)
    risk_references: List[str] = Field(default_factory=list)
    scenario_references: List[str] = Field(default_factory=list)

    @field_validator(
        "summary",
        "decision_purpose",
        "decision_type_statement",
        "selected_candidate_explanation",
        "approval_requirement_statement",
        "scenario_relationship",
        "risk_relationship",
        "prediction_relationship",
        "uncertainty_and_gaps",
        mode="after",
    )
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeDecisionExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeDecisionExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeDecisionExplanation.{info.field_name}")
        return v

    @field_validator(
        "constraint_explanations",
        "limitations",
        "citations",
        "candidate_references",
        "evidence_references",
        mode="after",
    )
    @classmethod
    def validate_list_safety(cls, v: List[str], info: Any) -> List[str]:
        for idx, item in enumerate(v):
            validate_no_sensitive_values(item, f"ClaudeDecisionExplanation.{info.field_name}[{idx}]")
            validate_no_reasoning_text(item, f"ClaudeDecisionExplanation.{info.field_name}[{idx}]")
        return v


def compute_decision_explanation_fingerprint(
    decision_id: str,
    organization_id: str,
    summary: str,
    citations: List[str],
    preferred_candidate_id: Optional[str] = None,
) -> str:
    """Generate deterministic SHA-256 semantic fingerprint for a decision explanation."""
    sorted_citations = sorted(c.strip() for c in citations)
    payload = {
        "decision_id": decision_id.strip(),
        "organization_id": organization_id.strip(),
        "summary": summary.strip(),
        "citations": sorted_citations,
        "preferred_candidate_id": (preferred_candidate_id or "").strip(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DecisionExplanationResult(DecisionBaseModel):
    """Canonical domain representation of the verified Claude decision explanation.

    Stored in AgentGraphState as decision_explanation.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    status: DecisionExplanationStatus = Field(default=DecisionExplanationStatus.AVAILABLE)
    summary: str = Field(..., min_length=1)
    decision_purpose: str = Field(..., min_length=1)
    decision_type_statement: str = Field(..., min_length=1)
    selected_candidate_explanation: str = Field(..., min_length=1)
    candidate_tradeoffs: List[ClaudeCandidateTradeoff] = Field(default_factory=list)
    approval_requirement_statement: str = Field(..., min_length=1)
    scenario_relationship: str = Field(..., min_length=1)
    risk_relationship: str = Field(..., min_length=1)
    prediction_relationship: str = Field(..., min_length=1)
    constraint_explanations: List[str] = Field(default_factory=list)
    uncertainty_and_gaps: str = Field(..., min_length=1)
    limitations: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    fingerprint: str = Field(..., min_length=1, max_length=64)
    authoritative_decision_fingerprint: str = Field(..., min_length=1, max_length=64)
    prompt_fingerprint: str = Field(..., min_length=1, max_length=64)
    validation_metadata: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    failure_category: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
