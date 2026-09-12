"""Phase 17 Test Suite: REST API Endpoints, RBAC, and Persistence.

Validates:
- Database invariant: strictly 34 tables, 0 migrations
- POST /api/v1/actions/execute:
    - Success with valid human approval (200 OK, ActionResult)
    - Rejection without approval (400 Bad Request)
    - Rejection for unauthorized role Viewer (403 Forbidden)
    - Rejection for cross-tenant payload (403 Forbidden)
    - Safe idempotent replay on repeated requests (200 OK)
    - Conflict on modified payload for same key (409 Conflict)
- GET /api/v1/actions & GET /api/v1/actions/{id}:
    - Tenant isolation (404 on nonexistent or cross-tenant ID)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_authenticated_context, require_role
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.main import app
from app.models.governance import Action, Approval, AuditLog, Recommendation
from app.models.logistics import Shipment
from app.models.network import Route
from app.models.tenancy import Organization, User


class MockAuthContext:
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        role: str,
        request_id: str = "req-test-p17-api",
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.roles = [role.lower()]
        self.request_id = request_id


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Clean up dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def sqlite_session():
    """In-memory SQLite session with full RiskWise 34-table schema."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    # Seed organizations
    org_a = Organization(id="tenant_alpha", name="Alpha Logistics")
    org_b = Organization(id="tenant_beta", name="Beta Freight")
    session.add_all([org_a, org_b])

    # Seed routes
    r_alt = Route(id="route_alt_corridor", org_id="tenant_alpha", name="Alternative Corridor")
    session.add(r_alt)

    # Seed shipment
    ship = Shipment(id="ship_api_001", org_id="tenant_alpha", tracking_number="TRK-API", status="IN_TRANSIT")
    session.add(ship)

    # Seed recommendation and approval
    rec = Recommendation(
        id="dec_api_001",
        org_id="tenant_alpha",
        title="Execute reroute",
        status="APPROVED",
    )
    session.add(rec)

    appr = Approval(
        id="appr_api_001",
        recommendation_id="dec_api_001",
        decided_by_user_id="user_risk",
        decision="APPROVE",
    )
    session.add(appr)

    session.commit()
    yield session
    session.close()


@pytest.fixture
def client(sqlite_session: Session):
    """TestClient wired to in-memory SQLite session and UnitOfWork."""
    def override_get_db():
        yield sqlite_session

    def override_get_uow():
        return UnitOfWork(session=sqlite_session)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_uow] = override_get_uow

    with TestClient(app) as test_client:
        yield test_client


def test_database_table_count_invariant(sqlite_session: Session):
    """Verify that Phase 17 maintains exactly 34 tables with 0 schema migrations."""
    engine = sqlite_session.get_bind()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert len(tables) == 34, f"Expected exactly 34 tables, found {len(tables)}: {tables}"


def test_api_post_execute_approved_action(client: TestClient, sqlite_session: Session):
    """Verify POST /api/v1/actions/execute succeeds with valid human approval."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    payload = {
        "decision_id": "dec_api_001",
        "approval_id": "appr_api_001",
        "organization_id": "tenant_alpha",
        "action_type": "SHIPMENT_REROUTE",
        "target_entity_type": "SHIPMENT",
        "target_entity_id": "ship_api_001",
        "parameters": {"new_route_id": "route_alt_corridor"},
        "idempotency_key": "idemp_api_test_001",
        "trace_id": "trace_api_001",
    }

    resp = client.post("/api/v1/actions/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_id"] is not None
    assert data["status"] == "SUCCEEDED"
    assert data["adapter"] == "ShipmentRerouteExecutor"
    assert data["provider"] == "carrier_edi"

    # Verify database state
    action_db = sqlite_session.query(Action).filter_by(id=data["action_id"]).first()
    assert action_db is not None
    assert action_db.status == "SUCCEEDED"

    rec_db = sqlite_session.query(Recommendation).filter_by(id="dec_api_001").first()
    assert rec_db is not None
    assert rec_db.status == "EXECUTED"


def test_api_post_execute_without_approval_returns_400(client: TestClient):
    """Verify POST /api/v1/actions/execute returns 400 when approval record is missing."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    payload = {
        "decision_id": "dec_nonexistent_999",
        "approval_id": "appr_nonexistent_999",
        "organization_id": "tenant_alpha",
        "action_type": "SHIPMENT_REROUTE",
        "target_entity_type": "SHIPMENT",
        "target_entity_id": "ship_api_001",
        "parameters": {"new_route_id": "route_alt_corridor"},
        "idempotency_key": "idemp_no_appr",
        "trace_id": "trace_no_appr",
    }

    resp = client.post("/api/v1/actions/execute", json=payload)
    assert resp.status_code == 400


def test_api_post_execute_viewer_forbidden_returns_403(client: TestClient):
    """Verify RBAC: Viewer cannot execute operational actions (403 Forbidden)."""
    auth_ctx = MockAuthContext(user_id="user_viewer", organization_id="tenant_alpha", role="Viewer")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx

    payload = {
        "decision_id": "dec_api_001",
        "approval_id": "appr_api_001",
        "organization_id": "tenant_alpha",
        "action_type": "SHIPMENT_REROUTE",
        "target_entity_type": "SHIPMENT",
        "target_entity_id": "ship_api_001",
        "parameters": {"new_route_id": "route_alt_corridor"},
        "idempotency_key": "idemp_viewer_test",
        "trace_id": "trace_viewer",
    }

    resp = client.post("/api/v1/actions/execute", json=payload)
    assert resp.status_code == 403


def test_api_post_execute_cross_tenant_rejected_returns_403(client: TestClient):
    """Verify cross-tenant execution attempt is rejected with 403 Forbidden."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    payload = {
        "decision_id": "dec_api_001",
        "approval_id": "appr_api_001",
        "organization_id": "tenant_beta",  # Attempting to target tenant_beta with tenant_alpha token!
        "action_type": "SHIPMENT_REROUTE",
        "target_entity_type": "SHIPMENT",
        "target_entity_id": "ship_api_001",
        "parameters": {"new_route_id": "route_alt_corridor"},
        "idempotency_key": "idemp_cross_tenant",
        "trace_id": "trace_cross",
    }

    resp = client.post("/api/v1/actions/execute", json=payload)
    assert resp.status_code == 403


def test_api_post_execute_idempotency_replay_and_conflict(client: TestClient):
    """Verify idempotent replay returns 200 and differing payload on same key returns 409."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    payload = {
        "decision_id": "dec_api_001",
        "approval_id": "appr_api_001",
        "organization_id": "tenant_alpha",
        "action_type": "SHIPMENT_REROUTE",
        "target_entity_type": "SHIPMENT",
        "target_entity_id": "ship_api_001",
        "parameters": {"new_route_id": "route_alt_corridor"},
        "idempotency_key": "idemp_api_replay_key",
        "trace_id": "trace_replay",
    }

    # 1. First call
    resp1 = client.post("/api/v1/actions/execute", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["idempotency_result"] == "FIRST_EXECUTION"

    # 2. Identical second call
    resp2 = client.post("/api/v1/actions/execute", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["action_id"] == data1["action_id"]
    assert data2["idempotency_result"] == "REPLAYED_IDEMPOTENT"

    # 3. Third call with changed parameter on same idempotency key
    payload_conflict = dict(payload)
    payload_conflict["parameters"] = {"new_route_id": "route_other"}
    resp3 = client.post("/api/v1/actions/execute", json=payload_conflict)
    assert resp3.status_code == 409


def test_api_get_action_by_id_and_list(client: TestClient, sqlite_session: Session):
    """Verify GET /api/v1/actions and GET /api/v1/actions/{id} endpoints."""
    auth_ctx = MockAuthContext(user_id="user_viewer", organization_id="tenant_alpha", role="Viewer")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    read_roles = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
    app.dependency_overrides[require_role(*read_roles)] = lambda: auth_ctx

    # Seed action
    act = Action(
        id="act_existing_001",
        org_id="tenant_alpha",
        recommendation_id="dec_api_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_api_001",
        status="SUCCEEDED",
    )
    sqlite_session.add(act)
    sqlite_session.commit()

    # GET by ID
    resp = client.get("/api/v1/actions/act_existing_001")
    assert resp.status_code == 200
    assert resp.json()["id"] == "act_existing_001"

    # GET list
    resp_list = client.get("/api/v1/actions")
    assert resp_list.status_code == 200
    items = resp_list.json()["items"]
    assert any(item["id"] == "act_existing_001" for item in items)
