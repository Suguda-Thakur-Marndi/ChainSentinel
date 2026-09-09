"""Historical assessment analysis, deterministic comparisons, and trend evaluation for Phase 7 Step 5.

Provides pure domain models and algorithms to compare consecutive or arbitrary
persisted RiskAssessment records without machine learning or non-deterministic inference.
"""

from __future__ import annotations

import copy
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.risk_engine.contract import RiskAssessment, RiskFactor, RiskLevel
from app.risk_engine.persistence import scrub_secrets


class RiskTrend(str, Enum):
    """Directional trend classification of risk score trajectory."""

    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class FactorChangeStatus(str, Enum):
    """Change status for individual risk factors between assessments."""

    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"


class ConflictChangeStatus(str, Enum):
    """Status of contradictory evidence/conflict transitions between evaluations."""

    NO_CHANGE = "NO_CHANGE"
    NEW_CONFLICT = "NEW_CONFLICT"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
    CONFLICT_CHANGED = "CONFLICT_CHANGED"


class QualityChangeStatus(str, Enum):
    """Status of evidence quality transitions."""

    IMPROVED = "IMPROVED"
    DEGRADED = "DEGRADED"
    UNCHANGED = "UNCHANGED"


class DriverChangeStatus(str, Enum):
    """Categorical status of primary driver changes."""

    SAME = "SAME"
    CHANGED = "CHANGED"
    NEW = "NEW"
    NONE = "NONE"


class FactorChange(BaseModel):
    """Deterministic comparison for a single risk factor across assessments."""

    model_config = ConfigDict(extra="forbid")

    factor_id: str = Field(..., description="Unique factor identifier.")
    factor_type: str = Field(..., description="Domain factor type.")
    name: str = Field(..., description="Human-readable factor name.")
    previous_severity: Optional[str] = Field(None, description="Previous severity level.")
    current_severity: Optional[str] = Field(None, description="Current severity level.")
    severity_changed: bool = Field(False, description="True if severity level shifted.")
    previous_confidence: Optional[float] = Field(None, description="Previous confidence [0.0, 1.0].")
    current_confidence: Optional[float] = Field(None, description="Current confidence [0.0, 1.0].")
    confidence_delta: float = Field(0.0, description="Difference in confidence.")
    previous_contribution: Optional[float] = Field(None, description="Previous contribution points.")
    current_contribution: Optional[float] = Field(None, description="Current contribution points.")
    contribution_delta: float = Field(0.0, description="Delta in contribution points.")
    status: FactorChangeStatus = Field(FactorChangeStatus.UNCHANGED, description="Factor change status.")


class EvidenceChanges(BaseModel):
    """Summary of evidence item and source quantity transitions."""

    model_config = ConfigDict(extra="forbid")

    previous_evidence_count: int = Field(0, ge=0)
    current_evidence_count: int = Field(0, ge=0)
    evidence_count_delta: int = Field(0)
    previous_source_count: int = Field(0, ge=0)
    current_source_count: int = Field(0, ge=0)
    source_count_delta: int = Field(0)
    previous_corroborating_count: int = Field(0, ge=0)
    current_corroborating_count: int = Field(0, ge=0)
    corroborating_count_delta: int = Field(0)
    details: List[str] = Field(default_factory=list, description="Descriptive points.")


class SourceChanges(BaseModel):
    """Breakdown of changes in data provider observation types and providers."""

    model_config = ConfigDict(extra="forbid")

    previous_independent_sources: int = Field(0, ge=0)
    current_independent_sources: int = Field(0, ge=0)
    independent_sources_delta: int = Field(0)
    previous_real_sources: int = Field(0, ge=0)
    current_real_sources: int = Field(0, ge=0)
    real_sources_delta: int = Field(0)
    previous_estimated_sources: int = Field(0, ge=0)
    current_estimated_sources: int = Field(0, ge=0)
    estimated_sources_delta: int = Field(0)
    previous_simulated_sources: int = Field(0, ge=0)
    current_simulated_sources: int = Field(0, ge=0)
    simulated_sources_delta: int = Field(0)
    added_providers: List[str] = Field(default_factory=list)
    removed_providers: List[str] = Field(default_factory=list)


class ConflictChanges(BaseModel):
    """Summary of conflict appearance, resolution, or count shifts."""

    model_config = ConfigDict(extra="forbid")

    status: ConflictChangeStatus = Field(ConflictChangeStatus.NO_CHANGE)
    previous_conflict_count: int = Field(0, ge=0)
    current_conflict_count: int = Field(0, ge=0)
    conflict_count_delta: int = Field(0)
    details: List[str] = Field(default_factory=list)


class QualityChanges(BaseModel):
    """Summary of data quality shifts and introduced or resolved limitations."""

    model_config = ConfigDict(extra="forbid")

    status: QualityChangeStatus = Field(QualityChangeStatus.UNCHANGED)
    previous_valid_count: int = Field(0, ge=0)
    current_valid_count: int = Field(0, ge=0)
    previous_partial_count: int = Field(0, ge=0)
    current_partial_count: int = Field(0, ge=0)
    new_limitations: List[str] = Field(default_factory=list)
    resolved_limitations: List[str] = Field(default_factory=list)


class AssessmentComparison(BaseModel):
    """Comprehensive comparison between two specific RiskAssessment points in time."""

    model_config = ConfigDict(extra="forbid")

    previous_assessment_id: Optional[str] = Field(None, description="Prior assessment ID.")
    current_assessment_id: str = Field(..., description="Target assessment ID.")
    previous_evaluated_at: Optional[datetime] = Field(None, description="Prior evaluation timestamp.")
    current_evaluated_at: datetime = Field(..., description="Target evaluation timestamp.")
    previous_score: Optional[float] = Field(None, description="Prior risk score [0.0, 100.0].")
    current_score: float = Field(..., description="Target risk score [0.0, 100.0].")
    score_delta: float = Field(0.0, description="Exact arithmetic difference (current - previous).")
    previous_risk_level: Optional[str] = Field(None, description="Prior Platform severity.")
    current_risk_level: str = Field(..., description="Target Platform severity.")
    risk_level_changed: bool = Field(False, description="True if risk level changed.")
    previous_primary_factor_id: Optional[str] = Field(None, description="Prior primary driver factor ID.")
    current_primary_factor_id: Optional[str] = Field(None, description="Current primary driver factor ID.")
    primary_driver_change_status: DriverChangeStatus = Field(DriverChangeStatus.SAME)
    previous_primary_driver: Optional[Dict[str, Any]] = Field(None, description="Prior primary driver details.")
    current_primary_driver: Optional[Dict[str, Any]] = Field(None, description="Current primary driver details.")
    direction: RiskTrend = Field(RiskTrend.STABLE, description="Trend classification.")
    factor_changes: List[FactorChange] = Field(default_factory=list, description="Per-factor deltas.")
    evidence_changes: EvidenceChanges = Field(default_factory=EvidenceChanges)
    source_changes: SourceChanges = Field(default_factory=SourceChanges)
    conflict_changes: ConflictChanges = Field(default_factory=ConflictChanges)
    quality_changes: QualityChanges = Field(default_factory=QualityChanges)
    explanation: str = Field("", description="Deterministic rule-based explanation of transitions.")


class RiskHistorySummary(BaseModel):
    """Descriptive historical risk summary across an entity or scope timeline."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(..., description="Authoritative tenant organization ID.")
    entity_scope: Optional[str] = Field("GLOBAL", description="Scope of evaluation (GLOBAL, SHIPMENT, etc.).")
    entity_id: Optional[str] = Field(None, description="Target entity ID.")
    assessment_count: int = Field(0, ge=0, description="Total assessments in history period.")
    first_assessment_id: Optional[str] = Field(None, description="Oldest assessment ID.")
    latest_assessment_id: Optional[str] = Field(None, description="Most recent assessment ID.")
    first_score: Optional[float] = Field(None, description="Score of oldest assessment.")
    latest_score: Optional[float] = Field(None, description="Score of most recent assessment.")
    score_delta: Optional[float] = Field(None, description="Delta between first and latest.")
    minimum_score: Optional[float] = Field(None, description="Minimum score observed.")
    maximum_score: Optional[float] = Field(None, description="Maximum score observed.")
    average_score: Optional[float] = Field(None, description="Exact mean score observed.")
    first_risk_level: Optional[str] = Field(None, description="Risk level of oldest assessment.")
    latest_risk_level: Optional[str] = Field(None, description="Risk level of most recent assessment.")
    trend: RiskTrend = Field(RiskTrend.INSUFFICIENT_HISTORY, description="Overall timeline trend.")
    primary_driver: Optional[Dict[str, Any]] = Field(None, description="Latest primary driver.")
    driver_changes_count: int = Field(0, ge=0, description="Count of primary driver transitions.")
    conflict_count: int = Field(0, ge=0, description="Count of active conflicts in latest assessment.")
    source_summary: Optional[Dict[str, Any]] = Field(None, description="Latest source summary.")
    history_start: Optional[datetime] = Field(None, description="Oldest evaluation timestamp.")
    history_end: Optional[datetime] = Field(None, description="Newest evaluation timestamp.")
    assessments: List[Dict[str, Any]] = Field(default_factory=list, description="Ordered assessment timeline.")
    transitions: List[AssessmentComparison] = Field(default_factory=list, description="Pairwise transitions.")
    overall_comparison: Optional[AssessmentComparison] = Field(None, description="First vs Latest comparison.")


class HistoricalRiskComparator:
    """Deterministic comparator calculating score deltas, transitions, and factor changes."""

    @classmethod
    def classify_trend(cls, score_delta: float) -> RiskTrend:
        """Classify directional trend based on exact score delta.

        delta > 0  -> INCREASING
        delta < 0  -> DECREASING
        delta == 0 -> STABLE
        """
        rounded = round(float(score_delta), 2)
        if rounded > 0.0:
            return RiskTrend.INCREASING
        elif rounded < 0.0:
            return RiskTrend.DECREASING
        else:
            return RiskTrend.STABLE

    @classmethod
    def compare(
        cls,
        current: Union[RiskAssessment, Dict[str, Any]],
        previous: Optional[Union[RiskAssessment, Dict[str, Any]]] = None,
    ) -> AssessmentComparison:
        """Compare two assessment representations deterministically.

        `current` and `previous` may be flat detail dictionaries, findings envelopes, or RiskAssessment domain models.
        """
        def _to_dict(item: Any) -> Dict[str, Any]:
            if hasattr(item, "model_dump"):
                d = item.model_dump()
                if hasattr(item, "score") and item.score is not None:
                    d["score"] = item.score
                if hasattr(item, "risk_level") and item.risk_level is not None:
                    d["risk_level"] = item.risk_level.value if hasattr(item.risk_level, "value") else str(item.risk_level)
                return d
            return dict(item) if isinstance(item, dict) else {}

        current = _to_dict(current)
        if previous is not None:
            previous = _to_dict(previous)

        curr_id = current.get("assessment_id") or current.get("id") or "unknown"
        curr_score = float(current.get("score") if current.get("score") is not None else 0.0)
        curr_level = current.get("risk_level") or "UNKNOWN"
        curr_time = current.get("created_at") or current.get("evaluated_at") or datetime.now()
        if isinstance(curr_time, str):
            try:
                curr_time = datetime.fromisoformat(curr_time)
            except Exception:
                curr_time = datetime.now()

        curr_driver = current.get("primary_driver")
        curr_driver_id = current.get("primary_factor_id") or (curr_driver.get("factor_id") or curr_driver.get("name") if curr_driver else None)

        if not previous:
            # Single assessment comparison baseline
            return AssessmentComparison(
                previous_assessment_id=None,
                current_assessment_id=curr_id,
                previous_evaluated_at=None,
                current_evaluated_at=curr_time,
                previous_score=None,
                current_score=curr_score,
                score_delta=0.0,
                previous_risk_level=None,
                current_risk_level=curr_level,
                risk_level_changed=False,
                previous_primary_factor_id=None,
                current_primary_factor_id=curr_driver_id,
                primary_driver_change_status=DriverChangeStatus.NONE if not curr_driver_id else DriverChangeStatus.NEW,
                previous_primary_driver=None,
                current_primary_driver=curr_driver,
                direction=RiskTrend.INSUFFICIENT_HISTORY,
                explanation=f"Initial evaluation established risk score of {curr_score:.1f} ({curr_level}).",
            )

        prev_id = previous.get("assessment_id") or previous.get("id") or "unknown"
        prev_score = float(previous.get("score") if previous.get("score") is not None else 0.0)
        prev_level = previous.get("risk_level") or "UNKNOWN"
        prev_time = previous.get("created_at") or previous.get("evaluated_at") or curr_time
        if isinstance(prev_time, str):
            try:
                prev_time = datetime.fromisoformat(prev_time)
            except Exception:
                prev_time = curr_time

        prev_driver = previous.get("primary_driver")
        prev_driver_id = previous.get("primary_factor_id") or (prev_driver.get("factor_id") or prev_driver.get("name") if prev_driver else None)

        # 1. Score delta & trend direction
        score_delta = round(curr_score - prev_score, 2)
        direction = cls.classify_trend(score_delta)

        # 2. Risk level transition
        level_changed = prev_level.upper() != curr_level.upper()

        # 3. Primary driver changes
        if not prev_driver_id and not curr_driver_id:
            driver_status = DriverChangeStatus.SAME
        elif not prev_driver_id and curr_driver_id:
            driver_status = DriverChangeStatus.NEW
        elif prev_driver_id and not curr_driver_id:
            driver_status = DriverChangeStatus.CHANGED
        elif prev_driver_id == curr_driver_id:
            driver_status = DriverChangeStatus.SAME
        else:
            driver_status = DriverChangeStatus.CHANGED

        # 4. Factor changes
        factor_changes = cls._compare_factors(previous, current)

        # 5. Evidence changes
        evidence_changes = cls._compare_evidence(previous, current)

        # 6. Source changes
        source_changes = cls._compare_sources(previous, current)

        # 7. Conflict changes
        conflict_changes = cls._compare_conflicts(previous, current)

        # 8. Quality changes
        quality_changes = cls._compare_quality(previous, current)

        # 9. Deterministic rule-based explanation
        explanation = cls._generate_explanation(
            prev_score=prev_score,
            curr_score=curr_score,
            score_delta=score_delta,
            prev_level=prev_level,
            curr_level=curr_level,
            level_changed=level_changed,
            driver_status=driver_status,
            prev_driver=prev_driver,
            curr_driver=curr_driver,
            evidence_changes=evidence_changes,
            conflict_changes=conflict_changes,
            factor_changes=factor_changes,
        )

        return AssessmentComparison(
            previous_assessment_id=prev_id,
            current_assessment_id=curr_id,
            previous_evaluated_at=prev_time,
            current_evaluated_at=curr_time,
            previous_score=prev_score,
            current_score=curr_score,
            score_delta=score_delta,
            previous_risk_level=prev_level,
            current_risk_level=curr_level,
            risk_level_changed=level_changed,
            previous_primary_factor_id=prev_driver_id,
            current_primary_factor_id=curr_driver_id,
            primary_driver_change_status=driver_status,
            previous_primary_driver=prev_driver,
            current_primary_driver=curr_driver,
            direction=direction,
            factor_changes=factor_changes,
            evidence_changes=evidence_changes,
            source_changes=source_changes,
            conflict_changes=conflict_changes,
            quality_changes=quality_changes,
            explanation=explanation,
        )

    @classmethod
    def _compare_factors(
        cls,
        prev: Dict[str, Any],
        curr: Dict[str, Any],
    ) -> List[FactorChange]:
        """Compare factors deterministically by factor_type or factor_id."""
        prev_factors = prev.get("factors") or []
        curr_factors = curr.get("factors") or []

        prev_contribs = {fc.get("factor_id"): fc for fc in (prev.get("factor_contributions") or [])}
        curr_contribs = {fc.get("factor_id"): fc for fc in (curr.get("factor_contributions") or [])}

        # Index factors by key: prefer factor_type, fallback to factor_id
        def _get_key(f: Dict[str, Any]) -> str:
            return f.get("factor_type") or f.get("category") or f.get("id") or f.get("factor_id") or ""

        prev_map = {_get_key(f): f for f in prev_factors if _get_key(f)}
        curr_map = {_get_key(f): f for f in curr_factors if _get_key(f)}

        all_keys = sorted(set(prev_map.keys()) | set(curr_map.keys()))
        changes: List[FactorChange] = []

        for key in all_keys:
            p = prev_map.get(key)
            c = curr_map.get(key)

            if p and not c:
                p_id = p.get("factor_id") or p.get("id") or key
                p_contrib = prev_contribs.get(p_id, {}).get("weighted_contribution", p.get("score") or p.get("contribution") or 0.0)
                changes.append(
                    FactorChange(
                        factor_id=p_id,
                        factor_type=p.get("factor_type") or p.get("category") or key,
                        name=p.get("name") or key,
                        previous_severity=p.get("severity"),
                        current_severity=None,
                        severity_changed=True,
                        previous_confidence=p.get("confidence"),
                        current_confidence=None,
                        confidence_delta=round(0.0 - float(p.get("confidence") or 1.0), 4),
                        previous_contribution=round(float(p_contrib), 2),
                        current_contribution=None,
                        contribution_delta=round(-float(p_contrib), 2),
                        status=FactorChangeStatus.REMOVED,
                    )
                )
            elif c and not p:
                c_id = c.get("factor_id") or c.get("id") or key
                c_contrib = curr_contribs.get(c_id, {}).get("weighted_contribution", c.get("score") or c.get("contribution") or 0.0)
                changes.append(
                    FactorChange(
                        factor_id=c_id,
                        factor_type=c.get("factor_type") or c.get("category") or key,
                        name=c.get("name") or key,
                        previous_severity=None,
                        current_severity=c.get("severity"),
                        severity_changed=True,
                        previous_confidence=None,
                        current_confidence=c.get("confidence"),
                        confidence_delta=round(float(c.get("confidence") or 1.0), 4),
                        previous_contribution=None,
                        current_contribution=round(float(c_contrib), 2),
                        contribution_delta=round(float(c_contrib), 2),
                        status=FactorChangeStatus.ADDED,
                    )
                )
            else:
                assert p is not None and c is not None
                p_id = p.get("factor_id") or p.get("id") or key
                c_id = c.get("factor_id") or c.get("id") or key

                p_contrib = prev_contribs.get(p_id, {}).get("weighted_contribution", p.get("score") or p.get("contribution") or 0.0)
                c_contrib = curr_contribs.get(c_id, {}).get("weighted_contribution", c.get("score") or c.get("contribution") or 0.0)

                p_sev = str(p.get("severity") or "")
                c_sev = str(c.get("severity") or "")
                sev_changed = p_sev.upper() != c_sev.upper()

                p_conf = float(p.get("confidence") or 1.0)
                c_conf = float(c.get("confidence") or 1.0)
                conf_delta = round(c_conf - p_conf, 4)
                contrib_delta = round(float(c_contrib) - float(p_contrib), 2)

                is_changed = sev_changed or abs(conf_delta) > 0.001 or abs(contrib_delta) > 0.01

                changes.append(
                    FactorChange(
                        factor_id=c_id,
                        factor_type=c.get("factor_type") or c.get("category") or key,
                        name=c.get("name") or key,
                        previous_severity=p_sev or None,
                        current_severity=c_sev or None,
                        severity_changed=sev_changed,
                        previous_confidence=p_conf,
                        current_confidence=c_conf,
                        confidence_delta=conf_delta,
                        previous_contribution=round(float(p_contrib), 2),
                        current_contribution=round(float(c_contrib), 2),
                        contribution_delta=contrib_delta,
                        status=FactorChangeStatus.CHANGED if is_changed else FactorChangeStatus.UNCHANGED,
                    )
                )

        return changes

    @classmethod
    def _compare_evidence(
        cls,
        prev: Dict[str, Any],
        curr: Dict[str, Any],
    ) -> EvidenceChanges:
        """Compare evidence counts and corroborated signal observations."""
        prev_ev = prev.get("evidence") or []
        curr_ev = curr.get("evidence") or []

        prev_sources = {e.get("source") or e.get("provider") for e in prev_ev if e.get("source") or e.get("provider")}
        curr_sources = {e.get("source") or e.get("provider") for e in curr_ev if e.get("source") or e.get("provider")}

        prev_src_summary = prev.get("source_summary") or {}
        curr_src_summary = curr.get("source_summary") or {}

        prev_corrob = prev_src_summary.get("corroborating_sources_count", 0)
        curr_corrob = curr_src_summary.get("corroborating_sources_count", 0)

        ev_delta = len(curr_ev) - len(prev_ev)
        src_delta = len(curr_sources) - len(prev_sources)
        corrob_delta = curr_corrob - prev_corrob

        details = []
        if ev_delta > 0:
            details.append(f"Evidence observations increased from {len(prev_ev)} to {len(curr_ev)} (+{ev_delta}).")
        elif ev_delta < 0:
            details.append(f"Evidence observations decreased from {len(prev_ev)} to {len(curr_ev)} ({ev_delta}).")

        if src_delta > 0:
            details.append(f"Active data sources increased from {len(prev_sources)} to {len(curr_sources)}.")
        elif src_delta < 0:
            details.append(f"Active data sources decreased from {len(prev_sources)} to {len(curr_sources)}.")

        return EvidenceChanges(
            previous_evidence_count=len(prev_ev),
            current_evidence_count=len(curr_ev),
            evidence_count_delta=ev_delta,
            previous_source_count=len(prev_sources),
            current_source_count=len(curr_sources),
            source_count_delta=src_delta,
            previous_corroborating_count=prev_corrob,
            current_corroborating_count=curr_corrob,
            corroborating_count_delta=corrob_delta,
            details=details,
        )

    @classmethod
    def _compare_sources(
        cls,
        prev: Dict[str, Any],
        curr: Dict[str, Any],
    ) -> SourceChanges:
        """Compare independent, real, estimated, and simulated source summaries."""
        ps = prev.get("source_summary") or {}
        cs = curr.get("source_summary") or {}

        p_indep = ps.get("independent_sources_count", 0)
        c_indep = cs.get("independent_sources_count", 0)
        p_real = ps.get("real_sources_count", 0)
        c_real = cs.get("real_sources_count", 0)
        p_est = ps.get("estimated_sources_count", 0)
        c_est = cs.get("estimated_sources_count", 0)
        p_sim = ps.get("simulated_sources_count", 0)
        c_sim = cs.get("simulated_sources_count", 0)

        p_prov = set(ps.get("providers") or [])
        c_prov = set(cs.get("providers") or [])

        return SourceChanges(
            previous_independent_sources=p_indep,
            current_independent_sources=c_indep,
            independent_sources_delta=c_indep - p_indep,
            previous_real_sources=p_real,
            current_real_sources=c_real,
            real_sources_delta=c_real - p_real,
            previous_estimated_sources=p_est,
            current_estimated_sources=c_est,
            estimated_sources_delta=c_est - p_est,
            previous_simulated_sources=p_sim,
            current_simulated_sources=c_sim,
            simulated_sources_delta=c_sim - p_sim,
            added_providers=sorted(c_prov - p_prov),
            removed_providers=sorted(p_prov - c_prov),
        )

    @classmethod
    def _compare_conflicts(
        cls,
        prev: Dict[str, Any],
        curr: Dict[str, Any],
    ) -> ConflictChanges:
        """Compare conflicting observations and multi-source discrepancies."""
        p_conflicts = prev.get("conflicts") or []
        c_conflicts = curr.get("conflicts") or []

        p_cnt = len(p_conflicts)
        c_cnt = len(c_conflicts)
        delta = c_cnt - p_cnt

        if p_cnt == 0 and c_cnt > 0:
            status = ConflictChangeStatus.NEW_CONFLICT
            details = [f"New source conflict introduced ({c_cnt} active conflict(s))."]
        elif p_cnt > 0 and c_cnt == 0:
            status = ConflictChangeStatus.CONFLICT_RESOLVED
            details = [f"Prior source conflicts resolved (was {p_cnt})."]
        elif p_cnt != c_cnt:
            status = ConflictChangeStatus.CONFLICT_CHANGED
            details = [f"Source conflict count shifted from {p_cnt} to {c_cnt}."]
        else:
            status = ConflictChangeStatus.NO_CHANGE
            details = []

        return ConflictChanges(
            status=status,
            previous_conflict_count=p_cnt,
            current_conflict_count=c_cnt,
            conflict_count_delta=delta,
            details=details,
        )

    @classmethod
    def _compare_quality(
        cls,
        prev: Dict[str, Any],
        curr: Dict[str, Any],
    ) -> QualityChanges:
        """Compare evidence quality (VALID vs PARTIAL vs INVALID) and limitations."""
        p_ev = prev.get("evidence") or []
        c_ev = curr.get("evidence") or []

        p_valid = sum(1 for e in p_ev if str(e.get("quality")).upper().endswith("VALID"))
        c_valid = sum(1 for e in c_ev if str(e.get("quality")).upper().endswith("VALID"))
        p_partial = sum(1 for e in p_ev if "PARTIAL" in str(e.get("quality")).upper())
        c_partial = sum(1 for e in c_ev if "PARTIAL" in str(e.get("quality")).upper())

        p_lims = set(prev.get("limitations") or [])
        c_lims = set(curr.get("limitations") or [])

        new_lims = sorted(c_lims - p_lims)
        resolved_lims = sorted(p_lims - c_lims)

        if len(new_lims) > len(resolved_lims) or (c_partial > p_partial and c_valid <= p_valid):
            status = QualityChangeStatus.DEGRADED
        elif len(resolved_lims) > len(new_lims) or (c_valid > p_valid and c_partial <= p_partial):
            status = QualityChangeStatus.IMPROVED
        else:
            status = QualityChangeStatus.UNCHANGED

        return QualityChanges(
            status=status,
            previous_valid_count=p_valid,
            current_valid_count=c_valid,
            previous_partial_count=p_partial,
            current_partial_count=c_partial,
            new_limitations=new_lims,
            resolved_limitations=resolved_lims,
        )

    @classmethod
    def _generate_explanation(
        cls,
        prev_score: float,
        curr_score: float,
        score_delta: float,
        prev_level: str,
        curr_level: str,
        level_changed: bool,
        driver_status: DriverChangeStatus,
        prev_driver: Optional[Dict[str, Any]],
        curr_driver: Optional[Dict[str, Any]],
        evidence_changes: EvidenceChanges,
        conflict_changes: ConflictChanges,
        factor_changes: List[FactorChange],
    ) -> str:
        """Generate deterministic, purely factual rule-based explanation of transitions."""
        sentences: List[str] = []

        # 1. Score movement
        if score_delta > 0:
            sentences.append(f"Risk increased from {prev_score:.1f} to {curr_score:.1f} (+{score_delta:.1f}).")
        elif score_delta < 0:
            sentences.append(f"Risk decreased from {prev_score:.1f} to {curr_score:.1f} ({score_delta:.1f}).")
        else:
            sentences.append(f"Risk score remained stable at {curr_score:.1f}.")

        # 2. Level shift
        if level_changed:
            sentences.append(f"Risk level transitioned from {prev_level} to {curr_level}.")

        # 3. Primary driver
        if driver_status == DriverChangeStatus.CHANGED and prev_driver and curr_driver:
            p_name = prev_driver.get("name") or prev_driver.get("factor_type") or "prior factor"
            c_name = curr_driver.get("name") or curr_driver.get("factor_type") or "new factor"
            sentences.append(f"Primary risk driver shifted from {p_name} to {c_name}.")
        elif driver_status == DriverChangeStatus.NEW and curr_driver:
            c_name = curr_driver.get("name") or curr_driver.get("factor_type") or "factor"
            sentences.append(f"New primary risk driver established: {c_name}.")

        # 4. Factor movements
        added_factors = [fc.name for fc in factor_changes if fc.status == FactorChangeStatus.ADDED]
        removed_factors = [fc.name for fc in factor_changes if fc.status == FactorChangeStatus.REMOVED]
        if added_factors:
            sentences.append(f"New risk factor(s) identified: {', '.join(added_factors[:3])}.")
        if removed_factors:
            sentences.append(f"Risk factor(s) cleared: {', '.join(removed_factors[:3])}.")

        # 5. Conflicts
        if conflict_changes.status == ConflictChangeStatus.NEW_CONFLICT:
            sentences.append(f"A source conflict was introduced across data providers.")
        elif conflict_changes.status == ConflictChangeStatus.CONFLICT_RESOLVED:
            sentences.append("Active source conflicts were resolved.")

        # 6. Evidence delta
        if evidence_changes.evidence_count_delta != 0:
            direction = "increased" if evidence_changes.evidence_count_delta > 0 else "decreased"
            sentences.append(
                f"Evidence observations {direction} from {evidence_changes.previous_evidence_count} to {evidence_changes.current_evidence_count}."
            )

        return " ".join(sentences)

    @classmethod
    def summarize_history(
        cls,
        org_id: str,
        assessments: List[Dict[str, Any]],
        entity_scope: Optional[str] = "GLOBAL",
        entity_id: Optional[str] = None,
    ) -> RiskHistorySummary:
        """Construct an aggregated RiskHistorySummary over a sequence of assessment records.

        Assessments must be sorted in ascending chronological order: `(created_at ASC, id ASC)`.
        """
        scope_val = entity_scope or "GLOBAL"
        if not assessments:
            return RiskHistorySummary(
                organization_id=org_id,
                entity_scope=scope_val,
                entity_id=entity_id,
                assessment_count=0,
                trend=RiskTrend.INSUFFICIENT_HISTORY,
            )

        first_asmt = assessments[0]
        latest_asmt = assessments[-1]
        count = len(assessments)

        first_id = first_asmt.get("assessment_id") or first_asmt.get("id")
        latest_id = latest_asmt.get("assessment_id") or latest_asmt.get("id")

        first_score = float(first_asmt.get("score") if first_asmt.get("score") is not None else 0.0)
        latest_score = float(latest_asmt.get("score") if latest_asmt.get("score") is not None else 0.0)

        all_scores = [float(a.get("score") if a.get("score") is not None else 0.0) for a in assessments]
        min_score = round(min(all_scores), 2)
        max_score = round(max(all_scores), 2)
        avg_score = round(sum(all_scores) / count, 2)

        first_level = first_asmt.get("risk_level") or "UNKNOWN"
        latest_level = latest_asmt.get("risk_level") or "UNKNOWN"

        first_time = first_asmt.get("created_at") or first_asmt.get("evaluated_at")
        latest_time = latest_asmt.get("created_at") or latest_asmt.get("evaluated_at")

        if isinstance(first_time, str):
            try:
                first_time = datetime.fromisoformat(first_time)
            except Exception:
                pass
        if isinstance(latest_time, str):
            try:
                latest_time = datetime.fromisoformat(latest_time)
            except Exception:
                pass

        # Pairwise consecutive transitions
        transitions: List[AssessmentComparison] = []
        driver_changes = 0
        for i in range(count - 1):
            pair_comp = cls.compare(current=assessments[i + 1], previous=assessments[i])
            transitions.append(pair_comp)
            if pair_comp.primary_driver_change_status in (DriverChangeStatus.CHANGED, DriverChangeStatus.NEW):
                driver_changes += 1

        if count < 2:
            trend = RiskTrend.INSUFFICIENT_HISTORY
            score_delta = 0.0
            overall_comp = cls.compare(current=first_asmt, previous=None)
        else:
            score_delta = round(latest_score - first_score, 2)
            trend = cls.classify_trend(score_delta)
            overall_comp = cls.compare(current=latest_asmt, previous=first_asmt)

        latest_driver = latest_asmt.get("primary_driver")
        latest_conflicts = latest_asmt.get("conflicts") or []
        latest_src_summary = latest_asmt.get("source_summary")

        return RiskHistorySummary(
            organization_id=org_id,
            entity_scope=scope_val,
            entity_id=entity_id,
            assessment_count=count,
            first_assessment_id=first_id,
            latest_assessment_id=latest_id,
            first_score=first_score,
            latest_score=latest_score,
            score_delta=score_delta,
            minimum_score=min_score,
            maximum_score=max_score,
            average_score=avg_score,
            first_risk_level=first_level,
            latest_risk_level=latest_level,
            trend=trend,
            primary_driver=latest_driver,
            driver_changes_count=driver_changes,
            conflict_count=len(latest_conflicts),
            source_summary=latest_src_summary,
            history_start=first_time,
            history_end=latest_time,
            assessments=assessments,
            transitions=transitions,
            overall_comparison=overall_comp,
        )
