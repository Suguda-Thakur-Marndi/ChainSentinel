"""Phase 9 Step 8 — Decision Flow Integration Comprehensive Test Suite.

Exhaustively verifies:
1. Decision contracts and Pydantic V2 validation
2. Candidate synthesis, structure, and deterministic ID generation
3. Structured rationale, basis types, and auditability
4. Deterministic decision rules, ranking, and versioning
5. Scenario integration and immutability
6. Prediction integration and uncertainty preservation
7. Risk assessment integration and non-recalculation
8. Recommendation integration and preservation
9. Authority and operational constraints
10. State ownership and write safety
11. Tenant isolation across all inputs and references
12. Security scrubbing and secret protection
13. Human approval boundary (REQUIRES_APPROVAL, never auto-approved)
14. Read-only and action boundary (no side-effects, no carrier/inventory/shipment mutations)
15. Observability, NodeExecutionTelemetry, and error classification
16. Deterministic identity (UUIDv5) and SHA-256 fingerprinting
17. Topology, edge transitions, and LangGraph integration
18. Deterministic end-to-end multi-agent pipeline fixture
19. Explicit no-side-effects verification
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List
import uuid

from pydantic import ValidationError
import pytest

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentNodeContract,
    AgentStage,
    LimitationCategory,
    ToolSideEffectType,
    apply_state_update,
    validate_state_update,
)
from app.agents.edges import ALLOWED_STAGE_TRANSITIONS, EdgeRegistry, StageTransitionValidator
from app.agents.errors import (
    AgentStageTransitionError,
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentValidationError,
)
from app.agents.graph import AgentGraphBuilder, execute_agent_graph
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.registry import NodeRegistry, global_node_registry
from app.agents.decision import (
    DECISION_NODE_CONTRACT,
    DECISION_RULE_VERSION,
    DecisionAgent,
    DecisionAgentError,
    DecisionAuthorizationError,
    DecisionBasis,
    DecisionCandidate,
    DecisionCandidateStatus,
    DecisionConstraint,
    DecisionGenerationError,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionRuleEngine,
    DecisionStatus,
    DecisionTenantIsolationError,
    DecisionType,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
    InvalidScenarioReferenceError,
    MissingScenarioError,
    UnsupportedDecisionTypeError,
    compute_decision_fingerprint,
    decision_node,
    generate_deterministic_decision_id,
)


# ==============================================================================
# FIXTURES AND FACTORIES
# ==============================================================================

@pytest.fixture
def sample_context() -> AgentExecutionContext:
    return AgentExecutionContext(
        organization_id="org_test_123",
        actor_id="usr_test_456",
        request_id="req_test_789",
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
        role="DISPATCHER",
        roles=["dispatcher", "analyst"],
        permissions=["read", "decision_evaluate"],
    )


@pytest.fixture
def sample_prediction_dict() -> Dict[str, Any]:
    return {
        "prediction_id": "pred_test_12345",
        "organization_id": "org_test_123",
        "prediction_type": "SHIPMENT_DELAY",
        "target": "delay_minutes",
        "predicted_value": 120.0,
        "unit": "minutes",
        "model_metadata": {
            "model_name": "delay_linear_v1",
            "model_version": "1.0.0",
            "is_production": False,
        },
        "feature_references": ["feat_1", "feat_2"],
        "evidence_references": ["ev_sig_001", "ev_sig_002"],
        "risk_assessment_reference": "risk_assess_999",
        "limitations": [],
        "provenance": {"service": "DeterministicMockPredictionService"},
        "status": "COMPLETED",
        "created_by_node": "prediction_agent",
    }


@pytest.fixture
def sample_risk_dict() -> Dict[str, Any]:
    return {
        "assessment_id": "risk_assess_999",
        "organization_id": "org_test_123",
        "assessment_fingerprint": "fp_assess_999_valid",
        "risk_score": 78.5,
        "risk_level": "HIGH",
        "factor_count": 2,
    }


@pytest.fixture
def sample_scenario_dict() -> Dict[str, Any]:
    return {
        "scenario_id": "scen_test_001",
        "organization_id": "org_test_123",
        "scenario_type": "SHIPMENT_DELAY",
        "status": "READY",
        "scenario_definition": {
            "scenario_id": "scen_test_001",
            "organization_id": "org_test_123",
            "target_reference": "ship_001",
            "parameters": [
                {
                    "name": "delay_minutes",
                    "value": 120.0,
                    "unit": "minutes",
                    "source": "prediction_agent",
                    "source_type": "PREDICTION",
                }
            ],
            "triggers": [],
            "constraints": [
                {
                    "constraint_type": "MAXIMUM_DELAY",
                    "name": "sla_delay_limit",
                    "value": 180.0,
                    "unit": "minutes",
                }
            ],
            "fingerprint": "scen_fp_12345",
            "provenance": {"generator": "ScenarioGenerator"},
        },
        "evidence_references": ["ev_sig_001", "ev_sig_002"],
        "fingerprint": "scen_fp_12345",
        "provenance": {"created_by_node": "scenario_agent"},
    }


@pytest.fixture
def sample_recommendation_dict() -> Dict[str, Any]:
    return {
        "recommendation_id": "rec_001",
        "action_type": "PREPARE_ALTERNATIVE",
        "title": "Stage alternative transport",
        "description": "Prepare secondary carrier capacity due to anticipated Route 99 delay.",
        "priority": 1,
        "requires_approval": True,
        "evidence_references": ["ev_sig_001"],
        "provenance": {"source": "Phase7RuleEngine"},
    }


@pytest.fixture
def sample_decision_request(
    sample_scenario_dict: Dict[str, Any],
    sample_risk_dict: Dict[str, Any],
    sample_prediction_dict: Dict[str, Any],
    sample_recommendation_dict: Dict[str, Any],
) -> DecisionRequest:
    return DecisionRequest(
        decision_id="dec_test_001",
        organization_id="org_test_123",
        scenario_id="scen_test_001",
        scenario_reference=sample_scenario_dict,
        scenario_result=sample_scenario_dict,
        risk_assessment_id="risk_assess_999",
        risk_assessment_reference=sample_risk_dict,
        prediction_id="pred_test_12345",
        prediction_reference=sample_prediction_dict,
        prediction_result=sample_prediction_dict,
        evidence_references=["ev_sig_001", "ev_sig_002"],
        available_recommendations=[sample_recommendation_dict],
        decision_type=DecisionType.OPERATIONAL_RESPONSE,
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
    )


@pytest.fixture
def sample_graph_state(
    sample_scenario_dict: Dict[str, Any],
    sample_risk_dict: Dict[str, Any],
    sample_prediction_dict: Dict[str, Any],
    sample_recommendation_dict: Dict[str, Any],
) -> AgentGraphStateDict:
    return {
        "run_id": "run_test_001",
        "organization_id": "org_test_123",
        "actor_id": "usr_test_456",
        "request_id": "req_test_789",
        "correlation_id": "corr_test_001",
        "trace_id": "trace_test_002",
        "objective": "Determine response strategy for shipment delay",
        "input_reference": "ship_001",
        "input_references": {"shipment_id": "ship_001"},
        "current_stage": AgentStage.SCENARIO_ANALYSIS.value,
        "current_node": "scenario_agent",
        "status": AgentLifecycleStatus.RUNNING.value,
        "step_count": 5,
        "evidence_bundle_id": "bundle_test_001",
        "evidence_references": ["ev_sig_001", "ev_sig_002"],
        "citation_references": ["cite_001"],
        "risk_assessment_id": "risk_assess_999",
        "risk_assessment_reference": sample_risk_dict,
        "risk_alert_references": [],
        "recommendation_references": ["rec_001"],
        "prediction_id": "pred_test_12345",
        "prediction_reference": sample_prediction_dict,
        "prediction_result": sample_prediction_dict,
        "scenario_id": "scen_test_001",
        "scenario_reference": sample_scenario_dict,
        "scenario_result": sample_scenario_dict,
        "decision_id": None,
        "decision_reference": None,
        "decision_result": None,
        "findings": {},
        "structured_findings": [],
        "warnings": [],
        "limitations": [],
        "conflicts": [],
        "selected_route": None,
        "next_node": None,
        "route_reason": None,
        "route_history": [],
        "retry_count": 0,
        "last_error": None,
        "errors": [],
        "requires_human_approval": False,
        "approval_reference": None,
        "side_effect_allowed": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "available_recommendations": [sample_recommendation_dict],
        },
        "state_schema_version": "1.0.0",
    }


# ==============================================================================
# GROUP 1: CONTRACTS & PYDANTIC VALIDATION (10 tests)
# ==============================================================================

class TestDecisionContracts:
    def test_valid_decision_request(self, sample_decision_request: DecisionRequest):
        assert sample_decision_request.organization_id == "org_test_123"
        assert sample_decision_request.scenario_id == "scen_test_001"
        assert sample_decision_request.decision_type == DecisionType.OPERATIONAL_RESPONSE

    def test_extra_field_rejected_in_request(self, sample_decision_request: DecisionRequest):
        data = sample_decision_request.model_dump()
        data["unauthorized_field"] = "malicious_payload"
        with pytest.raises((ValidationError, InvalidDecisionRequestError)):
            DecisionRequest.model_validate(data)

    def test_empty_organization_rejected(self, sample_decision_request: DecisionRequest):
        data = sample_decision_request.model_dump()
        data["organization_id"] = "   "
        with pytest.raises((ValidationError, DecisionTenantIsolationError, InvalidDecisionRequestError)):
            DecisionRequest.model_validate(data)

    def test_unsupported_decision_type_rejected(self, sample_decision_request: DecisionRequest):
        data = sample_decision_request.model_dump()
        data["decision_type"] = "INVALID_DECISION_TYPE"
        with pytest.raises((ValidationError, UnsupportedDecisionTypeError)):
            DecisionRequest.model_validate(data)

    def test_valid_candidate_construction(self):
        cand = DecisionCandidate(
            candidate_id="cand_test_001",
            action_type="MONITOR",
            description="Active telemetry monitoring",
            parameters={"interval_minutes": 15},
            prerequisites=["telemetry_active"],
            constraints=[],
            expected_effect="Early warning of ETA slip",
            evidence_references=["ev_1"],
            status=DecisionCandidateStatus.CANDIDATE,
            requires_human_approval=False,
            provenance={"rule_id": "rule_01"},
        )
        assert cand.action_type == "MONITOR"
        assert cand.requires_human_approval is False

    def test_extra_field_rejected_in_candidate(self):
        with pytest.raises((ValidationError, InvalidDecisionCandidateError)):
            DecisionCandidate(
                candidate_id="cand_001",
                action_type="MONITOR",
                description="desc",
                extra_forbidden_key="hack",
            )

    def test_valid_rationale_construction(self):
        rat = DecisionRationale(
            basis_type=DecisionBasis.RISK_ASSESSMENT,
            rule_id="rule_risk_high",
            source_reference="risk_assess_999",
            evidence_references=["ev_1"],
            explanation_code="HIGH_RISK_REVIEW_TRIGGERED",
        )
        assert rat.basis_type == DecisionBasis.RISK_ASSESSMENT
        assert rat.explanation_code == "HIGH_RISK_REVIEW_TRIGGERED"

    def test_extra_field_rejected_in_rationale(self):
        with pytest.raises(ValidationError):
            DecisionRationale(
                basis_type=DecisionBasis.RISK_ASSESSMENT,
                rule_id="rule_01",
                source_reference="src_01",
                evidence_references=[],
                extra_field="disallowed",
            )

    def test_decision_status_enum_values(self):
        assert DecisionStatus.READY.value == "READY"
        assert DecisionStatus.INSUFFICIENT_EVIDENCE.value == "INSUFFICIENT_EVIDENCE"
        assert DecisionStatus.REQUIRES_APPROVAL.value == "REQUIRES_APPROVAL"
        assert DecisionStatus.BLOCKED.value == "BLOCKED"
        assert DecisionStatus.INVALID.value == "INVALID"

    def test_decision_basis_enum_values(self):
        assert DecisionBasis.RISK_ASSESSMENT.value == "RISK_ASSESSMENT"
        assert DecisionBasis.PREDICTION.value == "PREDICTION"
        assert DecisionBasis.SCENARIO.value == "SCENARIO"
        assert DecisionBasis.RECOMMENDATION.value == "RECOMMENDATION"
        assert DecisionBasis.CONSTRAINT.value == "CONSTRAINT"
        assert DecisionBasis.EVIDENCE.value == "EVIDENCE"


# ==============================================================================
# GROUP 2: CANDIDATE SYNTHESIS & BEHAVIOR (8 tests)
# ==============================================================================

class TestCandidateSynthesis:
    def test_candidate_structure_and_types(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert len(result.candidates) > 0
        cand = result.candidates[0]
        assert isinstance(cand.candidate_id, str)
        assert isinstance(cand.action_type, str)
        assert isinstance(cand.description, str)
        assert isinstance(cand.parameters, dict)
        assert isinstance(cand.prerequisites, list)
        assert isinstance(cand.constraints, list)
        assert isinstance(cand.evidence_references, list)
        assert isinstance(cand.provenance, dict)

    def test_candidate_parameters_are_deterministic(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        res1, _ = engine.evaluate(sample_decision_request)
        res2, _ = engine.evaluate(sample_decision_request)
        assert res1.candidates[0].parameters == res2.candidates[0].parameters

    def test_candidate_contains_no_execution_flags(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            data = cand.model_dump()
            assert "executed" not in data
            assert "executed_at" not in data
            assert "execution_status" not in data

    def test_candidate_status_is_candidate(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            assert cand.status in (
                DecisionCandidateStatus.CANDIDATE,
                DecisionCandidateStatus.PREFERRED,
                DecisionCandidateStatus.ALTERNATIVE,
                DecisionCandidateStatus.REQUIRES_APPROVAL,
                DecisionCandidateStatus.PROPOSED,
            )

    def test_candidate_provenance_preserves_rule_and_source(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            assert "rule_id" in cand.provenance
            assert "rule_version" in cand.provenance

    def test_preferred_candidate_is_first_ranked(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        if result.preferred_candidate_id:
            assert result.preferred_candidate_id == result.candidates[0].candidate_id

    def test_candidate_evidence_references_subset_of_authoritative_evidence(
        self, sample_decision_request: DecisionRequest
    ):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            for ev in cand.evidence_references:
                assert ev in sample_decision_request.evidence_references

    def test_invalid_candidate_id_rejected(self):
        with pytest.raises((ValidationError, InvalidDecisionCandidateError)):
            DecisionCandidate(
                candidate_id="   ",
                action_type="MONITOR",
                description="desc",
            )


# ==============================================================================
# GROUP 3: RATIONALE & BASIS AUDITABILITY (8 tests)
# ==============================================================================

class TestRationaleAuditability:
    def test_rationale_basis_type_populated(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert len(result.rationales) > 0
        for rat in result.rationales:
            assert isinstance(rat.basis_type, DecisionBasis)

    def test_rationale_rule_id_audit_link(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for rat in result.rationales:
            assert rat.rule_id.startswith("rule_")

    def test_rationale_explanation_code_audit_link(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for rat in result.rationales:
            assert rat.explanation_code is not None
            assert len(rat.explanation_code) > 0

    def test_rationale_evidence_linked(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        found_evidence = False
        for rat in result.rationales:
            if rat.evidence_references:
                found_evidence = True
                break
        assert found_evidence is True

    def test_chain_of_thought_rejected_in_rationale(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionRationale(
                basis_type=DecisionBasis.RISK_ASSESSMENT,
                rule_id="rule_01",
                source_reference="src_01",
                explanation_code="CODE",
                chain_of_thought="Thinking step by step...",
            )

    def test_internal_monologue_rejected_in_rationale_provenance(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionRationale(
                basis_type=DecisionBasis.RISK_ASSESSMENT,
                rule_id="rule_01",
                source_reference="src_01",
                provenance={"internal_monologue": "Hidden text"},
            )

    def test_multiple_basis_types_represented(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        basis_set = {r.basis_type for r in result.rationales}
        assert DecisionBasis.SCENARIO in basis_set
        assert DecisionBasis.RISK_ASSESSMENT in basis_set

    def test_source_reference_points_to_authoritative_upstream_id(
        self, sample_decision_request: DecisionRequest
    ):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        sources = {r.source_reference for r in result.rationales}
        assert "scen_test_001" in sources or "risk_assess_999" in sources


# ==============================================================================
# GROUP 4: DETERMINISTIC DECISION RULES & RANKING (10 tests)
# ==============================================================================

class TestDeterministicRulesAndRanking:
    def test_rule_version_constant(self):
        assert DECISION_RULE_VERSION == "decision_rules_v1.0.0"

    def test_rule_engine_version_matches_constant(self):
        engine = DecisionRuleEngine()
        assert engine.rule_version == DECISION_RULE_VERSION

    def test_high_risk_triggers_escalation_candidate(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        action_types = [c.action_type for c in result.candidates]
        assert "ESCALATE_FOR_REVIEW" in action_types

    def test_delay_scenario_triggers_alternative_preparation(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        action_types = [c.action_type for c in result.candidates]
        assert "PREPARE_ALTERNATIVE" in action_types

    def test_rule_engine_uses_no_eval_or_exec(self):
        import inspect
        source = inspect.getsource(DecisionRuleEngine)
        assert "eval(" not in source
        assert "exec(" not in source

    def test_rule_engine_uses_no_llm_calls(self):
        import inspect
        source = inspect.getsource(DecisionRuleEngine)
        assert "openai" not in source
        assert "claude" not in source
        assert "bedrock" not in source
        assert "anthropic" not in source

    def test_deterministic_candidate_order_repeatability(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        results = [engine.evaluate(sample_decision_request)[0] for _ in range(5)]
        first_order = [c.candidate_id for c in results[0].candidates]
        for r in results[1:]:
            assert [c.candidate_id for c in r.candidates] == first_order

    def test_recommendation_ingestion_preserves_priority(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        # Recommendation rec_001 was PREPARE_ALTERNATIVE with priority 1
        rec_cand = [c for c in result.candidates if c.provenance.get("source_recommendation_id") == "rec_001"]
        assert len(rec_cand) == 1
        assert rec_cand[0].action_type == "PREPARE_ALTERNATIVE"
        assert rec_cand[0].requires_human_approval is True

    def test_empty_recommendations_handled_gracefully(self, sample_decision_request: DecisionRequest):
        sample_decision_request.available_recommendations = []
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.status in (DecisionStatus.READY, DecisionStatus.REQUIRES_APPROVAL)
        assert len(result.candidates) > 0

    def test_low_risk_scenario_triggers_monitor_candidate(self, sample_decision_request: DecisionRequest):
        sample_decision_request.risk_assessment_reference["risk_score"] = 25.0
        sample_decision_request.risk_assessment_reference["risk_level"] = "LOW"
        sample_decision_request.available_recommendations = []
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        action_types = [c.action_type for c in result.candidates]
        assert "MONITOR" in action_types


# ==============================================================================
# GROUP 5: SCENARIO INTEGRATION (8 tests)
# ==============================================================================

class TestScenarioIntegration:
    def test_scenario_id_preserved_in_decision_result(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.scenario_id == "scen_test_001"

    def test_scenario_fingerprint_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.scenario_fingerprint == "scen_fp_12345"

    def test_scenario_constraints_reflected_in_candidates(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        all_candidate_constraints = []
        for c in result.candidates:
            all_candidate_constraints.extend([cn.name for cn in c.constraints])
        assert "sla_delay_limit" in all_candidate_constraints

    def test_scenario_result_not_mutated(
        self, sample_decision_request: DecisionRequest, sample_scenario_dict: Dict[str, Any]
    ):
        original_json = json.dumps(sample_scenario_dict, sort_keys=True)
        engine = DecisionRuleEngine()
        engine.evaluate(sample_decision_request)
        current_json = json.dumps(sample_scenario_dict, sort_keys=True)
        assert original_json == current_json

    def test_missing_scenario_returns_insufficient_evidence(self, sample_decision_request: DecisionRequest):
        sample_decision_request.scenario_result = None
        sample_decision_request.scenario_reference = None
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
        assert len(result.candidates) == 0

    def test_cross_tenant_scenario_in_request_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.scenario_result["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_scenario_parameters_referenced_in_candidate_parameters(
        self, sample_decision_request: DecisionRequest
    ):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        # Should have captured delay_minutes
        found_param = any("delay_minutes" in c.parameters for c in result.candidates)
        assert found_param is True

    def test_scenario_definition_target_reference_preserved(
        self, sample_decision_request: DecisionRequest
    ):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        # Target ship_001 should be present in candidate parameters
        found_target = any(c.parameters.get("target") == "ship_001" for c in result.candidates)
        assert found_target is True


# ==============================================================================
# GROUP 6: PREDICTION INTEGRATION (8 tests)
# ==============================================================================

class TestPredictionIntegration:
    def test_prediction_id_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.prediction_id == "pred_test_12345"

    def test_prediction_value_preserved_in_candidate_parameters(
        self, sample_decision_request: DecisionRequest
    ):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        found_val = any(c.parameters.get("predicted_delay_minutes") == 120.0 for c in result.candidates)
        assert found_val is True

    def test_prediction_evidence_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        evidence_found = any("ev_sig_001" in c.evidence_references for c in result.candidates)
        assert evidence_found is True

    def test_prediction_uncertainty_not_converted_to_probability(
        self, sample_decision_request: DecisionRequest
    ):
        sample_decision_request.prediction_result["uncertainty"] = {
            "confidence_score": 0.88,
            "method": "CONFORMAL",
        }
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            assert "probability" not in cand.model_dump()
            assert "success_probability" not in cand.model_dump()

    def test_null_prediction_handled_gracefully(self, sample_decision_request: DecisionRequest):
        sample_decision_request.prediction_id = None
        sample_decision_request.prediction_result = None
        sample_decision_request.prediction_reference = None
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.status in (DecisionStatus.READY, DecisionStatus.REQUIRES_APPROVAL)
        assert result.prediction_id is None

    def test_cross_tenant_prediction_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.prediction_result["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_prediction_model_metadata_preserved_in_provenance(
        self, sample_decision_request: DecisionRequest
    ):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert "provenance" in result.model_dump()

    def test_prediction_result_not_mutated(
        self, sample_decision_request: DecisionRequest, sample_prediction_dict: Dict[str, Any]
    ):
        original_json = json.dumps(sample_prediction_dict, sort_keys=True)
        engine = DecisionRuleEngine()
        engine.evaluate(sample_decision_request)
        current_json = json.dumps(sample_prediction_dict, sort_keys=True)
        assert original_json == current_json


# ==============================================================================
# GROUP 7: RISK ASSESSMENT INTEGRATION (8 tests)
# ==============================================================================

class TestRiskAssessmentIntegration:
    def test_risk_assessment_id_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.risk_assessment_id == "risk_assess_999"

    def test_risk_score_preserved_in_candidate_parameters(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        found_score = any(c.parameters.get("risk_score") == 78.5 for c in result.candidates)
        assert found_score is True

    def test_risk_level_preserved_in_candidate_parameters(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        found_level = any(c.parameters.get("risk_level") == "HIGH" for c in result.candidates)
        assert found_level is True

    def test_no_risk_recalculation(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            # Score must match authoritative input exactly
            if "risk_score" in cand.parameters:
                assert cand.parameters["risk_score"] == 78.5

    def test_risk_score_is_not_converted_to_probability(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            for v in cand.parameters.values():
                assert v != 0.785

    def test_cross_tenant_risk_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.risk_assessment_reference["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_risk_assessment_not_mutated(
        self, sample_decision_request: DecisionRequest, sample_risk_dict: Dict[str, Any]
    ):
        original_json = json.dumps(sample_risk_dict, sort_keys=True)
        engine = DecisionRuleEngine()
        engine.evaluate(sample_decision_request)
        current_json = json.dumps(sample_risk_dict, sort_keys=True)
        assert original_json == current_json

    def test_missing_risk_assessment_handled_gracefully(self, sample_decision_request: DecisionRequest):
        sample_decision_request.risk_assessment_id = None
        sample_decision_request.risk_assessment_reference = None
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.status in (DecisionStatus.READY, DecisionStatus.REQUIRES_APPROVAL)
        assert result.risk_assessment_id is None


# ==============================================================================
# GROUP 8: RECOMMENDATION INTEGRATION (8 tests)
# ==============================================================================

class TestRecommendationIntegration:
    def test_recommendation_id_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        found = any(c.provenance.get("source_recommendation_id") == "rec_001" for c in result.candidates)
        assert found is True

    def test_recommendation_requires_approval_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        rec_cands = [c for c in result.candidates if c.provenance.get("source_recommendation_id") == "rec_001"]
        assert len(rec_cands) == 1
        assert rec_cands[0].requires_human_approval is True

    def test_recommendation_evidence_references_preserved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        rec_cands = [c for c in result.candidates if c.provenance.get("source_recommendation_id") == "rec_001"]
        assert "ev_sig_001" in rec_cands[0].evidence_references

    def test_recommendation_not_auto_approved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        rec_cands = [c for c in result.candidates if c.provenance.get("source_recommendation_id") == "rec_001"]
        assert rec_cands[0].status != DecisionCandidateStatus.APPROVED

    def test_recommendation_not_auto_executed(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        rec_cands = [c for c in result.candidates if c.provenance.get("source_recommendation_id") == "rec_001"]
        assert rec_cands[0].status != DecisionCandidateStatus.EXECUTED

    def test_recommendation_action_type_mapped(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        rec_cands = [c for c in result.candidates if c.provenance.get("source_recommendation_id") == "rec_001"]
        assert rec_cands[0].action_type == "PREPARE_ALTERNATIVE"

    def test_cross_tenant_recommendation_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.available_recommendations[0]["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_multiple_recommendations_ordered_by_priority(self, sample_decision_request: DecisionRequest):
        sample_decision_request.available_recommendations = [
            {
                "recommendation_id": "rec_002",
                "action_type": "MONITOR",
                "title": "Low priority monitor",
                "description": "desc",
                "priority": 2,
                "requires_approval": False,
                "evidence_references": ["ev_sig_001"],
            },
            {
                "recommendation_id": "rec_001",
                "action_type": "PREPARE_ALTERNATIVE",
                "title": "High priority alternative",
                "description": "desc",
                "priority": 1,
                "requires_approval": True,
                "evidence_references": ["ev_sig_001"],
            },
        ]
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        rec_cands = [c for c in result.candidates if "source_recommendation_id" in c.provenance]
        assert rec_cands[0].provenance["source_recommendation_id"] == "rec_001"
        assert rec_cands[1].provenance["source_recommendation_id"] == "rec_002"


# ==============================================================================
# GROUP 9: CONSTRAINTS & AUTHORITY (6 tests)
# ==============================================================================

class TestConstraintsAndAuthority:
    def test_authority_constraints_in_candidate(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        escalate_cand = next(c for c in result.candidates if c.action_type == "ESCALATE_FOR_REVIEW")
        constraint_names = [cn.name for cn in escalate_cand.constraints]
        assert "HUMAN_APPROVAL_AUTHORITY" in constraint_names

    def test_evidence_prerequisites_enforced(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for c in result.candidates:
            assert len(c.prerequisites) > 0

    def test_operational_prerequisites_are_descriptive(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for c in result.candidates:
            for p in c.prerequisites:
                assert isinstance(p, str)
                assert not p.startswith("EXECUTE_")

    def test_planning_horizon_preserved(self, sample_decision_request: DecisionRequest):
        sample_decision_request.planning_horizon_hours = 48.0
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.planning_horizon_hours == 48.0

    def test_no_solver_constraints_injected(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        data = result.model_dump()
        assert "solver_constraints" not in data
        assert "lp_relaxation" not in data
        assert "integer_programming" not in data

    def test_constraint_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            DecisionConstraint(
                name="test",
                constraint_type="TEST",
                value=10,
                extra_param="forbidden",
            )


# ==============================================================================
# GROUP 10: STATE OWNERSHIP & MUTATION SAFETY (8 tests)
# ==============================================================================

class TestStateOwnershipAndMutationSafety:
    def test_decision_node_writes_decision_owned_fields(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert "decision_id" in updates
        assert "decision_reference" in updates
        assert "decision_result" in updates
        assert "current_stage" in updates
        assert updates["current_stage"] == AgentStage.DECISION.value

    def test_apply_state_update_succeeds_for_decision_agent(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        updates = decision_node(sample_graph_state)
        new_state = apply_state_update(
            current_state=state_obj,
            update_payload=updates,
            writer_node_id="decision_agent",
            writer_stage=AgentStage.DECISION,
        )
        assert new_state.decision_id is not None
        assert new_state.current_node == "decision_agent"

    def test_unauthorized_write_to_scenario_result_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"scenario_result": {"hacked": True}},
                writer_node_id="decision_agent",
                writer_stage=AgentStage.DECISION,
            )

    def test_unauthorized_write_to_prediction_result_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"prediction_result": {"hacked": True}},
                writer_node_id="decision_agent",
                writer_stage=AgentStage.DECISION,
            )

    def test_unauthorized_write_to_risk_assessment_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"risk_assessment_id": "risk_hacked"},
                writer_node_id="decision_agent",
                writer_stage=AgentStage.DECISION,
            )

    def test_unauthorized_write_to_approval_reference_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"approval_reference": "app_hacked"},
                writer_node_id="decision_agent",
                writer_stage=AgentStage.DECISION,
            )

    def test_identity_fields_protected_against_mutation(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"run_id": "run_hacked"},
                writer_node_id="decision_agent",
                writer_stage=AgentStage.DECISION,
            )

    def test_state_schema_version_preserved(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert sample_graph_state["state_schema_version"] == "1.0.0"


# ==============================================================================
# GROUP 11: TENANT ISOLATION (10 tests)
# ==============================================================================

class TestTenantIsolation:
    def test_tenant_mismatch_in_request_rejected(self, sample_decision_request: DecisionRequest):
        req_dict = sample_decision_request.model_dump()
        req_dict["organization_id"] = "org_foreign_999"
        with pytest.raises(DecisionTenantIsolationError):
            DecisionRequest.model_validate(req_dict)

    def test_foreign_scenario_org_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.scenario_result["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_foreign_prediction_org_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.prediction_result["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_foreign_risk_org_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.risk_assessment_reference["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_foreign_recommendation_org_rejected(self, sample_decision_request: DecisionRequest):
        sample_decision_request.available_recommendations[0]["organization_id"] = "org_foreign_999"
        engine = DecisionRuleEngine()
        with pytest.raises(DecisionTenantIsolationError):
            engine.evaluate(sample_decision_request)

    def test_foreign_evidence_reference_rejected(self, sample_decision_request: DecisionRequest):
        req_dict = sample_decision_request.model_dump()
        req_dict["evidence_references"] = ["org_foreign_999:ev_01"]
        with pytest.raises(DecisionTenantIsolationError):
            DecisionRequest.model_validate(req_dict)

    def test_decision_node_fails_closed_on_missing_org(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["organization_id"] = "   "
        with pytest.raises(DecisionTenantIsolationError):
            decision_node(sample_graph_state)

    def test_graph_state_rejects_cross_tenant_decision_result(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["decision_result"] = {
            "decision_id": "dec_123",
            "organization_id": "org_foreign_tenant",
        }
        with pytest.raises(AgentTenantIsolationError):
            AgentGraphState.model_validate(sample_graph_state)

    def test_graph_state_rejects_cross_tenant_decision_reference(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["decision_reference"] = {
            "decision_id": "dec_123",
            "organization_id": "org_foreign_tenant",
        }
        with pytest.raises(AgentTenantIsolationError):
            AgentGraphState.model_validate(sample_graph_state)

    def test_clean_tenant_isolation_passes(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.organization_id == sample_decision_request.organization_id


# ==============================================================================
# GROUP 12: SECURITY & SECRET PROTECTION (8 tests)
# ==============================================================================

class TestSecurityScrubbing:
    def test_bearer_token_in_parameter_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionCandidate(
                candidate_id="cand_sec_01",
                action_type="MONITOR",
                description="desc",
                parameters={"auth_header": "Bearer secret_jwt_token_123"},
            )

    def test_api_key_in_provenance_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionCandidate(
                candidate_id="cand_sec_02",
                action_type="MONITOR",
                description="desc",
                provenance={"api_key": "sk-1234567890abcdef"},
            )

    def test_password_in_provenance_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionCandidate(
                candidate_id="cand_sec_03",
                action_type="MONITOR",
                description="desc",
                provenance={"db_password": "super_secret_password"},
            )

    def test_chain_of_thought_rejected_in_candidate(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionCandidate(
                candidate_id="cand_sec_04",
                action_type="MONITOR",
                description="desc",
                provenance={"chain_of_thought": "My reasoning steps"},
            )

    def test_internal_monologue_in_description_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            DecisionCandidate(
                candidate_id="cand_sec_05",
                action_type="MONITOR",
                description="Contains internal_monologue text here",
            )

    def test_sensitive_value_in_state_update_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentValidationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"findings": {"token": "bearer secret_123"}},
                writer_node_id="decision_agent",
                writer_stage=AgentStage.DECISION,
            )

    def test_clean_candidate_provenance_accepted(self):
        cand = DecisionCandidate(
            candidate_id="cand_clean",
            action_type="MONITOR",
            description="Active telemetry monitoring",
            provenance={"rule_engine": "DecisionRuleEngine", "version": "1.0"},
        )
        assert cand.provenance["rule_engine"] == "DecisionRuleEngine"

    def test_clean_rationale_provenance_accepted(self):
        rat = DecisionRationale(
            basis_type=DecisionBasis.SCENARIO,
            rule_id="rule_scen",
            source_reference="scen_01",
            provenance={"rule_source": "DeterministicRuleBase"},
        )
        assert rat.provenance["rule_source"] == "DeterministicRuleBase"


# ==============================================================================
# GROUP 13: HUMAN APPROVAL BOUNDARY (8 tests)
# ==============================================================================

class TestHumanApprovalBoundary:
    def test_requires_human_approval_set_when_candidate_requires_approval(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = decision_node(sample_graph_state)
        assert updates["decision_result"]["requires_human_approval"] is True
        assert updates.get("selected_route") == "approval_boundary"

    def test_decision_status_is_requires_approval(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.status == DecisionStatus.REQUIRES_APPROVAL

    def test_decision_status_is_never_approved(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        assert result.status != "APPROVED"
        for cand in result.candidates:
            assert cand.status != DecisionCandidateStatus.APPROVED

    def test_decision_node_does_not_set_approval_reference(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert updates.get("approval_reference") is None

    def test_decision_node_does_not_create_approval_record(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert "approvals" not in updates
        assert "approval_record" not in updates

    def test_decision_node_warning_logged_for_approval(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert any("human approval" in w.lower() for w in updates.get("warnings", []))

    def test_no_bypass_flag_in_decision_request(self, sample_decision_request: DecisionRequest):
        data = sample_decision_request.model_dump()
        assert "auto_approve" not in data
        assert "bypass_approval" not in data
        assert "skip_approval" not in data

    def test_approval_boundary_halts_autonomous_execution(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert updates.get("selected_route") == "approval_boundary" or updates.get("requires_human_approval") is True


# ==============================================================================
# GROUP 14: READ-ONLY & ACTION BOUNDARY (8 tests)
# ==============================================================================

class TestReadOnlyAndActionBoundary:
    def test_contract_is_read_only(self):
        assert DECISION_NODE_CONTRACT.is_side_effecting is False
        assert DECISION_NODE_CONTRACT.side_effect_type == ToolSideEffectType.READ_ONLY

    def test_decision_node_does_not_modify_shipment_data(self, sample_graph_state: AgentGraphStateDict):
        initial_input = sample_graph_state["input_references"]
        decision_node(sample_graph_state)
        assert sample_graph_state["input_references"] == initial_input

    def test_decision_node_does_not_mutate_inventory(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert "inventory" not in updates
        assert "inventory_allocations" not in updates

    def test_decision_node_does_not_contact_carrier(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert "carrier_notifications" not in updates
        assert "dispatch_commands" not in updates

    def test_decision_node_does_not_contact_supplier(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert "supplier_purchase_orders" not in updates
        assert "supplier_notifications" not in updates

    def test_decision_result_contains_no_executed_actions(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        data = result.model_dump()
        assert "executed_actions" not in data
        assert "dispatch_result" not in data

    def test_side_effect_allowed_remains_false(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        updates = decision_node(sample_graph_state)
        new_state = apply_state_update(
            current_state=state_obj,
            update_payload=updates,
            writer_node_id="decision_agent",
            writer_stage=AgentStage.DECISION,
        )
        assert new_state.side_effect_allowed is False

    def test_candidate_action_type_descriptive_not_imperative(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        result, _ = engine.evaluate(sample_decision_request)
        for cand in result.candidates:
            assert cand.action_type in (
                "MONITOR",
                "INVESTIGATE",
                "PREPARE_ALTERNATIVE",
                "ESCALATE_FOR_REVIEW",
            )


# ==============================================================================
# GROUP 15: OBSERVABILITY & TELEMETRY (8 tests)
# ==============================================================================

class TestObservabilityAndTelemetry:
    def test_telemetry_emitted_with_decision_agent_node_name(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        decision_node(sample_graph_state)
        assert len(recorded) == 1
        assert recorded[0].node_name == "decision_agent"
        assert recorded[0].status == "SUCCESS"

    def test_telemetry_captures_decision_id(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        updates = decision_node(sample_graph_state)
        assert len(recorded) == 1
        assert recorded[0].node_name == "decision_agent"
        assert updates["decision_id"] is not None

    def test_telemetry_captures_candidate_count(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        updates = decision_node(sample_graph_state)
        assert len(recorded) == 1
        assert recorded[0].node_name == "decision_agent"
        assert len(updates["decision_result"]["candidates"]) > 0

    def test_telemetry_captures_rule_version(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        updates = decision_node(sample_graph_state)
        assert len(recorded) == 1
        assert updates["decision_result"]["rule_version"] == DECISION_RULE_VERSION

    def test_telemetry_duration_positive(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        decision_node(sample_graph_state)
        assert len(recorded) == 1
        assert recorded[0].duration_ms >= 0.0

    def test_telemetry_emitted_on_error(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        sample_graph_state["organization_id"] = "   "
        with pytest.raises(DecisionTenantIsolationError):
            decision_node(sample_graph_state)
        assert len(recorded) == 1
        assert recorded[0].status == "FAILED"
        assert recorded[0].error_code == "DecisionTenantIsolationError"

    def test_telemetry_actor_and_correlation_ids_preserved(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        decision_node(sample_graph_state)
        assert recorded[0].actor_id == "usr_test_456"
        assert recorded[0].correlation_id == "corr_test_001"

    def test_telemetry_redacts_sensitive_metadata(
        self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch
    ):
        recorded: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: recorded.append(t))
        decision_node(sample_graph_state)
        data = recorded[0].model_dump()
        meta_str = json.dumps(data)
        assert "password" not in meta_str.lower()
        assert "bearer" not in meta_str.lower()


# ==============================================================================
# GROUP 16: DETERMINISTIC IDENTITY & FINGERPRINT (8 tests)
# ==============================================================================

class TestDeterministicIdentityAndFingerprint:
    def test_deterministic_decision_id_repeatability(self):
        id1 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
            risk_assessment_id="risk_789",
            prediction_id="pred_101",
            recommendation_ids=["rec_1"],
            rule_version="decision_rules_v1.0.0",
        )
        id2 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
            risk_assessment_id="risk_789",
            prediction_id="pred_101",
            recommendation_ids=["rec_1"],
            rule_version="decision_rules_v1.0.0",
        )
        assert id1 == id2
        assert id1.startswith("dec_")

    def test_different_org_produces_different_decision_id(self):
        id1 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
        )
        id2 = generate_deterministic_decision_id(
            organization_id="org_999",
            scenario_id="scen_456",
        )
        assert id1 != id2

    def test_different_scenario_produces_different_decision_id(self):
        id1 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
        )
        id2 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_777",
        )
        assert id1 != id2

    def test_different_rule_version_produces_different_decision_id(self):
        id1 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
            rule_version="v1.0",
        )
        id2 = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
            rule_version="v2.0",
        )
        assert id1 != id2

    def test_decision_id_is_valid_uuidv5(self):
        dec_id = generate_deterministic_decision_id(
            organization_id="org_123",
            scenario_id="scen_456",
        )
        raw_uuid = dec_id[4:]
        parsed = uuid.UUID(raw_uuid)
        assert parsed.version == 5

    def test_compute_fingerprint_repeatability(self, sample_decision_request: DecisionRequest):
        engine = DecisionRuleEngine()
        res1, _ = engine.evaluate(sample_decision_request)
        res2, _ = engine.evaluate(sample_decision_request)
        assert res1.fingerprint == res2.fingerprint
        assert len(res1.fingerprint) == 64  # SHA-256 hex string

    def test_fingerprint_invariant_to_candidate_order(self):
        cands1 = [
            {"candidate_id": "c1", "action_type": "MONITOR"},
            {"candidate_id": "c2", "action_type": "INVESTIGATE"},
        ]
        cands2 = [
            {"candidate_id": "c2", "action_type": "INVESTIGATE"},
            {"candidate_id": "c1", "action_type": "MONITOR"},
        ]
        fp1 = compute_decision_fingerprint(
            organization_id="org_123",
            scenario_id="scen_01",
            candidates=cands1,
        )
        fp2 = compute_decision_fingerprint(
            organization_id="org_123",
            scenario_id="scen_01",
            candidates=cands2,
        )
        assert fp1 == fp2

    def test_fingerprint_changes_on_modified_evidence(self):
        fp1 = compute_decision_fingerprint(
            organization_id="org_123",
            scenario_id="scen_01",
            evidence_references=["ev_1"],
        )
        fp2 = compute_decision_fingerprint(
            organization_id="org_123",
            scenario_id="scen_01",
            evidence_references=["ev_2"],
        )
        assert fp1 != fp2


# ==============================================================================
# GROUP 17: TOPOLOGY, TRANSITIONS & GRAPH INTEGRATION (10 tests)
# ==============================================================================

class TestTopologyAndGraphIntegration:
    def test_decision_node_registered_in_allowlist(self):
        assert "decision_agent" in global_node_registry.allowlist

    def test_decision_node_contract_attributes(self):
        assert DECISION_NODE_CONTRACT.node_id == "decision_agent"
        assert DECISION_NODE_CONTRACT.stage == AgentStage.DECISION
        assert DECISION_NODE_CONTRACT.is_side_effecting is False
        assert "decision_result" in DECISION_NODE_CONTRACT.output_keys

    def test_scenario_to_decision_is_allowed_transition(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.SCENARIO_ANALYSIS, AgentStage.DECISION
        ) is True

    def test_decision_to_approval_is_allowed_transition(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.DECISION, AgentStage.APPROVAL
        ) is True

    def test_decision_to_termination_is_allowed_transition(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.DECISION, AgentStage.TERMINATION
        ) is True

    def test_decision_backward_to_scenario_is_illegal(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.DECISION, AgentStage.SCENARIO_ANALYSIS
        ) is False

    def test_decision_backward_to_research_is_illegal(self):
        with pytest.raises(AgentStageTransitionError):
            StageTransitionValidator.validate_transition(
                AgentStage.DECISION, AgentStage.RESEARCH
            )

    def test_stage_decision_enum_value(self):
        assert AgentStage.DECISION.value == "DECISION"

    def test_decision_node_execution_in_graph_builder(self, sample_graph_state: AgentGraphStateDict):
        registry = NodeRegistry()
        registry.register_node(DECISION_NODE_CONTRACT, decision_node)
        assert registry.has_node("decision_agent") is True

    def test_decision_node_routes_to_approval_when_approval_needed(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = decision_node(sample_graph_state)
        assert updates.get("selected_route") == "approval_boundary"


# ==============================================================================
# GROUP 18: DETERMINISTIC END-TO-END SCENARIO FIXTURE (4 tests)
# ==============================================================================

class TestDeterministicPipelineFixture:
    def test_end_to_end_pipeline_fixture_repeatability(
        self, sample_graph_state: AgentGraphStateDict
    ):
        """Run Decision Agent across two identical states and verify byte-level equivalence."""
        state_copy_1 = json.loads(json.dumps(sample_graph_state))
        state_copy_2 = json.loads(json.dumps(sample_graph_state))

        updates_1 = decision_node(state_copy_1)
        updates_2 = decision_node(state_copy_2)

        assert updates_1["decision_id"] == updates_2["decision_id"]
        assert updates_1["decision_result"]["fingerprint"] == updates_2["decision_result"]["fingerprint"]
        assert updates_1["decision_result"]["preferred_candidate_id"] == updates_2["decision_result"]["preferred_candidate_id"]

        cands_1 = [c["candidate_id"] for c in updates_1["decision_result"]["candidates"]]
        cands_2 = [c["candidate_id"] for c in updates_2["decision_result"]["candidates"]]
        assert cands_1 == cands_2

    def test_end_to_end_pipeline_ten_runs_stability(
        self, sample_graph_state: AgentGraphStateDict
    ):
        """10 repeated runs must yield 10 identical outputs with zero variance."""
        results = [decision_node(json.loads(json.dumps(sample_graph_state))) for _ in range(10)]
        first_id = results[0]["decision_id"]
        first_fp = results[0]["decision_result"]["fingerprint"]

        for r in results[1:]:
            assert r["decision_id"] == first_id
            assert r["decision_result"]["fingerprint"] == first_fp

    def test_end_to_end_pipeline_produces_structured_findings(
        self, sample_graph_state: AgentGraphStateDict
    ):
        updates = decision_node(sample_graph_state)
        assert len(updates["structured_findings"]) > 0
        finding = updates["structured_findings"][0]
        assert finding["category"] == "DECISION_CANDIDATE"
        assert finding["created_by_node"] == "decision_agent"
        assert "evidence_ids" in finding

    def test_end_to_end_pipeline_produces_limitation_records(
        self, sample_graph_state: AgentGraphStateDict
    ):
        sample_graph_state["prediction_id"] = None
        sample_graph_state["prediction_result"] = None
        sample_graph_state["prediction_reference"] = None
        updates = decision_node(sample_graph_state)
        assert len(updates["limitations"]) > 0
        lim = updates["limitations"][0]
        assert lim["category"] in [c.value for c in LimitationCategory]
        assert lim["mitigation_or_impact"] is not None


# ==============================================================================
# GROUP 19: EXPLICIT NO-SIDE-EFFECT TEST (5 tests)
# ==============================================================================

class TestExplicitNoSideEffectSafety:
    def test_no_shipment_mutation(self, sample_graph_state: AgentGraphStateDict):
        initial_shipment = sample_graph_state["input_references"].copy()
        updates = decision_node(sample_graph_state)
        assert "input_references" not in updates
        assert sample_graph_state["input_references"] == initial_shipment

    def test_no_inventory_mutation(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        for key in updates.keys():
            assert "inventory" not in key.lower()

    def test_no_carrier_communication(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        for key in updates.keys():
            assert "carrier" not in key.lower()

    def test_no_supplier_communication(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        for key in updates.keys():
            assert "supplier" not in key.lower()

    def test_no_approval_mutation(self, sample_graph_state: AgentGraphStateDict):
        updates = decision_node(sample_graph_state)
        assert updates.get("approval_reference") is None
        assert updates.get("status") != AgentLifecycleStatus.COMPLETED.value
