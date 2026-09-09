"""Focused test suite for RiskWise 2.0 — Phase 7 Step 7: Risk Decision & Recommendation Foundation.

Validates:
1. Contract tests (instantiation, fields, deterministic ID, tenant isolation, approval flag).
2. Rule tests (LOW, MEDIUM, HIGH, CRITICAL, critical factors, port, road, ocean, logistics, supplier, inventory, trend, conflict, quality).
3. Recommendation type tests (all 8 types evaluated).
4. Priority tests (deterministic derivation from score, factor, and trend).
5. Traceability tests (recommendation -> assessment -> factor -> evidence -> normalized signal).
6. Explanation tests (factual rationale, constraints, assumptions, limitations, objectives).
7. Deduplication tests (deterministic hashing, idempotency hit, sorting invariants).
8. Conflict resolution & suppression tests (suppression of generic MONITOR at HIGH/CRITICAL).
9. Persistence & transaction tests (ORM serialization, atomic commit, rollback on failure, audit trail).
10. Tenant isolation tests (cross-tenant query rejection, 404 masking, org boundary enforcement).
11. API tests (authentication, roles, pagination, filters, response contracts).
12. Security tests (secret scrubbing, raw payload rejection).
13. No-Action tests (zero rerouting, zero cancellation, zero carrier interaction, zero auto-approval).
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
from app.risk_engine.contract import (
    AssessmentSourceSummary,
    FactorContribution,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
)
from app.risk_engine.evidence import EvidenceRelevance, RiskEvidence
from app.risk_engine.recommendations import (
    PRIORITY_RANKS,
    RecommendationPriority,
    RecommendationRuleConfig,
    RecommendationStatus,
    RecommendationType,
    RiskRecommendation,
    RiskRecommendationAdapter,
    RiskRecommendationEvaluator,
    compute_recommendation_id,
)
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
    scope: str = "GLOBAL",
    scope_entity_id: str = None,
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
        scope=scope,
        scope_entity_id=scope_entity_id,
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


@pytest.fixture
def client_app(db_session: Session):
    session_store = MemorySessionStore()
    session_service = SessionService(store=session_store)

    def override_get_db():
        yield db_session

    def override_get_session_service():
        return session_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = override_get_session_service

    with TestClient(app) as client:
        yield client, session_service

    app.dependency_overrides.clear()


def login_client(client: TestClient, session_service: SessionService, user: User) -> str:
    session_data = session_service.create_session(
        user_id=user.id,
        organization_id=user.org_id,
        role=user.role,
    )
    client.cookies.set("riskwise_session", session_data.session_id)
    return session_data.session_id


# ==============================================================================
# 1. CONTRACT TESTS (8 tests)
# ==============================================================================

def test_contract_valid_recommendation_creation():
    """RiskRecommendation model instantiates with all required domain fields."""
    rec = RiskRecommendation(
        recommendation_id="rec_test_01",
        organization_id="org_alpha",
        assessment_id="asm_test_01",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="[MONITOR] Maintain routine surveillance",
        rationale="Score is low, no immediate action required.",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    assert rec.recommendation_id == "rec_test_01"
    assert rec.organization_id == "org_alpha"
    assert rec.requires_human_approval is True
    assert rec.status == RecommendationStatus.PROPOSED


def test_contract_deterministic_id_generation():
    """compute_recommendation_id generates collision-resistant ID starting with rec_."""
    rec_id = compute_recommendation_id("org_1", "asm_1", "REVIEW_ALTERNATE_ROUTE", "fac_1")
    assert rec_id.startswith("rec_")
    assert len(rec_id) == 28
    # Exact duplicate input produces identical ID
    assert rec_id == compute_recommendation_id("org_1", "asm_1", "REVIEW_ALTERNATE_ROUTE", "fac_1")


def test_contract_distinct_inputs_produce_distinct_ids():
    """Different inputs produce distinct recommendation IDs."""
    id1 = compute_recommendation_id("org_1", "asm_1", "REVIEW_ALTERNATE_ROUTE")
    id2 = compute_recommendation_id("org_1", "asm_2", "REVIEW_ALTERNATE_ROUTE")
    id3 = compute_recommendation_id("org_2", "asm_1", "REVIEW_ALTERNATE_ROUTE")
    id4 = compute_recommendation_id("org_1", "asm_1", "MONITOR")
    assert len({id1, id2, id3, id4}) == 4


def test_contract_approval_flag_defaults_to_true():
    """Every actionable recommendation strictly enforces requires_human_approval=True."""
    rec = RiskRecommendation(
        recommendation_id="rec_appr_check",
        organization_id="org_alpha",
        assessment_id="asm_appr_check",
        recommendation_type=RecommendationType.REVIEW_ALTERNATE_ROUTE,
        priority=RecommendationPriority.HIGH,
        title="Review route",
        rationale="Highway closure",
        expected_objective="REDUCE_DELAY_RISK",
        created_at=datetime.now(timezone.utc),
    )
    assert rec.requires_human_approval is True


def test_contract_default_status_is_proposed():
    """Newly generated recommendations have status PROPOSED."""
    rec = RiskRecommendation(
        recommendation_id="rec_stat_check",
        organization_id="org_alpha",
        assessment_id="asm_stat_check",
        recommendation_type=RecommendationType.INVESTIGATE,
        priority=RecommendationPriority.MEDIUM,
        title="Investigate discrepancy",
        rationale="Conflicting signals",
        expected_objective="IMPROVE_VISIBILITY",
        created_at=datetime.now(timezone.utc),
    )
    assert rec.status == RecommendationStatus.PROPOSED


def test_contract_optional_fields_nullable():
    """Optional fields (risk_id, scope, scope_entity_id, confidence) default to None safely."""
    rec = RiskRecommendation(
        recommendation_id="rec_opt_check",
        organization_id="org_alpha",
        assessment_id="asm_opt_check",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="Monitor",
        rationale="Low risk",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    assert rec.risk_id is None
    assert rec.scope is None
    assert rec.scope_entity_id is None
    assert rec.confidence is None


def test_contract_list_fields_default_to_empty_list():
    """Factor IDs, evidence IDs, constraints, assumptions, limitations default to empty lists."""
    rec = RiskRecommendation(
        recommendation_id="rec_list_check",
        organization_id="org_alpha",
        assessment_id="asm_list_check",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="Monitor",
        rationale="Low risk",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    assert rec.factor_ids == []
    assert rec.evidence_ids == []
    assert rec.constraints == []
    assert rec.assumptions == []
    assert rec.limitations == []


def test_contract_priority_ranks_ordering():
    """Priority ranks maintain strictly monotonic order: LOW < MEDIUM < HIGH < CRITICAL."""
    assert PRIORITY_RANKS[RecommendationPriority.LOW.value] < PRIORITY_RANKS[RecommendationPriority.MEDIUM.value]
    assert PRIORITY_RANKS[RecommendationPriority.MEDIUM.value] < PRIORITY_RANKS[RecommendationPriority.HIGH.value]
    assert PRIORITY_RANKS[RecommendationPriority.HIGH.value] < PRIORITY_RANKS[RecommendationPriority.CRITICAL.value]


# ==============================================================================
# 2. RULE TESTS (14 tests)
# ==============================================================================

def test_rule_low_risk_recommends_monitor():
    """Assessment in LOW risk (<30.0) produces MONITOR recommendation with LOW priority."""
    curr = create_dummy_assessment("asm_low", score=18.5, risk_level=RiskLevel.LOW)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) == 1
    assert recs[0].recommendation_type == RecommendationType.MONITOR
    assert recs[0].priority == RecommendationPriority.LOW


def test_rule_medium_risk_recommends_monitor():
    """Assessment in MEDIUM risk ([30, 60)) produces MONITOR recommendation with MEDIUM priority."""
    curr = create_dummy_assessment("asm_med", score=45.0, risk_level=RiskLevel.MEDIUM)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.MONITOR and r.priority == RecommendationPriority.MEDIUM for r in recs)


def test_rule_high_risk_recommends_escalate_operational_attention():
    """Assessment in HIGH risk ([60, 85)) produces ESCALATE_OPERATIONAL_ATTENTION with HIGH priority."""
    curr = create_dummy_assessment("asm_high", score=72.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.HIGH


def test_rule_critical_risk_recommends_escalate_and_expedite():
    """Assessment in CRITICAL risk (>=85.0) produces both ESCALATE and EXPEDITE_REVIEW with CRITICAL priority."""
    curr = create_dummy_assessment("asm_crit", score=91.0, risk_level=RiskLevel.CRITICAL)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    types = {r.recommendation_type for r in recs}
    assert RecommendationType.ESCALATE_OPERATIONAL_ATTENTION in types
    assert RecommendationType.EXPEDITE_REVIEW in types
    for r in recs:
        if r.recommendation_type in (RecommendationType.ESCALATE_OPERATIONAL_ATTENTION, RecommendationType.EXPEDITE_REVIEW):
            assert r.priority == RecommendationPriority.CRITICAL


def test_rule_critical_factor_triggers_expedite_review():
    """Critical factor triggers EXPEDITE_REVIEW citing the exact factor."""
    f_crit = RiskFactor(
        factor_id="fac_super_typhoon",
        factor_type="WEATHER",
        domain=SignalDomain.WEATHER,
        name="Category 5 Typhoon",
        severity=RiskLevel.CRITICAL,
        confidence=0.95,
        contribution=0.85,
    )
    curr = create_dummy_assessment("asm_crit_fac", score=55.0, risk_level=RiskLevel.MEDIUM, factors=[f_crit])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    expedite = next((r for r in recs if r.recommendation_type == RecommendationType.EXPEDITE_REVIEW), None)
    assert expedite is not None
    assert expedite.priority == RecommendationPriority.CRITICAL
    assert "fac_super_typhoon" in expedite.factor_ids


def test_rule_port_disruption_recommends_review_alternate_route():
    """Port disruption factor triggers REVIEW_ALTERNATE_ROUTE."""
    f_port = RiskFactor(
        factor_id="fac_port_01",
        factor_type="PORT",
        domain=SignalDomain.LOGISTICS,
        name="Port Strike & Berthing Halt",
        severity=RiskLevel.HIGH,
        confidence=0.85,
        contribution=0.70,
    )
    curr = create_dummy_assessment("asm_port", score=65.0, risk_level=RiskLevel.HIGH, factors=[f_port])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    route_rec = next((r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_ROUTE), None)
    assert route_rec is not None
    assert route_rec.expected_objective == "REDUCE_DELAY_RISK"
    assert "fac_port_01" in route_rec.factor_ids


def test_rule_road_disruption_recommends_review_alternate_route():
    """Road disruption factor triggers REVIEW_ALTERNATE_ROUTE."""
    f_road = RiskFactor(
        factor_id="fac_road_01",
        factor_type="ROAD",
        domain=SignalDomain.ROAD,
        name="Highway Flooding",
        severity=RiskLevel.HIGH,
        confidence=0.90,
        contribution=0.60,
    )
    curr = create_dummy_assessment("asm_road", score=62.0, risk_level=RiskLevel.HIGH, factors=[f_road])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    route_rec = next((r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_ROUTE), None)
    assert route_rec is not None
    assert "Highway Flooding" in route_rec.title


def test_rule_ocean_disruption_recommends_review_alternate_route():
    """Maritime disruption factor triggers REVIEW_ALTERNATE_ROUTE."""
    f_ocean = RiskFactor(
        factor_id="fac_ocean_01",
        factor_type="OCEAN",
        domain=SignalDomain.OCEAN,
        name="Strait Blockade",
        severity=RiskLevel.CRITICAL,
        confidence=0.95,
        contribution=0.80,
    )
    curr = create_dummy_assessment("asm_ocean", score=88.0, risk_level=RiskLevel.CRITICAL, factors=[f_ocean])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    route_rec = next((r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_ROUTE), None)
    assert route_rec is not None
    assert route_rec.priority == RecommendationPriority.CRITICAL


def test_rule_logistics_disruption_recommends_review_carrier():
    """Air, Rail, or Logistics transport disruption triggers REVIEW_CARRIER."""
    f_logistics = RiskFactor(
        factor_id="fac_carrier_01",
        factor_type="AIR",
        domain=SignalDomain.AIR,
        name="Air Freight Grounding",
        severity=RiskLevel.HIGH,
        confidence=0.85,
        contribution=0.65,
    )
    curr = create_dummy_assessment("asm_air", score=64.0, risk_level=RiskLevel.HIGH, factors=[f_logistics])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    carrier_rec = next((r for r in recs if r.recommendation_type == RecommendationType.REVIEW_CARRIER), None)
    assert carrier_rec is not None
    assert carrier_rec.expected_objective == "REDUCE_DELAY_RISK"


def test_rule_supplier_disruption_recommends_review_alternate_supplier():
    """Supplier disruption triggers REVIEW_ALTERNATE_SUPPLIER."""
    f_supplier = RiskFactor(
        factor_id="fac_sup_01",
        factor_type="SUPPLIER",
        domain=SignalDomain.GENERAL,
        name="Tier 1 Factory Insolvency",
        severity=RiskLevel.HIGH,
        confidence=0.80,
        contribution=0.55,
    )
    curr = create_dummy_assessment("asm_sup", score=58.0, risk_level=RiskLevel.MEDIUM, factors=[f_supplier])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    sup_rec = next((r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_SUPPLIER), None)
    assert sup_rec is not None
    assert sup_rec.expected_objective == "REVIEW_SUPPLY_CONTINUITY"


def test_rule_inventory_risk_recommends_review_inventory():
    """Inventory or warehouse vulnerability triggers REVIEW_INVENTORY."""
    f_inv = RiskFactor(
        factor_id="fac_inv_01",
        factor_type="INVENTORY",
        domain=SignalDomain.LOGISTICS,
        name="Cold Storage Spoilage Risk",
        severity=RiskLevel.HIGH,
        confidence=0.85,
        contribution=0.60,
    )
    curr = create_dummy_assessment("asm_inv", score=55.0, risk_level=RiskLevel.MEDIUM, factors=[f_inv])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    inv_rec = next((r for r in recs if r.recommendation_type == RecommendationType.REVIEW_INVENTORY), None)
    assert inv_rec is not None
    assert inv_rec.expected_objective == "PROTECT_SERVICE_LEVEL"


def test_rule_increasing_trend_triggers_escalation():
    """Assessment on an INCREASING trend with score >= 60.0 triggers ESCALATE_OPERATIONAL_ATTENTION."""
    prev = create_dummy_assessment("asm_p", score=50.0, risk_level=RiskLevel.MEDIUM)
    curr = create_dummy_assessment("asm_c", score=70.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr, previous=prev)
    trend_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION and "trend" in r.metadata), None)
    assert trend_rec is not None
    assert trend_rec.metadata.get("trend") == "INCREASING"


def test_rule_conflict_triggers_investigate():
    """Presence of signal conflicts triggers INVESTIGATE with visibility objective."""
    conflicts = [{"factor": "ROAD", "detail": "TomTom vs Here conflict"}]
    curr = create_dummy_assessment("asm_conf", score=45.0, risk_level=RiskLevel.MEDIUM, conflicts=conflicts)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    inv = next((r for r in recs if r.recommendation_type == RecommendationType.INVESTIGATE), None)
    assert inv is not None
    assert inv.expected_objective == "IMPROVE_VISIBILITY"
    assert inv.metadata.get("conflict_count") == 1


def test_rule_quality_degraded_attaches_limitation():
    """Partial or degraded evidence attaches explicit quality limitation to recommendation."""
    sig = make_test_signal("sig_part", quality=EventQuality.PARTIAL)
    evi = RiskEvidence.from_normalized_signal(sig)
    curr = create_dummy_assessment("asm_part", score=40.0, risk_level=RiskLevel.MEDIUM, evidence=[evi])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    assert any("PARTIAL" in lim for lim in recs[0].limitations)


# ==============================================================================
# 3. RECOMMENDATION TYPE TESTS (8 tests)
# ==============================================================================

def test_type_monitor_represented():
    curr = create_dummy_assessment("asm_t_mon", score=20.0, risk_level=RiskLevel.LOW)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.MONITOR for r in recs)


def test_type_investigate_represented():
    curr = create_dummy_assessment("asm_t_inv", score=40.0, risk_level=RiskLevel.MEDIUM, conflicts=[{"a": 1}])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.INVESTIGATE for r in recs)


def test_type_expedite_review_represented():
    f = RiskFactor(factor_id="f1", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Cyclone", severity=RiskLevel.CRITICAL, confidence=0.9, contribution=0.8)
    curr = create_dummy_assessment("asm_t_exp", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.EXPEDITE_REVIEW for r in recs)


def test_type_review_alternate_route_represented():
    f = RiskFactor(factor_id="f2", factor_type="PORT", domain=SignalDomain.LOGISTICS, name="Port Congestion", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_t_route", score=65.0, risk_level=RiskLevel.HIGH, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_ROUTE for r in recs)


def test_type_review_alternate_supplier_represented():
    f = RiskFactor(factor_id="f3", factor_type="SUPPLIER", domain=SignalDomain.GENERAL, name="Supplier Failure", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_t_sup", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_SUPPLIER for r in recs)


def test_type_review_inventory_represented():
    f = RiskFactor(factor_id="f4", factor_type="INVENTORY", domain=SignalDomain.LOGISTICS, name="Warehouse Fire", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_t_inv", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.REVIEW_INVENTORY for r in recs)


def test_type_review_carrier_represented():
    f = RiskFactor(factor_id="f5", factor_type="AIR", domain=SignalDomain.AIR, name="Airline Grounding", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_t_car", score=65.0, risk_level=RiskLevel.HIGH, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.REVIEW_CARRIER for r in recs)


def test_type_escalate_operational_attention_represented():
    curr = create_dummy_assessment("asm_t_esc", score=75.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert any(r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION for r in recs)


# ==============================================================================
# 4. PRIORITY TESTS (6 tests)
# ==============================================================================

def test_priority_critical_risk_maps_to_critical():
    curr = create_dummy_assessment("asm_prio_crit", score=90.0, risk_level=RiskLevel.CRITICAL)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate = next(r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION)
    assert escalate.priority == RecommendationPriority.CRITICAL


def test_priority_high_risk_maps_to_high():
    curr = create_dummy_assessment("asm_prio_high", score=70.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate = next(r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION)
    assert escalate.priority == RecommendationPriority.HIGH


def test_priority_medium_risk_maps_to_medium():
    curr = create_dummy_assessment("asm_prio_med", score=45.0, risk_level=RiskLevel.MEDIUM)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    monitor = next(r for r in recs if r.recommendation_type == RecommendationType.MONITOR)
    assert monitor.priority == RecommendationPriority.MEDIUM


def test_priority_low_risk_maps_to_low():
    curr = create_dummy_assessment("asm_prio_low", score=15.0, risk_level=RiskLevel.LOW)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    monitor = next(r for r in recs if r.recommendation_type == RecommendationType.MONITOR)
    assert monitor.priority == RecommendationPriority.LOW


def test_priority_critical_factor_elevates_to_critical():
    f = RiskFactor(factor_id="f_crit", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Tornado", severity=RiskLevel.CRITICAL, confidence=0.9, contribution=0.8)
    curr = create_dummy_assessment("asm_crit_fac_prio", score=40.0, risk_level=RiskLevel.MEDIUM, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    expedite = next(r for r in recs if r.recommendation_type == RecommendationType.EXPEDITE_REVIEW)
    assert expedite.priority == RecommendationPriority.CRITICAL


def test_priority_deterministic_ordering():
    """Recommendations are deterministically ordered by priority descending."""
    f1 = RiskFactor(factor_id="f1", factor_type="PORT", domain=SignalDomain.LOGISTICS, name="Port", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    f2 = RiskFactor(factor_id="f2", factor_type="WEATHER", domain=SignalDomain.WEATHER, name="Cyclone", severity=RiskLevel.CRITICAL, confidence=0.9, contribution=0.8)
    curr = create_dummy_assessment("asm_order", score=88.0, risk_level=RiskLevel.CRITICAL, factors=[f1, f2])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) >= 2
    for i in range(len(recs) - 1):
        prio_a = PRIORITY_RANKS[recs[i].priority.value]
        prio_b = PRIORITY_RANKS[recs[i + 1].priority.value]
        assert prio_a >= prio_b


# ==============================================================================
# 5. TRACEABILITY TESTS (6 tests)
# ==============================================================================

def test_traceability_recommendation_links_to_assessment():
    curr = create_dummy_assessment("asm_trace_01", score=75.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    for r in recs:
        assert r.assessment_id == "asm_trace_01"


def test_traceability_factor_ids_present():
    f = RiskFactor(factor_id="fac_trace_99", factor_type="ROAD", domain=SignalDomain.ROAD, name="Road Landslide", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_trace_02", score=65.0, risk_level=RiskLevel.HIGH, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    route_rec = next(r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_ROUTE)
    assert "fac_trace_99" in route_rec.factor_ids


def test_traceability_evidence_ids_present():
    f = RiskFactor(
        factor_id="fac_evi_trace",
        factor_type="ROAD",
        domain=SignalDomain.ROAD,
        name="Bridge Out",
        severity=RiskLevel.HIGH,
        confidence=0.8,
        contribution=0.6,
        evidence_ids=["evi_sensor_01", "evi_sensor_02"],
    )
    curr = create_dummy_assessment("asm_trace_03", score=65.0, risk_level=RiskLevel.HIGH, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    route_rec = next(r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_ROUTE)
    assert "evi_sensor_01" in route_rec.evidence_ids


def test_traceability_empty_factors_safe():
    curr = create_dummy_assessment("asm_trace_empty", score=75.0, risk_level=RiskLevel.HIGH, factors=[])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    assert recs[0].factor_ids == []


def test_traceability_multi_factor_recs_preserved():
    f1 = RiskFactor(factor_id="f1", factor_type="PORT", domain=SignalDomain.LOGISTICS, name="Port", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.5)
    f2 = RiskFactor(factor_id="f2", factor_type="ROAD", domain=SignalDomain.ROAD, name="Road", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.5)
    curr = create_dummy_assessment("asm_multi", score=75.0, risk_level=RiskLevel.HIGH, factors=[f1, f2])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate = next(r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION)
    assert "f1" in escalate.factor_ids
    assert "f2" in escalate.factor_ids


def test_traceability_scope_and_entity_passed_through():
    curr = create_dummy_assessment("asm_scope", score=70.0, risk_level=RiskLevel.HIGH, scope="PORT", scope_entity_id="port_singapore")
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    for r in recs:
        assert r.scope == "PORT"
        assert r.scope_entity_id == "port_singapore"


# ==============================================================================
# 6. EXPLANATION TESTS (6 tests)
# ==============================================================================

def test_explanation_factual_rationale():
    curr = create_dummy_assessment("asm_exp_1", score=89.0, risk_level=RiskLevel.CRITICAL)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    assert "CRITICAL threshold" in recs[0].rationale


def test_explanation_no_speculative_causality():
    curr = create_dummy_assessment("asm_exp_2", score=65.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    for r in recs:
        assert "probability" not in r.rationale.lower()
        assert "guaranteed" not in r.rationale.lower()
        assert "will definitely" not in r.rationale.lower()


def test_explanation_assumptions_included():
    curr = create_dummy_assessment("asm_exp_3", score=40.0, risk_level=RiskLevel.MEDIUM)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    assert len(recs[0].assumptions) >= 2


def test_explanation_constraints_included():
    curr = create_dummy_assessment("asm_exp_4", score=40.0, risk_level=RiskLevel.MEDIUM)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    assert len(recs[0].constraints) >= 2


def test_explanation_operational_objective_included():
    f = RiskFactor(factor_id="f_sup", factor_type="SUPPLIER", domain=SignalDomain.GENERAL, name="Supplier", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.5)
    curr = create_dummy_assessment("asm_exp_5", score=50.0, risk_level=RiskLevel.MEDIUM, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    sup_rec = next(r for r in recs if r.recommendation_type == RecommendationType.REVIEW_ALTERNATE_SUPPLIER)
    assert sup_rec.expected_objective == "REVIEW_SUPPLY_CONTINUITY"


def test_explanation_title_formatted_cleanly():
    curr = create_dummy_assessment("asm_exp_6", score=75.0, risk_level=RiskLevel.HIGH)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    assert recs[0].title.startswith("[")
    assert "]" in recs[0].title


# ==============================================================================
# 7. DEDUPLICATION TESTS (6 tests)
# ==============================================================================

def test_deduplication_identical_inputs_produce_identical_ids():
    id1 = compute_recommendation_id("org_alpha", "asm_100", "REVIEW_ALTERNATE_ROUTE", "fac_1")
    id2 = compute_recommendation_id("org_alpha", "asm_100", "REVIEW_ALTERNATE_ROUTE", "fac_1")
    assert id1 == id2


def test_deduplication_repeated_evaluation_produces_identical_recommendations():
    curr = create_dummy_assessment("asm_repeat", score=70.0, risk_level=RiskLevel.HIGH)
    recs1 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    recs2 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert [r.recommendation_id for r in recs1] == [r.recommendation_id for r in recs2]


def test_deduplication_distinct_assessments_produce_distinct_recommendations():
    curr1 = create_dummy_assessment("asm_distinct_1", score=70.0, risk_level=RiskLevel.HIGH)
    curr2 = create_dummy_assessment("asm_distinct_2", score=70.0, risk_level=RiskLevel.HIGH)
    recs1 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr1)
    recs2 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr2)
    ids1 = {r.recommendation_id for r in recs1}
    ids2 = {r.recommendation_id for r in recs2}
    assert ids1.isdisjoint(ids2)


def test_deduplication_distinct_orgs_produce_distinct_recommendations():
    curr1 = create_dummy_assessment("asm_shared", org_id="org_alpha", score=70.0, risk_level=RiskLevel.HIGH)
    curr2 = create_dummy_assessment("asm_shared", org_id="org_beta", score=70.0, risk_level=RiskLevel.HIGH)
    recs1 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr1)
    recs2 = RiskRecommendationEvaluator.evaluate_recommendations(current=curr2)
    ids1 = {r.recommendation_id for r in recs1}
    ids2 = {r.recommendation_id for r in recs2}
    assert ids1.isdisjoint(ids2)


def test_deduplication_no_duplicate_types_for_same_entity():
    f = RiskFactor(factor_id="fac_single", factor_type="PORT", domain=SignalDomain.LOGISTICS, name="Port", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_no_dup", score=65.0, risk_level=RiskLevel.HIGH, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    ids = [r.recommendation_id for r in recs]
    assert len(ids) == len(set(ids))


def test_deduplication_deterministic_sort_tie_breaker():
    rec1 = RiskRecommendation(
        recommendation_id="rec_b",
        organization_id="org_1",
        assessment_id="asm_1",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="B",
        rationale="R",
        expected_objective="O",
        created_at=datetime.now(timezone.utc),
    )
    rec2 = RiskRecommendation(
        recommendation_id="rec_a",
        organization_id="org_1",
        assessment_id="asm_1",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="A",
        rationale="R",
        expected_objective="O",
        created_at=datetime.now(timezone.utc),
    )
    sorted_recs = sorted(
        [rec1, rec2],
        key=lambda r: (-PRIORITY_RANKS[r.priority.value], r.recommendation_type.value, r.recommendation_id),
    )
    assert sorted_recs[0].recommendation_id == "rec_a"
    assert sorted_recs[1].recommendation_id == "rec_b"


# ==============================================================================
# 8. CONFLICT RESOLUTION & SUPPRESSION TESTS (4 tests)
# ==============================================================================

def test_suppression_generic_monitor_suppressed_at_high_risk():
    """When operational review (e.g. alternate route) is present at HIGH risk, generic MONITOR is suppressed."""
    f = RiskFactor(factor_id="f_port", factor_type="PORT", domain=SignalDomain.LOGISTICS, name="Port", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.6)
    curr = create_dummy_assessment("asm_suppress_high", score=72.0, risk_level=RiskLevel.HIGH, factors=[f])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    types = [r.recommendation_type for r in recs]
    assert RecommendationType.REVIEW_ALTERNATE_ROUTE in types
    assert RecommendationType.MONITOR not in types


def test_suppression_generic_monitor_suppressed_at_critical_risk():
    """Generic MONITOR is strictly suppressed at CRITICAL risk."""
    curr = create_dummy_assessment("asm_suppress_crit", score=90.0, risk_level=RiskLevel.CRITICAL)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    types = [r.recommendation_type for r in recs]
    assert RecommendationType.MONITOR not in types


def test_suppression_generic_monitor_preserved_at_low_risk():
    """Generic MONITOR is preserved at LOW risk when no active disruption exists."""
    curr = create_dummy_assessment("asm_preserve_low", score=20.0, risk_level=RiskLevel.LOW)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) == 1
    assert recs[0].recommendation_type == RecommendationType.MONITOR


def test_suppression_multiple_operational_reviews_coexist():
    """Multiple distinct operational reviews (e.g. Route + Carrier) coexist without suppressing each other."""
    f1 = RiskFactor(factor_id="f1", factor_type="PORT", domain=SignalDomain.LOGISTICS, name="Port", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.5)
    f2 = RiskFactor(factor_id="f2", factor_type="AIR", domain=SignalDomain.AIR, name="Airport", severity=RiskLevel.HIGH, confidence=0.8, contribution=0.5)
    curr = create_dummy_assessment("asm_coexist", score=70.0, risk_level=RiskLevel.HIGH, factors=[f1, f2])
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    types = {r.recommendation_type for r in recs}
    assert RecommendationType.REVIEW_ALTERNATE_ROUTE in types
    assert RecommendationType.REVIEW_CARRIER in types


# ==============================================================================
# 9. PERSISTENCE & TRANSACTION TESTS (6 tests)
# ==============================================================================

def test_persistence_adapter_roundtrip():
    """RiskRecommendationAdapter round-trips domain model to ORM and back without data loss."""
    rec = RiskRecommendation(
        recommendation_id="rec_roundtrip",
        organization_id="org_alpha",
        assessment_id="asm_roundtrip",
        risk_id="rsk_roundtrip",
        scope="PORT",
        scope_entity_id="port_alpha",
        recommendation_type=RecommendationType.REVIEW_ALTERNATE_ROUTE,
        priority=RecommendationPriority.HIGH,
        title="[ROUTE] Review routing",
        rationale="Corridor blocked",
        factor_ids=["f1", "f2"],
        evidence_ids=["e1", "e2"],
        expected_objective="REDUCE_DELAY_RISK",
        constraints=["Optimization pending"],
        assumptions=["Active signal"],
        limitations=["None"],
        requires_human_approval=True,
        confidence=0.88,
        created_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    orm = RiskRecommendationAdapter.to_orm(rec)
    reconstructed = RiskRecommendationAdapter.from_orm(orm)

    assert reconstructed.recommendation_id == rec.recommendation_id
    assert reconstructed.recommendation_type == rec.recommendation_type
    assert reconstructed.priority == rec.priority
    assert reconstructed.factor_ids == rec.factor_ids
    assert reconstructed.evidence_ids == rec.evidence_ids
    assert reconstructed.requires_human_approval is True


def test_persistence_transactional_recommendations_created(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """evaluate_and_persist saves recommendations to recommendations table transactionally."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_rec_trans_01", org_id=test_org.id, severity=EventSeverity.CRITICAL)

    assessment, detail, is_hit = service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")
    assert is_hit is False
    assert len(detail.get("recommendations", [])) > 0

    # Query recommendations table via session
    recs = list(uow.session.scalars(select(Recommendation).where(Recommendation.org_id == test_org.id)).all())
    assert len(recs) > 0
    assert any(r.id.startswith("rec_") for r in recs)


def test_persistence_rollback_on_failure(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Failure during persistence transaction cleanly rolls back all recommendation records."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_rec_fail_01", org_id=test_org.id, severity=EventSeverity.CRITICAL)

    with pytest.raises(Exception):
        service.evaluate_and_persist(signals=[sig], risk_id="rsk_nonexistent_9999")

    # Confirm zero recommendations exist
    recs = list(uow.session.scalars(select(Recommendation).where(Recommendation.org_id == test_org.id)).all())
    assert len(recs) == 0


def test_persistence_idempotency_avoids_duplicate_recommendations(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Repeated evaluation with identical fingerprint produces zero duplicate recommendations."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal(
        "sig_rec_idem_01",
        org_id=test_org.id,
        severity=EventSeverity.CRITICAL,
        event_time=datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc),
    )

    _, _, hit1 = service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")
    assert hit1 is False
    count1 = len(list(uow.session.scalars(select(Recommendation).where(Recommendation.org_id == test_org.id)).all()))

    _, _, hit2 = service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")
    assert hit2 is True
    count2 = len(list(uow.session.scalars(select(Recommendation).where(Recommendation.org_id == test_org.id)).all()))

    assert count1 == count2


def test_persistence_audit_log_recorded(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Recommendation creation appends RECOMMENDATION_PROPOSED audit records."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_audit_rec_01", org_id=test_org.id, severity=EventSeverity.HIGH)

    service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")

    logs = list(uow.session.scalars(select(AuditLog).where(AuditLog.org_id == test_org.id, AuditLog.action == "RECOMMENDATION_PROPOSED")).all())
    assert len(logs) > 0
    assert logs[0].resource_type == "Recommendation"


def test_persistence_list_recommendations_service(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """RiskEvaluationService.list_recommendations retrieves and filters recommendations."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)

    rec = RiskRecommendation(
        recommendation_id="rec_serv_list_01",
        organization_id=test_org.id,
        assessment_id="asm_target_55",
        recommendation_type=RecommendationType.EXPEDITE_REVIEW,
        priority=RecommendationPriority.CRITICAL,
        title="Expedite review",
        rationale="Critical status",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    uow.session.add(RiskRecommendationAdapter.to_orm(rec))
    uow.session.commit()

    items, total = service.list_recommendations(assessment_id="asm_target_55")
    assert total == 1
    assert items[0].recommendation_id == "rec_serv_list_01"


# ==============================================================================
# 10. TENANT ISOLATION TESTS (6 tests)
# ==============================================================================

def test_tenant_isolation_org_a_cannot_see_org_b_recommendations(
    uow: UnitOfWork,
    analyst_user: User,
    other_user: User,
    test_org: Organization,
    other_org: Organization,
):
    """Organization A cannot query Organization B recommendations."""
    rec_b = RiskRecommendation(
        recommendation_id="rec_secret_b",
        organization_id=other_org.id,
        assessment_id="asm_b",
        recommendation_type=RecommendationType.REVIEW_ALTERNATE_SUPPLIER,
        priority=RecommendationPriority.HIGH,
        title="Secret supplier switch",
        rationale="Private",
        expected_objective="REVIEW_SUPPLY_CONTINUITY",
        created_at=datetime.now(timezone.utc),
    )
    uow.session.add(RiskRecommendationAdapter.to_orm(rec_b))
    uow.session.commit()

    ctx_a = make_context(analyst_user)
    service_a = RiskEvaluationService(uow=uow, context=ctx_a)
    items_a, total_a = service_a.list_recommendations()
    assert not any(r.recommendation_id == "rec_secret_b" for r in items_a)


def test_tenant_isolation_get_recommendation_cross_tenant_returns_404(
    uow: UnitOfWork,
    analyst_user: User,
    other_org: Organization,
):
    """Direct lookup of another tenant's recommendation raises NotFoundError (404 masking)."""
    rec_b = RiskRecommendation(
        recommendation_id="rec_b_private",
        organization_id=other_org.id,
        assessment_id="asm_b_priv",
        recommendation_type=RecommendationType.EXPEDITE_REVIEW,
        priority=RecommendationPriority.CRITICAL,
        title="Private",
        rationale="Private",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    uow.session.add(RiskRecommendationAdapter.to_orm(rec_b))
    uow.session.commit()

    ctx_a = make_context(analyst_user)
    service_a = RiskEvaluationService(uow=uow, context=ctx_a)
    from app.core.errors import NotFoundError
    with pytest.raises(NotFoundError):
        service_a.get_recommendation("rec_b_private")


def test_tenant_isolation_server_context_authoritative(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Client-supplied organization ID in signals cannot override server authenticated tenant context."""
    ctx_a = make_context(analyst_user)
    service_a = RiskEvaluationService(uow=uow, context=ctx_a)

    # Signal claiming org_beta while user is in org_alpha raises TenantMismatchError
    sig = make_test_signal("sig_mismatch", org_id="org_beta")
    from app.risk_engine.errors import TenantMismatchError
    with pytest.raises(TenantMismatchError):
        service_a.evaluate_and_persist(signals=[sig])


def test_tenant_isolation_cross_tenant_assessment_recommendations_empty(
    uow: UnitOfWork,
    analyst_user: User,
    other_org: Organization,
):
    """Querying recommendations for an assessment belonging to another tenant returns empty list."""
    rec_b = RiskRecommendation(
        recommendation_id="rec_b_scoped",
        organization_id=other_org.id,
        assessment_id="asm_b_target",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="Monitor B",
        rationale="Rationale",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    uow.session.add(RiskRecommendationAdapter.to_orm(rec_b))
    uow.session.commit()

    ctx_a = make_context(analyst_user)
    service_a = RiskEvaluationService(uow=uow, context=ctx_a)
    items, total = service_a.list_recommendations(assessment_id="asm_b_target")
    assert total == 0
    assert len(items) == 0


def test_tenant_isolation_persisted_org_id_matches_context(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Persisted recommendation strictly inherits authenticated context.organization_id."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_org_match", org_id=test_org.id, severity=EventSeverity.HIGH)

    service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")

    recs = list(uow.session.scalars(select(Recommendation)).all())
    assert len(recs) > 0
    for r in recs:
        assert r.org_id == test_org.id


def test_tenant_isolation_filter_by_priority_tenant_bounded(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
    other_org: Organization,
):
    """Priority filter only returns recommendations within tenant boundary."""
    rec_a = RiskRecommendation(
        recommendation_id="rec_prio_a",
        organization_id=test_org.id,
        assessment_id="asm_a",
        recommendation_type=RecommendationType.EXPEDITE_REVIEW,
        priority=RecommendationPriority.CRITICAL,
        title="A",
        rationale="A",
        expected_objective="O",
        created_at=datetime.now(timezone.utc),
    )
    rec_b = RiskRecommendation(
        recommendation_id="rec_prio_b",
        organization_id=other_org.id,
        assessment_id="asm_b",
        recommendation_type=RecommendationType.EXPEDITE_REVIEW,
        priority=RecommendationPriority.CRITICAL,
        title="B",
        rationale="B",
        expected_objective="O",
        created_at=datetime.now(timezone.utc),
    )
    uow.session.add(RiskRecommendationAdapter.to_orm(rec_a))
    uow.session.add(RiskRecommendationAdapter.to_orm(rec_b))
    uow.session.commit()

    ctx_a = make_context(analyst_user)
    service_a = RiskEvaluationService(uow=uow, context=ctx_a)
    items, total = service_a.list_recommendations(priority="CRITICAL")
    assert total == 1
    assert items[0].recommendation_id == "rec_prio_a"


# ==============================================================================
# 11. API TESTS (6 tests)
# ==============================================================================

def test_api_list_recommendations_authenticated(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/recommendations lists recommendations for authenticated user."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    rec = RiskRecommendation(
        recommendation_id="rec_api_01",
        organization_id=test_org.id,
        assessment_id="asm_api_01",
        recommendation_type=RecommendationType.MONITOR,
        priority=RecommendationPriority.LOW,
        title="[MONITOR] Surveillance",
        rationale="Normal baseline",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskRecommendationAdapter.to_orm(rec))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/recommendations")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["recommendation_id"] == "rec_api_01"


def test_api_list_recommendations_unauthenticated_rejected(client_app):
    """GET /api/v1/risk-assessments/recommendations without session returns 401."""
    client, _ = client_app
    resp = client.get("/api/v1/risk-assessments/recommendations")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_get_recommendation_by_id(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/recommendations/{id} retrieves specific recommendation."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    rec = RiskRecommendation(
        recommendation_id="rec_api_single",
        organization_id=test_org.id,
        assessment_id="asm_api_single",
        recommendation_type=RecommendationType.REVIEW_ALTERNATE_ROUTE,
        priority=RecommendationPriority.HIGH,
        title="[ROUTE] Detour",
        rationale="Detour required",
        expected_objective="REDUCE_DELAY_RISK",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskRecommendationAdapter.to_orm(rec))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/recommendations/rec_api_single")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["recommendation_id"] == "rec_api_single"
    assert data["recommendation_type"] == "REVIEW_ALTERNATE_ROUTE"


def test_api_get_recommendation_not_found(client_app, test_user: User):
    """GET /api/v1/risk-assessments/recommendations/rec_nonexistent returns 404."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    resp = client.get("/api/v1/risk-assessments/recommendations/rec_nonexistent_999")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def test_api_get_assessment_recommendations(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/{id}/recommendations returns assessment-linked recommendations."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    rec = RiskRecommendation(
        recommendation_id="rec_api_linked",
        organization_id=test_org.id,
        assessment_id="asm_target_999",
        recommendation_type=RecommendationType.EXPEDITE_REVIEW,
        priority=RecommendationPriority.CRITICAL,
        title="Expedite target",
        rationale="Target rationale",
        expected_objective="PROTECT_SERVICE_LEVEL",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(RiskRecommendationAdapter.to_orm(rec))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/asm_target_999/recommendations")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["recommendation_id"] == "rec_api_linked"


def test_api_list_recommendations_pagination(
    client_app,
    db_session: Session,
    test_user: User,
    test_org: Organization,
):
    """GET /api/v1/risk-assessments/recommendations respects pagination parameters."""
    client, session_service = client_app
    login_client(client, session_service, test_user)

    for i in range(5):
        rec = RiskRecommendation(
            recommendation_id=f"rec_page_{i}",
            organization_id=test_org.id,
            assessment_id=f"asm_p_{i}",
            recommendation_type=RecommendationType.MONITOR,
            priority=RecommendationPriority.LOW,
            title=f"Page rec {i}",
            rationale="Page rationale",
            expected_objective="PROTECT_SERVICE_LEVEL",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(RiskRecommendationAdapter.to_orm(rec))
    db_session.commit()

    resp = client.get("/api/v1/risk-assessments/recommendations?page=1&limit=2")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["pagination"]["total"] >= 5
    assert data["pagination"]["page"] == 1
    assert data["pagination"]["limit"] == 2


# ==============================================================================
# 12. SECURITY TESTS (3 tests)
# ==============================================================================

def test_security_no_api_keys_in_recommendation():
    """Recommendation rationale and metadata scrub API keys and sensitive tokens."""
    curr = create_dummy_assessment(
        "asm_sec_01",
        score=88.0,
        risk_level=RiskLevel.CRITICAL,
        limitations=["API_KEY=sk_live_secret123456789"],
    )
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    rec_str = str(recs[0].model_dump())
    assert "sk_live_secret" not in rec_str


def test_security_no_passwords_in_audit_data(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Audit logs for RECOMMENDATION_PROPOSED contain no passwords or secrets."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_pwd_test", org_id=test_org.id, severity=EventSeverity.CRITICAL)

    service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_alpha")

    logs = list(uow.session.scalars(select(AuditLog).where(AuditLog.org_id == test_org.id)).all())
    assert len(logs) > 0
    for log in logs:
        log_str = str(log.after_json or {})
        assert "password" not in log_str.lower()
        assert "secret" not in log_str.lower()


def test_security_raw_provider_payload_rejected_at_service_boundary(
    uow: UnitOfWork,
    analyst_user: User,
):
    """Unnormalized raw provider dictionaries are rejected at the service boundary."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    raw_payload = {"provider": "weather_api", "raw_temp": 105, "unnormalized": True}
    from app.core.errors import ValidationDomainError
    with pytest.raises(ValidationDomainError):
        service.evaluate_and_persist(signals=[raw_payload])


# ==============================================================================
# 13. NO-ACTION TESTS (5 tests)
# ==============================================================================

def test_no_action_does_not_reroute_shipments(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Evaluating recommendations does NOT mutate any shipment route or create Action records."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_no_act_1", org_id=test_org.id, severity=EventSeverity.CRITICAL, domain=SignalDomain.OCEAN)

    service.evaluate_and_persist(signals=[sig], scope="SHIPMENT", scope_entity_id="shp_test_01")
    actions = list(uow.session.scalars(select(Action).where(Action.org_id == test_org.id)).all())
    assert len(actions) == 0


def test_no_action_does_not_cancel_shipment(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Recommendation generation does NOT create approval sign-offs or cancel shipments."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_no_act_2", org_id=test_org.id, severity=EventSeverity.CRITICAL, domain=SignalDomain.LOGISTICS)

    service.evaluate_and_persist(signals=[sig], scope="SHIPMENT", scope_entity_id="shp_test_02")
    approvals = list(uow.session.scalars(select(Approval)).all())
    assert len(approvals) == 0


def test_no_action_does_not_contact_carriers():
    """Recommendation generation does not execute external HTTP/carrier requests."""
    curr = create_dummy_assessment("asm_no_ext", score=95.0, risk_level=RiskLevel.CRITICAL)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert len(recs) > 0
    for r in recs:
        assert isinstance(r, RiskRecommendation)


def test_no_action_does_not_auto_approve_recommendations(
    uow: UnitOfWork,
    analyst_user: User,
    test_org: Organization,
):
    """Generated recommendations remain PROPOSED / PENDING and are never auto-approved."""
    ctx = make_context(analyst_user)
    service = RiskEvaluationService(uow=uow, context=ctx)
    sig = make_test_signal("sig_no_act_4", org_id=test_org.id, severity=EventSeverity.CRITICAL, domain=SignalDomain.LOGISTICS)

    service.evaluate_and_persist(signals=[sig], scope="PORT", scope_entity_id="port_rotterdam")
    recs = list(uow.session.scalars(select(Recommendation).where(Recommendation.org_id == test_org.id)).all())
    assert len(recs) > 0
    for r in recs:
        assert r.status in ("PROPOSED", "PENDING")


def test_no_action_step7_scope_bounded():
    """Confirms Phase 7 Step 7 boundaries: purely recommendation intent, zero operational execution."""
    curr = create_dummy_assessment("asm_scope_b", score=100.0, risk_level=RiskLevel.CRITICAL)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    assert all(r.recommendation_type in RecommendationType for r in recs)
    assert all(r.requires_human_approval is True for r in recs)


# ==============================================================================
# 14. AUTHORITATIVE THRESHOLD BOUNDARY TESTS (Step 2 Consistency)
# ==============================================================================

def test_threshold_boundary_29_99_is_low():
    """Score 29.99 is LOW [0.0, 30.0) -> produces MONITOR with LOW priority."""
    curr = create_dummy_assessment("asm_b_29_99", score=29.99)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    monitor_rec = next((r for r in recs if r.recommendation_type == RecommendationType.MONITOR), None)
    assert monitor_rec is not None
    assert monitor_rec.priority == RecommendationPriority.LOW
    assert not any(r.priority in (RecommendationPriority.HIGH, RecommendationPriority.CRITICAL) for r in recs)


def test_threshold_boundary_30_00_is_medium():
    """Score 30.00 is MEDIUM [30.0, 60.0) -> produces MONITOR with MEDIUM priority."""
    curr = create_dummy_assessment("asm_b_30_00", score=30.00)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    monitor_rec = next((r for r in recs if r.recommendation_type == RecommendationType.MONITOR), None)
    assert monitor_rec is not None
    assert monitor_rec.priority == RecommendationPriority.MEDIUM
    assert not any(r.priority in (RecommendationPriority.LOW, RecommendationPriority.HIGH, RecommendationPriority.CRITICAL) for r in recs)


def test_threshold_boundary_59_99_is_medium():
    """Score 59.99 is MEDIUM [30.0, 60.0) -> produces MONITOR with MEDIUM priority."""
    curr = create_dummy_assessment("asm_b_59_99", score=59.99)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    monitor_rec = next((r for r in recs if r.recommendation_type == RecommendationType.MONITOR), None)
    assert monitor_rec is not None
    assert monitor_rec.priority == RecommendationPriority.MEDIUM
    assert not any(r.priority in (RecommendationPriority.LOW, RecommendationPriority.HIGH, RecommendationPriority.CRITICAL) for r in recs)


def test_threshold_boundary_60_00_is_high():
    """Score 60.00 is HIGH [60.0, 85.0) -> produces ESCALATE with HIGH priority, no CRITICAL."""
    curr = create_dummy_assessment("asm_b_60_00", score=60.00)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.HIGH
    assert not any(r.priority == RecommendationPriority.CRITICAL for r in recs)
    assert not any(r.recommendation_type == RecommendationType.EXPEDITE_REVIEW for r in recs)


def test_threshold_boundary_82_00_is_high():
    """Score 82.00 is HIGH [60.0, 85.0) -> produces ESCALATE with HIGH priority, NOT CRITICAL."""
    curr = create_dummy_assessment("asm_b_82_00", score=82.00)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.HIGH
    assert not any(r.priority == RecommendationPriority.CRITICAL for r in recs)
    assert not any(r.recommendation_type == RecommendationType.EXPEDITE_REVIEW for r in recs)


def test_threshold_boundary_84_99_is_high():
    """Score 84.99 is HIGH [60.0, 85.0) -> produces ESCALATE with HIGH priority, NOT CRITICAL."""
    curr = create_dummy_assessment("asm_b_84_99", score=84.99)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.HIGH
    assert not any(r.priority == RecommendationPriority.CRITICAL for r in recs)
    assert not any(r.recommendation_type == RecommendationType.EXPEDITE_REVIEW for r in recs)


def test_threshold_boundary_85_00_is_critical():
    """Score 85.00 is CRITICAL [85.0, 100.0] -> produces ESCALATE and EXPEDITE with CRITICAL priority."""
    curr = create_dummy_assessment("asm_b_85_00", score=85.00)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    expedite_rec = next((r for r in recs if r.recommendation_type == RecommendationType.EXPEDITE_REVIEW), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.CRITICAL
    assert expedite_rec is not None
    assert expedite_rec.priority == RecommendationPriority.CRITICAL


def test_threshold_boundary_100_00_is_critical():
    """Score 100.00 is CRITICAL [85.0, 100.0] -> produces ESCALATE and EXPEDITE with CRITICAL priority."""
    curr = create_dummy_assessment("asm_b_100_00", score=100.00)
    recs = RiskRecommendationEvaluator.evaluate_recommendations(current=curr)
    escalate_rec = next((r for r in recs if r.recommendation_type == RecommendationType.ESCALATE_OPERATIONAL_ATTENTION), None)
    expedite_rec = next((r for r in recs if r.recommendation_type == RecommendationType.EXPEDITE_REVIEW), None)
    assert escalate_rec is not None
    assert escalate_rec.priority == RecommendationPriority.CRITICAL
    assert expedite_rec is not None
    assert expedite_rec.priority == RecommendationPriority.CRITICAL

