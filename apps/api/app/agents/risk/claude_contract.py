"""Strongly typed contracts for Claude Risk Explanation Layer (Phase 10 Step 4).

Enforces strict authority boundaries:
- Phase 7 BaselineRiskEngine deterministically computes risk scores, levels, and factor contributions.
- Claude acts exclusively as an explanatory layer that interprets why the engine produced the assessment.
- All input snapshots provided to Claude are immutable (frozen).
- Claude structured output must conform strictly to ClaudeRiskExplanation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.contracts import (
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)


class RiskExplanationStatus(str, Enum):
    """Operational status of the Claude risk explanation artifact."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PARTIALLY_GROUNDED = "PARTIALLY_GROUNDED"
    REJECTED_CONTRADICTION = "REJECTED_CONTRADICTION"
    REJECTED_INVALID_CITATION = "REJECTED_INVALID_CITATION"
    REJECTED_UNSUPPORTED_FACTOR = "REJECTED_UNSUPPORTED_FACTOR"


class RiskFactorExplanationInput(BaseModel):
    """Immutable snapshot of a single Phase 7 RiskFactor provided to Claude."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor_id: str = Field(..., min_length=1, max_length=64, description="Deterministic factor ID.")
    factor_type: str = Field(..., min_length=1, max_length=64, description="Category of the factor.")
    domain: str = Field(..., min_length=1, max_length=64, description="Signal domain.")
    name: str = Field(..., min_length=1, max_length=256, description="Human-readable factor title.")
    description: Optional[str] = Field(None, max_length=4096, description="Optional factor details.")
    severity: str = Field(..., min_length=1, max_length=32, description="Severity: LOW, MEDIUM, HIGH, CRITICAL.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence certainty [0, 1].")
    contribution: Optional[float] = Field(None, ge=0.0, le=1.0, description="Normalized relative contribution [0, 1].")
    weighted_contribution: Optional[float] = Field(None, ge=0.0, le=100.0, description="Weighted impact points [0, 100].")
    rank: Optional[int] = Field(None, ge=1, description="Deterministic rank among factors.")
    evidence_ids: List[str] = Field(default_factory=list, description="Linked evidence identifiers.")


class RiskExplanationInput(BaseModel):
    """Immutable, frozen snapshot of authoritative Phase 7 RiskAssessment passed to Claude.
    
    Protects deterministic calculation outputs from being modified or corrupted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_id: str = Field(..., min_length=1, max_length=64, description="Authoritative assessment ID.")
    organization_id: str = Field(..., min_length=1, max_length=64, description="Tenant organization scope.")
    scope: str = Field(default="GLOBAL", max_length=64, description="Assessment scope.")
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Composite risk score [0, 100].")
    risk_level: Optional[str] = Field(None, max_length=32, description="Risk level: LOW, MEDIUM, HIGH, CRITICAL.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Assessment confidence certainty.")
    primary_factor_id: Optional[str] = Field(None, max_length=64, description="Primary risk driver factor ID.")
    primary_factor_name: Optional[str] = Field(None, max_length=256, description="Primary risk driver factor title.")
    factors: List[RiskFactorExplanationInput] = Field(default_factory=list, description="Authoritative risk factors.")
    factor_contributions: List[Dict[str, Any]] = Field(default_factory=list, description="Authoritative contribution values.")
    evidence_references: List[str] = Field(default_factory=list, description="Linked evidence references.")
    citation_references: List[str] = Field(default_factory=list, description="Linked citation references.")
    limitations: List[str] = Field(default_factory=list, description="Deterministic limitations and data caveats.")
    conflicts: List[Dict[str, Any]] = Field(default_factory=list, description="Preserved multi-source conflict records.")
    assessment_fingerprint: Optional[str] = Field(None, max_length=128, description="Deterministic assessment fingerprint.")
    objective: Optional[str] = Field(None, max_length=4096, description="Research or operational objective.")


REASONING_TEXT_PATTERNS = [
    re.compile(r"chain[\s_]+of[\s_]+thought", re.IGNORECASE),
    re.compile(r"internal[\s_]+monologue", re.IGNORECASE),
    re.compile(r"private[\s_]+reasoning", re.IGNORECASE),
    re.compile(r"hidden[\s_]+reasoning", re.IGNORECASE),
]


def validate_no_reasoning_text(text: str, field_name: str = "field") -> None:
    validate_no_reasoning_content(text, field_name)
    if not text or not isinstance(text, str):
        return
    for pattern in REASONING_TEXT_PATTERNS:
        if pattern.search(text):
            raise AgentValidationError(
                f"Prohibited reasoning content detected in '{field_name}'."
            )


class ClaudeRiskDriverExplanation(BaseModel):
    """Claude's structured explanation of a specific contributing risk factor."""

    model_config = ConfigDict(extra="forbid")

    factor_id: str = Field(..., min_length=1, max_length=64, description="Authoritative factor ID.")
    driver_name: str = Field(..., min_length=1, max_length=256, description="Factor title.")
    explanation: str = Field(..., min_length=1, max_length=4096, description="Why this factor contributed.")
    evidence_ids: List[str] = Field(default_factory=list, description="Supporting evidence IDs.")
    impact_summary: str = Field(..., min_length=1, max_length=2048, description="Operational impact description.")

    @field_validator("explanation", "impact_summary", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeRiskDriverExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeRiskDriverExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeRiskDriverExplanation.{info.field_name}")
        return v


class ClaudeEvidenceExplanation(BaseModel):
    """Claude's structured narrative grounding an evidence item to the risk evaluation."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1, max_length=64, description="Verified evidence ID.")
    citation_id: Optional[str] = Field(default=None, max_length=64, description="Citation key e.g. [CIT-1].")
    source: str = Field(..., min_length=1, max_length=128, description="Source name or provider.")
    claim: str = Field(..., min_length=1, max_length=2048, description="Verified claim extracted from evidence.")
    relevance_to_risk: str = Field(..., min_length=1, max_length=2048, description="Relevance to risk assessment.")

    @field_validator("claim", "relevance_to_risk", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeEvidenceExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeEvidenceExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeEvidenceExplanation.{info.field_name}")
        return v


class ClaudeRiskConflictExplanation(BaseModel):
    """Claude's explanation of multi-source contradictions identified by the engine."""

    model_config = ConfigDict(extra="forbid")

    entity_or_topic: str = Field(..., min_length=1, max_length=256, description="Entity or topic with conflict.")
    conflicting_claims: List[str] = Field(default_factory=list, description="Contradicting claims from sources.")
    evidence_ids: List[str] = Field(default_factory=list, description="Associated evidence IDs.")
    analysis: str = Field(..., min_length=1, max_length=4096, description="Contextual explanation of disagreement.")

    @field_validator("analysis", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeRiskConflictExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeRiskConflictExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeRiskConflictExplanation.{info.field_name}")
        return v


class ClaudeRiskExplanation(BaseModel):
    """Pydantic contract for structured response generated by Claude.
    
    All score_statement and risk_level_statement fields are explanatory and
    strictly verified against authoritative Phase 7 values before acceptance.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0.0", description="Contract schema version.")
    summary: str = Field(..., min_length=1, max_length=8192, description="Executive narrative explanation.")
    risk_level_statement: str = Field(..., min_length=1, max_length=512, description="Explanation of authoritative risk level.")
    score_statement: str = Field(..., min_length=1, max_length=512, description="Explanation of composite risk score.")
    key_drivers: List[ClaudeRiskDriverExplanation] = Field(default_factory=list, description="Breakdowns of primary drivers.")
    evidence_explanations: List[ClaudeEvidenceExplanation] = Field(default_factory=list, description="Grounded evidence narratives.")
    uncertainty_analysis: str = Field(..., min_length=1, max_length=4096, description="Discussion of data gaps and uncertainty.")
    conflict_explanations: List[ClaudeRiskConflictExplanation] = Field(default_factory=list, description="Discrepancy explanations.")
    limitations: List[str] = Field(default_factory=list, description="Known operational caveats.")
    citations: List[str] = Field(default_factory=list, description="All citation keys or evidence IDs referenced.")

    @field_validator("summary", "risk_level_statement", "score_statement", "uncertainty_analysis", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ClaudeRiskExplanation.{info.field_name}")
        validate_no_sensitive_values(v, f"ClaudeRiskExplanation.{info.field_name}")
        validate_no_reasoning_text(v, f"ClaudeRiskExplanation.{info.field_name}")
        return v

    @field_validator("limitations", mode="after")
    @classmethod
    def validate_limitations_safety(cls, v: List[str]) -> List[str]:
        for idx, item in enumerate(v):
            validate_no_sensitive_values(item, f"ClaudeRiskExplanation.limitations[{idx}]")
            validate_no_reasoning_text(item, f"ClaudeRiskExplanation.limitations[{idx}]")
        return v


def compute_explanation_fingerprint(
    assessment_id: str,
    organization_id: str,
    summary: str,
    citations: List[str],
) -> str:
    """Generate deterministic SHA-256 semantic fingerprint for a risk explanation."""
    sorted_citations = sorted(citations) if citations else []
    raw = f"risk_explanation:{organization_id}:{assessment_id}:{summary.strip()}:{','.join(sorted_citations)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RiskExplanationResult(BaseModel):
    """Authoritative domain contract for the completed risk explanation artifact.
    
    Attached to AgentGraphState as read-only explanatory metadata.
    """

    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(..., min_length=1, max_length=64, description="Associated assessment ID.")
    organization_id: str = Field(..., min_length=1, max_length=64, description="Tenant organization scope.")
    status: RiskExplanationStatus = Field(default=RiskExplanationStatus.AVAILABLE)
    summary: str = Field(..., description="Executive narrative explanation.")
    risk_level_statement: str = Field(default="", description="Narrative level explanation.")
    score_statement: str = Field(default="", description="Narrative score explanation.")
    key_drivers: List[ClaudeRiskDriverExplanation] = Field(default_factory=list)
    evidence_explanations: List[ClaudeEvidenceExplanation] = Field(default_factory=list)
    uncertainty_analysis: str = Field(default="")
    conflict_explanations: List[ClaudeRiskConflictExplanation] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    fingerprint: str = Field(..., min_length=1, description="Deterministic fingerprint.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Audit and execution provenance.")
