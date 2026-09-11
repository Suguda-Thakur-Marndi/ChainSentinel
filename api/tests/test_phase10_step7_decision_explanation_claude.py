"""Comprehensive focused test suite for Phase 10 Step 7: Claude Decision Analysis & Explanation Layer.

Covers:
A. Decision explanation contract (immutability, extra="forbid", validation of fields)
B. Immutable snapshot (creation, deepcopy/frozen, field mapping from DecisionResult)
C. Candidate & Action authority (Claude cannot alter selected candidate or candidate set)
D. Approval boundary (rejection of approved claims, waiving approval, bypassing approval)
E. Execution boundary (rejection of shipment reroutes, PO issuance, carrier dispatch)
F. Optimization-output rejection (fabricated OR-Tools, simplex, MIP, linear programming claims)
G. Quantitative hallucination protection (detect and reject fabricated savings, costs, ROI, probabilities)
H. Prompt generation (structure, XML sections, system prompt, tags)
I. Prompt determinism (reproducible hashes, version stability, fingerprint invariance)
J. System prompt protection & Injection handling (anti-override, data isolation)
K. Citation integrity & Tenant isolation (cross-tenant decision, scenario, risk, prediction, evidence rejected)
L. Grounding validation (ungrounded entities or rationales detected and rejected)
M. Status contradiction handling (authoritative BLOCKED, INVALID, INSUFFICIENT_EVIDENCE cannot be called actionable)
N. Upstream integration (honesty when scenario/prediction is unavailable)
O. Output mapping & deterministic fingerprinting
P. Failure isolation (timeouts, errors, contradictions - authoritative DecisionResult remains intact)
Q. Mock provider integration (DeterministicMockLLMProvider valid, malformed, empty, throttled responses)
R. LangGraph node integration & State ownership (decision_explanation owned by DECISION stage)
S. Audit trail (DECISION_LLM_EXPLANATION_STARTED/SUCCEEDED/FAILED/REJECTED events)
T. Critical Mandatory Security Invariants (Prompt Sections 20-30, Invariants 1-17)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import pytest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from app.agents.contracts import (
    AgentGraphState,
    AgentGraphStateDict,
    AgentLimitation,
    AgentStage,
    LimitationCategory,
    ToolSideEffectType,
    validate_state_update,
)
from app.agents.decision.agent import DecisionAgent
from app.agents.decision.claude_contract import (
    ClaudeCandidateTradeoff,
    ClaudeDecisionExplanation,
    DecisionCandidateExplanationInput,
    DecisionConstraintExplanationInput,
    DecisionExplanationInput,
    DecisionExplanationResult,
    DecisionExplanationStatus,
    DecisionRationaleExplanationInput,
    compute_decision_explanation_fingerprint,
)
from app.agents.decision.claude_service import (
    ClaudeDecisionExplanationService,
    DECISION_EXPLANATION_PROMPT_VERSION,
    MAX_DECISION_EXPLANATION_CONTEXT_CHARS,
)
from app.agents.decision.contract import (
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
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
    DecisionExplanationError,
    DecisionExplanationGroundingError,
    DecisionExplanationLLMError,
    DecisionOptionFabricationError,
    DecisionOptimizationFabricationError,
    DecisionQuantitativeFabricationError,
    DecisionStatusContradictionError,
    DecisionTenantIsolationError,
    DecisionValueContradictionError,
)
from app.agents.decision.node import (
    DECISION_NODE_CONTRACT,
    _emit_decision_audit,
    decision_node,
)
from app.agents.errors import (
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentValidationError,
)
from app.agents.prediction.contract import (
    ModelMetadata,
    PredictionResult,
    PredictionStatus,
)
from app.agents.research.contract import (
    FindingType,
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
)
from app.agents.risk.contract import (
    RiskAgentRequest,
    RiskAgentResult,
)
from app.agents.scenario.contract import (
    ScenarioDefinition,
    ScenarioParameter,
    ScenarioResult,
    ScenarioType,
)
from app.llm.contracts import LLMResponse, TokenUsage
from app.llm.errors import LLMProviderError, LLMTimeoutError, LLMValidationError
from app.llm.mock import DeterministicMockLLMProvider
from app.llm.prompts import ClaudePrompt
from app.rag.contracts import RAGContextCitation, RAGEvidenceBundle, RAGEvidenceItem
from app.risk_engine.contract import (
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def org_id() -> str:
    return "org_acme_corp"


@pytest.fixture
def sample_constraints() -> List[DecisionConstraint]:
    return [
        DecisionConstraint(
            constraint_type="BUDGET",
            name="max_expedited_budget",
            value=15000.0,
            unit="USD",
        ),
        DecisionConstraint(
            constraint_type="POLICY",
            name="carrier_compliance_policy",
            value="approved_tier_1_only",
            unit=None,
        ),
    ]


@pytest.fixture
def sample_candidates(sample_constraints: List[DecisionConstraint]) -> List[DecisionCandidate]:
    return [
        DecisionCandidate(
            candidate_id="cand_expedite_air",
            action_type="EXPEDITE_AIR_FREIGHT",
            title="Expedite critical component via air freight",
            description="Re-route batch #412 via charter cargo flight to avoid plant shutdown.",
            priority="HIGH",
            status="REQUIRES_APPROVAL",
            requires_human_approval=True,
            parameters={"carrier": "AirCargoCorp", "cost_estimate": 12000.0, "transit_hours": 18.0},
            prerequisites=["budget_approval", "carrier_booking"],
            constraints=sample_constraints,
            expected_effect="Eliminates 72-hour delay at warehouse.",
            evidence_references=["ev_supplier_delay_01", "ev_flight_schedule_02"],
        ),
        DecisionCandidate(
            candidate_id="cand_safety_stock",
            action_type="DRAW_DOWN_SAFETY_STOCK",
            title="Draw down regional safety stock",
            description="Utilize buffer stock at distribution center Beta to maintain production rate.",
            priority="MEDIUM",
            status="REQUIRES_APPROVAL",
            requires_human_approval=True,
            parameters={"distribution_center": "DC_Beta", "units_to_pull": 500},
            prerequisites=["inventory_verification"],
            constraints=[],
            expected_effect="Prevents stockout for 48 hours.",
            evidence_references=["ev_inventory_report_03"],
        ),
    ]


@pytest.fixture
def sample_rationales() -> List[DecisionRationale]:
    return [
        DecisionRationale(
            basis_type=DecisionBasis.SCENARIO,
            source_reference="scen_42",
            evidence_references=["ev_supplier_delay_01"],
            rule_id="RULE_PREFER_AIR_EXPEDITE",
            finding_ids=["find_delay_01"],
            explanation_code="AIR_EXPEDITE_VIABLE",
        ),
        DecisionRationale(
            basis_type=DecisionBasis.RISK_ASSESSMENT,
            source_reference="risk_ass_87",
            evidence_references=["ev_supplier_delay_01", "ev_flight_schedule_02"],
            rule_id="RULE_CRITICAL_RISK_MITIGATION",
            finding_ids=["find_risk_high"],
            explanation_code="HIGH_RISK_MITIGATION_REQUIRED",
        ),
    ]


@pytest.fixture
def sample_decision_result(
    org_id: str,
    sample_candidates: List[DecisionCandidate],
    sample_constraints: List[DecisionConstraint],
    sample_rationales: List[DecisionRationale],
) -> DecisionResult:
    fp = compute_decision_fingerprint(
        organization_id=org_id,
        decision_type="OPERATIONAL_REVIEW",
        target_reference="shipment_999",
        candidates=[c.model_dump() for c in sample_candidates],
        constraints=[con.model_dump() for con in sample_constraints],
        rationales=[r.model_dump() for r in sample_rationales],
        scenario_id="scen_42",
    )
    return DecisionResult(
        decision_id="dec_00000000-0000-0000-0000-000000000001",
        organization_id=org_id,
        decision_type=DecisionType.OPERATIONAL_REVIEW,
        status="REQUIRES_APPROVAL",
        candidates=sample_candidates,
        preferred_candidate=sample_candidates[0],
        preferred_candidate_id=sample_candidates[0].candidate_id,
        scenario_id="scen_42",
        risk_assessment_id="risk_ass_87",
        prediction_id="pred_delay_12",
        planning_horizon_hours=24.0,
        rationales=sample_rationales,
        constraints=sample_constraints,
        requires_human_approval=True,
        evidence_references=["ev_supplier_delay_01", "ev_flight_schedule_02", "ev_inventory_report_03"],
        limitations=[
            AgentLimitation(
                limitation_id="lim_01",
                category=LimitationCategory.HIGH_UNCERTAINTY,
                description="Air freight capacity subject to weather clearance.",
            )
        ],
        fingerprint=fp,
    )


@pytest.fixture
def valid_claude_decision_explanation_dict(sample_candidates: List[DecisionCandidate]) -> Dict[str, Any]:
    return {
        "summary": "Authoritative decision analysis recommends expedited air freight to mitigate plant shutdown risk.",
        "decision_purpose": "Formulates candidate responses for shipment disruption on lane Pacific-1.",
        "decision_type_statement": "Authoritative decision type is OPERATIONAL_REVIEW.",
        "selected_candidate_explanation": "Preferred candidate is cand_expedite_air (EXPEDITE_AIR_FREIGHT) to rapidly eliminate delay.",
        "candidate_tradeoffs": [
            {
                "candidate_id": "cand_expedite_air",
                "action_type": "EXPEDITE_AIR_FREIGHT",
                "pros": ["Fastest recovery", "resolves delay in 18 hours"],
                "cons": ["Higher operational expenditure within budget cap"],
                "operational_impact": "Prevents downstream line shutdown; preserves production target.",
            },
            {
                "candidate_id": "cand_safety_stock",
                "action_type": "DRAW_DOWN_SAFETY_STOCK",
                "pros": ["Zero direct freight cost"],
                "cons": ["Depletes regional buffer for subsequent orders"],
                "operational_impact": "Maintains production rate for 48 hours.",
            },
        ],
        "approval_requirement_statement": "Human approval is required before execution. Expedited booking cannot be dispatched autonomously.",
        "scenario_relationship": "Addresses the scenario of supplier delay on lane Pacific-1.",
        "risk_relationship": "Mitigates critical supply chain risk assessment finding.",
        "prediction_relationship": "Aligned with upstream delay forecast of 72 hours.",
        "constraint_explanations": ["Budget cap of $15,000 USD is respected ($12,000 cost)."],
        "uncertainty_and_gaps": "Air freight capacity subject to carrier booking confirmation and weather clearance.",
        "limitations": [
            "Air freight capacity subject to weather clearance.",
        ],
        "citations": [
            "dec_00000000-0000-0000-0000-000000000001",
            "cand_expedite_air",
            "ev_supplier_delay_01",
            "ev_flight_schedule_02",
        ],
        "candidate_references": ["cand_expedite_air", "cand_safety_stock"],
        "evidence_references": ["ev_supplier_delay_01", "ev_flight_schedule_02"],
        "prediction_references": ["pred_delay_12"],
        "risk_references": ["risk_ass_87"],
        "scenario_references": ["scen_42"],
    }


# ==============================================================================
# SECTION A: Decision Explanation Input Contract & Immutability
# ==============================================================================

class TestDecisionExplanationContract:
    def test_input_snapshot_immutability(self, sample_decision_result: DecisionResult) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        assert snapshot.decision_id == sample_decision_result.decision_id
        assert snapshot.organization_id == sample_decision_result.organization_id
        assert snapshot.preferred_candidate_id == "cand_expedite_air"
        assert len(snapshot.candidates) == 2

        # Verify frozen / extra forbid
        with pytest.raises(ValidationError):
            snapshot.decision_id = "dec_mutated"  # type: ignore

    def test_input_extra_forbid(self, org_id: str) -> None:
        with pytest.raises(ValidationError):
            DecisionExplanationInput(
                decision_id="dec_test",
                organization_id=org_id,
                decision_type="OPERATIONAL_REVIEW",
                status="REQUIRES_APPROVAL",
                requires_human_approval=True,
                preferred_candidate_id=None,
                preferred_candidate=None,
                candidates=[],
                constraints=[],
                rationales=[],
                decision_fingerprint="fp_test",
                unauthorized_extra_field="malicious",  # type: ignore
            )

    def test_output_schema_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            ClaudeDecisionExplanation(
                summary="Valid summary",
                decision_purpose="Valid purpose",
                decision_type_statement="Valid type",
                selected_candidate_explanation="Valid sel",
                candidate_tradeoffs=[],
                approval_requirement_statement="Req",
                scenario_relationship="Scen",
                risk_relationship="Risk",
                prediction_relationship="Pred",
                uncertainty_and_gaps="Gaps",
                citations=[],
                injected_extra_data="attack",  # type: ignore
            )


# ==============================================================================
# SECTION B: Prompt Generation, XML Tags & Context Budgeting
# ==============================================================================

class TestDecisionPromptGeneration:
    def test_prompt_xml_delimiters_and_version(self, sample_decision_result: DecisionResult) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)
        prompt = service.build_explanation_prompt(snapshot=snapshot)

        assert prompt.version == DECISION_EXPLANATION_PROMPT_VERSION
        system_text = prompt.system_instruction
        assert "NEVER APPROVE DECISIONS" in system_text
        assert "NEVER EXECUTE ACTIONS" in system_text
        assert "NEVER ALTER DECISION CANDIDATES" in system_text
        assert "NEVER FABRICATE OPTIMIZATION" in system_text

        prompt_str = prompt.messages[0].content
        assert "<authoritative_decision>" in prompt_str
        assert "</authoritative_decision>" in prompt_str

    def test_context_budget_exceeded_raises_error(self, sample_decision_result: DecisionResult) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        # Inject massive objective exceeding 120k chars
        huge_objective = "A" * (MAX_DECISION_EXPLANATION_CONTEXT_CHARS + 5000)
        huge_snapshot = snapshot.model_copy(update={"objective": huge_objective})

        with pytest.raises(DecisionExplanationLLMError) as exc_info:
            service.build_explanation_prompt(snapshot=huge_snapshot)
        assert "exceeds maximum allowed context budget limit" in str(exc_info.value)


# ==============================================================================
# SECTION C: Candidate & Action Authority (Claude cannot alter selected option)
# ==============================================================================

class TestCandidateAuthority:
    def test_selected_candidate_contradiction_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        # Contradict preferred candidate in narrative
        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["selected_candidate_explanation"] = "The selected candidate is cand_safety_stock."  # Auth is cand_expedite_air
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionCandidateContradictionError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "contradicting authoritative preferred candidate" in str(exc_info.value)

    def test_selected_action_contradiction_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["candidate_tradeoffs"] = [
            {
                "candidate_id": "cand_expedite_air",
                "action_type": "CANCEL_ORDER",  # Auth action is EXPEDITE_AIR_FREIGHT
                "pros": ["Saves cash"],
                "cons": ["Stops production"],
                "operational_impact": "Impact",
            }
        ]
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionActionContradictionError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "contradicts authoritative action" in str(exc_info.value)

    def test_nonexistent_candidate_id_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["candidate_references"] = ["cand_invented_999"]
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionOptionFabricationError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "references non-existent candidate_id" in str(exc_info.value)

    def test_tradeoff_with_nonexistent_candidate_id_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["candidate_tradeoffs"] = [
            {
                "candidate_id": "cand_ghost_candidate",
                "action_type": "EXPEDITE_AIR_FREIGHT",
                "pros": ["Fast"],
                "cons": ["Expensive"],
                "operational_impact": "Impact",
            }
        ]
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionOptionFabricationError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "references non-existent candidate_id" in str(exc_info.value)


# ==============================================================================
# SECTION D: Approval Boundary Enforcement (Mandatory Section 21)
# ==============================================================================

class TestApprovalBoundary:
    @pytest.mark.parametrize(
        "violating_phrase",
        [
            "The decision is approved.",
            "I approve this action immediately.",
            "Approval is granted by the system.",
            "Bypassing human approval due to high urgency.",
            "No human approval is required for this case.",
            "Action was automatically approved.",
            "Waiving approval requirement per policy.",
            "Approval status is approved.",
        ],
    )
    def test_approval_claims_raise_approval_violation(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
        violating_phrase: str,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["approval_requirement_statement"] = f"Proceed right away. {violating_phrase}"
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionApprovalViolationError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "violates human approval boundary" in str(exc_info.value)


# ==============================================================================
# SECTION E: Execution Boundary Enforcement (Mandatory Section 22)
# ==============================================================================

class TestExecutionBoundary:
    @pytest.mark.parametrize(
        "violating_phrase",
        [
            "We have rerouted the shipment to Chicago.",
            "The system dispatched the carrier already.",
            "Action has been executed and confirmed.",
            "Issued the purchase order to vendor Alpha.",
            "Order was cancelled per operational instructions.",
            "Carrier has been contacted and vessel rebooked.",
            "Transferred the inventory to warehouse Beta.",
            "Operational command dispatched to port authorities.",
        ],
    )
    def test_execution_claims_raise_execution_violation(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
        violating_phrase: str,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["decision_purpose"] = f"Immediate operational status: {violating_phrase}"
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionExecutionViolationError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "violates operational execution boundary" in str(exc_info.value)


# ==============================================================================
# SECTION F: Optimization-Output Rejection (Mandatory Section 20)
# ==============================================================================

class TestOptimizationFabricationDefense:
    @pytest.mark.parametrize(
        "violating_phrase",
        [
            "Solved via OR-Tools integer program.",
            "Calculated globally optimal solution using simplex algorithm.",
            "Mathematical optimization objective achieved value 98.4.",
            "Executed optimal route solver with mixed-integer programming.",
            "Pareto frontier algorithm determined the optimal trade-off.",
        ],
    )
    def test_optimization_claims_raise_error(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
        violating_phrase: str,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["decision_purpose"] = f"Evaluation approach: {violating_phrase}"
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionOptimizationFabricationError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "fabricates mathematical optimization claim" in str(exc_info.value)


# ==============================================================================
# SECTION G: Quantitative Hallucination Defense (Mandatory Section 23)
# ==============================================================================

class TestQuantitativeHallucinationDefense:
    @pytest.mark.parametrize(
        "violating_phrase",
        [
            "Yields estimated savings of $45,000 for the quarter.",
            "Saved $120,000 in operational downtime.",
            "Delivers an ROI of 340% over standard logistics.",
            "Probability of success is 96.5% under this routing.",
        ],
    )
    def test_ungrounded_financial_or_probability_claims_raise_error(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
        violating_phrase: str,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["decision_purpose"] = f"Expected performance: {violating_phrase}"
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionQuantitativeFabricationError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "fabricates ungrounded quantitative claim" in str(exc_info.value)


# ==============================================================================
# SECTION H: Status Contradiction Defense
# ==============================================================================

class TestStatusContradictionDefense:
    def test_blocked_status_cannot_be_called_ready_or_recommended(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        blocked_decision = sample_decision_result.model_copy(update={"status": "BLOCKED"})
        snapshot = service.build_snapshot(decision=blocked_decision)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["summary"] = "Decision is ready for execution without hurdles."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionStatusContradictionError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "asserts decision is viable/actionable" in str(exc_info.value)


# ==============================================================================
# SECTION I: Upstream Prediction & Scenario Grounding
# ==============================================================================

class TestUpstreamGroundingDefense:
    def test_prediction_delay_fabrication_when_prediction_unavailable_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        # Set prediction_id to None and prediction_status to NOT_AVAILABLE
        no_pred_decision = sample_decision_result.model_copy(update={"prediction_id": None})
        snapshot = service.build_snapshot(decision=no_pred_decision)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["prediction_relationship"] = "The predicted delay of 48.0 hours was factored into this choice."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionExplanationGroundingError) as exc_info:
            service.validate_consistency(explanation, snapshot)
        assert "fabricates authoritative prediction value" in str(exc_info.value)


# ==============================================================================
# SECTION J: Citation Integrity & Tenant Isolation
# ==============================================================================

class TestCitationIntegrityAndTenantIsolation:
    def test_valid_citations_pass(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)
        explanation = ClaudeDecisionExplanation.model_validate(valid_claude_decision_explanation_dict)

        # Should not raise
        service.validate_citations(explanation, snapshot)

    def test_invented_citation_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["citations"] = ["ev_completely_invented_citation_999"]
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionExplanationCitationIntegrityError) as exc_info:
            service.validate_citations(explanation, snapshot)
        assert "cites non-existent evidence or citation" in str(exc_info.value)

    def test_cross_tenant_citation_rejected(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["citations"] = ["org_foreign_corp:ev_foreign_evidence_123"]
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionExplanationCitationIntegrityError) as exc_info:
            service.validate_citations(explanation, snapshot)
        assert "Cross-tenant citation detected" in str(exc_info.value)

    def test_cross_tenant_upstream_scenario_fails_closed(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        foreign_scenario = {
            "scenario_id": "scen_foreign",
            "organization_id": "org_foreign_corp",
        }
        with pytest.raises(DecisionTenantIsolationError) as exc_info:
            service.build_snapshot(
                decision=sample_decision_result,
                scenario_result=foreign_scenario,
            )
        assert "Cross-tenant scenario detected" in str(exc_info.value)

    def test_cross_tenant_upstream_risk_fails_closed(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        foreign_risk = {
            "assessment_id": "risk_foreign",
            "organization_id": "org_foreign_corp",
        }
        with pytest.raises(DecisionTenantIsolationError) as exc_info:
            service.build_snapshot(
                decision=sample_decision_result,
                risk_assessment=foreign_risk,
            )
        assert "Cross-tenant risk assessment detected" in str(exc_info.value)

    def test_cross_tenant_upstream_prediction_fails_closed(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        foreign_pred = {
            "prediction_id": "pred_foreign",
            "organization_id": "org_foreign_corp",
        }
        with pytest.raises(DecisionTenantIsolationError) as exc_info:
            service.build_snapshot(
                decision=sample_decision_result,
                prediction_result=foreign_pred,
            )
        assert "Cross-tenant prediction detected" in str(exc_info.value)


# ==============================================================================
# SECTION K: Output Mapping & Fingerprint Reproducibility
# ==============================================================================

class TestOutputMappingAndFingerprint:
    def test_mapping_produces_valid_result(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)
        explanation = ClaudeDecisionExplanation.model_validate(valid_claude_decision_explanation_dict)

        res = service.map_to_explanation_result(
            claude_explanation=explanation,
            snapshot=snapshot,
            status=DecisionExplanationStatus.AVAILABLE,
            latency_ms=45.2,
        )

        assert res.decision_id == sample_decision_result.decision_id
        assert res.status == DecisionExplanationStatus.AVAILABLE
        assert res.fingerprint is not None
        assert len(res.fingerprint) == 64

    def test_fingerprint_deterministic_and_invariant_to_time(self) -> None:
        fp1 = compute_decision_explanation_fingerprint(
            decision_id="dec_123",
            organization_id="org_test",
            summary="Decision summary text",
            citations=["ev_1", "ev_2"],
            preferred_candidate_id="cand_1",
        )
        fp2 = compute_decision_explanation_fingerprint(
            decision_id="dec_123",
            organization_id="org_test",
            summary="Decision summary text",
            citations=["ev_2", "ev_1"],  # Order permutation
            preferred_candidate_id="cand_1",
        )
        assert fp1 == fp2


# ==============================================================================
# SECTION L: Deterministic Mock Provider & Failure Isolation
# ==============================================================================

class TestMockProviderAndFailureIsolation:
    def test_successful_execution_with_deterministic_mock(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        mock_provider = DeterministicMockLLMProvider(
            canned_response=json.dumps(valid_claude_decision_explanation_dict)
        )
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)

        result = service.execute(decision=sample_decision_result, fail_closed=True)
        assert result.status == DecisionExplanationStatus.AVAILABLE
        assert "Authoritative decision analysis" in result.summary

    def test_llm_timeout_fail_closed_raises_error(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        mock_provider = DeterministicMockLLMProvider()
        mock_provider.simulate_timeout(delay_seconds=0.01)
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)

        with pytest.raises(DecisionExplanationLLMError):
            service.execute(decision=sample_decision_result, fail_closed=True)

    def test_llm_timeout_node_mode_isolates_failure(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        mock_provider = DeterministicMockLLMProvider()
        mock_provider.simulate_timeout(delay_seconds=0.01)
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)

        # In node execution mode: fail_closed=False
        result = service.execute(decision=sample_decision_result, fail_closed=False)
        assert result.status == DecisionExplanationStatus.UNAVAILABLE
        assert "unavailable" in result.summary.lower()
        # Authoritative decision result was untouched!
        assert sample_decision_result.status == "REQUIRES_APPROVAL"
        assert len(sample_decision_result.candidates) == 2

    def test_malformed_json_isolates_failure(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        mock_provider = DeterministicMockLLMProvider(
            canned_response="This is plain prose, not valid JSON at all."
        )
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)

        result = service.execute(decision=sample_decision_result, fail_closed=False)
        assert result.status == DecisionExplanationStatus.UNAVAILABLE

    def test_contradiction_node_mode_returns_invalid_status(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["approval_requirement_statement"] = "The decision is approved by Claude."
        mock_provider = DeterministicMockLLMProvider(
            canned_response=json.dumps(bad_dict)
        )
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)

        # In node execution mode: fail_closed=False -> status INVALID
        result = service.execute(decision=sample_decision_result, fail_closed=False)
        assert result.status == DecisionExplanationStatus.INVALID
        assert "rejected" in result.summary.lower()


# ==============================================================================
# SECTION M: LangGraph Node Integration & State Ownership
# ==============================================================================

class TestDecisionNodeIntegration:
    def test_decision_node_contract_and_state_ownership(self) -> None:
        assert "decision_explanation" in DECISION_NODE_CONTRACT.output_keys
        assert DECISION_NODE_CONTRACT.stage == AgentStage.DECISION
        assert DECISION_NODE_CONTRACT.is_side_effecting is False

    def test_decision_node_with_claude_success(
        self,
        org_id: str,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        mock_provider = DeterministicMockLLMProvider(
            canned_response=json.dumps(valid_claude_decision_explanation_dict)
        )
        state: AgentGraphStateDict = {
            "organization_id": org_id,
            "run_id": "run_test_01",
            "actor_id": "analyst_alice",
            "request_id": "req_test_01",
            "correlation_id": "corr_test_01",
            "trace_id": "trace_test_01",
            "objective": "Resolve component bottleneck",
            "scenario_id": "scen_42",
            "risk_assessment_id": "risk_ass_87",
            "evidence_references": ["ev_supplier_delay_01"],
            "llm_provider": mock_provider,
            "use_claude": True,
        }

        # Mock DecisionAgent to return sample_decision_result
        with patch.object(
            DecisionAgent,
            "execute",
            return_value=(sample_decision_result, []),
        ):
            update = decision_node(state)

        assert "decision_explanation" in update
        assert update["decision_explanation"] is not None
        assert update["decision_explanation"]["status"] == "AVAILABLE"
        assert update["decision_result"]["decision_id"] == sample_decision_result.decision_id

    def test_decision_node_with_claude_failure_preserves_decision(
        self,
        org_id: str,
        sample_decision_result: DecisionResult,
    ) -> None:
        mock_provider = DeterministicMockLLMProvider()
        mock_provider.simulate_timeout(delay_seconds=0.01)
        state: AgentGraphStateDict = {
            "organization_id": org_id,
            "run_id": "run_test_01",
            "actor_id": "analyst_alice",
            "objective": "Resolve bottleneck",
            "llm_provider": mock_provider,
            "use_claude": True,
        }

        with patch.object(
            DecisionAgent,
            "execute",
            return_value=(sample_decision_result, []),
        ):
            update = decision_node(state)

        # Authoritative decision survived intact!
        assert update["decision_id"] == sample_decision_result.decision_id
        assert update["decision_result"]["status"] == "REQUIRES_APPROVAL"
        assert update["decision_explanation"]["status"] == "UNAVAILABLE"
        assert any("Decision explanation unavailable" in w for w in update["warnings"])


# ==============================================================================
# SECTION N: Audit Event Emission (Mandatory Section 29)
# ==============================================================================

class TestDecisionAuditEventEmission:
    def test_audit_event_emission_started_and_succeeded(
        self,
        org_id: str,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        mock_provider = DeterministicMockLLMProvider(
            canned_response=json.dumps(valid_claude_decision_explanation_dict)
        )
        state: AgentGraphStateDict = {
            "organization_id": org_id,
            "run_id": "run_test_01",
            "objective": "Resolve bottleneck",
            "llm_provider": mock_provider,
            "use_claude": True,
        }

        with patch("app.agents.decision.node._emit_decision_audit") as mock_audit:
            with patch.object(DecisionAgent, "execute", return_value=(sample_decision_result, [])):
                decision_node(state)

            actions = [call[1]["action"] for call in mock_audit.call_args_list]
            assert "DECISION_LLM_EXPLANATION_STARTED" in actions
            assert "DECISION_LLM_EXPLANATION_SUCCEEDED" in actions

    def test_audit_event_emission_rejected(
        self,
        org_id: str,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["approval_requirement_statement"] = "The decision is approved by Claude."
        mock_provider = DeterministicMockLLMProvider(
            canned_response=json.dumps(bad_dict)
        )
        state: AgentGraphStateDict = {
            "organization_id": org_id,
            "run_id": "run_test_01",
            "objective": "Resolve bottleneck",
            "llm_provider": mock_provider,
            "use_claude": True,
        }

        with patch("app.agents.decision.node._emit_decision_audit") as mock_audit:
            with patch.object(DecisionAgent, "execute", return_value=(sample_decision_result, [])):
                decision_node(state)

            actions = [call[1]["action"] for call in mock_audit.call_args_list]
            assert "DECISION_LLM_EXPLANATION_STARTED" in actions
            assert "DECISION_LLM_EXPLANATION_REJECTED" in actions


# ==============================================================================
# SECTION O: Mandatory Security Invariants (Section 36, Checks 1-17)
# ==============================================================================

class TestMandatorySecurityInvariants:
    def test_invariant_1_claude_cannot_change_authoritative_decision(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 1: Claude cannot change authoritative decision."""
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["selected_candidate_explanation"] = "The preferred candidate is cand_safety_stock."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionCandidateContradictionError):
            service.validate_consistency(explanation, snapshot)
        # Authoritative decision preferred candidate remains cand_expedite_air
        assert sample_decision_result.preferred_candidate_id == "cand_expedite_air"

    def test_invariant_4_claude_cannot_fabricate_optimization_values(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 7: Claude cannot fabricate optimization values."""
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["decision_purpose"] = "Calculated optimal candidate using OR-Tools simplex."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionOptimizationFabricationError):
            service.validate_consistency(explanation, snapshot)

    def test_invariant_8_claude_cannot_fabricate_business_impact(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 8: Claude cannot fabricate business impact / savings."""
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["decision_purpose"] = "Delivers projected savings of $500,000 across the network."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionQuantitativeFabricationError):
            service.validate_consistency(explanation, snapshot)

    def test_invariant_9_claude_cannot_approve_decision(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 9: Claude cannot approve a decision."""
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["approval_requirement_statement"] = "This decision is approved for immediate implementation."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionApprovalViolationError):
            service.validate_consistency(explanation, snapshot)

    def test_invariant_10_claude_cannot_execute_an_action(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 10: Claude cannot execute an action."""
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["decision_purpose"] = "Action has been executed and carrier rerouted."
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionExecutionViolationError):
            service.validate_consistency(explanation, snapshot)

    def test_invariant_11_claude_cannot_use_another_tenant_evidence(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 11: Claude cannot use another tenant's evidence."""
        service = ClaudeDecisionExplanationService(llm_provider=DeterministicMockLLMProvider())
        snapshot = service.build_snapshot(decision=sample_decision_result)

        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["citations"] = ["org_competitor:ev_stolen_data"]
        explanation = ClaudeDecisionExplanation.model_validate(bad_dict)

        with pytest.raises(DecisionExplanationCitationIntegrityError):
            service.validate_citations(explanation, snapshot)

    def test_invariant_15_claude_timeout_cannot_invalidate_authoritative_state(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        """Invariant 15: Claude timeout cannot invalidate authoritative state."""
        mock_provider = DeterministicMockLLMProvider()
        mock_provider.simulate_timeout(delay_seconds=0.01)
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)
        res = service.execute(decision=sample_decision_result, fail_closed=False)

        assert res.status == DecisionExplanationStatus.UNAVAILABLE
        # Authoritative decision is unaffected
        assert sample_decision_result.status == "REQUIRES_APPROVAL"
        assert sample_decision_result.preferred_candidate_id == "cand_expedite_air"

    def test_invariant_16_malformed_output_cannot_invalidate_authoritative_state(
        self,
        sample_decision_result: DecisionResult,
    ) -> None:
        """Invariant 16: Malformed Claude output cannot invalidate authoritative state."""
        mock_provider = DeterministicMockLLMProvider(
            canned_response="<<<corrupt data null byte>>>"
        )
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)
        res = service.execute(decision=sample_decision_result, fail_closed=False)

        assert res.status == DecisionExplanationStatus.UNAVAILABLE
        assert sample_decision_result.decision_id == "dec_00000000-0000-0000-0000-000000000001"

    def test_invariant_17_contradictory_output_cannot_overwrite_authoritative_state(
        self,
        sample_decision_result: DecisionResult,
        valid_claude_decision_explanation_dict: Dict[str, Any],
    ) -> None:
        """Invariant 17: Contradictory Claude output cannot overwrite authoritative state."""
        bad_dict = dict(valid_claude_decision_explanation_dict)
        bad_dict["selected_candidate_explanation"] = "The selected candidate is cand_safety_stock."
        mock_provider = DeterministicMockLLMProvider(
            canned_response=json.dumps(bad_dict)
        )
        service = ClaudeDecisionExplanationService(llm_provider=mock_provider)
        res = service.execute(decision=sample_decision_result, fail_closed=False)

        assert res.status == DecisionExplanationStatus.INVALID
        # The authoritative decision still has cand_expedite_air as preferred candidate!
        assert sample_decision_result.preferred_candidate_id == "cand_expedite_air"
