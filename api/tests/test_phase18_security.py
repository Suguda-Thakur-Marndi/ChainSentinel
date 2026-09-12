"""Tests for Phase 18 adversarial security, tenant boundaries, approval bindings, and injection protections."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.verification.contract import (
    ObservedEvidenceItem,
    VerificationCommand,
)
from app.agents.verification.errors import (
    VerificationActionNotExecutedError,
    VerificationActionNotFoundError,
    VerificationApprovalMismatchError,
    VerificationSecurityViolationError,
    VerificationTenantIsolationError,
)
from app.agents.verification.policy import VerificationPolicy
from app.db.base import Base
import app.models  # Load 34 models
from app.models.governance import Action, Approval, Recommendation
from app.models.logistics import Shipment
from app.models.tenancy import Organization


@pytest.fixture
def security_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    # Seed tenants
    org_1 = Organization(id="tenant_1", name="Tenant One")
    org_2 = Organization(id="tenant_2", name="Tenant Two")
    session.add_all([org_1, org_2])

    # Recommendations
    rec_1 = Recommendation(id="rec_1", org_id="tenant_1", title="Reroute Corridor")
    rec_2 = Recommendation(id="rec_2", org_id="tenant_2", title="Cross Tenant Rec")
    session.add_all([rec_1, rec_2])

    # Approvals
    appr_1 = Approval(id="appr_1", recommendation_id="rec_1", decision="APPROVE")
    appr_cross = Approval(id="appr_cross", recommendation_id="rec_2", decision="APPROVE")
    session.add_all([appr_1, appr_cross])

    # Executed Action for Tenant 1
    act_executed = Action(
        id="act_executed_1",
        org_id="tenant_1",
        recommendation_id="rec_1",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_sec_1",
        status="EXECUTED",
        executed_at=datetime.now(timezone.utc),
    )

    # Draft / Pending Action (not executed)
    act_pending = Action(
        id="act_pending_1",
        org_id="tenant_1",
        recommendation_id="rec_1",
        action_type="SHIPMENT_REROUTE",
        status="PENDING",
    )

    # Action for Tenant 2
    act_tenant_2 = Action(
        id="act_tenant_2",
        org_id="tenant_2",
        recommendation_id="rec_2",
        action_type="SHIPMENT_REROUTE",
        status="EXECUTED",
        executed_at=datetime.now(timezone.utc),
    )

    # Shipments
    ship_1 = Shipment(id="ship_sec_1", org_id="tenant_1", tracking_number="TRK-S1", route_id="R-NEW")
    session.add_all([act_executed, act_pending, act_tenant_2, ship_1])
    session.commit()
    return session


class TestAdversarialSecurity:
    """Validate zero-trust security and tenant containment."""

    def test_cross_tenant_action_verification_rejected(self, security_db):
        """Tenant 1 cannot verify Tenant 2's action."""
        policy = VerificationPolicy(security_db)
        cmd = VerificationCommand(
            action_id="act_tenant_2",
            organization_id="tenant_1",  # Requesting as tenant 1
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_sec_1",
        )

        with pytest.raises(VerificationTenantIsolationError, match="belongs to org 'tenant_2'"):
            policy.evaluate(cmd)

    def test_cross_tenant_approval_binding_rejected(self, security_db):
        """Action for Tenant 1 bound to Approval from Tenant 2 must be rejected."""
        policy = VerificationPolicy(security_db)
        cmd = VerificationCommand(
            action_id="act_executed_1",
            approval_id="appr_cross",  # Belongs to Tenant 2
            organization_id="tenant_1",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_sec_1",
        )

        with pytest.raises(VerificationTenantIsolationError, match="belongs to org 'tenant_2'"):
            policy.evaluate(cmd)

    def test_unexecuted_action_verification_rejected(self, security_db):
        """Attempting to verify an action that is PENDING or DRAFT must fail."""
        policy = VerificationPolicy(security_db)
        cmd = VerificationCommand(
            action_id="act_pending_1",
            organization_id="tenant_1",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_sec_1",
        )

        with pytest.raises(VerificationActionNotExecutedError, match="requires an executed action"):
            policy.evaluate(cmd)

    def test_nonexistent_action_raises_not_found(self, security_db):
        """Attempting to verify a non-existent action must fail cleanly."""
        policy = VerificationPolicy(security_db)
        cmd = VerificationCommand(
            action_id="act_ghost_does_not_exist",
            organization_id="tenant_1",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_sec_1",
        )

        with pytest.raises(VerificationActionNotFoundError, match="not found in authoritative storage"):
            policy.evaluate(cmd)
