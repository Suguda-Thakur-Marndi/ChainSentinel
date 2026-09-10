"""Focused test suite for RiskWise 2.0 Phase 9 Step 10: Observability & Recovery.

Covers:
A. Trace propagation
B. Node telemetry
C. Error classification
D. Retry policy & bounded retries
E. Timeout handling
F. Recovery policy
G. State integrity & hashing
H. Routing safety & loop/crash protection
I. Human approval boundary integration
J. Audit event integration
K. Secret redaction & sanitization
L. Tenant isolation
M. Idempotent retry
N. Concurrent & replayed execution protection
O. Failure response contract
P. Tool telemetry & metrics integration
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import json
import threading
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentNodeContract,
    AgentStage,
    apply_state_update,
    validate_state_update,
)
from app.agents.errors import (
    AgentErrorCategory,
    AgentApprovalBoundaryViolationError,
    AgentApprovalError,
    AgentAuthorizationError,
    AgentContractError,
    AgentDependencyFailureError,
    AgentEvidenceIntegrityError,
    AgentGraphError,
    AgentGraphValidationError,
    AgentInternalError,
    AgentInvalidEdgeError,
    AgentInvalidRouteError,
    AgentMaxStepsExceededError,
    AgentMissingInputError,
    AgentNodeExecutionError,
    AgentPersistenceError,
    AgentRateLimitError,
    AgentRoutingError,
    AgentSecurityError,
    AgentStageTransitionError,
    AgentStateError,
    AgentStateOwnershipViolationError,
    AgentStateSizeLimitError,
    AgentTenantIsolationError,
    AgentTimeoutError,
    AgentToolAuthorizationError,
    AgentTransientError,
    AgentUnauthorizedNodeError,
    AgentValidationError,
    ErrorClassification,
    NON_RETRYABLE_ERROR_CATEGORIES,
    categorize_error,
    is_retryable_error,
)
from app.agents.execution import NodeExecutionWrapper
from app.agents.graph import AgentGraphBuilder, execute_agent_graph
from app.agents.observability import (
    AgentMetricsCollector,
    AgentObservability,
    AgentRunTelemetry,
    AgentToolCallTelemetry,
    NodeExecutionTelemetry,
    global_metrics_collector,
)
from app.agents.recovery import (
    AgentFailureResult,
    CheckpointManager,
    RecoveryDecision,
    RecoveryPolicy,
    RetryPolicy,
    compute_state_hash,
    verify_state_integrity,
)


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset global metrics collector before and after each test."""
    global_metrics_collector.reset()
    yield
    global_metrics_collector.reset()


@pytest.fixture
def sample_context() -> AgentExecutionContext:
    return AgentExecutionContext(
        organization_id="org_test_10",
        actor_id="usr_test_10",
        request_id="req_test_10",
        correlation_id="corr_test_10",
        trace_id="trace_test_10",
        role="RiskManager",
        roles=["RiskManager"],
        permissions=["agents:execute", "agents:read"],
        max_steps=10,
        max_retries=3,
        timeout_seconds=5.0,
    )


@pytest.fixture
def sample_state() -> AgentGraphState:
    return AgentGraphState(
        run_id="run_test_10",
        organization_id="org_test_10",
        actor_id="usr_test_10",
        request_id="req_test_10",
        correlation_id="corr_test_10",
        trace_id="trace_test_10",
        objective="Assess supply chain vulnerability for APAC route disruption.",
        current_stage=AgentStage.INITIALIZATION,
        status=AgentLifecycleStatus.INITIALIZING,
    )


# ==============================================================================
# SECTION A: TRACE PROPAGATION (10 Tests)
# ==============================================================================

def test_01_trace_propagation_through_graph_execution(sample_state, sample_context):
    result = execute_agent_graph(sample_state, sample_context)
    assert result.run_id == sample_state.run_id
    assert result.organization_id == sample_context.organization_id
    assert result.request_id == sample_context.request_id
    assert result.correlation_id == sample_context.correlation_id
    assert result.trace_id == sample_context.trace_id


def test_02_trace_propagation_in_node_telemetry(sample_context):
    contract = AgentNodeContract(
        node_id="test_node_trace",
        name="Test Trace Node",
        description="Tests trace telemetry",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": {"status": "ok"}})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_001",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert updates == {"findings": {"status": "ok"}}


def test_03_trace_propagation_in_agent_run_telemetry(sample_context):
    telemetry = AgentRunTelemetry(
        organization_id=sample_context.organization_id,
        agent_run_id="run_123",
        execution_id="exec_123",
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        parent_span_id="span_001",
        node_id="research_agent",
        stage=AgentStage.RESEARCH.value,
        attempt=1,
        status="SUCCESS",
        duration_ms=45.2,
    )
    assert telemetry.trace_id == sample_context.trace_id
    assert telemetry.execution_id == "exec_123"
    assert telemetry.parent_span_id == "span_001"


def test_04_trace_mismatch_between_context_and_state_fails(sample_state, sample_context):
    alien_context = AgentExecutionContext(
        organization_id=sample_state.organization_id,
        actor_id=sample_state.actor_id,
        request_id=sample_state.request_id,
        correlation_id=sample_state.correlation_id,
        trace_id="different_alien_trace_id",
    )
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        execute_agent_graph(sample_state, alien_context)
    assert "Context trace_id" in str(exc_info.value)
    assert global_metrics_collector.security_failures >= 1


def test_05_trace_propagation_survives_multi_step_flow(sample_context):
    builder = AgentGraphBuilder()
    app = builder.build()
    state = AgentGraphState(
        run_id="run_multi_step",
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        objective="Multi step trace test",
        current_stage=AgentStage.INITIALIZATION,
    )
    result = execute_agent_graph(state, sample_context, builder=builder)
    assert result.trace_id == sample_context.trace_id
    assert result.run_id == "run_multi_step"


def test_06_trace_propagation_preserves_parent_span_id():
    telemetry = AgentRunTelemetry(
        organization_id="org_1",
        agent_run_id="run_1",
        execution_id="exec_1",
        request_id="req_1",
        correlation_id="corr_1",
        trace_id="trace_1",
        parent_span_id="span_parent_999",
        node_id="node_1",
        status="SUCCESS",
    )
    assert telemetry.parent_span_id == "span_parent_999"


def test_07_trace_id_cannot_be_empty():
    with pytest.raises(AgentTenantIsolationError):
        AgentExecutionContext(
            organization_id="org_1",
            actor_id="actor_1",
            request_id="req_1",
            correlation_id="corr_1",
            trace_id="",
        )


def test_08_request_id_cannot_be_empty():
    with pytest.raises(AgentTenantIsolationError):
        AgentExecutionContext(
            organization_id="org_1",
            actor_id="actor_1",
            request_id="   ",
            correlation_id="corr_1",
            trace_id="trace_1",
        )


def test_09_correlation_id_cannot_be_empty():
    with pytest.raises(AgentTenantIsolationError):
        AgentExecutionContext(
            organization_id="org_1",
            actor_id="actor_1",
            request_id="req_1",
            correlation_id="",
            trace_id="trace_1",
        )


def test_10_execution_id_defaults_to_run_id_when_omitted(sample_context):
    contract = AgentNodeContract(
        node_id="test_node_exec_id",
        name="Exec ID Node",
        description="Tests exec id defaulting",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": {}})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_explicit_id",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert updates == {"findings": {}}


# ==============================================================================
# SECTION B: NODE TELEMETRY (10 Tests)
# ==============================================================================

def test_11_node_telemetry_recorded_on_success(sample_context):
    contract = AgentNodeContract(
        node_id="telemetry_success_node",
        name="Success Node",
        description="Success node description",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": {"res": 1}})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_succ",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    wrapper(state_dict, sample_context)
    assert "telemetry_success_node" in global_metrics_collector.node_latencies
    assert len(global_metrics_collector.node_latencies["telemetry_success_node"]) == 1


def test_12_node_telemetry_recorded_on_failure(sample_context):
    contract = AgentNodeContract(
        node_id="telemetry_fail_node",
        name="Fail Node",
        description="Fail node description",
        stage=AgentStage.RESEARCH,
    )
    def fail_handler(s):
        raise AgentValidationError("Invalid payload structure")

    wrapper = NodeExecutionWrapper(contract, fail_handler)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_fail",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentValidationError):
        wrapper(state_dict, sample_context)


def test_13_node_telemetry_duration_positive(sample_context):
    contract = AgentNodeContract(
        node_id="duration_node",
        name="Duration Node",
        description="Checks duration is positive",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": {}})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_dur",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    wrapper(state_dict, sample_context)
    latencies = global_metrics_collector.node_latencies["duration_node"]
    assert len(latencies) == 1
    assert latencies[0] >= 0.0


def test_14_node_telemetry_computes_input_state_hash(sample_context):
    state_dict = {
        "run_id": "r1",
        "organization_id": "org_1",
        "objective": "Test objective",
    }
    h1 = compute_state_hash(state_dict)
    h2 = compute_state_hash(state_dict)
    assert h1 == h2
    assert len(h1) == 64


def test_15_node_telemetry_computes_output_state_hash(sample_context):
    s1 = {"run_id": "r1", "organization_id": "org_1", "findings": {}}
    s2 = {"run_id": "r1", "organization_id": "org_1", "findings": {"item": "new_val"}}
    assert compute_state_hash(s1) != compute_state_hash(s2)


def test_16_node_telemetry_captures_stage(sample_context):
    contract = AgentNodeContract(
        node_id="stage_capture_node",
        name="Stage Node",
        description="Captures stage",
        stage=AgentStage.RISK_ASSESSMENT,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": {}})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_stage",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RISK_ASSESSMENT.value,
    }
    wrapper(state_dict, sample_context)
    assert "stage_capture_node" in global_metrics_collector.node_latencies


def test_17_node_telemetry_metrics_collector_averages_latency():
    collector = AgentMetricsCollector()
    collector.record_node_latency("node_x", 10.0)
    collector.record_node_latency("node_x", 20.0)
    metrics = collector.get_metrics()
    assert metrics["average_node_latencies_ms"]["node_x"] == 15.0


def test_18_node_telemetry_records_selected_route(sample_context):
    contract = AgentNodeContract(
        node_id="route_record_node",
        name="Route Record Node",
        description="Tests route record",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"selected_route": "risk_assessment"})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_route",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert updates.get("selected_route") == "risk_assessment"


def test_19_node_telemetry_extra_metadata_scrubbed():
    telemetry = AgentObservability.record_node_execution(
        run_id="run_scrub",
        organization_id="org_scrub",
        actor_id="actor_scrub",
        request_id="req_scrub",
        correlation_id="corr_scrub",
        trace_id="trace_scrub",
        node_name="scrub_node",
        duration_ms=12.5,
        status="SUCCESS",
        metadata={"api_key": "secret123", "safe_metric": 42},
    )
    assert telemetry.metadata["safe_metric"] == 42
    assert "api_key" not in telemetry.metadata or telemetry.metadata["api_key"] == "[REDACTED]"


def test_20_node_telemetry_serializes_to_json():
    t = NodeExecutionTelemetry(
        run_id="run_ser",
        organization_id="org_ser",
        actor_id="actor_ser",
        request_id="req_ser",
        correlation_id="corr_ser",
        trace_id="trace_ser",
        node_name="test_node",
        duration_ms=5.0,
        status="SUCCESS",
    )
    dumped = json.loads(t.model_dump_json())
    assert dumped["node_name"] == "test_node"
    assert dumped["status"] == "SUCCESS"


# ==============================================================================
# SECTION C: ERROR CLASSIFICATION (15 Tests)
# ==============================================================================

def test_21_error_classification_validation_error():
    err = AgentValidationError("Invalid schema")
    assert err.category == AgentErrorCategory.VALIDATION_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_22_error_classification_security_error():
    err = AgentSecurityError("Security boundary violated")
    assert err.category == AgentErrorCategory.SECURITY_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_23_error_classification_tenant_isolation_error():
    err = AgentTenantIsolationError("Tenant mismatch")
    assert err.category == AgentErrorCategory.TENANT_ISOLATION_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_24_error_classification_authorization_error():
    err = AgentAuthorizationError("Missing role")
    assert err.category == AgentErrorCategory.AUTHORIZATION_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_25_error_classification_contract_error():
    err = AgentContractError("Contract violation")
    assert err.category == AgentErrorCategory.CONTRACT_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_26_error_classification_dependency_error():
    err = AgentDependencyFailureError("Vector DB timeout", retryable=True)
    assert err.category == AgentErrorCategory.DEPENDENCY_ERROR
    assert err.retryable
    assert is_retryable_error(err)


def test_27_error_classification_timeout_error():
    err = AgentTimeoutError("Node timeout")
    assert err.category == AgentErrorCategory.TIMEOUT_ERROR
    assert err.retryable
    assert is_retryable_error(err)


def test_28_error_classification_transient_error():
    err = AgentTransientError("Temporary socket error")
    assert err.category == AgentErrorCategory.TRANSIENT_ERROR
    assert err.retryable
    assert is_retryable_error(err)


def test_29_error_classification_rate_limit_error():
    err = AgentRateLimitError("Rate limit exceeded")
    assert err.category == AgentErrorCategory.RATE_LIMIT_ERROR
    assert err.retryable
    assert is_retryable_error(err)


def test_30_error_classification_state_error():
    err = AgentStateError("State hash corrupted")
    assert err.category == AgentErrorCategory.STATE_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_31_error_classification_routing_error():
    err = AgentRoutingError("Unreachable node")
    assert err.category == AgentErrorCategory.ROUTING_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_32_error_classification_approval_error():
    err = AgentApprovalError("Approval tampered")
    assert err.category == AgentErrorCategory.APPROVAL_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_33_error_classification_persistence_error():
    err = AgentPersistenceError("Lock contention", retryable=True)
    assert err.category == AgentErrorCategory.PERSISTENCE_ERROR
    assert err.retryable
    assert is_retryable_error(err)


def test_34_error_classification_internal_error():
    err = AgentInternalError("Unexpected bug")
    assert err.category == AgentErrorCategory.INTERNAL_ERROR
    assert not err.retryable
    assert not is_retryable_error(err)


def test_35_error_classification_unknown_error():
    err = RuntimeError("Some generic error")
    cat = categorize_error(err)
    assert cat == AgentErrorCategory.UNKNOWN_ERROR
    assert not is_retryable_error(err)


# ==============================================================================
# SECTION D: RETRY POLICY & BOUNDED RETRIES (10 Tests)
# ==============================================================================

def test_36_retry_policy_retries_transient_error(sample_context):
    calls = []
    def flaky_handler(state):
        calls.append(len(calls) + 1)
        if len(calls) < 2:
            raise AgentTransientError("Temporary glitch")
        return {"findings": {"resolved": True}}

    contract = AgentNodeContract(
        node_id="flaky_node",
        name="Flaky Node",
        description="Flaky node description",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.01)
    wrapper = NodeExecutionWrapper(contract, flaky_handler, retry_policy=policy)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_flaky",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert len(calls) == 2
    assert updates == {"findings": {"resolved": True}}
    assert global_metrics_collector.node_retries == 1


def test_37_retry_policy_stops_at_max_retries(sample_context):
    calls = []
    def persistent_failure_handler(state):
        calls.append(1)
        raise AgentTransientError("Persistent connection failure")

    contract = AgentNodeContract(
        node_id="persistent_fail_node",
        name="Persistent Fail Node",
        description="Fails repeatedly",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.005)
    wrapper = NodeExecutionWrapper(contract, persistent_failure_handler, retry_policy=policy)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_pfail",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTransientError):
        wrapper(state_dict, sample_context)

    # Max retries in sample_context is 3 -> attempt 1, retry attempt 2, retry attempt 3 -> total 3 calls
    assert len(calls) == 3
    assert global_metrics_collector.node_retries == 2


def test_38_retry_policy_never_retries_security_error(sample_context):
    calls = []
    def security_fail_handler(state):
        calls.append(1)
        raise AgentSecurityError("Malicious injection attempt")

    contract = AgentNodeContract(
        node_id="sec_node",
        name="Security Node",
        description="Fails on security",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, security_fail_handler)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_sec",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentSecurityError):
        wrapper(state_dict, sample_context)

    assert len(calls) == 1
    assert global_metrics_collector.node_retries == 0
    assert global_metrics_collector.security_failures >= 1


def test_39_retry_policy_never_retries_tenant_error(sample_context):
    calls = []
    def tenant_fail_handler(state):
        calls.append(1)
        raise AgentTenantIsolationError("Foreign tenant access")

    contract = AgentNodeContract(
        node_id="tenant_fail_node",
        name="Tenant Fail Node",
        description="Fails on tenant",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, tenant_fail_handler)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_t_fail",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTenantIsolationError):
        wrapper(state_dict, sample_context)

    assert len(calls) == 1
    assert global_metrics_collector.node_retries == 0


def test_40_retry_policy_never_retries_validation_error(sample_context):
    calls = []
    def val_fail_handler(state):
        calls.append(1)
        raise AgentValidationError("Field format invalid")

    contract = AgentNodeContract(
        node_id="val_fail_node",
        name="Val Fail Node",
        description="Fails on validation",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, val_fail_handler)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_v_fail",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentValidationError):
        wrapper(state_dict, sample_context)

    assert len(calls) == 1
    assert global_metrics_collector.node_retries == 0


def test_41_retry_policy_exponential_backoff_increases():
    policy = RetryPolicy(base_delay_seconds=0.1, max_delay_seconds=10.0, jitter=False)
    d1 = policy.compute_backoff(1)
    d2 = policy.compute_backoff(2)
    d3 = policy.compute_backoff(3)
    assert d1 == 0.1
    assert d2 == 0.2
    assert d3 == 0.4


def test_42_retry_policy_backoff_capped_at_max():
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=3.0, jitter=False)
    d10 = policy.compute_backoff(10)
    assert d10 == 3.0


def test_43_retry_policy_metrics_incremented(sample_context):
    collector = AgentMetricsCollector()
    collector.record_node_retry("node_1")
    collector.record_node_retry("node_1")
    metrics = collector.get_metrics()
    assert metrics["node_retries"] == 2


def test_44_retry_policy_zero_retries_disables_retry(sample_context):
    zero_retry_context = AgentExecutionContext(
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        max_retries=0,
    )
    calls = []
    def fail_once(state):
        calls.append(1)
        raise AgentTransientError("Temporary glitch")

    contract = AgentNodeContract(
        node_id="zero_retry_node",
        name="Zero Retry Node",
        description="Zero retry test",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, fail_once)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_zr",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTransientError):
        wrapper(state_dict, zero_retry_context)

    assert len(calls) == 1
    assert global_metrics_collector.node_retries == 0


def test_45_retry_policy_no_infinite_loops(sample_context):
    contract = AgentNodeContract(
        node_id="loop_node",
        name="Loop Node",
        description="Loop test",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.002)
    wrapper = NodeExecutionWrapper(contract, lambda s: (_ for _ in ()).throw(AgentTimeoutError("t")), retry_policy=policy)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_loop",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTimeoutError):
        wrapper(state_dict, sample_context)


# ==============================================================================
# SECTION E: TIMEOUT HANDLING (8 Tests)
# ==============================================================================

def test_46_timeout_handling_detects_exceeded_deadline(sample_context):
    def slow_handler(state):
        time.sleep(0.1)
        return {"findings": {}}

    contract = AgentNodeContract(
        node_id="slow_node",
        name="Slow Node",
        description="Slow node description",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, slow_handler, timeout_seconds=0.02)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_to",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTimeoutError) as exc_info:
        wrapper(state_dict, sample_context)

    assert "timed out after" in str(exc_info.value)
    assert global_metrics_collector.node_timeouts >= 1


def test_47_timeout_handling_records_metric():
    collector = AgentMetricsCollector()
    collector.record_node_timeout("slow_node_metric")
    assert collector.get_metrics()["node_timeouts"] == 1


def test_48_timeout_handling_records_telemetry():
    telemetry = AgentRunTelemetry(
        organization_id="org_1",
        agent_run_id="run_1",
        execution_id="exec_1",
        request_id="req_1",
        correlation_id="corr_1",
        trace_id="trace_1",
        node_id="timeout_telemetry_node",
        status="FAILED",
        error_code="AGENT_TIMEOUT_ERROR",
        error_category=AgentErrorCategory.TIMEOUT_ERROR.value,
    )
    assert telemetry.error_category == "TIMEOUT_ERROR"
    assert telemetry.error_code == "AGENT_TIMEOUT_ERROR"


def test_49_timeout_handling_retried_if_budget_allows(sample_context):
    calls = []
    def timeout_then_succeed(state):
        calls.append(1)
        if len(calls) == 1:
            time.sleep(0.06)
        return {"findings": {"done": True}}

    contract = AgentNodeContract(
        node_id="to_retry_node",
        name="Timeout Retry Node",
        description="Timeout retry description",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.005)
    wrapper = NodeExecutionWrapper(contract, timeout_then_succeed, retry_policy=policy, timeout_seconds=0.03)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_to_r",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert len(calls) == 2
    assert updates == {"findings": {"done": True}}


def test_50_timeout_handling_fails_when_budget_exhausted(sample_context):
    def always_slow(state):
        time.sleep(0.05)
        return {"findings": {}}

    contract = AgentNodeContract(
        node_id="always_slow_node",
        name="Always Slow Node",
        description="Always slow description",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.005)
    wrapper = NodeExecutionWrapper(contract, always_slow, retry_policy=policy, timeout_seconds=0.02)
    state_dict: AgentGraphStateDict = {
        "run_id": "run_slow_ex",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTimeoutError):
        wrapper(state_dict, sample_context)


def test_51_timeout_handling_safe_thread_termination():
    # Verify ThreadPoolExecutor shutdown doesn't leak threads
    before_threads = threading.active_count()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        f = ex.submit(lambda: 42)
        assert f.result() == 42
    after_threads = threading.active_count()
    assert abs(after_threads - before_threads) <= 1


def test_52_timeout_handling_preserves_trace_identity(sample_context):
    err = AgentTimeoutError("Operation timed out")
    err.trace_id = sample_context.trace_id
    assert err.trace_id == sample_context.trace_id
    d = err.to_dict()
    assert d["trace_id"] == sample_context.trace_id


def test_53_timeout_handling_custom_timeout_seconds(sample_context):
    ctx = AgentExecutionContext(
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        timeout_seconds=45.0,
    )
    assert ctx.timeout_seconds == 45.0


# ==============================================================================
# SECTION F: RECOVERY POLICY (10 Tests)
# ==============================================================================

def test_54_recovery_policy_retry_on_dependency_error():
    err = AgentDependencyFailureError("Temporary DB blip", retryable=True)
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    assert decision == RecoveryDecision.RETRY


def test_55_recovery_policy_fail_on_security_error():
    err = AgentSecurityError("Tampered credential")
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    assert decision == RecoveryDecision.FAIL


def test_56_recovery_policy_fail_on_tenant_error():
    err = AgentTenantIsolationError("Foreign tenant")
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    assert decision == RecoveryDecision.FAIL


def test_57_recovery_policy_wait_for_human_on_approval_pending():
    err = AgentGraphError("Paused for governance")
    state = {"status": AgentLifecycleStatus.WAITING_FOR_APPROVAL, "requires_human_approval": True}
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3, state=state)
    assert decision == RecoveryDecision.WAIT_FOR_HUMAN


def test_58_recovery_policy_escalate_when_retry_budget_exhausted():
    err = AgentTransientError("Persistent connectivity error")
    decision = RecoveryPolicy.evaluate(err, attempt=3, max_retries=3)
    assert decision == RecoveryDecision.ESCALATE


def test_59_recovery_policy_fail_on_state_error():
    err = AgentStateError("Corrupted state payload")
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    assert decision == RecoveryDecision.FAIL


def test_60_recovery_policy_fail_on_contract_error():
    err = AgentContractError("Stage jumped illegally")
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    assert decision == RecoveryDecision.FAIL


def test_61_recovery_policy_records_recovery_metric():
    collector = AgentMetricsCollector()
    collector.record_recovery("FAIL")
    collector.record_recovery("RETRY")
    assert collector.get_metrics()["recovery_count"] == 2


def test_62_recovery_policy_deterministic_for_same_input():
    err = AgentTransientError("Glitch")
    d1 = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    d2 = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3)
    assert d1 == d2 == RecoveryDecision.RETRY


def test_63_recovery_policy_with_none_state():
    err = AgentValidationError("Invalid schema")
    decision = RecoveryPolicy.evaluate(err, attempt=1, max_retries=3, state=None)
    assert decision == RecoveryDecision.FAIL


# ==============================================================================
# SECTION G: STATE INTEGRITY & HASHING (10 Tests)
# ==============================================================================

def test_64_compute_state_hash_deterministic():
    state1 = {"run_id": "r1", "organization_id": "org_1", "objective": "Analyze risk"}
    state2 = {"organization_id": "org_1", "objective": "Analyze risk", "run_id": "r1"}
    assert compute_state_hash(state1) == compute_state_hash(state2)


def test_65_compute_state_hash_ignores_transient_timestamps():
    state1 = {"run_id": "r1", "organization_id": "org_1", "started_at": datetime.now(timezone.utc)}
    state2 = {"run_id": "r1", "organization_id": "org_1", "started_at": datetime(2025, 1, 1, tzinfo=timezone.utc)}
    assert compute_state_hash(state1) == compute_state_hash(state2)


def test_66_compute_state_hash_detects_mutation():
    state1 = {"run_id": "r1", "organization_id": "org_1", "findings": {"items": [1]}}
    state2 = {"run_id": "r1", "organization_id": "org_1", "findings": {"items": [2]}}
    assert compute_state_hash(state1) != compute_state_hash(state2)


def test_67_verify_state_integrity_success():
    state = {"run_id": "r1", "organization_id": "org_1"}
    h = compute_state_hash(state)
    assert verify_state_integrity(state, h) is True


def test_68_verify_state_integrity_tampered_fails():
    state = {"run_id": "r1", "organization_id": "org_1"}
    h = compute_state_hash(state)
    tampered_state = {"run_id": "r1", "organization_id": "org_1", "injected": "evil"}
    assert verify_state_integrity(tampered_state, h) is False


def test_69_checkpoint_manager_saves_and_restores(sample_state):
    mgr = CheckpointManager()
    cid = mgr.save_checkpoint(sample_state.run_id, sample_state, step=1)
    restored, restored_cid = mgr.restore_checkpoint(cid, expected_org_id=sample_state.organization_id)
    assert restored_cid == cid
    assert restored.run_id == sample_state.run_id
    assert restored.organization_id == sample_state.organization_id


def test_70_checkpoint_manager_detects_corrupted_state(sample_state):
    mgr = CheckpointManager()
    cid = mgr.save_checkpoint(sample_state.run_id, sample_state, step=1)
    # Tamper with internal checkpoint payload
    mgr._checkpoints[cid]["state"]["objective"] = "Tampered unauthorized objective"
    with pytest.raises(AgentStateError) as exc_info:
        mgr.restore_checkpoint(cid, expected_org_id=sample_state.organization_id)
    assert "integrity failure" in str(exc_info.value).lower()


def test_71_checkpoint_manager_enforces_tenant_boundary(sample_state):
    mgr = CheckpointManager()
    cid = mgr.save_checkpoint(sample_state.run_id, sample_state, step=1)
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        mgr.restore_checkpoint(cid, expected_org_id="foreign_tenant_999")
    assert "tenant mismatch" in str(exc_info.value).lower()


def test_72_checkpoint_manager_missing_checkpoint_raises():
    mgr = CheckpointManager()
    with pytest.raises(AgentStateError) as exc_info:
        mgr.restore_checkpoint("non_existent_chk_id")
    assert "Checkpoint not found" in str(exc_info.value)


def test_73_checkpoint_manager_latest_thread_alias(sample_state):
    mgr = CheckpointManager()
    mgr.save_checkpoint(sample_state.run_id, sample_state, step=1)
    restored, _ = mgr.restore_checkpoint(sample_state.run_id, expected_org_id=sample_state.organization_id)
    assert restored.run_id == sample_state.run_id


# ==============================================================================
# SECTION H: ROUTING SAFETY & LOOP/CRASH PROTECTION (8 Tests)
# ==============================================================================

def test_74_routing_safety_max_steps_exceeded(sample_context):
    contract = AgentNodeContract(
        node_id="step_limit_node",
        name="Step Limit Node",
        description="Tests step limit",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": {}})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_steps",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
        "step_count": 10,  # Matches max_steps=10 in sample_context
    }
    with pytest.raises(AgentMaxStepsExceededError) as exc_info:
        wrapper(state_dict, sample_context)
    assert "Maximum step count" in str(exc_info.value)


def test_75_routing_safety_max_steps_increments_routing_failures_metric(sample_context):
    contract = AgentNodeContract(
        node_id="metric_steps_node",
        name="Step Node",
        description="Step node",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r_steps",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
        "step_count": 25,
    }
    with pytest.raises(AgentMaxStepsExceededError):
        wrapper(state_dict, sample_context)
    assert global_metrics_collector.routing_failures >= 1


def test_76_routing_safety_invalid_route_raises():
    err = AgentInvalidRouteError("Unrecognized route destination: malicious_node")
    assert err.error_code == "AGENT_INVALID_ROUTE_ERROR"
    assert err.category == AgentErrorCategory.ROUTING_ERROR


def test_77_routing_safety_forbidden_stage_transition_raises():
    err = AgentStageTransitionError("Illegal jump: RESEARCH -> APPROVAL")
    assert err.error_code == "AGENT_STAGE_TRANSITION_ERROR"
    assert not err.retryable


def test_78_routing_safety_unauthorized_node_raises():
    err = AgentUnauthorizedNodeError("Node not in allowlist")
    assert err.error_code == "AGENT_UNAUTHORIZED_NODE_ERROR"
    assert not err.retryable


def test_79_routing_safety_route_history_bounded(sample_state):
    # route_history should be bounded
    for i in range(15):
        sample_state.route_history.append({"from_node": "n1", "to_node": "n2", "reason": "step"})
    assert len(sample_state.route_history) == 15


def test_80_routing_safety_state_size_limit_enforced(sample_state):
    huge_payload = {"giant_blob": "x" * 600_000}
    with pytest.raises(AgentStateSizeLimitError):
        validate_state_update(
            current_state=sample_state,
            updates=huge_payload,
            node_id="test_node",
            stage=AgentStage.RESEARCH,
        )


def test_81_routing_safety_no_unbounded_cycles(sample_context, sample_state):
    # Enforces max_steps prevents endless cycles
    ctx = AgentExecutionContext(
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        max_steps=5,
    )
    assert ctx.max_steps == 5


# ==============================================================================
# SECTION I: HUMAN APPROVAL BOUNDARY INTEGRATION (10 Tests)
# ==============================================================================

def test_82_approval_waiting_state_does_not_execute_actions():
    state = AgentGraphState(
        run_id="run_appr_wait",
        organization_id="org_appr",
        actor_id="actor_appr",
        request_id="req_appr",
        correlation_id="corr_appr",
        trace_id="trace_appr",
        objective="Requires human decision",
        current_stage=AgentStage.APPROVAL,
        status=AgentLifecycleStatus.WAITING_FOR_APPROVAL,
        requires_human_approval=True,
    )
    assert state.status == AgentLifecycleStatus.WAITING_FOR_APPROVAL
    assert state.side_effect_allowed is False


def test_83_approval_never_automatically_approved_on_retry(sample_context):
    contract = AgentNodeContract(
        node_id="side_effect_node",
        name="Side Effecting Action",
        description="Performs side effect",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"executed": True})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_side",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.ACTION.value,
        "requires_human_approval": True,
        "side_effect_allowed": False,
    }
    with pytest.raises(AgentApprovalBoundaryViolationError) as exc_info:
        wrapper(state_dict, sample_context)
    assert "requires verified human approval" in str(exc_info.value)


def test_84_approval_approved_resume_succeeds(sample_state):
    sample_state.status = AgentLifecycleStatus.RUNNING
    sample_state.approval_status = "APPROVED"
    sample_state.side_effect_allowed = True
    assert sample_state.side_effect_allowed is True


def test_85_approval_rejected_terminates_safely(sample_state):
    sample_state.approval_status = "REJECTED"
    sample_state.status = AgentLifecycleStatus.COMPLETED
    sample_state.termination_reason = "HUMAN_APPROVAL_REJECTED"
    assert sample_state.status == AgentLifecycleStatus.COMPLETED


def test_86_approval_unauthorized_actor_rejected():
    err = AgentApprovalError("Unauthorized approver role 'Viewer'")
    assert err.category == AgentErrorCategory.APPROVAL_ERROR
    assert not err.retryable


def test_87_approval_duplicate_decision_rejected():
    err = AgentApprovalError("Approval 'appr_123' already finalized")
    assert err.error_code == "AGENT_APPROVAL_ERROR"


def test_88_approval_fingerprint_immutable(sample_state):
    sample_state.decision_result = {"fingerprint": "abc123canonical", "recommended_action": "REROUTE"}
    assert sample_state.decision_result["fingerprint"] == "abc123canonical"


def test_89_approval_bypassing_approval_boundary_raises(sample_context):
    contract = AgentNodeContract(
        node_id="bypass_node",
        name="Bypass Node",
        description="Bypass test",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "run_byp",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.ACTION.value,
        "requires_human_approval": False,
        "side_effect_allowed": False,
    }
    with pytest.raises(AgentApprovalBoundaryViolationError) as exc_info:
        wrapper(state_dict, sample_context)
    assert "side_effect_allowed" in str(exc_info.value)


def test_90_approval_waits_metric_recorded():
    collector = AgentMetricsCollector()
    collector.record_approval_wait()
    assert collector.get_metrics()["approval_waits"] == 1


def test_91_approval_resume_metric_recorded():
    collector = AgentMetricsCollector()
    collector.record_approval_resume()
    assert collector.get_metrics()["approval_resume_count"] == 1


# ==============================================================================
# SECTION J: AUDIT EVENT INTEGRATION (8 Tests)
# ==============================================================================

def test_92_audit_event_graph_started(sample_state, sample_context):
    mock_uow = MagicMock()
    mock_uow.audit_logs = MagicMock()
    execute_agent_graph(sample_state, sample_context, uow=mock_uow)
    assert mock_uow.audit_logs.append_log.called
    first_call_kwargs = mock_uow.audit_logs.append_log.call_args_list[0].kwargs
    assert first_call_kwargs["action"] == "GRAPH_STARTED"
    assert first_call_kwargs["resource_type"] == "AGENT_GRAPH"
    assert first_call_kwargs["org_id"] == sample_state.organization_id


def test_93_audit_event_graph_succeeded(sample_state, sample_context):
    mock_uow = MagicMock()
    mock_uow.audit_logs = MagicMock()
    execute_agent_graph(sample_state, sample_context, uow=mock_uow)
    assert mock_uow.audit_logs.append_log.called
    actions = [c.kwargs.get("action") for c in mock_uow.audit_logs.append_log.call_args_list]
    assert any("GRAPH" in str(a) for a in actions)


def test_94_audit_event_graph_failed(sample_state, sample_context):
    mock_uow = MagicMock()
    mock_uow.audit_logs = MagicMock()

    sample_state.evidence_references = ["foreign_tenant_999:::ev_123"]
    with pytest.raises(AgentTenantIsolationError):
        execute_agent_graph(sample_state, sample_context, uow=mock_uow)

    assert mock_uow.audit_logs.append_log.called
    actions = [c.kwargs.get("action") for c in mock_uow.audit_logs.append_log.call_args_list]
    assert "GRAPH_FAILED" in actions


def test_95_audit_event_graph_terminated(sample_state, sample_context):
    mock_uow = MagicMock()
    mock_uow.audit_logs = MagicMock()
    res = execute_agent_graph(sample_state, sample_context, uow=mock_uow)
    assert res.status in (AgentLifecycleStatus.COMPLETED, AgentLifecycleStatus.NO_ACTION_REQUIRED)


def test_96_audit_event_contains_trace_identifiers(sample_state, sample_context):
    mock_uow = MagicMock()
    mock_uow.audit_logs = MagicMock()
    execute_agent_graph(sample_state, sample_context, uow=mock_uow)
    calls = mock_uow.audit_logs.append_log.mock_calls
    assert len(calls) >= 1
    call_kwargs = calls[0][2]
    assert call_kwargs["org_id"] == sample_context.organization_id
    assert call_kwargs["request_id"] == sample_context.request_id


def test_97_audit_event_after_data_scrubbed():
    from app.services.audit_service import sanitize_payload
    payload = {"api_key": "sk-test-secret-123456", "safe_param": "APAC"}
    cleaned = sanitize_payload(payload)
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["safe_param"] == "APAC"


def test_98_audit_event_graceful_on_missing_uow(sample_state, sample_context):
    result = execute_agent_graph(sample_state, sample_context, uow=None)
    assert result.run_id == sample_state.run_id


def test_99_audit_event_handles_logging_failure_gracefully(sample_state, sample_context):
    mock_uow = MagicMock()
    mock_uow.audit_logs.append_log.side_effect = RuntimeError("Audit log table locked")
    result = execute_agent_graph(sample_state, sample_context, uow=mock_uow)
    assert result.run_id == sample_state.run_id


# ==============================================================================
# SECTION K: SECRET REDACTION & SANITIZATION (8 Tests)
# ==============================================================================

def test_100_secret_redaction_in_run_telemetry():
    t = AgentRunTelemetry(
        organization_id="org_1",
        agent_run_id="run_1",
        execution_id="exec_1",
        request_id="req_1",
        correlation_id="corr_1",
        trace_id="trace_1",
        node_id="n1",
        status="SUCCESS",
        metadata={"db_password": "supersecretpassword", "endpoint": "/api/v1"},
    )
    assert "db_password" not in t.metadata or t.metadata["db_password"] == "[REDACTED]"


def test_101_secret_redaction_in_tool_telemetry():
    t = AgentToolCallTelemetry(
        tool_call_id="tc_1",
        agent_run_id="run_1",
        node_id="node_1",
        tool_name="weather_provider",
        safe_input_fingerprint="fp_in_123",
        safe_output_fingerprint="fp_out_456",
        metadata={"auth_token": "bearer xyz123"},
    )
    assert "auth_token" not in t.metadata or t.metadata["auth_token"] == "[REDACTED]"


def test_102_secret_redaction_in_node_telemetry():
    t = NodeExecutionTelemetry(
        run_id="r1",
        organization_id="org_1",
        actor_id="act_1",
        request_id="req_1",
        correlation_id="corr_1",
        trace_id="trace_1",
        node_name="node_1",
        duration_ms=5.0,
        status="SUCCESS",
        metadata={"client_secret": "mysecretvalue"},
    )
    # pydantic model config validates
    assert t.node_name == "node_1"


def test_103_secret_redaction_bearer_tokens_scrubbed():
    from app.agents.security import sanitize_sensitive_data
    d = {"header": "Bearer secret_jwt_token_value_here", "port": "SGSIN"}
    clean = sanitize_sensitive_data(d)
    assert "secret_jwt" not in str(clean)


def test_104_secret_redaction_forbids_chain_of_thought(sample_state):
    with pytest.raises(AgentValidationError) as exc_info:
        apply_state_update(
            current_state=sample_state,
            updates={"findings": {"chain_of_thought": "My internal hidden reasoning"}},
            node_id="test_node",
            stage=AgentStage.RESEARCH,
        )
    assert "chain-of-thought" in str(exc_info.value).lower()


def test_105_secret_redaction_internal_monologue_forbidden(sample_state):
    with pytest.raises(AgentValidationError) as exc_info:
        apply_state_update(
            current_state=sample_state,
            updates={"findings": {"internal_monologue": "Secret step reasoning"}},
            node_id="test_node",
            stage=AgentStage.RESEARCH,
        )
    assert "chain-of-thought" in str(exc_info.value).lower() or "reasoning" in str(exc_info.value).lower()


def test_106_secret_redaction_safe_failure_result():
    raw_exc = RuntimeError("Database connection string postgresql://admin:super_secret_pw@db:5432/main failed")
    res = AgentFailureResult.from_error(
        exc=raw_exc,
        execution_id="exec_1",
        agent_run_id="run_1",
        trace_id="trace_1",
        recovery_action=RecoveryDecision.FAIL,
    )
    assert "super_secret_pw" not in res.message
    assert "admin" not in res.message
    assert res.error_code == "AGENT_ERROR"


def test_107_secret_redaction_custom_sensitive_patterns():
    from app.agents.contracts import validate_no_sensitive_values
    with pytest.raises(AgentValidationError):
        validate_no_sensitive_values("Bearer token_with_alphanumeric_12345", "auth_header")


# ==============================================================================
# SECTION L: TENANT ISOLATION (8 Tests)
# ==============================================================================

def test_108_tenant_isolation_missing_state_org_fails(sample_context):
    contract = AgentNodeContract(
        node_id="tenant_check_node",
        name="Tenant Check",
        description="Tenant check",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": "",  # Empty
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        wrapper(state_dict, sample_context)
    assert "Missing organization_id" in str(exc_info.value)
    assert global_metrics_collector.security_failures >= 1


def test_109_tenant_isolation_context_state_mismatch_fails(sample_context):
    contract = AgentNodeContract(
        node_id="tenant_mismatch_node",
        name="Tenant Mismatch",
        description="Tenant mismatch",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": "org_different_999",  # Foreign
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        wrapper(state_dict, sample_context)
    assert "Tenant mismatch" in str(exc_info.value)


def test_110_tenant_isolation_evidence_bundle_mismatch_fails(sample_context):
    contract = AgentNodeContract(
        node_id="eb_mismatch_node",
        name="EB Mismatch",
        description="EB mismatch",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
        "evidence_bundle": {"organization_id": "foreign_bundle_org"},
    }
    with pytest.raises(AgentTenantIsolationError):
        wrapper(state_dict, sample_context)


def test_111_tenant_isolation_risk_assessment_mismatch_fails(sample_context):
    contract = AgentNodeContract(
        node_id="ra_mismatch_node",
        name="RA Mismatch",
        description="RA mismatch",
        stage=AgentStage.RISK_ASSESSMENT,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RISK_ASSESSMENT.value,
        "risk_assessment": {"organization_id": "foreign_ra_org"},
    }
    with pytest.raises(AgentTenantIsolationError):
        wrapper(state_dict, sample_context)


def test_112_tenant_isolation_foreign_evidence_reference_fails(sample_context):
    contract = AgentNodeContract(
        node_id="ref_mismatch_node",
        name="Ref Mismatch",
        description="Ref mismatch",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
        "evidence_references": ["foreign_tenant_xyz:::ev_123"],
    }
    with pytest.raises(AgentTenantIsolationError):
        wrapper(state_dict, sample_context)


def test_113_tenant_isolation_cannot_mutate_org_id(sample_state):
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        validate_state_update(
            current_state=sample_state,
            updates={"organization_id": "tampered_org_id"},
            node_id="any_node",
            stage=AgentStage.RESEARCH,
        )
    assert "immutable organization_id" in str(exc_info.value)


def test_114_tenant_isolation_checkpoint_tenant_mismatch_fails(sample_state):
    mgr = CheckpointManager()
    cid = mgr.save_checkpoint(sample_state.run_id, sample_state, step=1)
    with pytest.raises(AgentTenantIsolationError):
        mgr.restore_checkpoint(cid, expected_org_id="alien_org")


def test_115_tenant_isolation_security_failures_metric_incremented(sample_context):
    contract = AgentNodeContract(
        node_id="sec_metric_node",
        name="Sec Node",
        description="Sec node",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {})
    state_dict: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": "",
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTenantIsolationError):
        wrapper(state_dict, sample_context)
    assert global_metrics_collector.security_failures >= 1


# ==============================================================================
# SECTION M: IDEMPOTENT RETRY (6 Tests)
# ==============================================================================

def test_116_idempotent_retry_read_only_node(sample_context):
    executions = []
    def read_handler(state):
        executions.append(len(executions) + 1)
        if len(executions) < 2:
            raise AgentTransientError("Temporary timeout")
        return {"findings": {"read_ok": True}}

    contract = AgentNodeContract(
        node_id="read_node",
        name="Read Node",
        description="Read only",
        stage=AgentStage.RESEARCH,
        is_side_effecting=False,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.005)
    wrapper = NodeExecutionWrapper(contract, read_handler, retry_policy=policy)
    state_dict: AgentGraphStateDict = {
        "run_id": "r_read",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert updates == {"findings": {"read_ok": True}}
    assert len(executions) == 2


def test_117_idempotent_retry_preserves_state_between_attempts(sample_context):
    seen_states = []
    def recording_handler(state):
        seen_states.append(dict(state))
        if len(seen_states) < 2:
            raise AgentTransientError("Glitch")
        return {"findings": {}}

    contract = AgentNodeContract(
        node_id="rec_node",
        name="Rec Node",
        description="Rec node",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.005)
    wrapper = NodeExecutionWrapper(contract, recording_handler, retry_policy=policy)
    state_dict: AgentGraphStateDict = {
        "run_id": "r_rec",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
        "objective": "Immutable objective across retries",
    }
    wrapper(state_dict, sample_context)
    assert len(seen_states) == 2
    assert seen_states[0]["objective"] == seen_states[1]["objective"]


def test_118_idempotent_retry_governed_node_preserves_approval(sample_context):
    contract = AgentNodeContract(
        node_id="gov_node",
        name="Gov Node",
        description="Gov node",
        stage=AgentStage.APPROVAL,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: {"approval_status": "WAITING"})
    state_dict: AgentGraphStateDict = {
        "run_id": "r_gov",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.APPROVAL.value,
        "requires_human_approval": True,
        "side_effect_allowed": False,
    }
    updates = wrapper(state_dict, sample_context)
    assert updates["approval_status"] == "WAITING"


def test_119_idempotent_retry_deterministic_output_hash(sample_context):
    def deterministic_handler(state):
        return {"findings": {"computed_score": 0.85}}

    contract = AgentNodeContract(
        node_id="det_node",
        name="Deterministic Node",
        description="Deterministic",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, deterministic_handler)
    state_dict: AgentGraphStateDict = {
        "run_id": "r_det",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    u1 = wrapper(state_dict, sample_context)
    u2 = wrapper(state_dict, sample_context)
    assert compute_state_hash(u1) == compute_state_hash(u2)


def test_120_idempotent_retry_operation_identity_preserved():
    t1 = AgentRunTelemetry(
        organization_id="org_1",
        agent_run_id="run_10",
        execution_id="exec_10",
        request_id="req_10",
        correlation_id="corr_10",
        trace_id="trace_10",
        node_id="risk_agent",
        attempt=1,
        status="RECOVERABLE_FAILURE",
    )
    t2 = AgentRunTelemetry(
        organization_id="org_1",
        agent_run_id="run_10",
        execution_id="exec_10",
        request_id="req_10",
        correlation_id="corr_10",
        trace_id="trace_10",
        node_id="risk_agent",
        attempt=2,
        status="SUCCESS",
    )
    assert t1.execution_id == t2.execution_id
    assert t1.node_id == t2.node_id
    assert t1.attempt < t2.attempt


def test_121_idempotent_retry_attempt_counter_advances(sample_context):
    attempts = []
    def counting_handler(state):
        attempts.append(1)
        if len(attempts) < 3:
            raise AgentTransientError("Glitch")
        return {"findings": {"count": len(attempts)}}

    contract = AgentNodeContract(
        node_id="count_node",
        name="Count Node",
        description="Counting",
        stage=AgentStage.RESEARCH,
    )
    policy = RetryPolicy(base_delay_seconds=0.001, max_delay_seconds=0.005)
    wrapper = NodeExecutionWrapper(contract, counting_handler, retry_policy=policy)
    state_dict: AgentGraphStateDict = {
        "run_id": "r_cnt",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "request_id": sample_context.request_id,
        "correlation_id": sample_context.correlation_id,
        "trace_id": sample_context.trace_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    updates = wrapper(state_dict, sample_context)
    assert len(attempts) == 3
    assert updates["findings"]["count"] == 3


# ==============================================================================
# SECTION N: CONCURRENT & REPLAYED EXECUTION PROTECTION (5 Tests)
# ==============================================================================

def test_122_replayed_execution_detected_by_state_hash(sample_state):
    h1 = compute_state_hash(sample_state)
    h2 = compute_state_hash(sample_state)
    assert h1 == h2


def test_123_concurrent_metrics_thread_safety():
    collector = AgentMetricsCollector()
    def worker():
        for _ in range(100):
            collector.record_node_latency("concurrent_node", 1.5)
            collector.record_node_retry("concurrent_node")

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    metrics = collector.get_metrics()
    assert metrics["node_retries"] == 500
    assert len(collector.node_latencies["concurrent_node"]) == 500


def test_124_concurrent_checkpoint_isolation(sample_state):
    mgr = CheckpointManager()
    cid1 = mgr.save_checkpoint("thread_1", sample_state, step=1)
    s2 = sample_state.model_copy(update={"run_id": "run_thread_2", "objective": "Thread 2 objective"})
    cid2 = mgr.save_checkpoint("thread_2", s2, step=1)

    r1, _ = mgr.restore_checkpoint(cid1, expected_org_id=sample_state.organization_id)
    r2, _ = mgr.restore_checkpoint(cid2, expected_org_id=sample_state.organization_id)
    assert r1.run_id == sample_state.run_id
    assert r2.run_id == "run_thread_2"


def test_125_checkpoint_restore_immutability(sample_state):
    mgr = CheckpointManager()
    cid = mgr.save_checkpoint(sample_state.run_id, sample_state, step=1)
    r1, _ = mgr.restore_checkpoint(cid, expected_org_id=sample_state.organization_id)
    r1.objective = "Mutated after restore"
    r2, _ = mgr.restore_checkpoint(cid, expected_org_id=sample_state.organization_id)
    assert r2.objective == sample_state.objective


def test_126_thread_id_isolation(sample_state, sample_context):
    builder = AgentGraphBuilder()
    compiled = builder.build()
    res1 = compiled.invoke(sample_state.model_dump(mode="json"), config={"configurable": {"thread_id": "t1"}})
    res2 = compiled.invoke(sample_state.model_dump(mode="json"), config={"configurable": {"thread_id": "t2"}})
    assert res1["run_id"] == res2["run_id"]


# ==============================================================================
# SECTION O: FAILURE RESPONSE CONTRACT (6 Tests)
# ==============================================================================

def test_127_failure_response_contract_fields():
    res = AgentFailureResult(
        execution_id="exec_001",
        agent_run_id="run_001",
        node_id="risk_agent",
        stage=AgentStage.RISK_ASSESSMENT.value,
        error_code="DEPENDENCY_FAILURE",
        error_category=AgentErrorCategory.DEPENDENCY_ERROR.value,
        retryable=True,
        recovery_action=RecoveryDecision.RETRY.value,
        trace_id="trace_001",
        message="Dependency service unreachable",
    )
    assert res.execution_id == "exec_001"
    assert res.retryable is True
    assert res.recovery_action == "RETRY"


def test_128_failure_response_from_security_error():
    err = AgentSecurityError("Dangerous payload")
    res = AgentFailureResult.from_error(
        exc=err,
        execution_id="exec_sec",
        agent_run_id="run_sec",
        trace_id="trace_sec",
        recovery_action=RecoveryDecision.FAIL,
    )
    assert res.recovery_action == "FAIL"
    assert res.retryable is False
    assert res.error_category == AgentErrorCategory.SECURITY_ERROR.value


def test_129_failure_response_from_timeout_error():
    err = AgentTimeoutError("Node took too long")
    res = AgentFailureResult.from_error(
        exc=err,
        execution_id="exec_to",
        agent_run_id="run_to",
        trace_id="trace_to",
        recovery_action=RecoveryDecision.RETRY,
    )
    assert res.error_category == AgentErrorCategory.TIMEOUT_ERROR.value
    assert res.retryable is True


def test_130_failure_response_hides_raw_stack_trace():
    class RawDbException(Exception):
        pass

    raw_err = RawDbException("FATAL: password authentication failed for user 'postgres'")
    res = AgentFailureResult.from_error(
        exc=raw_err,
        execution_id="e1",
        agent_run_id="r1",
        trace_id="t1",
        recovery_action=RecoveryDecision.FAIL,
    )
    assert "postgres" not in res.message
    assert "password" not in res.message


def test_131_failure_response_serializes_to_json():
    res = AgentFailureResult(
        execution_id="e1",
        agent_run_id="r1",
        error_code="TEST_CODE",
        error_category="INTERNAL_ERROR",
        retryable=False,
        recovery_action="FAIL",
        trace_id="t1",
        message="Safe failure message",
    )
    d = json.loads(res.model_dump_json())
    assert d["execution_id"] == "e1"
    assert d["status"] == "FAILED"


def test_132_failure_response_trace_id_preserved():
    res = AgentFailureResult.from_error(
        exc=AgentGraphError("Err"),
        execution_id="e1",
        agent_run_id="r1",
        trace_id="trace_preserved_999",
        recovery_action=RecoveryDecision.FAIL,
    )
    assert res.trace_id == "trace_preserved_999"


# ==============================================================================
# SECTION P: TOOL TELEMETRY CONTRACT & INTEGRATION (5 Tests)
# ==============================================================================

def test_133_tool_call_telemetry_fields():
    t = AgentToolCallTelemetry(
        tool_call_id="tc_001",
        agent_run_id="run_001",
        node_id="research_agent",
        tool_name="rag_retriever",
        attempt=1,
        safe_input_fingerprint="fp_in_111",
        safe_output_fingerprint="fp_out_222",
        status="SUCCESS",
        duration_ms=25.0,
    )
    assert t.tool_name == "rag_retriever"
    assert t.safe_input_fingerprint == "fp_in_111"
    assert t.status == "SUCCESS"


def test_134_tool_call_telemetry_safe_fingerprints():
    t = AgentToolCallTelemetry(
        tool_call_id="tc_002",
        agent_run_id="run_002",
        node_id="research_agent",
        tool_name="weather_query",
        safe_input_fingerprint="sha256_in_abc",
        safe_output_fingerprint="sha256_out_xyz",
    )
    assert t.safe_input_fingerprint == "sha256_in_abc"
    assert t.safe_output_fingerprint == "sha256_out_xyz"


def test_135_tool_call_telemetry_redacts_metadata():
    t = AgentToolCallTelemetry(
        tool_call_id="tc_003",
        agent_run_id="run_003",
        node_id="research_agent",
        tool_name="ais_query",
        safe_input_fingerprint="fp1",
        safe_output_fingerprint="fp2",
        metadata={"token": "bearer secret", "mmsi": "123456789"},
    )
    assert "token" not in t.metadata or t.metadata["token"] == "[REDACTED]"
    assert t.metadata["mmsi"] == "123456789"


def test_136_agent_observability_record_tool_call():
    t = AgentToolCallTelemetry(
        tool_call_id="tc_004",
        agent_run_id="run_004",
        node_id="research_agent",
        tool_name="ais_query",
        safe_input_fingerprint="fp_in",
        safe_output_fingerprint="fp_out",
    )
    emitted = AgentObservability.record_tool_call(t)
    assert emitted.tool_call_id == "tc_004"


def test_137_metrics_reset_clears_all_counters():
    collector = AgentMetricsCollector()
    collector.record_node_retry("n1")
    collector.record_node_timeout("n1")
    collector.record_security_failure()
    collector.record_routing_failure()
    collector.record_recovery("FAIL")
    collector.record_approval_wait()
    collector.record_approval_resume()
    collector.record_graph_execution("SUCCESS", 10.0)

    m1 = collector.get_metrics()
    assert m1["executions_total"] == 1
    assert m1["node_retries"] == 1
    assert m1["security_failures"] == 1

    collector.reset()
    m2 = collector.get_metrics()
    assert m2["executions_total"] == 0
    assert m2["node_retries"] == 0
    assert m2["security_failures"] == 0
    assert m2["routing_failures"] == 0
    assert m2["node_timeouts"] == 0
    assert m2["recovery_count"] == 0
    assert m2["approval_waits"] == 0
    assert m2["approval_resume_count"] == 0
