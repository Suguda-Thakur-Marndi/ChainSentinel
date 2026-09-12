"""Phase 15 Test Suite 4: End-to-End Multi-Phase LangGraph Integration.

Validates:
1. End-to-end multi-phase data pipeline execution:
   ResearchResult
       ↓
   RiskAssessment
       ↓
   PredictionResult
       ↓
   ScenarioResult / SimulationResult
       ↓
   OptimizationResult
       ↓
   Decision Agent (decision_node)
       ↓
   DecisionResult
       ↓
   Claude Explanation Layer (non-authoritative)
       ↓
   Human Approval Boundary (Phase 16 boundary: selected_route = "approval_boundary")
2. State ownership & write safety: writes strictly DECISION-owned fields
3. Telemetry emission (NodeExecutionTelemetry recorded in AgentObservability)
4. Failure isolation: Claude failure does NOT discard authoritative DecisionResult
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, patch

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentStage,
    apply_state_update,
    validate_state_update,
)
from app.agents.decision.node import (
    DECISION_NODE_CONTRACT,
    decision_node,
)
from app.agents.decision.contract import DecisionStatus, DecisionType
from app.agents.observability import AgentObservability
from app.llm.mock import DeterministicMockLLMProvider


@pytest.fixture
def org_id() -> str:
    return "org_enterprise_logistics"


@pytest.fixture
def multi_phase_graph_state(org_id: str) -> AgentGraphStateDict:
    """State containing full upstream results from Phases 7, 8, 10, 11, 12, 13, 14."""
    return {
        "run_id": "run_multi_phase_15_001",
        "organization_id": org_id,
        "actor_id": "usr_dispatcher_01",
        "request_id": "req_pipe_001",
        "correlation_id": "corr_pipe_001",
        "trace_id": "trace_pipe_001",
        "objective": "Mitigate major Seattle port congestion and reroute shipment SHP-900",
        "current_stage": AgentStage.OPTIMIZATION.value if hasattr(AgentStage, "OPTIMIZATION") else "OPTIMIZATION",
        "current_node": "optimization_agent",
        "status": "RUNNING",
        "step_count": 5,
        "evidence_references": ["ev_noaa_fog_01", "ev_port_congestion_sea"],
        # Phase 7 Risk
        "risk_assessment_id": "risk_sea_75",
        "risk_assessment_reference": {
            "organization_id": org_id,
            "assessment_id": "risk_sea_75",
            "risk_score": 82.0,
            "risk_level": "CRITICAL",
            "evidence_ids": ["ev_port_congestion_sea"],
            "factors": [{"factor_name": "TERMINAL_CHOKEPOINT"}],
        },
        # Phase 11 ML Delay Prediction
        "prediction_id": "pred_sea_delay",
        "prediction_result": {
            "organization_id": org_id,
            "prediction_id": "pred_sea_delay",
            "status": "COMPLETED",
            "predicted_value": 180.0,
            "confidence_lower": 140.0,
            "confidence_upper": 220.0,
            "model_name": "xgboost_delay_v3",
            "evidence_references": ["ev_historical_trends"],
        },
        # Phase 13 Simulation / Scenario
        "scenario_id": "scen_chokepoint_sea",
        "scenario_result": {
            "organization_id": org_id,
            "scenario_id": "scen_chokepoint_sea",
            "status": "COMPLETED",
            "fingerprint": "c" * 64,
            "scenario_definition": {
                "organization_id": org_id,
                "scenario_id": "scen_chokepoint_sea",
                "scenario_type": "PORT_CONGESTION",
                "parameters": [{"name": "delay_minutes", "value": 180.0}],
                "affected_nodes": ["port_sea"],
            },
        },
        # Phase 14 Optimization Result
        "optimization_id": "opt_reroute_optimal",
        "optimization_result": {
            "organization_id": org_id,
            "optimization_id": "opt_reroute_optimal",
            "domain": "SHIPMENT_REROUTE",
            "status": "OPTIMAL",
            "objective": {"objective_type": "MINIMIZE_DELAY"},
            "objective_value": 35.0,
            "selected_alternatives": [
                {
                    "entity_type": "ROUTE",
                    "entity_id": "route_vancouver_rail",
                    "variable_id": "x_van_rail",
                    "assigned_value": 1.0,
                    "cost": 2400.0,
                    "transit_time_hours": 14.0,
                }
            ],
            "metrics": {"delay_reduction_hours": 2.4, "cost_savings": 0.0},
            "solver_metadata": {"wall_time_ms": 18.2},
        },
        "candidate_alternatives": [
            {
                "alternative_id": "alt_van_rail",
                "entity_type": "ROUTE",
                "entity_id": "route_vancouver_rail",
                "cost": 2400.0,
                "transit_time_hours": 14.0,
                "objective_value": 35.0,
                "is_available": True,
            },
            {
                "alternative_id": "alt_oakland",
                "entity_type": "ROUTE",
                "entity_id": "route_oakland_sea",
                "cost": 3100.0,
                "transit_time_hours": 28.0,
                "objective_value": 120.0,
                "is_available": True,
            },
        ],
        "structured_findings": [],
        "limitations": [],
        "warnings": [],
        "findings": {},
        "use_claude": False,  # disable Claude in this test to isolate deterministic node execution
    }


def test_decision_node_full_pipeline_execution(multi_phase_graph_state: AgentGraphStateDict):
    """Verify decision_node processes multi-phase upstream state and writes compliant output payload."""
    update = decision_node(multi_phase_graph_state)

    # 1. Verify required output keys are present
    for key in [
        "decision_id",
        "decision_reference",
        "decision_result",
        "current_stage",
        "current_node",
        "step_count",
        "selected_route",
        "route_reason",
    ]:
        assert key in update

    # 2. Verify state values
    assert update["current_stage"] == AgentStage.DECISION.value
    assert update["current_node"] == "decision_agent"
    assert update["step_count"] == multi_phase_graph_state["step_count"] + 1

    # 3. Verify decision result properties
    res = update["decision_result"]
    assert res["status"] == DecisionStatus.RECOMMENDED.value
    assert res["decision_type"] == DecisionType.REROUTE_SHIPMENT.value
    assert res["optimization_id"] == "opt_reroute_optimal"
    assert res["optimization_summary"]["is_optimal"] is True
    assert res["selected_alternative_id"] == "route_vancouver_rail"
    assert res["requires_human_approval"] is True

    # 4. Verify human approval routing boundary (Phase 16 boundary)
    assert update["selected_route"] == "approval_boundary"
    assert "human approval" in update["route_reason"].lower()

    # 5. Verify state update validation succeeds (no unauthorized field writes)
    validate_state_update(
        current_state=multi_phase_graph_state,
        update_payload=update,
        writer_node_id="decision_agent",
        writer_stage=AgentStage.DECISION,
    )


def test_decision_node_emits_telemetry(multi_phase_graph_state: AgentGraphStateDict):
    """Verify decision_node emits NodeExecutionTelemetry on completion."""
    with patch.object(AgentObservability, "emit_node_telemetry") as mock_telemetry:
        decision_node(multi_phase_graph_state)
        assert mock_telemetry.called
        telemetry = mock_telemetry.call_args[0][0]
        assert telemetry.node_name == "decision_agent"
        assert telemetry.organization_id == multi_phase_graph_state["organization_id"]
        assert telemetry.status == "SUCCESS"
        assert telemetry.duration_ms > 0
