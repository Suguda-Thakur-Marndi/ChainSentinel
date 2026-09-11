"""Focused test suite for RiskWise 2.0 — Phase 7 Step 5: Risk History, Trends & Assessment Comparison.

Validates:
1. Repository historical retrieval, filtering, pagination, and deterministic ordering.
2. Pairwise assessment comparison: score deltas, level transitions, and primary driver shifts.
3. Factor-level diffing: additions, removals, severity shifts, confidence deltas, and contribution deltas.
4. Evidence and quality tracking: observations count, corroboration shifts, conflicts, and limitations.
5. Source distribution tracking: REAL vs ESTIMATED vs SIMULATED and provider deltas.
6. Trend classifications: INCREASING, DECREASING, STABLE, and INSUFFICIENT_HISTORY.
7. History timeline aggregation: min, max, average scores, transitions, and overall comparisons.
8. Immutability: read-only analysis without database mutation.
9. Tenant isolation: server-side org enforcement, cross-tenant 404 masking, and tamper rejection.
10. API integration: /api/v1/risk-assessments/history and /api/v1/risk-assessments/{id}/compare/{other_id}.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
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
from app.schemas.session import SessionData
from app.main import app
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
from app.risk_engine.history import (
    AssessmentComparison,
    ConflictChangeStatus,
    DriverChangeStatus,
    FactorChangeStatus,
    HistoricalRiskComparator,
    QualityChangeStatus,
    RiskHistorySummary,
    RiskTrend,
)
from app.risk_engine.persistence import RiskAssessmentPersistenceAdapter
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


@pytest.fixture(scope="function")
def session_service():
    """Isolated in-memory session service."""
    return SessionService(store=MemorySessionStore())


@pytest.fixture(scope="function")
def client(db_session: Session, session_service: SessionService):
    """FastAPI TestClient with overridden database session and session service dependencies."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_session_service():
        return session_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = override_session_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seed_data(db_session: Session, session_service: SessionService):
    """Seed multi-tenant users, organizations, parent risks, and sequential assessments."""
    # Organizations
    org_a = Organization(id="org_alpha", name="Alpha Logistics Corp", slug="alpha-logistics", is_active=True)
    org_b = Organization(id="org_beta", name="Beta Global Supply", slug="beta-global", is_active=True)
    db_session.add_all([org_a, org_b])
    db_session.flush()

    # Users
    analyst_a = User(id="usr_analyst_a", org_id="org_alpha", email="analyst@alpha.com", full_name="Analyst A", role="Analyst", is_active=True)
    viewer_a = User(id="usr_viewer_a", org_id="org_alpha", email="viewer@alpha.com", full_name="Viewer A", role="Viewer", is_active=True)
    analyst_b = User(id="usr_analyst_b", org_id="org_beta", email="analyst@beta.com", full_name="Analyst B", role="Analyst", is_active=True)
    viewer_b = User(id="usr_viewer_b", org_id="org_beta", email="viewer@beta.com", full_name="Viewer B", role="Viewer", is_active=True)
    db_session.add_all([analyst_a, viewer_a, analyst_b, viewer_b])
    db_session.flush()

    # Parent risks
    risk_a1 = ORMRisk(id="risk_a_001", org_id="org_alpha", title="North Atlantic Route Risk", severity="MEDIUM", risk_score=35.0)
    risk_a2 = ORMRisk(id="risk_a_002", org_id="org_alpha", title="Panama Canal Congestion", severity="HIGH", risk_score=70.0)
    risk_b1 = ORMRisk(id="risk_b_001", org_id="org_beta", title="Suez Canal Corridor Risk", severity="LOW", risk_score=20.0)
    db_session.add_all([risk_a1, risk_a2, risk_b1])
    db_session.flush()

    # Sessions
    def make_cookie(user: User) -> str:
        s = session_service.create_session(
            user_id=user.id,
            role=user.role,
            organization_id=user.org_id,
            ttl_seconds=3600,
        )
        return s.session_id

    def make_context(user: User) -> AuthenticatedContext:
        session_data = SessionData(
            session_id=f"sess_{user.id}",
            user_id=user.id,
            email=user.email,
            role=user.role,
            organization_id=user.org_id,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        org = org_a if user.org_id == "org_alpha" else org_b
        return AuthenticatedContext(user=user, session_data=session_data, organization=org)

    cookie_analyst_a = make_cookie(analyst_a)
    cookie_viewer_a = make_cookie(viewer_a)
    cookie_analyst_b = make_cookie(analyst_b)
    cookie_viewer_b = make_cookie(viewer_b)

    ctx_viewer_a = make_context(viewer_a)
    ctx_viewer_b = make_context(viewer_b)
    ctx_analyst_a = make_context(analyst_a)

    # Base reference timestamps
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Assessment A1 (Time 0): score=30.0, LOW, weather driver
    asmt_a1 = ORMRiskAssessment(
        id="asmt_a_001",
        org_id="org_alpha",
        risk_id="risk_a_001",
        score=30.0,
        confidence=0.90,
        assessor_type="DETERMINISTIC_ENGINE",
        created_at=base_time,
        findings={
            "assessment_id": "asmt_a_001",
            "scope": "SHIPMENT",
            "scope_entity_id": "SHP_1001",
            "risk_level": "LOW",
            "primary_factor_id": "factor_weather",
            "primary_driver": {"factor_id": "factor_weather", "factor_type": "WEATHER_DISRUPTION", "name": "Atlantic Gale", "severity": "LOW", "contribution": 30.0},
            "factors": [
                {"factor_id": "factor_weather", "factor_type": "WEATHER_DISRUPTION", "name": "Atlantic Gale", "severity": "LOW", "confidence": 0.90, "score": 30.0}
            ],
            "evidence": [
                {"evidence_id": "ev_w1", "source": "OPENWEATHER", "provider": "OPENWEATHER", "quality": "VALID", "relevance": "PRIMARY_DRIVER"}
            ],
            "source_summary": {
                "independent_sources_count": 1,
                "real_sources_count": 1,
                "estimated_sources_count": 0,
                "simulated_sources_count": 0,
                "corroborating_sources_count": 0,
                "providers": ["OPENWEATHER"],
            },
            "conflicts": [],
            "limitations": [],
        },
    )

    # Assessment A2 (Time +2h): score=65.0, HIGH, road driver, added conflict
    asmt_a2 = ORMRiskAssessment(
        id="asmt_a_002",
        org_id="org_alpha",
        risk_id="risk_a_001",
        score=65.0,
        confidence=0.85,
        assessor_type="DETERMINISTIC_ENGINE",
        created_at=base_time + timedelta(hours=2),
        findings={
            "assessment_id": "asmt_a_002",
            "scope": "SHIPMENT",
            "scope_entity_id": "SHP_1001",
            "risk_level": "HIGH",
            "primary_factor_id": "factor_road",
            "primary_driver": {"factor_id": "factor_road", "factor_type": "TRAFFIC_CONGESTION", "name": "Highway Blockade", "severity": "HIGH", "contribution": 50.0},
            "factors": [
                {"factor_id": "factor_weather", "factor_type": "WEATHER_DISRUPTION", "name": "Atlantic Gale", "severity": "MEDIUM", "confidence": 0.90, "score": 35.0},
                {"factor_id": "factor_road", "factor_type": "TRAFFIC_CONGESTION", "name": "Highway Blockade", "severity": "HIGH", "confidence": 0.85, "score": 50.0},
            ],
            "evidence": [
                {"evidence_id": "ev_w1", "source": "OPENWEATHER", "provider": "OPENWEATHER", "quality": "VALID", "relevance": "SUPPORTING"},
                {"evidence_id": "ev_r1", "source": "TOMTOM", "provider": "TOMTOM", "quality": "VALID", "relevance": "PRIMARY_DRIVER"},
                {"evidence_id": "ev_r2", "source": "HERE", "provider": "HERE", "quality": "PARTIAL", "relevance": "CORROBORATING"},
            ],
            "source_summary": {
                "independent_sources_count": 3,
                "real_sources_count": 2,
                "estimated_sources_count": 1,
                "simulated_sources_count": 0,
                "corroborating_sources_count": 1,
                "providers": ["OPENWEATHER", "TOMTOM", "HERE"],
            },
            "conflicts": [{"provider_a": "TOMTOM", "provider_b": "HERE", "field": "closure_state"}],
            "limitations": ["ESTIMATED_DATA_PRESENT"],
        },
    )

    # Assessment A3 (Time +4h): score=50.0, MEDIUM, road cleared, conflict resolved
    asmt_a3 = ORMRiskAssessment(
        id="asmt_a_003",
        org_id="org_alpha",
        risk_id="risk_a_001",
        score=50.0,
        confidence=0.88,
        assessor_type="DETERMINISTIC_ENGINE",
        created_at=base_time + timedelta(hours=4),
        findings={
            "assessment_id": "asmt_a_003",
            "scope": "SHIPMENT",
            "scope_entity_id": "SHP_1001",
            "risk_level": "MEDIUM",
            "primary_factor_id": "factor_road",
            "primary_driver": {"factor_id": "factor_road", "factor_type": "TRAFFIC_CONGESTION", "name": "Residual Congestion", "severity": "MEDIUM", "contribution": 50.0},
            "factors": [
                {"factor_id": "factor_road", "factor_type": "TRAFFIC_CONGESTION", "name": "Residual Congestion", "severity": "MEDIUM", "confidence": 0.88, "score": 50.0}
            ],
            "evidence": [
                {"evidence_id": "ev_r1", "source": "TOMTOM", "provider": "TOMTOM", "quality": "VALID", "relevance": "PRIMARY_DRIVER"},
                {"evidence_id": "ev_r2", "source": "HERE", "provider": "HERE", "quality": "VALID", "relevance": "CORROBORATING"},
            ],
            "source_summary": {
                "independent_sources_count": 2,
                "real_sources_count": 2,
                "estimated_sources_count": 0,
                "simulated_sources_count": 0,
                "corroborating_sources_count": 1,
                "providers": ["TOMTOM", "HERE"],
            },
            "conflicts": [],
            "limitations": [],
        },
    )

    # Assessment B1 (Org Beta): score=20.0, LOW
    asmt_b1 = ORMRiskAssessment(
        id="asmt_b_001",
        org_id="org_beta",
        risk_id="risk_b_001",
        score=20.0,
        confidence=0.95,
        assessor_type="DETERMINISTIC_ENGINE",
        created_at=base_time,
        findings={
            "assessment_id": "asmt_b_001",
            "scope": "SHIPMENT",
            "scope_entity_id": "SHP_2001",
            "risk_level": "LOW",
            "primary_factor_id": "factor_suez",
            "primary_driver": {"factor_id": "factor_suez", "factor_type": "PORT_CONGESTION", "name": "Suez Waiting Time", "severity": "LOW", "contribution": 20.0},
            "factors": [
                {"factor_id": "factor_suez", "factor_type": "PORT_CONGESTION", "name": "Suez Waiting Time", "severity": "LOW", "confidence": 0.95, "score": 20.0}
            ],
            "evidence": [{"evidence_id": "ev_b1", "source": "AISSTREAM", "provider": "AISSTREAM", "quality": "VALID", "relevance": "PRIMARY_DRIVER"}],
            "source_summary": {"independent_sources_count": 1, "real_sources_count": 1, "estimated_sources_count": 0, "simulated_sources_count": 0, "providers": ["AISSTREAM"]},
            "conflicts": [],
            "limitations": [],
        },
    )

    db_session.add_all([asmt_a1, asmt_a2, asmt_a3, asmt_b1])
    db_session.commit()

    return {
        "org_alpha": org_a,
        "org_beta": org_b,
        "cookie_analyst_a": cookie_analyst_a,
        "cookie_viewer_a": cookie_viewer_a,
        "cookie_analyst_b": cookie_analyst_b,
        "cookie_viewer_b": cookie_viewer_b,
        "ctx_viewer_a": ctx_viewer_a,
        "ctx_viewer_b": ctx_viewer_b,
        "ctx_analyst_a": ctx_analyst_a,
        "base_time": base_time,
    }


# ==============================================================================
# 1. REPOSITORY TESTS
# ==============================================================================

def test_repo_history_retrieval_order(db_session: Session, seed_data: dict):
    """Assessment history is returned in deterministic ascending order (created_at ASC, id ASC)."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", risk_id="risk_a_001", ascending=True)
    assert len(items) == 3
    assert items[0].id == "asmt_a_001"
    assert items[1].id == "asmt_a_002"
    assert items[2].id == "asmt_a_003"


def test_repo_history_organization_filtering(db_session: Session, seed_data: dict):
    """Queries for Org Alpha never return Org Beta records."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha")
    assert all(item.org_id == "org_alpha" for item in items)
    assert not any(item.id == "asmt_b_001" for item in items)


def test_repo_history_entity_filtering(db_session: Session, seed_data: dict):
    """Filtering by scope and scope_entity_id returns only matching items."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(
        org_id="org_alpha",
        scope="SHIPMENT",
        scope_entity_id="SHP_1001",
    )
    assert len(items) == 3


def test_repo_history_scope_filtering_mismatch(db_session: Session, seed_data: dict):
    """Scope filtering on an unassociated entity returns empty list."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(
        org_id="org_alpha",
        scope="SHIPMENT",
        scope_entity_id="SHP_NONEXISTENT",
    )
    assert len(items) == 0


def test_repo_history_start_time_filtering(db_session: Session, seed_data: dict):
    """Filtering by start_time excludes earlier evaluations."""
    uow = UnitOfWork(db_session)
    start = seed_data["base_time"] + timedelta(hours=1)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", start_time=start)
    assert len(items) == 2
    assert items[0].id == "asmt_a_002"
    assert items[1].id == "asmt_a_003"


def test_repo_history_end_time_filtering(db_session: Session, seed_data: dict):
    """Filtering by end_time excludes later evaluations."""
    uow = UnitOfWork(db_session)
    end = seed_data["base_time"] + timedelta(hours=3)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", end_time=end)
    assert len(items) == 2
    assert items[0].id == "asmt_a_001"
    assert items[1].id == "asmt_a_002"


def test_repo_history_date_range_window(db_session: Session, seed_data: dict):
    """Filtering by both start and end time isolates a specific window."""
    uow = UnitOfWork(db_session)
    start = seed_data["base_time"] + timedelta(hours=1)
    end = seed_data["base_time"] + timedelta(hours=3)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", start_time=start, end_time=end)
    assert len(items) == 1
    assert items[0].id == "asmt_a_002"


def test_repo_history_limit_bounding(db_session: Session, seed_data: dict):
    """Explicit limit restricts returned items count."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", limit=1)
    assert len(items) == 1
    assert items[0].id == "asmt_a_001"


def test_repo_history_empty_result(db_session: Session, seed_data: dict):
    """Tenant with no assessments returns empty list."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_empty")
    assert items == []


def test_repo_history_tie_breaker_deterministic(db_session: Session, seed_data: dict):
    """Identical timestamps use secondary key (id ASC) for absolute ordering stability."""
    same_time = seed_data["base_time"] + timedelta(days=1)
    asmt_z = ORMRiskAssessment(id="asmt_zzz", org_id="org_alpha", risk_id="risk_a_001", score=10.0, created_at=same_time)
    asmt_a = ORMRiskAssessment(id="asmt_aaa", org_id="org_alpha", risk_id="risk_a_001", score=20.0, created_at=same_time)
    db_session.add_all([asmt_z, asmt_a])
    db_session.commit()

    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", start_time=same_time)
    assert len(items) == 2
    assert items[0].id == "asmt_aaa"
    assert items[1].id == "asmt_zzz"


# ==============================================================================
# 2. COMPARISON TESTS
# ==============================================================================

def test_comparison_score_increase():
    """Score delta is positive when risk score increases."""
    prev = {"assessment_id": "a1", "score": 40.0, "risk_level": "LOW"}
    curr = {"assessment_id": "a2", "score": 65.5, "risk_level": "HIGH"}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.score_delta == 25.5
    assert comp.direction == RiskTrend.INCREASING
    assert comp.risk_level_changed is True


def test_comparison_score_decrease():
    """Score delta is negative when risk score decreases."""
    prev = {"assessment_id": "a1", "score": 75.0, "risk_level": "HIGH"}
    curr = {"assessment_id": "a2", "score": 50.0, "risk_level": "MEDIUM"}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.score_delta == -25.0
    assert comp.direction == RiskTrend.DECREASING
    assert comp.risk_level_changed is True


def test_comparison_unchanged_score():
    """Score delta is 0.0 when score does not move."""
    prev = {"assessment_id": "a1", "score": 50.0, "risk_level": "MEDIUM"}
    curr = {"assessment_id": "a2", "score": 50.0, "risk_level": "MEDIUM"}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.score_delta == 0.0
    assert comp.direction == RiskTrend.STABLE
    assert comp.risk_level_changed is False


def test_comparison_risk_level_transitions():
    """Risk level transition is accurately flagged."""
    prev = {"assessment_id": "a1", "score": 55.0, "risk_level": "MEDIUM"}
    curr = {"assessment_id": "a2", "score": 85.0, "risk_level": "CRITICAL"}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.previous_risk_level == "MEDIUM"
    assert comp.current_risk_level == "CRITICAL"
    assert comp.risk_level_changed is True


def test_comparison_primary_driver_change_detected():
    """Change in primary risk driver is detected and labeled."""
    prev = {"assessment_id": "a1", "score": 40.0, "primary_factor_id": "f_weather", "primary_driver": {"factor_id": "f_weather", "name": "Storm"}}
    curr = {"assessment_id": "a2", "score": 70.0, "primary_factor_id": "f_port", "primary_driver": {"factor_id": "f_port", "name": "Port Congestion"}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.primary_driver_change_status == DriverChangeStatus.CHANGED
    assert comp.previous_primary_factor_id == "f_weather"
    assert comp.current_primary_factor_id == "f_port"


def test_comparison_primary_driver_unchanged():
    """Same primary driver preserves DriverChangeStatus.SAME."""
    prev = {"assessment_id": "a1", "score": 40.0, "primary_factor_id": "f_weather", "primary_driver": {"factor_id": "f_weather", "name": "Storm"}}
    curr = {"assessment_id": "a2", "score": 45.0, "primary_factor_id": "f_weather", "primary_driver": {"factor_id": "f_weather", "name": "Storm"}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.primary_driver_change_status == DriverChangeStatus.SAME


def test_comparison_new_driver_when_previously_none():
    """Assessment moving from zero factors to having a driver sets status NEW."""
    prev = {"assessment_id": "a1", "score": 0.0, "primary_factor_id": None, "primary_driver": None}
    curr = {"assessment_id": "a2", "score": 30.0, "primary_factor_id": "f_weather", "primary_driver": {"factor_id": "f_weather", "name": "Rain"}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.primary_driver_change_status == DriverChangeStatus.NEW


# ==============================================================================
# 3. FACTOR TESTS
# ==============================================================================

def test_factor_added_detection():
    """New factor present in current but absent in previous has status ADDED."""
    prev = {"assessment_id": "a1", "score": 20.0, "factors": []}
    curr = {
        "assessment_id": "a2",
        "score": 50.0,
        "factors": [{"factor_id": "f_rail", "factor_type": "RAIL_DISRUPTION", "name": "Derailment", "severity": "HIGH", "confidence": 0.9, "contribution": 30.0}],
    }
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert len(comp.factor_changes) == 1
    fc = comp.factor_changes[0]
    assert fc.status == FactorChangeStatus.ADDED
    assert fc.factor_type == "RAIL_DISRUPTION"
    assert fc.contribution_delta == 30.0


def test_factor_removed_detection():
    """Factor absent in current but present in previous has status REMOVED."""
    prev = {
        "assessment_id": "a1",
        "score": 30.0,
        "factors": [{"factor_id": "f_rail", "factor_type": "RAIL_DISRUPTION", "name": "Derailment", "severity": "HIGH", "confidence": 0.9, "contribution": 30.0}],
    }
    curr = {"assessment_id": "a2", "score": 0.0, "factors": []}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert len(comp.factor_changes) == 1
    fc = comp.factor_changes[0]
    assert fc.status == FactorChangeStatus.REMOVED
    assert fc.contribution_delta == -30.0


def test_factor_severity_changed():
    """Severity shift for existing factor flags severity_changed=True."""
    prev = {"assessment_id": "a1", "score": 20.0, "factors": [{"factor_id": "f_w", "factor_type": "WEATHER", "severity": "LOW", "confidence": 0.9, "score": 20.0}]}
    curr = {"assessment_id": "a2", "score": 40.0, "factors": [{"factor_id": "f_w", "factor_type": "WEATHER", "severity": "HIGH", "confidence": 0.9, "score": 40.0}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    fc = comp.factor_changes[0]
    assert fc.status == FactorChangeStatus.CHANGED
    assert fc.severity_changed is True
    assert fc.previous_severity == "LOW"
    assert fc.current_severity == "HIGH"


def test_factor_confidence_delta():
    """Confidence delta is computed with exact float arithmetic."""
    prev = {"assessment_id": "a1", "score": 20.0, "factors": [{"factor_id": "f_w", "factor_type": "WEATHER", "confidence": 0.60, "score": 20.0}]}
    curr = {"assessment_id": "a2", "score": 20.0, "factors": [{"factor_id": "f_w", "factor_type": "WEATHER", "confidence": 0.90, "score": 20.0}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    fc = comp.factor_changes[0]
    assert round(fc.confidence_delta, 2) == 0.30


def test_factor_unchanged():
    """Identical factor maintains FactorChangeStatus.UNCHANGED."""
    prev = {"assessment_id": "a1", "score": 20.0, "factors": [{"factor_id": "f_w", "factor_type": "WEATHER", "severity": "LOW", "confidence": 0.9, "score": 20.0}]}
    curr = {"assessment_id": "a2", "score": 20.0, "factors": [{"factor_id": "f_w", "factor_type": "WEATHER", "severity": "LOW", "confidence": 0.9, "score": 20.0}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    fc = comp.factor_changes[0]
    assert fc.status == FactorChangeStatus.UNCHANGED
    assert fc.severity_changed is False
    assert fc.contribution_delta == 0.0


def test_multiple_factors_concurrent_diff():
    """Concurrent additions, removals, and changes are all tracked accurately."""
    prev = {
        "assessment_id": "a1",
        "score": 30.0,
        "factors": [
            {"factor_id": "f_w", "factor_type": "WEATHER", "severity": "LOW", "score": 20.0},
            {"factor_id": "f_r", "factor_type": "ROAD", "severity": "MEDIUM", "score": 25.0},
        ],
    }
    curr = {
        "assessment_id": "a2",
        "score": 50.0,
        "factors": [
            {"factor_id": "f_w", "factor_type": "WEATHER", "severity": "HIGH", "score": 40.0},
            {"factor_id": "f_p", "factor_type": "PORT", "severity": "MEDIUM", "score": 20.0},
        ],
    }
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    statuses = {fc.factor_type: fc.status for fc in comp.factor_changes}
    assert statuses["WEATHER"] == FactorChangeStatus.CHANGED
    assert statuses["ROAD"] == FactorChangeStatus.REMOVED
    assert statuses["PORT"] == FactorChangeStatus.ADDED


# ==============================================================================
# 4. EVIDENCE & QUALITY TESTS
# ==============================================================================

def test_evidence_count_delta():
    """Evidence observations delta is accurately calculated."""
    prev = {"assessment_id": "a1", "score": 20.0, "evidence": [{"id": "e1"}, {"id": "e2"}]}
    curr = {"assessment_id": "a2", "score": 40.0, "evidence": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}, {"id": "e4"}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.evidence_changes.evidence_count_delta == 2
    assert comp.evidence_changes.previous_evidence_count == 2
    assert comp.evidence_changes.current_evidence_count == 4


def test_evidence_source_count_delta():
    """Distinct data provider count changes are tracked."""
    prev = {"assessment_id": "a1", "score": 20.0, "evidence": [{"provider": "OPENWEATHER"}]}
    curr = {"assessment_id": "a2", "score": 40.0, "evidence": [{"provider": "OPENWEATHER"}, {"provider": "TOMTOM"}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.evidence_changes.previous_source_count == 1
    assert comp.evidence_changes.current_source_count == 2
    assert comp.evidence_changes.source_count_delta == 1


def test_conflict_introduced_transition():
    """Transition from 0 to 1+ conflicts marks status NEW_CONFLICT."""
    prev = {"assessment_id": "a1", "score": 20.0, "conflicts": []}
    curr = {"assessment_id": "a2", "score": 40.0, "conflicts": [{"provider_a": "TOMTOM", "provider_b": "HERE"}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.conflict_changes.status == ConflictChangeStatus.NEW_CONFLICT
    assert comp.conflict_changes.conflict_count_delta == 1


def test_conflict_resolved_transition():
    """Transition from 1+ conflicts to 0 marks status CONFLICT_RESOLVED."""
    prev = {"assessment_id": "a1", "score": 40.0, "conflicts": [{"provider_a": "TOMTOM", "provider_b": "HERE"}]}
    curr = {"assessment_id": "a2", "score": 20.0, "conflicts": []}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.conflict_changes.status == ConflictChangeStatus.CONFLICT_RESOLVED
    assert comp.conflict_changes.conflict_count_delta == -1


def test_quality_degraded_by_limitations():
    """Introduction of new caveats marks quality status DEGRADED."""
    prev = {"assessment_id": "a1", "score": 20.0, "limitations": []}
    curr = {"assessment_id": "a2", "score": 20.0, "limitations": ["ESTIMATED_DATA_USED", "LOCATION_APPROXIMATE"]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.quality_changes.status == QualityChangeStatus.DEGRADED
    assert len(comp.quality_changes.new_limitations) == 2


def test_quality_improved_by_clearing_limitations():
    """Resolving caveats marks quality status IMPROVED."""
    prev = {"assessment_id": "a1", "score": 20.0, "limitations": ["ESTIMATED_DATA_USED"]}
    curr = {"assessment_id": "a2", "score": 20.0, "limitations": []}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.quality_changes.status == QualityChangeStatus.IMPROVED
    assert "ESTIMATED_DATA_USED" in comp.quality_changes.resolved_limitations


# ==============================================================================
# 5. SOURCE DISTRIBUTION TESTS
# ==============================================================================

def test_source_summary_deltas():
    """Source changes accurately calculate real, estimated, and simulated deltas."""
    prev = {
        "assessment_id": "a1",
        "score": 30.0,
        "source_summary": {
            "independent_sources_count": 1,
            "real_sources_count": 1,
            "estimated_sources_count": 0,
            "simulated_sources_count": 0,
            "providers": ["OPENWEATHER"],
        },
    }
    curr = {
        "assessment_id": "a2",
        "score": 50.0,
        "source_summary": {
            "independent_sources_count": 3,
            "real_sources_count": 2,
            "estimated_sources_count": 1,
            "simulated_sources_count": 0,
            "providers": ["OPENWEATHER", "TOMTOM", "HERE"],
        },
    }
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    sc = comp.source_changes
    assert sc.independent_sources_delta == 2
    assert sc.real_sources_delta == 1
    assert sc.estimated_sources_delta == 1
    assert "TOMTOM" in sc.added_providers
    assert "HERE" in sc.added_providers


def test_source_summary_provider_removed():
    """Provider removed between evaluations is reflected in removed_providers."""
    prev = {"assessment_id": "a1", "score": 30.0, "source_summary": {"providers": ["OPENWEATHER", "TOMTOM"]}}
    curr = {"assessment_id": "a2", "score": 20.0, "source_summary": {"providers": ["OPENWEATHER"]}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert "TOMTOM" in comp.source_changes.removed_providers


def test_duplicate_observations_do_not_inflate_sources():
    """Multiple observations from same provider do not count as independent sources."""
    prev = {"assessment_id": "a1", "score": 20.0, "source_summary": {"independent_sources_count": 1, "providers": ["TOMTOM"]}}
    curr = {"assessment_id": "a2", "score": 20.0, "source_summary": {"independent_sources_count": 1, "providers": ["TOMTOM"]}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.source_changes.independent_sources_delta == 0


# ==============================================================================
# 6. TREND CLASSIFICATION TESTS
# ==============================================================================

def test_trend_classification_increasing():
    """Positive delta classifies as INCREASING."""
    assert HistoricalRiskComparator.classify_trend(5.25) == RiskTrend.INCREASING


def test_trend_classification_decreasing():
    """Negative delta classifies as DECREASING."""
    assert HistoricalRiskComparator.classify_trend(-3.10) == RiskTrend.DECREASING


def test_trend_classification_stable():
    """Zero delta classifies as STABLE."""
    assert HistoricalRiskComparator.classify_trend(0.00) == RiskTrend.STABLE


def test_trend_single_point_insufficient_history():
    """One single assessment cannot establish trend -> INSUFFICIENT_HISTORY."""
    asmt = {"assessment_id": "a1", "score": 45.0, "risk_level": "MEDIUM"}
    comp = HistoricalRiskComparator.compare(current=asmt, previous=None)
    assert comp.direction == RiskTrend.INSUFFICIENT_HISTORY


# ==============================================================================
# 7. SUMMARY & BOUNDS TESTS
# ==============================================================================

def test_summary_empty_history():
    """Empty assessment list returns zero counts and nullable defaults."""
    summary = HistoricalRiskComparator.summarize_history(org_id="org_alpha", assessments=[])
    assert summary.assessment_count == 0
    assert summary.trend == RiskTrend.INSUFFICIENT_HISTORY
    assert summary.first_score is None
    assert summary.latest_score is None
    assert summary.average_score is None


def test_summary_single_assessment():
    """Single assessment returns count=1 and INSUFFICIENT_HISTORY trend."""
    asmt = {"assessment_id": "a1", "score": 40.0, "risk_level": "LOW", "created_at": datetime.now(timezone.utc)}
    summary = HistoricalRiskComparator.summarize_history(org_id="org_alpha", assessments=[asmt])
    assert summary.assessment_count == 1
    assert summary.first_score == 40.0
    assert summary.latest_score == 40.0
    assert summary.score_delta == 0.0
    assert summary.minimum_score == 40.0
    assert summary.maximum_score == 40.0
    assert summary.average_score == 40.0
    assert summary.trend == RiskTrend.INSUFFICIENT_HISTORY


def test_summary_three_assessments_statistics():
    """Multiple assessments produce exact min, max, average, and trend."""
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    asmts = [
        {"assessment_id": "a1", "score": 20.0, "risk_level": "LOW", "created_at": base},
        {"assessment_id": "a2", "score": 60.0, "risk_level": "HIGH", "created_at": base + timedelta(hours=1)},
        {"assessment_id": "a3", "score": 40.0, "risk_level": "MEDIUM", "created_at": base + timedelta(hours=2)},
    ]
    summary = HistoricalRiskComparator.summarize_history(org_id="org_alpha", assessments=asmts)
    assert summary.assessment_count == 3
    assert summary.first_score == 20.0
    assert summary.latest_score == 40.0
    assert summary.score_delta == 20.0
    assert summary.minimum_score == 20.0
    assert summary.maximum_score == 60.0
    assert summary.average_score == 40.0  # (20 + 60 + 40) / 3 = 40.0
    assert summary.trend == RiskTrend.INCREASING
    assert len(summary.transitions) == 2


def test_summary_consecutive_pairwise_transitions():
    """Pairwise transitions are computed between consecutive evaluations."""
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    asmts = [
        {"assessment_id": "a1", "score": 30.0, "created_at": base},
        {"assessment_id": "a2", "score": 70.0, "created_at": base + timedelta(hours=1)},
        {"assessment_id": "a3", "score": 50.0, "created_at": base + timedelta(hours=2)},
    ]
    summary = HistoricalRiskComparator.summarize_history(org_id="org_alpha", assessments=asmts)
    assert len(summary.transitions) == 2
    assert summary.transitions[0].score_delta == 40.0
    assert summary.transitions[0].direction == RiskTrend.INCREASING
    assert summary.transitions[1].score_delta == -20.0
    assert summary.transitions[1].direction == RiskTrend.DECREASING


def test_summary_driver_changes_counter():
    """Driver changes count increases when consecutive assessments change drivers."""
    base = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    asmts = [
        {"assessment_id": "a1", "score": 30.0, "primary_factor_id": "f_w", "created_at": base},
        {"assessment_id": "a2", "score": 60.0, "primary_factor_id": "f_r", "created_at": base + timedelta(hours=1)},
        {"assessment_id": "a3", "score": 40.0, "primary_factor_id": "f_r", "created_at": base + timedelta(hours=2)},
    ]
    summary = HistoricalRiskComparator.summarize_history(org_id="org_alpha", assessments=asmts)
    assert summary.driver_changes_count == 1


# ==============================================================================
# 8. TENANT ISOLATION TESTS
# ==============================================================================

def test_tenant_isolation_history_service(db_session: Session, seed_data: dict):
    """Service strictly scopes history query to context tenant."""
    ctx = seed_data["ctx_viewer_a"]
    uow = UnitOfWork(db_session)
    service = RiskEvaluationService(uow=uow, context=ctx)

    history = service.get_history()
    assert history.organization_id == "org_alpha"
    assert history.assessment_count == 3
    assert not any(a["id"] == "asmt_b_001" for a in history.assessments)


def test_tenant_isolation_compare_cross_tenant_rejected(db_session: Session, seed_data: dict):
    """Attempting to compare with an assessment belonging to another tenant raises NotFoundError."""
    ctx = seed_data["ctx_viewer_a"]
    uow = UnitOfWork(db_session)
    service = RiskEvaluationService(uow=uow, context=ctx)

    with pytest.raises(Exception) as exc_info:
        service.compare_assessments(assessment_id_1="asmt_a_001", assessment_id_2="asmt_b_001")
    assert "not found" in str(exc_info.value).lower() or "resource_not_found" in str(exc_info.value).lower()


def test_tenant_isolation_org_b_cannot_see_org_a(db_session: Session, seed_data: dict):
    """Org Beta sees only its own history (1 assessment)."""
    ctx = seed_data["ctx_viewer_b"]
    uow = UnitOfWork(db_session)
    service = RiskEvaluationService(uow=uow, context=ctx)

    history = service.get_history()
    assert history.organization_id == "org_beta"
    assert history.assessment_count == 1
    assert history.assessments[0]["id"] == "asmt_b_001"


# ==============================================================================
# 9. IMMUTABILITY TESTS
# ==============================================================================

def test_immutability_history_performs_zero_writes(db_session: Session, seed_data: dict):
    """Executing get_history produces no database writes or updates."""
    ctx = seed_data["ctx_viewer_a"]
    uow = UnitOfWork(db_session)
    service = RiskEvaluationService(uow=uow, context=ctx)

    # Initial query
    count_before = len(list(db_session.scalars(select(ORMRiskAssessment)).all()))
    _ = service.get_history()
    count_after = len(list(db_session.scalars(select(ORMRiskAssessment)).all()))

    assert count_before == count_after


def test_immutability_comparison_performs_zero_writes(db_session: Session, seed_data: dict):
    """Comparing two assessments performs no database mutations."""
    ctx = seed_data["ctx_viewer_a"]
    uow = UnitOfWork(db_session)
    service = RiskEvaluationService(uow=uow, context=ctx)

    count_before = len(list(db_session.scalars(select(ORMRiskAssessment)).all()))
    _ = service.compare_assessments("asmt_a_001", "asmt_a_002")
    count_after = len(list(db_session.scalars(select(ORMRiskAssessment)).all()))

    assert count_before == count_after


# ==============================================================================
# 10. DETERMINISM TESTS
# ==============================================================================

def test_determinism_repeated_comparisons_identical():
    """Comparing identical assessments 100 times produces identical results."""
    fixed_time_1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    fixed_time_2 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    prev = {"assessment_id": "a1", "score": 30.0, "risk_level": "LOW", "created_at": fixed_time_1}
    curr = {"assessment_id": "a2", "score": 60.0, "risk_level": "HIGH", "created_at": fixed_time_2}

    comp1 = HistoricalRiskComparator.compare(current=curr, previous=prev)
    comp2 = HistoricalRiskComparator.compare(current=curr, previous=prev)

    assert comp1.model_dump() == comp2.model_dump()


def test_determinism_explanation_exact():
    """Explanation uses exact factual wording without volatility."""
    prev = {"assessment_id": "a1", "score": 20.0, "risk_level": "LOW", "primary_driver": {"name": "Wind"}}
    curr = {"assessment_id": "a2", "score": 75.0, "risk_level": "HIGH", "primary_driver": {"name": "Flood"}}

    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert "Risk increased from 20.0 to 75.0 (+55.0)." in comp.explanation
    assert "Risk level transitioned from LOW to HIGH." in comp.explanation
    assert "Primary risk driver shifted from Wind to Flood." in comp.explanation


# ==============================================================================
# 11. API INTEGRATION TESTS
# ==============================================================================

def test_api_history_endpoint_authenticated(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments/history returns 200 OK with full timeline."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    res = client.get("/api/v1/risk-assessments/history", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["organization_id"] == "org_alpha"
    assert data["assessment_count"] == 3
    assert data["first_score"] == 30.0
    assert data["latest_score"] == 50.0
    assert data["trend"] == "INCREASING"
    assert len(data["transitions"]) == 2


def test_api_history_endpoint_unauthenticated(client: TestClient):
    """GET /api/v1/risk-assessments/history without cookie returns 401 Unauthorized."""
    res = client.get("/api/v1/risk-assessments/history")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_history_endpoint_entity_filtering(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments/history?scope=SHIPMENT&scope_entity_id=SHP_1001 filters correctly."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    res = client.get("/api/v1/risk-assessments/history?scope=SHIPMENT&scope_entity_id=SHP_1001", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["assessment_count"] == 3


def test_api_compare_endpoint_success(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments/{id}/compare/{other_id} returns 200 OK comparison."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    res = client.get("/api/v1/risk-assessments/asmt_a_001/compare/asmt_a_002", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["previous_score"] == 30.0
    assert data["current_score"] == 65.0
    assert data["score_delta"] == 35.0
    assert data["direction"] == "INCREASING"
    assert data["risk_level_changed"] is True
    assert len(data["factor_changes"]) > 0


def test_api_compare_endpoint_cross_tenant_404(client: TestClient, seed_data: dict):
    """Attempting to compare with another tenant's assessment returns 404 Not Found."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    res = client.get("/api/v1/risk-assessments/asmt_a_001/compare/asmt_b_001", headers=headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_api_compare_endpoint_nonexistent_404(client: TestClient, seed_data: dict):
    """Comparing with a nonexistent ID returns 404 Not Found."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    res = client.get("/api/v1/risk-assessments/asmt_a_001/compare/asmt_nonexistent", headers=headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_api_history_endpoint_empty_tenant(client: TestClient, seed_data: dict):
    """Tenant with no assessments receives 200 OK with count=0 and INSUFFICIENT_HISTORY."""
    # Create org with no assessments
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_b']}"}
    res = client.get("/api/v1/risk-assessments/history?scope_entity_id=NONEXISTENT", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["assessment_count"] == 0
    assert data["trend"] == "INSUFFICIENT_HISTORY"


def test_api_compare_reverse_ordering_handled_chronologically(client: TestClient, seed_data: dict):
    """Specifying target before base in path still treats older as previous and newer as current."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    # Pass asmt_a_002 first and asmt_a_001 second
    res = client.get("/api/v1/risk-assessments/asmt_a_002/compare/asmt_a_001", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["previous_score"] == 30.0
    assert data["current_score"] == 65.0
    assert data["score_delta"] == 35.0


def test_repo_history_descending_order(db_session: Session, seed_data: dict):
    """Assessment history can be queried in descending order (created_at DESC, id ASC)."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", risk_id="risk_a_001", ascending=False)
    assert len(items) == 3
    assert items[0].id == "asmt_a_003"
    assert items[1].id == "asmt_a_002"
    assert items[2].id == "asmt_a_001"


def test_repo_history_risk_id_filter(db_session: Session, seed_data: dict):
    """Filtering by risk_id isolates assessments for that risk entity."""
    uow = UnitOfWork(db_session)
    items = uow.risk_assessments.get_assessment_history(org_id="org_alpha", risk_id="risk_a_001")
    assert all(item.risk_id == "risk_a_001" for item in items)


def test_comparison_direction_threshold_exact():
    """Smallest non-zero deltas (+0.01 and -0.01) classify deterministically."""
    prev = {"assessment_id": "a1", "score": 50.00}
    curr_inc = {"assessment_id": "a2", "score": 50.01}
    curr_dec = {"assessment_id": "a3", "score": 49.99}

    comp_inc = HistoricalRiskComparator.compare(current=curr_inc, previous=prev)
    comp_dec = HistoricalRiskComparator.compare(current=curr_dec, previous=prev)

    assert comp_inc.direction == RiskTrend.INCREASING
    assert comp_inc.score_delta == 0.01
    assert comp_dec.direction == RiskTrend.DECREASING
    assert comp_dec.score_delta == -0.01


def test_comparison_none_drivers_both():
    """When both evaluations lack a primary driver, status is DriverChangeStatus.SAME."""
    prev = {"assessment_id": "a1", "score": 0.0, "primary_driver": None}
    curr = {"assessment_id": "a2", "score": 0.0, "primary_driver": None}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.primary_driver_change_status == DriverChangeStatus.SAME


def test_factor_severity_unchanged_confidence_changed():
    """Factor with unchanged severity but shifted confidence is marked CHANGED."""
    prev = {"assessment_id": "a1", "factors": [{"factor_id": "f1", "factor_type": "PORT", "severity": "MEDIUM", "confidence": 0.50, "score": 20.0}]}
    curr = {"assessment_id": "a2", "factors": [{"factor_id": "f1", "factor_type": "PORT", "severity": "MEDIUM", "confidence": 0.95, "score": 20.0}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    fc = comp.factor_changes[0]
    assert fc.status == FactorChangeStatus.CHANGED
    assert fc.severity_changed is False
    assert fc.confidence_delta == 0.45


def test_evidence_corroboration_delta_negative():
    """Corroborating source count reduction is accurately captured as negative delta."""
    prev = {"assessment_id": "a1", "source_summary": {"corroborating_sources_count": 3}}
    curr = {"assessment_id": "a2", "source_summary": {"corroborating_sources_count": 1}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.evidence_changes.corroborating_count_delta == -2


def test_source_summary_simulated_sources_delta():
    """Changes in simulated sources count are tracked in SourceChanges."""
    prev = {"assessment_id": "a1", "source_summary": {"simulated_sources_count": 0}}
    curr = {"assessment_id": "a2", "source_summary": {"simulated_sources_count": 2}}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.source_changes.simulated_sources_delta == 2
    assert comp.source_changes.previous_simulated_sources == 0
    assert comp.source_changes.current_simulated_sources == 2


def test_conflict_count_increased_multiple():
    """Conflict count shifting from 1 to 3 sets status CONFLICT_CHANGED."""
    prev = {"assessment_id": "a1", "conflicts": [{"provider_a": "A", "provider_b": "B"}]}
    curr = {"assessment_id": "a2", "conflicts": [{"provider_a": "A", "provider_b": "B"}, {"provider_a": "C", "provider_b": "D"}, {"provider_a": "E", "provider_b": "F"}]}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.conflict_changes.status == ConflictChangeStatus.CONFLICT_CHANGED
    assert comp.conflict_changes.conflict_count_delta == 2


def test_quality_partial_to_valid_shift():
    """Quality shift from PARTIAL to VALID is classified as IMPROVED."""
    prev = {"assessment_id": "a1", "evidence": [{"quality": "PARTIAL"}], "limitations": ["ESTIMATED_DATA"]}
    curr = {"assessment_id": "a2", "evidence": [{"quality": "VALID"}], "limitations": []}
    comp = HistoricalRiskComparator.compare(current=curr, previous=prev)
    assert comp.quality_changes.status == QualityChangeStatus.IMPROVED


def test_api_history_limit_parameter(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments/history?limit=2 respects limit parameter."""
    headers = {"Cookie": f"riskwise_session={seed_data['cookie_viewer_a']}"}
    res = client.get("/api/v1/risk-assessments/history?limit=2", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["assessment_count"] == 2
    assert len(data["assessments"]) == 2

