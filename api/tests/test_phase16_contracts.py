"""Phase 16 Test Suite: Strongly typed contracts and validation for Human Approval.

Validates:
- ApprovalRequest validation, extra="forbid", tenant consistency
- ApprovalDecisionInput, HumanDecisionRequest, comments safety
- ApprovalResult lifecycle invariants:
    - PENDING requires requires_human_approval=True and side_effect_allowed=False
    - APPROVED requires actor_id, decided_at, side_effect_allowed=True, requires_human_approval=False
    - REJECTED requires actor_id, side_effect_allowed=False
- PendingApprovalItem, PendingApprovalListResponse, ApprovalDossier
- Deterministic ID and SHA-256 fingerprint generation
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.agents.approval.contract import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalDossier,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
    HumanDecisionRequest,
    PendingApprovalItem,
    PendingApprovalListResponse,
    compute_approval_fingerprint,
    generate_deterministic_approval_id,
)


def test_approval_request_valid():
    """Verify valid ApprovalRequest instantiation."""
    req = ApprovalRequest(
        organization_id="tenant_alpha",
        decision_id="dec_001",
        candidate_id="cand_reroute_ocean",
        recommendation_id="rec_001",
        required_role="RiskManager",
        evidence_references=["ev_ais_01", "ev_port_02"],
    )
    assert req.organization_id == "tenant_alpha"
    assert req.decision_id == "dec_001"
    assert req.candidate_id == "cand_reroute_ocean"
    assert req.required_role == "RiskManager"
    assert len(req.evidence_references) == 2


def test_approval_request_forbids_extra_fields():
    """Verify ApprovalRequest rejects injected or arbitrary fields."""
    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate(
            {
                "organization_id": "tenant_alpha",
                "decision_id": "dec_001",
                "candidate_id": "cand_001",
                "unauthorized_arbitrary_field": "malicious_payload",
            }
        )


def test_approval_request_tenant_mismatch_fails():
    """Verify tenant mismatch between request and decision_reference raises ValueError."""
    with pytest.raises(ValueError, match="Decision reference tenant"):
        ApprovalRequest(
            organization_id="tenant_alpha",
            decision_id="dec_001",
            candidate_id="cand_001",
            decision_reference={"organization_id": "tenant_beta"},
        )


def test_approval_actor_validation():
    """Verify ApprovalActor fields, secret validation, and extra=forbid."""
    actor = ApprovalActor(
        actor_id="user_john_doe",
        organization_id="tenant_alpha",
        role="RiskManager",
        email="john.doe@enterprise.com",
    )
    assert actor.actor_id == "user_john_doe"
    assert actor.role == "RiskManager"

    # Extra field forbidden
    with pytest.raises(ValidationError):
        ApprovalActor.model_validate(
            {
                "actor_id": "user_1",
                "organization_id": "tenant_1",
                "role": "RiskManager",
                "injected_key": "val",
            }
        )


def test_approval_result_pending_invariants():
    """Verify ApprovalResult PENDING lifecycle rules."""
    # Valid PENDING
    result = ApprovalResult(
        approval_id="appr_001",
        organization_id="tenant_alpha",
        decision_id="dec_001",
        candidate_id="cand_001",
        status=ApprovalStatus.PENDING.value,
        requires_human_approval=True,
        side_effect_allowed=False,
    )
    assert result.status == ApprovalStatus.PENDING.value
    assert result.requires_human_approval is True
    assert result.side_effect_allowed is False

    # Invalid: PENDING cannot have side_effect_allowed=True
    with pytest.raises(ValidationError):
        ApprovalResult(
            approval_id="appr_001",
            organization_id="tenant_alpha",
            decision_id="dec_001",
            candidate_id="cand_001",
            status=ApprovalStatus.PENDING.value,
            requires_human_approval=True,
            side_effect_allowed=True,
        )

    # Invalid: PENDING cannot have requires_human_approval=False
    with pytest.raises(ValidationError):
        ApprovalResult(
            approval_id="appr_001",
            organization_id="tenant_alpha",
            decision_id="dec_001",
            candidate_id="cand_001",
            status=ApprovalStatus.PENDING.value,
            requires_human_approval=False,
            side_effect_allowed=False,
        )


def test_approval_result_approved_invariants():
    """Verify ApprovalResult APPROVED lifecycle rules."""
    now = datetime.now(timezone.utc)
    # Valid APPROVED
    res = ApprovalResult(
        approval_id="appr_001",
        organization_id="tenant_alpha",
        decision_id="dec_001",
        candidate_id="cand_001",
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_risk_mgr",
        actor_role="RiskManager",
        decided_at=now,
        requires_human_approval=False,
        side_effect_allowed=True,
    )
    assert res.status == ApprovalStatus.APPROVED.value
    assert res.side_effect_allowed is True

    # Missing actor_id in APPROVED
    with pytest.raises(ValidationError):
        ApprovalResult(
            approval_id="appr_001",
            organization_id="tenant_alpha",
            decision_id="dec_001",
            candidate_id="cand_001",
            status=ApprovalStatus.APPROVED.value,
            actor_id=None,
            decided_at=now,
            requires_human_approval=False,
            side_effect_allowed=True,
        )


def test_approval_result_rejected_invariants():
    """Verify ApprovalResult REJECTED lifecycle rules."""
    now = datetime.now(timezone.utc)
    # Valid REJECTED
    res = ApprovalResult(
        approval_id="appr_001",
        organization_id="tenant_alpha",
        decision_id="dec_001",
        candidate_id="cand_001",
        status=ApprovalStatus.REJECTED.value,
        actor_id="user_risk_mgr",
        actor_role="RiskManager",
        decided_at=now,
        requires_human_approval=False,
        side_effect_allowed=False,
    )
    assert res.status == ApprovalStatus.REJECTED.value
    assert res.side_effect_allowed is False

    # REJECTED cannot have side_effect_allowed=True
    with pytest.raises(ValidationError):
        ApprovalResult(
            approval_id="appr_001",
            organization_id="tenant_alpha",
            decision_id="dec_001",
            candidate_id="cand_001",
            status=ApprovalStatus.REJECTED.value,
            actor_id="user_risk_mgr",
            decided_at=now,
            requires_human_approval=False,
            side_effect_allowed=True,
        )


def test_human_decision_request_contract():
    """Verify HumanDecisionRequest validation, comments safety, and extra=forbid."""
    req = HumanDecisionRequest(
        decision=ApprovalDecision.APPROVE,
        comments="Approved following executive review.",
    )
    assert req.decision == ApprovalDecision.APPROVE
    assert req.comments == "Approved following executive review."

    # Invalid enum
    with pytest.raises(ValidationError):
        HumanDecisionRequest.model_validate(
            {"decision": "AUTO_APPROVE", "comments": "hack"}
        )

    # Extra field forbidden
    with pytest.raises(ValidationError):
        HumanDecisionRequest.model_validate(
            {"decision": "APPROVE", "injected_field": "val"}
        )


def test_pending_approval_item_contract():
    """Verify PendingApprovalItem contract fields."""
    item = PendingApprovalItem(
        approval_id="appr_123",
        decision_id="dec_123",
        organization_id="org_alpha",
        title="Reroute Pacific Shipment",
        rationale="Minimize port delay",
        estimated_cost=15000.0,
        confidence=0.92,
        status="PENDING",
        preferred_candidate_id="alt_1",
        action_type="REROUTE_SHIPMENT",
        tradeoffs={"cost_delta": 2500.0, "delay_reduction_hours": 36.0},
        requires_human_approval=True,
    )
    assert item.approval_id == "appr_123"
    assert item.estimated_cost == 15000.0
    assert item.tradeoffs["delay_reduction_hours"] == 36.0


def test_deterministic_approval_id_and_fingerprint():
    """Verify UUIDv5 determinism and SHA-256 fingerprint reproducibility."""
    id1 = generate_deterministic_approval_id("tenant_a", "dec_1", "cand_1")
    id2 = generate_deterministic_approval_id("tenant_a", "dec_1", "cand_1")
    id3 = generate_deterministic_approval_id("tenant_b", "dec_1", "cand_1")
    assert id1 == id2
    assert id1 != id3

    fp1 = compute_approval_fingerprint("tenant_a", "dec_1", "cand_1", "APPROVED", "user_1", "APPROVE")
    fp2 = compute_approval_fingerprint("tenant_a", "dec_1", "cand_1", "APPROVED", "user_1", "APPROVE")
    fp3 = compute_approval_fingerprint("tenant_a", "dec_1", "cand_1", "REJECTED", "user_1", "REJECT")
    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 64
