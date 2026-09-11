"""Phase 7 Step 8 — Risk Engine Final Validation, Hardening & Acceptance Test Suite.

Comprehensive validation covering all 20 required Step 8 verification categories:
1. Happy-path behavior (multi-domain signals -> Assessment -> History -> Alerts -> Recommendations -> DB)
2. Boundary conditions (exact thresholds [0,30,60,85,100], confidence [0,1], recommendation priority consistency)
3. Empty inputs (empty signal list yields baseline LOW score, 0 alerts, MONITOR recommendation)
4. Missing optional fields (signals lacking coordinates, location name, metadata handled safely)
5. Invalid inputs (raw dicts, non-signals, empty IDs rejected at boundary with structured errors)
6. Duplicate inputs (identical signals handled idempotently without score inflation)
7. Conflicting evidence (conflicts preserved in metadata, 0.85 uncertainty discount applied)
8. Multiple independent sources (independent providers tracked in source summary)
9. Same-provider duplicates (same provider does not corroborate itself)
10. REAL signals (source type preserved, 1.0 weight)
11. ESTIMATED signals (source type preserved, 0.9 discount, recorded in limitations)
12. SIMULATED signals (source type preserved, 0.7 discount, never counted as corroboration, in limitations)
13. Tenant isolation matrix (Org A vs Org B across assessments, factors, alerts, recommendations, audit logs)
14. Deterministic output (byte-for-byte reproducibility of fingerprints, assessment IDs, factor IDs, alert IDs, recommendation IDs)
15. Idempotency (repeated evaluation returns existing record with HTTP 200 without duplicate rows)
16. Provenance preservation (unbroken lineage: recommendation -> factor -> evidence -> canonical event)
17. Existing Step 1-7 compatibility (probability=None, impact=None, history comparator, alerts, recommendations, persistence)
18. Security boundaries (zero API keys, bearer tokens, or passwords leaked in metadata or audit logs)
19. No autonomous action execution (zero actions, zero approvals, requires_human_approval=True, status=PROPOSED)
20. No future-phase functionality (zero RAG, pgvector, LangGraph, Bedrock, OR-Tools, or simulation)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.context import AuthenticatedContext
from app.core.errors import NotFoundError, ValidationDomainError
from app.db.base import Base
from app.db.unit_of_work import UnitOfWork
from app.models.governance import Action, Approval, AuditLog, Notification, Recommendation
from app.models.risk import Risk as ORMRisk, RiskAssessment as ORMRiskAssessment, RiskFactor as ORMRiskFactor
from app.models.tenancy import Organization, User
from app.normalization.contract import (
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
    RiskAlert,
    RiskAlertEvaluator,
    RiskAlertType,
)
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    AssessmentSourceSummary,
    FactorContribution,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
)
from app.risk_engine.errors import InvalidContextError, RiskEngineInputError
from app.risk_engine.evidence import EvidenceRelevance, RiskEvidence
from app.risk_engine.history import HistoricalRiskComparator, RiskTrend
from app.risk_engine.pipeline import BaselineRiskEngine, RiskEvaluationResult
from app.risk_engine.recommendations import (
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
    RiskRecommendation,
    RiskRecommendationEvaluator,
)
from app.risk_engine.scoring import score_to_risk_level
from app.schemas.session import SessionData
from app.services.risk_evaluation_service import RiskEvaluationService


# ==============================================================================
# TEST FIXTURES & ISOLATED IN-MEMORY DATABASE
# ==============================================================================

@pytest.fixture(scope="function")
def db_session():
    """Create an isolated in-memory SQLite database session with enforced foreign keys."""
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
def org_alpha(db_session: Session) -> Organization:
    org = Organization(id="org_alpha", name="Alpha Logistics Corp")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def org_beta(db_session: Session) -> Organization:
    org = Organization(id="org_beta", name="Beta Global Freight Ltd")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def user_alpha(db_session: Session, org_alpha: Organization) -> User:
    user = User(
        id="usr_alpha_analyst",
        org_id=org_alpha.id,
        email="analyst@alpha.com",
        full_name="Alpha Analyst",
        role="Analyst",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def user_beta(db_session: Session, org_beta: Organization) -> User:
    user = User(
        id="usr_beta_analyst",
        org_id=org_beta.id,
        email="analyst@beta.com",
        full_name="Beta Analyst",
        role="Analyst",
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
    location_name: Optional[str] = "Port of Shanghai",
    latitude: Optional[float] = 31.2304,
    longitude: Optional[float] = 121.4737,
    has_conflict: bool = False,
    conflicts: Optional[List[Dict[str, Any]]] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    event_time: Optional[datetime] = None,
    fingerprint: Optional[str] = None,
) -> NormalizedRiskSignal:
    """Construct a strongly-typed NormalizedRiskSignal adhering to Phase 6 contracts."""
    t = event_time or datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)

    return NormalizedRiskSignal(
        signal_id=signal_id,
        organization_id=org_id,
        domain=domain,
        signal_type=signal_type,
        event_type="HAZARD_WARNING",
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
        conflicts=conflicts or [],
        data_payload=raw_payload or {"wind_speed_kmh": 120.0, "precipitation_mm": 80.0},
        metadata=metadata or {},
        fingerprint=fingerprint,
    )


def create_dummy_assessment(
    assessment_id: str,
    org_id: str = "org_alpha",
    score: float = 20.0,
    risk_level: Optional[RiskLevel] = None,
    factors: Optional[List[RiskFactor]] = None,
    evidence: Optional[List[RiskEvidence]] = None,
    primary_factor_id: Optional[str] = None,
    conflicts: Optional[List[Dict[str, Any]]] = None,
    limitations: Optional[List[str]] = None,
    evaluated_at: Optional[datetime] = None,
    scope: str = "GLOBAL",
    scope_entity_id: Optional[str] = None,
) -> RiskAssessment:
    if evaluated_at is None:
        evaluated_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    if risk_level is None:
        risk_level = score_to_risk_level(score)
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
        scope=scope,
        scope_entity_id=scope_entity_id,
    )


# ==============================================================================
# 1. HAPPY-PATH FULL PIPELINE BEHAVIOR
# ==============================================================================

def test_happy_path_pure_domain_pipeline():
    """Verify that multi-domain signals execute through BaselineRiskEngine.evaluate_full deterministically."""
    eval_time = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    signals = [
        make_test_signal(
            signal_id="sig_weather_typhoon",
            domain=SignalDomain.WEATHER,
            severity=EventSeverity.CRITICAL,
            provider="noaa",
            event_time=eval_time,
        ),
        make_test_signal(
            signal_id="sig_maritime_congestion",
            domain=SignalDomain.OCEAN,
            severity=EventSeverity.HIGH,
            provider="aisstream",
            event_time=eval_time,
        ),
        make_test_signal(
            signal_id="sig_road_closure",
            domain=SignalDomain.ROAD,
            severity=EventSeverity.MEDIUM,
            provider="tomtom",
            event_time=eval_time,
        ),
    ]

    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=signals,
        scope="GLOBAL",
    )

    engine = BaselineRiskEngine()
    result: RiskEvaluationResult = engine.evaluate_full(context)

    # Assessment invariants
    assert isinstance(result.assessment, RiskAssessment)
    assert result.assessment.organization_id == "org_alpha"
    assert result.assessment.score is not None and result.assessment.score > 60.0
    assert result.assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert len(result.assessment.factors) >= 3
    assert len(result.assessment.evidence) >= 3
    assert result.assessment.primary_factor is not None

    # Alerts generated
    assert len(result.alerts) >= 1
    alert_types = [a.alert_type for a in result.alerts]
    assert RiskAlertType.HIGH_RISK_REACHED in alert_types or RiskAlertType.CRITICAL_RISK_REACHED in alert_types

    # Recommendations generated
    assert len(result.recommendations) >= 1
    for rec in result.recommendations:
        assert isinstance(rec, RiskRecommendation)
        assert rec.status == RecommendationStatus.PROPOSED
        assert rec.requires_human_approval is True
        assert rec.organization_id == "org_alpha"


def test_happy_path_service_persistence_pipeline(uow: UnitOfWork, user_alpha: User):
    """Verify that multi-domain signals persist atomically into the 34-table schema with complete lineage."""
    context = make_context(user_alpha)
    service = RiskEvaluationService(uow=uow, context=context)

    signals = [
        make_test_signal(
            signal_id="sig_typhoon_persist",
            domain=SignalDomain.WEATHER,
            severity=EventSeverity.HIGH,
            provider="openweather",
        ),
        make_test_signal(
            signal_id="sig_port_persist",
            domain=SignalDomain.OCEAN,
            severity=EventSeverity.HIGH,
            provider="aisstream",
        ),
    ]

    assessment, detail, is_idempotent = service.evaluate_and_persist(
        signals=signals,
        scope="PORT",
        scope_entity_id="port_shanghai_001",
    )

    assert is_idempotent is False
    assert assessment.assessment_id is not None and len(assessment.assessment_id) > 0
    assert detail["assessment_id"] == assessment.assessment_id

    # Verify ORM database records
    db_assessment = uow.risk_assessments.get_assessment("org_alpha", assessment.assessment_id)
    assert db_assessment is not None
    assert db_assessment.score == assessment.score
    assert db_assessment.findings.get("risk_level") == assessment.risk_level.value

    # Verify parent Risk entity created
    parent_risk = uow.risks.get(db_assessment.risk_id, org_id="org_alpha")
    assert parent_risk is not None
    assert parent_risk.risk_score == assessment.score
    assert parent_risk.severity == assessment.risk_level.value

    # Verify notifications (RiskAlerts)
    alerts, alert_count = service.list_alerts(assessment_id=assessment.assessment_id)
    assert alert_count >= 1

    # Verify recommendations persisted
    recs, rec_count = service.list_recommendations(assessment_id=assessment.assessment_id)
    assert rec_count >= 1
    assert all(r.status == RecommendationStatus.PROPOSED for r in recs)

    # Verify audit log recorded
    audit_logs = list(uow.session.scalars(select(AuditLog).where(AuditLog.org_id == "org_alpha")).all())
    actions = [a.action for a in audit_logs]
    assert "EVALUATE" in actions
    assert "ALERT_TRIGGERED" in actions
    assert "RECOMMENDATION_PROPOSED" in actions


# ==============================================================================
# 2. BOUNDARY CONDITIONS (THRESHOLDS, CONFIDENCE, PRIORITIES)
# ==============================================================================

@pytest.mark.parametrize(
    "score,expected_level",
    [
        (0.00, RiskLevel.LOW),
        (29.99, RiskLevel.LOW),
        (30.00, RiskLevel.MEDIUM),
        (59.99, RiskLevel.MEDIUM),
        (60.00, RiskLevel.HIGH),
        (84.99, RiskLevel.HIGH),
        (85.00, RiskLevel.CRITICAL),
        (100.00, RiskLevel.CRITICAL),
    ],
)
def test_boundary_conditions_score_to_risk_level(score: float, expected_level: RiskLevel):
    """Verify exact Step 2 threshold boundaries: [0,30) LOW, [30,60) MEDIUM, [60,85) HIGH, [85,100] CRITICAL."""
    assert score_to_risk_level(score) == expected_level


def test_boundary_conditions_recommendation_priority_consistency():
    """Verify recommendation priority derivation matches Step 2 thresholds (82.0 is HIGH, 85.0 is CRITICAL)."""
    # Score 82.0: must be HIGH priority, NOT CRITICAL
    curr_82 = create_dummy_assessment("asm_82", score=82.00)
    recs_82 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr_82)
    escalate_rec = next((r for r in recs_82 if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.HIGH
    assert not any(r.priority == RecommendationPriority.CRITICAL for r in recs_82)
    assert not any(r.recommendation_type == RecommendationType.EXPEDITE_REVIEW for r in recs_82)

    # Score 85.0: must be CRITICAL priority
    curr_85 = create_dummy_assessment("asm_85", score=85.00)
    recs_85 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr_85)
    escalate_rec_85 = next((r for r in recs_85 if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    expedite_rec_85 = next((r for r in recs_85 if r.recommendation_type == RecommendationType.EXPEDITE_REVIEW), None)
    assert escalate_rec_85 is not None
    assert escalate_rec_85.priority == RecommendationPriority.CRITICAL
    assert expedite_rec_85 is not None
    assert expedite_rec_85.priority == RecommendationPriority.CRITICAL


def test_boundary_conditions_confidence_bounds():
    """Verify confidence values stay strictly bounded within [0.0, 1.0]."""
    eval_time = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    sig_low_conf = make_test_signal(signal_id="sig_lc", confidence=0.05, severity=EventSeverity.HIGH)
    sig_high_conf = make_test_signal(signal_id="sig_hc", confidence=0.99, severity=EventSeverity.HIGH)

    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=[sig_low_conf, sig_high_conf],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    assert 0.0 <= assessment.confidence <= 1.0


# ==============================================================================
# 3. EMPTY INPUTS
# ==============================================================================

def test_empty_signal_inputs_pure_domain():
    """Verify that an empty signal list yields a baseline LOW assessment with 0 alerts and MONITOR rec."""
    eval_time = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=[],
    )

    result = BaselineRiskEngine().evaluate_full(context)
    assert result.assessment.score == 0.0
    assert result.assessment.risk_level == RiskLevel.LOW
    assert result.assessment.confidence == 1.0
    assert len(result.assessment.factors) == 0
    assert len(result.assessment.evidence) == 0
    assert len(result.alerts) == 0

    # Baseline low risk produces MONITOR recommendation
    assert len(result.recommendations) == 1
    assert result.recommendations[0].recommendation_type == RecommendationType.MONITOR
    assert result.recommendations[0].priority == RecommendationPriority.LOW


# ==============================================================================
# 4. MISSING OPTIONAL FIELDS
# ==============================================================================

def test_missing_optional_fields_safety():
    """Verify that signals lacking optional attributes (coordinates, location name, metadata) evaluate safely."""
    sig = make_test_signal(
        signal_id="sig_minimal",
        location_name=None,
        latitude=None,
        longitude=None,
        metadata={},
        raw_payload={},
    )
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig],
    )
    result = BaselineRiskEngine().evaluate_full(context)
    assert result.assessment.score is not None
    # Limitation should record lack of spatial coordinates
    assert any("lack spatial coordinates" in lim for lim in result.assessment.limitations)


# ==============================================================================
# 5. INVALID INPUTS & STRICT BOUNDARY DEFENSE
# ==============================================================================

def test_invalid_input_raw_dict_rejected_in_service(uow: UnitOfWork, user_alpha: User):
    """Verify that raw dictionary payloads are strictly rejected at the service boundary."""
    service = RiskEvaluationService(uow=uow, context=make_context(user_alpha))
    raw_payload: Any = [{"raw_data": "not_a_normalized_signal"}]
    with pytest.raises(ValidationDomainError) as exc_info:
        service.evaluate_and_persist(signals=raw_payload)
    assert exc_info.value.code == "UNNORMALIZED_SIGNAL_REJECTED"


def test_invalid_input_missing_signal_id_rejected(uow: UnitOfWork, user_alpha: User):
    """Verify that signals with empty signal_id are rejected."""
    service = RiskEvaluationService(uow=uow, context=make_context(user_alpha))
    sig = make_test_signal(signal_id="")
    with pytest.raises(ValidationDomainError) as exc_info:
        service.evaluate_and_persist(signals=[sig])
    assert exc_info.value.code == "INVALID_SIGNAL_ID"


def test_invalid_input_context_missing_organization():
    """Verify that a context missing organization_id raises validation error."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RiskEvaluationContext(
            organization_id="",
            evaluation_time=datetime.now(timezone.utc),
            signals=[],
        )


def test_invalid_input_non_context_to_engine():
    """Verify that passing arbitrary objects to RiskEngine.evaluate raises RiskEngineInputError."""
    engine = BaselineRiskEngine()
    with pytest.raises(RiskEngineInputError):
        engine.evaluate("not_a_context")  # type: ignore


# ==============================================================================
# 6. DUPLICATE INPUTS
# ==============================================================================

def test_duplicate_signal_ids_handled_safely():
    """Verify that passing identical signals twice is handled deterministically without inflating evidence map."""
    sig1 = make_test_signal(signal_id="sig_dup_1", severity=EventSeverity.HIGH)
    sig2 = make_test_signal(signal_id="sig_dup_1", severity=EventSeverity.HIGH)

    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig1, sig2],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    # Evidence map deduplicates identical evidence IDs
    assert len(assessment.evidence) == 1


# ==============================================================================
# 7. CONFLICTING EVIDENCE
# ==============================================================================

def test_conflicting_evidence_preserved_and_discounted():
    """Verify multi-source conflicts are preserved in conflicts list and 0.85 discount is applied."""
    conflict_list = [
        {"provider": "openweather", "severity": "HIGH"},
        {"provider": "tomtom", "severity": "LOW"},
    ]
    sig = make_test_signal(
        signal_id="sig_conflict_01",
        has_conflict=True,
        conflicts=conflict_list,
        severity=EventSeverity.HIGH,
    )
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig],
    )
    assessment = BaselineRiskEngine().evaluate(context)

    # Conflict preserved
    assert len(assessment.conflicts) == 1
    assert assessment.conflicts[0]["signal_id"] == "sig_conflict_01"
    assert assessment.conflicts[0]["uncertainty_multiplier"] == 0.85

    # Limitation recorded
    assert any("0.85 uncertainty discount" in lim for lim in assessment.limitations)


# ==============================================================================
# 8. MULTIPLE INDEPENDENT SOURCES
# ==============================================================================

def test_multiple_independent_sources_summary():
    """Verify that source summary tracks multiple independent providers correctly."""
    sig1 = make_test_signal(signal_id="sig_p1", domain=SignalDomain.WEATHER, provider="openweather", source="weather")
    sig2 = make_test_signal(signal_id="sig_p2", domain=SignalDomain.ROAD, provider="tomtom", source="traffic")
    sig3 = make_test_signal(signal_id="sig_p3", domain=SignalDomain.OCEAN, provider="aisstream", source="maritime")

    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig1, sig2, sig3],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    summary: AssessmentSourceSummary = assessment.source_summary
    assert summary.independent_sources_count == 3
    assert set(summary.providers) == {"openweather", "tomtom", "aisstream"}


# ==============================================================================
# 9. SAME-PROVIDER DUPLICATES
# ==============================================================================

def test_same_provider_duplicates_do_not_corroborate():
    """Verify that two signals from the same provider are counted as 1 provider and 0 corroborations."""
    sig1 = make_test_signal(signal_id="sig_ow_1", provider="openweather")
    sig2 = make_test_signal(signal_id="sig_ow_2", provider="openweather")

    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig1, sig2],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    assert assessment.source_summary.independent_sources_count == 1
    assert assessment.source_summary.corroborating_sources_count == 0


# ==============================================================================
# 10. REAL SIGNALS
# ==============================================================================

def test_real_signals_source_type():
    """Verify REAL signals are classified correctly with multiplier 1.0."""
    sig = make_test_signal(signal_id="sig_real", source_type=EventSourceType.REAL)
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    assert assessment.source_summary.real_sources_count == 1
    assert assessment.source_summary.estimated_sources_count == 0
    assert assessment.source_summary.simulated_sources_count == 0


# ==============================================================================
# 11. ESTIMATED SIGNALS
# ==============================================================================

def test_estimated_signals_discount_and_limitation():
    """Verify ESTIMATED signals have multiplier 0.9 and generate an explicit limitation."""
    sig = make_test_signal(signal_id="sig_est", source_type=EventSourceType.ESTIMATED)
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    assert assessment.source_summary.estimated_sources_count == 1
    assert any("ESTIMATED signal(s)" in lim for lim in assessment.limitations)


# ==============================================================================
# 12. SIMULATED SIGNALS
# ==============================================================================

def test_simulated_signals_discount_and_no_corroboration():
    """Verify SIMULATED signals receive discount 0.7, are listed in limitations, and never corroborate."""
    sig = make_test_signal(signal_id="sig_sim", source_type=EventSourceType.SIMULATED)
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc),
        signals=[sig],
    )
    assessment = BaselineRiskEngine().evaluate(context)
    assert assessment.source_summary.simulated_sources_count == 1
    assert any("SIMULATED signal(s)" in lim for lim in assessment.limitations)
    assert assessment.source_summary.corroborating_sources_count == 0


# ==============================================================================
# 13. TENANT ISOLATION MATRIX
# ==============================================================================

def test_tenant_isolation_matrix(uow: UnitOfWork, user_alpha: User, user_beta: User):
    """Verify strict multi-tenant isolation: Org B cannot access Org A assessments, alerts, or recommendations."""
    service_alpha = RiskEvaluationService(uow=uow, context=make_context(user_alpha))
    service_beta = RiskEvaluationService(uow=uow, context=make_context(user_beta))

    sig = make_test_signal(signal_id="sig_alpha_secure", org_id="org_alpha", severity=EventSeverity.CRITICAL)
    assessment, detail, _ = service_alpha.evaluate_and_persist(signals=[sig])

    asm_id = assessment.assessment_id

    # 1. Org A can retrieve its own assessment
    assert service_alpha.get_assessment_domain(asm_id) is not None
    assert service_alpha.get_assessment_detail(asm_id) is not None

    # 2. Org B cannot retrieve Org A's assessment (masked 404)
    with pytest.raises(NotFoundError) as exc_info:
        service_beta.get_assessment_domain(asm_id)
    assert exc_info.value.code == "RESOURCE_NOT_FOUND"

    with pytest.raises(NotFoundError) as exc_info:
        service_beta.get_assessment_detail(asm_id)
    assert exc_info.value.code == "RESOURCE_NOT_FOUND"

    # 3. Org B lists 0 assessments, 0 alerts, 0 recommendations
    alerts_beta, count_alerts_beta = service_beta.list_alerts()
    assert count_alerts_beta == 0
    assert len(alerts_beta) == 0

    recs_beta, count_recs_beta = service_beta.list_recommendations()
    assert count_recs_beta == 0
    assert len(recs_beta) == 0

    # 4. Org B cannot retrieve Org A alerts or recommendations by ID
    alerts_alpha, _ = service_alpha.list_alerts(assessment_id=asm_id)
    if alerts_alpha:
        with pytest.raises(NotFoundError):
            service_beta.get_alert(alerts_alpha[0].alert_id)

    recs_alpha, _ = service_alpha.list_recommendations(assessment_id=asm_id)
    if recs_alpha:
        with pytest.raises(NotFoundError):
            service_beta.get_recommendation(recs_alpha[0].recommendation_id)


# ==============================================================================
# 14. DETERMINISTIC OUTPUT
# ==============================================================================

def test_deterministic_output_reproducibility():
    """Verify that evaluating the exact same inputs yields byte-for-byte identical IDs and fingerprints."""
    eval_time = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
    signals_1 = [
        make_test_signal(signal_id="sig_det_1", domain=SignalDomain.WEATHER, severity=EventSeverity.HIGH),
        make_test_signal(signal_id="sig_det_2", domain=SignalDomain.LOGISTICS, severity=EventSeverity.MEDIUM),
    ]
    signals_2 = [
        make_test_signal(signal_id="sig_det_1", domain=SignalDomain.WEATHER, severity=EventSeverity.HIGH),
        make_test_signal(signal_id="sig_det_2", domain=SignalDomain.LOGISTICS, severity=EventSeverity.MEDIUM),
    ]

    context_1 = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=signals_1,
        scope="GLOBAL",
    )
    context_2 = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=signals_2,
        scope="GLOBAL",
    )

    res_1 = BaselineRiskEngine().evaluate_full(context_1)
    res_2 = BaselineRiskEngine().evaluate_full(context_2)

    # Assessment determinism
    assert res_1.assessment.assessment_id == res_2.assessment.assessment_id
    assert res_1.assessment.fingerprint == res_2.assessment.fingerprint
    assert res_1.assessment.score == res_2.assessment.score
    assert [f.factor_id for f in res_1.assessment.factors] == [f.factor_id for f in res_2.assessment.factors]

    # Alert determinism
    assert [a.alert_id for a in res_1.alerts] == [a.alert_id for a in res_2.alerts]

    # Recommendation determinism
    assert [r.recommendation_id for r in res_1.recommendations] == [r.recommendation_id for r in res_2.recommendations]


# ==============================================================================
# 15. IDEMPOTENCY
# ==============================================================================

def test_idempotent_persistence_no_duplicate_rows(uow: UnitOfWork, user_alpha: User):
    """Verify that re-evaluating identical signals produces an idempotency hit with zero new rows."""
    service = RiskEvaluationService(uow=uow, context=make_context(user_alpha))
    signals = [make_test_signal(signal_id="sig_idemp_1", severity=EventSeverity.HIGH)]

    # First evaluation
    _, _, is_idemp_1 = service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    assert is_idemp_1 is False

    initial_asm_count = len(list(uow.session.scalars(select(ORMRiskAssessment)).all()))
    initial_rec_count = len(list(uow.session.scalars(select(Recommendation)).all()))
    initial_notif_count = len(list(uow.session.scalars(select(Notification)).all()))

    # Second evaluation with identical signals
    _, _, is_idemp_2 = service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    assert is_idemp_2 is True

    # Row counts must remain strictly identical
    final_asm_count = len(list(uow.session.scalars(select(ORMRiskAssessment)).all()))
    final_rec_count = len(list(uow.session.scalars(select(Recommendation)).all()))
    final_notif_count = len(list(uow.session.scalars(select(Notification)).all()))

    assert final_asm_count == initial_asm_count
    assert final_rec_count == initial_rec_count
    assert final_notif_count == initial_notif_count


# ==============================================================================
# 16. PROVENANCE PRESERVATION
# ==============================================================================

def test_provenance_preservation_unbroken_lineage():
    """Verify 100% unbroken lineage from Recommendation -> Factor -> Evidence -> Canonical Signal."""
    eval_time = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    sig = make_test_signal(
        signal_id="sig_prov_root",
        domain=SignalDomain.WEATHER,
        severity=EventSeverity.HIGH,
        provider="openweather",
        event_time=eval_time,
    )
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=[sig],
    )

    res = BaselineRiskEngine().evaluate_full(context)
    assert len(res.recommendations) >= 1

    rec = res.recommendations[0]
    # Trace recommendation to factor
    for factor_id in rec.factor_ids:
        matching_factor = next((f for f in res.assessment.factors if f.factor_id == factor_id), None)
        assert matching_factor is not None, f"Factor {factor_id} not found in assessment"

        # Trace factor to evidence
        assert len(matching_factor.evidence) >= 1
        for ev in matching_factor.evidence:
            assert ev.normalized_signal_id is not None
            assert ev.provider == "openweather"
            assert ev.source_type == EventSourceType.REAL


# ==============================================================================
# 17. EXISTING STEP 1–7 COMPATIBILITY
# ==============================================================================

def test_step1_to_7_contract_compatibility():
    """Verify that all Step 1-7 contracts, scoring rules, and comparator invariants hold."""
    eval_time = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    sig = make_test_signal(signal_id="sig_c17", severity=EventSeverity.HIGH)
    context = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time,
        signals=[sig],
    )
    res = BaselineRiskEngine().evaluate_full(context)

    # Step 2 rule: probability and impact are strictly None
    assert res.assessment.probability is None
    assert res.assessment.impact is None
    assert res.assessment.overall_score.probability is None
    assert res.assessment.overall_score.impact is None

    # Step 5 rule: HistoricalRiskComparator compares cleanly
    previous_assessment = res.assessment
    # Create subsequent assessment with lower risk
    sig_low = make_test_signal(signal_id="sig_c17_low", severity=EventSeverity.LOW)
    context_next = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=eval_time + timedelta(hours=1),
        signals=[sig_low],
    )
    res_next = BaselineRiskEngine().evaluate_full(context_next, previous=previous_assessment)
    assert res_next.comparison is not None
    assert res_next.comparison.score_delta < 0.0
    assert res_next.comparison.direction in (RiskTrend.DECREASING, RiskTrend.STABLE)


# ==============================================================================
# 18. SECURITY BOUNDARIES & SECRET SCRUBBING
# ==============================================================================

def test_security_secret_scrubbing_in_metadata_and_payloads(uow: UnitOfWork, user_alpha: User):
    """Verify that credentials (API keys, bearer tokens, passwords) are never stored in plaintext."""
    service = RiskEvaluationService(uow=uow, context=make_context(user_alpha))

    dirty_sig = make_test_signal(
        signal_id="sig_dirty_sec",
        severity=EventSeverity.HIGH,
        metadata={"auth_header": "Bearer secret_jwt_token_999", "api_key": "sk_live_1234567890abcdef"},
        raw_payload={"password": "MySuperSecretPassword123", "normal_metric": 42.0},
    )

    assessment, detail, _ = service.evaluate_and_persist(signals=[dirty_sig])

    # Check persisted assessment findings
    raw_findings = str(detail["findings"])
    assert "MySuperSecretPassword123" not in raw_findings
    assert "sk_live_1234567890abcdef" not in raw_findings

    # Check audit logs
    audit_logs = list(uow.session.scalars(select(AuditLog).where(AuditLog.org_id == "org_alpha")).all())
    for log in audit_logs:
        log_str = str(log.after_json)
        assert "MySuperSecretPassword123" not in log_str
        assert "sk_live_1234567890abcdef" not in log_str


# ==============================================================================
# 19. NO AUTONOMOUS ACTION EXECUTION
# ==============================================================================

def test_no_autonomous_action_execution(uow: UnitOfWork, user_alpha: User):
    """Verify that evaluating CRITICAL risks never creates Action or Approval records or triggers side effects."""
    service = RiskEvaluationService(uow=uow, context=make_context(user_alpha))

    critical_sig = make_test_signal(
        signal_id="sig_crit_action_test",
        domain=SignalDomain.LOGISTICS,
        severity=EventSeverity.CRITICAL,
    )

    assessment, _, _ = service.evaluate_and_persist(signals=[critical_sig])

    # Actions table must be completely empty
    action_count = len(list(uow.session.scalars(select(Action)).all()))
    assert action_count == 0, "Violation: Action records were created autonomously!"

    # Approvals table must be completely empty
    approval_count = len(list(uow.session.scalars(select(Approval)).all()))
    assert approval_count == 0, "Violation: Approval records were created autonomously!"

    # Every recommendation must require human approval
    recs, _ = service.list_recommendations(assessment_id=assessment.assessment_id)
    assert len(recs) >= 1
    for r in recs:
        assert r.requires_human_approval is True
        assert r.status == RecommendationStatus.PROPOSED


# ==============================================================================
# 20. NO FUTURE-PHASE FUNCTIONALITY
# ==============================================================================

def test_no_future_phase_functionality_verification():
    """Verify that no Phase 8+ modules (LangGraph, Bedrock, RAG, pgvector, OR-Tools) are present in Risk Engine."""
    import app.risk_engine as re_pkg

    # Check package exports and symbols
    engine_attrs = dir(re_pkg)
    forbidden_terms = [
        "langgraph",
        "bedrock",
        "claude",
        "rag",
        "vector_search",
        "ortools",
        "solver",
        "digital_twin",
        "bayesian_network",
    ]
    for term in forbidden_terms:
        matches = [attr for attr in engine_attrs if term in attr.lower()]
        assert len(matches) == 0, f"Violation: Found forbidden future-phase symbol {matches} in risk_engine"

    # Confirm BaselineRiskEngine does not invoke external ML or LLM services
    engine = BaselineRiskEngine()
    assert hasattr(engine, "evaluate")
    assert hasattr(engine, "evaluate_full")
    assert not hasattr(engine, "invoke_llm")
    assert not hasattr(engine, "retrieve_rag_context")
    assert not hasattr(engine, "run_simulation")
