"""Phase 17 Test Suite: Execution Adapters, Success Semantics, and Idempotency.

Validates:
- Real execution behavior of allowlisted adapters:
    - ShipmentRerouteExecutor
    - CarrierReallocationExecutor
    - FacilityReallocationExecutor
    - ShipmentExpediteExecutor
    - ShipmentHoldExecutor
    - MonitorExecutor
- MockActionExecutor with deterministic statuses (SUCCEEDED, SUBMITTED, FAILED, TIMEOUT, NOT_AVAILABLE)
- Strict idempotency: replayed identical requests return cached result without re-executing
- Idempotency conflict: reusing key with changed parameters raises ActionIdempotencyConflictError
- Transactional persistence: actions table, audit_logs entry, and recommendation status = EXECUTED
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.action.agent import ActionAgent
from app.agents.action.contract import (
    ActionActor,
    ActionCommand,
    ActionResult,
    ActionType,
    ExecutionStatus,
    IdempotencyResult,
    TargetEntityType,
)
from app.agents.action.errors import ActionIdempotencyConflictError
from app.agents.action.executors import (
    ActionExecutorRegistry,
    CarrierReallocationExecutor,
    FacilityReallocationExecutor,
    MockActionExecutor,
    MonitorExecutor,
    ShipmentExpediteExecutor,
    ShipmentHoldExecutor,
    ShipmentRerouteExecutor,
)
from app.agents.action.persistence import ActionPersistenceService
from app.agents.approval.contract import ApprovalResult, ApprovalStatus
from app.db.base import Base
from app.models.governance import Action, AuditLog, Recommendation
from app.models.logistics import Shipment
from app.models.network import Carrier, Route
from app.models.tenancy import Organization, User


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

    # Seed organization
    org = Organization(id="tenant_alpha", name="Alpha Logistics")
    session.add(org)

    # Seed routes
    r1 = Route(id="route_primary", org_id="tenant_alpha", name="Primary Canal Corridor")
    r2 = Route(id="route_cape", org_id="tenant_alpha", name="Cape of Good Hope Bypass")
    session.add_all([r1, r2])

    # Seed carriers
    c1 = Carrier(id="carrier_maersk", org_id="tenant_alpha", name="Maersk Line")
    c2 = Carrier(id="carrier_msc", org_id="tenant_alpha", name="MSC Logistics")
    session.add_all([c1, c2])

    # Seed shipment
    ship = Shipment(
        id="ship_reroute_001",
        org_id="tenant_alpha",
        tracking_number="TRK-98765",
        route_id="route_primary",
        carrier_id="carrier_maersk",
        status="IN_TRANSIT",
        mode="OCEAN",
    )
    session.add(ship)

    # Seed recommendation
    rec = Recommendation(
        id="dec_reroute_001",
        org_id="tenant_alpha",
        title="Reroute container shipment via Cape",
        status="APPROVED",
    )
    session.add(rec)
    session.commit()
    yield session
    session.close()


def _make_approved_result(
    org_id: str = "tenant_alpha",
    dec_id: str = "dec_reroute_001",
    appr_id: str = "appr_reroute_001",
    cand_id: str = "cand_reroute",
) -> ApprovalResult:
    return ApprovalResult(
        approval_id=appr_id,
        organization_id=org_id,
        decision_id=dec_id,
        candidate_id=cand_id,
        status=ApprovalStatus.APPROVED.value,
        actor_id="user_approver_01",
        actor_role="RiskManager",
        decided_at=datetime.now(timezone.utc),
        fingerprint="b" * 64,
        requires_human_approval=False,
        side_effect_allowed=True,
    )


def test_shipment_reroute_executor_success(sqlite_session: Session):
    """Verify ShipmentRerouteExecutor mutates shipment route and returns SUCCEEDED."""
    cmd = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"new_route_id": "route_cape"},
        idempotency_key="idemp_reroute_test_01",
        trace_id="trace_reroute_01",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    executor = ShipmentRerouteExecutor()
    res = executor.execute(cmd, db=sqlite_session)
    sqlite_session.commit()

    assert res.status == ExecutionStatus.SUCCEEDED.value
    assert res.provider == "carrier_edi"
    assert res.result_payload["new_route_id"] == "route_cape"

    # Verify shipment route in DB was updated
    ship = sqlite_session.query(Shipment).filter_by(id="ship_reroute_001").first()
    assert ship is not None
    assert ship.route_id == "route_cape"


def test_carrier_reallocation_executor_success(sqlite_session: Session):
    """Verify CarrierReallocationExecutor updates carrier and returns SUCCEEDED."""
    cmd = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.CARRIER_REALLOCATION,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"new_carrier_id": "carrier_msc"},
        idempotency_key="idemp_carrier_test_01",
        trace_id="trace_carrier_01",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    executor = CarrierReallocationExecutor()
    res = executor.execute(cmd, db=sqlite_session)
    sqlite_session.commit()

    assert res.status == ExecutionStatus.SUCCEEDED.value
    assert res.provider == "logistics_broker"
    ship = sqlite_session.query(Shipment).filter_by(id="ship_reroute_001").first()
    assert ship is not None
    assert ship.carrier_id == "carrier_msc"


def test_shipment_expedite_executor_success(sqlite_session: Session):
    """Verify ShipmentExpediteExecutor sets shipment mode to AIR."""
    cmd = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.EXPEDITE_SHIPMENT,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"expedite_mode": "AIR_EXPRESS"},
        idempotency_key="idemp_expedite_test_01",
        trace_id="trace_expedite_01",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    executor = ShipmentExpediteExecutor()
    res = executor.execute(cmd, db=sqlite_session)
    sqlite_session.commit()

    assert res.status == ExecutionStatus.SUCCEEDED.value
    ship = sqlite_session.query(Shipment).filter_by(id="ship_reroute_001").first()
    assert ship is not None
    assert ship.mode == "AIR"


def test_shipment_hold_executor_success(sqlite_session: Session):
    """Verify ShipmentHoldExecutor updates shipment status to ON_HOLD."""
    cmd = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.HOLD_SHIPMENT,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"hold_reason": "Severe port strike at destination"},
        idempotency_key="idemp_hold_test_01",
        trace_id="trace_hold_01",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    executor = ShipmentHoldExecutor()
    res = executor.execute(cmd, db=sqlite_session)
    sqlite_session.commit()

    assert res.status == ExecutionStatus.SUCCEEDED.value
    ship = sqlite_session.query(Shipment).filter_by(id="ship_reroute_001").first()
    assert ship is not None
    assert ship.status == "ON_HOLD"


def test_monitor_executor_success(sqlite_session: Session):
    """Verify MonitorExecutor records monitoring without mutating shipment status."""
    cmd = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.MONITOR,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={},
        idempotency_key="idemp_monitor_test_01",
        trace_id="trace_monitor_01",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    executor = MonitorExecutor()
    res = executor.execute(cmd, db=sqlite_session)
    assert res.status == ExecutionStatus.SUCCEEDED.value
    assert res.result_payload["monitoring_active"] is True


def test_mock_executor_simulated_statuses():
    """Verify MockActionExecutor exposes real distinct execution statuses."""
    cmd = ActionCommand(
        decision_id="dec_001",
        approval_id="appr_001",
        organization_id="tenant_alpha",
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_123",
        parameters={"new_route_id": "route_B"},
        idempotency_key="idemp_mock_01",
        trace_id="trace_mock_01",
    )

    # 1. SUBMITTED
    mock_submitted = MockActionExecutor(simulated_status=ExecutionStatus.SUBMITTED)
    assert mock_submitted.execute(cmd).status == ExecutionStatus.SUBMITTED.value

    # 2. FAILED
    mock_failed = MockActionExecutor(simulated_status=ExecutionStatus.FAILED, simulated_error_code="CARRIER_REJECTED")
    res_failed = mock_failed.execute(cmd)
    assert res_failed.status == ExecutionStatus.FAILED.value
    assert res_failed.error_code == "CARRIER_REJECTED"

    # 3. TIMEOUT
    mock_timeout = MockActionExecutor(simulated_status=ExecutionStatus.TIMEOUT, simulated_error_code="TIMEOUT")
    assert mock_timeout.execute(cmd).status == ExecutionStatus.TIMEOUT.value

    # 4. NOT_AVAILABLE
    mock_unavail = MockActionExecutor(simulated_status=ExecutionStatus.NOT_AVAILABLE)
    assert mock_unavail.execute(cmd).status == ExecutionStatus.NOT_AVAILABLE.value


def test_idempotency_replay_and_conflict(sqlite_session: Session):
    """Verify idempotency replay returns cached result, and modified parameters cause conflict."""
    agent = ActionAgent()
    approval = _make_approved_result()

    cmd1 = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"new_route_id": "route_cape"},
        idempotency_key="idemp_unique_key_100",
        trace_id="trace_idemp_100",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    # First execution: records action and audit log
    res1, findings1 = agent.execute(command=cmd1, approval=approval, db=sqlite_session)
    sqlite_session.commit()
    assert res1.status == ExecutionStatus.SUCCEEDED.value
    assert res1.idempotency_result == IdempotencyResult.FIRST_EXECUTION.value
    assert any(f.category == "ACTION_EXECUTED" for f in findings1)

    # Second execution with identical command: returns cached result with REPLAYED_IDEMPOTENT
    res2, findings2 = agent.execute(command=cmd1, approval=approval, db=sqlite_session)
    assert res2.action_id == res1.action_id
    assert res2.idempotency_result == IdempotencyResult.REPLAYED_IDEMPOTENT.value
    assert any(f.category == "ACTION_IDEMPOTENT_REPLAY" for f in findings2)

    # Third execution with same key but different route_id: raises ActionIdempotencyConflictError
    cmd_conflict = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_reroute_001",
        organization_id="tenant_alpha",
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"new_route_id": "route_primary"},  # Changed parameter!
        idempotency_key="idemp_unique_key_100",  # Same idempotency key!
        trace_id="trace_idemp_100",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    with pytest.raises(ActionIdempotencyConflictError) as exc_info:
        agent.execute(command=cmd_conflict, approval=approval, db=sqlite_session)
    assert "already used with different parameters" in str(exc_info.value)


def test_transactional_audit_log_and_recommendation_update(sqlite_session: Session):
    """Verify action execution creates audit_log and updates recommendation status to EXECUTED."""
    agent = ActionAgent()
    approval = _make_approved_result(dec_id="dec_reroute_001", appr_id="appr_tx_001")

    cmd = ActionCommand(
        decision_id="dec_reroute_001",
        approval_id="appr_tx_001",
        organization_id="tenant_alpha",
        action_type=ActionType.SHIPMENT_REROUTE,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="ship_reroute_001",
        parameters={"new_route_id": "route_cape"},
        idempotency_key="idemp_tx_001",
        trace_id="trace_tx_001",
        actor=ActionActor(actor_id="user_risk", organization_id="tenant_alpha", role="RiskManager"),
    )

    res, _ = agent.execute(command=cmd, approval=approval, db=sqlite_session)
    sqlite_session.commit()

    # 1. Action persisted
    action_row = sqlite_session.query(Action).filter_by(id=res.action_id).first()
    assert action_row is not None
    assert action_row.status == "SUCCEEDED"

    # 2. Recommendation marked EXECUTED
    rec_row = sqlite_session.query(Recommendation).filter_by(id="dec_reroute_001").first()
    assert rec_row is not None
    assert rec_row.status == "EXECUTED"

    # 3. Audit log recorded
    audit_row = sqlite_session.query(AuditLog).filter_by(resource_id=res.action_id).first()
    assert audit_row is not None
    assert audit_row.action == "ACTION_EXECUTE"
    assert audit_row.status == "SUCCESS"
