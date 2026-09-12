"""Phase 17 Test Suite: Domain Contracts and Models.

Validates:
- ActionType enum members and Phase 15 alias resolution
- ExecutionStatus, TargetEntityType, and IdempotencyResult enums
- ActionCommand / ActionRequest validation, immutability, extra="forbid"
- Rejection of arbitrary URLs (SSRF prevention) and code execution patterns
- Deterministic UUIDv5 action_id repeatability
- Deterministic SHA-256 action fingerprint repeatability
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.agents.action.contract import (
    ActionActor,
    ActionCommand,
    ActionRequest,
    ActionResult,
    ActionType,
    ExecutionStatus,
    IdempotencyResult,
    TargetEntityType,
    compute_action_fingerprint,
    generate_deterministic_action_id,
)
from app.agents.action.errors import (
    ActionSecurityViolationError,
    ActionTenantIsolationError,
    InvalidActionRequestError,
)


def test_action_type_enum_and_aliases():
    """Verify ActionType enum members and backward-compatible alias resolution."""
    assert ActionType.SHIPMENT_REROUTE.value == "SHIPMENT_REROUTE"
    assert ActionType.CARRIER_REALLOCATION.value == "CARRIER_REALLOCATION"
    assert ActionType.FACILITY_REALLOCATION.value == "FACILITY_REALLOCATION"
    assert ActionType.EXPEDITE_SHIPMENT.value == "EXPEDITE_SHIPMENT"
    assert ActionType.HOLD_SHIPMENT.value == "HOLD_SHIPMENT"
    assert ActionType.MONITOR.value == "MONITOR"

    # Aliases
    assert ActionType("REROUTE_SHIPMENT") == ActionType.SHIPMENT_REROUTE
    assert ActionType("SELECT_ROUTE") == ActionType.SHIPMENT_REROUTE
    assert ActionType("REALLOCATE_CARRIER") == ActionType.CARRIER_REALLOCATION
    assert ActionType("REALLOCATE_FACILITY") == ActionType.FACILITY_REALLOCATION
    assert ActionType("EXPEDITE") == ActionType.EXPEDITE_SHIPMENT
    assert ActionType("HOLD") == ActionType.HOLD_SHIPMENT


def test_execution_status_enum():
    """Verify execution lifecycle statuses."""
    expected = {"SUCCEEDED", "SUBMITTED", "FAILED", "NOT_AVAILABLE", "TIMEOUT", "UNKNOWN"}
    actual = {s.value for s in ExecutionStatus}
    assert expected == actual


def test_target_entity_type_enum():
    """Verify supported operational target entities."""
    expected = {"SHIPMENT", "CARRIER", "FACILITY", "ROUTE", "SUPPLIER", "INVENTORY"}
    actual = {t.value for t in TargetEntityType}
    assert expected == actual


def test_action_command_valid():
    """Verify valid ActionCommand construction with deterministic action_id."""
    cmd = ActionCommand(
        decision_id="dec_test_001",
        approval_id="appr_test_001",
        organization_id="tenant_alpha",
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_123",
        parameters={"new_route_id": "route_pacific_01"},
        idempotency_key="idemp_reroute_001",
        trace_id="trace_001",
        actor=ActionActor(actor_id="user_risk_01", organization_id="tenant_alpha", role="RiskManager"),
    )
    assert cmd.action_id is not None
    assert cmd.action_id.startswith("act_")
    assert cmd.action_type == ActionType.SHIPMENT_REROUTE
    assert cmd.target_entity_id == "ship_123"


def test_action_command_forbids_extra_fields():
    """Verify that extra unknown fields are rejected."""
    with pytest.raises(ValidationError):
        ActionCommand.model_validate(
            {
                "decision_id": "dec_001",
                "approval_id": "appr_001",
                "organization_id": "tenant_alpha",
                "action_type": ActionType.MONITOR,
                "target_entity_type": TargetEntityType.SHIPMENT,
                "target_entity_id": "ship_123",
                "idempotency_key": "idemp_001",
                "trace_id": "trace_001",
                "unauthorized_field": "bypass",  # Extra field
            }
        )


def test_action_command_rejects_empty_ids():
    """Verify that empty string IDs are rejected."""
    with pytest.raises((InvalidActionRequestError, ValidationError)):
        ActionCommand(
            decision_id="",
            approval_id="appr_001",
            organization_id="tenant_alpha",
            action_type=ActionType.MONITOR,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_123",
            idempotency_key="idemp_001",
            trace_id="trace_001",
        )


def test_action_command_rejects_arbitrary_urls():
    """Verify SSRF protection: reject arbitrary user URLs in parameters."""
    with pytest.raises(ActionSecurityViolationError) as exc_info:
        ActionCommand(
            decision_id="dec_001",
            approval_id="appr_001",
            organization_id="tenant_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_123",
            parameters={"callback_url": "https://attacker.evil.com/exfiltrate"},
            idempotency_key="idemp_001",
            trace_id="trace_001",
        )
    assert "Arbitrary URL injection detected" in str(exc_info.value)


def test_action_command_rejects_code_execution_patterns():
    """Verify arbitrary code execution protection in parameters."""
    with pytest.raises(ActionSecurityViolationError) as exc_info:
        ActionCommand(
            decision_id="dec_001",
            approval_id="appr_001",
            organization_id="tenant_alpha",
            action_type=ActionType.SHIPMENT_REROUTE,
            target_entity_type=TargetEntityType.SHIPMENT,
            target_entity_id="ship_123",
            parameters={"hook": "__import__('os').system('id')"},
            idempotency_key="idemp_001",
            trace_id="trace_001",
        )
    assert "Prohibited executable code pattern" in str(exc_info.value)


def test_deterministic_action_id_repeatability():
    """Verify UUIDv5 action ID is stable and tenant-isolated."""
    id1 = generate_deterministic_action_id(
        organization_id="tenant_alpha",
        decision_id="dec_001",
        approval_id="appr_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_id="ship_123",
        idempotency_key="idemp_001",
    )
    id2 = generate_deterministic_action_id(
        organization_id="tenant_alpha",
        decision_id="dec_001",
        approval_id="appr_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_id="ship_123",
        idempotency_key="idemp_001",
    )
    assert id1 == id2
    assert id1.startswith("act_")

    # Different tenant produces different ID
    id_other_tenant = generate_deterministic_action_id(
        organization_id="tenant_beta",
        decision_id="dec_001",
        approval_id="appr_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_id="ship_123",
        idempotency_key="idemp_001",
    )
    assert id1 != id_other_tenant


def test_deterministic_action_fingerprint_repeatability():
    """Verify SHA-256 fingerprint is reproducible and sensitive to content changes."""
    fp1 = compute_action_fingerprint(
        organization_id="tenant_alpha",
        decision_id="dec_001",
        approval_id="appr_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_123",
        parameters={"new_route_id": "route_A"},
    )
    fp2 = compute_action_fingerprint(
        organization_id="tenant_alpha",
        decision_id="dec_001",
        approval_id="appr_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_123",
        parameters={"new_route_id": "route_A"},
    )
    assert fp1 == fp2
    assert len(fp1) == 64

    # Different parameter produces different fingerprint
    fp3 = compute_action_fingerprint(
        organization_id="tenant_alpha",
        decision_id="dec_001",
        approval_id="appr_001",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_123",
        parameters={"new_route_id": "route_B"},
    )
    assert fp1 != fp3
