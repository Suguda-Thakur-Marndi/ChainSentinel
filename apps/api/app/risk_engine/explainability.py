"""Deterministic explainability contract for RiskWise Risk Engine.

Produces structured, auditable human-readable explanations from evaluated
factors, evidence traces, and conflict signals without any reliance on LLMs,
heuristics, or external generative dependencies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.contract import RiskFactor, RiskLevel
from app.risk_engine.evidence import RiskEvidence


class FactorExplanation(BaseModel):
    """Deterministic explanation snippet for a single evaluated risk factor."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    factor_id: str = Field(..., description="Target factor identifier.")
    factor_type: str = Field(..., description="Classification category.")
    name: str = Field(..., description="Human-readable factor title.")
    summary: str = Field(..., description="Deterministic narrative summary.")
    severity: RiskLevel = Field(..., description="Factor severity classification.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Factor confidence certainty.")
    evidence_count: int = Field(default=0, ge=0, description="Number of supporting evidence items.")
    supporting_sources: List[str] = Field(default_factory=list, description="List of source providers supporting this factor.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional contextual explanation metadata.")


class RiskExplanation(BaseModel):
    """Authoritative, deterministic explanation contract for a risk assessment."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    summary: str = Field(..., description="High-level deterministic narrative overview.")
    factor_explanations: List[FactorExplanation] = Field(
        default_factory=list,
        description="Individual breakdowns for each contributor.",
    )
    evidence_references: List[str] = Field(
        default_factory=list,
        description="Lineage references to underlying evidence traces.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Overall confidence certainty of the evaluation.",
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Known data gaps, estimation caveats, or partial signal warnings.",
    )
    unresolved_conflicts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Documented disagreements or conflicts across sources from normalization.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Diagnostic metadata and audit context.",
    )

    @classmethod
    def generate_deterministic(
        cls,
        factors: List[RiskFactor],
        evidence: List[RiskEvidence],
        conflicts: Optional[List[Dict[str, Any]]] = None,
        limitations: Optional[List[str]] = None,
        custom_summary: Optional[str] = None,
    ) -> "RiskExplanation":
        """Generate a reproducible, deterministic risk explanation without generative AI."""
        factor_exps: List[FactorExplanation] = []
        evidence_refs: List[str] = [ev.evidence_id for ev in evidence]
        unresolved = list(conflicts) if conflicts else []
        limits = list(limitations) if limitations else []

        for f in factors:
            sources = sorted(list({ev.provider for ev in f.evidence if ev.provider}))
            desc = f.description or f"Identified {f.name} in {f.domain.value} domain."
            factor_exps.append(
                FactorExplanation(
                    factor_id=f.factor_id,
                    factor_type=f.factor_type,
                    name=f.name,
                    summary=desc,
                    severity=f.severity,
                    confidence=f.confidence,
                    evidence_count=len(f.evidence),
                    supporting_sources=sources,
                    metadata=dict(f.metadata),
                )
            )

        if custom_summary:
            summary = custom_summary
        elif not factors:
            summary = "No active risk factors identified in evaluation context."
        else:
            high_critical = [f for f in factors if f.severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
            if high_critical:
                summary = (
                    f"Evaluated {len(factors)} risk factor(s) with {len(high_critical)} "
                    f"elevated severity concern(s) across {len(evidence)} evidence trace(s)."
                )
            else:
                summary = (
                    f"Evaluated {len(factors)} standard risk factor(s) "
                    f"supported by {len(evidence)} evidence trace(s)."
                )

        return cls(
            summary=summary,
            factor_explanations=factor_exps,
            evidence_references=evidence_refs,
            confidence=1.0 if not factors else min(f.confidence for f in factors),
            limitations=limits,
            unresolved_conflicts=unresolved,
        )
