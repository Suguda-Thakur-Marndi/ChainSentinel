"""Test suite for company-aware authentication, multi-organization memberships,
organization switching, and tenant-level authorization isolation.
"""
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as models
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.session_service import MemorySessionStore, SessionService, get_session_service


@pytest.fixture(scope="function")
def test_db_session():
    """Isolated SQLite in-memory database fixture with foreign keys enabled."""
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
def memory_session_service():
    """Isolated in-memory session service."""
    return SessionService(store=MemorySessionStore())


@pytest.fixture(scope="function")
def client(test_db_session: Session, memory_session_service: SessionService):
    """FastAPI TestClient with dependency overrides."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    def override_session_service():
        return memory_session_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = override_session_service

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_one_user_with_one_organization(client: TestClient, test_db_session: Session):
    """Test 1: User registers one company, has exactly one membership, and active tenant matches."""
    reg_resp = client.post("/api/v1/auth/register-company", json={
        "full_name": "Alice Single",
        "company_name": "Solo Logistics Corp",
        "email": "alice.single@solologistics.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    })
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    org_id = reg_data["org_id"]
    assert org_id is not None
    assert reg_data["role"] == "ADMIN"
    assert len(reg_data["organizations"]) == 1
    assert reg_data["organizations"][0]["org_id"] == org_id
    assert reg_data["organizations"][0]["organization_name"] == "Solo Logistics Corp"

    # Profile check via GET /api/v1/auth/me
    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["org_id"] == org_id
    assert len(me_data["organizations"]) == 1
    assert me_data["organizations"][0]["org_id"] == org_id

    # Can access protected operational resources in this tenant
    ship_resp = client.get("/api/v1/shipments")
    assert ship_resp.status_code == 200


def test_one_user_with_multiple_organizations_and_switching(client: TestClient, test_db_session: Session):
    """Test 2 & 3: One user belongs to multiple organizations and can switch active tenant context."""
    # 1. Alice registers Company A
    reg_a = client.post("/api/v1/auth/register-company", json={
        "full_name": "Alice Multi",
        "company_name": "Alpha Freight Inc",
        "email": "alice.multi@alphafreight.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()
    org_a_id = reg_a["org_id"]

    # 2. Bob registers Company B
    client.cookies.clear()
    reg_b = client.post("/api/v1/auth/register-company", json={
        "full_name": "Bob Enterprise",
        "company_name": "Beta Ocean Lines",
        "email": "bob@betaocean.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()
    org_b_id = reg_b["org_id"]

    # 3. Bob invites Alice to Company B as an ANALYST
    inv_resp = client.post("/api/v1/auth/invitations", json={
        "email": "alice.multi@alphafreight.com",
        "role": "ANALYST",
    })
    assert inv_resp.status_code == 201
    inv_token = inv_resp.json()["invitation_link"].split("/auth/invite/")[1]

    # 4. Alice accepts the invitation to Company B
    client.cookies.clear()
    accept_resp = client.post(f"/api/v1/auth/invitations/{inv_token}/accept", json={
        "full_name": "Alice Multi",
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert accept_resp.status_code == 200
    accept_data = accept_resp.json()

    # Alice is now active in Company B with role ANALYST
    assert accept_data["org_id"] == org_b_id
    assert accept_data["role"] == "ANALYST"

    # Alice now has authorized memberships in BOTH Company A and Company B
    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert len(me_data["organizations"]) == 2

    org_ids_in_me = {o["org_id"] for o in me_data["organizations"]}
    assert org_a_id in org_ids_in_me
    assert org_b_id in org_ids_in_me

    # 5. Switch active tenant context back to Company A
    switch_a = client.post("/api/v1/auth/switch-org", json={"org_id": org_a_id})
    assert switch_a.status_code == 200
    switch_a_data = switch_a.json()
    assert switch_a_data["active_organization_id"] == org_a_id
    assert switch_a_data["role"] == "ADMIN"
    assert switch_a_data["user"]["org_id"] == org_a_id

    # Confirm GET /me reflects Company A and ADMIN permissions
    me_a = client.get("/api/v1/auth/me").json()
    assert me_a["org_id"] == org_a_id
    assert me_a["role"] == "ADMIN"
    assert "agents:trigger" in me_a["permissions"]

    # 6. Switch active tenant context back to Company B
    switch_b = client.post("/api/v1/auth/switch-org", json={"org_id": org_b_id})
    assert switch_b.status_code == 200
    switch_b_data = switch_b.json()
    assert switch_b_data["active_organization_id"] == org_b_id
    assert switch_b_data["role"] == "ANALYST"

    # Confirm GET /me reflects Company B and ANALYST role
    me_b = client.get("/api/v1/auth/me").json()
    assert me_b["org_id"] == org_b_id
    assert me_b["role"] == "ANALYST"


def test_organization_switching_unauthorized_rejection(client: TestClient, test_db_session: Session):
    """Test 4: User attempting to switch to an organization they do not belong to is rejected with 403."""
    # 1. Alice registers Company A
    reg_a = client.post("/api/v1/auth/register-company", json={
        "full_name": "Alice Tenant",
        "company_name": "Company Alpha",
        "email": "alice@alpha.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()
    org_a_id = reg_a["org_id"]

    # 2. Charlie registers Company C
    client.cookies.clear()
    reg_c = client.post("/api/v1/auth/register-company", json={
        "full_name": "Charlie External",
        "company_name": "Company Charlie",
        "email": "charlie@charlie.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()
    org_c_id = reg_c["org_id"]

    # 3. Log back in as Alice
    client.cookies.clear()
    login_a = client.post("/api/v1/auth/login", json={
        "email": "alice@alpha.com",
        "password": "Password123!",
    })
    assert login_a.status_code == 200

    # 4. Alice attempts to switch into Company C
    switch_denied = client.post("/api/v1/auth/switch-org", json={"org_id": org_c_id})
    assert switch_denied.status_code == 403
    assert "not an authorized member" in switch_denied.json()["detail"].lower()

    # Alice's active organization remains Company A
    me = client.get("/api/v1/auth/me").json()
    assert me["org_id"] == org_a_id


def test_user_without_organization_membership(client: TestClient, test_db_session: Session):
    """Test 5: Authenticated user without any organization membership resolves to onboarding-required

    and is strictly denied access to protected operational resources.
    """
    # Create an unassigned user directly in database
    unassigned_user = models.User(
        email="unassigned@independent.io",
        full_name="Independent Contractor",
        role="VIEWER",
        org_id=None,
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    test_db_session.add(unassigned_user)
    test_db_session.commit()
    test_db_session.refresh(unassigned_user)

    # User signs in
    client.cookies.clear()
    login_resp = client.post("/api/v1/auth/login", json={
        "email": "unassigned@independent.io",
        "password": "Password123!",
    })
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["org_id"] is None
    assert login_data["organization"] is None
    assert len(login_data["organizations"]) == 0

    # GET /me returns unassigned profile
    me_resp = client.get("/api/v1/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["org_id"] is None
    assert me_data["organization"] is None
    assert len(me_data["organizations"]) == 0

    # Protected operational endpoints requiring tenant context strictly return 403
    ship_resp = client.get("/api/v1/shipments")
    assert ship_resp.status_code == 403

    supp_resp = client.get("/api/v1/suppliers")
    assert supp_resp.status_code == 403

    inc_resp = client.get("/api/v1/incidents")
    assert inc_resp.status_code == 403

    audit_resp = client.get("/api/v1/audit-logs")
    assert audit_resp.status_code == 403


def test_cross_tenant_access_denial_by_changing_id(client: TestClient, test_db_session: Session):
    """Test 6: Negative test — verifying that modifying resource IDs across tenants returns 404 masked."""
    # 1. Register Tenant A and seed confidential resources
    reg_a = client.post("/api/v1/auth/register-company", json={
        "full_name": "Org A Admin",
        "company_name": "Org A Defense Ltd",
        "email": "admin@orga.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()
    org_a_id = reg_a["org_id"]

    supplier_a = models.Supplier(
        org_id=org_a_id,
        name="Confidential Aerospace Supplier A",
        code="SUP-SECRET-01",
        country="US",
        tier="CRITICAL",
    )
    shipment_a = models.Shipment(
        org_id=org_a_id,
        tracking_number="TRK-SECRET-A-777",
        status="IN_TRANSIT",
        origin="Savannah",
        destination="Hamburg",
    )
    incident_a = models.Incident(
        org_id=org_a_id,
        title="Critical Disruption Incident A",
        severity="HIGH",
        status="ACTIVE",
    )
    audit_a = models.AuditLog(
        org_id=org_a_id,
        resource_type="GOVERNANCE",
        action="EXPORT_DEFENSE_SPECS",
        actor_id="user_a",
    )
    test_db_session.add_all([supplier_a, shipment_a, incident_a, audit_a])
    test_db_session.commit()
    test_db_session.refresh(supplier_a)
    test_db_session.refresh(shipment_a)
    test_db_session.refresh(incident_a)

    # 2. Register Tenant B
    client.cookies.clear()
    reg_b = client.post("/api/v1/auth/register-company", json={
        "full_name": "Org B Admin",
        "company_name": "Org B Commercial Ltd",
        "email": "admin@orgb.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()

    # 3. Tenant B attempts cross-tenant retrieval by targeting Tenant A's IDs -> 404 Not Found
    s_get = client.get(f"/api/v1/suppliers/{supplier_a.id}")
    assert s_get.status_code == 404
    assert "not found" in s_get.json()["detail"].lower()

    shp_get = client.get(f"/api/v1/shipments/{shipment_a.id}")
    assert shp_get.status_code == 404
    assert "not found" in shp_get.json()["detail"].lower()

    inc_get = client.get(f"/api/v1/incidents/{incident_a.id}")
    assert inc_get.status_code == 404
    assert "not found" in inc_get.json()["detail"].lower()

    # Tenant B lists resources -> sees 0 items belonging to Tenant A
    assert len(client.get("/api/v1/suppliers").json()["items"]) == 0
    assert len(client.get("/api/v1/shipments").json()["items"]) == 0
    assert len(client.get("/api/v1/incidents").json()["items"]) == 0
    assert len(client.get("/api/v1/audit-logs").json()["items"]) == 0


def test_unauthorized_role_based_actions(client: TestClient, test_db_session: Session):
    """Test 7: Verify RBAC gates prevent unauthorized role-based mutations."""
    # 1. Register organization as Owner/Admin
    reg = client.post("/api/v1/auth/register-company", json={
        "full_name": "Org Owner",
        "company_name": "Role Test Logistics",
        "email": "owner@roletest.com",
        "password": "Password123!",
        "confirm_password": "Password123!",
        "terms_accepted": True,
    }).json()

    # 2. Invite a team member as VIEWER
    inv_resp = client.post("/api/v1/auth/invitations", json={
        "email": "viewer@roletest.com",
        "role": "VIEWER",
    })
    assert inv_resp.status_code == 201
    token = inv_resp.json()["invitation_link"].split("/auth/invite/")[1]

    # 3. Viewer accepts invitation
    client.cookies.clear()
    accept = client.post(f"/api/v1/auth/invitations/{token}/accept", json={
        "full_name": "Viewer User",
        "password": "Password123!",
        "confirm_password": "Password123!",
    })
    assert accept.status_code == 200
    assert accept.json()["role"] == "VIEWER"

    # 4. Viewer attempts to invite another employee -> 403 Forbidden (requires Admin)
    inv_denied = client.post("/api/v1/auth/invitations", json={
        "email": "another@roletest.com",
        "role": "VIEWER",
    })
    assert inv_denied.status_code == 403

    # 5. Viewer attempts to create a supplier -> 403 Forbidden (requires Analyst+)
    create_supp_denied = client.post("/api/v1/suppliers", json={
        "name": "Unauthorized Supplier",
        "country": "US",
        "tier": "LOW",
    })
    assert create_supp_denied.status_code == 403
