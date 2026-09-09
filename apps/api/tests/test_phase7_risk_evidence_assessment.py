"""Comprehensive focused test suite for Phase 7 Step 3:
Risk Evidence & Assessment Integration.

Verifies:
1. Evidence Creation, Deterministic IDs, and Provenance Traceability
2. Relevance Classification (PRIMARY, SUPPORTING, CORROBORATING, CONTEXTUAL, CONFLICTING, LIMITATION)
3. Factor-to-Evidence Bi-Directional Linkage and Deduplication
4. Score-to-Factor Traceability (FactorContribution, raw vs weighted delta, ranks)
5. Primary Risk Driver Selection (5-tuple deterministic ordering)
6. Stable Deterministic Factor Ordering
7. Authoritative RiskAssessment Assembly & Semantic Fingerprinting
8. Source Summary & Breakdown (REAL, ESTIMATED, SIMULATED, Independent Counting)
9. Rejection of SIMULATED data as REAL corroboration
10. Conflict Representation & Retention with 0.85 Uncertainty Penalty
11. Quality Gating & Limitations Aggregation
12. Multi-Tenant Isolation Enforcement across Evidence, Factors, Score, and Assessment
13. Probability and Impact Policy (Explicitly unfabricated, remain None)
14. Explainability Integration without Generative Models
15. End-to-End Determinism & Repeatability Across Independent Runs
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
import pytest
from pydantic import ValidationError

from app.integrations.canonical import (
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.normalization.contract import (
    CorroboratingEvidence,
    EntityType,
    NormalizedRiskSignal,
    OperationalValues,
    SignalDomain,
    SignalEntityReferences,
    SignalStatus,
    SignalType,
)
from app.risk_engine import (
    AssessmentSourceSummary,
    BaselineRiskEngine,
    BaselineRiskScoreAggregator,
    CONFLICT_MULTIPLIER,
    EvidenceRelevance,
    FactorContribution,
    RiskAssessment,
    RiskEngine,
    RiskEngineInputError,
    RiskEvaluationContext,
    RiskEvidence,
    RiskExplanation,
    RiskFactor,
    RiskLevel,
    RiskScore,
    TenantMismatchError,
    WeatherRiskFactorEvaluator,
    derive_evidence_relevance,
    generate_assessment_fingerprint,
    generate_deterministic_assessment_id,
    generate_deterministic_evidence_id,
    generate_deterministic_factor_id,
    select_primary_risk_driver,
    sort_factors_deterministically,
)


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================

@pytest.fixture
def eval_time() -> datetime:
    return datetime(2026, 9, 9, 14, 0, 0, tzinfo=timezone.utc)


def build_signal(
    signal_id: str = "sig_001",
    org_id: str = "org_acme",
    domain: SignalDomain = SignalDomain.WEATHER,
    signal_type: SignalType = SignalType.HAZARD,
    event_type: str = "TYPHOON_WARNING",
    status: SignalStatus = SignalStatus.ACTIVE,
    severity: EventSeverity = EventSeverity.HIGH,
    confidence: float = 0.90,
    quality: EventQuality = EventQuality.VALID,
    quality_reasons: Optional[List[str]] = None,
    source: str = "weather_noaa",
    provider: str = "noaa",
    source_type: EventSourceType = EventSourceType.REAL,
    has_conflict: bool = False,
    conflicts: Optional[List[dict]] = None,
    delay_minutes: Optional[float] = None,
    disruption_level: Optional[float] = None,
    latitude: Optional[float] = 22.3193,
    longitude: Optional[float] = 114.1694,
    location_name: Optional[str] = "Port of Hong Kong",
    supporting_sources: Optional[List[CorroboratingEvidence]] = None,
    event_time: Optional[datetime] = None,
    fingerprint: Optional[str] = None,
) -> NormalizedRiskSignal:
    t = event_time or datetime(2026, 9, 9, 13, 30, 0, tzinfo=timezone.utc)
    return NormalizedRiskSignal(
        signal_id=signal_id,
        organization_id=org_id,
        domain=domain,
        signal_type=signal_type,
        event_type=event_type,
        status=status,
        severity=severity,
        confidence=confidence,
        quality=quality,
        quality_reasons=quality_reasons or [],
        source=source,
        provider=provider,
        source_type=source_type,
        canonical_event_id=f"can_{signal_id}",
        event_time=t,
        observed_at=t - timedelta(minutes=5),
        received_at=t,
        latitude=latitude,
        longitude=longitude,
        location_name=location_name,
        has_conflict=has_conflict,
        conflicts=conflicts or [],
        supporting_sources=supporting_sources or [],
        measurements=OperationalValues(
            delay_minutes=delay_minutes,
            disruption_level=disruption_level,
        ),
        fingerprint=fingerprint or f"fp_{signal_id}",
    )


# =============================================================================
# 1. RISK EVIDENCE CONTRACT & PROVENANCE TESTS
# =============================================================================

def test_evidence_creation_from_normalized_signal(eval_time: datetime):
    """Verify strongly typed RiskEvidence captures full signal lineage and provenance."""
    sig = build_signal(signal_id="sig_ev_01", org_id="org_alpha")
    ev = RiskEvidence.from_normalized_signal(sig, organization_id="org_alpha")

    assert ev.normalized_signal_id == "sig_ev_01"
    assert ev.organization_id == "org_alpha"
    assert ev.source == "weather_noaa"
    assert ev.provider == "noaa"
    assert ev.source_type == EventSourceType.REAL
    assert ev.confidence == 0.90
    assert ev.quality == EventQuality.VALID
    assert ev.has_conflict is False
    assert ev.location is not None
    assert ev.location["location_name"] == "Port of Hong Kong"
    assert ev.location["latitude"] == 22.3193
    assert ev.provenance["canonical_event_id"] == "can_sig_ev_01"
    assert ev.provenance["fingerprint"] == "fp_sig_ev_01"


def test_evidence_deterministic_id_generation():
    """Verify evidence ID is strictly deterministic based on org, signal ID, and provider."""
    id1 = generate_deterministic_evidence_id("org_alpha", "sig_001", "noaa")
    id2 = generate_deterministic_evidence_id("org_alpha", "sig_001", "noaa")
    id_diff_provider = generate_deterministic_evidence_id("org_alpha", "sig_001", "openweather")
    id_diff_tenant = generate_deterministic_evidence_id("org_beta", "sig_001", "noaa")

    assert id1 == id2
    assert id1 != id_diff_provider
    assert id1 != id_diff_tenant


def test_evidence_relevance_classification():
    """Verify evidence relevance enum categories are correctly assigned and accessible."""
    sig_primary = build_signal(signal_id="sig_p")
    ev_primary = RiskEvidence.from_normalized_signal(sig_primary, relevance=EvidenceRelevance.PRIMARY)
    assert ev_primary.relevance == EvidenceRelevance.PRIMARY
    assert ev_primary.relevance == "PRIMARY"

    sig_supp = build_signal(signal_id="sig_s")
    ev_supp = RiskEvidence.from_normalized_signal(sig_supp, relevance=EvidenceRelevance.SUPPORTING)
    assert ev_supp.relevance == EvidenceRelevance.SUPPORTING

    sig_corrob = build_signal(signal_id="sig_c")
    ev_corrob = RiskEvidence.from_normalized_signal(sig_corrob, relevance=EvidenceRelevance.CORROBORATING)
    assert ev_corrob.relevance == EvidenceRelevance.CORROBORATING

    sig_conf = build_signal(signal_id="sig_cf", has_conflict=True)
    ev_conf = RiskEvidence.from_normalized_signal(sig_conf, relevance=EvidenceRelevance.CONFLICTING)
    assert ev_conf.relevance == EvidenceRelevance.CONFLICTING


def test_derive_evidence_relevance_deterministic_rules():
    """Verify derive_evidence_relevance deterministically selects correct category."""
    # Conflict signal
    sig_conflict = build_signal(has_conflict=True)
    assert derive_evidence_relevance(sig_conflict) == EvidenceRelevance.CONFLICTING

    # Conflict with conflict list
    sig_conf_list = build_signal(conflicts=[{"provider": "alt", "conflict": "speed"}])
    assert derive_evidence_relevance(sig_conf_list) == EvidenceRelevance.CONFLICTING

    # Invalid quality signal
    sig_invalid = build_signal(quality=EventQuality.INVALID)
    assert derive_evidence_relevance(sig_invalid) == EvidenceRelevance.LIMITATION

    # Secondary partial signal
    sig_partial = build_signal(quality=EventQuality.PARTIAL)
    assert derive_evidence_relevance(sig_partial, is_primary=False) == EvidenceRelevance.LIMITATION

    # Primary valid signal
    sig_valid = build_signal(quality=EventQuality.VALID)
    assert derive_evidence_relevance(sig_valid, is_primary=True) == EvidenceRelevance.PRIMARY


def test_evidence_source_type_retained_accurately():
    """Verify REAL, ESTIMATED, and SIMULATED source types are retained with appropriate limitations."""
    sig_real = build_signal(source_type=EventSourceType.REAL)
    ev_real = RiskEvidence.from_normalized_signal(sig_real)
    assert ev_real.source_type == EventSourceType.REAL
    assert len(ev_real.limitations) == 0

    sig_est = build_signal(source_type=EventSourceType.ESTIMATED)
    ev_est = RiskEvidence.from_normalized_signal(sig_est)
    assert ev_est.source_type == EventSourceType.ESTIMATED
    assert any("ESTIMATED" in lim for lim in ev_est.limitations)

    sig_sim = build_signal(source_type=EventSourceType.SIMULATED)
    ev_sim = RiskEvidence.from_normalized_signal(sig_sim)
    assert ev_sim.source_type == EventSourceType.SIMULATED
    assert any("SIMULATED" in lim for lim in ev_sim.limitations)


# =============================================================================
# 2. FACTOR → EVIDENCE LINKAGE & TRACEABILITY TESTS
# =============================================================================

def test_factor_evidence_linkage_auto_sync():
    """Verify RiskFactor automatically synchronizes evidence_ids and back-links factor_id."""
    sig = build_signal(signal_id="sig_link_01", org_id="org_alpha")
    ev = RiskEvidence.from_normalized_signal(sig, organization_id="org_alpha")

    factor = RiskFactor(
        factor_id="factor_weather_01",
        factor_type="WEATHER_DISRUPTION",
        domain=SignalDomain.WEATHER,
        name="Typhoon Warning",
        contribution=0.85,
        severity=RiskLevel.HIGH,
        confidence=0.90,
        organization_id="org_alpha",
        evidence=[ev],
    )

    assert factor.evidence_ids == [ev.evidence_id]
    assert ev.factor_id == "factor_weather_01"
    assert ev.organization_id == "org_alpha"


def test_factor_multiple_evidence_items():
    """Verify RiskFactor supports multiple evidence traces without duplication."""
    sig1 = build_signal(signal_id="sig_multi_01", org_id="org_alpha")
    sig2 = build_signal(signal_id="sig_multi_02", org_id="org_alpha", provider="tomtom", source="tomtom_feed")
    ev1 = RiskEvidence.from_normalized_signal(sig1, organization_id="org_alpha")
    ev2 = RiskEvidence.from_normalized_signal(sig2, organization_id="org_alpha")

    factor = RiskFactor(
        factor_id="factor_multi_01",
        factor_type="ROAD_DISRUPTION",
        domain=SignalDomain.ROAD,
        name="Severe Highway Closure",
        contribution=0.75,
        severity=RiskLevel.HIGH,
        confidence=0.88,
        organization_id="org_alpha",
        evidence=[ev1, ev2],
    )

    assert len(factor.evidence_ids) == 2
    assert ev1.evidence_id in factor.evidence_ids
    assert ev2.evidence_id in factor.evidence_ids
    assert ev1.factor_id == "factor_multi_01"
    assert ev2.factor_id == "factor_multi_01"


def test_factor_deterministic_id_generation():
    """Verify generate_deterministic_factor_id is stable and order-independent of evidence_ids."""
    id1 = generate_deterministic_factor_id("org_alpha", "WEATHER_DISRUPTION", ["ev_1", "ev_2"])
    id2 = generate_deterministic_factor_id("org_alpha", "WEATHER_DISRUPTION", ["ev_2", "ev_1"])
    id_diff_type = generate_deterministic_factor_id("org_alpha", "ROAD_DISRUPTION", ["ev_1", "ev_2"])
    id_diff_tenant = generate_deterministic_factor_id("org_beta", "WEATHER_DISRUPTION", ["ev_1", "ev_2"])

    assert id1 == id2
    assert id1 != id_diff_type
    assert id1 != id_diff_tenant


# =============================================================================
# 3. SCORE → FACTOR CONTRIBUTION TRACEABILITY TESTS
# =============================================================================

def test_score_factor_contribution_generation(eval_time: datetime):
    """Verify BaselineRiskScoreAggregator populates typed FactorContribution records."""
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=eval_time)
    f1 = RiskFactor(
        factor_id="f_01",
        factor_type="WEATHER_DISRUPTION",
        domain=SignalDomain.WEATHER,
        name="Severe Storm",
        contribution=0.80,
        severity=RiskLevel.HIGH,
        confidence=0.90,
        organization_id="org_alpha",
    )
    f2 = RiskFactor(
        factor_id="f_02",
        factor_type="ROAD_DISRUPTION",
        domain=SignalDomain.ROAD,
        name="Highway Blockage",
        contribution=0.50,
        severity=RiskLevel.MEDIUM,
        confidence=0.85,
        organization_id="org_alpha",
    )

    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[f1, f2], evidence=[], context=ctx)

    assert len(score.factor_contributions) == 2
    fc1 = score.factor_contributions[0]
    fc2 = score.factor_contributions[1]

    # Primary driver
    assert fc1.factor_id == "f_01"
    assert fc1.rank == 1
    assert fc1.raw_contribution == 0.80
    assert fc1.weighted_contribution == 80.0  # 100 * 0.80

    # Secondary driver compounds into remaining 20 headroom
    # delta = 20.0 * (0.50 * (0.50 / (1.0 + 0.20 * 1))) = 20.0 * (0.50 * 0.416666) = 4.17
    assert fc2.factor_id == "f_02"
    assert fc2.rank == 2
    assert fc2.raw_contribution == 0.50
    assert fc2.weighted_contribution == 4.17

    assert score.score == 84.17
    assert score.risk_level == RiskLevel.HIGH
    assert score.primary_factor_id == "f_01"


def test_score_empty_factors_produces_zero_score(eval_time: datetime):
    """Verify empty factor list produces 0.0 score, LOW level, and empty contributions."""
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=eval_time)
    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[], evidence=[], context=ctx)

    assert score.score == 0.0
    assert score.risk_level == RiskLevel.LOW
    assert score.primary_factor_id is None
    assert len(score.factor_contributions) == 0


def test_score_factor_contributions_preserve_evidence_ids(eval_time: datetime):
    """Verify FactorContribution retains linked evidence_ids."""
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=eval_time)
    sig = build_signal(signal_id="sig_trace_01", org_id="org_alpha")
    ev = RiskEvidence.from_normalized_signal(sig, organization_id="org_alpha")
    factor = RiskFactor(
        factor_id="f_trace",
        factor_type="WEATHER_DISRUPTION",
        domain=SignalDomain.WEATHER,
        name="Storm Alert",
        contribution=0.60,
        severity=RiskLevel.MEDIUM,
        confidence=0.80,
        organization_id="org_alpha",
        evidence=[ev],
    )

    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[factor], evidence=[ev], context=ctx)

    assert len(score.factor_contributions) == 1
    fc = score.factor_contributions[0]
    assert fc.evidence_ids == [ev.evidence_id]


# =============================================================================
# 4. DETERMINISTIC PRIMARY DRIVER & FACTOR ORDERING TESTS
# =============================================================================

def test_primary_driver_selection_highest_contribution():
    """Verify primary driver selects factor with highest contribution."""
    f_low = RiskFactor(factor_id="f_l", factor_type="T", domain=SignalDomain.WEATHER, name="Low", contribution=0.30, severity=RiskLevel.LOW)
    f_high = RiskFactor(factor_id="f_h", factor_type="T", domain=SignalDomain.WEATHER, name="High", contribution=0.85, severity=RiskLevel.HIGH)

    top = select_primary_risk_driver([f_low, f_high])
    assert top is not None
    assert top.factor_id == "f_h"


def test_primary_driver_tie_break_severity():
    """Verify tie in contribution breaks on severity (CRITICAL > HIGH > MEDIUM > LOW)."""
    f_high_sev = RiskFactor(factor_id="f_hs", factor_type="T", domain=SignalDomain.WEATHER, name="HighSev", contribution=0.70, severity=RiskLevel.CRITICAL)
    f_med_sev = RiskFactor(factor_id="f_ms", factor_type="T", domain=SignalDomain.WEATHER, name="MedSev", contribution=0.70, severity=RiskLevel.HIGH)

    top = select_primary_risk_driver([f_med_sev, f_high_sev])
    assert top is not None
    assert top.factor_id == "f_hs"


def test_primary_driver_tie_break_confidence():
    """Verify tie in contribution and severity breaks on confidence."""
    f_high_conf = RiskFactor(factor_id="f_hc", factor_type="T", domain=SignalDomain.WEATHER, name="HighConf", contribution=0.70, severity=RiskLevel.HIGH, confidence=0.95)
    f_low_conf = RiskFactor(factor_id="f_lc", factor_type="T", domain=SignalDomain.WEATHER, name="LowConf", contribution=0.70, severity=RiskLevel.HIGH, confidence=0.75)

    top = select_primary_risk_driver([f_low_conf, f_high_conf])
    assert top is not None
    assert top.factor_id == "f_hc"


def test_primary_driver_tie_break_evidence_quality():
    """Verify tie in contribution, severity, and confidence breaks on evidence quality."""
    sig_valid = build_signal(signal_id="sig_v", quality=EventQuality.VALID)
    sig_partial = build_signal(signal_id="sig_p", quality=EventQuality.PARTIAL)
    ev_valid = RiskEvidence.from_normalized_signal(sig_valid)
    ev_partial = RiskEvidence.from_normalized_signal(sig_partial)

    f_valid = RiskFactor(factor_id="f_val", factor_type="T", domain=SignalDomain.WEATHER, name="Valid", contribution=0.70, severity=RiskLevel.HIGH, confidence=0.90, evidence=[ev_valid])
    f_partial = RiskFactor(factor_id="f_part", factor_type="T", domain=SignalDomain.WEATHER, name="Partial", contribution=0.70, severity=RiskLevel.HIGH, confidence=0.90, evidence=[ev_partial])

    top = select_primary_risk_driver([f_partial, f_valid])
    assert top is not None
    assert top.factor_id == "f_val"


def test_primary_driver_tie_break_factor_id():
    """Verify final tie breaks deterministically on alphabetical factor_id."""
    f_a = RiskFactor(factor_id="factor_alpha", factor_type="T", domain=SignalDomain.WEATHER, name="Alpha", contribution=0.70, severity=RiskLevel.HIGH, confidence=0.90)
    f_b = RiskFactor(factor_id="factor_beta", factor_type="T", domain=SignalDomain.WEATHER, name="Beta", contribution=0.70, severity=RiskLevel.HIGH, confidence=0.90)

    top = select_primary_risk_driver([f_b, f_a])
    assert top is not None
    assert top.factor_id == "factor_alpha"


def test_sort_factors_deterministically_stability():
    """Verify sort_factors_deterministically produces identical order regardless of input permutation."""
    f1 = RiskFactor(factor_id="f_1", factor_type="T", domain=SignalDomain.WEATHER, name="One", contribution=0.90, severity=RiskLevel.CRITICAL)
    f2 = RiskFactor(factor_id="f_2", factor_type="T", domain=SignalDomain.ROAD, name="Two", contribution=0.60, severity=RiskLevel.HIGH)
    f3 = RiskFactor(factor_id="f_3", factor_type="T", domain=SignalDomain.OCEAN, name="Three", contribution=0.30, severity=RiskLevel.LOW)

    order1 = [f.factor_id for f in sort_factors_deterministically([f1, f2, f3])]
    order2 = [f.factor_id for f in sort_factors_deterministically([f3, f1, f2])]
    order3 = [f.factor_id for f in sort_factors_deterministically([f2, f3, f1])]

    assert order1 == ["f_1", "f_2", "f_3"]
    assert order1 == order2 == order3


# =============================================================================
# 5. RISK ASSESSMENT CONTRACT & SEMANTIC FINGERPRINTING TESTS
# =============================================================================

def test_assessment_generation_end_to_end(eval_time: datetime):
    """Verify complete deterministic RiskAssessment generation with BaselineRiskEngine."""
    sig = build_signal(
        signal_id="sig_full_01",
        org_id="org_alpha",
        domain=SignalDomain.WEATHER,
        severity=EventSeverity.CRITICAL,
        confidence=0.95,
    )
    ctx = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=[sig],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    assert assessment.organization_id == "org_alpha"
    assert assessment.evaluated_at == eval_time
    assert assessment.overall_score is not None
    assert assessment.score == assessment.overall_score.score
    assert assessment.risk_level == RiskLevel.CRITICAL
    assert assessment.probability is None
    assert assessment.impact is None
    assert assessment.confidence == 0.95
    assert len(assessment.factors) == 1
    assert assessment.primary_factor_id == assessment.factors[0].factor_id
    assert assessment.primary_factor is not None
    assert assessment.primary_factor.name == assessment.factors[0].name
    assert assessment.source_summary is not None
    assert assessment.source_summary.evidence_count == 1
    assert assessment.fingerprint is not None


def test_assessment_fingerprint_deterministic_stability(eval_time: datetime):
    """Verify semantic assessment fingerprint is identical across multiple runs with identical input."""
    fp1 = generate_assessment_fingerprint("org_alpha", "GLOBAL", ["sig_1", "sig_2"], ["f_1"], 75.0, "HIGH")
    fp2 = generate_assessment_fingerprint("org_alpha", "GLOBAL", ["sig_2", "sig_1"], ["f_1"], 75.0, "HIGH")
    assert fp1 == fp2

    fp_diff_org = generate_assessment_fingerprint("org_beta", "GLOBAL", ["sig_1", "sig_2"], ["f_1"], 75.0, "HIGH")
    fp_diff_score = generate_assessment_fingerprint("org_alpha", "GLOBAL", ["sig_1", "sig_2"], ["f_1"], 80.0, "HIGH")
    assert fp1 != fp_diff_org
    assert fp1 != fp_diff_score


def test_assessment_score_property_delegation(eval_time: datetime):
    """Verify assessment.score delegates cleanly to overall_score.score."""
    assessment = RiskAssessment(
        assessment_id="test_asm",
        organization_id="org_alpha",
        evaluated_at=eval_time,
        overall_score=RiskScore(
            score=72.5,
            risk_level=RiskLevel.HIGH,
            timestamp=eval_time,
        ),
    )
    assert assessment.score == 72.5


# =============================================================================
# 6. SOURCE SUMMARY & OBSERVATION BREAKDOWN TESTS
# =============================================================================

def test_source_summary_counts_real_estimated_simulated(eval_time: datetime):
    """Verify AssessmentSourceSummary distinguishes REAL, ESTIMATED, and SIMULATED sources."""
    sig_real = build_signal(signal_id="sig_r", source="noaa", provider="noaa", source_type=EventSourceType.REAL)
    sig_est = build_signal(signal_id="sig_e", source="tomtom", provider="tomtom", source_type=EventSourceType.ESTIMATED)
    sig_sim = build_signal(signal_id="sig_s", source="scenario_sim", provider="simulator", source_type=EventSourceType.SIMULATED)

    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        signals=[sig_real, sig_est, sig_sim],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    summary = assessment.source_summary
    assert summary is not None
    assert summary.evidence_count == 3
    assert summary.real_sources_count == 1
    assert summary.estimated_sources_count == 1
    assert summary.simulated_sources_count == 1
    assert summary.independent_sources_count == 3
    assert "noaa" in summary.providers
    assert "tomtom" in summary.providers
    assert "simulator" in summary.providers


def test_source_summary_duplicate_provider_not_inflated(eval_time: datetime):
    """Verify repeated events from the same provider do NOT inflate independent source count."""
    # 3 distinct signals from the same provider 'noaa'
    sig1 = build_signal(signal_id="sig_n1", provider="noaa", event_type="WIND_ALERT")
    sig2 = build_signal(signal_id="sig_n2", provider="noaa", event_type="RAIN_ALERT")
    sig3 = build_signal(signal_id="sig_n3", provider="noaa", event_type="FLOOD_ALERT")

    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        signals=[sig1, sig2, sig3],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    summary = assessment.source_summary
    assert summary is not None
    assert summary.evidence_count == 3
    # All 3 are from 'noaa' -> exactly 1 independent source
    assert summary.independent_sources_count == 1
    assert summary.real_sources_count == 1


def test_simulated_data_never_counted_as_real_corroboration(eval_time: datetime):
    """Verify SIMULATED supporting traces are never counted as real corroboration."""
    supp_sim = CorroboratingEvidence(
        source="sim_feed",
        provider="sim_engine",
        source_type="SIMULATED",
        summary="Simulated synthetic confirmation",
    )
    supp_real = CorroboratingEvidence(
        source="met_office",
        provider="uk_met",
        source_type="REAL",
        summary="Real meteorology confirmation",
    )

    sig = build_signal(
        signal_id="sig_corrob_check",
        provider="noaa",
        supporting_sources=[supp_sim, supp_real],
    )
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        signals=[sig],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    summary = assessment.source_summary
    assert summary is not None
    # Only uk_met is counted; sim_engine is rejected as corroboration
    assert summary.corroborating_sources_count == 1


# =============================================================================
# 7. CONFLICT REPRESENTATION & RETENTION TESTS
# =============================================================================

def test_conflict_preservation_and_penalty(eval_time: datetime):
    """Verify conflicts are retained in assessment.conflicts and apply 0.85 penalty."""
    conflict_data = [
        {"provider": "openweather", "value": "25 C", "conflict_type": "VALUE_MISMATCH"}
    ]
    sig_conflict = build_signal(
        signal_id="sig_conf_01",
        has_conflict=True,
        conflicts=conflict_data,
        severity=EventSeverity.HIGH,
        confidence=1.0,
    )
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        signals=[sig_conflict],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    assert len(assessment.conflicts) == 1
    assert assessment.conflicts[0]["signal_id"] == "sig_conf_01"
    assert assessment.conflicts[0]["uncertainty_multiplier"] == CONFLICT_MULTIPLIER

    # High severity = 0.85; conflict multiplier = 0.85; expected contribution = 0.85 * 0.85 = 0.7225
    # score = 72.25
    assert assessment.score == 72.25
    assert assessment.risk_level == RiskLevel.HIGH
    assert any("conflict" in lim.lower() for lim in assessment.limitations)


def test_conflict_does_not_drop_evidence(eval_time: datetime):
    """Verify conflicting signals still generate full traceable evidence records."""
    sig_conflict = build_signal(signal_id="sig_conf_retain", has_conflict=True)
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        signals=[sig_conflict],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    assert len(assessment.evidence) == 1
    ev = assessment.evidence[0]
    assert ev.has_conflict is True
    assert ev.relevance in (EvidenceRelevance.CONFLICTING, "CONFLICTING")


# =============================================================================
# 8. QUALITY GATING & LIMITATIONS AGGREGATION TESTS
# =============================================================================

def test_partial_quality_generates_limitations(eval_time: datetime):
    """Verify PARTIAL quality signals generate explicit limitations in the assessment."""
    sig_partial = build_signal(
        signal_id="sig_part_01",
        quality=EventQuality.PARTIAL,
        quality_reasons=["MISSING_COORDINATES", "UNVERIFIED_SOURCE"],
        latitude=None,
        longitude=None,
        location_name=None,
    )
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        allow_partial_signals=True,
        signals=[sig_partial],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    assert any("PARTIAL" in lim for lim in assessment.limitations)
    assert any("lack spatial coordinates" in lim for lim in assessment.limitations)


def test_stale_timestamp_generates_limitation(eval_time: datetime):
    """Verify signals with observations older than 24 hours generate stale limitations."""
    stale_time = eval_time - timedelta(hours=48)
    sig_stale = build_signal(
        signal_id="sig_stale_01",
        event_time=stale_time,
    )
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        signals=[sig_stale],
    )
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    assert any("older than 24 hours" in lim for lim in assessment.limitations)


# =============================================================================
# 9. MULTI-TENANT ISOLATION TESTS
# =============================================================================

def test_tenant_isolation_context_signal_mismatch(eval_time: datetime):
    """Verify passing a cross-tenant signal to RiskEvaluationContext raises TenantMismatchError."""
    sig_other_tenant = build_signal(signal_id="sig_t_diff", org_id="org_other")
    with pytest.raises(TenantMismatchError):
        RiskEvaluationContext(
            organization_id="org_acme",
            evaluation_time=eval_time,
            signals=[sig_other_tenant],
        )


def test_tenant_isolation_add_signal_mismatch(eval_time: datetime):
    """Verify add_signal rejects cross-tenant signals."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    sig_other_tenant = build_signal(signal_id="sig_t_add", org_id="org_other")
    with pytest.raises(TenantMismatchError):
        ctx.add_signal(sig_other_tenant)


def test_tenant_isolation_evidence_creation_mismatch():
    """Verify RiskEvidence.from_normalized_signal rejects mismatched organization_id."""
    sig = build_signal(signal_id="sig_ev_tenant", org_id="org_acme")
    with pytest.raises(TenantMismatchError):
        RiskEvidence.from_normalized_signal(sig, organization_id="org_other")


def test_tenant_isolation_scoring_factor_mismatch(eval_time: datetime):
    """Verify BaselineRiskScoreAggregator rejects factors belonging to a different tenant."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    f_other = RiskFactor(
        factor_id="f_diff_org",
        factor_type="WEATHER_DISRUPTION",
        domain=SignalDomain.WEATHER,
        name="Storm",
        contribution=0.80,
        organization_id="org_other",
    )
    aggregator = BaselineRiskScoreAggregator()
    with pytest.raises(TenantMismatchError):
        aggregator.aggregate(factors=[f_other], evidence=[], context=ctx)


def test_tenant_isolation_scoring_evidence_mismatch(eval_time: datetime):
    """Verify BaselineRiskScoreAggregator rejects evidence belonging to a different tenant."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    sig = build_signal(signal_id="sig_mismatch_ev", org_id="org_other")
    ev_other = RiskEvidence(
        evidence_id="ev_other_01",
        normalized_signal_id="sig_mismatch_ev",
        organization_id="org_other",
        source="noaa",
        provider="noaa",
        event_time=eval_time,
    )
    aggregator = BaselineRiskScoreAggregator()
    with pytest.raises(TenantMismatchError):
        aggregator.aggregate(factors=[], evidence=[ev_other], context=ctx)


# =============================================================================
# 10. EXPLAINABILITY INTEGRATION TESTS
# =============================================================================

def test_deterministic_explanation_structure(eval_time: datetime):
    """Verify RiskExplanation cleanly exposes primary drivers, scores, and factors."""
    sig = build_signal(signal_id="sig_exp_01", org_id="org_acme", severity=EventSeverity.HIGH)
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig])
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    exp: RiskExplanation = assessment.explanation
    assert exp is not None
    assert exp.score == assessment.score
    assert exp.risk_level == assessment.risk_level
    assert exp.primary_driver is not None
    assert len(exp.factor_explanations) == 1
    assert exp.factor_explanations[0].rank == 1
    assert exp.factor_explanations[0].weighted_contribution is not None
    assert len(exp.factor_explanations[0].evidence_ids) > 0


def test_explanation_no_factors(eval_time: datetime):
    """Verify explanation for empty factors is deterministic and informative."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[])
    engine = BaselineRiskEngine()
    assessment = engine.evaluate(ctx)

    exp: RiskExplanation = assessment.explanation
    assert exp is not None
    assert "No active risk factors identified" in exp.summary
    assert exp.primary_driver is None
    assert exp.score == 0.0
    assert exp.risk_level == RiskLevel.LOW


# =============================================================================
# 11. END-TO-END REPEATABILITY & DETERMINISM TESTS
# =============================================================================

def test_end_to_end_assessment_determinism_across_runs(eval_time: datetime):
    """Verify 5 independent engine runs on identical inputs yield 100% identical outputs."""
    sig1 = build_signal(signal_id="sig_det_01", org_id="org_acme", domain=SignalDomain.WEATHER, severity=EventSeverity.HIGH)
    sig2 = build_signal(signal_id="sig_det_02", org_id="org_acme", domain=SignalDomain.ROAD, severity=EventSeverity.MEDIUM, delay_minutes=45.0)

    assessments = []
    for _ in range(5):
        ctx = RiskEvaluationContext(
            organization_id="org_acme",
            evaluation_time=eval_time,
            signals=[sig1, sig2],
        )
        engine = BaselineRiskEngine()
        asm = engine.evaluate(ctx)
        assessments.append(asm)

    first = assessments[0]
    for other in assessments[1:]:
        assert other.assessment_id == first.assessment_id
        assert other.fingerprint == first.fingerprint
        assert other.score == first.score
        assert other.risk_level == first.risk_level
        assert other.primary_factor_id == first.primary_factor_id
        assert [f.factor_id for f in other.factors] == [f.factor_id for f in first.factors]
        assert other.explanation.summary == first.explanation.summary
        assert other.source_summary.model_dump() == first.source_summary.model_dump()


# =============================================================================
# 12. EVIDENCE CONTRACT EXTENSIONS & BOUNDARY TESTS
# =============================================================================

def test_evidence_relevance_roundtrip_dict():
    """Verify evidence relevance survives model_dump and dict roundtrip."""
    sig = build_signal()
    ev = RiskEvidence.from_normalized_signal(sig, relevance=EvidenceRelevance.CORROBORATING)
    d = ev.model_dump()
    assert d["relevance"] == "CORROBORATING"
    ev2 = RiskEvidence(**d)
    assert ev2.relevance == EvidenceRelevance.CORROBORATING


def test_evidence_relevance_float_backward_compat():
    """Verify legacy float relevance (e.g. 0.85) is fully accepted without validation error."""
    sig = build_signal()
    ev = RiskEvidence.from_normalized_signal(sig, relevance=0.85)
    assert ev.relevance == 0.85


def test_evidence_relevance_string_assignment():
    """Verify string values corresponding to EvidenceRelevance are accepted."""
    sig = build_signal()
    ev = RiskEvidence.from_normalized_signal(sig, relevance="LIMITATION")
    assert ev.relevance == "LIMITATION"


def test_evidence_rejects_raw_dict():
    """Verify RiskEvidence.from_normalized_signal rejects raw dictionaries."""
    with pytest.raises(RiskEngineInputError):
        RiskEvidence.from_normalized_signal({"signal_id": "raw_dict"})


def test_evidence_location_none_when_empty():
    """Verify evidence.location is None when signal carries no spatial indicators."""
    sig = build_signal(latitude=None, longitude=None, location_name=None)
    # Clear region & country
    sig = sig.model_copy(update={"region": None, "country_code": None})
    ev = RiskEvidence.from_normalized_signal(sig)
    assert ev.location is None


def test_evidence_location_partial_fields():
    """Verify evidence.location captures partial spatial coordinates accurately."""
    sig = build_signal(latitude=1.3521, longitude=103.8198, location_name=None)
    ev = RiskEvidence.from_normalized_signal(sig)
    assert ev.location is not None
    assert ev.location["latitude"] == 1.3521
    assert ev.location["longitude"] == 103.8198


def test_evidence_limitations_multiple_reasons():
    """Verify multiple quality caveats are joined into informative limitation strings."""
    sig = build_signal(
        quality=EventQuality.PARTIAL,
        quality_reasons=["LOW_CONFIDENCE", "MISSING_TIMESTAMP"],
        source_type=EventSourceType.ESTIMATED,
    )
    ev = RiskEvidence.from_normalized_signal(sig)
    assert len(ev.limitations) >= 2
    assert any("LOW_CONFIDENCE" in lim for lim in ev.limitations)
    assert any("ESTIMATED" in lim for lim in ev.limitations)


def test_evidence_timezone_naive_conversion_utc():
    """Verify timezone-naive event_time is automatically converted to UTC."""
    naive_t = datetime(2026, 9, 9, 10, 0, 0)
    ev = RiskEvidence(
        evidence_id="ev_naive",
        normalized_signal_id="sig_naive",
        source="noaa",
        provider="noaa",
        event_time=naive_t,
    )
    assert ev.event_time.tzinfo == timezone.utc


# =============================================================================
# 13. FACTOR LINKAGE & SYSTEM-GENERATED FACTOR TESTS
# =============================================================================

def test_factor_system_generated_without_evidence():
    """Verify documented system-generated factor can exist with empty evidence list."""
    factor = RiskFactor(
        factor_id="factor_sys_01",
        factor_type="SYSTEM_DEGRADATION",
        domain=SignalDomain.GENERAL,
        name="Telemetry Pipeline Latency",
        contribution=0.20,
        severity=RiskLevel.LOW,
        confidence=1.0,
        evidence=[],
    )
    assert factor.evidence_ids == []
    assert len(factor.evidence) == 0


def test_factor_pre_populated_evidence_ids_preserved():
    """Verify explicitly passed evidence_ids are preserved."""
    factor = RiskFactor(
        factor_id="factor_pre_01",
        factor_type="WEATHER_DISRUPTION",
        domain=SignalDomain.WEATHER,
        name="Storm",
        contribution=0.50,
        evidence_ids=["ev_manual_01", "ev_manual_02"],
    )
    assert factor.evidence_ids == ["ev_manual_01", "ev_manual_02"]


def test_factor_serialization_roundtrip():
    """Verify RiskFactor serializes cleanly to dict and reconstructs identical instance."""
    sig = build_signal()
    ev = RiskEvidence.from_normalized_signal(sig)
    factor = RiskFactor(
        factor_id="f_ser_01",
        factor_type="WEATHER_DISRUPTION",
        domain=SignalDomain.WEATHER,
        name="Typhoon",
        contribution=0.85,
        severity=RiskLevel.HIGH,
        organization_id="org_acme",
        evidence=[ev],
    )
    d = factor.model_dump()
    f2 = RiskFactor(**d)
    assert f2.factor_id == factor.factor_id
    assert f2.organization_id == "org_acme"
    assert f2.evidence_ids == [ev.evidence_id]


# =============================================================================
# 14. COMPOUND SCORE TRACEABILITY & DIMINISHING WEIGHT TESTS
# =============================================================================

def test_score_three_factors_diminishing_weight_exact(eval_time: datetime):
    """Verify 3-factor compounding matches mathematical formula and assigns exact delta points."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    f1 = RiskFactor(factor_id="f1", factor_type="T", domain=SignalDomain.WEATHER, name="F1", contribution=0.70, severity=RiskLevel.HIGH)
    f2 = RiskFactor(factor_id="f2", factor_type="T", domain=SignalDomain.ROAD, name="F2", contribution=0.60, severity=RiskLevel.MEDIUM)
    f3 = RiskFactor(factor_id="f3", factor_type="T", domain=SignalDomain.OCEAN, name="F3", contribution=0.40, severity=RiskLevel.LOW)

    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[f1, f2, f3], evidence=[], context=ctx)

    # Calculation:
    # S1 = 70.0
    # Headroom after S1 = 30.0
    # rank 2: weight = 0.5 / (1 + 0.2*1) = 0.5 / 1.2 = 0.416666...
    # delta2 = 30.0 * 0.60 * (0.5 / 1.2) = 18.0 * 0.416666... = 7.50
    # current_score = 77.50
    # Headroom after S2 = 22.50
    # rank 3: weight = 0.5 / (1 + 0.2*2) = 0.5 / 1.4 = 0.3571428...
    # delta3 = 22.50 * 0.40 * (0.5 / 1.4) = 9.0 * 0.3571428... = 3.21428... = 3.21
    # current_score = 77.50 + 3.21 = 80.71
    assert score.score == 80.71
    assert len(score.factor_contributions) == 3
    assert score.factor_contributions[0].weighted_contribution == 70.0
    assert score.factor_contributions[1].weighted_contribution == 7.50
    assert score.factor_contributions[2].weighted_contribution == 3.21


def test_score_factor_contribution_zero_raw(eval_time: datetime):
    """Verify factor with 0.0 raw contribution receives 0.0 weighted contribution."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    f1 = RiskFactor(factor_id="f1", factor_type="T", domain=SignalDomain.WEATHER, name="F1", contribution=0.50)
    f2 = RiskFactor(factor_id="f2", factor_type="T", domain=SignalDomain.ROAD, name="F2", contribution=0.0)

    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[f1, f2], evidence=[], context=ctx)

    assert score.factor_contributions[1].weighted_contribution == 0.0
    assert score.score == 50.0


def test_score_factor_saturation_stops_compounding(eval_time: datetime):
    """Verify when score reaches 100.0 saturation, subsequent factors add 0.0 delta."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    f1 = RiskFactor(factor_id="f1", factor_type="T", domain=SignalDomain.WEATHER, name="F1", contribution=1.0)
    f2 = RiskFactor(factor_id="f2", factor_type="T", domain=SignalDomain.ROAD, name="F2", contribution=1.0)

    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[f1, f2], evidence=[], context=ctx)

    assert score.score == 100.0
    assert score.factor_contributions[0].weighted_contribution == 100.0
    assert score.factor_contributions[1].weighted_contribution == 0.0


def test_score_min_confidence_multi_factor(eval_time: datetime):
    """Verify composite confidence is the minimum across all contributing factors."""
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time)
    f1 = RiskFactor(factor_id="f1", factor_type="T", domain=SignalDomain.WEATHER, name="F1", contribution=0.5, confidence=0.95)
    f2 = RiskFactor(factor_id="f2", factor_type="T", domain=SignalDomain.ROAD, name="F2", contribution=0.4, confidence=0.72)

    aggregator = BaselineRiskScoreAggregator()
    score = aggregator.aggregate(factors=[f1, f2], evidence=[], context=ctx)
    assert score.confidence == 0.72


def test_score_timestamp_naive_converted_to_utc():
    """Verify RiskScore timestamp enforces UTC conversion."""
    naive_t = datetime(2026, 9, 9, 12, 0, 0)
    score = RiskScore(score=50.0, timestamp=naive_t)
    assert score.timestamp.tzinfo == timezone.utc


# =============================================================================
# 15. PRIMARY DRIVER & ASSESSMENT EXTENSIONS
# =============================================================================

def test_primary_driver_empty_factors_returns_none():
    """Verify select_primary_risk_driver returns None on empty input."""
    assert select_primary_risk_driver([]) is None


def test_assessment_custom_scope_and_entity_id(eval_time: datetime):
    """Verify RiskAssessment supports SHIPMENT, PORT, and ROUTE scope evaluations."""
    sig = build_signal(signal_id="sig_shipment", org_id="org_acme")
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        scope="SHIPMENT",
        scope_entity_id="shipment_xyz_123",
        scope_entity_type=EntityType.SHIPMENT,
        evaluation_time=eval_time,
        signals=[sig],
    )
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    assert asm.scope == "SHIPMENT"
    assert asm.scope_entity_id == "shipment_xyz_123"
    assert asm.scope_entity_type == EntityType.SHIPMENT


def test_assessment_metadata_preservation(eval_time: datetime):
    """Verify context metadata and pipeline diagnostic telemetry are preserved in assessment."""
    ctx = RiskEvaluationContext(
        organization_id="org_acme",
        evaluation_time=eval_time,
        correlation_id="corr_999",
        trace_id="trace_888",
        metadata={"custom_audit_key": "audit_value_123"},
    )
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    assert asm.metadata["correlation_id"] == "corr_999"
    assert asm.metadata["trace_id"] == "trace_888"
    assert asm.metadata["custom_audit_key"] == "audit_value_123"
    assert "evaluation_duration_ms" in asm.metadata


def test_assessment_evaluated_at_naive_converted_to_utc():
    """Verify RiskAssessment evaluated_at enforces UTC conversion."""
    naive_t = datetime(2026, 9, 9, 8, 0, 0)
    asm = RiskAssessment(
        assessment_id="asm_naive",
        organization_id="org_acme",
        evaluated_at=naive_t,
    )
    assert asm.evaluated_at.tzinfo == timezone.utc


def test_assessment_serialization_dict_and_json(eval_time: datetime):
    """Verify RiskAssessment serializes cleanly to JSON and dictionary without loss."""
    sig = build_signal()
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig])
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    json_str = asm.model_dump_json()
    assert "assessment_id" in json_str
    assert "fingerprint" in json_str
    assert "source_summary" in json_str

    reconstructed = RiskAssessment.model_validate_json(json_str)
    assert reconstructed.assessment_id == asm.assessment_id
    assert reconstructed.fingerprint == asm.fingerprint
    assert reconstructed.score == asm.score


# =============================================================================
# 16. SOURCE SUMMARY & LIMITATIONS CORNER CASES
# =============================================================================

def test_source_summary_only_simulated_sources(eval_time: datetime):
    """Verify source summary handles pure synthetic simulation scenarios correctly."""
    sig = build_signal(source_type=EventSourceType.SIMULATED)
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig])
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    summary = asm.source_summary
    assert summary.simulated_sources_count == 1
    assert summary.real_sources_count == 0
    assert summary.estimated_sources_count == 0


def test_source_summary_only_estimated_sources(eval_time: datetime):
    """Verify source summary handles pure estimated observation scenarios correctly."""
    sig = build_signal(source_type=EventSourceType.ESTIMATED)
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig])
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    summary = asm.source_summary
    assert summary.estimated_sources_count == 1
    assert summary.real_sources_count == 0
    assert summary.simulated_sources_count == 0


def test_source_summary_matching_provider_corroboration_ignored(eval_time: datetime):
    """Verify supporting source with same provider as primary evidence is not counted as corroboration."""
    supp_same = CorroboratingEvidence(
        source="weather_noaa",
        provider="noaa",
        source_type="REAL",
        summary="Internal repeated observation",
    )
    sig = build_signal(provider="noaa", supporting_sources=[supp_same])
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig])
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    assert asm.source_summary.corroborating_sources_count == 0


def test_conflict_multi_signal_preservation(eval_time: datetime):
    """Verify multiple distinct conflicting signals each preserve their conflict record."""
    sig1 = build_signal(signal_id="sig_c1", has_conflict=True, event_type="DELAY_1")
    sig2 = build_signal(signal_id="sig_c2", has_conflict=True, event_type="DELAY_2")
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig1, sig2])
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    assert len(asm.conflicts) == 2
    assert {c["signal_id"] for c in asm.conflicts} == {"sig_c1", "sig_c2"}


def test_limitations_both_simulated_and_estimated(eval_time: datetime):
    """Verify both simulated and estimated caveats appear when mixed sources exist."""
    sig_sim = build_signal(signal_id="sig_s", source_type=EventSourceType.SIMULATED)
    sig_est = build_signal(signal_id="sig_e", source_type=EventSourceType.ESTIMATED)
    ctx = RiskEvaluationContext(organization_id="org_acme", evaluation_time=eval_time, signals=[sig_sim, sig_est])
    engine = BaselineRiskEngine()
    asm = engine.evaluate(ctx)

    assert any("SIMULATED" in lim for lim in asm.limitations)
    assert any("ESTIMATED" in lim for lim in asm.limitations)

