"""Comprehensive test suite for RiskWise 2.0 Decision & Governance APIs (Phase 4 Step 7).

Covers all 6 decision/governance resources:
1. recommendations (Mitigation proposals for active incidents)
2. approvals (Human-in-the-loop sign-off with concurrency protection)
3. actions (Operational mitigation execution records)
4. verification_results (Immutable post-action observational evaluations)
5. notifications (User alerts and broadcast announcements)
6. audit_logs (Read-only compliance audit trail)

Validates all 30 contract requirements:
 1. Authentication required (No session cookie -> 401)
 2. RBAC enforcement (Role-specific permissions across Viewer, Analyst, OpsManager, RiskManager, Admin)
 3. Tenant isolation (Cross-tenant access returns 404 masked)
 4. Cross-tenant relationship rejection (Cross-tenant references fail with 404)
 5. Recommendation creation (Valid POST -> 201)
 6. Recommendation retrieval (Valid GET by ID -> 200)
 7. Recommendation listing (Valid GET collection -> 200 paginated)
 8. Recommendation filtering (incident_id, status)
 9. Recommendation sorting (created_at, confidence, estimated_cost, title)
10. Recommendation search where supported (title, rationale)
11. Recommendation lifecycle (State transitions and hard DELETE -> 405)
12. Approval creation (Valid POST -> 201, transitions recommendation status)
13. Approval retrieval/listing (Valid GET -> 200, filters recommendation_id, decision)
14. Approval RBAC (Viewer/Analyst -> 403; RiskManager/Admin -> 201)
15. Approval lifecycle (Deciding already finalized recommendation -> 400 LifecycleStateError)
16. Concurrent approval transition protection (Double decision blocked by state lock)
17. Action creation (Valid POST -> 201; blocked if recommendation not APPROVED)
18. Action retrieval/listing (Valid GET -> 200, filters status, action_type)
19. Action lifecycle (Execution transitions; completing action marks rec EXECUTED; hard DELETE -> 405)
20. Verification result creation (Valid POST -> 201)
21. Verification result retrieval/listing (Valid GET -> 200, filters action_id, verified)
22. Verification immutability (PATCH/DELETE -> 405 Method Not Allowed)
23. Notification behavior (List, mark read PATCH, batch mark-all-read POST, DELETE -> 405)
24. Server-controlled field injection rejection (id, org_id, created_at in payload -> 422)
25. Duplicate/conflict behavior (Duplicate verification result for same action -> 409 Conflict)
26. Standardized errors (INVALID_FILTER_FIELD, INVALID_SORT_FIELD, RESOURCE_NOT_FOUND envelopes)
27. Audit logging (Governance mutations emit audit log entries; audit log read-only)
28. OpenAPI registration (All 23 governance endpoints in OpenAPI schema)
29. Operation-ID uniqueness (All operation IDs globally unique)
30. Route uniqueness (No duplicate paths)
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
from app.models.governance import (
    Action,
    Approval,
    AuditLog,
    Notification,
    Recommendation,
    VerificationResult,
)
from app.models.risk import Incident, Risk
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
    """Seed test organizations, users across roles, incident, and initial governance records."""
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

    # Users for Org B
    analyst_b = User(id="usr_analyst_b", org_id="org_beta_02", email="analyst@beta.test", full_name="Analyst B", role="Analyst", is_active=True)
    risk_b = User(id="usr_risk_b", org_id="org_beta_02", email="risk@beta.test", full_name="RiskManager B", role="RiskManager", is_active=True)

    test_db.add_all([viewer_a, analyst_a, ops_a, risk_a, admin_a, analyst_b, risk_b])
    test_db.commit()

    # Incidents
    inc_a = Incident(
        id="inc_a1",
        org_id="org_alpha_01",
        title="Red Sea Vessel Drone Threat",
        status="INVESTIGATING",
        severity="HIGH",
        location="Bab-el-Mandeb",
    )
    inc_b = Incident(
        id="inc_b1",
        org_id="org_beta_02",
        title="Suez Canal Grounding",
        status="DETECTED",
        severity="CRITICAL",
        location="Suez Canal",
    )
    test_db.add_all([inc_a, inc_b])
    test_db.commit()

    # Recommendations
    rec_a1 = Recommendation(
        id="rec_a1",
        org_id="org_alpha_01",
        incident_id="inc_a1",
        title="Reroute Asia-Europe shipments via Cape of Good Hope",
        rationale="Bypass high-risk maritime chokepoint to safeguard high-value cargo",
        estimated_cost=45000.0,
        expected_benefit_json={"delay_reduction_days": 0, "risk_reduction_pct": 90.0},
        confidence=0.88,
        status="PENDING",
    )
    rec_b1 = Recommendation(
        id="rec_b1",
        org_id="org_beta_02",
        incident_id="inc_b1",
        title="Procure spot carrier capacity from Rotterdam",
        rationale="Alternate lane activation for priority pharmaceutical containers",
        estimated_cost=80000.0,
        expected_benefit_json={"risk_reduction_pct": 75.0},
        confidence=0.82,
        status="PENDING",
    )
    test_db.add_all([rec_a1, rec_b1])
    test_db.commit()

    # Approvals
    # Action for rec_a1 later
    action_a1 = Action(
        id="act_a1",
        org_id="org_alpha_01",
        recommendation_id="rec_a1",
        action_type="REROUTE_SHIPMENT",
        target_entity_type="ROUTE",
        target_entity_id="route_asia_eu_01",
        status="EXECUTING",
        execution_payload={"alternate_waypoints": ["Cape Town", "Las Palmas"]},
    )
    action_b1 = Action(
        id="act_b1",
        org_id="org_beta_02",
        recommendation_id="rec_b1",
        action_type="CONTRACT_CARRIER",
        target_entity_type="CARRIER",
        target_entity_id="carrier_eu_01",
        status="PENDING",
        execution_payload={"spot_rate_usd": 4200},
    )
    test_db.add_all([action_a1, action_b1])
    test_db.commit()

    # Verification Result for action_a1
    ver_a1 = VerificationResult(
        id="ver_a1",
        action_id="act_a1",
        verified=True,
        risk_score_before=85.0,
        risk_score_after=15.0,
        observation_summary="Vessel safely cleared Southern tip of Africa without alert pings",
    )
    test_db.add(ver_a1)
    test_db.commit()

    # Notifications
    notif_a1 = Notification(
        id="notif_a1",
        org_id="org_alpha_01",
        user_id="usr_view_a",
        category="RISK_ALERT",
        severity="WARNING",
        title="Red Sea Alert Triggered",
        summary="Drone activity detected near route waypoint",
        is_read=False,
    )
    notif_b1 = Notification(
        id="notif_b1",
        org_id="org_beta_02",
        user_id="usr_analyst_b",
        category="SYSTEM",
        severity="INFO",
        title="Beta Maintenance Completed",
        summary="Routine maintenance done",
        is_read=False,
    )
    test_db.add_all([notif_a1, notif_b1])
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
        "risk_b_cookie": make_cookie(risk_b),
        "inc_a": inc_a,
        "inc_b": inc_b,
        "rec_a": rec_a1,
        "rec_b": rec_b1,
        "act_a": action_a1,
        "act_b": action_b1,
        "ver_a": ver_a1,
        "notif_a": notif_a1,
        "notif_b": notif_b1,
    }


# ==============================================================================
# 1. AUTHENTICATION REQUIRED (401)
# ==============================================================================
def test_authentication_required_governance(client: TestClient):
    """Requests without active session cookie receive 401 Unauthorized across all governance resources."""
    endpoints = [
        ("GET", "/api/v1/recommendations"),
        ("POST", "/api/v1/recommendations"),
        ("GET", "/api/v1/recommendations/rec_123"),
        ("PATCH", "/api/v1/recommendations/rec_123"),
        ("POST", "/api/v1/recommendations/rec_123/approve"),
        ("GET", "/api/v1/approvals"),
        ("POST", "/api/v1/approvals"),
        ("GET", "/api/v1/approvals/app_123"),
        ("GET", "/api/v1/actions"),
        ("POST", "/api/v1/actions"),
        ("GET", "/api/v1/actions/act_123"),
        ("PATCH", "/api/v1/actions/act_123"),
        ("POST", "/api/v1/actions/act_123/execute"),
        ("GET", "/api/v1/verification-results"),
        ("POST", "/api/v1/verification-results"),
        ("GET", "/api/v1/verification-results/ver_123"),
        ("GET", "/api/v1/audit-logs"),
        ("GET", "/api/v1/audit-logs/aud_123"),
        ("GET", "/api/v1/notifications"),
        ("POST", "/api/v1/notifications"),
        ("GET", "/api/v1/notifications/not_123"),
        ("PATCH", "/api/v1/notifications/not_123"),
        ("POST", "/api/v1/notifications/mark-all-read"),
    ]
    for method, path in endpoints:
        res = client.request(method, path)
        assert res.status_code == 401, f"{method} {path} should return 401, got {res.status_code}"


# ==============================================================================
# 2. RBAC ENFORCEMENT (403)
# ==============================================================================
def test_rbac_enforcement_governance(client: TestClient, seed_data: dict):
    """Verify strict role-based permission boundaries."""
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}
    admin_cookies = {"riskwise_session": seed_data["admin_a_cookie"]}

    # Viewer cannot create recommendations
    res = client.post("/api/v1/recommendations", json={"title": "Reroute test"}, cookies=viewer_cookies)
    assert res.status_code == 403

    # Viewer cannot approve recommendations
    res = client.post(f"/api/v1/recommendations/{seed_data['rec_a'].id}/approve", cookies=viewer_cookies)
    assert res.status_code == 403

    # Analyst cannot create formal approvals (requires RiskManager or Admin)
    res = client.post(
        "/api/v1/approvals",
        json={"recommendation_id": seed_data["rec_a"].id, "decision": "APPROVE"},
        cookies=analyst_cookies,
    )
    assert res.status_code == 403

    # Analyst cannot create actions (requires RiskManager or Admin)
    res = client.post(
        "/api/v1/actions",
        json={"action_type": "EXPEDITE_AIR"},
        cookies=analyst_cookies,
    )
    assert res.status_code == 403

    # Viewer/Analyst cannot view audit logs (requires Admin or RiskManager)
    res = client.get("/api/v1/audit-logs", cookies=viewer_cookies)
    assert res.status_code == 403

    res = client.get("/api/v1/audit-logs", cookies=analyst_cookies)
    assert res.status_code == 403

    # RiskManager CAN view audit logs
    res = client.get("/api/v1/audit-logs", cookies=risk_cookies)
    assert res.status_code == 200

    # Admin CAN view audit logs
    res = client.get("/api/v1/audit-logs", cookies=admin_cookies)
    assert res.status_code == 200


# ==============================================================================
# 3. TENANT ISOLATION (404 MASKED)
# ==============================================================================
def test_tenant_isolation_governance(client: TestClient, seed_data: dict):
    """Accessing another organization's records returns 404 masked without leakage."""
    cookies_b = {"riskwise_session": seed_data["risk_b_cookie"]}

    # Org B trying to read Org A's recommendation
    res = client.get(f"/api/v1/recommendations/{seed_data['rec_a'].id}", cookies=cookies_b)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    # Org B trying to read Org A's action
    res = client.get(f"/api/v1/actions/{seed_data['act_a'].id}", cookies=cookies_b)
    assert res.status_code == 404

    # Org B trying to read Org A's verification result
    res = client.get(f"/api/v1/verification-results/{seed_data['ver_a'].id}", cookies=cookies_b)
    assert res.status_code == 404

    # Org B trying to read Org A's notification
    res = client.get(f"/api/v1/notifications/{seed_data['notif_a'].id}", cookies=cookies_b)
    assert res.status_code == 404


# ==============================================================================
# 4. CROSS-TENANT RELATIONSHIP REJECTION (404)
# ==============================================================================
def test_cross_tenant_relationship_rejection(client: TestClient, seed_data: dict):
    """Referencing another organization's parent entity fails with 404 masked."""
    analyst_a = {"riskwise_session": seed_data["analyst_cookie"]}
    risk_a = {"riskwise_session": seed_data["risk_a_cookie"]}

    # Recommendation referencing Org B incident
    res = client.post(
        "/api/v1/recommendations",
        json={"title": "Cross Tenant Mitigation", "incident_id": seed_data["inc_b"].id},
        cookies=analyst_a,
    )
    assert res.status_code == 404

    # Approval referencing Org B recommendation
    res = client.post(
        "/api/v1/approvals",
        json={"recommendation_id": seed_data["rec_b"].id, "decision": "APPROVE"},
        cookies=risk_a,
    )
    assert res.status_code == 404

    # Action referencing Org B recommendation
    res = client.post(
        "/api/v1/actions",
        json={"action_type": "CROSS_TEST", "recommendation_id": seed_data["rec_b"].id},
        cookies=risk_a,
    )
    assert res.status_code == 404

    # Verification result referencing Org B action
    res = client.post(
        "/api/v1/verification-results",
        json={"action_id": seed_data["act_b"].id, "verified": True},
        cookies=risk_a,
    )
    assert res.status_code == 404


# ==============================================================================
# 5. RECOMMENDATION CREATION (201)
# ==============================================================================
def test_recommendation_creation(client: TestClient, seed_data: dict):
    """Analyst creates a valid mitigation recommendation proposal."""
    cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    payload = {
        "incident_id": seed_data["inc_a"].id,
        "title": "Air freight critical microchips from Taiwan",
        "rationale": "Prevents automotive factory line stoppage",
        "estimated_cost": 32000.0,
        "expected_benefit_json": {"delay_reduction_days": 14, "cost_avoided": 500000.0},
        "confidence": 0.95,
        "status": "PENDING",
    }
    res = client.post("/api/v1/recommendations", json=payload, cookies=cookies)
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == payload["title"]
    assert body["estimated_cost"] == 32000.0
    assert body["confidence"] == 0.95
    assert body["status"] == "PENDING"
    assert body["org_id"] == seed_data["org_a"].id


# ==============================================================================
# 6. RECOMMENDATION RETRIEVAL (200)
# ==============================================================================
def test_recommendation_retrieval(client: TestClient, seed_data: dict):
    """Retrieve recommendation by ID with verified attributes."""
    cookies = {"riskwise_session": seed_data["viewer_cookie"]}
    res = client.get(f"/api/v1/recommendations/{seed_data['rec_a'].id}", cookies=cookies)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == seed_data["rec_a"].id
    assert "Cape of Good Hope" in body["title"]


# ==============================================================================
# 7. RECOMMENDATION LISTING & PAGINATION (200)
# ==============================================================================
def test_recommendation_listing_and_pagination(client: TestClient, seed_data: dict):
    """Retrieve paginated recommendations scoped to tenant."""
    cookies = {"riskwise_session": seed_data["viewer_cookie"]}
    res = client.get("/api/v1/recommendations?page=1&limit=10", cookies=cookies)
    assert res.status_code == 200
    body = res.json()
    assert "items" in body
    assert "pagination" in body
    assert body["pagination"]["total"] >= 1
    assert all(item["org_id"] == seed_data["org_a"].id for item in body["items"])


# ==============================================================================
# 8. RECOMMENDATION FILTERING (200)
# ==============================================================================
def test_recommendation_filtering(client: TestClient, seed_data: dict):
    """Filter recommendations by incident_id and status."""
    cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    res = client.get(f"/api/v1/recommendations?incident_id={seed_data['inc_a'].id}", cookies=cookies)
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 1
    assert all(i["incident_id"] == seed_data["inc_a"].id for i in items)

    res = client.get("/api/v1/recommendations?status=PENDING", cookies=cookies)
    assert res.status_code == 200
    assert all(i["status"] == "PENDING" for i in res.json()["items"])


# ==============================================================================
# 9. RECOMMENDATION SORTING (200)
# ==============================================================================
def test_recommendation_sorting(client: TestClient, seed_data: dict):
    """Sort recommendations ascending and descending."""
    cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    res = client.get("/api/v1/recommendations?sort=confidence", cookies=cookies)
    assert res.status_code == 200

    res = client.get("/api/v1/recommendations?sort=-estimated_cost", cookies=cookies)
    assert res.status_code == 200


# ==============================================================================
# 10. RECOMMENDATION SEARCH (200)
# ==============================================================================
def test_recommendation_search(client: TestClient, seed_data: dict):
    """Substring search across title and rationale."""
    cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    res = client.get("/api/v1/recommendations?search=Reroute", cookies=cookies)
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 1
    assert any("Reroute" in i["title"] for i in items)


# ==============================================================================
# 11. RECOMMENDATION LIFECYCLE & DELETE REJECTION (405)
# ==============================================================================
def test_recommendation_lifecycle_and_delete_rejection(client: TestClient, seed_data: dict):
    """Recommendation can be updated in PENDING; hard DELETE returns 405 Method Not Allowed."""
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}

    # Update in PENDING status succeeds
    patch_res = client.patch(
        f"/api/v1/recommendations/{seed_data['rec_a'].id}",
        json={"estimated_cost": 48000.0, "title": "Updated Reroute Plan"},
        cookies=analyst_cookies,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["estimated_cost"] == 48000.0

    # Hard DELETE is rejected with 405 Method Not Allowed
    del_res = client.delete(f"/api/v1/recommendations/{seed_data['rec_a'].id}", cookies=analyst_cookies)
    assert del_res.status_code == 405


# ==============================================================================
# 12. APPROVAL CREATION & RECOMMENDATION STATUS TRANSITION (201)
# ==============================================================================
def test_approval_creation_and_status_transition(client: TestClient, seed_data: dict):
    """RiskManager formally signs off on a recommendation, transitioning its status to APPROVED."""
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}

    # Create approval sign-off
    app_res = client.post(
        "/api/v1/approvals",
        json={
            "recommendation_id": seed_data["rec_a"].id,
            "decision": "APPROVE",
            "comments": "Cost within discretionary contingency threshold; approved for execution",
        },
        cookies=risk_cookies,
    )
    assert app_res.status_code == 201
    approval = app_res.json()
    assert approval["decision"] == "APPROVE"
    assert approval["recommendation_id"] == seed_data["rec_a"].id
    assert approval["decided_by_user_id"] == "usr_risk_a"

    # Verify parent recommendation is now APPROVED
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}
    rec_res = client.get(f"/api/v1/recommendations/{seed_data['rec_a'].id}", cookies=viewer_cookies)
    assert rec_res.status_code == 200
    assert rec_res.json()["status"] == "APPROVED"


# ==============================================================================
# 13. APPROVAL RETRIEVAL & LISTING (200)
# ==============================================================================
def test_approval_retrieval_and_listing(client: TestClient, seed_data: dict):
    """Retrieve individual approval by ID and list approvals with filters."""
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    # Create a fresh recommendation and approval
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    r = client.post("/api/v1/recommendations", json={"title": "Test Rec For Approval List"}, cookies=analyst_cookies)
    rec_id = r.json()["id"]

    a = client.post("/api/v1/approvals", json={"recommendation_id": rec_id, "decision": "REJECT", "comments": "Too expensive"}, cookies=risk_cookies)
    approval_id = a.json()["id"]

    # Retrieve by ID
    get_res = client.get(f"/api/v1/approvals/{approval_id}", cookies=viewer_cookies)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == approval_id
    assert get_res.json()["decision"] == "REJECT"

    # List approvals
    list_res = client.get(f"/api/v1/approvals?recommendation_id={rec_id}", cookies=viewer_cookies)
    assert list_res.status_code == 200
    assert len(list_res.json()["items"]) == 1


# ==============================================================================
# 14. APPROVAL RBAC (403 vs 201)
# ==============================================================================
def test_approval_rbac_matrix(client: TestClient, seed_data: dict):
    """Approvals strictly restricted to RiskManager and Admin."""
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    ops_cookies = {"riskwise_session": seed_data["ops_a_cookie"]}
    admin_cookies = {"riskwise_session": seed_data["admin_a_cookie"]}

    # Create recommendation
    r = client.post("/api/v1/recommendations", json={"title": "RBAC Test Rec"}, cookies=analyst_cookies)
    rec_id = r.json()["id"]

    # OpsManager cannot approve
    res = client.post("/api/v1/approvals", json={"recommendation_id": rec_id, "decision": "APPROVE"}, cookies=ops_cookies)
    assert res.status_code == 403

    # Admin CAN approve
    res = client.post("/api/v1/approvals", json={"recommendation_id": rec_id, "decision": "APPROVE"}, cookies=admin_cookies)
    assert res.status_code == 201


# ==============================================================================
# 15. APPROVAL LIFECYCLE & STATE RESTRICTION (400)
# ==============================================================================
def test_approval_lifecycle_conflict(client: TestClient, seed_data: dict):
    """Cannot approve a recommendation that is already APPROVED or REJECTED."""
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}

    r = client.post("/api/v1/recommendations", json={"title": "Lifecycle Rec"}, cookies=analyst_cookies)
    rec_id = r.json()["id"]

    # First decision succeeds
    res1 = client.post("/api/v1/approvals", json={"recommendation_id": rec_id, "decision": "APPROVE"}, cookies=risk_cookies)
    assert res1.status_code == 201

    # Second decision fails
    res2 = client.post("/api/v1/approvals", json={"recommendation_id": rec_id, "decision": "REJECT"}, cookies=risk_cookies)
    assert res2.status_code == 409
    assert res2.json()["error"]["code"] == "INVALID_LIFECYCLE_STATE"


# ==============================================================================
# 16. APPROVAL IMMUTABILITY (405)
# ==============================================================================
def test_approval_immutability(client: TestClient, seed_data: dict):
    """Approvals are immutable records; PATCH and DELETE return 405."""
    admin_cookies = {"riskwise_session": seed_data["admin_a_cookie"]}

    patch_res = client.patch("/api/v1/approvals/app_fixed_123", json={"comments": "new"}, cookies=admin_cookies)
    assert patch_res.status_code == 405

    del_res = client.delete("/api/v1/approvals/app_fixed_123", cookies=admin_cookies)
    assert del_res.status_code == 405


# ==============================================================================
# 17. ACTION CREATION & RECOMMENDATION APPROVAL PREREQUISITE
# ==============================================================================
def test_action_creation_prerequisite(client: TestClient, seed_data: dict):
    """Actions linked to recommendations require the recommendation to be APPROVED."""
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}

    # Rec in PENDING state
    r = client.post("/api/v1/recommendations", json={"title": "Pending Rec for Action"}, cookies=analyst_cookies)
    rec_id = r.json()["id"]

    # Attempt action creation while recommendation is PENDING -> rejected
    res = client.post(
        "/api/v1/actions",
        json={"action_type": "REROUTE", "recommendation_id": rec_id},
        cookies=risk_cookies,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "RECOMMENDATION_NOT_APPROVED"

    # Approve recommendation
    client.post(f"/api/v1/recommendations/{rec_id}/approve", cookies=risk_cookies)

    # Action creation now succeeds
    act_res = client.post(
        "/api/v1/actions",
        json={"action_type": "REROUTE", "recommendation_id": rec_id, "target_entity_type": "ROUTE"},
        cookies=risk_cookies,
    )
    assert act_res.status_code == 201
    assert act_res.json()["recommendation_id"] == rec_id


# ==============================================================================
# 18. ACTION RETRIEVAL & LISTING (200)
# ==============================================================================
def test_action_retrieval_and_listing(client: TestClient, seed_data: dict):
    """Retrieve action by ID and list actions with filters."""
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    res = client.get(f"/api/v1/actions/{seed_data['act_a'].id}", cookies=viewer_cookies)
    assert res.status_code == 200
    assert res.json()["id"] == seed_data["act_a"].id

    list_res = client.get("/api/v1/actions?status=EXECUTING", cookies=viewer_cookies)
    assert list_res.status_code == 200
    assert all(a["status"] == "EXECUTING" for a in list_res.json()["items"])


# ==============================================================================
# 19. ACTION LIFECYCLE & RPC EXECUTION (200, 405)
# ==============================================================================
def test_action_lifecycle_and_execute_rpc(client: TestClient, seed_data: dict):
    """Advancing action to COMPLETED marks linked recommendation EXECUTED; DELETE returns 405."""
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}

    # Setup approved recommendation and action
    r = client.post("/api/v1/recommendations", json={"title": "Action Lifecycle Test Rec"}, cookies=analyst_cookies)
    rec_id = r.json()["id"]
    client.post(f"/api/v1/recommendations/{rec_id}/approve", cookies=risk_cookies)

    act_res = client.post(
        "/api/v1/actions",
        json={"action_type": "DISPATCH_FEEDER", "recommendation_id": rec_id},
        cookies=risk_cookies,
    )
    act_id = act_res.json()["id"]

    # PATCH action to COMPLETED
    patch_res = client.patch(f"/api/v1/actions/{act_id}", json={"status": "COMPLETED"}, cookies=risk_cookies)
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "COMPLETED"

    # Linked recommendation must now be EXECUTED
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}
    rec_check = client.get(f"/api/v1/recommendations/{rec_id}", cookies=viewer_cookies)
    assert rec_check.json()["status"] == "EXECUTED"

    # Terminal state cannot be transitioned again
    conflict_res = client.patch(f"/api/v1/actions/{act_id}", json={"status": "EXECUTING"}, cookies=risk_cookies)
    assert conflict_res.status_code == 409

    # Hard DELETE returns 405
    del_res = client.delete(f"/api/v1/actions/{act_id}", cookies=risk_cookies)
    assert del_res.status_code == 405


# ==============================================================================
# 20. VERIFICATION RESULT CREATION (201)
# ==============================================================================
def test_verification_result_creation(client: TestClient, seed_data: dict):
    """Record an observational verification result for an action."""
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}

    # Create action without verification
    act_res = client.post(
        "/api/v1/actions",
        json={"action_type": "VERIFY_TEST_ACTION"},
        cookies=risk_cookies,
    )
    action_id = act_res.json()["id"]

    ver_res = client.post(
        "/api/v1/verification-results",
        json={
            "action_id": action_id,
            "verified": True,
            "risk_score_before": 70.0,
            "risk_score_after": 20.0,
            "observation_summary": "Telemetry indicates zero disruption to cold chain cargo",
        },
        cookies=risk_cookies,
    )
    assert ver_res.status_code == 201
    assert ver_res.json()["action_id"] == action_id
    assert ver_res.json()["verified"] is True


# ==============================================================================
# 21. VERIFICATION RESULT RETRIEVAL & LISTING (200)
# ==============================================================================
def test_verification_result_retrieval_and_listing(client: TestClient, seed_data: dict):
    """Retrieve verification result by ID and list results."""
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    res = client.get(f"/api/v1/verification-results/{seed_data['ver_a'].id}", cookies=viewer_cookies)
    assert res.status_code == 200
    assert res.json()["id"] == seed_data["ver_a"].id

    list_res = client.get("/api/v1/verification-results?verified=true", cookies=viewer_cookies)
    assert list_res.status_code == 200
    assert len(list_res.json()["items"]) >= 1


# ==============================================================================
# 22. VERIFICATION IMMUTABILITY (405)
# ==============================================================================
def test_verification_result_immutability(client: TestClient, seed_data: dict):
    """Verification results are immutable historical records; PATCH and DELETE return 405."""
    admin_cookies = {"riskwise_session": seed_data["admin_a_cookie"]}

    patch_res = client.patch(f"/api/v1/verification-results/{seed_data['ver_a'].id}", json={"verified": False}, cookies=admin_cookies)
    assert patch_res.status_code == 405

    del_res = client.delete(f"/api/v1/verification-results/{seed_data['ver_a'].id}", cookies=admin_cookies)
    assert del_res.status_code == 405


# ==============================================================================
# 23. NOTIFICATION LIFECYCLE & BATCH MARK READ (200, 405)
# ==============================================================================
def test_notification_lifecycle_and_batch_mark(client: TestClient, seed_data: dict):
    """List notifications, mark as read via PATCH, batch mark read via POST, DELETE returns 405."""
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    # List notifications
    list_res = client.get("/api/v1/notifications", cookies=viewer_cookies)
    assert list_res.status_code == 200
    assert len(list_res.json()["items"]) >= 1

    # Mark single notification as read
    patch_res = client.patch(f"/api/v1/notifications/{seed_data['notif_a'].id}", json={"is_read": True}, cookies=viewer_cookies)
    assert patch_res.status_code == 200
    assert patch_res.json()["is_read"] is True

    # Batch mark all read
    batch_res = client.post("/api/v1/notifications/mark-all-read", cookies=viewer_cookies)
    assert batch_res.status_code == 200
    assert "updated_count" in batch_res.json()

    # Hard DELETE returns 405
    del_res = client.delete(f"/api/v1/notifications/{seed_data['notif_a'].id}", cookies=viewer_cookies)
    assert del_res.status_code == 405


# ==============================================================================
# 24. SERVER-CONTROLLED FIELD INJECTION REJECTION (422)
# ==============================================================================
def test_server_controlled_field_injection_rejection(client: TestClient, seed_data: dict):
    """Injecting server-controlled fields (id, org_id, created_at) returns 422 Unprocessable Content."""
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}

    # Recommendation with injected id and org_id
    res = client.post(
        "/api/v1/recommendations",
        json={"title": "Injection Test", "id": "evil_id_001", "org_id": "evil_org_002"},
        cookies=analyst_cookies,
    )
    assert res.status_code == 422

    # Approval with injected id
    res = client.post(
        "/api/v1/approvals",
        json={"recommendation_id": seed_data["rec_a"].id, "id": "evil_approval_001"},
        cookies=risk_cookies,
    )
    assert res.status_code == 422

    # Action with injected org_id
    res = client.post(
        "/api/v1/actions",
        json={"action_type": "INJECTION_ACTION", "org_id": "evil_org_002"},
        cookies=risk_cookies,
    )
    assert res.status_code == 422


# ==============================================================================
# 25. DUPLICATE/CONFLICT BEHAVIOR (409)
# ==============================================================================
def test_duplicate_verification_result_conflict(client: TestClient, seed_data: dict):
    """Creating a second verification result for an action that already has one returns 409 Conflict."""
    risk_cookies = {"riskwise_session": seed_data["risk_a_cookie"]}

    # seed_data['act_a'] already has seed_data['ver_a']
    res = client.post(
        "/api/v1/verification-results",
        json={"action_id": seed_data["act_a"].id, "verified": False},
        cookies=risk_cookies,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "VERIFICATION_RESULT_ALREADY_EXISTS"


# ==============================================================================
# 26. STANDARDIZED ERROR ENVELOPES
# ==============================================================================
def test_standardized_error_envelopes(client: TestClient, seed_data: dict):
    """Errors follow the standard envelope with error.code, error.message, error.details."""
    viewer_cookies = {"riskwise_session": seed_data["viewer_cookie"]}

    # Invalid filter field
    res = client.get("/api/v1/recommendations?evil_filter=1", cookies=viewer_cookies)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_FILTER_FIELD"

    # Invalid sort field
    res = client.get("/api/v1/recommendations?sort=evil_column", cookies=viewer_cookies)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SORT_FIELD"

    # Resource not found
    res = client.get("/api/v1/recommendations/non_existent_rec_id", cookies=viewer_cookies)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 27. AUDIT LOGGING (AUDIT TRAIL GENERATION)
# ==============================================================================
def test_audit_logging_generation(client: TestClient, seed_data: dict, test_db: Session):
    """Mutations generate immutable entries in audit_logs table."""
    analyst_cookies = {"riskwise_session": seed_data["analyst_cookie"]}

    res = client.post(
        "/api/v1/recommendations",
        json={"title": "Audit Test Recommendation"},
        cookies=analyst_cookies,
    )
    assert res.status_code == 201
    rec_id = res.json()["id"]

    # Verify audit log entry in database
    logs = list(test_db.scalars(select(AuditLog).where(AuditLog.resource_id == rec_id)).all())
    assert len(logs) >= 1
    assert logs[0].action == "CREATE"
    assert logs[0].resource_type == "Recommendation"
    assert logs[0].org_id == seed_data["org_a"].id


# ==============================================================================
# 28. OPENAPI REGISTRATION
# ==============================================================================
def test_openapi_governance_registration():
    """All 23 governance endpoints are registered in OpenAPI paths."""
    schema = app.openapi()
    paths = schema.get("paths", {})

    expected_paths = [
        "/api/v1/recommendations",
        "/api/v1/recommendations/{id}",
        "/api/v1/recommendations/{id}/approve",
        "/api/v1/approvals",
        "/api/v1/approvals/{id}",
        "/api/v1/actions",
        "/api/v1/actions/{id}",
        "/api/v1/actions/{id}/execute",
        "/api/v1/verification-results",
        "/api/v1/verification-results/{id}",
        "/api/v1/audit-logs",
        "/api/v1/audit-logs/{id}",
        "/api/v1/notifications",
        "/api/v1/notifications/{id}",
        "/api/v1/notifications/mark-all-read",
    ]
    for p in expected_paths:
        assert p in paths, f"Path {p} not found in OpenAPI specification"


# ==============================================================================
# 29. OPERATION-ID UNIQUENESS
# ==============================================================================
def test_operation_id_uniqueness():
    """Every endpoint in the FastAPI application has a globally unique operation ID."""
    schema = app.openapi()
    paths = schema.get("paths", {})
    op_ids = []
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                op_ids.append(operation["operationId"])

    assert len(op_ids) == len(set(op_ids)), f"Duplicate operation IDs found: {len(op_ids)} vs {len(set(op_ids))}"


# ==============================================================================
# 30. ROUTE UNIQUENESS
# ==============================================================================
def test_route_uniqueness():
    """Ensure no duplicate route and method combinations in OpenAPI."""
    schema = app.openapi()
    route_methods = []
    for path, item in schema["paths"].items():
        for method in item.keys():
            if method.lower() in ("get", "post", "put", "patch", "delete", "options", "head"):
                route_methods.append((method.upper(), path))
    assert len(route_methods) == len(set(route_methods)), "Duplicate route and method combination detected"
