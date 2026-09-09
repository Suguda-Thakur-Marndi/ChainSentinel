"""Core strongly typed application contracts for RiskWise Risk Engine.

Defines RiskLevel, RiskFactor, RiskScore, and RiskAssessment without committing
to specific numerical scoring mathematics or Bayesian formulas in Step 1.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.normalization.contract import EntityType, SignalDomain
from app.risk_engine.evidence import RiskEvidence


class RiskLevel(str, Enum):
    """Operational risk level classification aligned with core platform severity taxonomy."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


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
    evidence: List[RiskEvidence] = Field(default_factory=list, description="Associated traceable evidence records.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Operational telemetry and metadata.")


class RiskScore(BaseModel):
    """Strongly typed risk score representation with strict validation boundaries."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    score: Optional[float] = Field(None, ge=0.0, le=100.0, description="Calculated composite risk score [0, 100]. None in Step 1.")
    risk_level: Optional[RiskLevel] = Field(None, description="Categorical risk level classification.")
    probability: Optional[float] = Field(None, ge=0.0, le=1.0, description="Estimated disruption likelihood [0, 1].")
    impact: Optional[float] = Field(None, ge=0.0, le=100.0, description="Estimated operational or financial impact severity [0, 100].")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Probabilistic certainty score [0, 1].")
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
    factors: List[RiskFactor] = Field(default_factory=list, description="Evaluated risk factors contributing to assessment.")
    evidence: List[RiskEvidence] = Field(default_factory=list, description="All underlying evidence traces.")
    explanation: Optional[Any] = Field(None, description="Structured human-readable explanation.")
    source_signals: List[str] = Field(default_factory=list, description="List of source NormalizedRiskSignal IDs evaluated.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Preserved audit, trace, and conflict metadata.")

    @field_validator("evaluated_at")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
