"""Phase 17 Test Suite: Mandatory Human Approval and Approval Binding Enforcement.

Validates:
- Rejection of missing approvals
- Rejection of non-APPROVED approvals (PENDING, REJECTED)
- Rejection of expired approvals and stale decisions (> 24h)
- Rejection of cross-tenant approvals
- Rejection of approvals bound to a different decision or candidate
- Rejection of approvals signed by unauthorized roles (Viewer, Analyst)
- Cryptographic fingerprint verification between approval and action command
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.agents.action.agent import ActionAgent
from app.agents.action.contract import (
    ActionActor,
    ActionCommand,
    ActionType,
    TargetEntityType,
)
from app.agents.action.errors import (
    ActionApprovalInvalidError,
    ActionApprovalMismatchError,
    ActionApprovalMissingError,
    ActionAuthorizationError,
    ActionStaleDecisionError,
    ActionTenantIsolationError,
)
from app.agents.approval.contract import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalResult,
    ApprovalStatus,
)


def _make_sample_command(
    org_id: str = "tenant_alpha",
    dec_id: str = "dec_001",
    appr_id: str = "appr_001",
    cand_id: str = "cand_reroute_01",
) -> ActionCommand:
    return ActionCommand(
        decision_id=dec_id,
        approval_id=appr_id,
        candidate_id=cand_id,
        organization_id=org_id,
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_123",
        parameters={"new_route_id": "route_pacific_alt"},
        idempotency_key=f"idemp_{appr_id}",
        trace_id="trace_appr_test",
        actor=ActionActor(actor_id="user_exec", organization_id=org_id, role="RiskManager"),
    )


def test_missing_approval_raises_error():
    """Verify ActionApprovalMissingError when approval is None."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    with pytest.raises(ActionApprovalMissingError) as exc_info:
        agent.execute(command=cmd, approval=None)
    assert "strictly requires human approval" in str(exc_info.value)


def test_pending_approval_rejected():
    """Verify ActionApprovalInvalidError when approval status is PENDING."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.PENDING.value,
        fingerprint="a" * 64,
        requires_human_approval=True,
        side_effect_allowed=False,
    )
    with pytest.raises(ActionApprovalInvalidError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "require an APPROVED human sign-off" in str(exc_info.value)


def test_rejected_approval_rejected():
    """Verify ActionApprovalInvalidError when approval status is REJECTED."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.REJECTED.value,
        actor_id="user_approver_01",
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=False,
    )
    with pytest.raises(ActionApprovalInvalidError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "require an APPROVED human sign-off" in str(exc_info.value)


def test_expired_approval_rejected():
    """Verify ActionStaleDecisionError when approval expiration timestamp is in the past."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    expired_at = datetime.now(timezone.utc) - timedelta(hours=2)
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=datetime.now(timezone.utc) - timedelta(hours=3),
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )
    cmd.expiration_timestamp = expired_at

    with pytest.raises(ActionStaleDecisionError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "expired" in str(exc_info.value)


def test_stale_approval_age_limit_exceeded():
    """Verify ActionStaleDecisionError when approval is older than max_freshness_seconds."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    old_decision = datetime.now(timezone.utc) - timedelta(days=2)  # 48 hours ago
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=old_decision,
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )

    with pytest.raises(ActionStaleDecisionError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "exceeding freshness limit" in str(exc_info.value)


def test_cross_tenant_approval_rejected():
    """Verify ActionTenantIsolationError when approval belongs to a different tenant."""
    agent = ActionAgent()
    cmd = _make_sample_command(org_id="tenant_alpha")
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id="tenant_beta",  # Different tenant!
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=datetime.now(timezone.utc),
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )

    with pytest.raises(ActionTenantIsolationError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "Cross-tenant approval" in str(exc_info.value)


def test_decision_mismatch_rejected():
    """Verify ActionApprovalMismatchError when approval was granted for a different decision ID."""
    agent = ActionAgent()
    cmd = _make_sample_command(dec_id="dec_intended_001")
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id="dec_other_999",  # Different decision!
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=datetime.now(timezone.utc),
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )

    with pytest.raises(ActionApprovalMismatchError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "does not match command decision ID" in str(exc_info.value)


def test_candidate_mismatch_rejected():
    """Verify ActionApprovalMismatchError when approval was granted for candidate A but command targets candidate B."""
    agent = ActionAgent()
    cmd = _make_sample_command(cand_id="cand_air_freight")
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id="cand_ocean_reroute",  # Mismatched candidate!
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=datetime.now(timezone.utc),
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )

    with pytest.raises(ActionApprovalMismatchError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "does not match command candidate ID" in str(exc_info.value)


def test_unauthorized_approver_role_rejected():
    """Verify ActionAuthorizationError when approval was signed by an unauthorized role (e.g. Viewer)."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="Viewer",  # Unauthorized role!
        decided_at=datetime.now(timezone.utc),
        fingerprint="a" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )

    with pytest.raises(ActionAuthorizationError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "not authorized to approve operational execution" in str(exc_info.value)


def test_tampered_fingerprint_rejected():
    """Verify ActionApprovalMismatchError when cryptographic fingerprint fails comparison."""
    agent = ActionAgent()
    cmd = _make_sample_command()
    cmd.approval_fingerprint = "f" * 64  # Claimed fingerprint
    approval = ApprovalResult(
        approval_id=cmd.approval_id,
        organization_id=cmd.organization_id,
        decision_id=cmd.decision_id,
        candidate_id=cmd.candidate_id or "cand_01",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=datetime.now(timezone.utc),
        fingerprint="e" * 64,  # Actual authentic fingerprint
        requires_human_approval=False,
        side_effect_allowed=True,
    )

    with pytest.raises(ActionApprovalMismatchError) as exc_info:
        agent.execute(command=cmd, approval=approval)
    assert "Approval cryptographic fingerprint mismatch" in str(exc_info.value)
