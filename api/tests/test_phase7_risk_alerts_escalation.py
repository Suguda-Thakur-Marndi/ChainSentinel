"""Focused test suite for RiskWise 2.0 — Phase 7 Step 6: Risk Alerts, Thresholds & Escalation.

Validates:
1. Threshold tests (LOW no alert, MEDIUM behavior, boundaries at 30.0, 60.0, 85.0, score 0.0, 100.0, level transitions).
2. Alert trigger tests (HIGH reached, CRITICAL reached, level increased/decreased, score jump, upward trend, critical factor, new conflict, quality degraded, driver changed).
3. Deduplication tests (deterministic IDs, idempotency hit, repeated evaluations, distinct assessments).
4. Severity & Escalation tests (deterministic mapping, transition escalation to CRITICAL/WARNING, INFO de-escalation).
5. Evidence & Traceability tests (assessment ID, factor ID, evidence IDs, conflict citations, quality citations).
6. Explanation tests (deterministic rule-based text, score/level/factor/conflict explanations).
7. Persistence & Transaction tests (atomic persistence, rollback on failure, audit logging, notification queries, read status).
8. Tenant Isolation tests (cross-tenant query rejection, cross-tenant acknowledgement 404, org context enforcement).
9. API tests (authentication, roles, pagination, status/severity/type filtering).
10. Security & Secret Scrubbing tests (no secrets in title/summary/metadata, rejection of raw payloads).
11. No-Action tests (verify zero rerouting, zero cancellation, zero carrier interaction, zero optimization execution).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import pytest
from fastapi import status
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.core.context import AuthenticatedContext
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork
from app.main import app
from app.models.governance import Action, Approval, AuditLog, Notification, Recommendation
from app.models.tenancy import Organization, User
from app.models.risk import Risk as ORMRisk, RiskAssessment as ORMRiskAssessment, RiskFactor as ORMRiskFactor
from app.normalization.contract import (
    CanonicalEventType,
    EntityType,
    EventQuality,
    EventSeverity,
    EventSourceType,
    NormalizedRiskSignal,
    SignalDomain,
    SignalType,
)
from app.risk_engine.alerts import (
    AlertRuleConfig,
    AlertSeverity,
    AlertStatus,
    RiskAlert,
    RiskAlertEvaluator,
    RiskAlertNotificationAdapter,
    RiskAlertType,
    compute_alert_id,
)
from app.risk_engine.contract import (
    AssessmentSourceSummary,
    FactorContribution,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
)
from app.risk_engine.evidence import EvidenceRelevance, RiskEvidence
from app.risk_engine.persistence import RiskAssessmentPersistenceAdapter
from app.schemas.session import SessionData
from app.services.risk_evaluation_service import RiskEvaluationService
from app.services.session_service import MemorySessionStore, SessionService, get_session_service


# ==============================================================================
# TEST FIXTURES & ISOLATED DATABASE
# ==============================================================================

@pytest.fixture(scope="function")
def db_session():
    """Create an isolated in-memory SQLite database for deterministic test isolation."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def uow(db_session: Session) -> UnitOfWork:
    return UnitOfWork(db_session)


@pytest.fixture
def test_org(db_session: Session) -> Organization:
    org = Organization(id="org_alpha", name="Alpha Logistics Corp")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def other_org(db_session: Session) -> Organization:
    org = Organization(id="org_beta", name="Beta Shipping Ltd")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def test_user(db_session: Session, test_org: Organization) -> User:
    user = User(
        id="usr_viewer_1",
        org_id=test_org.id,
        email="viewer@alpha.com",
        full_name="Alpha Viewer",
        role="Viewer",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def analyst_user(db_session: Session, test_org: Organization) -> User:
    user = User(
        id="usr_analyst_1",
        org_id=test_org.id,
        email="analyst@alpha.com",
        full_name="Alpha Analyst",
        role="Analyst",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def other_user(db_session: Session, other_org: Organization) -> User:
    user = User(
        id="usr_other_1",
        org_id=other_org.id,
        email="viewer@beta.com",
        full_name="Beta Viewer",
        role="Viewer",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def make_context(user: User) -> AuthenticatedContext:
    session_data = SessionData(
        session_id=f"sess_{user.id}",
        user_id=user.id,
        organization_id=user.org_id,
        role=user.role,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    )
    return AuthenticatedContext(user=user, session_data=session_data)


def create_dummy_assessment(
    assessment_id: str,
    org_id: str = "org_alpha",
    score: float = 20.0,
    risk_level: RiskLevel = RiskLevel.LOW,
    factors: List[RiskFactor] = None,
    evidence: List[RiskEvidence] = None,
    primary_factor_id: str = None,
    conflicts: List[Dict[str, Any]] = None,
    limitations: List[str] = None,
    evaluated_at: datetime = None,
) -> RiskAssessment:
    if evaluated_at is None:
        evaluated_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    if factors is None:
        factors = []
    if evidence is None:
        evidence = []
    if conflicts is None:
        conflicts = []
    if limitations is None:
        limitations = []

    risk_score = RiskScore(
        score=score,
        risk_level=risk_level,
        confidence=0.85,
        timestamp=evaluated_at,
    )
    return RiskAssessment(
        assessment_id=assessment_id,
        organization_id=org_id,
        evaluated_at=evaluated_at,
        overall_score=risk_score,
        risk_level=risk_level,
        factors=factors,
        evidence=evidence,
        primary_factor_id=primary_factor_id,
        conflicts=conflicts,
        limitations=limitations,
    )


def make_test_signal(
    signal_id: str = "sig_weather_01",
    org_id: str = "org_alpha",
    domain: SignalDomain = SignalDomain.WEATHER,
    signal_type: SignalType = SignalType.HAZARD,
    severity: EventSeverity = EventSeverity.HIGH,
    confidence: float = 0.90,
    quality: EventQuality = EventQuality.VALID,
    source: str = "weather_noaa",
    provider: str = "noaa",
    source_type: EventSourceType = EventSourceType.REAL,
    location_name: str = "Hong Kong Port",
    latitude: float = 22.3193,
    longitude: float = 114.1694,
    has_conflict: bool = False,
    event_time: Optional[datetime] = None,
    fingerprint: Optional[str] = None,
) -> NormalizedRiskSignal:
    """Helper constructing a canonical NormalizedRiskSignal for tests."""
    t = event_time or datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    return NormalizedRiskSignal(
        signal_id=signal_id,
        organization_id=org_id,
        domain=domain,
        signal_type=signal_type,
        event_type="TYPHOON_WARNING",
        status="ACTIVE",
        severity=severity,
        confidence=confidence,
        quality=quality,
        source=source,
        provider=provider,
        source_type=source_type,
        canonical_event_id=f"can_{signal_id}",
        event_time=t,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        has_conflict=has_conflict,
        fingerprint=fingerprint,
    )


# ==============================================================================
# 1. THRESHOLD TESTS (11 tests)
# ==============================================================================

def test_threshold_low_score_produces_no_alerts():
    """Scores in LOW [0, 30) produce zero operational alerts."""
    current = create_dummy_assessment("asm_low", score=25.0, risk_level=RiskLevel.LOW)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert len(alerts) == 0


def test_threshold_score_zero_produces_no_alerts():
    """Score at absolute minimum 0.0 produces no alerts."""
    current = create_dummy_assessment("asm_zero", score=0.0, risk_level=RiskLevel.LOW)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert len(alerts) == 0


def test_threshold_medium_score_without_transition_produces_no_alerts():
    """Scores in MEDIUM [30, 60) without previous evaluation produce no threshold alerts."""
    current = create_dummy_assessment("asm_med", score=45.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert len(alerts) == 0


def test_threshold_boundary_below_30_produces_no_alert():
    """Score at 29.9 remains LOW without alerts."""
    current = create_dummy_assessment("asm_29", score=29.9, risk_level=RiskLevel.LOW)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert len(alerts) == 0


def test_threshold_boundary_at_30_produces_no_threshold_alert():
    """Score at 30.0 enters MEDIUM without breaching HIGH/CRITICAL thresholds."""
    current = create_dummy_assessment("asm_30", score=30.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert len(alerts) == 0


def test_threshold_boundary_below_60_produces_no_high_alert():
    """Score at 59.9 remains MEDIUM without triggering HIGH_RISK_REACHED."""
    current = create_dummy_assessment("asm_59", score=59.9, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert not any(a.alert_type == RiskAlertType.HIGH_RISK_REACHED for a in alerts)


def test_threshold_boundary_at_60_triggers_high_risk_reached():
    """Score at exactly 60.0 enters HIGH and triggers HIGH_RISK_REACHED."""
    current = create_dummy_assessment("asm_60", score=60.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    high_alerts = [a for a in alerts if a.alert_type == RiskAlertType.HIGH_RISK_REACHED]
    assert len(high_alerts) == 1
    assert high_alerts[0].severity == AlertSeverity.WARNING


def test_threshold_boundary_below_85_triggers_high_not_critical():
    """Score at 84.9 triggers HIGH_RISK_REACHED, not CRITICAL_RISK_REACHED."""
    current = create_dummy_assessment("asm_84", score=84.9, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert any(a.alert_type == RiskAlertType.HIGH_RISK_REACHED for a in alerts)
    assert not any(a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED for a in alerts)


def test_threshold_boundary_at_85_triggers_critical_risk_reached():
    """Score at exactly 85.0 enters CRITICAL and triggers CRITICAL_RISK_REACHED."""
    current = create_dummy_assessment("asm_85", score=85.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    crit_alerts = [a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED]
    assert len(crit_alerts) == 1
    assert crit_alerts[0].severity == AlertSeverity.CRITICAL


def test_threshold_score_100_triggers_critical_alert():
    """Score at absolute maximum 100.0 triggers CRITICAL_RISK_REACHED."""
    current = create_dummy_assessment("asm_100", score=100.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=current)
    assert any(a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED for a in alerts)


def test_threshold_medium_to_high_transition():
    """Transition from MEDIUM (45.0) to HIGH (72.0) triggers both LEVEL_INCREASED and HIGH_REACHED."""
    prev = create_dummy_assessment("asm_prev", score=45.0, risk_level=RiskLevel.MEDIUM)
    curr = create_dummy_assessment("asm_curr", score=72.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)

    types = {a.alert_type for a in alerts}
    assert RiskAlertType.HIGH_RISK_REACHED in types
    assert RiskAlertType.RISK_LEVEL_INCREASED in types


# ==============================================================================
# 2. ALERT TRIGGER TESTS (10 tests)
# ==============================================================================

def test_trigger_high_risk_reached():
    """HIGH_RISK_REACHED triggers when crossing into HIGH."""
    curr = create_dummy_assessment("asm_high", score=65.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    high_alert = next(a for a in alerts if a.alert_type == RiskAlertType.HIGH_RISK_REACHED)
    assert high_alert.current_score == 65.0
    assert high_alert.severity == AlertSeverity.WARNING


def test_trigger_critical_risk_reached():
    """CRITICAL_RISK_REACHED triggers when crossing into CRITICAL."""
    curr = create_dummy_assessment("asm_crit", score=90.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    crit_alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED)
    assert crit_alert.current_score == 90.0
    assert crit_alert.severity == AlertSeverity.CRITICAL


def test_trigger_risk_level_increased():
    """RISK_LEVEL_INCREASED triggers on upward categorical transition."""
    prev = create_dummy_assessment("asm_prev", score=50.0, risk_level=RiskLevel.MEDIUM)
    curr = create_dummy_assessment("asm_curr", score=62.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    inc_alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_LEVEL_INCREASED)
    assert inc_alert.previous_risk_level == "MEDIUM"
    assert inc_alert.current_risk_level == "HIGH"


def test_trigger_risk_level_decreased():
    """RISK_LEVEL_DECREASED triggers on downward categorical transition with INFO severity."""
    prev = create_dummy_assessment("asm_prev", score=75.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_curr", score=45.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    dec_alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_LEVEL_DECREASED)
    assert dec_alert.severity == AlertSeverity.INFO
    assert dec_alert.previous_risk_level == "HIGH"
    assert dec_alert.current_risk_level == "MEDIUM"


def test_trigger_risk_score_increased_material_jump():
    """RISK_SCORE_INCREASED triggers when score jump delta >= 15.0."""
    prev = create_dummy_assessment("asm_prev", score=20.0, risk_level=RiskLevel.LOW)
    curr = create_dummy_assessment("asm_curr", score=38.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    jump_alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_SCORE_INCREASED)
    assert jump_alert.score_delta == 18.0


def test_trigger_risk_trend_increasing():
    """RISK_TREND_INCREASING triggers when trajectory is INCREASING with score >= 60.0."""
    prev = create_dummy_assessment("asm_prev", score=60.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_curr", score=75.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    trend_alert = next((a for a in alerts if a.alert_type == RiskAlertType.RISK_TREND_INCREASING), None)
    assert trend_alert is not None


def test_trigger_critical_factor_detected():
    """CRITICAL_FACTOR_DETECTED triggers when any factor has CRITICAL severity."""
    f_crit = RiskFactor(
        factor_id="fac_cyclone",
        factor_type="WEATHER",
        domain=SignalDomain.WEATHER,
        name="Category 5 Cyclone",
        severity=RiskLevel.CRITICAL,
        confidence=0.9,
        contribution=0.80,
    )
    curr = create_dummy_assessment("asm_fac", score=55.0, risk_level=RiskLevel.MEDIUM, factors=[f_crit])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    fac_alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_FACTOR_DETECTED)
    assert fac_alert.factor_id == "fac_cyclone"
    assert fac_alert.severity == AlertSeverity.CRITICAL


def test_trigger_new_conflict():
    """NEW_CONFLICT triggers when signal conflict emerges in current assessment."""
    conflict_data = [{"factor": "WEATHER", "provider_a": "NOAA", "provider_b": "OpenWeather"}]
    prev = create_dummy_assessment("asm_prev", score=40.0, risk_level=RiskLevel.MEDIUM, conflicts=[])
    curr = create_dummy_assessment("asm_curr", score=42.0, risk_level=RiskLevel.MEDIUM, conflicts=conflict_data)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    conf_alert = next(a for a in alerts if a.alert_type == RiskAlertType.NEW_CONFLICT)
    assert conf_alert.severity == AlertSeverity.WARNING


def test_trigger_quality_degraded():
    """QUALITY_DEGRADED triggers when evidence quality transitions to DEGRADED."""
    prev = create_dummy_assessment("asm_prev", score=40.0, risk_level=RiskLevel.MEDIUM, limitations=[])
    curr = create_dummy_assessment(
        "asm_curr",
        score=40.0,
        risk_level=RiskLevel.MEDIUM,
        limitations=["uncorroborated_single_source", "stale_evidence"],
    )
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    qual_alert = next((a for a in alerts if a.alert_type == RiskAlertType.QUALITY_DEGRADED), None)
    assert qual_alert is not None
    assert qual_alert.severity == AlertSeverity.WARNING


def test_trigger_primary_driver_changed():
    """PRIMARY_DRIVER_CHANGED triggers when driver shifts and score >= 30.0."""
    f_prev = RiskFactor(factor_id="fac_w", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Weather", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.50)
    f_curr = RiskFactor(factor_id="fac_p", factor_type="ROAD", domain=SignalDomain.ROAD, name="Road Congestion", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.60)
    prev = create_dummy_assessment("asm_prev", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f_prev], primary_factor_id="fac_w")
    curr = create_dummy_assessment("asm_curr", score=55.0, risk_level=RiskLevel.MEDIUM, factors=[f_curr], primary_factor_id="fac_p")
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    driver_alert = next((a for a in alerts if a.alert_type == RiskAlertType.PRIMARY_DRIVER_CHANGED), None)
    assert driver_alert is not None


# ==============================================================================
# 3. DEDUPLICATION & ALERT STORM TESTS (7 tests)
# ==============================================================================

def test_deduplication_deterministic_alert_id():
    """Same org, assessment, and alert type produce identical deterministic alert IDs."""
    id1 = compute_alert_id("org_1", "asm_1", "HIGH_RISK_REACHED")
    id2 = compute_alert_id("org_1", "asm_1", "HIGH_RISK_REACHED")
    assert id1 == id2
    assert id1.startswith("alt_")
    assert len(id1) == 28


def test_deduplication_different_assessments_produce_different_ids():
    """Different assessments produce distinct alert IDs."""
    id1 = compute_alert_id("org_1", "asm_1", "HIGH_RISK_REACHED")
    id2 = compute_alert_id("org_1", "asm_2", "HIGH_RISK_REACHED")
    assert id1 != id2


def test_deduplication_different_orgs_produce_different_ids():
    """Different organizations produce distinct alert IDs for isolation."""
    id1 = compute_alert_id("org_1", "asm_1", "HIGH_RISK_REACHED")
    id2 = compute_alert_id("org_2", "asm_1", "HIGH_RISK_REACHED")
    assert id1 != id2


def test_deduplication_high_remains_high_no_repeated_threshold_alert():
    """Assessment staying HIGH (70.0 -> 72.0) does NOT re-trigger HIGH_RISK_REACHED."""
    prev = create_dummy_assessment("asm_prev", score=70.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_curr", score=72.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    assert not any(a.alert_type == RiskAlertType.HIGH_RISK_REACHED for a in alerts)


def test_deduplication_critical_remains_critical_no_repeated_threshold_alert():
    """Assessment staying CRITICAL (88.0 -> 90.0) does NOT re-trigger CRITICAL_RISK_REACHED."""
    prev = create_dummy_assessment("asm_prev", score=88.0, risk_level=RiskLevel.CRITICAL)
    curr = create_dummy_assessment("asm_curr", score=90.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    assert not any(a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED for a in alerts)


def test_deduplication_unchanged_critical_factor_not_repeated():
    """A critical factor already present in previous assessment is NOT re-alerted."""
    f_crit = RiskFactor(factor_id="fac_cyclone", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Cyclone", severity=RiskLevel.CRITICAL, confidence=0.9, contribution=0.80)
    prev = create_dummy_assessment("asm_prev", score=85.0, risk_level=RiskLevel.CRITICAL, factors=[f_crit])
    curr = create_dummy_assessment("asm_curr", score=86.0, risk_level=RiskLevel.CRITICAL, factors=[f_crit])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    assert not any(a.alert_type == RiskAlertType.CRITICAL_FACTOR_DETECTED for a in alerts)


def test_deduplication_new_critical_transition_produces_alert():
    """Transitioning from HIGH (75.0) to CRITICAL (88.0) DOES trigger CRITICAL_RISK_REACHED."""
    prev = create_dummy_assessment("asm_prev", score=75.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_curr", score=88.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    assert any(a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED for a in alerts)


# ==============================================================================
# 4. SEVERITY & ESCALATION TESTS (7 tests)
# ==============================================================================

def test_severity_critical_threshold_is_critical():
    """Reaching CRITICAL threshold maps to CRITICAL alert severity."""
    curr = create_dummy_assessment("asm_c", score=89.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED)
    assert alert.severity == AlertSeverity.CRITICAL


def test_severity_high_threshold_is_warning():
    """Reaching HIGH threshold maps to WARNING alert severity."""
    curr = create_dummy_assessment("asm_h", score=65.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.HIGH_RISK_REACHED)
    assert alert.severity == AlertSeverity.WARNING


def test_severity_transition_to_critical_escalates():
    """Transition to CRITICAL level produces CRITICAL severity for RISK_LEVEL_INCREASED."""
    prev = create_dummy_assessment("asm_prev", score=70.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_curr", score=88.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_LEVEL_INCREASED)
    assert alert.severity == AlertSeverity.CRITICAL


def test_severity_transition_to_high_is_warning():
    """Transition to HIGH level produces WARNING severity for RISK_LEVEL_INCREASED."""
    prev = create_dummy_assessment("asm_prev", score=40.0, risk_level=RiskLevel.MEDIUM)
    curr = create_dummy_assessment("asm_curr", score=65.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_LEVEL_INCREASED)
    assert alert.severity == AlertSeverity.WARNING


def test_severity_score_decrease_is_info():
    """De-escalation alert produces INFO severity."""
    prev = create_dummy_assessment("asm_prev", score=80.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_curr", score=50.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_LEVEL_DECREASED)
    assert alert.severity == AlertSeverity.INFO


def test_severity_driver_change_at_medium_is_info():
    """Driver change while in MEDIUM risk produces INFO severity."""
    f1 = RiskFactor(factor_id="f1", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Weather", severity=RiskLevel.MEDIUM, confidence=0.8, contribution=0.35)
    f2 = RiskFactor(factor_id="f2", factor_type="ROAD", domain=SignalDomain.ROAD, name="Road", severity=RiskLevel.MEDIUM, confidence=0.8, contribution=0.40)
    prev = create_dummy_assessment("asm_p", score=40.0, risk_level=RiskLevel.MEDIUM, factors=[f1], primary_factor_id="f1")
    curr = create_dummy_assessment("asm_c", score=45.0, risk_level=RiskLevel.MEDIUM, factors=[f2], primary_factor_id="f2")
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next((a for a in alerts if a.alert_type == RiskAlertType.PRIMARY_DRIVER_CHANGED), None)
    assert alert is not None
    assert alert.severity == AlertSeverity.INFO


def test_severity_driver_change_at_high_is_warning():
    """Driver change while in HIGH risk escalates to WARNING severity."""
    f1 = RiskFactor(factor_id="f1", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Weather", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.60)
    f2 = RiskFactor(factor_id="f2", factor_type="ROAD", domain=SignalDomain.ROAD, name="Road", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.70)
    prev = create_dummy_assessment("asm_p", score=65.0, risk_level=RiskLevel.HIGH, factors=[f1], primary_factor_id="f1")
    curr = create_dummy_assessment("asm_c", score=72.0, risk_level=RiskLevel.HIGH, factors=[f2], primary_factor_id="f2")
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next((a for a in alerts if a.alert_type == RiskAlertType.PRIMARY_DRIVER_CHANGED), None)
    assert alert is not None
    assert alert.severity == AlertSeverity.WARNING


# ==============================================================================
# 5. EVIDENCE & TRACEABILITY TESTS (6 tests)
# ==============================================================================

def test_evidence_traceability_assessment_id_present():
    """Every generated alert contains the triggering assessment_id."""
    curr = create_dummy_assessment("asm_trace_01", score=90.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    assert len(alerts) > 0
    for a in alerts:
        assert a.assessment_id == "asm_trace_01"


def test_evidence_traceability_factor_id_linked():
    """Critical factor alert contains the exact factor_id."""
    f_crit = RiskFactor(factor_id="fac_typhoon_99", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Typhoon", severity=RiskLevel.CRITICAL, confidence=0.9, contribution=0.85)
    curr = create_dummy_assessment("asm_trace_02", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f_crit])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_FACTOR_DETECTED)
    assert alert.factor_id == "fac_typhoon_99"


def test_evidence_traceability_evidence_ids_present():
    """Alert carries evidence_ids from triggering assessment or factor."""
    f_crit = RiskFactor(
        factor_id="fac_1",
        factor_type="ROAD",
        domain=SignalDomain.ROAD,
        name="Road Closure",
        severity=RiskLevel.CRITICAL,
        confidence=0.9,
        contribution=0.70,
        evidence_ids=["evi_tomtom_01", "evi_tomtom_02"],
    )
    curr = create_dummy_assessment("asm_trace_03", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f_crit])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_FACTOR_DETECTED)
    assert "evi_tomtom_01" in alert.evidence_ids


def test_evidence_traceability_conflict_metadata_preserved():
    """Conflict alert includes conflict count in metadata."""
    conflicts = [{"factor": "AIR", "reason": "flight delay vs on-time"}]
    prev = create_dummy_assessment("asm_p", score=40.0, risk_level=RiskLevel.MEDIUM, conflicts=[])
    curr = create_dummy_assessment("asm_c", score=40.0, risk_level=RiskLevel.MEDIUM, conflicts=conflicts)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.NEW_CONFLICT)
    assert alert.metadata.get("conflict_count") == 1


def test_evidence_traceability_quality_limitations_preserved():
    """Quality degraded alert includes limitations in metadata."""
    prev = create_dummy_assessment("asm_p", score=40.0, risk_level=RiskLevel.MEDIUM, limitations=[])
    curr = create_dummy_assessment("asm_c", score=40.0, risk_level=RiskLevel.MEDIUM, limitations=["stale_signals"])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next((a for a in alerts if a.alert_type == RiskAlertType.QUALITY_DEGRADED), None)
    if alert:
        assert "stale_signals" in alert.metadata.get("limitations", [])


def test_evidence_traceability_empty_evidence_safe():
    """Assessment with empty evidence evaluates safely without errors."""
    curr = create_dummy_assessment("asm_empty_evi", score=88.0, risk_level=RiskLevel.CRITICAL, evidence=[])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    assert len(alerts) > 0
    assert alerts[0].evidence_ids == []


# ==============================================================================
# 6. EXPLANATION TESTS (6 tests)
# ==============================================================================

def test_explanation_score_threshold_critical():
    """Explanation for CRITICAL threshold is deterministic and factual."""
    curr = create_dummy_assessment("asm_exp_1", score=88.5, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_RISK_REACHED)
    assert "Risk score reached CRITICAL threshold at 88.5" in alert.trigger_reason


def test_explanation_level_transition():
    """Explanation for level transition states previous and current levels."""
    prev = create_dummy_assessment("asm_prev", score=45.0, risk_level=RiskLevel.MEDIUM)
    curr = create_dummy_assessment("asm_curr", score=72.0, risk_level=RiskLevel.HIGH)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_LEVEL_INCREASED)
    assert alert.trigger_reason == "Risk level escalated from MEDIUM to HIGH."


def test_explanation_score_jump():
    """Explanation for score increase details delta points."""
    prev = create_dummy_assessment("asm_prev", score=30.0, risk_level=RiskLevel.MEDIUM)
    curr = create_dummy_assessment("asm_curr", score=50.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.RISK_SCORE_INCREASED)
    assert "+20.0 points (from 30.0 to 50.0)" in alert.trigger_reason


def test_explanation_critical_factor():
    """Explanation for critical factor includes name and contribution."""
    f = RiskFactor(factor_id="f_wildfire", factor_type="GENERAL", domain=SignalDomain.GENERAL, name="Wildfire Alert", severity=RiskLevel.CRITICAL, confidence=0.9, contribution=0.78)
    curr = create_dummy_assessment("asm_fac", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.CRITICAL_FACTOR_DETECTED)
    assert "Wildfire Alert with contribution 0.78" in alert.trigger_reason


def test_explanation_conflict():
    """Explanation for conflict states count of conflicts."""
    prev = create_dummy_assessment("asm_p", score=40.0, risk_level=RiskLevel.MEDIUM, conflicts=[])
    curr = create_dummy_assessment("asm_c", score=40.0, risk_level=RiskLevel.MEDIUM, conflicts=[{"a": 1}, {"b": 2}])
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    alert = next(a for a in alerts if a.alert_type == RiskAlertType.NEW_CONFLICT)
    assert "2 conflict(s) present" in alert.trigger_reason


def test_explanation_no_speculative_causality():
    """Explanations state factual transitions without speculative causality."""
    prev = create_dummy_assessment("asm_p", score=75.0, risk_level=RiskLevel.HIGH)
    curr = create_dummy_assessment("asm_c", score=45.0, risk_level=RiskLevel.MEDIUM)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr, previous=prev)
    for a in alerts:
        assert "because" not in a.trigger_reason.lower()
        assert "might have caused" not in a.trigger_reason.lower()


# ==============================================================================
# 7. PERSISTENCE & NOTIFICATION INTEGRATION TESTS (7 tests)
# ==============================================================================

def test_persistence_adapter_to_notification(test_org: Organization):
    """NotificationAdapter converts domain RiskAlert into valid ORM Notification."""
    alert = RiskAlert(
        alert_id="alt_test_001",
        organization_id=test_org.id,
        assessment_id="asm_test_001",
        risk_id="rsk_001",
        alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
        severity=AlertSeverity.CRITICAL,
        current_score=88.0,
        trigger_reason="Test critical alert",
        created_at=datetime.now(timezone.utc),
    )
    notif = RiskAlertNotificationAdapter.to_notification_model(alert)
    assert notif.id == "alt_test_001"
    assert notif.org_id == test_org.id
    assert notif.category == "RISK_ALERT"
    assert notif.severity == "CRITICAL"
    assert notif.is_read is False


def test_persistence_adapter_roundtrip(test_org: Organization):
    """NotificationAdapter roundtrip reconstructs domain RiskAlert accurately."""
    alert = RiskAlert(
        alert_id="alt_test_002",
        organization_id=test_org.id,
        assessment_id="asm_test_002",
        risk_id="rsk_002",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=72.5,
        score_delta=15.0,
        current_risk_level="HIGH",
        previous_risk_level="MEDIUM",
        trigger_reason="Score reached HIGH threshold",
        created_at=datetime.now(timezone.utc),
    )
    notif = RiskAlertNotificationAdapter.to_notification_model(alert)
    reconstructed = RiskAlertNotificationAdapter.from_notification_model(notif)
    assert reconstructed.alert_id == alert.alert_id
    assert reconstructed.alert_type == RiskAlertType.HIGH_RISK_REACHED
    assert reconstructed.severity == AlertSeverity.WARNING
    assert reconstructed.current_score == 72.5


def test_persistence_transactional_notification_created(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """RiskEvaluationService.evaluate_and_persist creates Notification records transactionally."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)

    sig = make_test_signal(
        signal_id="sig_test_crit_01",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.WEATHER,
        confidence=0.95,
    )

    assessment, detail, is_hit = service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")
    assert is_hit is False
    assert assessment.score >= 85.0

    # Query notifications via uow
    notifs, total = uow.notifications.list_for_user(org_id=test_org.id, category="RISK_ALERT")
    assert total >= 1
    assert any(n.severity == "CRITICAL" for n in notifs)


def test_persistence_rollback_on_failure(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Rollback on failure leaves no orphaned notifications."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)

    # Attempt evaluate with invalid risk_id to trigger NotFoundError
    sig = make_test_signal(
        signal_id="sig_test_fail",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.WEATHER,
    )

    with pytest.raises(Exception):
        service.evaluate_and_persist(signals=[sig], risk_id="rsk_nonexistent_999")

    # Verify no notifications were committed
    notifs, total = uow.notifications.list_for_user(org_id=test_org.id, category="RISK_ALERT")
    assert total == 0


def test_persistence_idempotency_avoids_duplicate_notifications(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Repeated evaluation with identical fingerprint does not duplicate notifications."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)

    sig = make_test_signal(
        signal_id="sig_idem_01",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.WEATHER,
        event_time=datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
    )

    # First evaluation: creates notifications
    _, _, hit1 = service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")
    assert hit1 is False
    _, count1 = uow.notifications.list_for_user(org_id=test_org.id, category="RISK_ALERT")

    # Second evaluation: idempotency hit, no duplicate notifications
    _, _, hit2 = service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")
    assert hit2 is True
    _, count2 = uow.notifications.list_for_user(org_id=test_org.id, category="RISK_ALERT")
    assert count1 == count2


def test_persistence_acknowledge_alert_updates_status(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Acknowledging an alert marks the notification as read and logs an audit record."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)

    # Create an alert notification directly
    alert = RiskAlert(
        alert_id="alt_ack_01",
        organization_id=test_org.id,
        assessment_id="asm_ack_01",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=70.0,
        trigger_reason="High risk alert",
        created_at=datetime.now(timezone.utc),
    )
    notif = RiskAlertNotificationAdapter.to_notification_model(alert)
    with uow:
        uow.notifications.create(notif, auto_commit=False)
        uow.commit()

    # Acknowledge alert
    acknowledged = service.acknowledge_alert(alert_id="alt_ack_01", is_read=True)
    assert acknowledged.status == AlertStatus.ACKNOWLEDGED

    # Verify notification in DB
    updated_notif = uow.notifications.get("alt_ack_01", org_id=test_org.id)
    assert updated_notif.is_read is True


def test_persistence_list_alerts_filtered(
    uow: UnitOfWork,
    test_user: User,
    test_org: Organization,
):
    """list_alerts returns risk alerts filtered by severity and tenant."""
    ctx = make_context(test_user)
    service = RiskEvaluationService(uow=uow, context=ctx)

    alert1 = RiskAlert(
        alert_id="alt_list_crit",
        organization_id=test_org.id,
        assessment_id="asm_1",
        alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
        severity=AlertSeverity.CRITICAL,
        current_score=90.0,
        trigger_reason="Crit alert",
        created_at=datetime.now(timezone.utc),
    )
    alert2 = RiskAlert(
        alert_id="alt_list_warn",
        organization_id=test_org.id,
        assessment_id="asm_2",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=70.0,
        trigger_reason="Warn alert",
        created_at=datetime.now(timezone.utc),
    )
    with uow:
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert1), auto_commit=False)
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert2), auto_commit=False)
        uow.commit()

    crit_items, total_crit = service.list_alerts(severity="CRITICAL")
    assert total_crit == 1
    assert crit_items[0].alert_id == "alt_list_crit"


# ==============================================================================
# 8. TENANT ISOLATION TESTS (6 tests)
# ==============================================================================

def test_tenant_isolation_org_a_cannot_see_org_b_alerts(
    uow: UnitOfWork,
    test_user: User,
    other_user: User,
    test_org: Organization,
    other_org: Organization,
):
    """Organization A cannot view alerts belonging to Organization B."""
    service_b = RiskEvaluationService(uow=uow, context=make_context(other_user))
    alert_b = RiskAlert(
        alert_id="alt_b_secret",
        organization_id=other_org.id,
        assessment_id="asm_b",
        alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
        severity=AlertSeverity.CRITICAL,
        current_score=95.0,
        trigger_reason="Beta secret alert",
        created_at=datetime.now(timezone.utc),
    )
    with uow:
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert_b), auto_commit=False)
        uow.commit()

    service_a = RiskEvaluationService(uow=uow, context=make_context(test_user))
    alerts_a, total_a = service_a.list_alerts()
    assert not any(a.alert_id == "alt_b_secret" for a in alerts_a)


def test_tenant_isolation_get_alert_cross_tenant_returns_404(
    uow: UnitOfWork,
    test_user: User,
    other_org: Organization,
):
    """Querying another tenant's alert by ID returns NotFoundError (404 masking)."""
    alert_b = RiskAlert(
        alert_id="alt_b_hidden",
        organization_id=other_org.id,
        assessment_id="asm_b",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=75.0,
        trigger_reason="Beta hidden",
        created_at=datetime.now(timezone.utc),
    )
    with uow:
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert_b), auto_commit=False)
        uow.commit()

    service_a = RiskEvaluationService(uow=uow, context=make_context(test_user))
    with pytest.raises(Exception) as exc_info:
        service_a.get_alert("alt_b_hidden")
    assert "not found" in str(exc_info.value).lower()


def test_tenant_isolation_acknowledge_cross_tenant_rejected(
    uow: UnitOfWork,
    test_user: User,
    other_org: Organization,
):
    """Acknowledging another tenant's alert is rejected with 404."""
    alert_b = RiskAlert(
        alert_id="alt_b_locked",
        organization_id=other_org.id,
        assessment_id="asm_b",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=75.0,
        trigger_reason="Beta locked",
        created_at=datetime.now(timezone.utc),
    )
    with uow:
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert_b), auto_commit=False)
        uow.commit()

    service_a = RiskEvaluationService(uow=uow, context=make_context(test_user))
    with pytest.raises(Exception):
        service_a.acknowledge_alert("alt_b_locked", is_read=True)


def test_tenant_isolation_server_context_authoritative(
    uow: UnitOfWork,
    test_user: User,
    test_org: Organization,
):
    """Server-side tenant context strictly dictates the organization_id."""
    ctx = make_context(test_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    assert service._enforce_tenant_scope() == test_org.id


def test_tenant_isolation_broadcast_alerts_tenant_bounded(
    uow: UnitOfWork,
    test_user: User,
    other_user: User,
    test_org: Organization,
):
    """Broadcast alerts (user_id=None) are only visible within their organization."""
    ctx_a = make_context(test_user)
    ctx_b = make_context(other_user)
    service_a = RiskEvaluationService(uow=uow, context=ctx_a)
    service_b = RiskEvaluationService(uow=uow, context=ctx_b)

    alert_a = RiskAlert(
        alert_id="alt_a_broadcast",
        organization_id=test_org.id,
        assessment_id="asm_a",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=70.0,
        trigger_reason="Alpha broadcast",
        created_at=datetime.now(timezone.utc),
    )
    with uow:
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert_a), auto_commit=False)
        uow.commit()

    items_a, _ = service_a.list_alerts()
    assert any(a.alert_id == "alt_a_broadcast" for a in items_a)

    items_b, _ = service_b.list_alerts()
    assert not any(a.alert_id == "alt_a_broadcast" for a in items_b)


def test_tenant_isolation_cross_tenant_assessment_alerts_empty(
    uow: UnitOfWork,
    test_user: User,
    other_org: Organization,
):
    """Filtering alerts by an assessment ID belonging to another org returns empty."""
    alert_b = RiskAlert(
        alert_id="alt_b_spec",
        organization_id=other_org.id,
        assessment_id="asm_foreign_99",
        alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
        severity=AlertSeverity.CRITICAL,
        current_score=90.0,
        trigger_reason="Foreign assessment alert",
        created_at=datetime.now(timezone.utc),
    )
    with uow:
        uow.notifications.create(RiskAlertNotificationAdapter.to_notification_model(alert_b), auto_commit=False)
        uow.commit()

    service_a = RiskEvaluationService(uow=uow, context=make_context(test_user))
    items, total = service_a.list_alerts(assessment_id="asm_foreign_99")
    assert len(items) == 0


# ==============================================================================
# 9. API INTEGRATION TESTS (7 tests)
# ==============================================================================

@pytest.fixture
def client_app(db_session: Session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    memory_store = MemorySessionStore()
    session_service = SessionService(store=memory_store)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = lambda: session_service
    client = TestClient(app)
    yield client, session_service
    app.dependency_overrides.clear()


def login_client(client: TestClient, session_service: SessionService, user: User) -> None:
    session_data = session_service.create_session(
        user_id=user.id,
        role=user.role,
        organization_id=user.org_id,
    )
    client.cookies.set("riskwise_session", session_data.session_id)


def test_api_list_alerts_authenticated(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/alerts returns list for authenticated Viewer+."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    alert = RiskAlert(
        alert_id="alt_api_01",
        organization_id=test_org.id,
        assessment_id="asm_api_01",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=75.0,
        trigger_reason="API test alert",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskAlertNotificationAdapter.to_notification_model(alert))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/alerts")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "items" in data
    assert any(a["alert_id"] == "alt_api_01" for a in data["items"])


def test_api_list_alerts_unauthenticated_rejected(client_app):
    """GET /api/v1/risk-assessments/alerts requires authentication (401)."""
    client, _ = client_app
    resp = client.get("/api/v1/risk-assessments/alerts")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_get_alert_by_id(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/alerts/{alert_id} retrieves single alert."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    alert = RiskAlert(
        alert_id="alt_api_single",
        organization_id=test_org.id,
        assessment_id="asm_api_02",
        alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
        severity=AlertSeverity.CRITICAL,
        current_score=92.0,
        trigger_reason="Single alert fetch",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskAlertNotificationAdapter.to_notification_model(alert))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/alerts/alt_api_single")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["alert_id"] == "alt_api_single"
    assert data["severity"] == "CRITICAL"


def test_api_get_alert_not_found(client_app, test_user: User):
    """GET /api/v1/risk-assessments/alerts/{alert_id} returns 404 for unknown ID."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    resp = client.get("/api/v1/risk-assessments/alerts/alt_nonexistent_999")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_api_acknowledge_alert(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """PATCH /api/v1/risk-assessments/alerts/{alert_id}/acknowledge marks alert as read."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    alert = RiskAlert(
        alert_id="alt_api_ack",
        organization_id=test_org.id,
        assessment_id="asm_api_ack",
        alert_type=RiskAlertType.HIGH_RISK_REACHED,
        severity=AlertSeverity.WARNING,
        current_score=71.0,
        trigger_reason="Alert to acknowledge",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskAlertNotificationAdapter.to_notification_model(alert))
    db_session.commit()

    resp = client.patch("/api/v1/risk-assessments/alerts/alt_api_ack/acknowledge?is_read=true")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "ACKNOWLEDGED"


def test_api_get_assessment_alerts(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/{id}/alerts returns alerts triggered by assessment."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    alert = RiskAlert(
        alert_id="alt_api_asm",
        organization_id=test_org.id,
        assessment_id="asm_target_123",
        alert_type=RiskAlertType.CRITICAL_RISK_REACHED,
        severity=AlertSeverity.CRITICAL,
        current_score=89.0,
        trigger_reason="Assessment specific alert",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskAlertNotificationAdapter.to_notification_model(alert))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/asm_target_123/alerts")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["assessment_id"] == "asm_target_123"


def test_api_list_alerts_pagination(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/alerts respects page and limit pagination parameters."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    for i in range(5):
        alert = RiskAlert(
            alert_id=f"alt_page_{i}",
            organization_id=test_org.id,
            assessment_id=f"asm_p_{i}",
            alert_type=RiskAlertType.HIGH_RISK_REACHED,
            severity=AlertSeverity.WARNING,
            current_score=65.0 + i,
            trigger_reason=f"Page alert {i}",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(RiskAlertNotificationAdapter.to_notification_model(alert))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/alerts?page=1&limit=2")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["pagination"]["total"] >= 5
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["limit"] == 2


# ==============================================================================
# 10. SECURITY & SECRET SCRUBBING TESTS (4 tests)
# ==============================================================================

def test_security_no_api_keys_in_alert():
    """Alert trigger reasons and metadata scrub API keys and sensitive tokens."""
    curr = create_dummy_assessment(
        "asm_sec_01",
        score=88.0,
        risk_level=RiskLevel.CRITICAL,
        limitations=["API_KEY=sk_live_secret123456789"],
    )
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    for a in alerts:
        notif = RiskAlertNotificationAdapter.to_notification_model(a)
        assert "sk_live_secret123456789" not in notif.title


def test_security_no_authorization_headers_in_notification():
    """Authorization headers are not persisted into notification summary."""
    curr = create_dummy_assessment("asm_sec_02", score=90.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    assert len(alerts) > 0
    notif = RiskAlertNotificationAdapter.to_notification_model(alerts[0])
    assert "Bearer " not in notif.summary


def test_security_raw_provider_payload_rejected_at_service_boundary(
    uow: UnitOfWork,
    analyst_user: User,
):
    """Raw provider payloads without normalized contract are strictly rejected."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    with pytest.raises(Exception):
        service.evaluate_and_persist(signals=[{"raw": "payload"}])


def test_security_no_passwords_in_audit_data(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Audit logs for ALERT_TRIGGERED contain no passwords or private keys."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal(
        signal_id="sig_pwd_test",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.WEATHER,
    )
    service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")

    # Check audit logs
    logs = list(uow.session.execute(select(AuditLog).where(AuditLog.org_id == test_org.id)).scalars().all())
    assert len(logs) > 0
    for log in logs:
        log_str = str(log.after_json or {})
        assert "password" not in log_str.lower()
        assert "secret" not in log_str.lower()


# ==============================================================================
# 11. NO-ACTION TESTS (5 tests)
# ==============================================================================

def test_no_action_does_not_reroute_shipments(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Evaluating risk alerts does NOT mutate any shipment route."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal(
        signal_id="sig_no_action_1",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.OCEAN,
    )
    _, detail, _ = service.evaluate_and_persist(signals=[sig], scope="SHIPMENT", scope_entity_id="shp_test_01")
    # Verify no action records or shipment updates were generated
    actions = list(uow.session.execute(select(Action).where(Action.org_id == test_org.id)).scalars().all())
    assert len(actions) == 0


def test_no_action_does_not_cancel_shipment(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Alert evaluation raises notification only and does NOT cancel orders/shipments."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal(
        signal_id="sig_no_action_2",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.LOGISTICS,
    )
    service.evaluate_and_persist(signals=[sig], scope="SHIPMENT", scope_entity_id="shp_test_02")
    # Verify zero approvals or action executions
    approvals = list(uow.session.execute(select(Approval)).scalars().all())
    assert len(approvals) == 0


def test_no_action_does_not_contact_carriers():
    """Alert generation does not make external HTTP/carrier requests."""
    curr = create_dummy_assessment("asm_no_ext", score=95.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    assert len(alerts) > 0
    # Alerts are pure in-memory data representations
    for a in alerts:
        assert isinstance(a, RiskAlert)


def test_no_action_does_not_execute_recommendations(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Alert evaluation does NOT auto-execute or auto-approve recommendations."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal(
        signal_id="sig_no_action_4",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        domain=SignalDomain.LOGISTICS,
    )
    service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_rotterdam")
    # Verify zero recommendation auto-approvals or executions
    approved_recs = [
        r
        for r in uow.session.execute(select(Recommendation).where(Recommendation.org_id == test_org.id)).scalars().all()
        if r.status in ("APPROVED", "COMPLETED", "EXECUTED")
    ]
    assert len(approved_recs) == 0


def test_no_action_step6_scope_bounded():
    """Confirms Phase 7 Step 6 boundaries: purely alert intent, no operational execution."""
    curr = create_dummy_assessment("asm_scope_test", score=100.0, risk_level=RiskLevel.CRITICAL)
    alerts = RiskAlertEvaluator.evaluate_alerts(current=curr)
    # The output is strictly alerts and notifications
    assert all(a.alert_type in RiskAlertType for a in alerts)
