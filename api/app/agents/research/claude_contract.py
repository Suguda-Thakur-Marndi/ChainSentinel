"""Strongly typed contracts for structured Claude research synthesis outputs.

Defines schemas for Claude findings, source conflicts, and operational limitations
conforming strictly to RiskWise epistemic standards.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClaudeFindingItem(BaseModel):
    """Structured research finding produced by LLM provider."""

    model_config = ConfigDict(extra="ignore")

    category: str = Field(..., min_length=1, max_length=64, description="Disruption or analytical domain category")
    finding_type: str = Field(..., description="Epistemic type: 'FACT', 'INFERENCE', or 'UNKNOWN'")
    title: str = Field(..., min_length=1, max_length=256, description="Concise finding headline")
    statement: str = Field(..., min_length=1, max_length=4096, description="Detailed synthesized finding text")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of supporting evidence units")
    citation_ids: List[str] = Field(default_factory=list, description="Citation references (e.g. [CIT-1])")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence in research finding interpretation")
    limitations: List[str] = Field(default_factory=list, description="Epistemic gaps or caveats regarding this finding")
    rationale: Optional[str] = Field(default=None, max_length=2048, description="Analytical reasoning link")

    @field_validator("finding_type", mode="before")
    @classmethod
    def normalize_finding_type(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in {"FACT", "INFERENCE", "UNKNOWN"}:
                return clean
        raise ValueError(f"Invalid finding_type '{v}'. Must be 'FACT', 'INFERENCE', or 'UNKNOWN'.")


class ClaudeConflictItem(BaseModel):
    """Contradiction or variance detected across multiple evidence sources."""

    model_config = ConfigDict(extra="ignore")

    entity_or_topic: str = Field(..., min_length=1, max_length=256, description="Subject of the conflicting reports")
    conflicting_claims: List[str] = Field(..., min_length=2, description="Divergent statements reported by sources")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of evidence units in conflict")
    explanation: str = Field(..., min_length=1, max_length=2048, description="Description of the discrepancy")


class ClaudeResearchResponse(BaseModel):
    """Authoritative structured output schema requested from LLM."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field(default="1.0.0", description="Contract schema version")
    summary: str = Field(..., min_length=1, max_length=8192, description="Executive narrative research synthesis")
    findings: List[ClaudeFindingItem] = Field(default_factory=list, description="List of synthesized findings")
    conflicts: List[ClaudeConflictItem] = Field(default_factory=list, description="Discrepancies identified across sources")
    limitations: List[str] = Field(default_factory=list, description="Overall data gaps or research caveats")
    unknowns: List[str] = Field(default_factory=list, description="Unverified or missing variables")
    citations: List[str] = Field(default_factory=list, description="All citation keys referenced in synthesis")
    overall_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Aggregate research confidence")

    @classmethod
    def _unwrap_envelope(cls, raw: Any) -> Any:
        if isinstance(raw, dict):
            for candidate_key in (
                "research_response",
                "claude_research_response",
                "response",
                "research",
                "analysis",
            ):
                nested = raw.get(candidate_key)
                if isinstance(nested, dict) and "summary" in nested:
                    return nested
            if len(raw) == 1:
                single_val = next(iter(raw.values()))
                if isinstance(single_val, dict) and "summary" in single_val:
                    return single_val
        return raw

    @classmethod
    def _normalize_fields(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(raw)
        if "summary" not in data:
            for alt in ("executive_summary", "overview", "synthesis", "narrative"):
                if alt in data and isinstance(data[alt], str):
                    data["summary"] = data[alt]
                    break
        if "findings" not in data:
            for alt in ("finding_list", "key_findings", "results"):
                if alt in data and isinstance(data[alt], list):
                    data["findings"] = data[alt]
                    break
        return data

    def __init__(self, **data: Any) -> None:
        unwrapped = self._unwrap_envelope(data)
        if isinstance(unwrapped, dict):
            normalized = self._normalize_fields(unwrapped)
            super().__init__(**normalized)
        else:
            super().__init__(**data)


# Canonical provider-neutral aliases
ResearchFindingItem = ClaudeFindingItem
ResearchConflictItem = ClaudeConflictItem
ResearchResponse = ClaudeResearchResponse
