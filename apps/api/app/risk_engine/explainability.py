"""Deterministic explainability contract for RiskWise Risk Engine.

Produces structured, auditable human-readable explanations from evaluated
factors, evidence traces, and conflict signals without any reliance on LLMs,
heuristics, or external generative dependencies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.contract import RiskFactor, RiskLevel, select_primary_risk_driver
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
    contribution: Optional[float] = Field(None, description="Normalized factor contribution [0, 1].")
    weighted_contribution: Optional[float] = Field(None, description="Weighted impact points on score [0, 100].")
    rank: Optional[int] = Field(None, description="Factor contribution rank.")
    evidence_ids: List[str] = Field(default_factory=list, description="Linked evidence identifiers.")
    evidence_count: int = Field(default=0, ge=0, description="Number of supporting evidence items.")
    supporting_sources: List[str] = Field(default_factory=list, description="List of source providers supporting this factor.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional contextual explanation metadata.")


class RiskExplanation(BaseModel):
    """Authoritative, deterministic explanation contract for a risk assessment."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    summary: str = Field(..., description="High-level deterministic narrative overview.")
    primary_driver: Optional[str] = Field(None, description="Title of the primary risk driver factor.")
    primary_factor_id: Optional[str] = Field(None, description="Identifier of primary risk driver factor.")
    score: Optional[float] = Field(None, description="Evaluated composite risk score.")
    risk_level: Optional[RiskLevel] = Field(None, description="Categorical risk level classification.")
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
    source_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Deterministic summary of sources and observation types.",
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
        score: Optional[float] = None,
        risk_level: Optional[RiskLevel] = None,
        primary_factor: Optional[RiskFactor] = None,
        factor_contributions: Optional[List[Any]] = None,
        source_summary: Optional[Any] = None,
    ) -> "RiskExplanation":
        """Generate a reproducible, deterministic risk explanation without generative AI."""
        factor_exps: List[FactorExplanation] = []
        evidence_refs: List[str] = [ev.evidence_id for ev in evidence]
        unresolved = list(conflicts) if conflicts else []
        limits = list(limitations) if limitations else []

        # Map factor contribution metadata if available
        contribution_map = {}
        if factor_contributions:
            for fc in factor_contributions:
                fid = getattr(fc, "factor_id", None) or (fc.get("factor_id") if isinstance(fc, dict) else None)
                if fid:
                    contribution_map[fid] = fc

        for f in factors:
            sources = sorted(list({ev.provider for ev in f.evidence if ev.provider}))
            desc = f.description or f"Identified {f.name} in {f.domain.value} domain."
            fc = contribution_map.get(f.factor_id)
            w_contr = getattr(fc, "weighted_contribution", None) if fc else None
            f_rank = getattr(fc, "rank", None) if fc else None
            ev_ids = list(f.evidence_ids) if f.evidence_ids else [e.evidence_id for e in f.evidence]

            factor_exps.append(
                FactorExplanation(
                    factor_id=f.factor_id,
                    factor_type=f.factor_type,
                    name=f.name,
                    summary=desc,
                    severity=f.severity,
                    confidence=f.confidence,
                    contribution=f.contribution,
                    weighted_contribution=w_contr,
                    rank=f_rank,
                    evidence_ids=ev_ids,
                    evidence_count=len(f.evidence),
                    supporting_sources=sources,
                    metadata=dict(f.metadata),
                )
            )

        top_f = primary_factor or select_primary_risk_driver(factors)
        top_name = top_f.name if top_f else None
        top_fid = top_f.factor_id if top_f else None

        if custom_summary:
            summary = custom_summary
        elif not factors:
            score_desc = f" (Score: {score:.1f}, Level: {risk_level.value})" if score is not None and risk_level else ""
            summary = f"No active risk factors identified in evaluation context{score_desc}."
        else:
            high_critical = [f for f in factors if f.severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
            score_prefix = (
                f"Overall Risk Score: {score:.1f} ({risk_level.value if risk_level else 'UNRATED'}). "
                if score is not None
                else ""
            )
            top_contr = top_f.contribution if top_f else 0.0
            if high_critical:
                summary = (
                    f"{score_prefix}Evaluated {len(factors)} risk factor(s) with {len(high_critical)} "
                    f"elevated severity concern(s). Primary driver: '{top_name}' "
                    f"(contribution: {top_contr})."
                )
            else:
                summary = (
                    f"{score_prefix}Evaluated {len(factors)} standard risk factor(s) "
                    f"supported by {len(evidence)} evidence trace(s). Primary driver: '{top_name}'."
                )

        src_summary_dict = None
        if source_summary is not None:
            if hasattr(source_summary, "model_dump"):
                src_summary_dict = source_summary.model_dump()
            elif isinstance(source_summary, dict):
                src_summary_dict = source_summary

        return cls(
            summary=summary,
            primary_driver=top_name,
            primary_factor_id=top_fid,
            score=score,
            risk_level=risk_level,
            factor_explanations=factor_exps,
            evidence_references=evidence_refs,
            confidence=1.0 if not factors else min(f.confidence for f in factors),
            source_summary=src_summary_dict,
            limitations=limits,
            unresolved_conflicts=unresolved,
        )
