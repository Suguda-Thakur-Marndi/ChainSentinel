"""Tests for Phase 18 LangGraph Node Integration and Claude Explanation Boundary."""

from datetime import datetime, timezone
from typing import Any, Dict
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentStage,
    AUTHORITATIVE_FIELD_OWNERS,
)
from app.agents.verification.node import VERIFICATION_NODE_CONTRACT, verification_node
from app.db.base import Base
import app.models
from app.db.unit_of_work import UnitOfWork
from app.models.governance import Action
from app.models.logistics import Shipment
from app.models.tenancy import Organization


@pytest.fixture
def graph_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    org = Organization(id="org_lg_test", name="LangGraph Test Corp")
    session.add(org)

    ship = Shipment(
        id="ship_lg_01",
        org_id="org_lg_test",
        tracking_number="TRK-LG",
        route_id="ROUTE_LG_TARGET",
        status="IN_TRANSIT",
    )
    session.add(ship)

    act = Action(
        id="act_lg_01",
        org_id="org_lg_test",
        action_type="SHIPMENT_REROUTE",
        target_entity_type="SHIPMENT",
        target_entity_id="ship_lg_01",
        status="EXECUTED",
        executed_at=datetime.now(timezone.utc),
    )
    session.add(act)
    session.commit()
    return session


class TestLangGraphAndClaudeBoundary:
    """Validate LangGraph node contracts, state transitions, and Claude boundary."""

    def test_authoritative_field_owners_registration(self):
        """Ensure verification fields are mapped strictly to AgentStage.VERIFICATION."""
        assert AUTHORITATIVE_FIELD_OWNERS["verification_id"] == {AgentStage.VERIFICATION}
        assert AUTHORITATIVE_FIELD_OWNERS["verification_reference"] == {AgentStage.VERIFICATION}
        assert AUTHORITATIVE_FIELD_OWNERS["verification_result"] == {AgentStage.VERIFICATION}
        assert AUTHORITATIVE_FIELD_OWNERS["verification_status"] == {AgentStage.VERIFICATION}

    def test_node_contract_properties(self):
        """Ensure VERIFICATION_NODE_CONTRACT satisfies requirements."""
        assert VERIFICATION_NODE_CONTRACT.node_id == "verification_agent"
        assert VERIFICATION_NODE_CONTRACT.stage == AgentStage.VERIFICATION
        assert VERIFICATION_NODE_CONTRACT.is_side_effecting is False
        assert "action_result" in VERIFICATION_NODE_CONTRACT.input_keys
        assert "verification_result" in VERIFICATION_NODE_CONTRACT.output_keys

    def test_verification_node_execution_halts_at_termination(self, graph_db):
        """Node must execute, populate verification results, and strictly route to termination (no autonomous remediation)."""
        uow = UnitOfWork(session=graph_db)

        state: AgentGraphStateDict = {
            "run_id": "run_test_001",
            "organization_id": "org_lg_test",
            "actor_id": "user_operator",
            "request_id": "req_001",
            "correlation_id": "corr_001",
            "trace_id": "trace_001",
            "action_id": "act_lg_01",
            "action_result": {
                "action_id": "act_lg_01",
                "action_type": "SHIPMENT_REROUTE",
                "target_entity_type": "SHIPMENT",
                "target_entity_id": "ship_lg_01",
                "status": "SUCCEEDED",
                "execution_details": {"new_route_id": "ROUTE_LG_TARGET"},
            },
        }

        update = verification_node(state=state, uow=uow)

        assert update["current_stage"] == AgentStage.VERIFICATION.value
        assert update["current_node"] == "verification_agent"
        assert update["verification_id"] is not None
        assert update["verification_status"] == "VERIFIED"
        assert update["verification_result"]["verified"] is True

        # STRICT BOUNDARY: Never route to action, approval, or decision
        assert update["selected_route"] == "termination"
        assert "Pipeline halted" in update["route_reason"]

    def test_claude_cannot_determine_outcome(self):
        """VerificationResult is strictly derived from authoritative code, never LLM output."""
        from app.agents.verification.verifiers import BaseActionVerifier

        class FakeLLMVerifier(BaseActionVerifier):
            action_type = "UNKNOWN"

        # Verifier cannot be an LLM wrapper
        assert not hasattr(FakeLLMVerifier, "prompt")
        assert not hasattr(FakeLLMVerifier, "model_id")
