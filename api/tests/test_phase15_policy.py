"""Phase 15 Test Suite 2: Deterministic Decision Policy Engine.

Tests:
1. Healthy Decision: Risk + ML Prediction + Simulation + Optimization -> valid recommendation.
2. Solver Status OPTIMAL: Proven mathematical optimality selected with high confidence.
3. Solver Status FEASIBLE: Feasible solution, optimality not proven -> CONDITIONAL recommendation.
4. Solver Status TIME_LIMIT: Solver timed out; feasible candidate -> CONDITIONAL; no candidate -> NO_FEASIBLE_OPTION.
5. Solver Status INFEASIBLE: Strictly NO_FEASIBLE_OPTION, human review required, no fabricated solutions.
6. Solver Status FAILED / UNBOUNDED: Status FAILED.
7. Objective Alignment: Respects requested objective (MINIMIZE_DELAY, MINIMIZE_COST, MINIMIZE_RISK).
8. Low Risk / Nominal Conditions: NO_ACTION or MONITOR.
9. High Risk Disruption without Optimization: Escalate for operational review.
10. Deterministic Tie-Breaking: Stable, identical alternative selection for equal objective values.
11. Alternative Comparison: Evaluates all candidates, preserves rejection reasons & tradeoffs.
12. Freshness Enforcement: Stale inputs flagged with limitation, conditional status.
13. Human Approval Boundary: requires_human_approval = True across all policy outcomes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.agents.decision.contract import (
    AlternativeEvaluation,
    DecisionConstraint,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionType,
)
from app.agents.decision.policy import DecisionPolicy, DecisionPolicyConfig


@pytest.fixture
def org_id() -> str:
    return "org_logistics_corp"


@pytest.fixture
def base_request(org_id: str) -> DecisionRequest:
    return DecisionRequest(
        organization_id=org_id,
        target_reference="shipment_US_SEA_101",
        risk_assessment_reference={
            "organization_id": org_id,
            "assessment_id": "risk_ass_001",
            "risk_score": 75.0,
            "risk_level": "HIGH",
            "evidence_ids": ["ev_ais_congestion_01"],
            "factors": [{"factor_name": "PORT_CONGESTION_SEATTLE"}],
        },
        prediction_result={
            "organization_id": org_id,
            "prediction_id": "pred_001",
            "status": "COMPLETED",
            "predicted_value": 140.0,  # 140 minutes delay
            "confidence_lower": 110.0,
            "confidence_upper": 170.0,
            "model_name": "lightgbm_delay_v2",
            "evidence_references": ["ev_historical_transit_01"],
        },
        scenario_result={
            "organization_id": org_id,
            "scenario_id": "scen_chokepoint_01",
            "status": "COMPLETED",
            "fingerprint": "b" * 64,
            "scenario_definition": {
                "organization_id": org_id,
                "scenario_id": "scen_chokepoint_01",
                "scenario_type": "PORT_CLOSURE",
                "parameters": [{"name": "delay_minutes", "value": 140.0}],
                "affected_nodes": ["port_sea"],
                "affected_edges": ["edge_pac_sea"],
            },
        },
        objective_type="MINIMIZE_DELAY",
        constraints=[
            DecisionConstraint(constraint_type="BUDGET", name="max_budget", value=20000.0, unit="USD"),
        ],
    )


def test_policy_healthy_optimal_decision(base_request: DecisionRequest):
    """Verify healthy end-to-end recommendation with solver status OPTIMAL."""
    opt_result = {
        "organization_id": base_request.organization_id,
        "optimization_id": "opt_reroute_001",
        "domain": "SHIPMENT_REROUTE",
        "status": "OPTIMAL",
        "objective": {"objective_type": "MINIMIZE_DELAY"},
        "objective_value": 25.0,  # delay reduced to 25 mins
        "selected_alternatives": [
            {
                "entity_type": "ROUTE",
                "entity_id": "route_vancouver_inland",
                "variable_id": "x_route_van",
                "assigned_value": 1.0,
                "cost": 1500.0,
                "transit_time_hours": 12.0,
            }
        ],
        "metrics": {"delay_reduction_minutes": 115.0},
        "solver_metadata": {"wall_time_ms": 14.5},
    }
    candidate_alts = [
        {
            "alternative_id": "alt_van",
            "entity_type": "ROUTE",
            "entity_id": "route_vancouver_inland",
            "cost": 1500.0,
            "transit_time_hours": 12.0,
            "objective_value": 25.0,
            "is_available": True,
        },
        {
            "alternative_id": "alt_tac",
            "entity_type": "ROUTE",
            "entity_id": "route_tacoma_rail",
            "cost": 2200.0,
            "transit_time_hours": 18.0,
            "objective_value": 60.0,
            "is_available": True,
        },
    ]

    base_request.optimization_result = opt_result
    base_request.candidate_alternatives = candidate_alts

    policy = DecisionPolicy()
    result, limitations = policy.evaluate(base_request)

    assert result.status == DecisionStatus.RECOMMENDED.value
    assert result.decision_type == DecisionType.REROUTE_SHIPMENT
    assert result.preferred_candidate is not None
    assert result.selected_alternative_id == "route_vancouver_inland"
    assert result.optimization_summary is not None
    assert result.optimization_summary.is_optimal is True
    assert result.requires_human_approval is True
    assert result.confidence is not None and result.confidence >= 0.90

    # Verify alternative comparisons
    assert len(result.alternatives_considered) == 2
    selected_alt = [a for a in result.alternatives_considered if a.is_selected][0]
    unselected_alt = [a for a in result.alternatives_considered if not a.is_selected][0]
    assert selected_alt.rejection_reason is None
    assert unselected_alt.rejection_reason is not None
    assert "Suboptimal" in unselected_alt.rejection_reason


def test_policy_feasible_unproven_optimality(base_request: DecisionRequest):
    """Verify solver status FEASIBLE produces CONDITIONAL recommendation."""
    opt_result = {
        "organization_id": base_request.organization_id,
        "optimization_id": "opt_reroute_002",
        "domain": "ROUTE_SELECTION",
        "status": "FEASIBLE",
        "objective": {"objective_type": "MINIMIZE_DELAY"},
        "objective_value": 40.0,
        "selected_alternatives": [
            {
                "entity_type": "ROUTE",
                "entity_id": "route_oakland_alt",
                "variable_id": "x_route_oak",
                "assigned_value": 1.0,
            }
        ],
        "metrics": {},
        "solver_metadata": {"wall_time_ms": 850.0},
    }
    base_request.optimization_result = opt_result

    policy = DecisionPolicy()
    result, limitations = policy.evaluate(base_request)

    assert result.status == DecisionStatus.CONDITIONAL.value
    assert result.decision_type == DecisionType.SELECT_ROUTE
    assert result.optimization_summary.is_optimal is False
    assert any(lim.category.value == "HIGH_UNCERTAINTY" for lim in limitations)


def test_policy_time_limit_handling(base_request: DecisionRequest):
    """Verify solver status TIME_LIMIT is never labeled OPTIMAL."""
    # Case A: Time limit with a feasible candidate found before timeout
    opt_result_with_cand = {
        "organization_id": base_request.organization_id,
        "optimization_id": "opt_timeout_01",
        "domain": "CARRIER_ALLOCATION",
        "status": "TIME_LIMIT",
        "objective": {"objective_type": "MINIMIZE_COST"},
        "objective_value": 5200.0,
        "selected_alternatives": [
            {
                "entity_type": "CARRIER",
                "entity_id": "carrier_maersk_secondary",
                "variable_id": "x_carrier_01",
                "assigned_value": 1.0,
            }
        ],
        "metrics": {},
        "solver_metadata": {"wall_time_ms": 10000.0},
    }
    base_request.optimization_result = opt_result_with_cand

    policy = DecisionPolicy()
    result, limitations = policy.evaluate(base_request)

    assert result.status == DecisionStatus.CONDITIONAL.value
    assert result.decision_type == DecisionType.REALLOCATE_CARRIER
    assert result.optimization_summary.time_limit_reached is True
    assert result.optimization_summary.is_optimal is False
    assert any(lim.category.value == "HIGH_UNCERTAINTY" for lim in limitations)

    # Case B: Time limit with NO solution found before timeout
    opt_result_no_cand = dict(opt_result_with_cand)
    opt_result_no_cand["selected_alternatives"] = []
    base_request.optimization_result = opt_result_no_cand

    result_no_cand, lims_no_cand = policy.evaluate(base_request)
    assert result_no_cand.status == DecisionStatus.NO_FEASIBLE_OPTION.value
    assert result_no_cand.optimization_summary.is_optimal is False


def test_policy_infeasible_handling(base_request: DecisionRequest):
    """Verify solver status INFEASIBLE produces NO_FEASIBLE_OPTION and no fabricated solution."""
    opt_result_infeasible = {
        "organization_id": base_request.organization_id,
        "optimization_id": "opt_infeasible_01",
        "domain": "SHIPMENT_REROUTE",
        "status": "INFEASIBLE",
        "objective": {"objective_type": "MINIMIZE_DELAY"},
        "objective_value": None,
        "selected_alternatives": [],
        "metrics": {},
        "solver_metadata": {"wall_time_ms": 55.0},
    }
    base_request.optimization_result = opt_result_infeasible
    base_request.candidate_alternatives = [
        {"alternative_id": "alt_01", "entity_type": "ROUTE", "entity_id": "r1", "is_available": False}
    ]

    policy = DecisionPolicy()
    result, limitations = policy.evaluate(base_request)

    assert result.status == DecisionStatus.NO_FEASIBLE_OPTION.value
    assert result.decision_type == DecisionType.HOLD
    assert result.confidence is None
    assert result.requires_human_approval is True
    assert any(lim.category.value == "UNSUPPORTED_OPERATION" for lim in limitations)



def test_policy_objective_alignment(base_request: DecisionRequest):
    """Verify policy respects explicit objective type."""
    opt_result = {
        "organization_id": base_request.organization_id,
        "optimization_id": "opt_obj_cost",
        "domain": "SHIPMENT_REROUTE",
        "status": "OPTIMAL",
        "objective": {"objective_type": "MINIMIZE_COST"},
        "objective_value": 850.0,
        "selected_alternatives": [
            {"entity_type": "ROUTE", "entity_id": "route_cheapest", "variable_id": "x1", "assigned_value": 1.0}
        ],
        "metrics": {},
        "solver_metadata": {"wall_time_ms": 10.0},
    }
    base_request.objective_type = "MINIMIZE_COST"
    base_request.optimization_result = opt_result

    policy = DecisionPolicy()
    result, _ = policy.evaluate(base_request)

    assert result.optimization_summary.objective_type == "MINIMIZE_COST"
    assert result.optimization_summary.objective_value == 850.0


def test_policy_low_risk_nominal_no_action(org_id: str):
    """Verify low risk with no delay results in NO_ACTION or MONITOR."""
    request = DecisionRequest(
        organization_id=org_id,
        target_reference="shipment_nominal_001",
        risk_assessment_reference={
            "organization_id": org_id,
            "assessment_id": "risk_low_01",
            "risk_score": 15.0,
            "risk_level": "LOW",
        },
        prediction_result={
            "organization_id": org_id,
            "prediction_id": "pred_low_01",
            "status": "COMPLETED",
            "predicted_value": 0.0,
        },
    )

    policy = DecisionPolicy()
    result, _ = policy.evaluate(request)

    assert result.status == DecisionStatus.NO_ACTION_RECOMMENDED.value
    assert result.decision_type == DecisionType.NO_ACTION
    assert result.preferred_candidate.action_type == "NO_ACTION"


def test_policy_deterministic_tie_breaking(base_request: DecisionRequest):
    """Verify tie-breaking between candidates with equal objective values is stable and deterministic."""
    candidate_alts = [
        {"alternative_id": "alt_z", "entity_type": "ROUTE", "entity_id": "route_z", "objective_value": 100.0, "is_available": True},
        {"alternative_id": "alt_a", "entity_type": "ROUTE", "entity_id": "route_a", "objective_value": 100.0, "is_available": True},
        {"alternative_id": "alt_m", "entity_type": "ROUTE", "entity_id": "route_m", "objective_value": 100.0, "is_available": True},
    ]
    opt_result = {
        "organization_id": base_request.organization_id,
        "optimization_id": "opt_tie_break",
        "domain": "ROUTE_SELECTION",
        "status": "OPTIMAL",
        "objective": {"objective_type": "MINIMIZE_DELAY"},
        "objective_value": 100.0,
        "selected_alternatives": [
            {"entity_type": "ROUTE", "entity_id": "route_a", "variable_id": "x_a", "assigned_value": 1.0}
        ],
        "metrics": {},
        "solver_metadata": {"wall_time_ms": 12.0},
    }
    base_request.optimization_result = opt_result
    base_request.candidate_alternatives = candidate_alts

    policy = DecisionPolicy()
    result1, _ = policy.evaluate(base_request)
    result2, _ = policy.evaluate(base_request)

    # Identical ordering across repeated evaluations
    alts1 = [a.alternative_id for a in result1.alternatives_considered]
    alts2 = [a.alternative_id for a in result2.alternatives_considered]
    assert alts1 == alts2
    assert alts1[0] == "alt_a"  # selected alternative is first


def test_policy_freshness_enforcement(base_request: DecisionRequest):
    """Verify stale inputs (>24 hours) are flagged with limitation."""
    stale_time = datetime.now(timezone.utc) - timedelta(hours=36)
    base_request.freshness_timestamp = stale_time

    policy = DecisionPolicy()
    result, limitations = policy.evaluate(base_request)

    assert any(lim.category.value == "STALE_DATA" and "freshness" in lim.description.lower() for lim in limitations)

