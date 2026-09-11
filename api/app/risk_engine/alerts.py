"""Risk Alerts, Thresholds & Escalation Module (Phase 7 Step 6).

Deterministic, rule-based risk alert evaluation, threshold monitoring,
semantic alert deduplication, and notification adapter for RiskWise 2.0.

Adheres to:
- Pure deterministic rules (no ML, LLM, LangGraph, Bedrock, or Bayesian inference).
- Step 2 risk level boundaries ([0,30) LOW, [30,60) MEDIUM, [60,85) HIGH, [85,100] CRITICAL).
- Step 3 deterministic primary driver and evidence lineage.
- Step 4 PostgreSQL persistence and atomic transactions.
- Step 5 historical comparison and trend classifications.
- Server-side tenant isolation and secret scrubbing.
- Existing 34-table schema (persisting alerts into notifications table).
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.governance import Notification
from app.risk_engine.contract import (
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)
from app.risk_engine.history import (
    ConflictChangeStatus,
    DriverChangeStatus,
    HistoricalRiskComparator,
    QualityChangeStatus,
    RiskTrend,
)


class RiskAlertType(str, Enum):
    """Categorical trigger types for deterministic risk alerts."""
    HIGH_RISK_REACHED = "HIGH_RISK_REACHED"
    CRITICAL_RISK_REACHED = "CRITICAL_RISK_REACHED"
    RISK_LEVEL_INCREASED = "RISK_LEVEL_INCREASED"
    RISK_LEVEL_DECREASED = "RISK_LEVEL_DECREASED"
    RISK_SCORE_INCREASED = "RISK_SCORE_INCREASED"
    RISK_TREND_INCREASING = "RISK_TREND_INCREASING"
    PRIMARY_DRIVER_CHANGED = "PRIMARY_DRIVER_CHANGED"
    CRITICAL_FACTOR_DETECTED = "CRITICAL_FACTOR_DETECTED"
    NEW_CONFLICT = "NEW_CONFLICT"
    QUALITY_DEGRADED = "QUALITY_DEGRADED"


class AlertSeverity(str, Enum):
    """Operational urgency and priority level of a risk alert."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    """Lifecycle state of a risk alert."""
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


# Risk level ordinal ranks for transition detection
RISK_LEVEL_RANKS: dict[str, int] = {
    RiskLevel.LOW.value: 0,
    RiskLevel.MEDIUM.value: 1,
    RiskLevel.HIGH.value: 2,
    RiskLevel.CRITICAL.value: 3,
}


def compute_alert_id(
    org_id: str,
    assessment_id: str,
    alert_type: str,
    entity_key: str = "",
) -> str:
    """Compute deterministic, collision-resistant alert ID.

    Format: alt_<sha256(org:assessment:type:key)[:24]>
    Total length: 28 characters (well within String(64) PK limit).
    Never incorporates timestamps, UUIDs, or random tokens.
    """
    raw_key = f"{org_id}:{assessment_id}:{alert_type}:{entity_key}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]
    return f"alt_{digest}"


class AlertRuleConfig(BaseModel):
    """Configuration options for deterministic risk alert rules."""
    model_config = ConfigDict(frozen=True)

    # Threshold boundaries from Step 2
    high_threshold: float = 60.0
    critical_threshold: float = 85.0

    # Material score jump delta
    score_jump_threshold: float = 15.0

    # Minimum score required to alert on primary driver changes
    driver_change_min_score: float = 30.0

    # Minimum score required to alert on increasing trend
    increasing_trend_min_score: float = 60.0

    # Enabled alert types
    enabled_alert_types: set[RiskAlertType] = Field(
        default_factory=lambda: set(RiskAlertType)
    )


class RiskAlert(BaseModel):
    """Domain model representing a deterministic operational risk alert."""
    model_config = ConfigDict(from_attributes=True)

    alert_id: str
    organization_id: str
    assessment_id: str
    risk_id: Optional[str] = None
    scope: Optional[str] = None
    scope_entity_id: Optional[str] = None
    alert_type: RiskAlertType
    severity: AlertSeverity
    previous_score: Optional[float] = None
    current_score: float
    score_delta: Optional[float] = None
    previous_risk_level: Optional[str] = None
    current_risk_level: Optional[str] = None
    trigger_reason: str
    factor_id: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    status: AlertStatus = AlertStatus.OPEN
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


def _assessment_to_dict(asm: RiskAssessment) -> dict[str, Any]:
    score_val = asm.score
    if score_val is None and getattr(asm, "overall_score", None) is not None:
        score_val = getattr(asm.overall_score, "score", None)

    driver = None
    if getattr(asm, "primary_factor", None) is not None:
        pf = asm.primary_factor
        driver = {
            "factor_id": pf.factor_id,
            "name": pf.name,
            "severity": pf.severity.value if hasattr(pf.severity, "value") else str(pf.severity),
            "contribution": pf.contribution,
        }
    elif getattr(asm, "primary_factor_id", None):
        driver = {"factor_id": asm.primary_factor_id, "name": asm.primary_factor_id}

    return {
        "assessment_id": asm.assessment_id,
        "score": score_val if score_val is not None else 0.0,
        "risk_level": asm.risk_level.value if asm.risk_level else "LOW",
        "created_at": asm.evaluated_at,
        "evaluated_at": asm.evaluated_at,
        "primary_factor_id": asm.primary_factor_id,
        "primary_driver": driver,
        "factors": [
            {
                "factor_id": f.factor_id,
                "factor_type": f.factor_type,
                "name": f.name,
                "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                "confidence": f.confidence,
                "contribution": f.contribution,
            }
            for f in getattr(asm, "factors", [])
        ],
        "evidence": [{"evidence_id": e.evidence_id} for e in getattr(asm, "evidence", [])],
        "conflicts": getattr(asm, "conflicts", []),
        "limitations": getattr(asm, "limitations", []),
    }


class RiskAlertEvaluator:
    """Deterministic engine evaluating risk alerts from assessment states and transitions."""

    @classmethod
    def evaluate_alerts(
        cls,
        current: RiskAssessment,
        previous: Optional[RiskAssessment] = None,
        config: Optional[AlertRuleConfig] = None,
    ) -> list[RiskAlert]:
        """Evaluate all deterministic alert rules against current and previous assessments."""
        if config is None:
            config = AlertRuleConfig()

        alerts: list[RiskAlert] = []
        org_id = current.organization_id
        assessment_id = current.assessment_id

        curr_raw_score = current.score
        if curr_raw_score is None and getattr(current, "overall_score", None) is not None:
            curr_raw_score = getattr(current.overall_score, "score", None)
        current_score = round(float(curr_raw_score if curr_raw_score is not None else 0.0), 2)
        current_level_str = current.risk_level.value if current.risk_level else "LOW"
        created_at = current.evaluated_at if current.evaluated_at else datetime.now(timezone.utc)

        prev_raw_score = previous.score if previous else None
        if prev_raw_score is None and previous and getattr(previous, "overall_score", None) is not None:
            prev_raw_score = getattr(previous.overall_score, "score", None)
        previous_score = round(float(prev_raw_score), 2) if prev_raw_score is not None else None
        previous_level_str = previous.risk_level.value if previous and previous.risk_level else None

        score_delta: Optional[float] = None
        if previous_score is not None:
            score_delta = round(current_score - previous_score, 2)

        # 1. CRITICAL_RISK_REACHED (current >= 85.0 and [previous is None or previous < 85.0])
        if (
            RiskAlertType.CRITICAL_RISK_REACHED in config.enabled_alert_types
            and current_score >= config.critical_threshold
            and (previous_score is None or previous_score < config.critical_threshold)
        ):
            alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.CRITICAL_RISK_REACHED.value)
            reason = (
                f"Risk score reached CRITICAL threshold at {current_score:.1f} "
                f"(>= {config.critical_threshold:.1f})."
            )
            alerts.append(
                RiskAlert(
                    alert_id=alert_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                    scope=current.scope if hasattr(current, "scope") else None,
                    scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                    alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
                    severity=AlertSeverity.CRITICAL,
                    previous_score=previous_score,
                    current_score=current_score,
                    score_delta=score_delta,
                    previous_risk_level=previous_level_str,
                    current_risk_level=current_level_str,
                    trigger_reason=reason,
                    factor_id=current.primary_factor_id,
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    created_at=created_at,
                    metadata={"critical_threshold": config.critical_threshold},
                )
            )

        # 2. HIGH_RISK_REACHED (60.0 <= current < 85.0 and [previous is None or previous < 60.0])
        if (
            RiskAlertType.HIGH_RISK_REACHED in config.enabled_alert_types
            and config.high_threshold <= current_score < config.critical_threshold
            and (previous_score is None or previous_score < config.high_threshold)
        ):
            alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.HIGH_RISK_REACHED.value)
            reason = (
                f"Risk score reached HIGH threshold at {current_score:.1f} "
                f"(>= {config.high_threshold:.1f})."
            )
            alerts.append(
                RiskAlert(
                    alert_id=alert_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                    scope=current.scope if hasattr(current, "scope") else None,
                    scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                    alert_type=RiskAlertType.HIGH_RISK_REACHED,
                    severity=AlertSeverity.WARNING,
                    previous_score=previous_score,
                    current_score=current_score,
                    score_delta=score_delta,
                    previous_risk_level=previous_level_str,
                    current_risk_level=current_level_str,
                    trigger_reason=reason,
                    factor_id=current.primary_factor_id,
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    created_at=created_at,
                    metadata={"high_threshold": config.high_threshold},
                )
            )

        # 3. RISK_LEVEL_INCREASED (categorical transition upward)
        if (
            RiskAlertType.RISK_LEVEL_INCREASED in config.enabled_alert_types
            and previous_level_str is not None
            and RISK_LEVEL_RANKS.get(current_level_str, 0) > RISK_LEVEL_RANKS.get(previous_level_str, 0)
        ):
            alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.RISK_LEVEL_INCREASED.value)
            severity = (
                AlertSeverity.CRITICAL
                if current_level_str == RiskLevel.CRITICAL.value
                else AlertSeverity.WARNING
            )
            reason = f"Risk level escalated from {previous_level_str} to {current_level_str}."
            alerts.append(
                RiskAlert(
                    alert_id=alert_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                    scope=current.scope if hasattr(current, "scope") else None,
                    scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                    alert_type=RiskAlertType.RISK_LEVEL_INCREASED,
                    severity=severity,
                    previous_score=previous_score,
                    current_score=current_score,
                    score_delta=score_delta,
                    previous_risk_level=previous_level_str,
                    current_risk_level=current_level_str,
                    trigger_reason=reason,
                    factor_id=current.primary_factor_id,
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    created_at=created_at,
                    metadata={"previous_level": previous_level_str, "current_level": current_level_str},
                )
            )

        # 4. RISK_LEVEL_DECREASED (categorical transition downward)
        if (
            RiskAlertType.RISK_LEVEL_DECREASED in config.enabled_alert_types
            and previous_level_str is not None
            and RISK_LEVEL_RANKS.get(current_level_str, 0) < RISK_LEVEL_RANKS.get(previous_level_str, 0)
        ):
            alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.RISK_LEVEL_DECREASED.value)
            reason = f"Risk level de-escalated from {previous_level_str} to {current_level_str}."
            alerts.append(
                RiskAlert(
                    alert_id=alert_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                    scope=current.scope if hasattr(current, "scope") else None,
                    scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                    alert_type=RiskAlertType.RISK_LEVEL_DECREASED,
                    severity=AlertSeverity.INFO,
                    previous_score=previous_score,
                    current_score=current_score,
                    score_delta=score_delta,
                    previous_risk_level=previous_level_str,
                    current_risk_level=current_level_str,
                    trigger_reason=reason,
                    factor_id=current.primary_factor_id,
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    created_at=created_at,
                    metadata={"previous_level": previous_level_str, "current_level": current_level_str},
                )
            )

        # 5. RISK_SCORE_INCREASED (material jump >= score_jump_threshold)
        if (
            RiskAlertType.RISK_SCORE_INCREASED in config.enabled_alert_types
            and score_delta is not None
            and score_delta >= config.score_jump_threshold
        ):
            alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.RISK_SCORE_INCREASED.value)
            severity = (
                AlertSeverity.CRITICAL
                if current_score >= config.critical_threshold
                else (
                    AlertSeverity.WARNING
                    if current_score >= config.high_threshold
                    else AlertSeverity.INFO
                )
            )
            reason = (
                f"Risk score materially increased by +{score_delta:.1f} points "
                f"(from {previous_score:.1f} to {current_score:.1f})."
            )
            alerts.append(
                RiskAlert(
                    alert_id=alert_id,
                    organization_id=org_id,
                    assessment_id=assessment_id,
                    risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                    scope=current.scope if hasattr(current, "scope") else None,
                    scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                    alert_type=RiskAlertType.RISK_SCORE_INCREASED,
                    severity=severity,
                    previous_score=previous_score,
                    current_score=current_score,
                    score_delta=score_delta,
                    previous_risk_level=previous_level_str,
                    current_risk_level=current_level_str,
                    trigger_reason=reason,
                    factor_id=current.primary_factor_id,
                    evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                    created_at=created_at,
                    metadata={"score_delta": score_delta, "threshold": config.score_jump_threshold},
                )
            )

        # 6. CRITICAL_FACTOR_DETECTED (any factor with severity == CRITICAL)
        if RiskAlertType.CRITICAL_FACTOR_DETECTED in config.enabled_alert_types:
            previous_critical_factor_ids = set()
            if previous:
                for pf in previous.factors:
                    if pf.severity == RiskLevel.CRITICAL:
                        previous_critical_factor_ids.add(pf.factor_id)

            for factor in current.factors:
                if factor.severity == RiskLevel.CRITICAL:
                    # Alert if newly critical or not in previous assessment
                    if factor.factor_id not in previous_critical_factor_ids:
                        alert_id = compute_alert_id(
                            org_id,
                            assessment_id,
                            RiskAlertType.CRITICAL_FACTOR_DETECTED.value,
                            entity_key=factor.factor_id,
                        )
                        contrib_str = f" with contribution {factor.contribution:.2f}" if factor.contribution is not None else ""
                        reason = f"Critical risk factor detected: {factor.name}{contrib_str}."
                        alerts.append(
                            RiskAlert(
                                alert_id=alert_id,
                                organization_id=org_id,
                                assessment_id=assessment_id,
                                risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                                scope=current.scope if hasattr(current, "scope") else None,
                                scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                                alert_type=RiskAlertType.CRITICAL_FACTOR_DETECTED,
                                severity=AlertSeverity.CRITICAL,
                                previous_score=previous_score,
                                current_score=current_score,
                                score_delta=score_delta,
                                previous_risk_level=previous_level_str,
                                current_risk_level=current_level_str,
                                trigger_reason=reason,
                                factor_id=factor.factor_id,
                                evidence_ids=factor.evidence_ids[:5],
                                created_at=created_at,
                                metadata={
                                    "factor_name": factor.name,
                                    "factor_type": factor.factor_type,
                                    "contribution": factor.contribution,
                                },
                            )
                        )

        # If previous assessment exists, run comparison-based alert rules
        if previous:
            curr_dict = _assessment_to_dict(current)
            prev_dict = _assessment_to_dict(previous)
            comparison = HistoricalRiskComparator.compare(current=curr_dict, previous=prev_dict)

            # 7. RISK_TREND_INCREASING (direction == INCREASING and score >= 60.0)
            if (
                RiskAlertType.RISK_TREND_INCREASING in config.enabled_alert_types
                and comparison.direction == RiskTrend.INCREASING
                and current_score >= config.increasing_trend_min_score
            ):
                alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.RISK_TREND_INCREASING.value)
                severity = (
                    AlertSeverity.CRITICAL
                    if current_score >= config.critical_threshold
                    else AlertSeverity.WARNING
                )
                reason = f"Risk trajectory is INCREASING with elevated risk score ({current_score:.1f})."
                alerts.append(
                    RiskAlert(
                        alert_id=alert_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                        scope=current.scope if hasattr(current, "scope") else None,
                        scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                        alert_type=RiskAlertType.RISK_TREND_INCREASING,
                        severity=severity,
                        previous_score=previous_score,
                        current_score=current_score,
                        score_delta=score_delta,
                        previous_risk_level=previous_level_str,
                        current_risk_level=current_level_str,
                        trigger_reason=reason,
                        factor_id=current.primary_factor_id,
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        created_at=created_at,
                        metadata={"trend": comparison.direction.value},
                    )
                )

            # 8. PRIMARY_DRIVER_CHANGED (driver changed and score >= 30.0)
            if (
                RiskAlertType.PRIMARY_DRIVER_CHANGED in config.enabled_alert_types
                and comparison.primary_driver_change_status == DriverChangeStatus.CHANGED
                and current_score >= config.driver_change_min_score
            ):
                alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.PRIMARY_DRIVER_CHANGED.value)
                prev_dname = (
                    comparison.previous_primary_driver.get("name", "UNKNOWN")
                    if comparison.previous_primary_driver
                    else "NONE"
                )
                curr_dname = (
                    comparison.current_primary_driver.get("name", "UNKNOWN")
                    if comparison.current_primary_driver
                    else "NONE"
                )
                severity = (
                    AlertSeverity.WARNING
                    if current_score >= config.high_threshold
                    else AlertSeverity.INFO
                )
                reason = f"Primary risk driver changed from {prev_dname} to {curr_dname}."
                alerts.append(
                    RiskAlert(
                        alert_id=alert_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                        scope=current.scope if hasattr(current, "scope") else None,
                        scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                        alert_type=RiskAlertType.PRIMARY_DRIVER_CHANGED,
                        severity=severity,
                        previous_score=previous_score,
                        current_score=current_score,
                        score_delta=score_delta,
                        previous_risk_level=previous_level_str,
                        current_risk_level=current_level_str,
                        trigger_reason=reason,
                        factor_id=current.primary_factor_id,
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        created_at=created_at,
                        metadata={"previous_driver": prev_dname, "current_driver": curr_dname},
                    )
                )

            # 9. NEW_CONFLICT (conflict appeared in comparison)
            if (
                RiskAlertType.NEW_CONFLICT in config.enabled_alert_types
                and comparison.conflict_changes.status == ConflictChangeStatus.NEW_CONFLICT
            ):
                alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.NEW_CONFLICT.value)
                conflict_count = len(current.conflicts)
                reason = f"New source conflict detected in risk assessment ({conflict_count} conflict(s) present)."
                alerts.append(
                    RiskAlert(
                        alert_id=alert_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                        scope=current.scope if hasattr(current, "scope") else None,
                        scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                        alert_type=RiskAlertType.NEW_CONFLICT,
                        severity=AlertSeverity.WARNING,
                        previous_score=previous_score,
                        current_score=current_score,
                        score_delta=score_delta,
                        previous_risk_level=previous_level_str,
                        current_risk_level=current_level_str,
                        trigger_reason=reason,
                        factor_id=current.primary_factor_id,
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        created_at=created_at,
                        metadata={"conflict_count": conflict_count},
                    )
                )

            # 10. QUALITY_DEGRADED (quality status == DEGRADED)
            if (
                RiskAlertType.QUALITY_DEGRADED in config.enabled_alert_types
                and comparison.quality_changes.status == QualityChangeStatus.DEGRADED
            ):
                alert_id = compute_alert_id(org_id, assessment_id, RiskAlertType.QUALITY_DEGRADED.value)
                reason = "Evidence quality degraded compared to previous evaluation."
                alerts.append(
                    RiskAlert(
                        alert_id=alert_id,
                        organization_id=org_id,
                        assessment_id=assessment_id,
                        risk_id=current.risk_id if hasattr(current, "risk_id") else None,
                        scope=current.scope if hasattr(current, "scope") else None,
                        scope_entity_id=current.scope_entity_id if hasattr(current, "scope_entity_id") else None,
                        alert_type=RiskAlertType.QUALITY_DEGRADED,
                        severity=AlertSeverity.WARNING,
                        previous_score=previous_score,
                        current_score=current_score,
                        score_delta=score_delta,
                        previous_risk_level=previous_level_str,
                        current_risk_level=current_level_str,
                        trigger_reason=reason,
                        factor_id=current.primary_factor_id,
                        evidence_ids=[e.evidence_id for e in current.evidence[:5]],
                        created_at=created_at,
                        metadata={"limitations": current.limitations},
                    )
                )

        return alerts


class RiskAlertNotificationAdapter:
    """Bridges domain RiskAlert objects with existing PostgreSQL Notification records."""

    @classmethod
    def to_notification_model(
        cls,
        alert: RiskAlert,
        user_id: Optional[str] = None,
    ) -> Notification:
        """Convert a domain RiskAlert into an ORM Notification instance.

        Stores deterministic alert_id as the primary key.
        Category is strictly 'RISK_ALERT'.
        Severity maps to NotificationSeverity ('INFO', 'WARNING', 'CRITICAL').
        Title and summary contain structured, secret-scrubbed context.
        """
        # Map alert severity to notification severity
        notif_severity = alert.severity.value

        # Build clean title: [ALERT_TYPE] Trigger reason
        title = f"[{alert.alert_type.value}] {alert.trigger_reason}"
        if len(title) > 255:
            title = title[:252] + "..."

        # Build structured summary payload for frontends and audit consumers
        summary_payload = {
            "alert_id": alert.alert_id,
            "alert_type": alert.alert_type.value,
            "assessment_id": alert.assessment_id,
            "risk_id": alert.risk_id,
            "current_score": alert.current_score,
            "score_delta": alert.score_delta,
            "current_risk_level": alert.current_risk_level,
            "previous_risk_level": alert.previous_risk_level,
            "factor_id": alert.factor_id,
            "evidence_ids": alert.evidence_ids,
            "trigger_reason": alert.trigger_reason,
            "metadata": alert.metadata,
        }
        summary_str = json.dumps(summary_payload, default=str)
        if len(summary_str) > 1000:
            # Truncate metadata if necessary to fit within String(1000)
            summary_payload["metadata"] = {}
            summary_str = json.dumps(summary_payload, default=str)
            if len(summary_str) > 1000:
                summary_str = summary_str[:997] + "..."

        return Notification(
            id=alert.alert_id,
            org_id=alert.organization_id,
            user_id=user_id,
            category="RISK_ALERT",
            severity=notif_severity,
            title=title,
            summary=summary_str,
            is_read=(alert.status in (AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED)),
            created_at=alert.created_at,
        )

    @classmethod
    def from_notification_model(cls, notif: Notification) -> RiskAlert:
        """Reconstruct a domain RiskAlert from an ORM Notification instance."""
        alert_type = RiskAlertType.HIGH_RISK_REACHED
        assessment_id = ""
        risk_id = None
        current_score = 0.0
        score_delta = None
        current_risk_level = None
        previous_risk_level = None
        factor_id = None
        evidence_ids = []
        trigger_reason = notif.title
        metadata = {}

        # Parse JSON summary if available
        if notif.summary:
            try:
                data = json.loads(notif.summary)
                if isinstance(data, dict):
                    if "alert_type" in data:
                        try:
                            alert_type = RiskAlertType(data["alert_type"])
                        except ValueError:
                            pass
                    assessment_id = data.get("assessment_id", "")
                    risk_id = data.get("risk_id")
                    current_score = float(data.get("current_score", 0.0))
                    score_delta = float(data["score_delta"]) if data.get("score_delta") is not None else None
                    current_risk_level = data.get("current_risk_level")
                    previous_risk_level = data.get("previous_risk_level")
                    factor_id = data.get("factor_id")
                    evidence_ids = data.get("evidence_ids", [])
                    trigger_reason = data.get("trigger_reason", notif.title)
                    metadata = data.get("metadata", {})
            except Exception:
                # Fallback: extract alert type from title prefix
                match = re.match(r"^\[([A-Z_]+)\]\s*(.*)", notif.title)
                if match:
                    try:
                        alert_type = RiskAlertType(match.group(1))
                        trigger_reason = match.group(2)
                    except ValueError:
                        pass

        # Severity mapping
        try:
            severity = AlertSeverity(notif.severity)
        except ValueError:
            severity = AlertSeverity.WARNING if notif.severity == "WARNING" else (
                AlertSeverity.CRITICAL if notif.severity == "CRITICAL" else AlertSeverity.INFO
            )

        status = AlertStatus.ACKNOWLEDGED if notif.is_read else AlertStatus.OPEN

        return RiskAlert(
            alert_id=notif.id,
            organization_id=notif.org_id or "",
            assessment_id=assessment_id,
            risk_id=risk_id,
            alert_type=alert_type,
            severity=severity,
            current_score=current_score,
            score_delta=score_delta,
            previous_risk_level=previous_risk_level,
            current_risk_level=current_risk_level,
            trigger_reason=trigger_reason,
            factor_id=factor_id,
            evidence_ids=evidence_ids,
            status=status,
            created_at=notif.created_at or datetime.now(timezone.utc),
            metadata=metadata,
        )
