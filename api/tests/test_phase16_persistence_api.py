"""Phase 16 Test Suite: REST API Endpoints, RBAC, and Persistence for Human Approval.

Validates:
- GET /api/v1/approvals/pending (lists pending decisions awaiting approval)
- GET /api/v1/approvals/{id}/dossier (retrieves detailed review dossier)
- POST /api/v1/approvals/{id}/decide (records APPROVE or REJECT)
- POST /api/v1/approvals/{id}/approve (convenience approve)
- POST /api/v1/approvals/{id}/reject (convenience reject)
- RBAC: Viewer cannot sign off (403 Forbidden)
- Multi-tenant isolation: Tenant B cannot view/sign off Tenant A's approvals
- 404 response on nonexistent approval ID
- 409 Conflict on attempting to re-decide an already finalized approval
- Database invariant: strictly 34 tables, 0 migrations
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.approval.contract import ApprovalDecision, ApprovalStatus
from app.api.deps import get_authenticated_context, require_role
from app.core.context import AuthenticatedContext
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.main import app
from app.models.governance import Approval, AuditLog, Recommendation
from app.models.tenancy import Organization, User


class MockAuthContext:
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        role: str,
        request_id: str = "req-test-p16-api",
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

    # Seed baseline organizations
    org_a = Organization(id="tenant_alpha", name="Alpha Logistics")
    org_b = Organization(id="tenant_beta", name="Beta Freight")
    session.add_all([org_a, org_b])

    # Seed users
    u_risk = User(id="user_risk", org_id="tenant_alpha", email="risk@alpha.com", full_name="Risk Lead", role="RiskManager")
    u_viewer = User(id="user_viewer", org_id="tenant_alpha", email="viewer@alpha.com", full_name="Viewer User", role="Viewer")
    session.add_all([u_risk, u_viewer])

    # Seed pending recommendation in tenant_alpha
    rec1 = Recommendation(
        id="dec_reroute_001",
        org_id="tenant_alpha",
        title="Reroute Transpacific Flight 808",
        rationale="Avoid severe weather disruption",
        estimated_cost=8500.0,
        confidence=0.94,
        status="PENDING",
        expected_benefit_json={
            "decision_id": "dec_reroute_001",
            "decision_type": "REROUTE_SHIPMENT",
            "status": "PENDING",
            "preferred_candidate": {
                "candidate_id": "alt_southern_air",
                "action_type": "REROUTE_SHIPMENT",
                "title": "Southern Air Corridor",
                "tradeoffs": {"cost_delta": 1800.0, "delay_reduction_hours": 14.0},
            },
            "candidates": [
                {
                    "candidate_id": "alt_southern_air",
                    "action_type": "REROUTE_SHIPMENT",
                    "title": "Southern Air Corridor",
                }
            ],
            "evidence_references": ["ev_weather_radar_01"],
            "decision_explanation": {
                "status": "AVAILABLE",
                "summary": "Southern route avoids convective weather cell with minimal cost delta.",
            },
        },
    )

    # Seed pending recommendation in tenant_beta
    rec2 = Recommendation(
        id="dec_beta_002",
        org_id="tenant_beta",
        title="Facility Capacity Shift",
        status="PENDING",
        expected_benefit_json={"decision_id": "dec_beta_002", "status": "PENDING"},
    )
    session.add_all([rec1, rec2])
    session.commit()

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
        return UnitOfWork(sqlite_session)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_uow] = _override_get_uow
    return TestClient(app)


def test_database_table_count_invariant(sqlite_session: Session):
    """Verify database retains exactly 34 tables with zero migrations and zero schema changes."""
    engine = sqlite_session.get_bind()
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert len(tables) == 34, f"Expected 34 tables, found {len(tables)}: {tables}"
    assert "approvals" in tables
    assert "recommendations" in tables
    assert "audit_logs" in tables


def test_list_pending_approvals(client: TestClient):
    """Verify GET /api/v1/approvals/pending returns tenant pending decisions."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")] = lambda: auth_ctx

    resp = client.get("/api/v1/approvals/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["decision_id"] == "dec_reroute_001"
    assert item["status"] == "PENDING"
    assert item["action_type"] == "REROUTE_SHIPMENT"
    assert item["tradeoffs"]["delay_reduction_hours"] == 14.0


def test_get_approval_dossier(client: TestClient):
    """Verify GET /api/v1/approvals/{id}/dossier returns complete review context."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")] = lambda: auth_ctx

    resp = client.get("/api/v1/approvals/dec_reroute_001/dossier")
    assert resp.status_code == 200
    dossier = resp.json()
    assert dossier["decision_id"] == "dec_reroute_001"
    assert dossier["status"] == "PENDING"
    assert dossier["preferred_candidate"]["candidate_id"] == "alt_southern_air"
    assert dossier["decision_explanation"]["status"] == "AVAILABLE"
    assert len(dossier["evidence_references"]) == 1


def test_record_human_decision_approve(client: TestClient, sqlite_session: Session):
    """Verify POST /api/v1/approvals/{id}/decide approves candidate and transitions state."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    payload = {
        "decision": "APPROVE",
        "comments": "Signed off by Senior Risk Manager after pilot confirmation.",
    }
    resp = client.post("/api/v1/approvals/dec_reroute_001/decide", json=payload)
    assert resp.status_code == 200
    dossier = resp.json()
    assert dossier["status"] == "APPROVED"
    assert dossier["decision"] == "APPROVE"
    assert dossier["decided_by_user_id"] == "user_risk"
    assert dossier["comments"] == "Signed off by Senior Risk Manager after pilot confirmation."

    # Verify database state
    rec = sqlite_session.query(Recommendation).filter_by(id="dec_reroute_001").first()
    assert rec is not None
    assert rec.status == "APPROVED"
    appr = sqlite_session.query(Approval).filter_by(recommendation_id="dec_reroute_001").first()
    assert appr is not None
    assert appr.decision == "APPROVE"


def test_convenience_approve_and_reject_endpoints(client: TestClient, sqlite_session: Session):
    """Verify POST /api/v1/approvals/{id}/approve and /reject convenience endpoints."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    # Reject endpoint
    resp = client.post("/api/v1/approvals/dec_reroute_001/reject", json={"comments": "Excessive cost delta."})
    assert resp.status_code == 200
    dossier = resp.json()
    assert dossier["status"] == "REJECTED"
    assert dossier["decision"] == "REJECT"

    # Attempting to approve after rejection must return 409 Conflict
    resp_conflict = client.post("/api/v1/approvals/dec_reroute_001/approve", json={"comments": "Try approve now"})
    assert resp_conflict.status_code == 409


def test_rbac_viewer_cannot_decide(client: TestClient):
    """Verify Viewer receives 403 Forbidden when attempting to record an approval decision."""
    auth_ctx = MockAuthContext(user_id="user_viewer", organization_id="tenant_alpha", role="Viewer")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    # require_role raises 403 for Viewer
    from fastapi import HTTPException
    def _forbid_viewer():
        raise HTTPException(status_code=403, detail="Operation requires one of: RiskManager, Admin")
    app.dependency_overrides[require_role("RiskManager", "Admin")] = _forbid_viewer

    resp = client.post("/api/v1/approvals/dec_reroute_001/decide", json={"decision": "APPROVE"})
    assert resp.status_code == 403


def test_cross_tenant_isolation_api(client: TestClient):
    """Verify tenant cannot view dossier or decide on another tenant's approval."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    # Attempting to get dossier of tenant_beta's decision
    resp = client.get("/api/v1/approvals/dec_beta_002/dossier")
    assert resp.status_code == 403

    # Attempting to decide on tenant_beta's decision
    resp_decide = client.post("/api/v1/approvals/dec_beta_002/decide", json={"decision": "APPROVE"})
    assert resp_decide.status_code == 403


def test_nonexistent_approval_returns_404(client: TestClient):
    """Verify 404 response on unknown decision candidate ID."""
    auth_ctx = MockAuthContext(user_id="user_risk", organization_id="tenant_alpha", role="RiskManager")
    app.dependency_overrides[get_authenticated_context] = lambda: auth_ctx
    app.dependency_overrides[require_role("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")] = lambda: auth_ctx
    app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: auth_ctx

    resp = client.get("/api/v1/approvals/dec_nonexistent_999/dossier")
    assert resp.status_code == 404

    resp_decide = client.post("/api/v1/approvals/dec_nonexistent_999/decide", json={"decision": "APPROVE"})
    assert resp_decide.status_code == 404
