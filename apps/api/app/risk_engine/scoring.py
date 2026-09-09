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
from app.risk_engine.contract import RiskFactor, RiskLevel, RiskScore
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
        - Factors are sorted descending by contribution.
        - Primary factor establishes base score: S_1 = 100.0 * c_1.
        - Subsequent factors compound into remaining risk headroom (100 - S_{k-1})
          with diminishing marginal weight:
              Delta S_k = (100.0 - S_{k-1}) * (c_k * (0.5 / (1.0 + 0.2 * (k - 1))))
        - Score is strictly bounded in [0.0, 100.0].
        - Probability and Impact remain unfabricated (None).
    """

    def aggregate(
        self,
        factors: List[RiskFactor],
        evidence: List[RiskEvidence],
        context: RiskEvaluationContext,
    ) -> RiskScore:
        if not factors:
            return RiskScore(
                score=0.0,
                risk_level=RiskLevel.LOW,
                probability=None,
                impact=None,
                confidence=1.0,
                factors=[],
                evidence=evidence,
                timestamp=context.evaluation_time,
            )

        # Sort factors descending by contribution, breaking ties deterministically by factor_id
        sorted_factors = sorted(
            factors,
            key=lambda f: (f.contribution if f.contribution is not None else 0.0, f.factor_id),
            reverse=True,
        )

        c1 = sorted_factors[0].contribution if sorted_factors[0].contribution is not None else 0.0
        current_score = 100.0 * max(0.0, min(1.0, c1))

        # Compounding loop for secondary factors
        for rank, factor in enumerate(sorted_factors[1:], start=2):
            ck = factor.contribution if factor.contribution is not None else 0.0
            if ck <= 0.0:
                continue
            headroom = 100.0 - current_score
            if headroom <= 0.0:
                break
            diminishing_weight = 0.50 / (1.0 + 0.20 * (rank - 1))
            delta = headroom * (ck * diminishing_weight)
            current_score += delta

        final_score = round(max(0.0, min(100.0, current_score)), 2)
        risk_level = score_to_risk_level(final_score)
        min_confidence = round(min((f.confidence for f in sorted_factors), default=1.0), 4)

        return RiskScore(
            score=final_score,
            risk_level=risk_level,
            probability=None,  # Not fabricated without calibrated probability model
            impact=None,       # Not fabricated without explicit financial/operational model
            confidence=min_confidence,
            factors=sorted_factors,
            evidence=evidence,
            timestamp=context.evaluation_time,
        )
