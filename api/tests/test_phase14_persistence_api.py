"""Phase 14 Test Suite: REST API endpoints, RBAC, and Persistence.

Validates:
- POST /api/v1/optimization-runs (creates run, saves to optimization_runs table, returns 201)
- GET /api/v1/optimization-runs (lists tenant's runs, returns 200)
- GET /api/v1/optimization-runs/{id} (retrieves run, returns 200)
- RBAC: Viewer cannot trigger optimization (403 Forbidden)
- Multi-tenant isolation: Tenant B cannot view Tenant A's optimization run (403 Forbidden)
- 404 response on nonexistent optimization ID
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_authenticated_context, require_role
from app.core.context import AuthenticatedContext
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.main import app
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationDomain,
    OptimizationObjectiveType,
)


class MockAuthContext:
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        role: str,
        request_id: str = "req-test-p14-api",
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.request_id = request_id


@pytest.fixture(scope="module", autouse=True)
def mount_optimization_routes():
    """Mount Optimization API routes dynamically for this module and cleanly restore afterwards."""
    from app.api.v1.endpoints.optimization import router as opt_router
    orig_routes = list(app.router.routes)
    app.include_router(opt_router, prefix="/api/v1", tags=["Optimization"])
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
def db_session():
    """Isolated in-memory database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(db_session: Session):
    """FastAPI test client with DB and default OpsManager context."""
    app.dependency_overrides[get_db] = lambda: db_session

    class TestUOW(UnitOfWork):
        def __init__(self):
            self.session = db_session

        def commit(self):
            self.session.commit()

        def rollback(self):
            self.session.rollback()

    app.dependency_overrides[get_uow] = lambda: TestUOW()

    ctx = MockAuthContext("user-1", "org-tenant-a", "OpsManager")
    app.dependency_overrides[get_authenticated_context] = lambda: ctx

    return TestClient(app)


def test_api_trigger_optimization_run(client: TestClient):
    """Verify POST /api/v1/optimization-runs creates run and returns 201."""
    payload = {
        "organization_id": "org-tenant-a",
        "domain": "SHIPMENT_REROUTE",
        "objective_type": "MINIMIZE_DELAY",
        "target_entity_ids": ["shipment-001"],
        "candidate_alternatives": [
            {
                "alternative_id": "alt-route-1",
                "entity_type": "ROUTE",
                "entity_id": "route-fast",
                "is_available": True,
                "transit_time_hours": 14.0,
                "cost": 1200.0,
                "capacity": 20.0,
                "properties": {},
            },
            {
                "alternative_id": "alt-route-2",
                "entity_type": "ROUTE",
                "entity_id": "route-slow",
                "is_available": True,
                "transit_time_hours": 36.0,
                "cost": 800.0,
                "capacity": 20.0,
                "properties": {},
            },
        ],
        "parameters": {},
    }

    resp = client.post("/api/v1/optimization-runs", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "OPTIMAL"
    assert data["objective_value"] == 14.0
    assert len(data["selected_alternatives"]) == 1
    assert data["selected_alternatives"][0]["entity_id"] == "route-fast"
    opt_id = data["optimization_id"]

    # Verify GET by ID returns the result
    get_resp = client.get(f"/api/v1/optimization-runs/{opt_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["optimization_id"] == opt_id

    # Verify GET list returns the run
    list_resp = client.get("/api/v1/optimization-runs")
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert any(r["optimization_id"] == opt_id for r in runs)


def test_api_viewer_role_forbidden_to_trigger(client: TestClient):
    """Verify Viewer role is rejected with 403 Forbidden when attempting to trigger optimization."""
    ctx = MockAuthContext("user-viewer", "org-tenant-a", "Viewer")
    app.dependency_overrides[get_authenticated_context] = lambda: ctx

    payload = {
        "organization_id": "org-tenant-a",
        "domain": "SHIPMENT_REROUTE",
        "objective_type": "MINIMIZE_DELAY",
        "target_entity_ids": ["shipment-001"],
        "candidate_alternatives": [],
        "parameters": {},
    }
    resp = client.post("/api/v1/optimization-runs", json=payload)
    assert resp.status_code == 403


def test_api_cross_tenant_access_forbidden(client: TestClient):
    """Verify Tenant B cannot access an optimization run created by Tenant A."""
    # 1. Create run as Tenant A
    payload = {
        "organization_id": "org-tenant-a",
        "domain": "SHIPMENT_REROUTE",
        "objective_type": "MINIMIZE_DELAY",
        "target_entity_ids": ["ship-01"],
        "candidate_alternatives": [
            {
                "alternative_id": "alt-1",
                "entity_type": "ROUTE",
                "entity_id": "r1",
                "is_available": True,
                "transit_time_hours": 10.0,
                "properties": {},
            }
        ],
        "parameters": {},
    }
    resp = client.post("/api/v1/optimization-runs", json=payload)
    assert resp.status_code == 201
    opt_id = resp.json()["optimization_id"]

    # 2. Switch context to Tenant B
    ctx_b = MockAuthContext("user-tenant-b", "org-tenant-b", "OpsManager")
    app.dependency_overrides[get_authenticated_context] = lambda: ctx_b

    # Tenant B tries to access Tenant A's run
    get_resp = client.get(f"/api/v1/optimization-runs/{opt_id}")
    assert get_resp.status_code == 403
    assert "belongs to another tenant" in get_resp.json()["detail"]


def test_api_nonexistent_run_returns_404(client: TestClient):
    """Verify querying nonexistent optimization run returns 404."""
    resp = client.get("/api/v1/optimization-runs/prob_nonexistent_12345")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]
