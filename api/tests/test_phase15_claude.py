"""Phase 15 Claude Decision Explanation Layer Integration Tests.

Validates:
1. Decision explanation snapshot preserves Phase 15 authoritative decision fields
2. Claude explanation layer cannot alter the selected candidate or decision status
3. Claude cannot approve, waive approval, or mark decision executed
4. Claude cannot perform or claim operational mutations (rerouting, dispatch, PO issuance)
5. Failure isolation: Claude timeouts or errors do NOT invalidate authoritative DecisionResult
6. Grounding and citation integrity: citations outside evidence are rejected
7. Multi-tenant isolation: cross-tenant citations rejected
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from app.agents.decision.claude_contract import (
    ClaudeDecisionExplanation,
    DecisionExplanationInput,
    DecisionExplanationResult,
    DecisionExplanationStatus,
)
from app.agents.decision.claude_service import (
    ClaudeDecisionExplanationService,
    DECISION_EXPLANATION_PROMPT_VERSION,
)
from app.agents.decision.contract import (
    AlternativeEvaluation,
    DecisionBasis,
    DecisionCandidate,
    DecisionConstraint,
    DecisionOptimizationSummary,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionType,
    compute_decision_fingerprint,
    generate_deterministic_decision_id,
)
from app.agents.decision.errors import (
    DecisionActionContradictionError,
    DecisionApprovalViolationError,
    DecisionCandidateContradictionError,
    DecisionExecutionViolationError,
    DecisionExplanationCitationIntegrityError,
    DecisionExplanationGroundingError,
    DecisionQuantitativeFabricationError,
    DecisionTenantIsolationError,
)
from app.agents.decision.policy import DecisionPolicy


def _sample_decision_result(
    org_id: str = "tenant_alpha",
    status: str = DecisionStatus.RECOMMENDED.value,
) -> DecisionResult:
    cand = DecisionCandidate(
        candidate_id="cand_opt_1",
        action_type="REROUTE_SHIPMENT",
        title="Reroute via Alternate Corridor",
        description="Reroutes shipment around congested corridor based on mathematical solver.",
        priority="HIGH",
        parameters={"selected_route": "corridor_b", "target": "shp_100"},
        prerequisites=["validate_corridor"],
        constraints=[
            DecisionConstraint(
                constraint_type="AUTHORITY",
                name="HUMAN_APPROVAL_AUTHORITY",
                value=True,
            )
        ],
        expected_effect="Avoids 18-hour congestion delay.",
        evidence_references=["doc_corridor_audit#c1"],
        requires_human_approval=True,
        provenance={"rule_id": "rule_optimization_synthesis"},
        status="REQUIRES_APPROVAL",
    )
    rationale = DecisionRationale(
        basis_type=DecisionBasis.OPTIMIZATION,
        source_reference="opt_run_1",
        evidence_references=["doc_corridor_audit#c1"],
        rule_id="rule_optimization_synthesis",
        finding_ids=[],
        explanation_code="MATHEMATICALLY_OPTIMAL_SOLUTION_PROVEN",
    )
    req = DecisionRequest(
        organization_id=org_id,
        decision_type=DecisionType.REROUTE_SHIPMENT,
        shipment_id="shp_100",
        evidence_references=["doc_corridor_audit#c1"],
    )
    fingerprint = compute_decision_fingerprint(req)
    decision_id = generate_deterministic_decision_id(req)

    return DecisionResult(
        decision_id=decision_id,
        organization_id=org_id,
        decision_type=DecisionType.REROUTE_SHIPMENT,
        status=status,
        candidates=[cand],
        preferred_candidate=cand,
        preferred_candidate_id=cand.candidate_id,
        rationales=[rationale],
        constraints=cand.constraints,
        requires_human_approval=True,
        evidence_references=["doc_corridor_audit#c1"],
        fingerprint=fingerprint,
        optimization_id="opt_run_1",
        optimization_summary=DecisionOptimizationSummary(
            optimization_id="opt_run_1",
            domain="SHIPMENT_REROUTE",
            solver_status="OPTIMAL",
            objective_type="MINIMIZE_DELAY",
            objective_value=120.0,
            selected_alternatives_count=1,
            solver_wall_time_ms=55.0,
            is_optimal=True,
            time_limit_reached=False,
            metrics={"delay_savings_hours": 18.0},
        ),
        selected_alternative_id="cand_opt_1",
        confidence=0.95,
        decision_policy_version="1.0.0",
    )


# 1. Decision explanation snapshot preserves Phase 15 authoritative decision fields
def test_phase15_claude_snapshot_preservation():
    service = ClaudeDecisionExplanationService()
    decision = _sample_decision_result()
    snapshot = service.build_snapshot(decision=decision, objective="MINIMIZE_DELAY")

    assert snapshot.decision_id == decision.decision_id
    assert snapshot.organization_id == decision.organization_id
    assert snapshot.status == decision.status
    assert snapshot.preferred_candidate_id == "cand_opt_1"
    assert snapshot.requires_human_approval is True
    assert "doc_corridor_audit#c1" in snapshot.evidence_references
    assert snapshot.objective == "MINIMIZE_DELAY"


# 2. Claude explanation layer cannot alter the selected candidate
def test_phase15_claude_cannot_alter_selected_candidate():
    service = ClaudeDecisionExplanationService()
    decision = _sample_decision_result()
    # Add a second candidate to test contradiction between authoritative preferred and claimed candidate
    cand_alt_2 = DecisionCandidate(
        candidate_id="cand_alt_2",
        action_type="HOLD",
        title="Hold in Place",
        description="Alternative hold option.",
        priority="LOW",
        parameters={},
        prerequisites=[],
        constraints=[],
        expected_effect="Hold shipment.",
        evidence_references=["doc_corridor_audit#c1"],
        requires_human_approval=True,
        provenance={"rule_id": "rule_hold"},
        status="REQUIRES_APPROVAL",
    )
    decision.candidates.append(cand_alt_2)
    snapshot = service.build_snapshot(decision=decision)

    # Mock Claude output attempting to switch the selected candidate to cand_alt_2
    explanation = ClaudeDecisionExplanation(
        summary="Executive summary recommending different candidate.",
        decision_purpose="Authoritative decision review.",
        decision_type_statement="Decision type is REROUTE_SHIPMENT.",
        selected_candidate_explanation="Selected candidate is cand_alt_2 instead of cand_opt_1.",
        candidate_tradeoffs=[],
        approval_requirement_statement="Human approval is required before execution.",
        scenario_relationship="Scenario verified.",
        risk_relationship="Risk verified.",
        prediction_relationship="Prediction verified.",
        constraint_explanations=[],
        uncertainty_and_gaps="None.",
        limitations=[],
        citations=["doc_corridor_audit#c1"],
    )

    with pytest.raises(DecisionCandidateContradictionError):
        service.validate_consistency(explanation, snapshot)


# 3. Claude cannot approve, waive approval, or claim approval granted
def test_phase15_claude_cannot_approve_or_waive_approval():
    service = ClaudeDecisionExplanationService()
    decision = _sample_decision_result()
    snapshot = service.build_snapshot(decision=decision)

    explanation = ClaudeDecisionExplanation(
        summary="Decision is approved by the system autonomously.",
        decision_purpose="Authoritative decision review.",
        decision_type_statement="Decision type is REROUTE_SHIPMENT.",
        selected_candidate_explanation="Preferred candidate is cand_opt_1.",
        candidate_tradeoffs=[],
        approval_requirement_statement="Approval granted automatically; no review required.",
        scenario_relationship="Scenario verified.",
        risk_relationship="Risk verified.",
        prediction_relationship="Prediction verified.",
        constraint_explanations=[],
        uncertainty_and_gaps="None.",
        limitations=[],
        citations=["doc_corridor_audit#c1"],
    )

    with pytest.raises(DecisionApprovalViolationError):
        service.validate_consistency(explanation, snapshot)


# 4. Claude cannot perform or claim operational execution
def test_phase15_claude_cannot_execute_reroute():
    service = ClaudeDecisionExplanationService()
    decision = _sample_decision_result()
    snapshot = service.build_snapshot(decision=decision)

    explanation = ClaudeDecisionExplanation(
        summary="Shipment shp_100 was rerouted the shipment by the agent.",
        decision_purpose="Authoritative decision review.",
        decision_type_statement="Decision type is REROUTE_SHIPMENT.",
        selected_candidate_explanation="Preferred candidate is cand_opt_1.",
        candidate_tradeoffs=[],
        approval_requirement_statement="Human approval is required before execution.",
        scenario_relationship="Scenario verified.",
        risk_relationship="Risk verified.",
        prediction_relationship="Prediction verified.",
        constraint_explanations=[],
        uncertainty_and_gaps="None.",
        limitations=[],
        citations=["doc_corridor_audit#c1"],
    )

    with pytest.raises(DecisionExecutionViolationError):
        service.validate_consistency(explanation, snapshot)


# 5. Failure isolation: Claude timeouts or errors do NOT invalidate authoritative DecisionResult
def test_phase15_claude_failure_isolation():
    service = ClaudeDecisionExplanationService()
    decision = _sample_decision_result()

    # Mock invoke_structured to raise a timeout exception
    service._invocation_service.invoke_structured = MagicMock(side_effect=TimeoutError("Bedrock request timed out after 30s"))

    # Execute should NOT raise; it should return an UNAVAILABLE result gracefully
    res = service.execute(decision=decision, fail_closed=False)
    assert res.status == DecisionExplanationStatus.UNAVAILABLE
    assert "timed out" in res.summary
    assert decision.status == DecisionStatus.RECOMMENDED.value
    assert decision.selected_alternative_id == "cand_opt_1"


# 6. Multi-tenant citation rejection: cross-tenant citation rejected
def test_phase15_claude_cross_tenant_citation_rejected():
    service = ClaudeDecisionExplanationService()
    decision = _sample_decision_result(org_id="tenant_alpha")
    snapshot = service.build_snapshot(decision=decision)

    explanation = ClaudeDecisionExplanation(
        summary="Summary citing foreign tenant.",
        decision_purpose="Review.",
        decision_type_statement="REROUTE_SHIPMENT.",
        selected_candidate_explanation="Candidate cand_opt_1.",
        candidate_tradeoffs=[],
        approval_requirement_statement="Human approval is required before execution.",
        scenario_relationship="Scenario verified.",
        risk_relationship="Risk verified.",
        prediction_relationship="Prediction verified.",
        constraint_explanations=[],
        uncertainty_and_gaps="None.",
        limitations=[],
        citations=["org_foreign_beta:doc_999"],  # Cross-tenant citation!
    )

    with pytest.raises(DecisionExplanationCitationIntegrityError, match="Cross-tenant citation"):
        service.validate_citations(explanation, snapshot)
