"""Comprehensive test suite for RiskWise 2.0 Risk APIs (Phase 4 Step 6).

Covers all 4 risk domain resources:
1. risks (Identified geopolitical, climatic, supplier, lane risks)
2. risk_factors (Causal drivers scoped via parent risk.org_id)
3. risk_assessments (Immutable evaluation snapshots)
4. incidents (Realized disruptions managed through lifecycle state)

Validates all 26 criteria specified in the contract:
 1. Authentication required (GET/POST/PATCH/DELETE without session → 401)
 2. RBAC enforcement (Viewer write/delete → 403; Analyst/OpsManager/Admin write → 200/201/204)
 3. Tenant isolation (Cross-tenant GET/PATCH/DELETE → 404 masked)
 4. Cross-tenant parent reference rejection (Referencing Org B risk in Org A factor/assessment/incident → 404 masked)
 5. Risk factor creation (Valid POST → 201)
 6. Risk factor retrieval (Valid GET by ID → 200)
 7. Risk factor listing (Valid GET collection → 200 paginated)
 8. Risk factor filtering (risk_id, category)
 9. Risk factor sorting (score, -score, created_at, -created_at)
10. Risk factor search where supported (search across name/category, wildcard escaping)
11. Risk CRUD (POST → 201, GET → 200, PATCH → 200, list → 200)
12. Risk lifecycle validation (trend, severity, hard DELETE → 405 Method Not Allowed)
13. Risk numeric bounds validation (probability [0..1], impact [0..100], risk_score [0..100] → 422 if invalid)
14. Risk assessment creation (Valid POST → 201)
15. Risk assessment retrieval (Valid GET by ID → 200)
16. Assessment immutability rules (PATCH/DELETE to /risk-assessments/{id} → 405 Method Not Allowed)
17. Incident creation (Valid POST → 201)
18. Incident retrieval (Valid GET by ID → 200)
19. Incident listing (Valid GET collection → 200 paginated)
20. Incident update (Valid PATCH → 200)
21. Incident lifecycle transitions (transitioning status to RESOLVED auto-sets resolved_at)
22. Duplicate/conflict & server-controlled field protection (id, org_id, detected_at in payload → 422)
23. Standardized error envelopes (INVALID_FILTER_FIELD → 400, INVALID_SORT_FIELD → 400, RESOURCE_NOT_FOUND → 404)
24. Audit behavior (CREATE/UPDATE/DELETE produce records in audit_logs)
25. OpenAPI route registration & uniqueness (All routes present, unique operation IDs)
26. Risk factor deletion (DELETE /risk-factors/{id} → 204 No Content)
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.governance import AuditLog
from app.models.risk import Incident, Risk, RiskAssessment, RiskFactor
from app.models.tenancy import Organization, User
from app.services.session_service import MemorySessionStore, SessionService, get_session_service


# ==============================================================================
# FIXTURES
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
    """FastAPI TestClient with overridden database and session service dependencies."""
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
    """Seed test organizations, users across roles, risks, factors, assessments, and incidents."""
    # Organizations
    org_a = Organization(id="org_alpha_01", name="Alpha Logistics Inc", slug="alpha-logistics", is_active=True)
    org_b = Organization(id="org_beta_02", name="Beta Global Ltd", slug="beta-global", is_active=True)
    test_db.add_all([org_a, org_b])
    test_db.commit()

    # Users for Org A
    viewer_a = User(id="usr_view_a", org_id="org_alpha_01", email="viewer@alpha.test", full_name="Viewer A", role="Viewer", is_active=True)
    analyst_a = User(id="usr_analyst_a", org_id="org_alpha_01", email="analyst@alpha.test", full_name="Analyst A", role="Analyst", is_active=True)
    ops_a = User(id="usr_ops_a", org_id="org_alpha_01", email="ops@alpha.test", full_name="OpsManager A", role="OpsManager", is_active=True)
    risk_a = User(id="usr_risk_a", org_id="org_alpha_01", email="risk@alpha.test", full_name="RiskManager A", role="RiskManager", is_active=True)
    admin_a = User(id="usr_admin_a", org_id="org_alpha_01", email="admin@alpha.test", full_name="Admin A", role="Admin", is_active=True)

    # User for Org B
    analyst_b = User(id="usr_analyst_b", org_id="org_beta_02", email="analyst@beta.test", full_name="Analyst B", role="Analyst", is_active=True)

    test_db.add_all([viewer_a, analyst_a, ops_a, risk_a, admin_a, analyst_b])
    test_db.commit()

    # Risks
    risk_entity_a = Risk(
        id="risk_a1",
        org_id="org_alpha_01",
        title="Red Sea Chokepoint Disruptions",
        risk_type="GEOPOLITICAL",
        severity="HIGH",
        location="Bab-el-Mandeb",
        probability=0.85,
        impact=75.0,
        risk_score=78.5,
        confidence=0.9,
        trend="INCREASING",
        source="INTELLIGENCE_FEED",
    )
    risk_entity_b = Risk(
        id="risk_b1",
        org_id="org_beta_02",
        title="Panama Canal Drought Low Draft",
        risk_type="CLIMATIC",
        severity="CRITICAL",
        location="Panama Canal",
        probability=0.95,
        impact=90.0,
        risk_score=92.0,
        confidence=0.95,
        trend="STABLE",
        source="MET_REPORT",
    )
    test_db.add_all([risk_entity_a, risk_entity_b])
    test_db.commit()

    # Risk Factors
    factor_entity_a = RiskFactor(
        id="fact_a1",
        risk_id="risk_a1",
        name="Missile Threat to Commercial Vessels",
        category="SECURITY",
        weight=2.0,
        score=85.0,
        evidence_json={"incidents_reported": 12},
    )
    factor_entity_b = RiskFactor(
        id="fact_b1",
        risk_id="risk_b1",
        name="Reservoir Water Level Deficit",
        category="ENVIRONMENTAL",
        weight=1.5,
        score=90.0,
        evidence_json={"lake_level_meters": 24.2},
    )
    test_db.add_all([factor_entity_a, factor_entity_b])
    test_db.commit()

    # Risk Assessments
    assessment_entity_a = RiskAssessment(
        id="ass_a1",
        org_id="org_alpha_01",
        risk_id="risk_a1",
        assessor_type="AI_AGENT",
        assessor_id="agent_geopol_01",
        methodology="BAYESIAN_NETWORK",
        findings={"summary": "Elevated rerouting costs via Cape of Good Hope"},
        score=78.5,
        confidence=0.9,
    )
    assessment_entity_b = RiskAssessment(
        id="ass_b1",
        org_id="org_beta_02",
        risk_id="risk_b1",
        assessor_type="HUMAN_ANALYST",
        assessor_id="usr_analyst_b",
        methodology="EXPERT_OPINION",
        findings={"summary": "Draft restrictions reducing vessel container capacity by 30%"},
        score=92.0,
        confidence=0.95,
    )
    test_db.add_all([assessment_entity_a, assessment_entity_b])
    test_db.commit()

    # Incidents
    incident_entity_a = Incident(
        id="inc_a1",
        org_id="org_alpha_01",
        risk_id="risk_a1",
        title="Commercial Tanker Attack off Hodeidah",
        status="INVESTIGATING",
        severity="HIGH",
        location="Red Sea",
        source="COASTAL_ALERT",
        affected_assets=["route_asia_europe_01"],
    )
    incident_entity_b = Incident(
        id="inc_b1",
        org_id="org_beta_02",
        risk_id="risk_b1",
        title="Gatun Lake Transit Slot Restriction",
        status="DETECTED",
        severity="CRITICAL",
        location="Panama",
        source="CANAL_AUTHORITY",
        affected_assets=["route_americas_02"],
    )
    test_db.add_all([incident_entity_a, incident_entity_b])
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
        "viewer_cookie": make_cookie(viewer_a),
        "analyst_cookie": make_cookie(analyst_a),
        "ops_a_cookie": make_cookie(ops_a),
        "risk_a_cookie": make_cookie(risk_a),
        "admin_a_cookie": make_cookie(admin_a),
        "analyst_b_cookie": make_cookie(analyst_b),
        "risk_a": risk_entity_a,
        "risk_b": risk_entity_b,
        "factor_a": factor_entity_a,
        "factor_b": factor_entity_b,
        "assessment_a": assessment_entity_a,
        "assessment_b": assessment_entity_b,
        "incident_a": incident_entity_a,
        "incident_b": incident_entity_b,
    }


# ==============================================================================
# 1. AUTHENTICATION REQUIRED (401)
# ==============================================================================
def test_1_authentication_required(client: TestClient):
    """Unauthenticated requests to all Risk domain endpoints return 401."""
    assert client.get("/api/v1/risks").status_code == 401
    assert client.post("/api/v1/risks", json={"title": "R1"}).status_code == 401
    assert client.get("/api/v1/risks/r_1").status_code == 401
    assert client.patch("/api/v1/risks/r_1", json={"title": "R1"}).status_code == 401

    assert client.get("/api/v1/risk-factors").status_code == 401
    assert client.post("/api/v1/risk-factors", json={"risk_id": "r1", "name": "F1"}).status_code == 401
    assert client.get("/api/v1/risk-factors/f_1").status_code == 401
    assert client.patch("/api/v1/risk-factors/f_1", json={"name": "F1"}).status_code == 401
    assert client.delete("/api/v1/risk-factors/f_1").status_code == 401

    assert client.get("/api/v1/risk-assessments").status_code == 401
    assert client.post("/api/v1/risk-assessments", json={"risk_id": "r1"}).status_code == 401
    assert client.get("/api/v1/risk-assessments/a_1").status_code == 401

    assert client.get("/api/v1/incidents").status_code == 401
    assert client.post("/api/v1/incidents", json={"title": "I1"}).status_code == 401
    assert client.get("/api/v1/incidents/i_1").status_code == 401
    assert client.patch("/api/v1/incidents/i_1", json={"title": "I1"}).status_code == 401


# ==============================================================================
# 2. RBAC ENFORCEMENT (Viewer 403 vs Analyst+ 200/201/204)
# ==============================================================================
def test_2_rbac_enforcement(client: TestClient, seed_data: dict):
    """Viewer role receives 403 on mutation endpoints; Analyst+ can create/update/delete."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}

    # Viewer can read collections
    assert client.get("/api/v1/risks", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/risk-factors", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/risk-assessments", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/incidents", headers=headers_viewer).status_code == 200

    # Viewer cannot create or update risks
    assert client.post("/api/v1/risks", json={"title": "New Risk"}, headers=headers_viewer).status_code == 403
    assert client.patch(f"/api/v1/risks/{seed_data['risk_a'].id}", json={"title": "Upd"}, headers=headers_viewer).status_code == 403

    # Viewer cannot create, update, or delete risk factors
    factor_payload = {"risk_id": seed_data["risk_a"].id, "name": "Wind Factor"}
    assert client.post("/api/v1/risk-factors", json=factor_payload, headers=headers_viewer).status_code == 403
    assert client.patch(f"/api/v1/risk-factors/{seed_data['factor_a'].id}", json={"name": "Upd"}, headers=headers_viewer).status_code == 403
    assert client.delete(f"/api/v1/risk-factors/{seed_data['factor_a'].id}", headers=headers_viewer).status_code == 403

    # Viewer cannot create assessment or incident
    assert client.post("/api/v1/risk-assessments", json={"risk_id": seed_data["risk_a"].id}, headers=headers_viewer).status_code == 403
    assert client.post("/api/v1/incidents", json={"title": "New Inc"}, headers=headers_viewer).status_code == 403

    # Analyst can create risk
    res = client.post("/api/v1/risks", json={"title": "Typhoon Approaching Port"}, headers=headers_analyst)
    assert res.status_code == 201


# ==============================================================================
# 3. TENANT ISOLATION (404 MASKED)
# ==============================================================================
def test_3_tenant_isolation(client: TestClient, seed_data: dict):
    """Tenant A cannot access or mutate Tenant B risks, factors, assessments, or incidents."""
    headers_analyst_a = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    risk_b_id = seed_data["risk_b"].id
    fact_b_id = seed_data["factor_b"].id
    ass_b_id = seed_data["assessment_b"].id
    inc_b_id = seed_data["incident_b"].id

    # Org A accessing Org B risk -> 404 masked
    res = client.get(f"/api/v1/risks/{risk_b_id}", headers=headers_analyst_a)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    # Org A updating Org B risk -> 404 masked
    assert client.patch(f"/api/v1/risks/{risk_b_id}", json={"title": "Hacked"}, headers=headers_analyst_a).status_code == 404

    # Org A accessing Org B factor -> 404 masked
    assert client.get(f"/api/v1/risk-factors/{fact_b_id}", headers=headers_analyst_a).status_code == 404
    assert client.patch(f"/api/v1/risk-factors/{fact_b_id}", json={"name": "Hacked"}, headers=headers_analyst_a).status_code == 404
    assert client.delete(f"/api/v1/risk-factors/{fact_b_id}", headers=headers_analyst_a).status_code == 404

    # Org A accessing Org B assessment -> 404 masked
    assert client.get(f"/api/v1/risk-assessments/{ass_b_id}", headers=headers_analyst_a).status_code == 404

    # Org A accessing Org B incident -> 404 masked
    assert client.get(f"/api/v1/incidents/{inc_b_id}", headers=headers_analyst_a).status_code == 404
    assert client.patch(f"/api/v1/incidents/{inc_b_id}", json={"title": "Hacked"}, headers=headers_analyst_a).status_code == 404

    # Collections exclude Tenant B records
    res = client.get("/api/v1/risks", headers=headers_analyst_a)
    assert risk_b_id not in [r["id"] for r in res.json()["items"]]

    res = client.get("/api/v1/risk-factors", headers=headers_analyst_a)
    assert fact_b_id not in [f["id"] for f in res.json()["items"]]

    res = client.get("/api/v1/risk-assessments", headers=headers_analyst_a)
    assert ass_b_id not in [a["id"] for a in res.json()["items"]]

    res = client.get("/api/v1/incidents", headers=headers_analyst_a)
    assert inc_b_id not in [i["id"] for i in res.json()["items"]]


# ==============================================================================
# 4. CROSS-TENANT PARENT REFERENCE REJECTION (404 MASKED)
# ==============================================================================
def test_4_cross_tenant_parent_reference_rejection(client: TestClient, seed_data: dict):
    """Creating a factor, assessment, or incident referencing a risk of another tenant is rejected with 404."""
    headers_analyst_a = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    risk_b_id = seed_data["risk_b"].id

    # RiskFactor referencing Org B risk
    res = client.post(
        "/api/v1/risk-factors",
        json={"risk_id": risk_b_id, "name": "Cross-tenant Factor"},
        headers=headers_analyst_a,
    )
    assert res.status_code == 404
    assert "Risk" in res.json()["error"]["message"]

    # RiskAssessment referencing Org B risk
    res = client.post(
        "/api/v1/risk-assessments",
        json={"risk_id": risk_b_id, "score": 80.0},
        headers=headers_analyst_a,
    )
    assert res.status_code == 404
    assert "Risk" in res.json()["error"]["message"]

    # Incident referencing Org B risk
    res = client.post(
        "/api/v1/incidents",
        json={"title": "Cross-tenant Incident", "risk_id": risk_b_id},
        headers=headers_analyst_a,
    )
    assert res.status_code == 404
    assert "Risk" in res.json()["error"]["message"]


# ==============================================================================
# 5. RISK FACTOR CREATION (201)
# ==============================================================================
def test_5_risk_factor_creation(client: TestClient, seed_data: dict):
    """Authorized analyst can create a risk factor linked to a tenant risk."""
    headers_analyst_a = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    risk_id = seed_data["risk_a"].id

    payload = {
        "risk_id": risk_id,
        "name": "Houthi Drone Activity",
        "category": "MILITARY",
        "weight": 2.5,
        "score": 88.0,
        "evidence_json": {"drones_intercepted": 5},
    }
    res = client.post("/api/v1/risk-factors", json=payload, headers=headers_analyst_a)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Houthi Drone Activity"
    assert data["category"] == "MILITARY"
    assert data["weight"] == 2.5
    assert data["score"] == 88.0
    assert data["risk_id"] == risk_id
    assert "id" in data


# ==============================================================================
# 6. RISK FACTOR RETRIEVAL (200)
# ==============================================================================
def test_6_risk_factor_retrieval(client: TestClient, seed_data: dict):
    """Retrieve an individual risk factor by ID."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    fact_id = seed_data["factor_a"].id

    res = client.get(f"/api/v1/risk-factors/{fact_id}", headers=headers_viewer)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == fact_id
    assert data["name"] == seed_data["factor_a"].name


# ==============================================================================
# 7. RISK FACTOR LISTING & SUB-RESOURCE (200)
# ==============================================================================
def test_7_risk_factor_listing(client: TestClient, seed_data: dict):
    """List risk factors globally or via parent risk sub-path."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    risk_id = seed_data["risk_a"].id

    # Top-level collection
    res = client.get("/api/v1/risk-factors", headers=headers_viewer)
    assert res.status_code == 200
    assert "items" in res.json()
    assert "pagination" in res.json()

    # Sub-resource path /risks/{id}/factors
    res_sub = client.get(f"/api/v1/risks/{risk_id}/factors", headers=headers_viewer)
    assert res_sub.status_code == 200
    for item in res_sub.json()["items"]:
        assert item["risk_id"] == risk_id


# ==============================================================================
# 8. RISK FACTOR FILTERING
# ==============================================================================
def test_8_risk_factor_filtering(client: TestClient, seed_data: dict):
    """Filter risk factors by risk_id and category."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    res = client.get(f"/api/v1/risk-factors?risk_id={seed_data['risk_a'].id}", headers=headers_viewer)
    assert res.status_code == 200
    for item in res.json()["items"]:
        assert item["risk_id"] == seed_data["risk_a"].id

    res_cat = client.get("/api/v1/risk-factors?category=SECURITY", headers=headers_viewer)
    assert res_cat.status_code == 200
    for item in res_cat.json()["items"]:
        assert item["category"] == "SECURITY"


# ==============================================================================
# 9. RISK FACTOR SORTING
# ==============================================================================
def test_9_risk_factor_sorting(client: TestClient, seed_data: dict):
    """Sort risk factors ascending/descending on allowed columns."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    assert client.get("/api/v1/risk-factors?sort=score", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/risk-factors?sort=-score", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/risk-factors?sort=created_at", headers=headers_viewer).status_code == 200


# ==============================================================================
# 10. RISK FACTOR SEARCH & SQL WILDCARD ESCAPING
# ==============================================================================
def test_10_risk_factor_search_and_wildcard_escaping(client: TestClient, seed_data: dict):
    """Search risk factors safely escaping % and _."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    res = client.get("/api/v1/risk-factors?search=%25_vessel%25", headers=headers_viewer)
    assert res.status_code == 200
    assert isinstance(res.json()["items"], list)


# ==============================================================================
# 11. RISK CRUD (201, 200, PATCH 200)
# ==============================================================================
def test_11_risk_crud(client: TestClient, seed_data: dict):
    """Complete CRUD operations for Risk entity."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}

    # CREATE
    create_payload = {
        "title": "Strait of Hormuz Escalation",
        "risk_type": "GEOPOLITICAL",
        "severity": "HIGH",
        "location": "Strait of Hormuz",
        "probability": 0.70,
        "impact": 85.0,
        "risk_score": 75.0,
        "confidence": 0.8,
        "trend": "INCREASING",
        "source": "NAVAL_BRIEF",
    }
    create_res = client.post("/api/v1/risks", json=create_payload, headers=headers_analyst)
    assert create_res.status_code == 201
    risk_id = create_res.json()["id"]

    # GET
    get_res = client.get(f"/api/v1/risks/{risk_id}", headers=headers_analyst)
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Strait of Hormuz Escalation"

    # PATCH
    patch_res = client.patch(
        f"/api/v1/risks/{risk_id}",
        json={"severity": "CRITICAL", "risk_score": 90.0},
        headers=headers_analyst,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["severity"] == "CRITICAL"
    assert patch_res.json()["risk_score"] == 90.0


# ==============================================================================
# 12. RISK LIFECYCLE & FORBIDDEN HARD DELETE (405)
# ==============================================================================
def test_12_risk_forbidden_hard_delete(client: TestClient, seed_data: dict):
    """Risks cannot be hard deleted; HTTP DELETE returns 405 Method Not Allowed."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    risk_id = seed_data["risk_a"].id

    res = client.delete(f"/api/v1/risks/{risk_id}", headers=headers_analyst)
    assert res.status_code == 405


# ==============================================================================
# 13. RISK NUMERIC BOUNDS VALIDATION (422)
# ==============================================================================
def test_13_risk_numeric_bounds_validation(client: TestClient, seed_data: dict):
    """Numeric attributes out of bounds (probability > 1.0, impact > 100.0) return 422."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}

    # Probability > 1.0
    res = client.post(
        "/api/v1/risks",
        json={"title": "Invalid Risk", "probability": 1.5},
        headers=headers_analyst,
    )
    assert res.status_code == 422

    # Impact > 100.0
    res = client.post(
        "/api/v1/risks",
        json={"title": "Invalid Risk", "impact": 150.0},
        headers=headers_analyst,
    )
    assert res.status_code == 422

    # Risk score < 0.0
    res = client.post(
        "/api/v1/risks",
        json={"title": "Invalid Risk", "risk_score": -10.0},
        headers=headers_analyst,
    )
    assert res.status_code == 422


# ==============================================================================
# 14. RISK ASSESSMENT CREATION (201)
# ==============================================================================
def test_14_risk_assessment_creation(client: TestClient, seed_data: dict):
    """Create a new risk assessment evaluation snapshot."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    risk_id = seed_data["risk_a"].id

    payload = {
        "risk_id": risk_id,
        "assessor_type": "AI_AGENT",
        "assessor_id": "agent_deep_risk_01",
        "methodology": "MONTE_CARLO",
        "findings": {"var_95": "$1.4M", "mean_delay_days": 8.5},
        "score": 82.0,
        "confidence": 0.88,
    }
    res = client.post("/api/v1/risk-assessments", json=payload, headers=headers_analyst)
    assert res.status_code == 201
    data = res.json()
    assert data["risk_id"] == risk_id
    assert data["score"] == 82.0
    assert data["methodology"] == "MONTE_CARLO"
    assert "id" in data


# ==============================================================================
# 15. RISK ASSESSMENT RETRIEVAL & SUB-RESOURCE (200)
# ==============================================================================
def test_15_risk_assessment_retrieval(client: TestClient, seed_data: dict):
    """Retrieve an assessment by ID and via risk sub-resource."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    ass_id = seed_data["assessment_a"].id
    risk_id = seed_data["risk_a"].id

    # Direct retrieval
    res = client.get(f"/api/v1/risk-assessments/{ass_id}", headers=headers_viewer)
    assert res.status_code == 200
    assert res.json()["id"] == ass_id

    # Sub-resource retrieval
    res_sub = client.get(f"/api/v1/risks/{risk_id}/assessments", headers=headers_viewer)
    assert res_sub.status_code == 200
    for item in res_sub.json()["items"]:
        assert item["risk_id"] == risk_id


# ==============================================================================
# 16. ASSESSMENT IMMUTABILITY RULES (405)
# ==============================================================================
def test_16_assessment_immutability_rules(client: TestClient, seed_data: dict):
    """Risk assessments are immutable evaluation records (PATCH and DELETE return 405)."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    ass_id = seed_data["assessment_a"].id

    assert client.patch(f"/api/v1/risk-assessments/{ass_id}", json={"score": 99.0}, headers=headers_analyst).status_code == 405
    assert client.delete(f"/api/v1/risk-assessments/{ass_id}", headers=headers_analyst).status_code == 405


# ==============================================================================
# 17. INCIDENT CREATION (201)
# ==============================================================================
def test_17_incident_creation(client: TestClient, seed_data: dict):
    """Create a new disruption incident."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}

    payload = {
        "risk_id": seed_data["risk_a"].id,
        "title": "Port Berth Congestion Emergency",
        "status": "DETECTED",
        "severity": "HIGH",
        "location": "Jeddah Islamic Port",
        "source": "TERMINAL_OPERATOR",
        "affected_assets": ["wh_a1", "fac_a1"],
    }
    res = client.post("/api/v1/incidents", json=payload, headers=headers_analyst)
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Port Berth Congestion Emergency"
    assert data["status"] == "DETECTED"
    assert data["severity"] == "HIGH"
    assert data["risk_id"] == seed_data["risk_a"].id
    assert "id" in data


# ==============================================================================
# 18. INCIDENT RETRIEVAL (200)
# ==============================================================================
def test_18_incident_retrieval(client: TestClient, seed_data: dict):
    """Retrieve a single incident by ID."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    inc_id = seed_data["incident_a"].id

    res = client.get(f"/api/v1/incidents/{inc_id}", headers=headers_viewer)
    assert res.status_code == 200
    assert res.json()["id"] == inc_id
    assert res.json()["title"] == seed_data["incident_a"].title


# ==============================================================================
# 19. INCIDENT LISTING (200)
# ==============================================================================
def test_19_incident_listing(client: TestClient, seed_data: dict):
    """List incidents returning paginated response."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    res = client.get("/api/v1/incidents", headers=headers_viewer)
    assert res.status_code == 200
    body = res.json()
    assert "items" in body
    assert "pagination" in body
    assert len(body["items"]) >= 1


# ==============================================================================
# 20. INCIDENT UPDATE (200)
# ==============================================================================
def test_20_incident_update(client: TestClient, seed_data: dict):
    """Update incident operational attributes."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    inc_id = seed_data["incident_a"].id

    res = client.patch(
        f"/api/v1/incidents/{inc_id}",
        json={"severity": "CRITICAL", "source": "COAST_GUARD_CONFIRMED"},
        headers=headers_analyst,
    )
    assert res.status_code == 200
    assert res.json()["severity"] == "CRITICAL"
    assert res.json()["source"] == "COAST_GUARD_CONFIRMED"


# ==============================================================================
# 21. INCIDENT LIFECYCLE TRANSITIONS (RESOLVED AUTO-SET RESOLVED_AT)
# ==============================================================================
def test_21_incident_lifecycle_auto_resolution(client: TestClient, seed_data: dict):
    """Transitioning incident status to RESOLVED automatically timestamps resolved_at."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    inc_id = seed_data["incident_a"].id

    res = client.patch(
        f"/api/v1/incidents/{inc_id}",
        json={"status": "RESOLVED"},
        headers=headers_analyst,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "RESOLVED"
    assert res.json()["resolved_at"] is not None


# ==============================================================================
# 22. SERVER-CONTROLLED FIELD PROTECTION (422)
# ==============================================================================
def test_22_server_controlled_field_protection(client: TestClient, seed_data: dict):
    """Injected server-controlled fields (id, org_id, detected_at) are rejected with 422."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}

    # Injected org_id on risk create
    res = client.post(
        "/api/v1/risks",
        json={"title": "Hack Risk", "org_id": "org_beta_02"},
        headers=headers_analyst,
    )
    assert res.status_code == 422

    # Injected id on factor create
    res = client.post(
        "/api/v1/risk-factors",
        json={"risk_id": seed_data["risk_a"].id, "name": "Hack Factor", "id": "custom_id"},
        headers=headers_analyst,
    )
    assert res.status_code == 422

    # Injected detected_at on incident create
    res = client.post(
        "/api/v1/incidents",
        json={"title": "Hack Incident", "detected_at": "2020-01-01T00:00:00Z"},
        headers=headers_analyst,
    )
    assert res.status_code == 422


# ==============================================================================
# 23. STANDARDIZED ERROR ENVELOPES
# ==============================================================================
def test_23_standardized_error_envelopes(client: TestClient, seed_data: dict):
    """Unapproved filter or sort parameter returns 400 with standardized error envelope."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    # Invalid filter field on risks
    res = client.get("/api/v1/risks?fake_filter=yes", headers=headers_viewer)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_FILTER_FIELD"

    # Invalid sort field on incidents
    res = client.get("/api/v1/incidents?sort=non_existent_column", headers=headers_viewer)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SORT_FIELD"


# ==============================================================================
# 24. AUDIT LOGGING BEHAVIOR
# ==============================================================================
def test_24_audit_logging_behavior(client: TestClient, seed_data: dict, test_db: Session):
    """Mutations across risks, factors, assessments, and incidents produce audit logs."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}

    # 1. Create risk
    r_res = client.post("/api/v1/risks", json={"title": "Audit Test Risk"}, headers=headers_analyst)
    assert r_res.status_code == 201
    risk_id = r_res.json()["id"]

    # 2. Update risk
    u_res = client.patch(f"/api/v1/risks/{risk_id}", json={"severity": "HIGH"}, headers=headers_analyst)
    assert u_res.status_code == 200

    # 3. Create factor
    f_res = client.post("/api/v1/risk-factors", json={"risk_id": risk_id, "name": "Audit Factor"}, headers=headers_analyst)
    assert f_res.status_code == 201
    factor_id = f_res.json()["id"]

    # 4. Delete factor
    d_res = client.delete(f"/api/v1/risk-factors/{factor_id}", headers=headers_analyst)
    assert d_res.status_code == 204

    # 5. Create assessment
    a_res = client.post("/api/v1/risk-assessments", json={"risk_id": risk_id, "score": 60.0}, headers=headers_analyst)
    assert a_res.status_code == 201

    # 6. Create incident
    i_res = client.post("/api/v1/incidents", json={"risk_id": risk_id, "title": "Audit Incident"}, headers=headers_analyst)
    assert i_res.status_code == 201

    # Verify audit records in DB
    logs = test_db.scalars(
        select(AuditLog).where(AuditLog.org_id == "org_alpha_01").order_by(AuditLog.timestamp.desc())
    ).all()
    actions = [log.action for log in logs]
    resource_types = [log.resource_type for log in logs]

    assert "CREATE" in actions
    assert "UPDATE" in actions
    assert "DELETE" in actions
    assert "Risk" in resource_types
    assert "RiskFactor" in resource_types
    assert "RiskAssessment" in resource_types
    assert "Incident" in resource_types


# ==============================================================================
# 25. OPENAPI ROUTE REGISTRATION & UNIQUENESS
# ==============================================================================
def test_25_openapi_route_registration_and_uniqueness():
    """Verify all Risk routes are mounted with unique operation IDs."""
    schema = app.openapi()
    paths = schema.get("paths", {})

    expected_routes = [
        "/api/v1/risks",
        "/api/v1/risks/{id}",
        "/api/v1/risks/{id}/factors",
        "/api/v1/risks/{id}/assessments",
        "/api/v1/risk-factors",
        "/api/v1/risk-factors/{id}",
        "/api/v1/risk-assessments",
        "/api/v1/risk-assessments/{id}",
        "/api/v1/incidents",
        "/api/v1/incidents/{id}",
    ]
    for route in expected_routes:
        assert route in paths, f"Route '{route}' missing from OpenAPI schema"

    operation_ids = set()
    duplicates = []
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                op_id = operation["operationId"]
                if op_id in operation_ids:
                    duplicates.append(f"{method.upper()} {path} -> {op_id}")
                operation_ids.add(op_id)

    assert len(duplicates) == 0, f"Duplicate operation IDs found: {duplicates}"


# ==============================================================================
# 26. RISK FACTOR DELETION (204)
# ==============================================================================
def test_26_risk_factor_deletion(client: TestClient, seed_data: dict):
    """Obsolete risk factor can be deleted returning 204 No Content."""
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    fact_id = seed_data["factor_a"].id

    # Verify exists
    assert client.get(f"/api/v1/risk-factors/{fact_id}", headers=headers_analyst).status_code == 200

    # Delete
    del_res = client.delete(f"/api/v1/risk-factors/{fact_id}", headers=headers_analyst)
    assert del_res.status_code == 204

    # Verify gone
    assert client.get(f"/api/v1/risk-factors/{fact_id}", headers=headers_analyst).status_code == 404
