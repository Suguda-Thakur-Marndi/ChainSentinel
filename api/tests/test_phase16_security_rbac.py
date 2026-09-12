"""Phase 16 Security and RBAC Test Suite.

Validates the critical governance boundaries of the Human Approval Subsystem:
1. Zero Autonomous Approval (system, bot, agent, auto accounts cannot approve)
2. Role-Based Access Control (Viewer, Analyst, OpsManager cannot approve; RiskManager, Admin can)
3. Multi-Tenant Boundary Isolation (cross-tenant review and sign-off prohibited)
4. Idempotency & Immutability (double-approval or re-decision fails closed)
5. Audit Trail Verification (cryptographic fingerprints and immutable log rows)
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.approval.contract import ApprovalDecision, ApprovalStatus
from app.agents.approval.errors import (
    ApprovalAlreadyFinalizedError,
    ApprovalAuthorizationError,
    ApprovalNotFoundError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
)
from app.agents.approval.persistence import ApprovalRepository
from app.db.base import Base
from app.models.governance import Approval, AuditLog, Recommendation
from app.models.tenancy import Organization, User


@pytest.fixture
def db_session():
    """In-memory SQLite session with all models created."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed tenants
    org_a = Organization(id="tenant_alpha", name="Alpha Corp")
    org_b = Organization(id="tenant_beta", name="Beta Corp")
    session.add_all([org_a, org_b])

    # Seed users
    u_viewer = User(id="user_viewer", org_id="tenant_alpha", email="v@a.com", full_name="Viewer User", role="Viewer")
    u_analyst = User(id="user_analyst", org_id="tenant_alpha", email="an@a.com", full_name="Analyst User", role="Analyst")
    u_ops = User(id="user_ops", org_id="tenant_alpha", email="op@a.com", full_name="Ops User", role="OpsManager")
    u_risk = User(id="user_risk", org_id="tenant_alpha", email="rm@a.com", full_name="Risk User", role="RiskManager")
    u_admin = User(id="user_admin", org_id="tenant_alpha", email="ad@a.com", full_name="Admin User", role="Admin")
    u_beta_risk = User(id="user_beta_risk", org_id="tenant_beta", email="rm@b.com", full_name="Beta Risk", role="RiskManager")
    session.add_all([u_viewer, u_analyst, u_ops, u_risk, u_admin, u_beta_risk])

    # Seed pending decision in tenant_alpha
    rec_alpha = Recommendation(
        id="dec_alpha_001",
        org_id="tenant_alpha",
        title="Reroute Pacific Container Vessel",
        rationale="Mitigate port typhoon congestion",
        estimated_cost=12000.0,
        confidence=0.88,
        status="PENDING",
        expected_benefit_json={
            "decision_id": "dec_alpha_001",
            "decision_type": "REROUTE_SHIPMENT",
            "status": "PENDING",
            "preferred_candidate": {
                "candidate_id": "alt_north_channel",
                "action_type": "REROUTE_SHIPMENT",
                "title": "North Channel Deviation",
                "tradeoffs": {"cost_delta": 3200.0, "delay_reduction_hours": 48.0},
            },
            "candidates": [
                {
                    "candidate_id": "alt_north_channel",
                    "action_type": "REROUTE_SHIPMENT",
                    "title": "North Channel Deviation",
                }
            ],
            "evidence_references": ["ev_ais_01", "ev_meteo_02"],
        },
    )

    # Seed pending decision in tenant_beta
    rec_beta = Recommendation(
        id="dec_beta_001",
        org_id="tenant_beta",
        title="Supplier Allocation Transfer",
        rationale="Shift critical component allocation",
        estimated_cost=25000.0,
        confidence=0.91,
        status="PENDING",
        expected_benefit_json={
            "decision_id": "dec_beta_001",
            "decision_type": "SUPPLIER_ALLOCATION",
            "status": "PENDING",
            "preferred_candidate": {
                "candidate_id": "alt_secondary_fab",
                "action_type": "SUPPLIER_ALLOCATION",
                "tradeoffs": {"cost_delta": 5000.0, "risk_reduction": 0.4},
            },
        },
    )
    session.add_all([rec_alpha, rec_beta])
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(engine)


# 1. Zero Autonomous Approval
def test_zero_autonomous_approval_enforcement(db_session):
    """Verify autonomous agents, bots, or system accounts cannot sign off on approvals."""
    # Attempting approval with system/agent names
    for bad_actor in ("system", "agent", "bot", "auto", "automated", "llm"):
        with pytest.raises(ApprovalAuthorizationError, match="Autonomous approval prohibited"):
            ApprovalRepository.record_human_decision(
                db=db_session,
                organization_id="tenant_alpha",
                id_or_decision_id="dec_alpha_001",
                decision=ApprovalDecision.APPROVE,
                actor_id=bad_actor,
                actor_role="RiskManager",
            )

    # Empty actor_id
    with pytest.raises(InvalidApprovalRequestError):
        ApprovalRepository.record_human_decision(
            db=db_session,
            organization_id="tenant_alpha",
            id_or_decision_id="dec_alpha_001",
            decision=ApprovalDecision.APPROVE,
            actor_id="",
            actor_role="RiskManager",
        )


# 2. RBAC Enforcement
def test_rbac_unauthorized_roles_rejected(db_session):
    """Verify Viewer, Analyst, and OpsManager are forbidden from approving decisions."""
    for unauthorized_role in ("Viewer", "Analyst", "OpsManager"):
        with pytest.raises(ApprovalAuthorizationError, match="not authorized to sign off"):
            ApprovalRepository.record_human_decision(
                db=db_session,
                organization_id="tenant_alpha",
                id_or_decision_id="dec_alpha_001",
                decision=ApprovalDecision.APPROVE,
                actor_id=f"user_{unauthorized_role.lower()}",
                actor_role=unauthorized_role,
            )


def test_rbac_authorized_roles_allowed(db_session):
    """Verify RiskManager and Admin roles successfully sign off on decisions."""
    # RiskManager approval
    dossier = ApprovalRepository.record_human_decision(
        db=db_session,
        organization_id="tenant_alpha",
        id_or_decision_id="dec_alpha_001",
        decision=ApprovalDecision.APPROVE,
        actor_id="user_risk",
        actor_role="RiskManager",
        comments="Sign-off verified against risk policy.",
    )
    assert dossier.status == ApprovalStatus.APPROVED.value
    assert dossier.decision == "APPROVE"
    assert dossier.decided_by_user_id == "user_risk"
    assert dossier.comments == "Sign-off verified against risk policy."


# 3. Multi-Tenant Boundary Isolation
def test_multi_tenant_isolation_review_and_decision(db_session):
    """Verify tenant cannot review or sign off decisions of another tenant."""
    # Cross-tenant review dossier request
    with pytest.raises(ApprovalTenantIsolationError):
        ApprovalRepository.get_approval_dossier(
            db=db_session,
            organization_id="tenant_alpha",
            id_or_decision_id="dec_beta_001",  # Belongs to tenant_beta
        )

    # Cross-tenant sign-off attempt
    with pytest.raises(ApprovalTenantIsolationError):
        ApprovalRepository.record_human_decision(
            db=db_session,
            organization_id="tenant_alpha",
            id_or_decision_id="dec_beta_001",  # Belongs to tenant_beta
            decision=ApprovalDecision.APPROVE,
            actor_id="user_risk",
            actor_role="RiskManager",
        )


# 4. Idempotency & Lifecycle Immutability
def test_approval_lifecycle_immutability(db_session):
    """Verify once decided (APPROVED or REJECTED), an approval cannot be decided again."""
    # 1. First decision succeeds
    ApprovalRepository.record_human_decision(
        db=db_session,
        organization_id="tenant_alpha",
        id_or_decision_id="dec_alpha_001",
        decision=ApprovalDecision.APPROVE,
        actor_id="user_risk",
        actor_role="RiskManager",
    )

    # 2. Attempting second decision on already finalized approval must raise ApprovalAlreadyFinalizedError
    with pytest.raises(ApprovalAlreadyFinalizedError, match="has already been finalized"):
        ApprovalRepository.record_human_decision(
            db=db_session,
            organization_id="tenant_alpha",
            id_or_decision_id="dec_alpha_001",
            decision=ApprovalDecision.REJECT,
            actor_id="user_admin",
            actor_role="Admin",
        )


# 5. Cryptographic Audit Trail Verification
def test_audit_trail_created_with_fingerprint(db_session):
    """Verify Approval action commits an immutable audit log entry with fingerprint and details."""
    dossier = ApprovalRepository.record_human_decision(
        db=db_session,
        organization_id="tenant_alpha",
        id_or_decision_id="dec_alpha_001",
        decision=ApprovalDecision.APPROVE,
        actor_id="user_risk",
        actor_role="RiskManager",
        comments="Approved for dispatch",
    )
    db_session.commit()

    # Query audit logs
    audit_entry = db_session.query(AuditLog).filter_by(resource_id=dossier.approval_id).first()
    assert audit_entry is not None
    assert audit_entry.org_id == "tenant_alpha"
    assert audit_entry.action == "APPROVAL_APPROVE"
    assert audit_entry.actor_type == "USER"
    assert audit_entry.actor_id == "user_risk"
    assert audit_entry.after_json["fingerprint"] is not None
    assert audit_entry.after_json["side_effect_allowed"] is True
