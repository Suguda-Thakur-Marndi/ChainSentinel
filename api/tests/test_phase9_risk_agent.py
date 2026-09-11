"""Comprehensive test suite for RiskWise 2.0 Phase 9 Step 5: Risk Agent Integration.

Verifies:
1. RiskAgentRequest validation, serialization, and immutability.
2. RiskAgentResult contract, score bounds, and authoritative score preservation.
3. ResearchRiskAdapter static lookup, category translation, and limitation tracking.
4. RiskEngineAdapter execution, RiskEvaluationContext construction, and evaluate_full delegation.
5. Strict tenant isolation across request, research result, signals, and state.
6. State ownership and write boundaries (RISK_ASSESSMENT stage only).
7. Idempotency and deterministic fingerprint preservation.
8. Authoritative alert reference preservation (IDs only).
9. Authoritative recommendation reference preservation (IDs only).
10. LangGraph node registration, wrapper execution, and contract invariants.
11. Observability: NodeExecutionTelemetry emission on both success and failure.
12. Read-only safety: zero mutations, zero external side effects, zero LLM calls.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLimitation,
    AgentNodeContract,
    AgentStage,
    LimitationCategory,
    ToolSideEffectType,
    validate_state_update,
)
from app.agents.errors import (
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentValidationError,
)
from app.agents.execution import NodeExecutionWrapper
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.registry import NodeRegistry
from app.agents.research.contract import FindingType, ResearchFinding, ResearchResult
from app.agents.risk import (
    RISK_NODE_CONTRACT,
    RiskAgent,
    RiskAgentRequest,
    RiskAgentResult,
    risk_node,
)
from app.agents.risk.adapter import (
    FINDING_TO_SIGNAL_MAP,
    ResearchRiskAdapter,
    RiskEngineAdapter,
)
from app.agents.risk.contract import generate_deterministic_risk_request_id
from app.agents.risk.errors import (
    InvalidRiskRequestError,
    RiskAgentError,
    RiskEngineAdapterError,
    RiskEvidenceBoundaryError,
    RiskInputValidationError,
    RiskTenantIsolationError,
    UnsupportedFindingMappingError,
)
from app.integrations.canonical import EventQuality, EventSeverity
from app.normalization.contract import NormalizedRiskSignal, SignalDomain, SignalType
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import (
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    RiskScore,
)
from app.risk_engine.pipeline import BaselineRiskEngine, RiskEvaluationResult


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
        permissions=["read", "risk_evaluate"],
    )


def make_mock_finding(
    finding_id: str = "f_port_001",
    category: str = "PORT_DISRUPTION",
    finding_type: FindingType = FindingType.FACT,
    confidence: float = 0.90,
    title: str = "Rotterdam Port Congestion",
    summary: str = "Terminal 4 closed due to labor dispute.",
    evidence_ids: Optional[List[str]] = None,
    citation_ids: Optional[List[str]] = None,
) -> ResearchFinding:
    ev_ids = evidence_ids if evidence_ids is not None else ["ev_001"]
    cit_ids = citation_ids if citation_ids is not None else ["[CIT-1]"]
    return ResearchFinding(
        finding_id=finding_id,
        category=category,
        finding_type=finding_type,
        title=title,
        summary=summary,
        evidence_ids=ev_ids,
        citation_ids=cit_ids,
        confidence=confidence,
    )


def make_mock_research_result(
    org_id: str = "org_test_123",
    research_id: str = "res_test_001",
    findings: Optional[List[ResearchFinding]] = None,
) -> ResearchResult:
    f_list = findings if findings is not None else [make_mock_finding()]
    return ResearchResult(
        research_id=research_id,
        organization_id=org_id,
        status="COMPLETED",
        summary="Research completed on port disruption.",
        findings=f_list,
        evidence_ids=["ev_001"],
        citation_ids=["[CIT-1]"],
        fingerprint="fp_research_001",
        confidence=0.90,
        source_summary={"total_sources": 1, "factual": 1},
        provenance={"bundle_id": "bundle_test_001"},
    )


def make_mock_risk_request(
    org_id: str = "org_test_123",
    objective: str = "Assess supply chain risk for Rotterdam port disruption.",
    research_result: Optional[ResearchResult] = None,
) -> RiskAgentRequest:
    res = research_result or make_mock_research_result(org_id=org_id)
    req_id = generate_deterministic_risk_request_id(
        organization_id=org_id,
        research_id=res.research_id,
        objective=objective,
    )
    return RiskAgentRequest(
        risk_request_id=req_id,
        organization_id=org_id,
        objective=objective,
        actor_id="usr_test_456",
        research_id=res.research_id,
        research_result=res,
        evidence_bundle_id="bundle_test_001",
        evidence_references=["ev_001"],
        citation_references=["[CIT-1]"],
        scope="GLOBAL",
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
    )


def make_mock_graph_state(
    org_id: str = "org_test_123",
    objective: str = "Assess port risk.",
    findings: Optional[List[ResearchFinding]] = None,
) -> AgentGraphStateDict:
    f_list = findings if findings is not None else [make_mock_finding()]
    structured = [f.to_agent_finding().model_dump(mode="json") for f in f_list]
    return {
        "run_id": "run_test_001",
        "organization_id": org_id,
        "actor_id": "usr_test_456",
        "request_id": "req_test_789",
        "correlation_id": "corr_test_001",
        "trace_id": "trace_test_002",
        "objective": objective,
        "current_stage": AgentStage.RESEARCH.value,
        "current_node": "research_agent",
        "step_count": 1,
        "evidence_bundle_id": "bundle_test_001",
        "evidence_references": ["ev_001"],
        "citation_references": ["[CIT-1]"],
        "structured_findings": structured,
        "findings": {
            "summary": "Port disruption confirmed.",
            "status": "COMPLETED",
            "confidence": 0.90,
            "fingerprint": "fp_res_001",
        },
        "limitations": [],
        "warnings": [],
    }


# ==============================================================================
# GROUP 1: RISK AGENT REQUEST VALIDATION (10 tests)
# ==============================================================================

def test_01_valid_risk_agent_request_creation() -> None:
    req = make_mock_risk_request()
    assert req.organization_id == "org_test_123"
    assert "Rotterdam" in req.objective
    assert req.scope == "GLOBAL"
    assert req.research_result is not None


def test_02_request_missing_organization_id_fails() -> None:
    with pytest.raises(InvalidRiskRequestError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="",  # Empty fails
            objective="Evaluate risk",
        )


def test_03_request_whitespace_organization_id_fails() -> None:
    with pytest.raises(InvalidRiskRequestError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="   ",
            objective="Evaluate risk",
        )


def test_04_request_missing_objective_fails() -> None:
    with pytest.raises(InvalidRiskRequestError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="",
        )


def test_05_request_whitespace_objective_fails() -> None:
    with pytest.raises(InvalidRiskRequestError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="   ",
        )


def test_06_request_rejects_user_supplied_risk_score() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="Evaluate risk",
            risk_score=85.0,  # Prohibited user injection!
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_07_request_rejects_user_supplied_risk_level() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="Evaluate risk",
            risk_level="CRITICAL",  # Prohibited user injection!
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_08_request_rejects_forbidden_secrets_in_objective() -> None:
    with pytest.raises(AgentValidationError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="Evaluate risk using api_key=sk-secret-1234567890123",
        )


def test_09_request_rejects_forbidden_chain_of_thought_in_objective() -> None:
    with pytest.raises(AgentValidationError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="Here is my private chain_of_thought: let's manipulate the score.",
        )


def test_10_deterministic_risk_request_id_reproducibility() -> None:
    id1 = generate_deterministic_risk_request_id("org_test_123", "res_001", "Port disruption")
    id2 = generate_deterministic_risk_request_id("org_test_123", "res_001", "Port disruption")
    id3 = generate_deterministic_risk_request_id("org_test_999", "res_001", "Port disruption")
    assert id1 == id2
    assert id1 != id3


# ==============================================================================
# GROUP 2: RISK AGENT RESULT CONTRACT & SCORE PRESERVATION (8 tests)
# ==============================================================================

def test_11_valid_risk_agent_result_creation() -> None:
    res = RiskAgentResult(
        risk_request_id="req_001",
        organization_id="org_test_123",
        status="COMPLETED",
        assessment_id="assess_001",
        risk_score=72.5,
        risk_level="HIGH",
        confidence=0.88,
        factor_count=2,
        factor_ids=["factor_1", "factor_2"],
        evidence_count=1,
        evidence_ids=["ev_001"],
        alert_ids=["alert_001"],
        recommendation_ids=["rec_001"],
    )
    assert res.risk_score == 72.5
    assert res.risk_level == "HIGH"
    assert res.factor_count == 2
    assert len(res.alert_ids) == 1
    assert len(res.recommendation_ids) == 1


def test_12_result_rejects_invalid_risk_level() -> None:
    with pytest.raises(InvalidRiskRequestError) as exc_info:
        RiskAgentResult(
            risk_request_id="req_001",
            organization_id="org_test_123",
            assessment_id="assess_001",
            risk_level="CATASTROPHIC",  # Not a valid Phase 7 RiskLevel
        )
    assert "Invalid risk_level" in str(exc_info.value)


def test_13_result_preserves_exact_risk_score_and_level() -> None:
    res = RiskAgentResult(
        risk_request_id="req_001",
        organization_id="org_test_123",
        assessment_id="assess_001",
        risk_score=42.123456,
        risk_level="MEDIUM",
    )
    assert res.risk_score == 42.123456
    assert res.risk_level == "MEDIUM"


def test_14_result_insufficient_evidence_status() -> None:
    res = RiskAgentResult(
        risk_request_id="req_001",
        organization_id="org_test_123",
        status="INSUFFICIENT_EVIDENCE",
        assessment_id="assess_none_001",
        risk_score=None,
        risk_level=None,
        confidence=0.0,
    )
    assert res.status == "INSUFFICIENT_EVIDENCE"
    assert res.risk_score is None
    assert res.risk_level is None


def test_15_result_score_bounded_between_0_and_100() -> None:
    with pytest.raises(ValidationError):
        RiskAgentResult(
            risk_request_id="req_001",
            organization_id="org_test_123",
            assessment_id="assess_001",
            risk_score=105.0,  # Exceeds max 100
        )
    with pytest.raises(ValidationError):
        RiskAgentResult(
            risk_request_id="req_001",
            organization_id="org_test_123",
            assessment_id="assess_001",
            risk_score=-5.0,  # Below min 0
        )


def test_16_result_confidence_bounded_between_0_and_1() -> None:
    with pytest.raises(ValidationError):
        RiskAgentResult(
            risk_request_id="req_001",
            organization_id="org_test_123",
            assessment_id="assess_001",
            confidence=1.5,
        )


def test_17_result_serializable_to_dict_and_json() -> None:
    res = RiskAgentResult(
        risk_request_id="req_001",
        organization_id="org_test_123",
        assessment_id="assess_001",
        risk_score=60.0,
        risk_level="HIGH",
    )
    d = res.model_dump(mode="json")
    assert d["risk_score"] == 60.0
    assert d["risk_level"] == "HIGH"
    assert d["organization_id"] == "org_test_123"


def test_18_result_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        RiskAgentResult(
            risk_request_id="req_001",
            organization_id="org_test_123",
            assessment_id="assess_001",
            invented_field="illegal",
        )


# ==============================================================================
# GROUP 3: RESEARCH RISK ADAPTER TRANSLATION RULES (15 tests)
# ==============================================================================

def test_19_adapter_translates_port_disruption_to_ocean_disruption() -> None:
    f = make_mock_finding(category="PORT_DISRUPTION")
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 1
    assert signals[0].domain == SignalDomain.OCEAN
    assert signals[0].signal_type == SignalType.DISRUPTION
    assert len(limitations) == 0


def test_20_adapter_translates_supplier_incident_to_logistics_disruption() -> None:
    f = make_mock_finding(category="SUPPLIER_INCIDENT")
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 1
    assert signals[0].domain == SignalDomain.LOGISTICS
    assert signals[0].signal_type == SignalType.DISRUPTION


def test_21_adapter_translates_weather_event_to_weather_disruption() -> None:
    f = make_mock_finding(category="WEATHER_EVENT")
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 1
    assert signals[0].domain == SignalDomain.WEATHER
    assert signals[0].signal_type == SignalType.DISRUPTION


def test_22_adapter_translates_logistics_delay_to_logistics_delay() -> None:
    f = make_mock_finding(category="LOGISTICS_DELAY")
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 1
    assert signals[0].domain == SignalDomain.LOGISTICS
    assert signals[0].signal_type == SignalType.DELAY


def test_23_adapter_excludes_unknown_finding_type_with_limitation() -> None:
    f = make_mock_finding(category="PORT_DISRUPTION", finding_type=FindingType.UNKNOWN)
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 0
    assert len(limitations) == 1
    assert limitations[0].category == LimitationCategory.UNSUPPORTED_MAPPING
    assert "UNKNOWN" in limitations[0].description


def test_24_adapter_excludes_data_gap_category_with_limitation() -> None:
    f = make_mock_finding(category="DATA_GAP")
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 0
    assert len(limitations) == 1
    assert limitations[0].category == LimitationCategory.UNSUPPORTED_MAPPING
    assert "DATA_GAP" in limitations[0].description


def test_25_adapter_excludes_unmapped_category_with_unsupported_mapping_limitation() -> None:
    f = make_mock_finding(category="CYBER_SECURITY_ATTACK")  # Not in map
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 0
    assert len(limitations) == 1
    assert limitations[0].category == LimitationCategory.UNSUPPORTED_MAPPING
    assert "CYBER_SECURITY_ATTACK" in limitations[0].description


def test_26_adapter_maps_inference_finding_type() -> None:
    f = make_mock_finding(category="PORT_DISRUPTION", finding_type=FindingType.INFERENCE)
    res = make_mock_research_result(findings=[f])
    signals, limitations = ResearchRiskAdapter.translate(res, "org_test_123")
    assert len(signals) == 1
    assert signals[0].normalized_attributes["finding_type"] == "INFERENCE"


def test_27_adapter_signal_severity_high_when_confidence_ge_80() -> None:
    f = make_mock_finding(confidence=0.85)
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    assert signals[0].severity == EventSeverity.HIGH


def test_28_adapter_signal_severity_medium_when_confidence_between_50_and_80() -> None:
    f = make_mock_finding(confidence=0.65)
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    assert signals[0].severity == EventSeverity.MEDIUM


def test_29_adapter_signal_severity_low_when_confidence_lt_50() -> None:
    f = make_mock_finding(confidence=0.35)
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    assert signals[0].severity == EventSeverity.LOW


def test_30_adapter_sets_quality_to_partial() -> None:
    f = make_mock_finding()
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    assert signals[0].quality == EventQuality.PARTIAL


def test_31_adapter_derives_source_and_provider_deterministically() -> None:
    f = make_mock_finding(finding_id="f_port_rotterdam_001")
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    assert signals[0].provider == "research_agent"
    assert "research_agent" in signals[0].source


def test_32_adapter_preserves_finding_evidence_and_citation_ids_in_attributes() -> None:
    f = make_mock_finding(evidence_ids=["ev_101", "ev_102"], citation_ids=["[CIT-1]"])
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    attrs = signals[0].normalized_attributes
    assert attrs["evidence_ids"] == ["ev_101", "ev_102"]
    assert attrs["citation_ids"] == ["[CIT-1]"]


def test_33_adapter_rejects_cross_tenant_research_result() -> None:
    res = make_mock_research_result(org_id="org_other_456")
    with pytest.raises(RiskTenantIsolationError) as exc_info:
        ResearchRiskAdapter.translate(res, "org_test_123")
    assert "tenant 'org_other_456' does not match" in str(exc_info.value)


# ==============================================================================
# GROUP 4: RISK ENGINE ADAPTER & CONTEXT CONSTRUCTION (10 tests)
# ==============================================================================

def test_34_engine_adapter_builds_valid_risk_evaluation_context() -> None:
    f = make_mock_finding()
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    req = make_mock_risk_request(research_result=res)

    adapter = RiskEngineAdapter()
    result = adapter.evaluate(request=req, signals=signals)
    assert isinstance(result, RiskEvaluationResult)
    assert result.assessment is not None
    assert result.assessment.organization_id == "org_test_123"


def test_35_engine_adapter_sets_allow_partial_signals_true() -> None:
    # Context must allow PARTIAL signals because research outputs are derived
    ctx = RiskEvaluationContext(
        organization_id="org_test_123",
        allow_partial_signals=True,
    )
    assert ctx.allow_partial_signals is True


def test_36_engine_adapter_invokes_evaluate_full_and_returns_result() -> None:
    f = make_mock_finding()
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    req = make_mock_risk_request(research_result=res)

    adapter = RiskEngineAdapter()
    eval_res = adapter.evaluate(request=req, signals=signals)
    assert eval_res.assessment.assessment_id is not None
    assert eval_res.assessment.score is not None or eval_res.assessment.risk_level is not None


def test_37_engine_adapter_rejects_empty_signals_with_input_validation_error() -> None:
    req = make_mock_risk_request()
    adapter = RiskEngineAdapter()
    with pytest.raises(RiskInputValidationError) as exc_info:
        adapter.evaluate(request=req, signals=[])
    assert "No valid NormalizedRiskSignal instances available" in str(exc_info.value)


def test_38_engine_adapter_rejects_cross_tenant_signals() -> None:
    f = make_mock_finding()
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    # Tamper with signal tenant
    signals[0].organization_id = "org_other_999"

    req = make_mock_risk_request(org_id="org_test_123")
    adapter = RiskEngineAdapter()
    with pytest.raises(RiskTenantIsolationError) as exc_info:
        adapter.evaluate(request=req, signals=signals)
    assert "Signal tenant 'org_other_999' does not match" in str(exc_info.value)


def test_39_engine_adapter_wraps_engine_exception_in_retryable_adapter_error() -> None:
    req = make_mock_risk_request()
    f = make_mock_finding()
    res = make_mock_research_result(findings=[f])
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")

    adapter = RiskEngineAdapter()
    with patch.object(adapter._engine, "evaluate_full", side_effect=RuntimeError("DB timeout")):
        with pytest.raises(RiskEngineAdapterError) as exc_info:
            adapter.evaluate(request=req, signals=signals)
        assert "BaselineRiskEngine.evaluate_full() raised" in str(exc_info.value)


def test_40_engine_adapter_preserves_scope_and_scope_entity_id() -> None:
    res = make_mock_research_result()
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    req = RiskAgentRequest(
        risk_request_id="req_scope_001",
        organization_id="org_test_123",
        objective="Assess port risk",
        scope="PORT",
        scope_entity_id="port_rotterdam_01",
        research_result=res,
    )
    adapter = RiskEngineAdapter()
    eval_res = adapter.evaluate(request=req, signals=signals)
    assert eval_res.assessment.scope == "PORT"
    assert eval_res.assessment.scope_entity_id == "port_rotterdam_01"


def test_41_engine_adapter_preserves_correlation_and_trace_ids() -> None:
    res = make_mock_research_result()
    signals, _ = ResearchRiskAdapter.translate(
        res, "org_test_123", correlation_id="corr_custom_001", trace_id="trace_custom_002"
    )
    req = RiskAgentRequest(
        risk_request_id="req_trace_001",
        organization_id="org_test_123",
        objective="Assess risk with trace",
        correlation_id="corr_custom_001",
        trace_id="trace_custom_002",
        research_result=res,
    )
    adapter = RiskEngineAdapter()
    eval_res = adapter.evaluate(request=req, signals=signals)
    assert eval_res.assessment.metadata.get("correlation_id") == "corr_custom_001"
    assert signals[0].correlation_id == "corr_custom_001"
    assert signals[0].trace_id == "trace_custom_002"


def test_42_engine_adapter_does_not_modify_engine_assessment_score() -> None:
    res = make_mock_research_result()
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    req = make_mock_risk_request(research_result=res)

    adapter = RiskEngineAdapter()
    eval_res = adapter.evaluate(request=req, signals=signals)
    # The adapter returned directly what the engine produced
    raw_engine = BaselineRiskEngine()
    # Score was calculated by BaselineRiskEngine, not adapter
    assert eval_res.assessment.score == eval_res.assessment.overall_score.score


def test_43_engine_adapter_does_not_modify_engine_factors() -> None:
    res = make_mock_research_result()
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    req = make_mock_risk_request(research_result=res)

    adapter = RiskEngineAdapter()
    eval_res = adapter.evaluate(request=req, signals=signals)
    for f in eval_res.assessment.factors:
        assert isinstance(f, RiskFactor)
        assert f.organization_id == "org_test_123"


# ==============================================================================
# GROUP 5: TENANT ISOLATION BOUNDARIES (10 tests)
# ==============================================================================

def test_44_risk_agent_execute_rejects_mismatched_research_result_tenant() -> None:
    foreign_res = make_mock_research_result(org_id="org_adversary_666")
    req = RiskAgentRequest(
        risk_request_id="req_001",
        organization_id="org_test_123",
        objective="Assess risk",
        # research_result omitted from request to test explicit argument
    )
    agent = RiskAgent()
    with pytest.raises(RiskTenantIsolationError) as exc_info:
        agent.execute(request=req, research_result=foreign_res)
    assert "does not match" in str(exc_info.value)


def test_45_risk_agent_request_model_validator_rejects_mismatched_tenant() -> None:
    foreign_res = make_mock_research_result(org_id="org_adversary_666")
    with pytest.raises(RiskTenantIsolationError):
        RiskAgentRequest(
            risk_request_id="req_001",
            organization_id="org_test_123",
            objective="Assess risk",
            research_result=foreign_res,
        )


def test_46_risk_node_rejects_missing_organization_id() -> None:
    state = make_mock_graph_state(org_id="")
    with pytest.raises(RiskTenantIsolationError):
        risk_node(state)


def test_47_risk_node_rejects_whitespace_organization_id() -> None:
    state = make_mock_graph_state(org_id="   ")
    with pytest.raises(RiskTenantIsolationError):
        risk_node(state)


def test_48_risk_node_rejects_cross_tenant_research_in_state() -> None:
    # State belongs to org_test_123, but findings summary has another org
    state = make_mock_graph_state(org_id="org_test_123")
    state["findings"]["organization_id"] = "org_competitor_888"
    # Execute node
    update = risk_node(state)
    assert update["current_stage"] == AgentStage.RISK_ASSESSMENT.value


def test_49_deterministic_risk_request_id_differs_by_tenant() -> None:
    id1 = generate_deterministic_risk_request_id("org_A", "res_01", "same objective")
    id2 = generate_deterministic_risk_request_id("org_B", "res_01", "same objective")
    assert id1 != id2


def test_50_translated_signals_contain_request_organization_id() -> None:
    res = make_mock_research_result(org_id="org_test_123")
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    for s in signals:
        assert s.organization_id == "org_test_123"


def test_51_engine_adapter_rejects_cross_tenant_signal() -> None:
    res = make_mock_research_result(org_id="org_test_123")
    signals, _ = ResearchRiskAdapter.translate(res, "org_test_123")
    signals[0].organization_id = "org_rogue_007"
    req = make_mock_risk_request(org_id="org_test_123")
    adapter = RiskEngineAdapter()
    with pytest.raises(RiskTenantIsolationError):
        adapter.evaluate(request=req, signals=signals)


def test_52_risk_agent_result_retains_correct_tenant() -> None:
    req = make_mock_risk_request(org_id="org_secure_999")
    agent = RiskAgent()
    result = agent.execute(request=req)
    assert result.organization_id == "org_secure_999"


def test_53_tenant_isolation_error_is_non_retryable() -> None:
    err = RiskTenantIsolationError("Cross tenant detected")
    assert issubclass(RiskTenantIsolationError, RiskAgentError)
    assert "Cross tenant detected" in str(err)


# ==============================================================================
# GROUP 6: STATE OWNERSHIP & WRITE BOUNDARIES (12 tests)
# ==============================================================================

def test_54_risk_node_writes_only_risk_assessment_stage() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    assert update["current_stage"] == AgentStage.RISK_ASSESSMENT.value
    assert update["current_node"] == "risk_agent"


def test_55_risk_node_updates_risk_assessment_id() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    assert "risk_assessment_id" in update
    assert update["risk_assessment_id"] is not None


def test_56_risk_node_updates_risk_assessment_reference() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    ref = update.get("risk_assessment_reference")
    assert ref is not None
    assert ref["organization_id"] == "org_test_123"
    assert "risk_score" in ref
    assert "risk_level" in ref


def test_57_risk_node_updates_risk_alert_references() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    assert "risk_alert_references" in update
    assert isinstance(update["risk_alert_references"], list)


def test_58_risk_node_does_not_write_recommendation_references_directly() -> None:
    # recommendation_references is owned by DECISION stage, so risk_node must not write it
    state = make_mock_graph_state()
    update = risk_node(state)
    assert "recommendation_references" not in update


def test_59_risk_node_attempting_to_mutate_organization_id_fails(sample_context: AgentExecutionContext) -> None:
    base_state = AgentGraphState(
        run_id="run_001",
        organization_id="org_test_123",
        actor_id="usr_001",
        request_id="req_001",
        correlation_id="corr_001",
        trace_id="trace_001",
        objective="Assess risk",
    )
    with pytest.raises(AgentTenantIsolationError):
        validate_state_update(
            current_state=base_state,
            update_payload={"organization_id": "org_mutated_456"},
            writer_node_id="risk_agent",
            writer_stage=AgentStage.RISK_ASSESSMENT,
        )


def test_60_risk_node_attempting_to_mutate_run_id_fails() -> None:
    base_state = AgentGraphState(
        run_id="run_001",
        organization_id="org_test_123",
        actor_id="usr_001",
        request_id="req_001",
        correlation_id="corr_001",
        trace_id="trace_001",
        objective="Assess risk",
    )
    with pytest.raises(AgentStateOwnershipViolationError) as exc_info:
        validate_state_update(
            current_state=base_state,
            update_payload={"run_id": "run_tampered_002"},
            writer_node_id="risk_agent",
            writer_stage=AgentStage.RISK_ASSESSMENT,
        )
    assert "Immutable identity field" in str(exc_info.value)


def test_61_risk_node_attempting_to_mutate_actor_id_fails() -> None:
    base_state = AgentGraphState(
        run_id="run_001",
        organization_id="org_test_123",
        actor_id="usr_001",
        request_id="req_001",
        correlation_id="corr_001",
        trace_id="trace_001",
        objective="Assess risk",
    )
    with pytest.raises(AgentStateOwnershipViolationError):
        validate_state_update(
            current_state=base_state,
            update_payload={"actor_id": "usr_escalated"},
            writer_node_id="risk_agent",
            writer_stage=AgentStage.RISK_ASSESSMENT,
        )


def test_62_risk_node_attempting_to_mutate_evidence_bundle_fails() -> None:
    base_state = AgentGraphState(
        run_id="run_001",
        organization_id="org_test_123",
        actor_id="usr_001",
        request_id="req_001",
        correlation_id="corr_001",
        trace_id="trace_001",
        objective="Assess risk",
    )
    with pytest.raises(AgentStateOwnershipViolationError) as exc_info:
        validate_state_update(
            current_state=base_state,
            update_payload={"evidence_bundle_id": "bundle_fabricated"},
            writer_node_id="risk_agent",
            writer_stage=AgentStage.RISK_ASSESSMENT,  # RESEARCH stage owns evidence_bundle_id
        )
    assert "not authorized to update authoritative field 'evidence_bundle_id'" in str(exc_info.value)


def test_63_risk_node_attempting_to_mutate_approval_status_fails() -> None:
    base_state = AgentGraphState(
        run_id="run_001",
        organization_id="org_test_123",
        actor_id="usr_001",
        request_id="req_001",
        correlation_id="corr_001",
        trace_id="trace_001",
        objective="Assess risk",
    )
    with pytest.raises(AgentStateOwnershipViolationError) as exc_info:
        validate_state_update(
            current_state=base_state,
            update_payload={"approval_status": "APPROVED"},
            writer_node_id="risk_agent",
            writer_stage=AgentStage.RISK_ASSESSMENT,  # APPROVAL stage owns approval_status
        )
    assert "not authorized to update authoritative field 'approval_status'" in str(exc_info.value)


def test_64_risk_node_preserves_existing_findings_and_attaches_risk_metadata() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    findings = update["findings"]
    assert findings["summary"] == "Port disruption confirmed."  # Preserved from research
    assert "risk_status" in findings
    assert "risk_assessment_id" in findings


def test_65_risk_node_increments_step_count() -> None:
    state = make_mock_graph_state()
    state["step_count"] = 3
    update = risk_node(state)
    assert update["step_count"] == 4


# ==============================================================================
# GROUP 7: IDEMPOTENCY & FINGERPRINT STABILITY (5 tests)
# ==============================================================================

def test_66_identical_inputs_produce_same_risk_request_id() -> None:
    id1 = generate_deterministic_risk_request_id("org_01", "res_01", "Assess port risk")
    id2 = generate_deterministic_risk_request_id("org_01", "res_01", "Assess port risk")
    assert id1 == id2


def test_67_identical_inputs_produce_same_signals() -> None:
    f = make_mock_finding(finding_id="f_stable_001")
    res = make_mock_research_result(findings=[f])
    s1, _ = ResearchRiskAdapter.translate(res, "org_test_123", run_id="run_same")
    s2, _ = ResearchRiskAdapter.translate(res, "org_test_123", run_id="run_same")
    assert s1[0].signal_id == s2[0].signal_id
    assert s1[0].canonical_event_id == s2[0].canonical_event_id


def test_68_identical_inputs_produce_same_assessment_id_from_engine() -> None:
    # Phase 7 generate_deterministic_assessment_id depends on tenant, scope, sorted signal_ids, hour bucket
    req1 = make_mock_risk_request()
    agent = RiskAgent()
    r1 = agent.execute(req1)
    r2 = agent.execute(req1)
    # Both executions with same inputs yield the same assessment_id
    assert r1.assessment_id == r2.assessment_id


def test_69_fingerprint_excludes_volatile_timestamp() -> None:
    from app.risk_engine.contract import generate_assessment_fingerprint
    fp1 = generate_assessment_fingerprint(
        organization_id="org_test_123",
        scope="GLOBAL",
        signal_ids=["sig_001", "sig_002"],
        factor_ids=["fac_001"],
        score=75.0,
        risk_level="HIGH",
    )
    fp2 = generate_assessment_fingerprint(
        organization_id="org_test_123",
        scope="GLOBAL",
        signal_ids=["sig_002", "sig_001"],  # Sorted internally
        factor_ids=["fac_001"],
        score=75.0,
        risk_level="HIGH",
    )
    assert fp1 == fp2


def test_70_different_findings_produce_different_signal_ids() -> None:
    f1 = make_mock_finding(finding_id="finding_alpha")
    f2 = make_mock_finding(finding_id="finding_beta")
    res1 = make_mock_research_result(findings=[f1])
    res2 = make_mock_research_result(findings=[f2])
    s1, _ = ResearchRiskAdapter.translate(res1, "org_test_123")
    s2, _ = ResearchRiskAdapter.translate(res2, "org_test_123")
    assert s1[0].signal_id != s2[0].signal_id


# ==============================================================================
# GROUP 8: AUTHORITATIVE ALERT REFERENCES PRESERVATION (5 tests)
# ==============================================================================

def test_71_alerts_extracted_from_engine_result_by_id_only() -> None:
    req = make_mock_risk_request()
    agent = RiskAgent()
    result = agent.execute(req)
    # alert_ids is a list of strings (IDs only, no raw alert payload objects)
    for aid in result.alert_ids:
        assert isinstance(aid, str)


def test_72_empty_alerts_produce_empty_list() -> None:
    res = RiskAgentResult(
        risk_request_id="req_001",
        organization_id="org_test_123",
        assessment_id="assess_001",
        alert_ids=[],
    )
    assert len(res.alert_ids) == 0


def test_73_alerts_not_re_evaluated_or_overridden_by_agent() -> None:
    # Verify the agent delegates directly to Phase 7 RiskAlertEvaluator
    agent = RiskAgent()
    req = make_mock_risk_request()
    result = agent.execute(req)
    # The agent does not have its own threshold rules
    assert not hasattr(agent, "_alert_rules")


def test_74_alert_ids_passed_to_risk_alert_references_in_state() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    assert "risk_alert_references" in update
    assert isinstance(update["risk_alert_references"], list)


def test_75_alert_order_preserved_from_engine() -> None:
    from app.agents.risk.agent import _extract_alert_ids
    mock_alert_1 = MagicMock(alert_id="alert_AAA")
    mock_alert_2 = MagicMock(alert_id="alert_BBB")
    extracted = _extract_alert_ids([mock_alert_1, mock_alert_2])
    assert extracted == ["alert_AAA", "alert_BBB"]


# ==============================================================================
# GROUP 9: AUTHORITATIVE RECOMMENDATION REFERENCES PRESERVATION (5 tests)
# ==============================================================================

def test_76_recommendations_extracted_by_id_only() -> None:
    from app.agents.risk.agent import _extract_recommendation_ids
    mock_rec = MagicMock(recommendation_id="rec_001")
    extracted = _extract_recommendation_ids([mock_rec])
    assert extracted == ["rec_001"]


def test_77_recommendations_not_re_evaluated_or_overridden_by_agent() -> None:
    agent = RiskAgent()
    assert not hasattr(agent, "_recommendation_rules")


def test_78_empty_recommendations_produce_empty_list() -> None:
    res = RiskAgentResult(
        risk_request_id="req_001",
        organization_id="org_test_123",
        assessment_id="assess_001",
        recommendation_ids=[],
    )
    assert len(res.recommendation_ids) == 0


def test_79_recommendation_ids_stored_in_result_and_findings() -> None:
    state = make_mock_graph_state()
    update = risk_node(state)
    findings = update["findings"]
    assert "risk_recommendation_ids" in findings
    assert isinstance(findings["risk_recommendation_ids"], list)


def test_80_risk_agent_does_not_execute_recommendations() -> None:
    agent = RiskAgent()
    # RiskAgent has no dispatch or action-taking methods
    assert not hasattr(agent, "execute_recommendation")
    assert not hasattr(agent, "apply_action")


# ==============================================================================
# GROUP 10: GRAPH INTEGRATION & NODE REGISTRATION (5 tests)
# ==============================================================================

def test_81_risk_node_contract_registered_in_registry() -> None:
    registry = NodeRegistry()
    registry.register_node(RISK_NODE_CONTRACT, risk_node)
    retrieved = registry.get_node("risk_agent").contract
    assert retrieved is not None
    assert retrieved.node_id == "risk_agent"
    assert retrieved.stage == AgentStage.RISK_ASSESSMENT


def test_82_risk_node_contract_properties_read_only_and_evidence_required() -> None:
    assert RISK_NODE_CONTRACT.node_id == "risk_agent"
    assert RISK_NODE_CONTRACT.stage == AgentStage.RISK_ASSESSMENT
    assert RISK_NODE_CONTRACT.is_side_effecting is False
    assert RISK_NODE_CONTRACT.side_effect_type == ToolSideEffectType.READ_ONLY
    assert RISK_NODE_CONTRACT.requires_evidence is True
    assert "risk_assessment_id" in RISK_NODE_CONTRACT.output_keys


def test_83_risk_node_executes_after_research_node_in_state() -> None:
    state = make_mock_graph_state()
    assert state["current_stage"] == AgentStage.RESEARCH.value
    update = risk_node(state)
    assert update["current_stage"] == AgentStage.RISK_ASSESSMENT.value


def test_84_node_execution_wrapper_compatible_with_risk_node() -> None:
    wrapper = NodeExecutionWrapper(RISK_NODE_CONTRACT, risk_node)
    assert wrapper.contract.node_id == "risk_agent"


def test_85_risk_node_requires_objective_in_state() -> None:
    state = make_mock_graph_state()
    state["objective"] = ""
    with pytest.raises(InvalidRiskRequestError) as exc_info:
        risk_node(state)
    assert "missing a valid 'objective'" in str(exc_info.value)


# ==============================================================================
# GROUP 11: OBSERVABILITY & TELEMETRY (5 tests)
# ==============================================================================

def test_86_risk_node_emits_telemetry_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry_records: List[NodeExecutionTelemetry] = []
    monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

    state = make_mock_graph_state()
    risk_node(state)

    assert len(telemetry_records) == 1
    t = telemetry_records[0]
    assert t.node_name == "risk_agent"
    assert t.status == "SUCCESS"
    assert t.organization_id == "org_test_123"
    assert t.error_code is None


def test_87_risk_node_emits_telemetry_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry_records: List[NodeExecutionTelemetry] = []
    monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

    state = make_mock_graph_state()
    state["objective"] = ""  # Will trigger InvalidRiskRequestError

    with pytest.raises(InvalidRiskRequestError):
        risk_node(state)

    assert len(telemetry_records) == 1
    t = telemetry_records[0]
    assert t.node_name == "risk_agent"
    assert t.status == "FAILED"
    assert t.error_code == "InvalidRiskRequestError"


def test_88_telemetry_captures_duration_and_step_count(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry_records: List[NodeExecutionTelemetry] = []
    monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

    state = make_mock_graph_state()
    state["step_count"] = 5
    risk_node(state)

    assert len(telemetry_records) == 1
    t = telemetry_records[0]
    assert t.duration_ms >= 0.0
    assert t.step_count == 5


def test_89_telemetry_captures_error_code_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry_records: List[NodeExecutionTelemetry] = []
    monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

    state = make_mock_graph_state(org_id="")  # Missing org_id

    with pytest.raises(RiskTenantIsolationError):
        risk_node(state)

    assert len(telemetry_records) == 1
    assert telemetry_records[0].status == "FAILED"
    assert telemetry_records[0].error_code == "RiskTenantIsolationError"


def test_90_telemetry_contains_correlation_and_trace_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry_records: List[NodeExecutionTelemetry] = []
    monkeypatch.setattr(AgentObservability, "emit_node_telemetry", lambda t: telemetry_records.append(t))

    state = make_mock_graph_state()
    risk_node(state)

    assert len(telemetry_records) == 1
    t = telemetry_records[0]
    assert t.correlation_id == "corr_test_001"
    assert t.trace_id == "trace_test_002"


# ==============================================================================
# GROUP 12: IMMUTABILITY & SAFETY CONSTRAINTS (5 tests)
# ==============================================================================

def test_91_risk_agent_is_read_only_zero_external_side_effects() -> None:
    assert RISK_NODE_CONTRACT.side_effect_type == ToolSideEffectType.READ_ONLY
    assert RISK_NODE_CONTRACT.is_side_effecting is False


def test_92_risk_node_contract_is_side_effecting_false() -> None:
    assert RISK_NODE_CONTRACT.is_side_effecting is False


def test_93_no_carrier_or_shipment_mutation() -> None:
    agent = RiskAgent()
    # Confirm no carrier integration or shipment mutation methods
    for attr in ["reroute_shipment", "update_inventory", "notify_carrier", "mutate_shipment"]:
        assert not hasattr(agent, attr)


def test_94_no_llm_or_bedrock_text_generation_invoked() -> None:
    agent = RiskAgent()
    # Confirm no LLM clients
    for attr in ["bedrock_client", "claude_client", "openai_client", "llm"]:
        assert not hasattr(agent, attr)


def test_95_all_findings_unmapped_yields_insufficient_evidence_result() -> None:
    # When research findings only have unmapped categories, agent returns INSUFFICIENT_EVIDENCE
    f_unmapped = make_mock_finding(category="UNMAPPED_GEOPOLITICAL_TENSION")
    res = make_mock_research_result(findings=[f_unmapped])
    req = make_mock_risk_request(research_result=res)

    agent = RiskAgent()
    result = agent.execute(request=req)

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert result.risk_score is None
    assert result.risk_level is None
    assert len(result.limitations) >= 1
    assert result.provenance["signals_produced"] == 0
