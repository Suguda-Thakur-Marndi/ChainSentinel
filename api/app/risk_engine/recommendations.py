"""Deterministic decision and recommendation foundation for RiskWise 2.0 Risk Engine.

Translates an evaluated RiskAssessment and associated RiskAlert records into
structured, explainable, and auditable operational recommendations (RiskRecommendation)
without any reliance on ML, LLMs, LangGraph, Bedrock, or autonomous agent execution.

Human approval and autonomous action are NOT implemented here; recommendations
represent advisory operational review guidance only.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field

from app.normalization.contract import SignalDomain
from app.risk_engine.alerts import AlertRuleConfig, AlertSeverity, RiskAlert, RiskAlertType
from app.risk_engine.contract import RiskAssessment, RiskFactor, RiskLevel
from app.risk_engine.history import HistoricalRiskComparator, RiskTrend
from app.risk_engine.scoring import score_to_risk_level


# ==============================================================================
# 1. ENUMS & CONSTANTS
# ==============================================================================

class RecommendationType(str, Enum):
    """Deterministic taxonomy of operational review recommendations."""

    MONITOR = "MONITOR"
    INVESTIGATE = "INVESTIGATE"
    EXPEDITE_REVIEW = "EXPEDITE_REVIEW"
    REVIEW_ALTERNATE_ROUTE = "REVIEW_ALTERNATE_ROUTE"
    REVIEW_ALTERNATE_SUPPLIER = "REVIEW_ALTERNATE_SUPPLIER"
    REVIEW_INVENTORY = "REVIEW_INVENTORY"
    REVIEW_CARRIER = "REVIEW_CARRIER"
    ESCALATE_OPERATIONAL_ATTENTION = "ESCALATE_OPERATIONAL_ATTENTION"


class RecommendationPriority(str, Enum):
    """Deterministic operational urgency of a recommendation."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendationStatus(str, Enum):
    """Governance lifecycle status of a recommendation."""

    PROPOSED = "PROPOSED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


# Ordinal ranking for deterministic priority comparison and sorting
PRIORITY_RANKS: dict[str, int] = {
    RecommendationPriority.LOW.value: 0,
    RecommendationPriority.MEDIUM.value: 1,
    RecommendationPriority.HIGH.value: 2,
    RecommendationPriority.CRITICAL.value: 3,
}

RISK_LEVEL_RANKS: dict[str, int] = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
    RiskLevel.CRITICAL.value: 3,
}

SENSITIVE_KEY_PATTERNS = {
    "authorization",
    "auth",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "credential",
    "credentials",
    "private_key",
    "cookie",
}

SENSITIVE_STRING_REGEX = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|credential|auth|bearer)[\s:=]+([^\s,;\"']+)",
)


def scrub_sensitive_data(data: Any) -> Any:
    """Recursively scrub sensitive keys, credentials, and tokens from structures."""
    if isinstance(data, str):
        cleaned = SENSITIVE_STRING_REGEX.sub(r"\1=[REDACTED]", data)
        for pattern in (r"(?i)sk_live_[a-zA-Z0-9_\-]+", r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+"):
            cleaned = re.sub(pattern, "[REDACTED]", cleaned)
        return cleaned
    elif isinstance(data, dict):
        cleaned_dict = {}
        for k, v in data.items():
            k_lower = str(k).lower().strip()
            if any(p in k_lower for p in SENSITIVE_KEY_PATTERNS):
                cleaned_dict[k] = "[REDACTED]"
            else:
                cleaned_dict[k] = scrub_sensitive_data(v)
        return cleaned_dict
    elif isinstance(data, list):
        return [scrub_sensitive_data(item) for item in data]
    return data


# ==============================================================================
# 2. DETERMINISTIC IDENTIFIER GENERATOR
# ==============================================================================

def compute_recommendation_id(
    org_id: str,
    assessment_id: str,
    recommendation_type: str,
    entity_key: str = "",
) -> str:
    """Compute a deterministic, collision-resistant recommendation ID.

    Format: rec_<sha256(org:assessment:type:key)[:24]>
    Total length: 28 characters (comfortably within String(64) PK limit).
    Strictly excludes random UUIDs, request IDs, trace IDs, and timestamps.
    """
    raw_key = f"{org_id}:{assessment_id}:{recommendation_type}:{entity_key}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]
    return f"rec_{digest}"


# ==============================================================================
# 3. RULE CONFIGURATION & DOMAIN CONTRACT
# ==============================================================================

class RecommendationRuleConfig(BaseModel):
    """Configurable thresholds and policy switches for recommendation rules."""

    model_config = ConfigDict(frozen=True)

    # Authoritative Step 2 threshold boundaries reused directly from AlertRuleConfig
    medium_threshold: float = 30.0
    high_threshold: float = AlertRuleConfig().high_threshold        # 60.0
    critical_threshold: float = AlertRuleConfig().critical_threshold # 85.0

    # Minimum score required to justify alternate routing reviews
    routing_review_min_score: float = 30.0

    # Minimum score required to justify carrier reviews
    carrier_review_min_score: float = 30.0

    # Enabled recommendation types
    enabled_recommendation_types: Set[RecommendationType] = Field(
        default_factory=lambda: set(RecommendationType)
    )


class RiskRecommendation(BaseModel):
    """Domain model representing a deterministic operational recommendation."""

    model_config = ConfigDict(from_attributes=True)

    recommendation_id: str
    organization_id: str
    assessment_id: str
    risk_id: Optional[str] = None
    scope: Optional[str] = None
    scope_entity_id: Optional[str] = None

    recommendation_type: RecommendationType
    priority: RecommendationPriority
    status: RecommendationStatus = RecommendationStatus.PROPOSED

    title: str
    rationale: str

    factor_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)

    expected_objective: str
    constraints: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    requires_human_approval: bool = True
    confidence: Optional[float] = None
    fingerprint: str = ""
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ==============================================================================
# 4. DETERMINISTIC RECOMMENDATION EVALUATOR
# ==============================================================================

def _assessment_to_dict(asm: RiskAssessment) -> dict[str, Any]:
    """Extract flat dictionary representation for HistoricalRiskComparator."""
    raw_score = asm.score
    if raw_score is None and getattr(asm, "overall_score", None) is not None:
        raw_score = getattr(asm.overall_score, "score", None)
    score_val = round(float(raw_score if raw_score is not None else 0.0), 2)

    level_val = asm.risk_level.value if asm.risk_level else "LOW"
    factors_raw = []
    for f in asm.factors:
        factors_raw.append(
            {
                "factor_id": f.factor_id,
                "factor_type": f.factor_type,
                "name": f.name,
                "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                "confidence": f.confidence,
                "contribution": f.contribution,
                "evidence_ids": getattr(f, "evidence_ids", []),
            }
        )
    return {
        "assessment_id": asm.assessment_id,
        "score": score_val,
        "risk_level": level_val,
        "confidence": asm.confidence,
        "evaluated_at": asm.evaluated_at.isoformat() if asm.evaluated_at else "",
        "factors": factors_raw,
        "primary_factor_id": asm.primary_factor_id,
        "evidence": [e.model_dump() if hasattr(e, "model_dump") else e for e in asm.evidence],
        "conflicts": getattr(asm, "conflicts", []),
        "limitations": getattr(asm, "limitations", []),
    }


class RiskRecommendationEvaluator:
    """Deterministic engine evaluating rule-based operational recommendations."""

    @classmethod
    def evaluate_recommendations(
        cls,
        current: RiskAssessment,
        previous: Optional[RiskAssessment] = None,
        alerts: Optional[List[RiskAlert]] = None,
        config: Optional[RecommendationRuleConfig] = None,
    ) -> list[RiskRecommendation]:
        """Evaluate deterministic decision rules against assessment, history, and alerts."""
        if config is None:
            config = RecommendationRuleConfig()

        recs: list[RiskRecommendation] = []
        org_id = current.organization_id
        assessment_id = current.assessment_id
        risk_id = getattr(current, "risk_id", None)
        scope = getattr(current, "scope", None)
        scope_entity_id = getattr(current, "scope_entity_id", None)

        curr_raw_score = current.score
        if curr_raw_score is None and getattr(current, "overall_score", None) is not None:
            curr_raw_score = getattr(current.overall_score, "score", None)
        current_score = round(float(curr_raw_score if curr_raw_score is not None else 0.0), 2)
        
        # Determine authoritative risk level from assessment or Step 2 score_to_risk_level
        effective_level = current.risk_level or score_to_risk_level(current_score)
        current_level_str = effective_level.value if hasattr(effective_level, "value") else str(effective_level)

        # Baseline tier classification strictly aligned with Step 2 authoritative thresholds:
        # LOW: [0.0, 30.0)
        # MEDIUM: [30.0, 60.0)
        # HIGH: [60.0, 85.0)
        # CRITICAL: [85.0, 100.0]
        is_critical = (effective_level == RiskLevel.CRITICAL or current_score >= config.critical_threshold)
        is_high = not is_critical and (effective_level == RiskLevel.HIGH or config.high_threshold <= current_score < config.critical_threshold)
        is_medium = not is_critical and not is_high and (effective_level == RiskLevel.MEDIUM or config.medium_threshold <= current_score < config.high_threshold)
        is_low = not is_critical and not is_high and not is_medium

        created_at = current.evaluated_at if current.evaluated_at else datetime.now(timezone.utc)
        confidence = current.confidence

        # Baseline assumptions and constraints
        default_assumptions = [
            "Current recommendation is derived deterministically from evaluated normalized risk signals.",
            "Operational impacts remain active until verified or mitigated.",
        ]
        default_constraints = [
            "Route and scheduling alternatives have not yet been evaluated by mathematical optimization.",
            "Alternative supplier capacity and contract terms have not been verified.",
        ]
        assessment_limitations = list(getattr(current, "limitations", []))

        # Check evidence quality for degraded signals
        has_partial_evidence = any(
            getattr(e, "quality", None) and str(getattr(e, "quality", "")).endswith("PARTIAL")
            for e in current.evidence
        )
        if has_partial_evidence:
            assessment_limitations.append(
                "Recommendation is derived from PARTIAL/degraded evidence; field verification advised."
            )

        # ----------------------------------------------------------------------
        # Rule 1: LOW RISK -> MONITOR
        # ----------------------------------------------------------------------
        if is_low and RecommendationType.MONITOR in config.enabled_recommendation_types:
            rec_id = compute_recommendation_id(org_id, assessment_id, RecommendationType.MONITOR.value)
            recs.append(
                RiskRecommendation(
                    recommendation_id=rec_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=risk_id,
                    scope=scope,
                    scope_entity_id=scope_entity_id,
                    recommendation_type=RecommendationType.MONITOR,
                    priority=RecommendationPriority.LOW,
                    title="[MONITOR] Maintain standard operational surveillance",
                    rationale=(
                        f"Operational risk score is LOW ({current_score:.1f}/100). "
                        "Signals indicate baseline normal operating conditions; maintain routine surveillance."
                    ),
                    factor_ids=[f.factor_id for f in current.factors[:3]],
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    expected_objective="PROTECT_SERVICE_LEVEL",
                    constraints=default_constraints,
                    assumptions=default_assumptions,
                    limitations=assessment_limitations,
                    requires_human_approval=True,
                    confidence=confidence,
                    fingerprint=rec_id,
                    created_at=created_at,
                    metadata={"risk_score": current_score, "risk_level": current_level_str},
                )
            )

        # ----------------------------------------------------------------------
        # Rule 2: MEDIUM RISK -> MONITOR / INVESTIGATE
        # ----------------------------------------------------------------------
        if is_medium and RecommendationType.MONITOR in config.enabled_recommendation_types:
            rec_id = compute_recommendation_id(org_id, assessment_id, RecommendationType.MONITOR.value)
            recs.append(
                RiskRecommendation(
                    recommendation_id=rec_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=risk_id,
                    scope=scope,
                    scope_entity_id=scope_entity_id,
                    recommendation_type=RecommendationType.MONITOR,
                    priority=RecommendationPriority.MEDIUM,
                    title="[MONITOR] Heightened monitoring for emerging risk drivers",
                    rationale=(
                        f"Operational risk score is MEDIUM ({current_score:.1f}/100). "
                        "Moderate risk contributors detected; heightened surveillance of key indicators advised."
                    ),
                    factor_ids=[f.factor_id for f in current.factors[:3]],
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    expected_objective="PROTECT_SERVICE_LEVEL",
                    constraints=default_constraints,
                    assumptions=default_assumptions,
                    limitations=assessment_limitations,
                    requires_human_approval=True,
                    confidence=confidence,
                    fingerprint=rec_id,
                    created_at=created_at,
                    metadata={"risk_score": current_score, "risk_level": current_level_str},
                )
            )

        # ----------------------------------------------------------------------
        # Rule 3: HIGH RISK -> ESCALATE_OPERATIONAL_ATTENTION
        # ----------------------------------------------------------------------
        if is_high and RecommendationType.ESCALATE_OPERATIONAL_ATTENTION in config.enabled_recommendation_types:
            rec_id = compute_recommendation_id(
                org_id, assessment_id, RecommendationType.ESCALATE_OPERATIONAL_ATTENTION.value
            )
            recs.append(
                RiskRecommendation(
                    recommendation_id=rec_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=risk_id,
                    scope=scope,
                    scope_entity_id=scope_entity_id,
                    recommendation_type=RecommendationType.ESCALATE_OPERATIONAL_ATTENTION,
                    priority=RecommendationPriority.HIGH,
                    title="[ESCALATE] Escalate operational attention to logistics managers",
                    rationale=(
                        f"Risk score reached HIGH threshold ({current_score:.1f}/100). "
                        "Recommend briefing logistics coordinators and actively reviewing mitigation options."
                    ),
                    factor_ids=[f.factor_id for f in current.factors if f.severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)],
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    expected_objective="REDUCE_DISRUPTION_EXPOSURE",
                    constraints=default_constraints,
                    assumptions=default_assumptions,
                    limitations=assessment_limitations,
                    requires_human_approval=True,
                    confidence=confidence,
                    fingerprint=rec_id,
                    created_at=created_at,
                    metadata={"risk_score": current_score, "risk_level": current_level_str},
                )
            )

        # ----------------------------------------------------------------------
        # Rule 4: CRITICAL RISK -> ESCALATE_OPERATIONAL_ATTENTION & EXPEDITE_REVIEW
        # ----------------------------------------------------------------------
        if is_critical:
            if RecommendationType.ESCALATE_OPERATIONAL_ATTENTION in config.enabled_recommendation_types:
                rec_id = compute_recommendation_id(
                    org_id, assessment_id, RecommendationType.ESCALATE_OPERATIONAL_ATTENTION.value
                )
                recs.append(
                    RiskRecommendation(
                        recommendation_id=rec_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=risk_id,
                        scope=scope,
                        scope_entity_id=scope_entity_id,
                        recommendation_type=RecommendationType.ESCALATE_OPERATIONAL_ATTENTION,
                        priority=RecommendationPriority.CRITICAL,
                        title="[ESCALATE] Critical escalation: immediate operational briefing required",
                        rationale=(
                            f"Risk score reached CRITICAL threshold ({current_score:.1f}/100). "
                            "Immediate operational escalation and active risk containment required."
                        ),
                        factor_ids=[f.factor_id for f in current.factors if f.severity in (RiskLevel.HIGH, RiskLevel.CRITICAL)],
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        expected_objective="REDUCE_DISRUPTION_EXPOSURE",
                        constraints=default_constraints,
                        assumptions=default_assumptions,
                        limitations=assessment_limitations,
                        requires_human_approval=True,
                        confidence=confidence,
                        fingerprint=rec_id,
                        created_at=created_at,
                        metadata={"risk_score": current_score, "risk_level": current_level_str},
                    )
                )

            if RecommendationType.EXPEDITE_REVIEW in config.enabled_recommendation_types:
                rec_id = compute_recommendation_id(
                    org_id, assessment_id, RecommendationType.EXPEDITE_REVIEW.value
                )
                recs.append(
                    RiskRecommendation(
                        recommendation_id=rec_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=risk_id,
                        scope=scope,
                        scope_entity_id=scope_entity_id,
                        recommendation_type=RecommendationType.EXPEDITE_REVIEW,
                        priority=RecommendationPriority.CRITICAL,
                        title="[EXPEDITE] Expedite operational review of active shipments",
                        rationale=(
                            f"Critical risk assessment ({current_score:.1f}/100) mandates expedited review "
                            "of potentially impacted shipments and facility operations."
                        ),
                        factor_ids=[f.factor_id for f in current.factors[:3]],
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        expected_objective="PROTECT_SERVICE_LEVEL",
                        constraints=default_constraints,
                        assumptions=default_assumptions,
                        limitations=assessment_limitations,
                        requires_human_approval=True,
                        confidence=confidence,
                        fingerprint=rec_id,
                        created_at=created_at,
                        metadata={"risk_score": current_score, "risk_level": current_level_str},
                    )
                )

        # ----------------------------------------------------------------------
        # Rule 5: CRITICAL FACTOR -> EXPEDITE_REVIEW
        # ----------------------------------------------------------------------
        if RecommendationType.EXPEDITE_REVIEW in config.enabled_recommendation_types:
            for factor in current.factors:
                if factor.severity == RiskLevel.CRITICAL:
                    rec_id = compute_recommendation_id(
                        org_id,
                        assessment_id,
                        RecommendationType.EXPEDITE_REVIEW.value,
                        entity_key=factor.factor_id,
                    )
                    # Check if already present to avoid duplicate EXPEDITE_REVIEW with same key
                    if not any(r.recommendation_id == rec_id for r in recs):
                        recs.append(
                            RiskRecommendation(
                                recommendation_id=rec_id,
                                organization_id=org_id,
                                assessment_id=assessment_id,
                                risk_id=risk_id,
                                scope=scope,
                                scope_entity_id=scope_entity_id,
                                recommendation_type=RecommendationType.EXPEDITE_REVIEW,
                                priority=RecommendationPriority.CRITICAL,
                                title=f"[EXPEDITE] Expedite review for critical factor: {factor.name}",
                                rationale=(
                                    f"Critical severity risk factor detected: '{factor.name}'. "
                                    "Expedited operational review of affected assets recommended."
                                ),
                                factor_ids=[factor.factor_id],
                                evidence_ids=factor.evidence_ids[:5],
                                expected_objective="REDUCE_DISRUPTION_EXPOSURE",
                                constraints=default_constraints,
                                assumptions=default_assumptions,
                                limitations=assessment_limitations,
                                requires_human_approval=True,
                                confidence=factor.confidence,
                                fingerprint=rec_id,
                                created_at=created_at,
                                metadata={
                                    "factor_name": factor.name,
                                    "factor_type": factor.factor_type,
                                    "factor_severity": "CRITICAL",
                                },
                            )
                        )

        # ----------------------------------------------------------------------
        # Rule 6: DOMAIN SPECIFIC DISRUPTIONS
        # ----------------------------------------------------------------------
        for factor in current.factors:
            f_domain_str = (
                factor.domain.value if hasattr(factor.domain, "value") else str(factor.domain)
            ).upper()
            f_type_str = str(factor.factor_type).upper()
            f_name_str = str(factor.name).lower()
            f_sev_val = factor.severity.value if hasattr(factor.severity, "value") else str(factor.severity)

            # Map factor severity to recommendation priority
            rec_prio = (
                RecommendationPriority.CRITICAL
                if f_sev_val == "CRITICAL"
                else (
                    RecommendationPriority.HIGH
                    if f_sev_val == "HIGH"
                    else RecommendationPriority.MEDIUM
                )
            )

            # 6a. PORT / ROAD / OCEAN Disruption -> REVIEW_ALTERNATE_ROUTE
            is_routing_disruption = (
                f_domain_str in ("ROAD", "OCEAN")
                or "PORT" in f_domain_str
                or f_type_str in ("ROAD", "PORT", "OCEAN", "MARITIME")
                or any(term in f_name_str for term in ("port", "road", "typhoon", "highway", "canal", "chokepoint"))
            )
            if (
                is_routing_disruption
                and current_score >= config.routing_review_min_score
                and RecommendationType.REVIEW_ALTERNATE_ROUTE in config.enabled_recommendation_types
            ):
                rec_id = compute_recommendation_id(
                    org_id,
                    assessment_id,
                    RecommendationType.REVIEW_ALTERNATE_ROUTE.value,
                    entity_key=factor.factor_id,
                )
                if not any(r.recommendation_id == rec_id for r in recs):
                    recs.append(
                        RiskRecommendation(
                            recommendation_id=rec_id,
                            organization_id=org_id,
                            assessment_id=assessment_id,
                            risk_id=risk_id,
                            scope=scope,
                            scope_entity_id=scope_entity_id,
                            recommendation_type=RecommendationType.REVIEW_ALTERNATE_ROUTE,
                            priority=rec_prio,
                            title=f"[ROUTE] Review alternate routing to bypass: {factor.name}",
                            rationale=(
                                f"Corridor disruption factor '{factor.name}' detected with {f_sev_val} severity. "
                                "Recommend evaluating alternate transport corridors or rerouting options."
                            ),
                            factor_ids=[factor.factor_id],
                            evidence_ids=factor.evidence_ids[:5],
                            expected_objective="REDUCE_DELAY_RISK",
                            constraints=default_constraints,
                            assumptions=default_assumptions,
                            limitations=assessment_limitations,
                            requires_human_approval=True,
                            confidence=factor.confidence,
                            fingerprint=rec_id,
                            created_at=created_at,
                            metadata={"trigger_factor": factor.name, "factor_severity": f_sev_val},
                        )
                    )

            # 6d. INVENTORY Disruption -> REVIEW_INVENTORY
            is_inventory_disruption = (
                "inventory" in f_type_str.lower()
                or "warehouse" in f_type_str.lower()
                or "inventory" in f_name_str
                or "stock" in f_name_str
                or "warehouse" in f_name_str
                or "storage" in f_name_str
                or "spoilage" in f_name_str
                or scope in ("INVENTORY", "WAREHOUSE")
            )
            if (
                is_inventory_disruption
                and current_score >= config.medium_threshold
                and RecommendationType.REVIEW_INVENTORY in config.enabled_recommendation_types
            ):
                rec_id = compute_recommendation_id(
                    org_id,
                    assessment_id,
                    RecommendationType.REVIEW_INVENTORY.value,
                    entity_key=factor.factor_id,
                )
                if not any(r.recommendation_id == rec_id for r in recs):
                    recs.append(
                        RiskRecommendation(
                            recommendation_id=rec_id,
                            organization_id=org_id,
                            assessment_id=assessment_id,
                            risk_id=risk_id,
                            scope=scope,
                            scope_entity_id=scope_entity_id,
                            recommendation_type=RecommendationType.REVIEW_INVENTORY,
                            priority=rec_prio,
                            title=f"[INVENTORY] Review inventory buffer levels: {factor.name}",
                            rationale=(
                                f"Inventory vulnerability factor '{factor.name}' detected with {f_sev_val} severity. "
                                "Recommend reviewing safety stock buffers and consumption velocity."
                            ),
                            factor_ids=[factor.factor_id],
                            evidence_ids=factor.evidence_ids[:5],
                            expected_objective="PROTECT_SERVICE_LEVEL",
                            constraints=default_constraints,
                            assumptions=default_assumptions,
                            limitations=assessment_limitations,
                            requires_human_approval=True,
                            confidence=factor.confidence,
                            fingerprint=rec_id,
                            created_at=created_at,
                            metadata={"trigger_factor": factor.name, "factor_severity": f_sev_val},
                        )
                    )

            # 6b. LOGISTICS / CARRIER Disruption -> REVIEW_CARRIER
            is_carrier_disruption = (
                not is_inventory_disruption
                and (
                    f_domain_str in ("AIR", "RAIL")
                    or (f_domain_str == "LOGISTICS" and "inventory" not in f_type_str.lower())
                    or f_type_str in ("AIR", "RAIL", "CARRIER")
                    or any(term in f_name_str for term in ("carrier", "flight", "rail", "booking", "capacity", "freight"))
                )
            )
            if (
                is_carrier_disruption
                and current_score >= config.carrier_review_min_score
                and RecommendationType.REVIEW_CARRIER in config.enabled_recommendation_types
            ):
                rec_id = compute_recommendation_id(
                    org_id,
                    assessment_id,
                    RecommendationType.REVIEW_CARRIER.value,
                    entity_key=factor.factor_id,
                )
                if not any(r.recommendation_id == rec_id for r in recs):
                    recs.append(
                        RiskRecommendation(
                            recommendation_id=rec_id,
                            organization_id=org_id,
                            assessment_id=assessment_id,
                            risk_id=risk_id,
                            scope=scope,
                            scope_entity_id=scope_entity_id,
                            recommendation_type=RecommendationType.REVIEW_CARRIER,
                            priority=rec_prio,
                            title=f"[CARRIER] Review carrier capacity and performance: {factor.name}",
                            rationale=(
                                f"Logistics/carrier disruption factor '{factor.name}' detected with {f_sev_val} severity. "
                                "Recommend reviewing carrier transit schedules and contingency capacity."
                            ),
                            factor_ids=[factor.factor_id],
                            evidence_ids=factor.evidence_ids[:5],
                            expected_objective="REDUCE_DELAY_RISK",
                            constraints=default_constraints,
                            assumptions=default_assumptions,
                            limitations=assessment_limitations,
                            requires_human_approval=True,
                            confidence=factor.confidence,
                            fingerprint=rec_id,
                            created_at=created_at,
                            metadata={"trigger_factor": factor.name, "factor_severity": f_sev_val},
                        )
                    )

            # 6c. SUPPLIER Disruption -> REVIEW_ALTERNATE_SUPPLIER
            is_supplier_disruption = (
                f_domain_str == "SUPPLIER"
                or "supplier" in f_type_str.lower()
                or "supplier" in f_name_str
                or "factory" in f_name_str
            )
            if (
                is_supplier_disruption
                and RecommendationType.REVIEW_ALTERNATE_SUPPLIER in config.enabled_recommendation_types
            ):
                rec_id = compute_recommendation_id(
                    org_id,
                    assessment_id,
                    RecommendationType.REVIEW_ALTERNATE_SUPPLIER.value,
                    entity_key=factor.factor_id,
                )
                if not any(r.recommendation_id == rec_id for r in recs):
                    recs.append(
                        RiskRecommendation(
                            recommendation_id=rec_id,
                            organization_id=org_id,
                            assessment_id=assessment_id,
                            risk_id=risk_id,
                            scope=scope,
                            scope_entity_id=scope_entity_id,
                            recommendation_type=RecommendationType.REVIEW_ALTERNATE_SUPPLIER,
                            priority=rec_prio,
                            title=f"[SUPPLIER] Review secondary supplier readiness: {factor.name}",
                            rationale=(
                                f"Supplier operational risk factor '{factor.name}' detected with {f_sev_val} severity. "
                                "Recommend evaluating secondary sourcing options and replenishment lead times."
                            ),
                            factor_ids=[factor.factor_id],
                            evidence_ids=factor.evidence_ids[:5],
                            expected_objective="REVIEW_SUPPLY_CONTINUITY",
                            constraints=default_constraints,
                            assumptions=default_assumptions,
                            limitations=assessment_limitations,
                            requires_human_approval=True,
                            confidence=factor.confidence,
                            fingerprint=rec_id,
                            created_at=created_at,
                            metadata={"trigger_factor": factor.name, "factor_severity": f_sev_val},
                        )
                    )

        # ----------------------------------------------------------------------
        # Rule 7: NEW CONFLICT -> INVESTIGATE
        # ----------------------------------------------------------------------
        conflicts = getattr(current, "conflicts", [])
        if (
            len(conflicts) > 0
            and RecommendationType.INVESTIGATE in config.enabled_recommendation_types
        ):
            rec_id = compute_recommendation_id(
                org_id, assessment_id, RecommendationType.INVESTIGATE.value, entity_key="conflict"
            )
            if not any(r.recommendation_id == rec_id for r in recs):
                recs.append(
                    RiskRecommendation(
                        recommendation_id=rec_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=risk_id,
                        scope=scope,
                        scope_entity_id=scope_entity_id,
                        recommendation_type=RecommendationType.INVESTIGATE,
                        priority=RecommendationPriority.MEDIUM,
                        title="[INVESTIGATE] Investigate multi-source signal discrepancies",
                        rationale=(
                            f"Multi-source signal conflicts detected ({len(conflicts)} conflict(s)). "
                            "Recommend field investigation and provider data reconciliation."
                        ),
                        factor_ids=[f.factor_id for f in current.factors[:2]],
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        expected_objective="IMPROVE_VISIBILITY",
                        constraints=default_constraints,
                        assumptions=default_assumptions,
                        limitations=assessment_limitations,
                        requires_human_approval=True,
                        confidence=confidence,
                        fingerprint=rec_id,
                        created_at=created_at,
                        metadata={"conflict_count": len(conflicts)},
                    )
                )

        # ----------------------------------------------------------------------
        # Rule 8: INCREASING TREND (History-based) -> ESCALATE_OPERATIONAL_ATTENTION
        # ----------------------------------------------------------------------
        if previous and RecommendationType.ESCALATE_OPERATIONAL_ATTENTION in config.enabled_recommendation_types:
            curr_dict = _assessment_to_dict(current)
            prev_dict = _assessment_to_dict(previous)
            comparison = HistoricalRiskComparator.compare(current=curr_dict, previous=prev_dict)
            if (
                comparison.direction == RiskTrend.INCREASING
                and current_score >= config.high_threshold
            ):
                rec_id = compute_recommendation_id(
                    org_id,
                    assessment_id,
                    RecommendationType.ESCALATE_OPERATIONAL_ATTENTION.value,
                    entity_key="increasing_trend",
                )
                if not any(r.recommendation_id == rec_id for r in recs):
                    trend_prio = (
                        RecommendationPriority.CRITICAL
                        if current_score >= config.critical_threshold
                        else RecommendationPriority.HIGH
                    )
                    recs.append(
                        RiskRecommendation(
                            recommendation_id=rec_id,
                            organization_id=org_id,
                            assessment_id=assessment_id,
                            risk_id=risk_id,
                            scope=scope,
                            scope_entity_id=scope_entity_id,
                            recommendation_type=RecommendationType.ESCALATE_OPERATIONAL_ATTENTION,
                            priority=trend_prio,
                            title="[ESCALATE] Upward risk trend detected: active mitigation review required",
                            rationale=(
                                f"Risk trend is INCREASING with current score at {current_score:.1f} "
                                f"(+{comparison.score_delta:+.1f} pts). Proactive operational escalation advised."
                            ),
                            factor_ids=[f.factor_id for f in current.factors[:3]],
                            evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                            expected_objective="REDUCE_DISRUPTION_EXPOSURE",
                            constraints=default_constraints,
                            assumptions=default_assumptions,
                            limitations=assessment_limitations,
                            requires_human_approval=True,
                            confidence=confidence,
                            fingerprint=rec_id,
                            created_at=created_at,
                            metadata={"score_delta": comparison.score_delta, "trend": "INCREASING"},
                        )
                    )

        # ----------------------------------------------------------------------
        # 5. CONFLICT RESOLUTION & SUPPRESSION
        # ----------------------------------------------------------------------
        # If active operational review recommendations exist at HIGH/CRITICAL risk,
        # suppress the generic MONITOR recommendation to prevent diluted attention.
        has_active_review = any(
            r.recommendation_type in (
                RecommendationType.REVIEW_ALTERNATE_ROUTE,
                RecommendationType.REVIEW_ALTERNATE_SUPPLIER,
                RecommendationType.REVIEW_INVENTORY,
                RecommendationType.REVIEW_CARRIER,
                RecommendationType.EXPEDITE_REVIEW,
                RecommendationType.ESCALATE_OPERATIONAL_ATTENTION,
            )
            for r in recs
        )
        if has_active_review and current_score >= config.high_threshold:
            recs = [r for r in recs if r.recommendation_type != RecommendationType.MONITOR]

        # ----------------------------------------------------------------------
        # 6. DETERMINISTIC ORDERING
        # ----------------------------------------------------------------------
        # 1. Priority descending (CRITICAL -> HIGH -> MEDIUM -> LOW)
        # 2. Recommendation type name ascending
        # 3. Recommendation ID ascending
        recs.sort(
            key=lambda r: (
                -PRIORITY_RANKS.get(r.priority.value, 0),
                r.recommendation_type.value,
                r.recommendation_id,
            )
        )

        # Scrub all sensitive credentials, tokens, and keys from recommendations
        for r in recs:
            r.title = scrub_sensitive_data(r.title)
            r.rationale = scrub_sensitive_data(r.rationale)
            r.limitations = scrub_sensitive_data(r.limitations)
            r.constraints = scrub_sensitive_data(r.constraints)
            r.assumptions = scrub_sensitive_data(r.assumptions)
            r.metadata = scrub_sensitive_data(r.metadata)

        return recs


# ==============================================================================
# 5. ORM PERSISTENCE ADAPTER
# ==============================================================================

class RiskRecommendationAdapter:
    """Bidirectional serializer between RiskRecommendation and PostgreSQL Recommendation model."""

    @staticmethod
    def to_orm(rec: RiskRecommendation) -> Any:
        """Serialize a domain RiskRecommendation into a PostgreSQL Recommendation model."""
        from app.models.governance import Recommendation

        # Pack full domain model into expected_benefit_json for zero-data-loss lineage
        payload = rec.model_dump(mode="json")

        return Recommendation(
            id=rec.recommendation_id,
            org_id=rec.organization_id,
            incident_id=None,
            title=rec.title[:255],
            rationale=rec.rationale[:1000] if rec.rationale else None,
            estimated_cost=None,
            expected_benefit_json=payload,
            confidence=rec.confidence,
            status=rec.status.value,
            created_at=rec.created_at,
        )

    @staticmethod
    def from_orm(orm: Any) -> RiskRecommendation:
        """Reconstruct domain RiskRecommendation from PostgreSQL Recommendation entity."""
        data = getattr(orm, "expected_benefit_json", {}) or {}
        if data and "recommendation_id" in data:
            # Parse datetime fields
            if "created_at" in data and isinstance(data["created_at"], str):
                try:
                    data["created_at"] = datetime.fromisoformat(data["created_at"])
                except Exception:
                    data["created_at"] = orm.created_at or datetime.now(timezone.utc)
            return RiskRecommendation(**data)

        # Fallback reconstruction from raw columns
        return RiskRecommendation(
            recommendation_id=orm.id,
            organization_id=orm.org_id or "",
            assessment_id="",
            recommendation_type=RecommendationType.MONITOR,
            priority=RecommendationPriority.MEDIUM,
            status=RecommendationStatus(orm.status) if orm.status in RecommendationStatus._value2member_map_ else RecommendationStatus.PROPOSED,
            title=orm.title,
            rationale=orm.rationale or "",
            expected_objective="PROTECT_SERVICE_LEVEL",
            requires_human_approval=True,
            confidence=orm.confidence,
            created_at=orm.created_at or datetime.now(timezone.utc),
            metadata={},
        )
