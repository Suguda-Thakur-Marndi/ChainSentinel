"""Core strongly typed application contracts for RiskWise Risk Engine.

Defines RiskLevel, FactorContribution, AssessmentSourceSummary, RiskFactor,
RiskScore, and RiskAssessment with deterministic identities and stable ordering.
"""

from __future__ import annotations

import functools
import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.normalization.contract import EntityType, SignalDomain
from app.risk_engine.evidence import EvidenceRelevance, RiskEvidence


class RiskLevel(str, Enum):
    """Operational risk level classification aligned with core platform severity taxonomy."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# Severity numerical hierarchy for deterministic ordering
SEVERITY_ORDER: Dict[RiskLevel, int] = {
    RiskLevel.CRITICAL: 4,
    RiskLevel.HIGH: 3,
    RiskLevel.MEDIUM: 2,
    RiskLevel.LOW: 1,
}

QUALITY_ORDER_RANK: Dict[str, int] = {
    "VALID": 2,
    "PARTIAL": 1,
    "INVALID": 0,
}


def generate_deterministic_factor_id(
    organization_id: Optional[str],
    factor_type: str,
    evidence_ids: List[str],
) -> str:
    """Generate a reproducible UUIDv5 factor identifier based on tenant, factor type, and sorted evidence."""
    org = organization_id or "global"
    evidence_key = ",".join(sorted(evidence_ids)) if evidence_ids else "no_evidence"
    token = f"{org}:factor:{factor_type.upper()}:{evidence_key}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, token))


def generate_deterministic_assessment_id(
    organization_id: Optional[str],
    scope: str,
    signal_ids: List[str],
    eval_time: datetime,
) -> str:
    """Generate a reproducible UUIDv5 assessment identifier based on tenant, scope, signals, and time bucket."""
    org = organization_id or "global"
    signals_key = ",".join(sorted(signal_ids)) if signal_ids else "no_signals"
    time_key = eval_time.strftime("%Y-%m-%d-%H")
    token = f"{org}:assessment:{scope.upper()}:{signals_key}:{time_key}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, token))


def generate_assessment_fingerprint(
    organization_id: Optional[str],
    scope: str,
    signal_ids: List[str],
    factor_ids: List[str],
    score: Optional[float] = None,
    risk_level: Optional[str] = None,
) -> str:
    """Generate a stable, reproducible SHA-256 semantic fingerprint for a risk assessment.

    Excludes volatile runtime fields (wall-clock timestamps, random UUIDs, request IDs).
    """
    org = organization_id or "global"
    signals_token = ",".join(sorted(signal_ids)) if signal_ids else "no_signals"
    factors_token = ",".join(sorted(factor_ids)) if factor_ids else "no_factors"
    score_token = f"{score:.2f}" if score is not None else "no_score"
    level_token = risk_level or "no_level"
    raw_str = f"{org}:{scope.upper()}:{signals_token}:{factors_token}:{score_token}:{level_token}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


class FactorContribution(BaseModel):
    """Traceable factor contribution to composite risk score."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    factor_id: str = Field(..., description="Deterministic factor identifier.")
    factor_type: str = Field(..., description="Classification category of factor.")
    name: str = Field(..., description="Human-readable factor title.")
    raw_contribution: float = Field(..., ge=0.0, le=1.0, description="Direct bounded factor contribution [0, 1].")
    weighted_contribution: float = Field(..., ge=0.0, le=100.0, description="Effective point contribution added to composite score [0, 100].")
    rank: int = Field(..., ge=1, description="Deterministic contribution rank (1 = primary driver).")
    evidence_ids: List[str] = Field(default_factory=list, description="Traceable evidence identifiers supporting this factor.")
    severity: RiskLevel = Field(..., description="Factor severity classification.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Factor confidence.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Calculation metadata.")


class AssessmentSourceSummary(BaseModel):
    """Deterministic summary of evidence sources, counts, and observation types."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    evidence_count: int = Field(default=0, ge=0, description="Total number of evaluated evidence items.")
    independent_sources_count: int = Field(default=0, ge=0, description="Number of unique independent provider/sources.")
    real_sources_count: int = Field(default=0, ge=0, description="Number of unique REAL observation sources.")
    estimated_sources_count: int = Field(default=0, ge=0, description="Number of unique ESTIMATED observation sources.")
    simulated_sources_count: int = Field(default=0, ge=0, description="Number of unique SIMULATED observation sources.")
    corroborating_sources_count: int = Field(default=0, ge=0, description="Number of corroborating external sources.")
    conflicts_count: int = Field(default=0, ge=0, description="Number of detected multi-source conflicts.")
    sources: List[str] = Field(default_factory=list, description="Sorted list of unique primary source names.")
    providers: List[str] = Field(default_factory=list, description="Sorted list of unique provider names.")


class RiskFactor(BaseModel):
    """Normalized contributor to composite risk."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    factor_id: str = Field(..., min_length=1, description="Deterministic factor identifier.")
    factor_type: str = Field(..., min_length=1, description="Classification of the risk factor.")
    domain: SignalDomain = Field(..., description="Top-level domain classification.")
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable factor title.")
    description: Optional[str] = Field(None, description="Detailed explanatory context.")
    contribution: Optional[float] = Field(None, ge=0.0, le=1.0, description="Normalized relative contribution placeholder.")
    severity: RiskLevel = Field(default=RiskLevel.MEDIUM, description="Factor severity classification.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence certainty of the factor evaluation.")
    organization_id: Optional[str] = Field(default=None, description="Tenant organization identifier.")
    evidence_ids: List[str] = Field(default_factory=list, description="Linked deterministic evidence identifiers.")
    evidence: List[RiskEvidence] = Field(default_factory=list, description="Associated traceable evidence records.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Operational telemetry and metadata.")

    @model_validator(mode="after")
    def sync_evidence_linkage(self) -> "RiskFactor":
        """Ensure evidence_ids accurately mirrors attached RiskEvidence and links back."""
        if not self.evidence_ids and self.evidence:
            self.evidence_ids = [e.evidence_id for e in self.evidence]
        for ev in self.evidence:
            if getattr(ev, "factor_id", None) is None:
                ev.factor_id = self.factor_id
            if self.organization_id and getattr(ev, "organization_id", None) is None:
                ev.organization_id = self.organization_id
        return self


def _get_best_evidence_quality_rank(factor: RiskFactor) -> int:
    """Determine highest quality rank from attached evidence."""
    best = 0
    for ev in factor.evidence:
        q = getattr(ev, "quality", None)
        if q is not None:
            q_val = q.value if hasattr(q, "value") else str(q)
            best = max(best, QUALITY_ORDER_RANK.get(q_val, 0))
        elif isinstance(getattr(ev, "metadata", None), dict):
            q_val = ev.metadata.get("quality")
            if q_val:
                best = max(best, QUALITY_ORDER_RANK.get(str(q_val), 0))
    return best


def sort_factors_deterministically(factors: List[RiskFactor]) -> List[RiskFactor]:
    """Sort risk factors deterministically using the stable 5-tuple rule.

    Deterministic Ordering:
    1. contribution (descending)
    2. severity (descending: CRITICAL > HIGH > MEDIUM > LOW)
    3. confidence (descending)
    4. evidence quality (descending: VALID > PARTIAL > INVALID)
    5. factor_id (ascending: alphabetical tie-breaker)
    """
    def _comparator(a: RiskFactor, b: RiskFactor) -> int:
        c_a = a.contribution if a.contribution is not None else 0.0
        c_b = b.contribution if b.contribution is not None else 0.0
        if c_a != c_b:
            return 1 if c_a > c_b else -1

        s_a = SEVERITY_ORDER.get(a.severity, 0)
        s_b = SEVERITY_ORDER.get(b.severity, 0)
        if s_a != s_b:
            return 1 if s_a > s_b else -1

        conf_a = a.confidence if a.confidence is not None else 0.0
        conf_b = b.confidence if b.confidence is not None else 0.0
        if conf_a != conf_b:
            return 1 if conf_a > conf_b else -1

        q_a = _get_best_evidence_quality_rank(a)
        q_b = _get_best_evidence_quality_rank(b)
        if q_a != q_b:
            return 1 if q_a > q_b else -1

        if a.factor_id != b.factor_id:
            return 1 if a.factor_id < b.factor_id else -1
        return 0

    return sorted(factors, key=functools.cmp_to_key(_comparator), reverse=True)


def select_primary_risk_driver(factors: List[RiskFactor]) -> Optional[RiskFactor]:
    """Select the primary risk driver deterministically using the stable 5-tuple ordering."""
    if not factors:
        return None
    sorted_factors = sort_factors_deterministically(factors)
    return sorted_factors[0]


class RiskScore(BaseModel):
    """Strongly typed risk score representation with strict validation boundaries."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Calculated composite risk score [0, 100]. None in Step 1.")
    risk_level: Optional[RiskLevel] = Field(None, description="Categorical risk level classification.")
    probability: Optional[float] = Field(None, ge=0.0, le=1.0, description="Estimated disruption likelihood [0, 1].")
    impact: Optional[float] = Field(None, ge=0.0, le=100.0, description="Estimated operational or financial impact severity [0, 100].")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Probabilistic certainty score [0, 1].")
    organization_id: Optional[str] = Field(default=None, description="Tenant organization scope.")
    primary_factor_id: Optional[str] = Field(default=None, description="Factor ID of the primary risk driver.")
    factor_contributions: List[FactorContribution] = Field(default_factory=list, description="Ordered factor contributions explaining the score.")
    factors: List[RiskFactor] = Field(default_factory=list, description="Contributors evaluated for this score.")
    evidence: List[RiskEvidence] = Field(default_factory=list, description="Underlying evidence items supporting this score.")
    timestamp: datetime = Field(..., description="UTC timestamp of the score evaluation.")

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class RiskAssessment(BaseModel):
    """Authoritative output contract of the Risk Engine evaluating risk across a scope."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    assessment_id: str = Field(..., min_length=1, description="Deterministic assessment identifier.")
    organization_id: str = Field(..., min_length=1, description="Tenant organization scope.")
    evaluated_at: datetime = Field(..., description="UTC evaluation instant.")
    scope: str = Field(default="GLOBAL", description="Evaluation scope (e.g. GLOBAL, SHIPMENT, SUPPLIER, PORT, ROUTE).")
    scope_entity_id: Optional[str] = Field(None, description="Target entity ID if evaluated for a specific network node.")
    scope_entity_type: Optional[EntityType] = Field(None, description="Target entity type if applicable.")
    overall_score: Optional[RiskScore] = Field(None, description="Composite risk score if calculated.")
    risk_level: Optional[RiskLevel] = Field(None, description="Overall categorical risk level.")
    probability: Optional[float] = Field(None, ge=0.0, le=1.0, description="Overall probability indicator.")
    impact: Optional[float] = Field(None, ge=0.0, le=100.0, description="Overall impact indicator.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Overall assessment confidence.")
    primary_factor_id: Optional[str] = Field(default=None, description="Deterministic primary risk driver factor ID.")
    primary_factor: Optional[RiskFactor] = Field(default=None, description="Deterministic primary risk driver.")
    factors: List[RiskFactor] = Field(default_factory=list, description="Evaluated risk factors contributing to assessment.")
    evidence: List[RiskEvidence] = Field(default_factory=list, description="All underlying evidence traces.")
    explanation: Optional[Any] = Field(None, description="Structured human-readable explanation.")
    source_summary: Optional[AssessmentSourceSummary] = Field(default=None, description="Deterministic source summary.")
    limitations: List[str] = Field(default_factory=list, description="Documented assessment limitations and data caveats.")
    conflicts: List[Dict[str, Any]] = Field(default_factory=list, description="Preserved multi-source conflict records.")
    source_signals: List[str] = Field(default_factory=list, description="List of source NormalizedRiskSignal IDs evaluated.")
    fingerprint: Optional[str] = Field(default=None, description="Deterministic semantic fingerprint.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Preserved audit, trace, and conflict metadata.")

    @property
    def score(self) -> Optional[float]:
        """Convenience property accessing composite numerical risk score [0, 100]."""
        return self.overall_score.score if self.overall_score is not None else None

    @field_validator("evaluated_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
