"""Deterministic baseline risk scoring formulas, mappings, and aggregator for RiskWise 2.0.

Establishes transparent, bounded, and auditable scoring without machine learning,
Bayesian inference, or external API calls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.canonical import EventQuality, EventSeverity, EventSourceType
from app.normalization.contract import NormalizedRiskSignal
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    FactorContribution,
    RiskFactor,
    RiskLevel,
    RiskScore,
    sort_factors_deterministically,
)
from app.risk_engine.errors import TenantMismatchError
from app.risk_engine.evidence import RiskEvidence
from app.risk_engine.pipeline import RiskScoreAggregatorProtocol

logger = logging.getLogger("riskwise.risk_engine.scoring")

# =============================================================================
# 1. Deterministic Severity Mappings
# =============================================================================

SEVERITY_WEIGHTS: Dict[EventSeverity, float] = {
    EventSeverity.INFO: 0.10,
    EventSeverity.LOW: 0.30,
    EventSeverity.MEDIUM: 0.60,
    EventSeverity.HIGH: 0.85,
    EventSeverity.CRITICAL: 1.00,
}

SEVERITY_TO_RISK_LEVEL: Dict[EventSeverity, RiskLevel] = {
    EventSeverity.INFO: RiskLevel.LOW,
    EventSeverity.LOW: RiskLevel.LOW,
    EventSeverity.MEDIUM: RiskLevel.MEDIUM,
    EventSeverity.HIGH: RiskLevel.HIGH,
    EventSeverity.CRITICAL: RiskLevel.CRITICAL,
}

# =============================================================================
# 2. Quality, Source Type, and Conflict Adjustments
# =============================================================================

QUALITY_MULTIPLIERS: Dict[EventQuality, float] = {
    EventQuality.VALID: 1.00,
    EventQuality.PARTIAL: 0.80,    # 20% discount for completeness uncertainty
    EventQuality.INVALID: 0.00,    # Strictly zero contribution / rejected
}

SOURCE_TYPE_MULTIPLIERS: Dict[EventSourceType, float] = {
    EventSourceType.REAL: 1.00,
    EventSourceType.ESTIMATED: 0.90,  # 10% discount for modeled/inferred observations
    EventSourceType.SIMULATED: 0.70,  # 30% discount for synthetic scenarios
}

CONFLICT_MULTIPLIER = 0.85  # 15% discount reflecting unresolved source disagreement

# =============================================================================
# 3. Factor Contribution Calculation
# =============================================================================

def compute_factor_contribution(
    signal: NormalizedRiskSignal,
) -> Tuple[float, Dict[str, Any]]:
    """Compute a transparent, bounded [0.0, 1.0] factor contribution from a normalized signal.

    Formula:
        base_severity = SEVERITY_WEIGHTS[signal.severity]
        confidence = bounded signal.confidence (default 0.80)
        quality_mult = QUALITY_MULTIPLIERS[signal.quality]
        source_mult = SOURCE_TYPE_MULTIPLIERS[signal.source_type]
        conflict_mult = 0.85 if has_conflict else 1.0

        contribution = base_severity * confidence * quality_mult * source_mult * conflict_mult
    """
    base_severity = SEVERITY_WEIGHTS.get(signal.severity, 0.30)
    confidence = float(signal.confidence if signal.confidence is not None else 0.80)
    confidence = max(0.0, min(1.0, confidence))

    quality_mult = QUALITY_MULTIPLIERS.get(signal.quality, 1.00)
    source_mult = SOURCE_TYPE_MULTIPLIERS.get(signal.source_type, 1.00)
    conflict_mult = CONFLICT_MULTIPLIER if getattr(signal, "has_conflict", False) else 1.00

    raw_contribution = base_severity * confidence * quality_mult * source_mult * conflict_mult
    bounded_contribution = round(max(0.0, min(1.0, raw_contribution)), 4)

    metadata: Dict[str, Any] = {
        "base_severity": base_severity,
        "severity_level": signal.severity.value,
        "confidence": confidence,
        "quality_multiplier": quality_mult,
        "source_type_multiplier": source_mult,
        "conflict_multiplier": conflict_mult,
        "calculated_contribution": bounded_contribution,
    }

    return bounded_contribution, metadata


# =============================================================================
# 4. Risk Level Thresholds
# =============================================================================

def score_to_risk_level(score: float) -> RiskLevel:
    """Map a continuous composite risk score [0.0, 100.0] to a categorical RiskLevel.

    Threshold Boundaries:
        [0.0, 30.0)  -> LOW
        [30.0, 60.0) -> MEDIUM
        [60.0, 85.0) -> HIGH
        [85.0, 100.0] -> CRITICAL
    """
    if score < 30.0:
        return RiskLevel.LOW
    elif score < 60.0:
        return RiskLevel.MEDIUM
    elif score < 85.0:
        return RiskLevel.HIGH
    else:
        return RiskLevel.CRITICAL


# =============================================================================
# 5. Baseline Deterministic Risk Score Aggregator
# =============================================================================

class BaselineRiskScoreAggregator(RiskScoreAggregatorProtocol):
    """Deterministic, bounded baseline risk score aggregator.

    Uses Diminishing Marginal Compound Aggregation (Bounded Saturation):
        - Factors are sorted descending by contribution with stable tie-breaking.
        - Primary factor establishes base score: S_1 = 100.0 * c_1.
        - Subsequent factors compound into remaining risk headroom (100 - S_{k-1})
          with diminishing marginal weight:
              Delta S_k = (100.0 - S_{k-1}) * (c_k * (0.5 / (1.0 + 0.2 * (k - 1))))
        - Traceable FactorContribution objects record exact point contribution Delta S_k.
        - Score is strictly bounded in [0.0, 100.0].
        - Probability and Impact remain unfabricated (None).
    """

    def aggregate(
        self,
        factors: List[RiskFactor],
        evidence: List[RiskEvidence],
        context: RiskEvaluationContext,
    ) -> RiskScore:
        # Enforce strict tenant isolation across factors and evidence
        if context.organization_id:
            for f in factors:
                if f.organization_id and f.organization_id != context.organization_id:
                    raise TenantMismatchError(
                        f"Tenant isolation violated in score aggregation: factor '{f.factor_id}' "
                        f"belongs to organization '{f.organization_id}', expected '{context.organization_id}'."
                    )
            for ev in evidence:
                if ev.organization_id and ev.organization_id != context.organization_id:
                    raise TenantMismatchError(
                        f"Tenant isolation violated in score aggregation: evidence '{ev.evidence_id}' "
                        f"belongs to organization '{ev.organization_id}', expected '{context.organization_id}'."
                    )

        if not factors:
            return RiskScore(
                score=0.0,
                risk_level=RiskLevel.LOW,
                probability=None,
                impact=None,
                confidence=1.0,
                organization_id=context.organization_id,
                primary_factor_id=None,
                factor_contributions=[],
                factors=[],
                evidence=evidence,
                timestamp=context.evaluation_time,
            )

        # Sort factors using deterministic 5-tuple ordering rule
        sorted_factors = sort_factors_deterministically(factors)

        c1 = sorted_factors[0].contribution if sorted_factors[0].contribution is not None else 0.0
        current_score = 100.0 * max(0.0, min(1.0, c1))
        primary_delta = round(current_score, 2)

        factor_contributions: List[FactorContribution] = [
            FactorContribution(
                factor_id=sorted_factors[0].factor_id,
                factor_type=sorted_factors[0].factor_type,
                name=sorted_factors[0].name,
                raw_contribution=c1,
                weighted_contribution=primary_delta,
                rank=1,
                evidence_ids=list(sorted_factors[0].evidence_ids),
                severity=sorted_factors[0].severity,
                confidence=sorted_factors[0].confidence,
                metadata=dict(sorted_factors[0].metadata),
            )
        ]

        # Compounding loop for secondary factors
        for rank, factor in enumerate(sorted_factors[1:], start=2):
            ck = factor.contribution if factor.contribution is not None else 0.0
            if ck <= 0.0:
                factor_contributions.append(
                    FactorContribution(
                        factor_id=factor.factor_id,
                        factor_type=factor.factor_type,
                        name=factor.name,
                        raw_contribution=ck,
                        weighted_contribution=0.0,
                        rank=rank,
                        evidence_ids=list(factor.evidence_ids),
                        severity=factor.severity,
                        confidence=factor.confidence,
                        metadata=dict(factor.metadata),
                    )
                )
                continue

            headroom = 100.0 - current_score
            if headroom <= 0.0:
                delta = 0.0
            else:
                diminishing_weight = 0.50 / (1.0 + 0.20 * (rank - 1))
                delta = headroom * (ck * diminishing_weight)
                current_score += delta

            factor_contributions.append(
                FactorContribution(
                    factor_id=factor.factor_id,
                    factor_type=factor.factor_type,
                    name=factor.name,
                    raw_contribution=ck,
                    weighted_contribution=round(delta, 2),
                    rank=rank,
                    evidence_ids=list(factor.evidence_ids),
                    severity=factor.severity,
                    confidence=factor.confidence,
                    metadata=dict(factor.metadata),
                )
            )

        final_score = round(max(0.0, min(100.0, current_score)), 2)
        risk_level = score_to_risk_level(final_score)
        min_confidence = round(min((f.confidence for f in sorted_factors), default=1.0), 4)

        return RiskScore(
            score=final_score,
            risk_level=risk_level,
            probability=None,  # Not fabricated without calibrated probability model
            impact=None,       # Not fabricated without explicit financial/operational model
            confidence=min_confidence,
            organization_id=context.organization_id,
            primary_factor_id=sorted_factors[0].factor_id,
            factor_contributions=factor_contributions,
            factors=sorted_factors,
            evidence=evidence,
            timestamp=context.evaluation_time,
        )
