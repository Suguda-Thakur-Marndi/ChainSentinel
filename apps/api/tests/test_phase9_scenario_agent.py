"""Comprehensive test suite for RiskWise 2.0 Phase 9 Step 7: Scenario Agent Integration.

Verifies:
1. ScenarioRequest contracts, Pydantic validation, extra="forbid", and forbidden arbitrary inputs.
2. ScenarioParameter contracts, bounds, units, NaN/inf rejection, and tenant validation.
3. ScenarioTrigger contracts, condition syntax safety (no eval/exec), and threshold checks.
4. ScenarioConstraint contracts and deterministic serialization.
5. ScenarioDefinition and ScenarioResult contracts, ready/insufficient consistency.
6. Deterministic scenario ID generation (UUIDv5) and canonical SHA-256 fingerprinting.
7. Deterministic ScenarioGenerator: conversion of upstream PredictionResult without fabrication.
8. Handling of unavailable prediction without fabricating values (INSUFFICIENT_EVIDENCE).
9. Risk and research integration: context preservation, immutability, no prose-to-number heuristics.
10. State ownership: writes only SCENARIO-owned fields (scenario_id, scenario_reference, scenario_result).
11. LangGraph node registration, telemetry emission, and StateGraph pipeline execution.
12. Multi-tenant isolation and fail-closed security invariants across all references.
13. Security scrubbing: rejection of credentials, bearer tokens, and chain-of-thought monologue.
14. Read-only safety: zero operational side effects, no mutation of shipments, inventory, or routes.
15. No probability invention from risk scores or prediction confidence.
16. No simulation or optimization executed at the scenario definition boundary.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    AUTHORITATIVE_FIELD_OWNERS,
    AgentExecutionContext,
    AgentFinding,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentLimitation,
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
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.registry import NodeRegistry
from app.agents.scenario import (
    SCENARIO_NODE_CONTRACT,
    InsufficientEvidenceError,
    InvalidScenarioParameterError,
    InvalidScenarioRequestError,
    ScenarioAgent,
    ScenarioAgentError,
    ScenarioConstraint,
    ScenarioDefinition,
    ScenarioGenerationError,
    ScenarioGenerator,
    ScenarioParameter,
    ScenarioRequest,
    ScenarioResult,
    ScenarioStatus,
    ScenarioTenantIsolationError,
    ScenarioTrigger,
    ScenarioType,
    compute_scenario_fingerprint,
    generate_deterministic_scenario_id,
    scenario_node,
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
        role="ANALYST",
        roles=["analyst"],
        permissions=["read", "scenario_evaluate"],
    )


@pytest.fixture
def sample_parameter() -> ScenarioParameter:
    return ScenarioParameter(
        name="delay_minutes",
        value=120.0,
        unit="minutes",
        source="PredictionAgent:pred_abc123",
        source_type="PREDICTION",
        evidence_references=["ev_sig_001", "ev_sig_002"],
        provenance={"model_name": "delay_estimator_v1"},
    )


@pytest.fixture
def sample_trigger() -> ScenarioTrigger:
    return ScenarioTrigger(
        trigger_type="PREDICTED_DELAY_THRESHOLD",
        source_reference="PredictionAgent:pred_abc123",
        condition="GREATER_THAN",
        threshold=60.0,
        evidence_references=["ev_sig_001"],
    )


@pytest.fixture
def sample_constraint() -> ScenarioConstraint:
    return ScenarioConstraint(
        constraint_type="MAXIMUM_DELAY",
        name="max_allowable_delay",
        value=360.0,
        unit="minutes",
    )


@pytest.fixture
def sample_prediction_result() -> Dict[str, Any]:
    return {
        "prediction_id": "pred_test_12345",
        "organization_id": "org_test_123",
        "prediction_type": "SHIPMENT_DELAY",
        "target": "delay_minutes",
        "predicted_value": 95.0,
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
def sample_scenario_request(sample_prediction_result: Dict[str, Any]) -> ScenarioRequest:
    return ScenarioRequest(
        scenario_id="scen_custom_123",
        organization_id="org_test_123",
        shipment_id="ship_001",
        scenario_type=ScenarioType.SHIPMENT_DELAY,
        target_reference="ship_001",
        risk_assessment_id="risk_assess_999",
        risk_assessment_reference={
            "assessment_id": "risk_assess_999",
            "organization_id": "org_test_123",
            "risk_score": 75.0,
            "risk_level": "HIGH",
            "evidence_ids": ["ev_sig_001"],
        },
        prediction_id="pred_test_12345",
        prediction_reference=sample_prediction_result,
        prediction_result=sample_prediction_result,
        evidence_references=["ev_sig_001", "ev_sig_002"],
        horizon_hours=24.0,
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
    )


@pytest.fixture
def sample_graph_state(sample_prediction_result: Dict[str, Any]) -> AgentGraphStateDict:
    return {
        "run_id": "run_test_001",
        "organization_id": "org_test_123",
        "actor_id": "usr_test_456",
        "request_id": "req_test_789",
        "correlation_id": "corr_test_001",
        "trace_id": "trace_test_002",
        "objective": "Investigate shipping disruption on Route 99",
        "input_reference": "ship_001",
        "input_references": {"shipment_id": "ship_001"},
        "current_stage": AgentStage.PREDICTION.value,
        "current_node": "prediction_agent",
        "status": AgentLifecycleStatus.RUNNING.value,
        "step_count": 4,
        "evidence_bundle_id": "bundle_test_001",
        "evidence_references": ["ev_sig_001", "ev_sig_002"],
        "citation_references": ["cite_001"],
        "risk_assessment_id": "risk_assess_999",
        "risk_assessment_reference": {
            "assessment_id": "risk_assess_999",
            "organization_id": "org_test_123",
            "assessment_fingerprint": "fp_assess_999_valid",
            "risk_score": 75.0,
            "risk_level": "HIGH",
            "factor_count": 1,
        },
        "risk_alert_references": [],
        "recommendation_references": [],
        "prediction_id": "pred_test_12345",
        "prediction_reference": sample_prediction_result,
        "prediction_result": sample_prediction_result,
        "scenario_id": None,
        "scenario_reference": None,
        "scenario_result": None,
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
        "metadata": {},
        "state_schema_version": "1.0.0",
    }


# ==============================================================================
# GROUP 1: SCENARIO CONTRACTS & PYDANTIC VALIDATION (8 tests)
# ==============================================================================

class TestScenarioContracts:
    def test_valid_scenario_request(self, sample_scenario_request: ScenarioRequest):
        assert sample_scenario_request.organization_id == "org_test_123"
        assert sample_scenario_request.scenario_type == ScenarioType.SHIPMENT_DELAY
        assert sample_scenario_request.horizon_hours == 24.0

    def test_scenario_request_extra_forbid(self, sample_scenario_request: ScenarioRequest):
        data = sample_scenario_request.model_dump()
        data["arbitrary_injected_payload"] = "malicious_attempt"
        with pytest.raises(ValidationError):
            ScenarioRequest.model_validate(data)

    def test_scenario_request_missing_organization_id(self, sample_scenario_request: ScenarioRequest):
        data = sample_scenario_request.model_dump()
        data["organization_id"] = "   "
        with pytest.raises((ValidationError, InvalidScenarioRequestError)):
            ScenarioRequest.model_validate(data)

    def test_unsupported_scenario_type_rejected(self, sample_scenario_request: ScenarioRequest):
        data = sample_scenario_request.model_dump()
        data["scenario_type"] = "CYBER_ATTACK_SIMULATION"
        with pytest.raises(ValidationError):
            ScenarioRequest.model_validate(data)

    def test_scenario_definition_valid(self, sample_parameter: ScenarioParameter):
        definition = ScenarioDefinition(
            scenario_id="scen_001",
            organization_id="org_test_123",
            scenario_type=ScenarioType.SHIPMENT_DELAY,
            target_reference="ship_001",
            parameters=[sample_parameter],
            fingerprint="abc123def456",
        )
        assert definition.scenario_id == "scen_001"
        assert len(definition.parameters) == 1

    def test_scenario_definition_empty_parameters_rejected(self):
        with pytest.raises(ValidationError):
            ScenarioDefinition(
                scenario_id="scen_001",
                organization_id="org_test_123",
                scenario_type=ScenarioType.SHIPMENT_DELAY,
                target_reference="ship_001",
                parameters=[],
                fingerprint="abc123def456",
            )

    def test_scenario_result_ready_requires_definition_and_fingerprint(self):
        with pytest.raises(InvalidScenarioRequestError):
            ScenarioResult(
                scenario_id="scen_001",
                organization_id="org_test_123",
                status=ScenarioStatus.READY.value,
                scenario_definition=None,
                fingerprint=None,
            )

    def test_scenario_result_tenant_mismatch_with_definition(self, sample_parameter: ScenarioParameter):
        definition = ScenarioDefinition(
            scenario_id="scen_001",
            organization_id="org_other_tenant",
            scenario_type=ScenarioType.SHIPMENT_DELAY,
            target_reference="ship_001",
            parameters=[sample_parameter],
            fingerprint="fp123",
        )
        with pytest.raises(ScenarioTenantIsolationError):
            ScenarioResult(
                scenario_id="scen_001",
                organization_id="org_test_123",
                status=ScenarioStatus.READY.value,
                scenario_definition=definition,
                fingerprint="fp123",
            )


# ==============================================================================
# GROUP 2: PARAMETERS & HORIZON VALIDATION (8 tests)
# ==============================================================================

class TestParametersAndHorizon:
    def test_valid_scenario_parameter(self, sample_parameter: ScenarioParameter):
        assert sample_parameter.name == "delay_minutes"
        assert sample_parameter.value == 120.0
        assert sample_parameter.unit == "minutes"

    def test_parameter_nan_value_rejected(self):
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioParameter(
                name="delay_minutes",
                value=float("nan"),
                unit="minutes",
                source="test",
                source_type="test",
            )

    def test_parameter_inf_value_rejected(self):
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioParameter(
                name="delay_minutes",
                value=float("inf"),
                unit="minutes",
                source="test",
                source_type="test",
            )

    def test_negative_horizon_rejected(self, sample_scenario_request: ScenarioRequest):
        data = sample_scenario_request.model_dump()
        data["horizon_hours"] = -5.0
        with pytest.raises((ValidationError, InvalidScenarioRequestError)):
            ScenarioRequest.model_validate(data)

    def test_nan_horizon_rejected(self, sample_scenario_request: ScenarioRequest):
        data = sample_scenario_request.model_dump()
        data["horizon_hours"] = float("nan")
        with pytest.raises((ValidationError, InvalidScenarioRequestError)):
            ScenarioRequest.model_validate(data)

    def test_effective_timestamp_ordering_violation(self, sample_parameter: ScenarioParameter):
        t_early = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        t_late = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioDefinition(
                scenario_id="scen_001",
                organization_id="org_test_123",
                scenario_type=ScenarioType.SHIPMENT_DELAY,
                target_reference="ship_001",
                parameters=[sample_parameter],
                effective_from=t_late,
                effective_until=t_early,
                fingerprint="fp123",
            )

    def test_parameter_string_value_valid(self):
        param = ScenarioParameter(
            name="disrupted_corridor",
            value="Suez Canal",
            unit="name",
            source="manual",
            source_type="EXPLICIT",
        )
        assert param.value == "Suez Canal"

    def test_parameter_boolean_value_valid(self):
        param = ScenarioParameter(
            name="port_open",
            value=False,
            unit="status",
            source="sensor",
            source_type="EXPLICIT",
        )
        assert param.value is False


# ==============================================================================
# GROUP 3: TRIGGER & CONSTRAINT VALIDATION (8 tests)
# ==============================================================================

class TestTriggerAndConstraint:
    def test_valid_trigger(self, sample_trigger: ScenarioTrigger):
        assert sample_trigger.trigger_type == "PREDICTED_DELAY_THRESHOLD"
        assert sample_trigger.condition == "GREATER_THAN"
        assert sample_trigger.threshold == 60.0

    def test_trigger_rejects_eval_injection(self):
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioTrigger(
                trigger_type="DISRUPTION",
                condition="eval('__import__(\"os\").system(\"ls\")')",
                threshold=10.0,
            )

    def test_trigger_rejects_exec_injection(self):
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioTrigger(
                trigger_type="DISRUPTION",
                condition="exec('rm -rf /')",
                threshold=10.0,
            )

    def test_trigger_threshold_nan_rejected(self):
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioTrigger(
                trigger_type="DELAY",
                condition="GREATER_THAN",
                threshold=float("nan"),
            )

    def test_valid_constraint(self, sample_constraint: ScenarioConstraint):
        assert sample_constraint.constraint_type == "MAXIMUM_DELAY"
        assert sample_constraint.value == 360.0

    def test_constraint_nan_rejected(self):
        with pytest.raises((ValidationError, InvalidScenarioParameterError)):
            ScenarioConstraint(
                constraint_type="MAXIMUM_DELAY",
                name="max_delay",
                value=float("nan"),
            )

    def test_trigger_condition_uppercased(self):
        trig = ScenarioTrigger(
            trigger_type="DELAY",
            condition="greater_than",
            threshold=15.0,
        )
        assert trig.condition == "GREATER_THAN"

    def test_constraint_string_value_valid(self):
        con = ScenarioConstraint(
            constraint_type="AFFECTED_ENTITIES_ONLY",
            name="target_carrier",
            value="Carrier_X",
        )
        assert con.value == "Carrier_X"


# ==============================================================================
# GROUP 4: DETERMINISTIC IDENTITY & FINGERPRINTING (8 tests)
# ==============================================================================

class TestDeterministicIdentityAndFingerprinting:
    def test_generate_deterministic_scenario_id_reproducibility(self):
        id1 = generate_deterministic_scenario_id(
            organization_id="org_test_123",
            scenario_type="SHIPMENT_DELAY",
            target_reference="ship_001",
            parameter_fingerprint="delay_minutes=120.0minutes",
            upstream_prediction_id="pred_123",
            upstream_risk_id="risk_999",
        )
        id2 = generate_deterministic_scenario_id(
            organization_id="org_test_123",
            scenario_type="SHIPMENT_DELAY",
            target_reference="ship_001",
            parameter_fingerprint="delay_minutes=120.0minutes",
            upstream_prediction_id="pred_123",
            upstream_risk_id="risk_999",
        )
        assert id1 == id2
        assert uuid.UUID(id1).version == 5

    def test_scenario_id_changes_with_different_tenant(self):
        id1 = generate_deterministic_scenario_id(
            organization_id="org_1",
            scenario_type="SHIPMENT_DELAY",
            target_reference="ship_001",
            parameter_fingerprint="fp1",
        )
        id2 = generate_deterministic_scenario_id(
            organization_id="org_2",
            scenario_type="SHIPMENT_DELAY",
            target_reference="ship_001",
            parameter_fingerprint="fp1",
        )
        assert id1 != id2

    def test_scenario_id_changes_with_different_parameters(self):
        id1 = generate_deterministic_scenario_id(
            organization_id="org_1",
            scenario_type="SHIPMENT_DELAY",
            target_reference="ship_001",
            parameter_fingerprint="delay=60",
        )
        id2 = generate_deterministic_scenario_id(
            organization_id="org_1",
            scenario_type="SHIPMENT_DELAY",
            target_reference="ship_001",
            parameter_fingerprint="delay=120",
        )
        assert id1 != id2

    def test_empty_tenant_in_scenario_id_rejected(self):
        with pytest.raises(ScenarioTenantIsolationError):
            generate_deterministic_scenario_id(
                organization_id="",
                scenario_type="SHIPMENT_DELAY",
                target_reference="ship_001",
                parameter_fingerprint="fp1",
            )

    def test_compute_scenario_fingerprint_reproducibility(self):
        params = [{"name": "delay_minutes", "value": 90.0, "unit": "minutes"}]
        fp1 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_1", params)
        fp2 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_1", params)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex string

    def test_fingerprint_changes_with_parameter_value(self):
        p1 = [{"name": "delay_minutes", "value": 90.0}]
        p2 = [{"name": "delay_minutes", "value": 180.0}]
        fp1 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_1", p1)
        fp2 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_1", p2)
        assert fp1 != fp2

    def test_fingerprint_insensitive_to_parameter_ordering(self):
        p1 = [{"name": "a", "value": 1}, {"name": "b", "value": 2}]
        p2 = [{"name": "b", "value": 2}, {"name": "a", "value": 1}]
        fp1 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_1", p1)
        fp2 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_1", p2)
        assert fp1 == fp2

    def test_fingerprint_changes_with_different_target(self):
        params = [{"name": "delay", "value": 10}]
        fp1 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_A", params)
        fp2 = compute_scenario_fingerprint("org_test", "SHIPMENT_DELAY", "target_B", params)
        assert fp1 != fp2


# ==============================================================================
# GROUP 5: DETERMINISTIC SCENARIO GENERATOR (8 tests)
# ==============================================================================

class TestScenarioGenerator:
    def test_generate_from_valid_prediction(self, sample_scenario_request: ScenarioRequest):
        result, limitations = ScenarioGenerator.generate(sample_scenario_request)
        assert result.status == ScenarioStatus.READY.value
        assert result.scenario_definition is not None
        assert result.scenario_definition.scenario_type == ScenarioType.SHIPMENT_DELAY
        # Verify delay_minutes extracted from prediction result (95.0)
        delay_param = next(p for p in result.scenario_definition.parameters if p.name == "delay_minutes")
        assert delay_param.value == 95.0
        assert delay_param.unit == "minutes"
        assert delay_param.source == "PredictionAgent:pred_test_12345"

    def test_generate_same_inputs_produce_identical_scenario(self, sample_scenario_request: ScenarioRequest):
        res1, _ = ScenarioGenerator.generate(sample_scenario_request)
        res2, _ = ScenarioGenerator.generate(sample_scenario_request)
        assert res1.scenario_id == res2.scenario_id
        assert res1.fingerprint == res2.fingerprint

    def test_generate_with_unavailable_prediction_yields_insufficient_evidence(self, sample_scenario_request: ScenarioRequest):
        req_dict = sample_scenario_request.model_dump()
        req_dict["prediction_result"]["status"] = "NOT_AVAILABLE"
        req_dict["prediction_result"]["predicted_value"] = None
        req = ScenarioRequest.model_validate(req_dict)

        result, limitations = ScenarioGenerator.generate(req)
        assert result.status == ScenarioStatus.INSUFFICIENT_EVIDENCE.value
        assert result.scenario_definition is None
        assert len(limitations) > 0
        assert any(lim.category == LimitationCategory.INSUFFICIENT_EVIDENCE for lim in limitations)

    def test_generate_with_failed_prediction_yields_insufficient_evidence(self, sample_scenario_request: ScenarioRequest):
        req_dict = sample_scenario_request.model_dump()
        req_dict["prediction_result"]["status"] = "FAILED"
        req = ScenarioRequest.model_validate(req_dict)

        result, limitations = ScenarioGenerator.generate(req)
        assert result.status == ScenarioStatus.INSUFFICIENT_EVIDENCE.value
        assert result.scenario_definition is None

    def test_generate_with_explicit_parameters_overrides_empty_prediction(self):
        explicit_param = ScenarioParameter(
            name="port_closure_days",
            value=3,
            unit="days",
            source="RiskAssessment:risk_999",
            source_type="RISK_ENGINE",
            evidence_references=["ev_001"],
        )
        req = ScenarioRequest(
            organization_id="org_test_123",
            target_reference="port_rotterdam",
            scenario_type=ScenarioType.PORT_DISRUPTION,
            parameters=[explicit_param],
            evidence_references=["ev_001"],
        )
        result, limitations = ScenarioGenerator.generate(req)
        assert result.status == ScenarioStatus.READY.value
        assert result.scenario_definition is not None
        assert len(result.scenario_definition.parameters) == 1
        assert result.scenario_definition.parameters[0].name == "port_closure_days"

    def test_generate_no_evidence_or_parameters_returns_insufficient_evidence(self):
        req = ScenarioRequest(
            organization_id="org_test_123",
            target_reference="ship_999",
            scenario_type=ScenarioType.SHIPMENT_DELAY,
        )
        result, limitations = ScenarioGenerator.generate(req)
        assert result.status == ScenarioStatus.INSUFFICIENT_EVIDENCE.value
        assert result.scenario_definition is None

    def test_generate_preserves_evidence_references(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        assert "ev_sig_001" in result.evidence_references
        assert "ev_sig_002" in result.evidence_references

    def test_generate_preserves_upstream_references(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        assert result.upstream_references.get("prediction_id") == "pred_test_12345"
        assert result.upstream_references.get("risk_assessment_id") == "risk_assess_999"


# ==============================================================================
# GROUP 6: SCENARIO AGENT ORCHESTRATION & FINDINGS (8 tests)
# ==============================================================================

class TestScenarioAgent:
    def test_agent_execution_success(self, sample_scenario_request: ScenarioRequest):
        agent = ScenarioAgent()
        result, findings = agent.execute(sample_scenario_request)
        assert result.status == ScenarioStatus.READY.value
        assert len(findings) == 1
        finding = findings[0]
        assert finding.category == "SCENARIO_DEFINITION"
        assert finding.created_by_node == "scenario_agent"
        assert finding.confidence == 1.0
        assert "delay_minutes=95.0 minutes" in finding.summary

    def test_agent_execution_insufficient_evidence_finding(self, sample_scenario_request: ScenarioRequest):
        req_dict = sample_scenario_request.model_dump()
        req_dict["prediction_result"] = None
        req_dict["prediction_reference"] = None
        req = ScenarioRequest.model_validate(req_dict)

        agent = ScenarioAgent()
        result, findings = agent.execute(req)
        assert result.status == ScenarioStatus.INSUFFICIENT_EVIDENCE.value
        assert len(findings) == 1
        finding = findings[0]
        assert finding.category == "INSUFFICIENT_EVIDENCE"
        assert "could not be computed" in finding.summary

    def test_agent_missing_organization_id_raises_error(self, sample_scenario_request: ScenarioRequest):
        req = sample_scenario_request
        object.__setattr__(req, "organization_id", "")
        agent = ScenarioAgent()
        with pytest.raises(InvalidScenarioRequestError):
            agent.execute(req)

    def test_agent_custom_generator_injection(self, sample_scenario_request: ScenarioRequest):
        custom_gen = ScenarioGenerator()
        agent = ScenarioAgent(generator=custom_gen)
        result, _ = agent.execute(sample_scenario_request)
        assert result.status == ScenarioStatus.READY.value

    def test_agent_finding_contains_evidence_ids(self, sample_scenario_request: ScenarioRequest):
        agent = ScenarioAgent()
        _, findings = agent.execute(sample_scenario_request)
        assert "ev_sig_001" in findings[0].evidence_ids

    def test_agent_finding_contains_scenario_source_ref(self, sample_scenario_request: ScenarioRequest):
        agent = ScenarioAgent()
        result, findings = agent.execute(sample_scenario_request)
        assert f"scenario:{result.scenario_id}" in findings[0].source_references

    def test_agent_finding_severity_info_for_ready(self, sample_scenario_request: ScenarioRequest):
        agent = ScenarioAgent()
        _, findings = agent.execute(sample_scenario_request)
        assert findings[0].severity == "INFO"

    def test_agent_finding_severity_low_for_insufficient(self):
        req = ScenarioRequest(
            organization_id="org_test_123",
            target_reference="target",
            scenario_type=ScenarioType.SHIPMENT_DELAY,
        )
        agent = ScenarioAgent()
        _, findings = agent.execute(req)
        assert findings[0].severity == "LOW"


# ==============================================================================
# GROUP 7: LANGGRAPH NODE & PIPELINE EXECUTION (8 tests)
# ==============================================================================

class TestLangGraphNodeAndExecution:
    def test_scenario_node_contract_properties(self):
        assert SCENARIO_NODE_CONTRACT.node_id == "scenario_agent"
        assert SCENARIO_NODE_CONTRACT.stage == AgentStage.SCENARIO_ANALYSIS
        assert SCENARIO_NODE_CONTRACT.is_side_effecting is False
        assert SCENARIO_NODE_CONTRACT.side_effect_type == ToolSideEffectType.READ_ONLY
        assert SCENARIO_NODE_CONTRACT.requires_evidence is True
        assert "scenario_id" in SCENARIO_NODE_CONTRACT.output_keys
        assert "scenario_result" in SCENARIO_NODE_CONTRACT.output_keys

    def test_scenario_node_execution_success(self, sample_graph_state: AgentGraphStateDict):
        updates = scenario_node(sample_graph_state)
        assert updates["scenario_id"] is not None
        assert updates["scenario_reference"]["status"] == "READY"
        assert updates["current_stage"] == AgentStage.SCENARIO_ANALYSIS.value
        assert updates["current_node"] == "scenario_agent"
        assert updates["step_count"] == sample_graph_state["step_count"] + 1

    def test_scenario_node_missing_organization_raises_error(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["organization_id"] = ""
        with pytest.raises(ScenarioTenantIsolationError):
            scenario_node(sample_graph_state)

    def test_scenario_node_emits_telemetry_on_success(self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch):
        telemetry_records: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

        scenario_node(sample_graph_state)
        assert len(telemetry_records) == 1
        telem = telemetry_records[0]
        assert telem.node_name == "scenario_agent"
        assert telem.status == "SUCCESS"
        assert telem.organization_id == "org_test_123"

    def test_scenario_node_emits_telemetry_on_failure(self, sample_graph_state: AgentGraphStateDict, monkeypatch: pytest.MonkeyPatch):
        telemetry_records: List[NodeExecutionTelemetry] = []
        monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

        sample_graph_state["organization_id"] = ""
        with pytest.raises(ScenarioTenantIsolationError):
            scenario_node(sample_graph_state)

        assert len(telemetry_records) == 1
        telem = telemetry_records[0]
        assert telem.node_name == "scenario_agent"
        assert telem.status == "FAILED"
        assert telem.error_code == "ScenarioTenantIsolationError"

    def test_scenario_node_registered_in_registry(self):
        reg = NodeRegistry()
        reg.register_node(SCENARIO_NODE_CONTRACT, scenario_node)
        assert reg.has_node("scenario_agent")
        entry = reg.get_node("scenario_agent")
        assert entry.contract.stage == AgentStage.SCENARIO_ANALYSIS

    def test_apply_state_update_with_scenario_updates(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        updates = scenario_node(sample_graph_state)
        new_state = apply_state_update(
            current_state=state_obj,
            update_payload=updates,
            writer_node_id="scenario_agent",
            writer_stage=AgentStage.SCENARIO_ANALYSIS,
        )
        assert new_state.scenario_id == updates["scenario_id"]
        assert new_state.scenario_reference == updates["scenario_reference"]
        assert new_state.current_stage == AgentStage.SCENARIO_ANALYSIS
        assert new_state.current_node == "scenario_agent"

    def test_pipeline_prediction_to_scenario_to_termination(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        # 1. Execute scenario node
        scen_updates = scenario_node(sample_graph_state)
        post_scen_state = apply_state_update(
            current_state=state_obj,
            update_payload=scen_updates,
            writer_node_id="scenario_agent",
            writer_stage=AgentStage.SCENARIO_ANALYSIS,
        )
        assert post_scen_state.current_stage == AgentStage.SCENARIO_ANALYSIS

        # 2. Transition to termination
        term_updates = {
            "current_stage": AgentStage.TERMINATION.value,
            "current_node": "termination",
            "status": "COMPLETED",
            "completed_at": datetime.now(timezone.utc),
            "termination_reason": "Scenario pipeline complete.",
        }
        final_state = apply_state_update(
            current_state=post_scen_state,
            update_payload=term_updates,
            writer_node_id="termination",
            writer_stage=AgentStage.TERMINATION,
        )
        assert final_state.current_stage == AgentStage.TERMINATION
        assert final_state.scenario_id == scen_updates["scenario_id"]
        assert final_state.status == AgentLifecycleStatus.COMPLETED


# ==============================================================================
# GROUP 8: STATE OWNERSHIP & WRITE BOUNDARIES (8 tests)
# ==============================================================================

class TestStateOwnershipAndWriteBoundaries:
    def test_scenario_agent_owns_scenario_fields(self):
        assert AUTHORITATIVE_FIELD_OWNERS["scenario_id"] == {AgentStage.SCENARIO_ANALYSIS}
        assert AUTHORITATIVE_FIELD_OWNERS["scenario_reference"] == {AgentStage.SCENARIO_ANALYSIS}
        assert AUTHORITATIVE_FIELD_OWNERS["scenario_result"] == {AgentStage.SCENARIO_ANALYSIS}

    def test_scenario_agent_valid_update_accepted(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        validate_state_update(
            current_state=state_obj,
            update_payload={"scenario_id": "scen_12345"},
            writer_node_id="scenario_agent",
            writer_stage=AgentStage.SCENARIO_ANALYSIS,
        )

    def test_scenario_agent_cannot_update_prediction_fields(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"prediction_id": "alien_pred_id"},
                writer_node_id="scenario_agent",
                writer_stage=AgentStage.SCENARIO_ANALYSIS,
            )

    def test_scenario_agent_cannot_update_risk_fields(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"risk_assessment_id": "alien_risk_id"},
                writer_node_id="scenario_agent",
                writer_stage=AgentStage.SCENARIO_ANALYSIS,
            )

    def test_scenario_agent_cannot_update_research_fields(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"evidence_bundle_id": "alien_bundle_id"},
                writer_node_id="scenario_agent",
                writer_stage=AgentStage.SCENARIO_ANALYSIS,
            )

    def test_prediction_agent_cannot_update_scenario_fields(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"scenario_id": "scen_unauth"},
                writer_node_id="prediction_agent",
                writer_stage=AgentStage.PREDICTION,
            )

    def test_scenario_agent_cannot_mutate_organization_id(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentTenantIsolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"organization_id": "org_hijacked"},
                writer_node_id="scenario_agent",
                writer_stage=AgentStage.SCENARIO_ANALYSIS,
            )

    def test_scenario_agent_cannot_mutate_run_id(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentStateOwnershipViolationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"run_id": "run_tampered"},
                writer_node_id="scenario_agent",
                writer_stage=AgentStage.SCENARIO_ANALYSIS,
            )


# ==============================================================================
# GROUP 9: MULTI-TENANT ISOLATION (8 tests)
# ==============================================================================

class TestMultiTenantIsolation:
    def test_cross_tenant_prediction_in_request_rejected(self, sample_scenario_request: ScenarioRequest):
        req_dict = sample_scenario_request.model_dump()
        req_dict["prediction_result"]["organization_id"] = "org_foreign_999"
        with pytest.raises((ValidationError, ScenarioTenantIsolationError)):
            ScenarioRequest.model_validate(req_dict)

    def test_cross_tenant_risk_in_request_rejected(self, sample_scenario_request: ScenarioRequest):
        req_dict = sample_scenario_request.model_dump()
        req_dict["risk_assessment_reference"]["organization_id"] = "org_foreign_999"
        with pytest.raises((ValidationError, ScenarioTenantIsolationError)):
            ScenarioRequest.model_validate(req_dict)

    def test_cross_tenant_evidence_reference_rejected(self, sample_scenario_request: ScenarioRequest):
        req_dict = sample_scenario_request.model_dump()
        req_dict["evidence_references"] = ["org_foreign_999:evidence_001"]
        with pytest.raises((ValidationError, ScenarioTenantIsolationError)):
            ScenarioRequest.model_validate(req_dict)

    def test_cross_tenant_scenario_result_in_state_rejected(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["scenario_result"] = {
            "scenario_id": "scen_123",
            "organization_id": "org_foreign_tenant",
        }
        with pytest.raises(AgentTenantIsolationError):
            AgentGraphState.model_validate(sample_graph_state)

    def test_cross_tenant_scenario_reference_in_state_rejected(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["scenario_reference"] = {
            "scenario_id": "scen_123",
            "organization_id": "org_foreign_tenant",
        }
        with pytest.raises(AgentTenantIsolationError):
            AgentGraphState.model_validate(sample_graph_state)

    def test_generator_rejects_cross_tenant_prediction_payload(self, sample_scenario_request: ScenarioRequest):
        sample_scenario_request.prediction_result["organization_id"] = "org_attacker"
        with pytest.raises(ScenarioTenantIsolationError):
            ScenarioGenerator.generate(sample_scenario_request)

    def test_generator_rejects_cross_tenant_risk_payload(self, sample_scenario_request: ScenarioRequest):
        sample_scenario_request.risk_assessment_reference["organization_id"] = "org_attacker"
        with pytest.raises(ScenarioTenantIsolationError):
            ScenarioGenerator.generate(sample_scenario_request)

    def test_node_rejects_empty_tenant(self, sample_graph_state: AgentGraphStateDict):
        sample_graph_state["organization_id"] = "  "
        with pytest.raises(ScenarioTenantIsolationError):
            scenario_node(sample_graph_state)


# ==============================================================================
# GROUP 10: SECURITY SCRUBBING & REASONING PROTECTION (8 tests)
# ==============================================================================

class TestSecurityScrubbing:
    def test_bearer_token_in_parameter_value_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            ScenarioParameter(
                name="auth_param",
                value="Bearer secret_token_xyz123",
                source="test",
                source_type="test",
            )

    def test_password_in_provenance_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            ScenarioParameter(
                name="delay",
                value=60,
                source="test",
                source_type="test",
                provenance={"db_password": "super_secret_value"},
            )

    def test_api_key_in_provenance_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            ScenarioParameter(
                name="delay",
                value=60,
                source="test",
                source_type="test",
                provenance={"api_key": "sk-1234567890abcdef"},
            )

    def test_chain_of_thought_key_in_provenance_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            ScenarioParameter(
                name="delay",
                value=60,
                source="test",
                source_type="test",
                provenance={"chain_of_thought": "My reasoning step"},
            )

    def test_private_reasoning_in_text_rejected(self):
        with pytest.raises((ValidationError, AgentValidationError)):
            ScenarioParameter(
                name="reasoning",
                value="Contains internal_monologue text here",
                source="test",
                source_type="test",
            )

    def test_sensitive_value_in_state_update_rejected(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        with pytest.raises(AgentValidationError):
            validate_state_update(
                current_state=state_obj,
                update_payload={"findings": {"token": "bearer secret_123"}},
                writer_node_id="scenario_agent",
                writer_stage=AgentStage.SCENARIO_ANALYSIS,
            )

    def test_clean_parameter_provenance_accepted(self):
        param = ScenarioParameter(
            name="delay_minutes",
            value=45,
            source="PredictionAgent:p1",
            source_type="PREDICTION",
            provenance={"algorithm": "gradient_boosting", "version": "1.0"},
        )
        assert param.provenance["algorithm"] == "gradient_boosting"

    def test_clean_definition_provenance_accepted(self, sample_parameter: ScenarioParameter):
        definition = ScenarioDefinition(
            scenario_id="scen_clean",
            organization_id="org_test_123",
            target_reference="target",
            parameters=[sample_parameter],
            fingerprint="fp123",
            provenance={"generator": "ScenarioGenerator"},
        )
        assert definition.provenance["generator"] == "ScenarioGenerator"


# ==============================================================================
# GROUP 11: TOPOLOGY & STAGE TRANSITIONS (8 tests)
# ==============================================================================

class TestTopologyAndTransitions:
    def test_prediction_to_scenario_is_valid_transition(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.PREDICTION, AgentStage.SCENARIO_ANALYSIS
        ) is True

    def test_scenario_to_termination_is_valid_transition(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.SCENARIO_ANALYSIS, AgentStage.TERMINATION
        ) is True

    def test_scenario_to_decision_is_valid_transition(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.SCENARIO_ANALYSIS, AgentStage.DECISION
        ) is True

    def test_scenario_backward_to_prediction_is_illegal(self):
        assert StageTransitionValidator.is_valid_transition(
            AgentStage.SCENARIO_ANALYSIS, AgentStage.PREDICTION
        ) is False

    def test_scenario_backward_to_research_is_illegal(self):
        with pytest.raises(AgentStageTransitionError):
            StageTransitionValidator.validate_transition(
                AgentStage.SCENARIO_ANALYSIS, AgentStage.RESEARCH
            )

    def test_scenario_backward_to_initialization_is_illegal(self):
        with pytest.raises(AgentStageTransitionError):
            StageTransitionValidator.validate_transition(
                AgentStage.SCENARIO_ANALYSIS, AgentStage.INITIALIZATION
            )

    def test_stage_scenario_alias_resolves_to_scenario_analysis(self):
        assert AgentStage.SCENARIO == AgentStage.SCENARIO_ANALYSIS
        assert AgentStage("SCENARIO") == AgentStage.SCENARIO_ANALYSIS

    def test_allowed_stage_transitions_contains_scenario_analysis(self):
        assert AgentStage.SCENARIO_ANALYSIS in ALLOWED_STAGE_TRANSITIONS[AgentStage.PREDICTION]
        assert AgentStage.TERMINATION in ALLOWED_STAGE_TRANSITIONS[AgentStage.SCENARIO_ANALYSIS]


# ==============================================================================
# GROUP 12: READ-ONLY & NON-SIDE-EFFECT SAFETY (6 tests)
# ==============================================================================

class TestReadOnlyAndNonSideEffect:
    def test_contract_is_read_only(self):
        assert SCENARIO_NODE_CONTRACT.is_side_effecting is False
        assert SCENARIO_NODE_CONTRACT.side_effect_type == ToolSideEffectType.READ_ONLY

    def test_scenario_node_does_not_set_approval_flag(self, sample_graph_state: AgentGraphStateDict):
        updates = scenario_node(sample_graph_state)
        assert updates.get("requires_human_approval") is None or updates.get("requires_human_approval") is False

    def test_scenario_node_does_not_modify_shipment_data(self, sample_graph_state: AgentGraphStateDict):
        initial_input = sample_graph_state["input_references"]
        scenario_node(sample_graph_state)
        assert sample_graph_state["input_references"] == initial_input

    def test_scenario_definition_does_not_contain_action_recommendations(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "recommended_actions" not in data
        assert "carrier_rerouting" not in data
        assert "action_plan" not in data

    def test_scenario_definition_contains_no_optimization_results(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "optimal_route" not in data
        assert "cost_savings" not in data
        assert "solver_status" not in data

    def test_scenario_agent_read_only_with_frozen_state(self, sample_graph_state: AgentGraphStateDict):
        state_obj = AgentGraphState.model_validate(sample_graph_state)
        updates = scenario_node(sample_graph_state)
        new_state = apply_state_update(
            current_state=state_obj,
            update_payload=updates,
            writer_node_id="scenario_agent",
            writer_stage=AgentStage.SCENARIO_ANALYSIS,
        )
        assert new_state.side_effect_allowed is False


# ==============================================================================
# GROUP 13: NO PROBABILITY INVENTION (5 tests)
# ==============================================================================

class TestNoProbabilityInvention:
    def test_delay_parameter_has_no_fabricated_probability(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        param = result.scenario_definition.parameters[0]
        data = param.model_dump()
        assert "probability" not in data
        assert "likelihood" not in data

    def test_scenario_definition_has_no_fabricated_probability(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.scenario_definition.model_dump()
        assert "probability" not in data
        assert "occurrence_probability" not in data

    def test_risk_score_is_not_converted_to_probability(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        # Even with risk_score = 75.0, no 0.75 probability is attached
        for param in result.scenario_definition.parameters:
            assert param.value != 0.75

    def test_prediction_confidence_is_not_converted_to_probability(self, sample_scenario_request: ScenarioRequest):
        sample_scenario_request.prediction_result["uncertainty"] = {
            "confidence_score": 0.85,
            "method": "MOCK",
        }
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "probability" not in data

    def test_explicit_probability_only_if_in_parameter_value(self):
        # Only if an explicit parameter value was provided as a calibrated probability
        param = ScenarioParameter(
            name="historical_congestion_frequency",
            value=0.35,
            unit="ratio",
            source="HistoricalAnalysis",
            source_type="EMPIRICAL",
        )
        assert param.value == 0.35


# ==============================================================================
# GROUP 14: NO SIMULATION / NO OPTIMIZATION BOUNDARY (5 tests)
# ==============================================================================

class TestNoSimulationOrOptimizationBoundary:
    def test_scenario_agent_does_not_compute_financial_impact(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "financial_impact_usd" not in data
        assert "estimated_cost" not in data

    def test_scenario_agent_does_not_propagate_network_delays(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "downstream_shipments_affected" not in data
        assert "network_delay_hours" not in data

    def test_scenario_agent_does_not_calculate_eta_changes(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "projected_eta" not in data
        assert "new_delivery_date" not in data

    def test_scenario_agent_does_not_invoke_or_tools(self, sample_scenario_request: ScenarioRequest):
        result, _ = ScenarioGenerator.generate(sample_scenario_request)
        data = result.model_dump()
        assert "objective_value" not in data
        assert "solver_time_ms" not in data

    def test_scenario_agent_does_not_mutate_inventory(self, sample_graph_state: AgentGraphStateDict):
        updates = scenario_node(sample_graph_state)
        assert "inventory" not in updates
        assert "inventory_allocations" not in updates
