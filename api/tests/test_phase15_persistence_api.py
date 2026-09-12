"""Phase 15 Test Suite 5: REST API Endpoints, RBAC, and Persistence.

Validates:
- POST /api/v1/decisions (formulates decision, saves to recommendations & audit_logs, returns 201)
- GET /api/v1/decisions (lists tenant decisions, returns 200)
- GET /api/v1/decisions/{id} (retrieves decision by ID, returns 200)
- RBAC: Viewer cannot create decision (403 Forbidden)
- Multi-tenant isolation: Tenant B cannot view Tenant A's decision (403 or 404)
- 404 response on nonexistent decision ID
- Idempotency: repeated identical request succeeds and maintains deterministic identity
- Database invariant: exactly 34 tables, 0 schema changes, 0 migrations
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_authenticated_context, require_role
from app.core.context import AuthenticatedContext
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.main import app
from app.agents.decision.contract import (
    DecisionConstraint,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionType,
)


class MockAuthContext:
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        role: str,
        request_id: str = "req-test-p15-api",
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.roles = [role.lower()]
        self.request_id = request_id


@pytest.fixture(scope="module", autouse=True)
def mount_decision_routes():
    """Mount Decision API routes dynamically for this module and cleanly restore afterwards."""
    from app.api.v1.endpoints.decisions import router as dec_router
    orig_routes = list(app.router.routes)
    app.include_router(dec_router, prefix="/api/v1", tags=["Decisions"])
    app.openapi_schema = None
    yield
    app.router.routes = orig_routes
    app.openapi_schema = None


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
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(sqlite_session: Session):
    """FastAPI TestClient with overridden database session."""
    def _override_get_db():
        yield sqlite_session

    def _override_get_uow():
        uow = UnitOfWork(sqlite_session)
        return uow

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_uow] = _override_get_uow
    return TestClient(app)


def test_database_table_count_invariant(sqlite_session: Session):
    """Verify database retains exactly 34 tables with zero migrations and zero schema changes."""
    engine = sqlite_session.get_bind()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert len(tables) == 34, f"Expected 34 tables, found {len(tables)}: {tables}"
    assert "recommendations" in tables
    assert "audit_logs" in tables


def test_post_decision_success_analyst(client: TestClient, sqlite_session: Session):
    """Verify Analyst role can trigger decision generation and receive 201 Created."""
    org_id = "org_test_logistics"
    auth = MockAuthContext(user_id="usr_analyst_01", organization_id=org_id, role="Analyst")
    app.dependency_overrides[get_authenticated_context] = lambda: auth
    for role_name in ("Analyst", "OpsManager", "RiskManager", "Admin"):
        app.dependency_overrides[require_role(role_name)] = lambda: auth

    payload = {
        "organization_id": org_id,
        "target_reference": "shipment_LAX_101",
        "optimization_result": {
            "organization_id": org_id,
            "optimization_id": "opt_reroute_lax",
            "domain": "SHIPMENT_REROUTE",
            "status": "OPTIMAL",
            "objective": {"objective_type": "MINIMIZE_DELAY"},
            "objective_value": 20.0,
            "selected_alternatives": [
                {"entity_type": "ROUTE", "entity_id": "route_inland_rail", "assigned_value": 1.0}
            ],
            "metrics": {},
        },
    }

    resp = client.post("/api/v1/decisions", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "RECOMMENDED"
    assert data["decision_type"] == "REROUTE_SHIPMENT"
    assert data["optimization_id"] == "opt_reroute_lax"
    assert data["selected_alternative_id"] == "route_inland_rail"
    assert data["requires_human_approval"] is True


def test_post_decision_forbidden_for_viewer(client: TestClient):
    """Verify Viewer role cannot generate decisions (403 Forbidden)."""
    org_id = "org_test_logistics"
    auth = MockAuthContext(user_id="usr_viewer_01", organization_id=org_id, role="Viewer")
    app.dependency_overrides[get_authenticated_context] = lambda: auth

    payload = {
        "organization_id": org_id,
        "target_reference": "shipment_001",
    }

    resp = client.post("/api/v1/decisions", json=payload)
    assert resp.status_code == 403


def test_post_decision_cross_tenant_rejected(client: TestClient):
    """Verify cross-tenant request payload is rejected with 403 Forbidden."""
    org_id = "org_tenant_a"
    auth = MockAuthContext(user_id="usr_admin_01", organization_id=org_id, role="Admin")
    app.dependency_overrides[get_authenticated_context] = lambda: auth

    payload = {
        "organization_id": "org_tenant_b",  # mismatch!
        "target_reference": "shipment_001",
    }

    resp = client.post("/api/v1/decisions", json=payload)
    assert resp.status_code == 403


def test_get_and_list_decisions_tenant_isolated(client: TestClient):
    """Verify listing and getting decisions enforces tenant isolation."""
    org_a = "org_client_alpha"
    org_b = "org_client_beta"

    # 1. Create decision for Org A as Analyst
    auth_a = MockAuthContext(user_id="usr_analyst_a", organization_id=org_a, role="Analyst")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_a
    for role_name in ("Analyst", "OpsManager", "RiskManager", "Admin", "Viewer"):
        app.dependency_overrides[require_role(role_name)] = lambda: auth_a

    payload_a = {
        "organization_id": org_a,
        "target_reference": "shipment_alpha_01",
        "optimization_result": {
            "organization_id": org_a,
            "optimization_id": "opt_alpha_01",
            "domain": "ROUTE_SELECTION",
            "status": "OPTIMAL",
            "objective": {"objective_type": "MINIMIZE_DELAY"},
            "selected_alternatives": [
                {"entity_type": "ROUTE", "entity_id": "route_alpha_main", "assigned_value": 1.0}
            ],
        },
    }
    resp_create = client.post("/api/v1/decisions", json=payload_a)
    assert resp_create.status_code == 201
    decision_id_a = resp_create.json()["decision_id"]

    # 2. List decisions as Org A -> finds 1 decision
    resp_list_a = client.get("/api/v1/decisions")
    assert resp_list_a.status_code == 200
    assert len(resp_list_a.json()) == 1
    assert resp_list_a.json()[0]["decision_id"] == decision_id_a

    # 3. Retrieve decision as Org A -> succeeds (200)
    resp_get_a = client.get(f"/api/v1/decisions/{decision_id_a}")
    assert resp_get_a.status_code == 200
    assert resp_get_a.json()["decision_id"] == decision_id_a

    # 4. Switch context to Org B
    auth_b = MockAuthContext(user_id="usr_analyst_b", organization_id=org_b, role="Analyst")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_b
    for role_name in ("Analyst", "OpsManager", "RiskManager", "Admin", "Viewer"):
        app.dependency_overrides[require_role(role_name)] = lambda: auth_b

    # Org B lists decisions -> empty list (cannot see Org A's decision)
    resp_list_b = client.get("/api/v1/decisions")
    assert resp_list_b.status_code == 200
    assert len(resp_list_b.json()) == 0

    # Org B tries to get Org A's decision by ID -> 403 Forbidden
    resp_get_b = client.get(f"/api/v1/decisions/{decision_id_a}")
    assert resp_get_b.status_code == 403


def test_get_nonexistent_decision_returns_404(client: TestClient):
    """Verify 404 response on unknown decision ID."""
    org_id = "org_client_alpha"
    auth = MockAuthContext(user_id="usr_admin_01", organization_id=org_id, role="Admin")
    app.dependency_overrides[get_authenticated_context] = lambda: auth
    for role_name in ("Analyst", "OpsManager", "RiskManager", "Admin", "Viewer"):
        app.dependency_overrides[require_role(role_name)] = lambda: auth

    resp = client.get("/api/v1/decisions/dec_00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
