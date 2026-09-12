"""Tests for Phase 18 Persistence, Database Invariants, Idempotency, and REST API Endpoints."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_authenticated_context, require_role
from app.db.base import Base
import app.models  # All 34 models
from app.db.unit_of_work import UnitOfWork, get_uow
from app.main import app
from app.models.governance import Action, AuditLog, VerificationResult
from app.models.logistics import Shipment
from app.models.tenancy import Organization
from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.verification.contract import (
    IntendedOutcome,
    ObservedOutcome,
    VerificationResultPayload,
    VerificationStatus,
    compute_verification_fingerprint,
)
from app.agents.verification.persistence import VerificationPersistenceManager


class MockAuthContext:
    def __init__(self, user_id: str, organization_id: str, role: str):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.roles = [role.lower()]
        self.request_id = "req-test-p18"


@pytest.fixture(autouse=True)
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    # Seed tenant
    org = Organization(id="tenant_p18", name="P18 Verification Corp")
    session.add(org)

    # Seed shipment
    ship = Shipment(
        id="ship_api_test",
        org_id="tenant_p18",
        tracking_number="TRK-P18",
        route_id="ROUTE_NEW_NORTH",
        status="IN_TRANSIT",
    )
    session.add(ship)

    # Seed executed action
    act = Action(
        id="act_api_test",
        org_id="tenant_p18",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_api_test",
        status="EXECUTED",
        executed_at=datetime.now(timezone.utc),
    )
    session.add(act)
    session.commit()
    return session


class TestPersistenceAndAPI:
    """Verify idempotency, 34-table DB invariant, and REST API behavior."""

    def test_database_table_count_invariant(self):
        """Database table count must be strictly 34 with zero modifications."""
        assert len(Base.metadata.tables) == 34
        assert "verification_results" in Base.metadata.tables

    def test_persistence_idempotency_replay(self, test_db):
        """Identical fingerprint returns existing record without duplicate DB write."""
        mgr = VerificationPersistenceManager(test_db)
        intended = IntendedOutcome(
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_api_test",
            expected_attributes={"route_id": "ROUTE_NEW_NORTH"},
        )
        observed = ObservedOutcome(
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_api_test",
            observed_attributes={"route_id": "ROUTE_NEW_NORTH"},
            evidence_count=1,
        )
        fp = compute_verification_fingerprint(
            organization_id="tenant_p18",
            action_id="act_api_test",
            intended_outcome=intended.model_dump(),
            observed_outcome=observed.model_dump(exclude={"evidence_items"}),
            status="VERIFIED",
        )

        payload = VerificationResultPayload(
            verification_id="verif_001",
            action_id="act_api_test",
            organization_id="tenant_p18",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_api_test",
            status=VerificationStatus.VERIFIED,
            verified=True,
            intended_outcome=intended,
            observed_outcome=observed,
            observation_window_start=datetime.now(timezone.utc),
            observation_window_end=datetime.now(timezone.utc),
            fingerprint=fp,
            observation_summary="Route confirmed.",
        )

        # First persist: writes new record
        rec1, is_new1 = mgr.persist(payload)
        assert is_new1 is True

        # Second persist with same fingerprint: returns cached record
        rec2, is_new2 = mgr.persist(payload)
        assert is_new2 is False
        assert rec1.id == rec2.id

        # Total verification_results count must be exactly 1
        count = test_db.execute(select(VerificationResult)).scalars().all()
        assert len(count) == 1

    def test_api_verify_endpoint_success(self, test_db):
        """POST /api/v1/verification-results/verify succeeds with RiskManager role."""
        uow = UnitOfWork(session=test_db)
        app.dependency_overrides[get_uow] = lambda: uow
        app.dependency_overrides[get_authenticated_context] = lambda: MockAuthContext(
            user_id="user_rm", organization_id="tenant_p18", role="RiskManager"
        )
        app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: MockAuthContext(
            user_id="user_rm", organization_id="tenant_p18", role="RiskManager"
        )

        client = TestClient(app)
        body = {
            "action_id": "act_api_test",
            "organization_id": "tenant_p18",
            "action_type": "SHIPMENT_REROUTE",
            "target_entity_type": "SHIPMENT",
            "target_entity_id": "ship_api_test",
            "action_parameters": {"new_route_id": "ROUTE_NEW_NORTH"},
        }

        resp = client.post("/api/v1/verification-results/verify", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_id"] == "act_api_test"
        assert data["status"] == "VERIFIED"
        assert data["verified"] is True

    def test_api_verify_endpoint_cross_tenant_forbidden(self, test_db):
        """Cross-tenant verification payload is rejected with 403 Forbidden."""
        uow = UnitOfWork(session=test_db)
        app.dependency_overrides[get_uow] = lambda: uow
        app.dependency_overrides[get_authenticated_context] = lambda: MockAuthContext(
            user_id="user_rm", organization_id="tenant_p18", role="RiskManager"
        )
        app.dependency_overrides[require_role("RiskManager", "Admin")] = lambda: MockAuthContext(
            user_id="user_rm", organization_id="tenant_p18", role="RiskManager"
        )

        client = TestClient(app)
        body = {
            "action_id": "act_api_test",
            "organization_id": "different_org_id",  # Mismatch!
            "action_type": "SHIPMENT_REROUTE",
            "target_entity_type": "SHIPMENT",
            "target_entity_id": "ship_api_test",
        }

        resp = client.post("/api/v1/verification-results/verify", json=body)
        assert resp.status_code == 403
        assert "Cross-tenant verification request" in resp.json()["detail"]
