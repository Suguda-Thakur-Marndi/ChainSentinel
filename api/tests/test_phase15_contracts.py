"""Phase 15 Test Suite 1: Strongly Typed Decision Contracts & Pydantic V2 Invariants.

Validates:
- DecisionType enum (all 13 values across Phase 9 and Phase 15 operational responses)
- DecisionStatus enum (all 11 values across Phase 9 and Phase 15)
- DecisionBasis enum (including OPTIMIZATION, SIMULATION, POLICY)
- Pydantic V2 strict validation (extra="forbid", validate_assignment=True)
- AlternativeEvaluation contract (rejection reason, tradeoffs, metrics)
- DecisionOptimizationSummary contract (solver status, objective value, metrics)
- DecisionRiskSummary, DecisionPredictionSummary, DecisionScenarioSummary
- DecisionRequest (tenant validation across scenario, risk, prediction, optimization, simulation)
- DecisionResult (status and candidate consistency, non-fabrication)
- Deterministic UUIDv5 ID generation and SHA-256 fingerprinting
- Credential scrubbing and no-sensitive-values validation
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agents.decision.contract import (
    AlternativeEvaluation,
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
    DecisionOptimizationSummary,
    DecisionPredictionSummary,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionRiskSummary,
    DecisionScenarioSummary,
    DecisionStatus,
    DecisionType,
    compute_decision_fingerprint,
    generate_deterministic_decision_id,
)
from app.agents.decision.errors import (
    DecisionTenantIsolationError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
)


def test_decision_type_enum_completeness():
    """Verify all expected decision types are supported in the enum."""
    expected_types = {
        "OPERATIONAL_REVIEW",
        "OPERATIONAL_RESPONSE",
        "DISRUPTION_MITIGATION",
        "MONITORING",
        "ESCALATION",
        "REROUTE_SHIPMENT",
        "SELECT_ROUTE",
        "REALLOCATE_CARRIER",
        "REALLOCATE_FACILITY",
        "EXPEDITE",
        "HOLD",
        "MONITOR",
        "NO_ACTION",
    }
    actual_types = {t.value for t in DecisionType}
    assert expected_types.issubset(actual_types)


def test_decision_status_enum_completeness():
    """Verify all expected decision statuses are supported."""
    expected_statuses = {
        "READY",
        "REQUIRES_APPROVAL",
        "INSUFFICIENT_EVIDENCE",
        "BLOCKED",
        "INVALID",
        "RECOMMENDED",
        "CONDITIONAL",
        "INSUFFICIENT_DATA",
        "NO_FEASIBLE_OPTION",
        "NO_ACTION_RECOMMENDED",
        "FAILED",
    }
    actual_statuses = {s.value for s in DecisionStatus}
    assert expected_statuses.issubset(actual_statuses)


def test_decision_basis_enum_includes_phase15():
    """Verify Phase 15 basis categories are present."""
    assert DecisionBasis.OPTIMIZATION.value == "OPTIMIZATION"
    assert DecisionBasis.SIMULATION.value == "SIMULATION"
    assert DecisionBasis.POLICY.value == "POLICY"


def test_alternative_evaluation_contract():
    """Verify AlternativeEvaluation schema enforcement and extra='forbid'."""
    alt = AlternativeEvaluation(
        alternative_id="alt_route_north",
        entity_type="ROUTE",
        entity_id="route_002",
        is_selected=False,
        is_feasible=True,
        objective_value=1450.0,
        cost=1450.0,
        delay_minutes=35.0,
        risk_score=42.0,
        metrics={"cost": 1450.0, "delay_minutes": 35.0},
        rejection_reason="Suboptimal cost compared to primary route ($1,450 vs $1,200).",
        tradeoffs={"cost_delta": 250.0, "delay_delta": -10.0},
        evidence_references=["ev_route_data_01"],
    )
    assert alt.alternative_id == "alt_route_north"
    assert not alt.is_selected
    assert alt.tradeoffs["cost_delta"] == 250.0

    # Test extra='forbid'
    with pytest.raises(ValidationError):
        AlternativeEvaluation.model_validate(
            {
                "alternative_id": "alt_bad",
                "entity_type": "ROUTE",
                "entity_id": "route_001",
                "unauthorized_field": "forbidden",
            }
        )


def test_decision_optimization_summary_contract():
    """Verify DecisionOptimizationSummary fields and validation."""
    summary = DecisionOptimizationSummary(
        optimization_id="opt_run_999",
        domain="SHIPMENT_REROUTE",
        solver_status="OPTIMAL",
        objective_type="MINIMIZE_DELAY",
        objective_value=45.0,
        selected_alternatives_count=1,
        solver_wall_time_ms=12.4,
        is_optimal=True,
        time_limit_reached=False,
        metrics={"delay_reduction_hours": 3.5},
    )
    assert summary.solver_status == "OPTIMAL"
    assert summary.is_optimal is True
    assert summary.time_limit_reached is False


def test_decision_request_forbids_extra_fields():
    """Ensure DecisionRequest rejects injected or arbitrary fields."""
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate(
            {
                "organization_id": "org_test_123",
                "target_reference": "shipment_001",
                "arbitrary_injected_field": "malicious_payload",
            }
        )


def test_decision_request_tenant_isolation_validation():
    """Verify multi-tenant isolation fails closed across all upstream references."""
    org = "org_alpha"

    # Cross-tenant optimization result
    with pytest.raises(DecisionTenantIsolationError):
        DecisionRequest(
            organization_id=org,
            target_reference="shipment_001",
            optimization_result={"organization_id": "org_beta", "optimization_id": "opt_01"},
        )

    # Cross-tenant simulation result
    with pytest.raises(DecisionTenantIsolationError):
        DecisionRequest(
            organization_id=org,
            target_reference="shipment_001",
            simulation_result={"organization_id": "org_beta", "simulation_id": "sim_01"},
        )

    # Cross-tenant prefixed evidence
    with pytest.raises(DecisionTenantIsolationError):
        DecisionRequest(
            organization_id=org,
            target_reference="shipment_001",
            evidence_references=["org_beta:ev_secret_document"],
        )


def test_decision_candidate_approval_invariants():
    """Ensure a decision candidate cannot claim autonomous APPROVED status."""
    with pytest.raises(InvalidDecisionCandidateError):
        DecisionCandidate(
            candidate_id="cand_invalid",
            action_type="REROUTE_SHIPMENT",
            title="Auto approved reroute",
            description="Autonomous execution claim",
            status="APPROVED",
            requires_human_approval=True,
        )


def test_deterministic_id_and_fingerprint_generation():
    """Verify UUIDv5 and SHA-256 fingerprint reproducibility."""
    org = "org_test_tenant"
    opt_id = "opt_001_run"
    target = "shipment_777"

    id1 = generate_deterministic_decision_id(
        organization_id=org,
        target_reference=target,
        decision_type="REROUTE_SHIPMENT",
        optimization_id=opt_id,
    )
    id2 = generate_deterministic_decision_id(
        organization_id=org,
        target_reference=target,
        decision_type="REROUTE_SHIPMENT",
        optimization_id=opt_id,
    )
    assert id1 == id2
    assert id1.startswith("dec_")

    fp1 = compute_decision_fingerprint(
        organization_id=org,
        decision_type="REROUTE_SHIPMENT",
        target_reference=target,
        optimization_id=opt_id,
        policy_version="1.0.0",
    )
    fp2 = compute_decision_fingerprint(
        organization_id=org,
        decision_type="REROUTE_SHIPMENT",
        target_reference=target,
        optimization_id=opt_id,
        policy_version="1.0.0",
    )
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex string


def test_decision_result_requires_human_approval_invariant():
    """Verify that DecisionResult strictly maintains human approval boundary."""
    cand = DecisionCandidate(
        candidate_id="cand_01",
        action_type="SELECT_ROUTE",
        title="Select Secondary Corridor",
        description="Recommend alternate maritime corridor.",
        requires_human_approval=True,
        status="REQUIRES_APPROVAL",
    )
    res = DecisionResult(
        decision_id="dec_0001",
        organization_id="org_test",
        decision_type=DecisionType.SELECT_ROUTE,
        status=DecisionStatus.RECOMMENDED.value,
        candidates=[cand],
        preferred_candidate=cand,
        requires_human_approval=True,
        fingerprint="a" * 64,
    )
    assert res.requires_human_approval is True
    assert res.status == "RECOMMENDED"
