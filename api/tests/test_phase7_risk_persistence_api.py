"""Comprehensive focused test suite for Phase 7 Step 4:
Risk Persistence & API Integration.

Validates:
1. Repository CRUD, tenant isolation, and deterministic fingerprint lookups
2. Persistence adapter mapping between pure domain RiskAssessment and SQLAlchemy ORM models
3. Secret scrubbing from evidence traces (no API keys, tokens, or credentials persisted)
4. Transactional atomicity: all-or-nothing writes and automatic rollback on failure
5. Deterministic idempotency: repeated evaluations with identical signals avoid duplicates
6. Temporal / version semantics: historical assessments are preserved
7. Multi-tenant isolation: strict org_id boundary on every query and mutation
8. API endpoints: /evaluate, /latest, /{id}/detail, and /{id} with RBAC enforcement
9. End-to-end integration: NormalizedRiskSignal -> Engine -> Persistence -> API response
10. Strict domain boundaries: probability=None, impact=None, no ML/LLM scoring
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import pytest
from fastapi import status
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.integrations.canonical import (
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.main import app
from app.models.risk import Risk as ORMRisk
from app.models.risk import RiskAssessment as ORMRiskAssessment
from app.models.risk import RiskFactor as ORMRiskFactor
from app.models.tenancy import Organization, User
from app.normalization.contract import (
    EntityType,
    NormalizedRiskSignal,
    SignalDomain,
    SignalStatus,
    SignalType,
)
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    FactorContribution,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
)
from app.risk_engine.evidence import EvidenceRelevance, RiskEvidence
from app.risk_engine.persistence import (
    RiskAssessmentPersistenceAdapter,
    scrub_secrets,
)
from app.risk_engine.pipeline import BaselineRiskEngine
from app.services.risk_evaluation_service import RiskEvaluationService
from app.services.session_service import MemorySessionStore, SessionService, get_session_service


# ==============================================================================
# FIXTURES & TEST SETUP
# ==============================================================================

@pytest.fixture(scope="function")
def test_db():
    """Isolated in-memory SQLite database session fixture."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
def client(test_db: Session, session_service: SessionService):
    """FastAPI TestClient with overridden database and session dependencies."""
    def override_get_db():
        try:
            yield test_db
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
def seed_data(test_db: Session, session_service: SessionService):
    """Seed test organizations, users across roles, and existing baseline risks."""
    org_a = Organization(id="org_alpha", name="Alpha Logistics Inc", slug="alpha-logistics", is_active=True)
    org_b = Organization(id="org_beta", name="Beta Global Ltd", slug="beta-global", is_active=True)
    test_db.add_all([org_a, org_b])
    test_db.commit()

    # Org A users
    viewer_a = User(id="usr_view_a", org_id="org_alpha", email="viewer@alpha.test", full_name="Viewer A", role="Viewer", is_active=True)
    analyst_a = User(id="usr_analyst_a", org_id="org_alpha", email="analyst@alpha.test", full_name="Analyst A", role="Analyst", is_active=True)
    admin_a = User(id="usr_admin_a", org_id="org_alpha", email="admin@alpha.test", full_name="Admin A", role="Admin", is_active=True)

    # Org B user
    analyst_b = User(id="usr_analyst_b", org_id="org_beta", email="analyst@beta.test", full_name="Analyst B", role="Analyst", is_active=True)

    test_db.add_all([viewer_a, analyst_a, admin_a, analyst_b])
    test_db.commit()

    # Pre-existing risk in Org A
    risk_a = ORMRisk(
        id="risk_alpha_01",
        org_id="org_alpha",
        title="Red Sea Lane Disruption",
        risk_type="GEOPOLITICAL",
        severity="HIGH",
        location="Bab-el-Mandeb",
        probability=None,
        impact=None,
        risk_score=75.0,
        confidence=0.9,
        trend="STABLE",
        source="DETERMINISTIC_ENGINE",
    )
    # Pre-existing risk in Org B
    risk_b = ORMRisk(
        id="risk_beta_01",
        org_id="org_beta",
        title="Panama Canal Low Draft",
        risk_type="CLIMATIC",
        severity="CRITICAL",
        location="Panama Canal",
        probability=None,
        impact=None,
        risk_score=90.0,
        confidence=0.95,
        trend="INCREASING",
        source="DETERMINISTIC_ENGINE",
    )
    test_db.add_all([risk_a, risk_b])
    test_db.commit()

    def make_cookie(user: User) -> str:
        s = session_service.create_session(
            user_id=user.id,
            role=user.role,
            organization_id=user.org_id,
            ttl_seconds=3600,
        )
        return s.session_id

    return {
        "org_a": org_a,
        "org_b": org_b,
        "viewer_a_cookie": make_cookie(viewer_a),
        "analyst_a_cookie": make_cookie(analyst_a),
        "admin_a_cookie": make_cookie(admin_a),
        "analyst_b_cookie": make_cookie(analyst_b),
        "risk_a": risk_a,
        "risk_b": risk_b,
    }


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
        status=SignalStatus.ACTIVE,
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
# 1. REPOSITORY TESTS (8 tests)
# ==============================================================================

def test_repo_create_and_get_assessment(test_db: Session, seed_data: dict):
    """Repository creates and retrieves an assessment strictly within tenant boundary."""
    uow = UnitOfWork(test_db)
    org_id = "org_alpha"
    risk_id = seed_data["risk_a"].id

    assessment = ORMRiskAssessment(
        id="ass_test_01",
        org_id=org_id,
        risk_id=risk_id,
        assessor_type="DETERMINISTIC_ENGINE",
        assessor_id="riskwise-baseline-risk-engine-2.0",
        methodology="2.0-baseline-deterministic",
        findings={"deterministic_fingerprint": "fp_01", "scope": "GLOBAL"},
        score=72.5,
        confidence=0.9,
    )
    uow.risk_assessments.create(assessment)

    retrieved = uow.risk_assessments.get_assessment(org_id=org_id, assessment_id="ass_test_01")
    assert retrieved is not None
    assert retrieved.id == "ass_test_01"
    assert retrieved.score == 72.5
    assert retrieved.findings["deterministic_fingerprint"] == "fp_01"


def test_repo_get_assessment_tenant_isolation(test_db: Session, seed_data: dict):
    """Repository masks existence (returns None) when querying with cross-tenant org_id."""
    uow = UnitOfWork(test_db)
    assessment = ORMRiskAssessment(
        id="ass_alpha_secret",
        org_id="org_alpha",
        risk_id=seed_data["risk_a"].id,
        score=65.0,
        findings={"deterministic_fingerprint": "fp_alpha"},
    )
    uow.risk_assessments.create(assessment)

    # Org B queries Org A assessment -> None
    assert uow.risk_assessments.get_assessment(org_id="org_beta", assessment_id="ass_alpha_secret") is None
    # BaseRepository.get also masks cross-tenant
    assert uow.risk_assessments.get("ass_alpha_secret", org_id="org_beta") is None


def test_repo_find_by_fingerprint(test_db: Session, seed_data: dict):
    """Repository finds an assessment by its deterministic fingerprint within tenant scope."""
    uow = UnitOfWork(test_db)
    assessment = ORMRiskAssessment(
        id="ass_fp_match",
        org_id="org_alpha",
        risk_id=seed_data["risk_a"].id,
        score=80.0,
        findings={"deterministic_fingerprint": "sha256_exact_match_123"},
    )
    uow.risk_assessments.create(assessment)

    found = uow.risk_assessments.find_by_fingerprint(org_id="org_alpha", fingerprint="sha256_exact_match_123")
    assert found is not None
    assert found.id == "ass_fp_match"

    # Nonexistent fingerprint returns None
    assert uow.risk_assessments.find_by_fingerprint(org_id="org_alpha", fingerprint="nonexistent_fp") is None


def test_repo_find_by_fingerprint_tenant_isolation(test_db: Session, seed_data: dict):
    """Repository fingerprint lookup never matches cross-tenant records."""
    uow = UnitOfWork(test_db)
    assessment = ORMRiskAssessment(
        id="ass_org_a_fp",
        org_id="org_alpha",
        risk_id=seed_data["risk_a"].id,
        score=55.0,
        findings={"deterministic_fingerprint": "shared_fp_hash"},
    )
    uow.risk_assessments.create(assessment)

    # Org B should not find Org A's fingerprint
    assert uow.risk_assessments.find_by_fingerprint(org_id="org_beta", fingerprint="shared_fp_hash") is None


def test_repo_get_latest_for_risk(test_db: Session, seed_data: dict):
    """Repository returns the chronologically latest assessment for a given risk."""
    uow = UnitOfWork(test_db)
    risk_id = seed_data["risk_a"].id
    t1 = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)

    a1 = ORMRiskAssessment(id="ass_older", org_id="org_alpha", risk_id=risk_id, score=50.0, created_at=t1)
    a2 = ORMRiskAssessment(id="ass_newer", org_id="org_alpha", risk_id=risk_id, score=85.0, created_at=t2)
    uow.risk_assessments.create(a1)
    uow.risk_assessments.create(a2)

    latest = uow.risk_assessments.get_latest_for_risk(org_id="org_alpha", risk_id=risk_id)
    assert latest is not None
    assert latest.id == "ass_newer"
    assert latest.score == 85.0


def test_repo_get_latest_for_entity(test_db: Session, seed_data: dict):
    """Repository retrieves latest assessment for a given scope and target entity ID."""
    uow = UnitOfWork(test_db)
    risk_id = seed_data["risk_a"].id
    t1 = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 9, 11, 0, tzinfo=timezone.utc)

    a1 = ORMRiskAssessment(
        id="ass_ship_01_old",
        org_id="org_alpha",
        risk_id=risk_id,
        score=40.0,
        findings={"scope": "SHIPMENT", "scope_entity_id": "ship_100"},
        created_at=t1,
    )
    a2 = ORMRiskAssessment(
        id="ass_ship_01_new",
        org_id="org_alpha",
        risk_id=risk_id,
        score=78.0,
        findings={"scope": "SHIPMENT", "scope_entity_id": "ship_100"},
        created_at=t2,
    )
    uow.risk_assessments.create(a1)
    uow.risk_assessments.create(a2)

    latest = uow.risk_assessments.get_latest_for_entity(org_id="org_alpha", scope="SHIPMENT", scope_entity_id="ship_100")
    assert latest is not None
    assert latest.id == "ass_ship_01_new"
    assert latest.score == 78.0


def test_repo_get_latest_for_org(test_db: Session, seed_data: dict):
    """Repository retrieves most recent assessment for organization or by scope."""
    uow = UnitOfWork(test_db)
    risk_id = seed_data["risk_a"].id
    t1 = datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 9, 13, 0, tzinfo=timezone.utc)

    a1 = ORMRiskAssessment(id="ass_g1", org_id="org_alpha", risk_id=risk_id, score=50.0, findings={"scope": "GLOBAL"}, created_at=t1)
    a2 = ORMRiskAssessment(id="ass_g2", org_id="org_alpha", risk_id=risk_id, score=65.0, findings={"scope": "GLOBAL"}, created_at=t2)
    uow.risk_assessments.create(a1)
    uow.risk_assessments.create(a2)

    latest_any = uow.risk_assessments.get_latest_for_org(org_id="org_alpha")
    assert latest_any is not None
    assert latest_any.id == "ass_g2"

    latest_scope = uow.risk_assessments.get_latest_for_org(org_id="org_alpha", scope="GLOBAL")
    assert latest_scope is not None
    assert latest_scope.id == "ass_g2"


def test_repo_list_assessments_for_org_filtering(test_db: Session, seed_data: dict):
    """Repository list method applies filters and strict tenant boundary."""
    uow = UnitOfWork(test_db)
    risk_a_id = seed_data["risk_a"].id
    risk_b_id = seed_data["risk_b"].id

    a1 = ORMRiskAssessment(id="a_alpha_1", org_id="org_alpha", risk_id=risk_a_id, assessor_type="DETERMINISTIC_ENGINE", score=60.0)
    a2 = ORMRiskAssessment(id="a_alpha_2", org_id="org_alpha", risk_id=risk_a_id, assessor_type="HUMAN_ANALYST", score=70.0)
    b1 = ORMRiskAssessment(id="a_beta_1", org_id="org_beta", risk_id=risk_b_id, assessor_type="DETERMINISTIC_ENGINE", score=80.0)
    uow.risk_assessments.create(a1)
    uow.risk_assessments.create(a2)
    uow.risk_assessments.create(b1)

    items, total = uow.risk_assessments.list_assessments_for_org(org_id="org_alpha")
    assert total == 2
    assert all(i.org_id == "org_alpha" for i in items)

    filtered_items, f_total = uow.risk_assessments.list_assessments_for_org(
        org_id="org_alpha", assessor_type="DETERMINISTIC_ENGINE"
    )
    assert f_total == 1
    assert filtered_items[0].id == "a_alpha_1"


# ==============================================================================
# 2. PERSISTENCE ADAPTER TESTS (10 tests)
# ==============================================================================

def test_adapter_to_orm_roundtrip(seed_data: dict):
    """Adapter maps domain RiskAssessment to ORM models and faithfully reconstructs it."""
    engine = BaselineRiskEngine()
    signals = [make_test_signal(signal_id="sig_ HongKong", org_id="org_alpha")]
    ctx = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc),
        signals=signals,
        scope="PORT",
        scope_entity_id="port_hk_01",
        scope_entity_type=EntityType.PORT,
    )
    domain_assessment = engine.evaluate(ctx)

    # Map to ORM
    orm_ass, orm_factors = RiskAssessmentPersistenceAdapter.to_orm(
        domain_assessment,
        risk_id=seed_data["risk_a"].id,
    )
    assert orm_ass.id == domain_assessment.assessment_id
    assert orm_ass.org_id == "org_alpha"
    assert orm_ass.score == domain_assessment.score
    assert len(orm_factors) == len(domain_assessment.factors)

    # Reconstruct back to domain
    reconstructed = RiskAssessmentPersistenceAdapter.from_orm(orm_ass, orm_factors)
    assert reconstructed.assessment_id == domain_assessment.assessment_id
    assert reconstructed.organization_id == domain_assessment.organization_id
    assert reconstructed.scope == domain_assessment.scope
    assert reconstructed.score == domain_assessment.score
    assert reconstructed.risk_level == domain_assessment.risk_level
    assert reconstructed.fingerprint == domain_assessment.fingerprint
    assert len(reconstructed.factors) == len(domain_assessment.factors)


def test_adapter_preserves_deterministic_identities(seed_data: dict):
    """Adapter preserves deterministic UUIDs for assessment, factors, and evidence."""
    engine = BaselineRiskEngine()
    signals = [make_test_signal(signal_id="sig_det_01", org_id="org_alpha")]
    ctx = RiskEvaluationContext(
        organization_id="org_alpha",
        evaluation_time=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
        signals=signals,
    )
    assessment = engine.evaluate(ctx)

    orm_ass, orm_factors = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    reconstructed = RiskAssessmentPersistenceAdapter.from_orm(orm_ass, orm_factors)

    assert reconstructed.assessment_id == assessment.assessment_id
    for orig_f, recon_f in zip(assessment.factors, reconstructed.factors):
        assert recon_f.factor_id == orig_f.factor_id
        assert set(recon_f.evidence_ids) == set(orig_f.evidence_ids)


def test_adapter_factor_persistence_attributes(seed_data: dict):
    """Adapter maps all factor metadata, severity, weight, score, and rank."""
    engine = BaselineRiskEngine()
    signals = [make_test_signal(signal_id="sig_fact_attr", org_id="org_alpha")]
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=datetime.now(timezone.utc), signals=signals)
    assessment = engine.evaluate(ctx)

    _, orm_factors = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    assert len(orm_factors) > 0
    f0 = orm_factors[0]
    assert f0.name != ""
    assert f0.category is not None
    assert f0.weight >= 0.0
    assert f0.score >= 0.0
    assert "evidence_ids" in f0.evidence_json
    assert "severity" in f0.evidence_json
    assert "confidence" in f0.evidence_json


def test_adapter_evidence_persistence_attributes(seed_data: dict):
    """Adapter maps evidence source, provider, quality, coordinates, and observation time."""
    engine = BaselineRiskEngine()
    signals = [
        make_test_signal(
            signal_id="sig_ev_attrs",
            org_id="org_alpha",
            location_name="Singapore Anchorage",
            latitude=1.29027,
            longitude=103.851959,
        )
    ]
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=datetime.now(timezone.utc), signals=signals)
    assessment = engine.evaluate(ctx)

    orm_ass, _ = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    evidence_list = orm_ass.findings.get("evidence", [])
    assert len(evidence_list) > 0
    ev0 = evidence_list[0]
    assert ev0["signal_id"] == "sig_ev_attrs"
    assert ev0["location_name"] == "Singapore Anchorage"
    assert ev0["latitude"] == 1.29027
    assert ev0["longitude"] == 103.851959
    assert ev0["quality"] == "VALID"
    assert ev0["source_type"] == "REAL"


def test_adapter_evidence_factor_bi_directional_linkage(seed_data: dict):
    """Adapter maintains factor_id on evidence and evidence_ids on factors."""
    engine = BaselineRiskEngine()
    signals = [make_test_signal(signal_id="sig_linkage", org_id="org_alpha")]
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=datetime.now(timezone.utc), signals=signals)
    assessment = engine.evaluate(ctx)

    orm_ass, orm_factors = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    reconstructed = RiskAssessmentPersistenceAdapter.from_orm(orm_ass, orm_factors)

    for factor in reconstructed.factors:
        assert len(factor.evidence_ids) > 0
        for ev in factor.evidence:
            assert ev.factor_id == factor.factor_id
            assert ev.evidence_id in factor.evidence_ids


def test_adapter_source_summary_persistence(seed_data: dict):
    """Adapter preserves AssessmentSourceSummary breakdown across persistence boundary."""
    engine = BaselineRiskEngine()
    signals = [
        make_test_signal(signal_id="sig_s1", org_id="org_alpha", provider="noaa", source_type=EventSourceType.REAL),
        make_test_signal(signal_id="sig_s2", org_id="org_alpha", provider="copernicus", source_type=EventSourceType.ESTIMATED),
    ]
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=datetime.now(timezone.utc), signals=signals)
    assessment = engine.evaluate(ctx)

    orm_ass, _ = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    reconstructed = RiskAssessmentPersistenceAdapter.from_orm(orm_ass)

    assert reconstructed.source_summary is not None
    assert reconstructed.source_summary.evidence_count == assessment.source_summary.evidence_count
    assert reconstructed.source_summary.independent_sources_count == assessment.source_summary.independent_sources_count
    assert reconstructed.source_summary.real_sources_count == assessment.source_summary.real_sources_count
    assert reconstructed.source_summary.estimated_sources_count == assessment.source_summary.estimated_sources_count


def test_adapter_conflicts_and_limitations_persistence(seed_data: dict):
    """Adapter persists limitations and detected multi-source conflict records."""
    engine = BaselineRiskEngine()
    signals = [
        make_test_signal(
            signal_id="sig_conflict_test",
            org_id="org_alpha",
            has_conflict=True,
            quality=EventQuality.PARTIAL,
        )
    ]
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=datetime.now(timezone.utc), signals=signals)
    assessment = engine.evaluate(ctx)

    orm_ass, _ = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    reconstructed = RiskAssessmentPersistenceAdapter.from_orm(orm_ass)

    assert len(reconstructed.limitations) > 0
    assert len(reconstructed.conflicts) > 0
    assert reconstructed.limitations == assessment.limitations


def test_adapter_explanation_persistence(seed_data: dict):
    """Adapter persists structured deterministic RiskExplanation without loss."""
    engine = BaselineRiskEngine()
    signals = [make_test_signal(signal_id="sig_exp", org_id="org_alpha")]
    ctx = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=datetime.now(timezone.utc), signals=signals)
    assessment = engine.evaluate(ctx)

    orm_ass, _ = RiskAssessmentPersistenceAdapter.to_orm(assessment, risk_id="risk_01")
    reconstructed = RiskAssessmentPersistenceAdapter.from_orm(orm_ass)

    assert reconstructed.explanation is not None
    summary = (
        reconstructed.explanation.summary
        if hasattr(reconstructed.explanation, "summary")
        else reconstructed.explanation.get("summary")
    )
    assert "Overall Risk" in summary or "assessed at" in summary


def test_adapter_secret_scrubbing_authorization_headers():
    """Adapter automatically scrubs authorization tokens and cookies from dictionary structures."""
    dirty_data = {
        "provider": "noaa",
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsIn...",
        "access_token": "secret_token_12345",
        "cookie": "session=secret_session_abc",
        "nested": {
            "api_key": "raw_api_key_xyz",
            "safe_metric": 42.0,
        },
    }
    cleaned = scrub_secrets(dirty_data)
    assert cleaned["Authorization"] == "[REDACTED]"
    assert cleaned["access_token"] == "[REDACTED]"
    assert cleaned["cookie"] == "[REDACTED]"
    assert cleaned["nested"]["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["safe_metric"] == 42.0


def test_adapter_secret_scrubbing_api_keys_and_passwords():
    """Adapter redacts passwords, client secrets, and api keys embedded in evidence metadata."""
    dirty_evidence = {
        "client_secret": "super_secret_oauth_client_secret",
        "password": "db_password_123",
        "token": "ghp_xxxxxxxxxxxx",
        "safe_flag": True,
    }
    cleaned = scrub_secrets(dirty_evidence)
    assert cleaned["client_secret"] == "[REDACTED]"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["token"] == "[REDACTED]"
    assert cleaned["safe_flag"] is True


# ==============================================================================
# 3. TRANSACTION SAFETY & ATOMICITY TESTS (6 tests)
# ==============================================================================

def test_transaction_successful_commit(test_db: Session, seed_data: dict):
    """Evaluation service commits parent risk, assessment, and factors in a single transaction."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_01"})()

    signals = [make_test_signal(signal_id="sig_tx_success", org_id="org_alpha")]
    assessment, detail, is_hit = service.evaluate_and_persist(
        signals=signals,
        scope="GLOBAL",
    )
    assert is_hit is False
    assert detail["id"] == assessment.assessment_id

    # Verify rows in DB
    persisted_ass = test_db.get(ORMRiskAssessment, assessment.assessment_id)
    assert persisted_ass is not None
    assert persisted_ass.score == assessment.score

    persisted_factors = list(test_db.scalars(select(ORMRiskFactor).where(ORMRiskFactor.risk_id == persisted_ass.risk_id)).all())
    assert len(persisted_factors) > 0


def test_transaction_rollback_on_factor_failure(test_db: Session, seed_data: dict):
    """An error persisting factors causes an automatic rollback of the entire assessment transaction."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_02"})()

    # Monkeypatch session.merge to simulate database failure on factor insert
    original_merge = uow.session.merge

    def broken_merge(obj):
        if isinstance(obj, ORMRiskFactor):
            raise RuntimeError("Simulated Database I/O Failure while saving factor")
        return original_merge(obj)

    uow.session.merge = broken_merge

    signals = [make_test_signal(signal_id="sig_tx_fail_factor", org_id="org_alpha")]
    with pytest.raises(RuntimeError, match="Simulated Database I/O Failure"):
        service.evaluate_and_persist(signals=signals, scope="GLOBAL")

    # Assert NO partial assessment was left in the database
    assessments_count = test_db.scalar(select(func.count()).select_from(ORMRiskAssessment))
    assert assessments_count == 0


def test_transaction_rollback_on_assessment_failure(test_db: Session, seed_data: dict):
    """An error creating assessment record rolls back all associated changes."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_03"})()

    original_create = uow.risk_assessments.create

    def broken_create(entity, auto_commit=False):
        raise RuntimeError("Simulated Disk Full Failure on assessment write")

    uow.risk_assessments.create = broken_create

    signals = [make_test_signal(signal_id="sig_tx_fail_ass", org_id="org_alpha")]
    with pytest.raises(RuntimeError, match="Simulated Disk Full Failure"):
        service.evaluate_and_persist(signals=signals, scope="GLOBAL")

    assert test_db.scalar(select(func.count()).select_from(ORMRiskAssessment)) == 0


def test_transaction_no_partial_records_on_exception(test_db: Session, seed_data: dict):
    """Table row counts for RiskAssessment and RiskFactor remain strictly zero after an error."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_04"})()

    # Attempt evaluation with invalid signals payload
    with pytest.raises(Exception):
        service.evaluate_and_persist(signals="not_a_list", scope="GLOBAL")

    assert test_db.scalar(select(func.count()).select_from(ORMRiskAssessment)) == 0
    assert test_db.scalar(select(func.count()).select_from(ORMRiskFactor)) == 0


def test_transaction_unit_of_work_context_manager_safety(test_db: Session, seed_data: dict):
    """UnitOfWork context manager automatically triggers rollback on unhandled exception."""
    uow = UnitOfWork(test_db)
    try:
        with uow:
            ass = ORMRiskAssessment(
                id="ass_uow_fail",
                org_id="org_alpha",
                risk_id=seed_data["risk_a"].id,
                score=45.0,
            )
            uow.risk_assessments.create(ass, auto_commit=False)
            raise ValueError("Intentional business rule failure")
    except ValueError:
        pass

    # Verify assessment was NOT persisted
    assert test_db.get(ORMRiskAssessment, "ass_uow_fail") is None


def test_transaction_parent_risk_metrics_updated_atomically(test_db: Session, seed_data: dict):
    """Parent risk score, severity, and confidence update atomically with the new assessment."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_05"})()

    parent_risk_id = seed_data["risk_a"].id
    initial_score = seed_data["risk_a"].risk_score

    signals = [make_test_signal(signal_id="sig_update_parent", org_id="org_alpha", severity=EventSeverity.CRITICAL)]
    assessment, _, _ = service.evaluate_and_persist(
        signals=signals,
        risk_id=parent_risk_id,
    )

    refreshed_risk = test_db.get(ORMRisk, parent_risk_id)
    assert refreshed_risk.risk_score == assessment.score
    assert refreshed_risk.confidence == round(float(assessment.confidence), 4)
    assert refreshed_risk.updated_at is not None


# ==============================================================================
# 4. DETERMINISTIC IDEMPOTENCY TESTS (6 tests)
# ==============================================================================

def test_idempotency_same_fingerprint_returns_existing(test_db: Session, seed_data: dict):
    """Repeated evaluation with identical signals matches fingerprint and returns existing record."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_idemp_1"})()

    signals = [make_test_signal(signal_id="sig_idemp_01", org_id="org_alpha")]

    # Run 1: new persistence
    ass1, detail1, is_hit1 = service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    assert is_hit1 is False

    # Run 2: identical input -> idempotency hit
    ass2, detail2, is_hit2 = service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    assert is_hit2 is True
    assert ass2.fingerprint == ass1.fingerprint
    assert detail2["id"] == detail1["id"]


def test_idempotency_no_duplicate_assessment_rows(test_db: Session, seed_data: dict):
    """Repeated evaluation with identical input does not create duplicate rows in risk_assessments."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_idemp_2"})()

    signals = [make_test_signal(signal_id="sig_idemp_rows", org_id="org_alpha")]

    service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    count_1 = test_db.scalar(select(func.count()).select_from(ORMRiskAssessment))

    service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    count_2 = test_db.scalar(select(func.count()).select_from(ORMRiskAssessment))

    assert count_1 == count_2 == 1


def test_idempotency_no_duplicate_factor_rows(test_db: Session, seed_data: dict):
    """Repeated evaluation does not duplicate associated risk_factors rows."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_idemp_3"})()

    signals = [make_test_signal(signal_id="sig_idemp_fact", org_id="org_alpha")]

    service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    f_count_1 = test_db.scalar(select(func.count()).select_from(ORMRiskFactor))

    service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    f_count_2 = test_db.scalar(select(func.count()).select_from(ORMRiskFactor))

    assert f_count_1 == f_count_2


def test_idempotency_different_signals_create_new_assessment(test_db: Session, seed_data: dict):
    """Evaluations with differing signals have different fingerprints and persist distinct records."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_idemp_4"})()

    signals_a = [make_test_signal(signal_id="sig_set_a", org_id="org_alpha", severity=EventSeverity.LOW)]
    signals_b = [make_test_signal(signal_id="sig_set_b", org_id="org_alpha", severity=EventSeverity.CRITICAL)]

    ass_a, _, hit_a = service.evaluate_and_persist(signals=signals_a, scope="GLOBAL")
    ass_b, _, hit_b = service.evaluate_and_persist(signals=signals_b, scope="GLOBAL")

    assert hit_a is False
    assert hit_b is False
    assert ass_a.fingerprint != ass_b.fingerprint
    assert test_db.scalar(select(func.count()).select_from(ORMRiskAssessment)) == 2


def test_idempotency_preserves_original_created_at(test_db: Session, seed_data: dict):
    """Idempotent replay preserves the original evaluation timestamp rather than overriding with current time."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_idemp_5"})()

    signals = [make_test_signal(signal_id="sig_time_test", org_id="org_alpha")]
    _, detail_1, _ = service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    created_at_1 = detail_1["created_at"]

    _, detail_2, is_hit = service.evaluate_and_persist(signals=signals, scope="GLOBAL")
    assert is_hit is True
    assert detail_2["created_at"] == created_at_1


def test_idempotency_independent_of_request_or_trace_id(test_db: Session, seed_data: dict):
    """Deterministic fingerprint does not change when correlation_id or request_id vary."""
    signals = [make_test_signal(signal_id="sig_corr_test", org_id="org_alpha")]
    t_fixed = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)

    ctx1 = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=t_fixed, signals=signals, correlation_id="req_alpha_1")
    ctx2 = RiskEvaluationContext(organization_id="org_alpha", evaluation_time=t_fixed, signals=signals, correlation_id="req_alpha_2")

    engine = BaselineRiskEngine()
    ass1 = engine.evaluate(ctx1)
    ass2 = engine.evaluate(ctx2)

    assert ass1.fingerprint == ass2.fingerprint


# ==============================================================================
# 5. MULTI-TENANT BOUNDARY & AUTHORIZATION TESTS (8 tests)
# ==============================================================================

def test_tenant_isolation_service_enforces_server_tenant(test_db: Session, seed_data: dict):
    """RiskEvaluationService strictly uses context.organization_id ignoring any untrusted metadata."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_ten_1"})()

    signals = [make_test_signal(signal_id="sig_ten_enforce", org_id="org_alpha")]
    # Attempt to inject cross-tenant spoofing in metadata
    assessment, detail, _ = service.evaluate_and_persist(
        signals=signals,
        metadata={"organization_id": "org_beta_spoofed"},
    )
    assert assessment.organization_id == "org_alpha"
    assert detail["org_id"] == "org_alpha"

    persisted = test_db.get(ORMRiskAssessment, assessment.assessment_id)
    assert persisted.org_id == "org_alpha"


def test_tenant_isolation_client_org_mismatch_ignored(test_db: Session, seed_data: dict):
    """Client attempt to evaluate with a mismatched risk_id from another tenant is rejected with 404."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    # Caller is Org A
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_ten_2"})()

    signals = [make_test_signal(signal_id="sig_cross_risk", org_id="org_alpha")]
    # Client provides risk_id belonging to Org B
    cross_tenant_risk_id = seed_data["risk_b"].id

    from app.core.errors import NotFoundError
    with pytest.raises(NotFoundError):
        service.evaluate_and_persist(
            signals=signals,
            risk_id=cross_tenant_risk_id,
        )


def test_tenant_isolation_org_a_cannot_view_org_b_assessment(test_db: Session, seed_data: dict):
    """User from Org A querying an Org B assessment raises NotFoundError (404 masking)."""
    uow = UnitOfWork(test_db)
    # Seed Org B assessment
    ass_b = ORMRiskAssessment(
        id="ass_b_private",
        org_id="org_beta",
        risk_id=seed_data["risk_b"].id,
        score=95.0,
    )
    uow.risk_assessments.create(ass_b)

    service_a = RiskEvaluationService(uow=uow, context=None)
    service_a.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_ten_3"})()

    from app.core.errors import NotFoundError
    with pytest.raises(NotFoundError):
        service_a.get_assessment_detail("ass_b_private")


def test_tenant_isolation_org_a_cannot_view_org_b_factors(test_db: Session, seed_data: dict):
    """Factors linked to an Org B risk return None when queried within Org A tenant scope."""
    uow = UnitOfWork(test_db)
    factor_b = ORMRiskFactor(
        id="fact_b_private",
        risk_id=seed_data["risk_b"].id,
        name="Panama Drought Factor",
        weight=1.0,
        score=90.0,
    )
    uow.risk_factors.create(factor_b)

    # Org A query
    assert uow.risk_factors.get_factor_in_org("fact_b_private", org_id="org_alpha") is None


def test_tenant_isolation_org_a_latest_does_not_return_org_b(test_db: Session, seed_data: dict):
    """get_latest_assessment only returns records created by the caller's organization."""
    uow = UnitOfWork(test_db)
    # Only Org B has an assessment
    ass_b = ORMRiskAssessment(
        id="ass_b_only",
        org_id="org_beta",
        risk_id=seed_data["risk_b"].id,
        score=88.0,
        findings={"scope": "GLOBAL"},
    )
    uow.risk_assessments.create(ass_b)

    service_a = RiskEvaluationService(uow=uow, context=None)
    service_a.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_ten_4"})()

    latest_a = service_a.get_latest_assessment(scope="GLOBAL")
    assert latest_a is None


def test_tenant_isolation_audit_log_records_correct_tenant(test_db: Session, seed_data: dict):
    """Audit log generated during evaluation strictly records the calling organization_id."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_ten_5"})()

    signals = [make_test_signal(signal_id="sig_audit_ten", org_id="org_alpha")]
    service.evaluate_and_persist(signals=signals, scope="GLOBAL")

    from app.models.governance import AuditLog
    logs = list(test_db.scalars(select(AuditLog).where(AuditLog.org_id == "org_alpha")).all())
    assert len(logs) > 0
    assert all(l.org_id == "org_alpha" for l in logs)


def test_tenant_isolation_unauthenticated_request_rejected(client: TestClient):
    """Unauthenticated call to evaluate risk returns 401 Unauthorized."""
    payload = {
        "scope": "GLOBAL",
        "signals": [],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload)
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_tenant_isolation_viewer_cannot_evaluate(client: TestClient, seed_data: dict):
    """Viewer role does not have permission to trigger risk evaluation mutations (403 Forbidden)."""
    headers = {"Cookie": f"riskwise_session={seed_data['viewer_a_cookie']}"}
    payload = {
        "scope": "GLOBAL",
        "signals": [],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 6. API ENDPOINT TESTS (12 tests)
# ==============================================================================

def test_api_evaluate_endpoint_success_analyst(client: TestClient, seed_data: dict):
    """Analyst role successfully evaluates risk and receives 201 Created with detail response."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(signal_id="sig_api_eval_1", org_id="org_alpha")

    payload = {
        "scope": "PORT",
        "scope_entity_id": "port_hk",
        "signals": [sig.model_dump(mode="json")],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert "id" in data
    assert "assessment_id" in data
    assert data["org_id"] == "org_alpha"
    assert data["score"] >= 0.0
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["probability"] is None
    assert data["impact"] is None
    assert len(data["factors"]) > 0
    assert len(data["evidence"]) > 0


def test_api_evaluate_endpoint_unauthenticated_401(client: TestClient):
    """API evaluate endpoint rejects requests without session cookie."""
    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": []})
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_evaluate_endpoint_viewer_role_forbidden_403(client: TestClient, seed_data: dict):
    """API evaluate endpoint rejects Viewer role with 403 Forbidden."""
    headers = {"Cookie": f"riskwise_session={seed_data['viewer_a_cookie']}"}
    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": []}, headers=headers)
    assert res.status_code == status.HTTP_403_FORBIDDEN


def test_api_evaluate_endpoint_idempotency_200_ok(client: TestClient, seed_data: dict):
    """API returns 200 OK (instead of 201) when returning an idempotent cached assessment."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(signal_id="sig_api_idemp", org_id="org_alpha")
    payload = {
        "scope": "GLOBAL",
        "signals": [sig.model_dump(mode="json")],
    }

    res1 = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res1.status_code == status.HTTP_201_CREATED

    res2 = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()["id"] == res1.json()["id"]


def test_api_evaluate_endpoint_invalid_signal_type_rejected(client: TestClient, seed_data: dict):
    """API rejects request when signals contain non-NormalizedRiskSignal objects."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    payload = {
        "scope": "GLOBAL",
        "signals": [{"arbitrary_key": "unvalidated_data"}],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code in (status.HTTP_422_UNPROCESSABLE_CONTENT, status.HTTP_400_BAD_REQUEST)


def test_api_evaluate_endpoint_raw_provider_payload_rejected(client: TestClient, seed_data: dict):
    """Raw provider dictionary (OpenWeather, TomTom, AIS) passed directly is rejected at schema boundary."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    raw_weather_payload = {
        "coord": {"lon": 114.15, "lat": 22.28},
        "weather": [{"id": 500, "main": "Rain", "description": "light rain"}],
        "main": {"temp": 298.15, "pressure": 1013},
    }
    payload = {
        "scope": "GLOBAL",
        "signals": [raw_weather_payload],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code in (status.HTTP_422_UNPROCESSABLE_CONTENT, status.HTTP_400_BAD_REQUEST)


def test_api_get_assessment_by_id_viewer_success(client: TestClient, seed_data: dict):
    """Viewer retrieves single assessment by ID and receives standard RiskAssessmentResponse."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_a_cookie']}"}

    sig = make_test_signal(signal_id="sig_get_by_id", org_id="org_alpha")
    eval_res = client.post(
        "/api/v1/risk-assessments/evaluate",
        json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]},
        headers=headers_analyst,
    )
    ass_id = eval_res.json()["id"]

    get_res = client.get(f"/api/v1/risk-assessments/{ass_id}", headers=headers_viewer)
    assert get_res.status_code == status.HTTP_200_OK
    data = get_res.json()
    assert data["id"] == ass_id
    assert "findings" in data
    assert data["score"] == eval_res.json()["score"]


def test_api_get_assessment_by_id_cross_tenant_404(client: TestClient, seed_data: dict):
    """User in Org B querying an Org A assessment ID receives 404 Not Found."""
    headers_analyst_a = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    headers_analyst_b = {"Cookie": f"riskwise_session={seed_data['analyst_b_cookie']}"}

    sig = make_test_signal(signal_id="sig_cross_404", org_id="org_alpha")
    eval_res = client.post(
        "/api/v1/risk-assessments/evaluate",
        json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]},
        headers=headers_analyst_a,
    )
    ass_id = eval_res.json()["id"]

    # Org B retrieves Org A assessment
    get_res = client.get(f"/api/v1/risk-assessments/{ass_id}", headers=headers_analyst_b)
    assert get_res.status_code == status.HTTP_404_NOT_FOUND


def test_api_get_assessment_by_id_nonexistent_404(client: TestClient, seed_data: dict):
    """Querying a nonexistent assessment ID returns 404 Not Found."""
    headers = {"Cookie": f"riskwise_session={seed_data['viewer_a_cookie']}"}
    res = client.get("/api/v1/risk-assessments/nonexistent_id_9999", headers=headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_api_get_assessment_detail_endpoint(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments/{id}/detail returns flattened detail response."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_a_cookie']}"}

    sig = make_test_signal(signal_id="sig_detail_test", org_id="org_alpha")
    eval_res = client.post(
        "/api/v1/risk-assessments/evaluate",
        json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]},
        headers=headers_analyst,
    )
    ass_id = eval_res.json()["id"]

    res = client.get(f"/api/v1/risk-assessments/{ass_id}/detail", headers=headers_viewer)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["assessment_id"] == ass_id
    assert "factor_contributions" in data
    assert "source_summary" in data
    assert "explanation" in data


def test_api_get_latest_assessment_endpoint(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments/latest returns the most recent evaluation for caller's org."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_a_cookie']}"}

    sig = make_test_signal(signal_id="sig_latest_api", org_id="org_alpha")
    client.post(
        "/api/v1/risk-assessments/evaluate",
        json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]},
        headers=headers_analyst,
    )

    res = client.get("/api/v1/risk-assessments/latest?scope=GLOBAL", headers=headers_viewer)
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["findings"]["scope"] == "GLOBAL"


def test_api_list_assessments_endpoint_tenant_partition(client: TestClient, seed_data: dict):
    """GET /api/v1/risk-assessments returns paginated list partitioned to the tenant."""
    headers_analyst_a = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    headers_analyst_b = {"Cookie": f"riskwise_session={seed_data['analyst_b_cookie']}"}

    sig_a = make_test_signal(signal_id="sig_list_a", org_id="org_alpha")
    sig_b = make_test_signal(signal_id="sig_list_b", org_id="org_beta")

    client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig_a.model_dump(mode="json")]}, headers=headers_analyst_a)
    client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig_b.model_dump(mode="json")]}, headers=headers_analyst_b)

    res_a = client.get("/api/v1/risk-assessments", headers=headers_analyst_a)
    assert res_a.status_code == status.HTTP_200_OK
    items_a = res_a.json()["items"]
    assert all(item["org_id"] == "org_alpha" for item in items_a)


# ==============================================================================
# 7. RISK ENGINE INTEGRATION & TRACEABILITY TESTS (8 tests)
# ==============================================================================

def test_integration_normalized_signal_to_api_response_chain(client: TestClient, seed_data: dict):
    """Full round-trip trace: NormalizedRiskSignal -> Evaluators -> Aggregator -> Persistence -> Response."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(
        signal_id="sig_full_chain_01",
        org_id="org_alpha",
        severity=EventSeverity.HIGH,
        quality=EventQuality.VALID,
    )
    payload = {
        "scope": "GLOBAL",
        "signals": [sig.model_dump(mode="json")],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    # Verify chain: Response has primary factor -> has evidence -> references original signal_id
    assert data["primary_factor_id"] is not None
    ev_signals = [e["signal_id"] for e in data["evidence"]]
    assert "sig_full_chain_01" in ev_signals


def test_integration_score_bounded_0_to_100(client: TestClient, seed_data: dict):
    """Calculated composite risk score is bounded [0.0, 100.0] under extreme signal conditions."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    # Multiple critical signals
    signals = [
        make_test_signal(signal_id=f"sig_crit_{i}", org_id="org_alpha", severity=EventSeverity.CRITICAL, confidence=1.0)
        for i in range(5)
    ]
    payload = {
        "scope": "GLOBAL",
        "signals": [s.model_dump(mode="json") for s in signals],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code == status.HTTP_201_CREATED
    score = res.json()["score"]
    assert 0.0 <= score <= 100.0


def test_integration_primary_driver_selection_persisted(client: TestClient, seed_data: dict):
    """Primary risk driver selected by 5-tuple rule is stored and returned in detail response."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig_low = make_test_signal(signal_id="sig_low", org_id="org_alpha", domain=SignalDomain.WEATHER, severity=EventSeverity.LOW, fingerprint="fp_low")
    sig_crit = make_test_signal(signal_id="sig_crit", org_id="org_alpha", domain=SignalDomain.ROAD, severity=EventSeverity.CRITICAL, fingerprint="fp_crit")

    payload = {
        "scope": "GLOBAL",
        "signals": [sig_low.model_dump(mode="json"), sig_crit.model_dump(mode="json")],
    }
    res = client.post("/api/v1/risk-assessments/evaluate", json=payload, headers=headers)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["primary_driver"] is not None
    assert data["primary_driver"]["severity"] in ("CRITICAL", "HIGH")


def test_integration_factor_contributions_persisted(client: TestClient, seed_data: dict):
    """Factor contributions with raw and weighted contributions and ranks are retrievable from DB."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(signal_id="sig_contrib_test", org_id="org_alpha")

    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]}, headers=headers)
    contribs = res.json()["factor_contributions"]
    assert len(contribs) > 0
    c0 = contribs[0]
    assert c0["rank"] == 1
    assert "raw_contribution" in c0
    assert "weighted_contribution" in c0


def test_integration_evidence_lineage_traceable_to_signal(client: TestClient, seed_data: dict):
    """Every persisted evidence record correctly links to its source normalized signal ID."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(signal_id="sig_trace_canonical_123", org_id="org_alpha")

    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]}, headers=headers)
    ev_list = res.json()["evidence"]
    assert len(ev_list) > 0
    assert any(e["signal_id"] == "sig_trace_canonical_123" for e in ev_list)


def test_integration_source_summary_accurate(client: TestClient, seed_data: dict):
    """Source summary accurately reports independent source counts in the API response."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    s1 = make_test_signal(signal_id="sig_src_1", org_id="org_alpha", provider="noaa", source="weather_noaa", fingerprint="fp_s1")
    s2 = make_test_signal(signal_id="sig_src_2", org_id="org_alpha", provider="copernicus", source="weather_copernicus", fingerprint="fp_s2")

    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [s1.model_dump(mode="json"), s2.model_dump(mode="json")]}, headers=headers)
    summary = res.json()["source_summary"]
    assert summary is not None
    assert summary["independent_sources_count"] >= 2
    assert "noaa" in summary["providers"]
    assert "copernicus" in summary["providers"]


def test_integration_deterministic_factor_ordering_persisted(client: TestClient, seed_data: dict):
    """Persisted factors retain deterministic rank ordering (primary driver first)."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    s1 = make_test_signal(signal_id="sig_ord_1", org_id="org_alpha", severity=EventSeverity.LOW)
    s2 = make_test_signal(signal_id="sig_ord_2", org_id="org_alpha", severity=EventSeverity.CRITICAL)

    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [s1.model_dump(mode="json"), s2.model_dump(mode="json")]}, headers=headers)
    factors = res.json()["factors"]
    assert len(factors) >= 1
    # Factor contributions rank order
    contribs = res.json()["factor_contributions"]
    ranks = [c["rank"] for c in contribs]
    assert ranks == sorted(ranks)


def test_integration_conflict_uncertainty_penalty_reflected(client: TestClient, seed_data: dict):
    """Conflicting signals apply the 0.85 uncertainty discount visible in calculation metadata."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig_normal = make_test_signal(signal_id="sig_penalty_norm", org_id="org_alpha", has_conflict=False)
    sig_conflict = make_test_signal(signal_id="sig_penalty_conf", org_id="org_alpha", has_conflict=True)

    res_norm = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig_normal.model_dump(mode="json")]}, headers=headers)
    res_conf = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig_conflict.model_dump(mode="json")]}, headers=headers)

    score_norm = res_norm.json()["score"]
    score_conf = res_conf.json()["score"]
    assert score_conf < score_norm
    assert len(res_conf.json()["conflicts"]) > 0


# ==============================================================================
# 8. SECURITY & NON-FABRICATION POLICY TESTS (6 tests)
# ==============================================================================

def test_security_probability_strictly_none(client: TestClient, seed_data: dict):
    """Probability is strictly null in evaluation responses (non-fabrication policy)."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(signal_id="sig_prob_test", org_id="org_alpha")

    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]}, headers=headers)
    assert res.json()["probability"] is None


def test_security_impact_strictly_none(client: TestClient, seed_data: dict):
    """Impact is strictly null in evaluation responses (non-fabrication policy)."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    sig = make_test_signal(signal_id="sig_impact_test", org_id="org_alpha")

    res = client.post("/api/v1/risk-assessments/evaluate", json={"scope": "GLOBAL", "signals": [sig.model_dump(mode="json")]}, headers=headers)
    assert res.json()["impact"] is None


def test_security_no_secrets_in_findings_evidence(test_db: Session, seed_data: dict):
    """Persisted findings JSON never contains unredacted authorization tokens or passwords."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_sec_1"})()

    sig = make_test_signal(signal_id="sig_sec_findings", org_id="org_alpha")
    sig.supporting_sources = []

    assessment, _, _ = service.evaluate_and_persist(
        signals=[sig],
        metadata={"Authorization": "Bearer secret_jwt_token", "api_key": "secret_key_123"},
    )

    persisted = test_db.get(ORMRiskAssessment, assessment.assessment_id)
    findings_str = str(persisted.findings)
    assert "secret_jwt_token" not in findings_str
    assert "secret_key_123" not in findings_str


def test_security_no_secrets_in_factors_evidence_json(test_db: Session, seed_data: dict):
    """Persisted risk_factors.evidence_json never contains unredacted credentials."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_sec_2"})()

    sig = make_test_signal(signal_id="sig_sec_fact", org_id="org_alpha")
    service.evaluate_and_persist(
        signals=[sig],
        metadata={"password": "database_password", "token": "oauth_token_val"},
    )

    factors = list(test_db.scalars(select(ORMRiskFactor)).all())
    for f in factors:
        ev_str = str(f.evidence_json)
        assert "database_password" not in ev_str
        assert "oauth_token_val" not in ev_str


def test_security_no_secrets_in_audit_log(test_db: Session, seed_data: dict):
    """Audit log records written during risk evaluation never log tokens or credentials."""
    uow = UnitOfWork(test_db)
    service = RiskEvaluationService(uow=uow, context=None)
    service.context = type("MockContext", (), {"organization_id": "org_alpha", "user_id": "usr_analyst_a", "request_id": "req_sec_3"})()

    sig = make_test_signal(signal_id="sig_sec_audit", org_id="org_alpha")
    service.evaluate_and_persist(signals=[sig])

    from app.models.governance import AuditLog
    logs = list(test_db.scalars(select(AuditLog)).all())
    for l in logs:
        after_str = str(l.after_json)
        for forbidden in ("password", "Bearer", "secret_key", "client_secret"):
            assert forbidden not in after_str


def test_security_no_internal_db_errors_leaked(client: TestClient, seed_data: dict):
    """Database or query errors return standard error envelopes without raw SQL traces."""
    headers = {"Cookie": f"riskwise_session={seed_data['analyst_a_cookie']}"}
    # Send malformed filter param on GET
    res = client.get("/api/v1/risk-assessments?unallowed_filter=true", headers=headers)
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    data = res.json()
    assert "error" in data
    assert "code" in data["error"]
    assert "SELECT" not in str(data)
    assert "sqlalchemy" not in str(data).lower()
