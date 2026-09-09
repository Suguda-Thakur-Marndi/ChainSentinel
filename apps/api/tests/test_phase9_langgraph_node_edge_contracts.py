"""Phase 9 Step 3 — LangGraph Node & Edge Contracts Test Suite.

Exhaustively verifies:
1. Node contracts, node metadata, input requirements, output permissions, stage definitions.
2. Node registry, deterministic registration, allowlist enforcement, invalid node rejection.
3. Edge contracts, typed edge classes, endpoint allowlists, duplicate detection.
4. Stage transition validation, forward flow, backward rejection, bounded retry self-loops.
5. Conditional routing, deterministic ConditionEvaluator, eval/expression injection rejection.
6. Retry edges, retryable errors, non-retryable errors, bounded retry attempts.
7. Failure edges, error categorization, error preservation, correlation IDs.
8. Termination edges, lifecycle statuses (COMPLETED, FAILED, BLOCKED, NO_ACTION, etc.), END.
9. Approval gate, side-effect boundary enforcement, governance condition checks.
10. Tenant isolation, foreign reference rejection, authorization, role enforcement.
11. Observability, telemetry emission, correlation/trace IDs, secret/CoT redaction.
12. Graph validation, reachability, cycle boundedness, terminal path validation.
13. Real LangGraph compilation and execution using in-memory checkpointer.
"""

from __future__ import annotations

import time
import uuid
import pytest
from pydantic import ValidationError

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.contracts import (
    AgentEdgeContract,
    AgentErrorState,
    AgentExecutionContext,
    AgentFinding,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentLimitation,
    AgentNodeContract,
    AgentStage,
    ConditionCode,
    ConflictResolutionStatus,
    EdgeType,
    LimitationCategory,
    NodeContract,
    RAGEvidenceReference,
    RiskAssessmentReference,
    RouteDecision,
    RoutingReasonCode,
    ToolSideEffectType,
    apply_state_update,
    validate_state_update,
)
from app.agents.edges import (
    ALLOWED_STAGE_TRANSITIONS,
    ConditionEvaluator,
    EdgeRegistry,
    StageTransitionValidator,
    global_edge_registry,
)
from app.agents.errors import (
    AgentApprovalBoundaryViolationError,
    AgentDependencyFailureError,
    AgentEvidenceIntegrityError,
    AgentGraphError,
    AgentGraphValidationError,
    AgentInvalidEdgeError,
    AgentInvalidRouteError,
    AgentMissingInputError,
    AgentNodeExecutionError,
    AgentStageTransitionError,
    AgentStateOwnershipViolationError,
    AgentStateSizeLimitError,
    AgentTenantIsolationError,
    AgentTimeoutError,
    AgentToolAuthorizationError,
    AgentUnauthorizedNodeError,
    AgentValidationError,
    ErrorClassification,
)
from app.agents.execution import NodeExecutionWrapper
from app.agents.graph import AgentGraphBuilder, execute_agent_graph
from app.agents.nodes import (
    APPROVAL_BOUNDARY_NODE_CONTRACT,
    INITIALIZATION_NODE_CONTRACT,
    TERMINATION_NODE_CONTRACT,
    approval_boundary_node,
    create_safe_placeholder_node,
    initialization_node,
    termination_node,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.registry import NodeRegistry, global_node_registry
from app.agents.routing import RouteEvaluator
from app.agents.validator import GraphValidator


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture
def clean_node_registry() -> NodeRegistry:
    """Isolated NodeRegistry for testing without contaminating global state."""
    registry = NodeRegistry()
    registry.register_node(INITIALIZATION_NODE_CONTRACT, initialization_node)
    registry.register_node(TERMINATION_NODE_CONTRACT, termination_node)
    registry.register_node(APPROVAL_BOUNDARY_NODE_CONTRACT, approval_boundary_node)
    return registry


@pytest.fixture
def clean_edge_registry(clean_node_registry: NodeRegistry) -> EdgeRegistry:
    """Isolated EdgeRegistry for testing without contaminating global state."""
    return EdgeRegistry(node_registry=clean_node_registry)


@pytest.fixture
def sample_context() -> AgentExecutionContext:
    """Standard authorized execution context."""
    return AgentExecutionContext(
        organization_id="org_test_123",
        actor_id="usr_test_456",
        roles=["risk_manager", "compliance_officer"],
        permissions=["read", "write", "approve", "assess_risk"],
        request_id="req_test_789",
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
    )


@pytest.fixture
def sample_state() -> AgentGraphState:
    """Standard verified graph state."""
    return AgentGraphState(
        run_id="run_test_001",
        organization_id="org_test_123",
        actor_id="usr_test_456",
        objective="Assess supply chain risk posture",
        request_id="req_test_789",
        correlation_id="corr_test_001",
        trace_id="trace_test_002",
        status=AgentLifecycleStatus.INITIALIZING,
        current_stage=AgentStage.INITIALIZATION,
        step_count=0,
    )


# ==============================================================================
# GROUP 1: NODE CONTRACTS & IDENTITY
# ==============================================================================

def test_01_valid_agent_node_contract() -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Gathers evidence and facts",
        stage=AgentStage.RESEARCH,
        required_inputs=["objective"],
        allowed_outputs=["findings", "evidence_references"],
        requires_evidence=True,
        minimum_evidence=1,
        required_roles=["analyst"],
        retryable=True,
        max_retries=2,
        timeout_seconds=45.0,
    )
    assert contract.node_id == "research_agent"
    assert contract.node_name == "research_agent"
    assert contract.stage == AgentStage.RESEARCH
    assert contract.required_inputs == ["objective"]
    assert contract.input_keys == ["objective"]
    assert contract.allowed_outputs == ["findings", "evidence_references"]
    assert contract.output_keys == ["findings", "evidence_references"]
    assert contract.retryable is True
    assert contract.max_retries == 2


def test_02_node_contract_empty_name_fails() -> None:
    with pytest.raises(ValidationError):
        AgentNodeContract(
            node_id="",
            name="Blank Node",
            description="Empty id",
            stage=AgentStage.RESEARCH,
        )


def test_03_node_contract_invalid_stage_fails() -> None:
    with pytest.raises(ValidationError):
        AgentNodeContract(
            node_id="research_agent",
            name="Research Agent",
            description="Invalid stage test",
            stage="NON_EXISTENT_STAGE",  # type: ignore
        )


def test_04_node_contract_input_requirements() -> None:
    contract = AgentNodeContract(
        node_id="risk_agent",
        name="Risk Agent",
        description="Assesses risk posture",
        stage=AgentStage.RISK_ASSESSMENT,
        required_inputs=["evidence_references", "objective"],
        allowed_outputs=["findings", "risk_alert_references"],
    )
    assert "evidence_references" in contract.required_inputs
    assert "objective" in contract.required_inputs


def test_05_node_contract_output_permissions_sync() -> None:
    # Providing output_keys syncs allowed_outputs and vice-versa
    c1 = AgentNodeContract(
        node_id="decision_agent",
        name="Decision Agent",
        description="Synthesizes options",
        stage=AgentStage.DECISION,
        output_keys=["recommendation_references"],
    )
    assert c1.allowed_outputs == ["recommendation_references"]

    c2 = AgentNodeContract(
        node_id="decision_agent",
        name="Decision Agent",
        description="Synthesizes options",
        stage=AgentStage.DECISION,
        allowed_outputs=["findings"],
    )
    assert c2.output_keys == ["findings"]


def test_06_node_contract_side_effect_classification() -> None:
    read_only = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Read only",
        stage=AgentStage.RESEARCH,
        is_side_effecting=False,
    )
    assert read_only.side_effect_type == ToolSideEffectType.READ_ONLY

    side_effect = AgentNodeContract(
        node_id="action_agent",
        name="Action Agent",
        description="Side effecting",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    assert side_effect.side_effect_type == ToolSideEffectType.SIDE_EFFECTING


def test_07_node_contract_evidence_requirements() -> None:
    contract = AgentNodeContract(
        node_id="prediction_agent",
        name="Prediction Agent",
        description="Forecasts impact",
        stage=AgentStage.PREDICTION,
        requires_evidence=True,
        minimum_evidence=2,
        required_evidence_types=["market_signal", "supplier_history"],
        required_references=["evidence_bundle"],
    )
    assert contract.requires_evidence is True
    assert contract.minimum_evidence == 2
    assert len(contract.required_evidence_types) == 2
    assert contract.required_references == ["evidence_bundle"]


def test_08_node_contract_role_requirements() -> None:
    contract = AgentNodeContract(
        node_id="action_agent",
        name="Action Agent",
        description="Executes action",
        stage=AgentStage.ACTION,
        required_roles=["admin"],
        required_permissions=["execute_action"],
    )
    assert "admin" in contract.required_roles
    assert "execute_action" in contract.required_permissions


def test_09_node_contract_retry_policy() -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Retries up to 3 times",
        stage=AgentStage.RESEARCH,
        retryable=True,
        max_retries=3,
    )
    assert contract.retryable is True
    assert contract.max_retries == 3


def test_10_node_contract_timeout_and_extra_fields() -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Timeout test",
        stage=AgentStage.RESEARCH,
        timeout_seconds=60.0,
    )
    assert contract.timeout_seconds == 60.0

    with pytest.raises(ValidationError):
        AgentNodeContract(
            node_id="research_agent",
            name="Research Agent",
            description="Extra fields test",
            stage=AgentStage.RESEARCH,
            unexpected_field="disallowed",  # type: ignore
        )


# ==============================================================================
# GROUP 2: NODE REGISTRY & ALLOWLIST
# ==============================================================================

def test_11_node_registry_registration_and_lookup(clean_node_registry: NodeRegistry) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Research agent",
        stage=AgentStage.RESEARCH,
    )
    handler = create_safe_placeholder_node(contract)
    clean_node_registry.register_node(contract, handler)

    entry = clean_node_registry.get_node("research_agent")
    assert entry.contract.node_id == "research_agent"
    assert clean_node_registry.has_node("research_agent") is True


def test_12_node_registry_duplicate_registration_rejected(clean_node_registry: NodeRegistry) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Research agent",
        stage=AgentStage.RESEARCH,
    )
    handler = create_safe_placeholder_node(contract)
    clean_node_registry.register_node(contract, handler)

    with pytest.raises(AgentValidationError) as exc_info:
        clean_node_registry.register_node(contract, handler)
    assert "already registered" in str(exc_info.value)


def test_13_node_registry_unknown_node_lookup_fails(clean_node_registry: NodeRegistry) -> None:
    with pytest.raises(AgentUnauthorizedNodeError) as exc_info:
        clean_node_registry.get_node("unregistered_ghost_node")
    assert "not registered" in str(exc_info.value)


def test_14_node_registry_allowlist_enforcement(clean_node_registry: NodeRegistry) -> None:
    assert clean_node_registry.is_allowed("initialization") is True
    assert clean_node_registry.is_allowed("termination") is True
    assert clean_node_registry.is_allowed("malicious_injected_node") is False


def test_15_node_registry_arbitrary_unallowlisted_name_rejected(clean_node_registry: NodeRegistry) -> None:
    contract = AgentNodeContract(
        node_id="eval_python_arbitrary_code",
        name="Arbitrary Node",
        description="Disallowed id",
        stage=AgentStage.RESEARCH,
    )
    with pytest.raises(AgentUnauthorizedNodeError) as exc_info:
        clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))
    assert "not in the architectural allowlist" in str(exc_info.value)


def test_16_node_registry_list_nodes_deterministic_order(clean_node_registry: NodeRegistry) -> None:
    nodes = clean_node_registry.list_nodes()
    node_ids = [n.node_id for n in nodes]
    assert node_ids == sorted(node_ids)


def test_17_node_registry_is_allowed_query(clean_node_registry: NodeRegistry) -> None:
    assert clean_node_registry.is_allowed("research_agent") is True
    assert clean_node_registry.is_allowed("risk_agent") is True
    assert clean_node_registry.is_allowed("unknown_xyz") is False


def test_18_node_registry_clear(clean_node_registry: NodeRegistry) -> None:
    clean_node_registry.clear()
    assert len(clean_node_registry.list_nodes()) == 0
    assert clean_node_registry.has_node("initialization") is False


# ==============================================================================
# GROUP 3: EDGE CONTRACTS & TOPOLOGY
# ==============================================================================

def test_19_valid_agent_edge_contract() -> None:
    edge = AgentEdgeContract(
        edge_id="init_to_research",
        from_node="initialization",
        to_node="research_agent",
        edge_type=EdgeType.NORMAL,
        reason_code=RoutingReasonCode.INITIAL_ROUTE.value,
        condition_code=ConditionCode.ALWAYS.value,
    )
    assert edge.edge_id == "init_to_research"
    assert edge.from_node == "initialization"
    assert edge.to_node == "research_agent"
    assert edge.edge_type == EdgeType.NORMAL
    assert edge.reason_code == "INITIAL_ROUTE"


def test_20_edge_contract_empty_fields_fail() -> None:
    with pytest.raises(AgentValidationError):
        AgentEdgeContract(
            edge_id="",
            from_node="initialization",
            to_node="research_agent",
            reason_code="REASON",
        )
    with pytest.raises(AgentValidationError):
        AgentEdgeContract(
            edge_id="e1",
            from_node="   ",
            to_node="research_agent",
            reason_code="REASON",
        )


def test_21_edge_contract_forbids_arbitrary_extras() -> None:
    with pytest.raises(ValidationError):
        AgentEdgeContract(
            edge_id="e1",
            from_node="initialization",
            to_node="research_agent",
            reason_code="REASON",
            dynamic_code="malicious()",  # type: ignore
        )


def test_22_edge_registry_registration_and_lookup(
    clean_node_registry: NodeRegistry,
    clean_edge_registry: EdgeRegistry,
) -> None:
    # Register research_agent in node registry first
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
    )
    clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))

    edge = AgentEdgeContract(
        edge_id="init_to_research",
        from_node="initialization",
        to_node="research_agent",
        edge_type=EdgeType.NORMAL,
        reason_code=RoutingReasonCode.INITIAL_ROUTE.value,
    )
    clean_edge_registry.register_edge(edge)
    assert clean_edge_registry.has_edge("init_to_research") is True
    retrieved = clean_edge_registry.get_edge("init_to_research")
    assert retrieved.edge_id == "init_to_research"


def test_23_edge_registry_duplicate_edge_id_rejected(
    clean_node_registry: NodeRegistry,
    clean_edge_registry: EdgeRegistry,
) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
    )
    clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))

    edge = AgentEdgeContract(
        edge_id="dup_edge",
        from_node="initialization",
        to_node="research_agent",
        reason_code="R1",
    )
    clean_edge_registry.register_edge(edge)
    with pytest.raises(AgentInvalidEdgeError) as exc_info:
        clean_edge_registry.register_edge(edge)
    assert "already registered" in str(exc_info.value)


def test_24_edge_registry_unknown_edge_lookup_fails(clean_edge_registry: EdgeRegistry) -> None:
    with pytest.raises(AgentInvalidEdgeError) as exc_info:
        clean_edge_registry.get_edge("non_existent_edge")
    assert "not registered" in str(exc_info.value)


def test_25_edge_registry_unregistered_source_node_rejected(clean_edge_registry: EdgeRegistry) -> None:
    edge = AgentEdgeContract(
        edge_id="e_invalid_source",
        from_node="unregistered_source",
        to_node="termination",
        reason_code="R1",
    )
    with pytest.raises(AgentInvalidEdgeError) as exc_info:
        clean_edge_registry.register_edge(edge)
    assert "Source node 'unregistered_source' is not registered" in str(exc_info.value)


def test_26_edge_registry_unregistered_dest_node_rejected(clean_edge_registry: EdgeRegistry) -> None:
    edge = AgentEdgeContract(
        edge_id="e_invalid_dest",
        from_node="initialization",
        to_node="unregistered_dest",
        reason_code="R1",
    )
    with pytest.raises(AgentInvalidEdgeError) as exc_info:
        clean_edge_registry.register_edge(edge)
    assert "Destination node 'unregistered_dest' is not registered" in str(exc_info.value)


def test_27_edge_registry_special_nodes_allowed_endpoints(clean_edge_registry: EdgeRegistry) -> None:
    start_edge = AgentEdgeContract(
        edge_id="start_edge",
        from_node="START",
        to_node="initialization",
        reason_code="START",
    )
    clean_edge_registry.register_edge(start_edge)
    assert clean_edge_registry.has_edge("start_edge") is True

    end_edge = AgentEdgeContract(
        edge_id="end_edge",
        from_node="termination",
        to_node="END",
        edge_type=EdgeType.TERMINATION,
        reason_code="END",
        is_terminal=True,
    )
    clean_edge_registry.register_edge(end_edge)
    assert clean_edge_registry.has_edge("end_edge") is True


def test_28_edge_registry_outgoing_edges_query(
    clean_node_registry: NodeRegistry,
    clean_edge_registry: EdgeRegistry,
) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
    )
    clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))

    e1 = AgentEdgeContract(
        edge_id="init_to_research",
        from_node="initialization",
        to_node="research_agent",
        reason_code="R1",
    )
    e2 = AgentEdgeContract(
        edge_id="init_to_term",
        from_node="initialization",
        to_node="termination",
        reason_code="R2",
    )
    clean_edge_registry.register_edge(e1)
    clean_edge_registry.register_edge(e2)

    outgoing = clean_edge_registry.get_outgoing_edges("initialization")
    assert len(outgoing) == 2
    assert {e.edge_id for e in outgoing} == {"init_to_research", "init_to_term"}


# ==============================================================================
# GROUP 4: STAGE TRANSITION VALIDATION
# ==============================================================================

def test_29_valid_stage_transitions_forward() -> None:
    assert StageTransitionValidator.is_valid_transition(AgentStage.INITIALIZATION, AgentStage.RESEARCH) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.RESEARCH, AgentStage.RISK_ASSESSMENT) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.RISK_ASSESSMENT, AgentStage.PREDICTION) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.PREDICTION, AgentStage.DECISION) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.DECISION, AgentStage.APPROVAL) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.APPROVAL, AgentStage.ACTION) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.ACTION, AgentStage.VERIFICATION) is True
    assert StageTransitionValidator.is_valid_transition(AgentStage.VERIFICATION, AgentStage.TERMINATION) is True


def test_30_invalid_backward_stage_transition_fails_closed() -> None:
    with pytest.raises(AgentStageTransitionError) as exc_info:
        StageTransitionValidator.validate_transition(
            current_stage=AgentStage.DECISION,
            destination_stage=AgentStage.RESEARCH,
        )
    assert "Illegal stage transition" in str(exc_info.value)
    assert "DECISION -> RESEARCH" in str(exc_info.value)


def test_31_action_to_research_backward_transition_rejected() -> None:
    with pytest.raises(AgentStageTransitionError):
        StageTransitionValidator.validate_transition(
            current_stage=AgentStage.ACTION,
            destination_stage=AgentStage.RESEARCH,
        )


def test_32_verification_to_prediction_backward_transition_rejected() -> None:
    with pytest.raises(AgentStageTransitionError):
        StageTransitionValidator.validate_transition(
            current_stage=AgentStage.VERIFICATION,
            destination_stage=AgentStage.PREDICTION,
        )


def test_33_retry_self_loop_transition_allowed() -> None:
    assert StageTransitionValidator.is_valid_transition(
        AgentStage.RESEARCH,
        AgentStage.RESEARCH,
        is_retry=True,
    ) is True
    # validate_transition does not raise
    StageTransitionValidator.validate_transition(
        current_stage=AgentStage.RESEARCH,
        destination_stage=AgentStage.RESEARCH,
        is_retry=True,
    )


def test_34_non_retry_self_loop_transition_rejected() -> None:
    with pytest.raises(AgentStageTransitionError) as exc_info:
        StageTransitionValidator.validate_transition(
            current_stage=AgentStage.RESEARCH,
            destination_stage=AgentStage.RESEARCH,
            is_retry=False,
        )
    assert "Self-loop transition" in str(exc_info.value)


def test_35_termination_has_no_outgoing_transitions() -> None:
    with pytest.raises(AgentStageTransitionError) as exc_info:
        StageTransitionValidator.validate_transition(
            current_stage=AgentStage.TERMINATION,
            destination_stage=AgentStage.RESEARCH,
        )
    assert "Terminal stage" in str(exc_info.value)


def test_36_unknown_stage_transition_rejected() -> None:
    with pytest.raises(AgentStageTransitionError):
        StageTransitionValidator.validate_transition(
            current_stage="NON_EXISTENT_1",  # type: ignore
            destination_stage=AgentStage.RESEARCH,
        )


# ==============================================================================
# GROUP 5: CONDITIONAL ROUTING & EVAL REJECTION
# ==============================================================================

def test_37_condition_evaluator_always() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.ALWAYS, {}) is True
    assert ConditionEvaluator.evaluate("ALWAYS", {}) is True


def test_38_condition_evaluator_has_errors() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.HAS_ERRORS, {"errors": []}) is False
    assert ConditionEvaluator.evaluate(ConditionCode.HAS_ERRORS, {"errors": [{"msg": "err"}]}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.HAS_ERRORS, {"status": "FAILED"}) is True


def test_39_condition_evaluator_is_retryable() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.IS_RETRYABLE, {"can_retry": True}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.IS_RETRYABLE, {"can_retry": False}) is False


def test_40_condition_evaluator_needs_approval() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.NEEDS_APPROVAL, {"requires_human_approval": True}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.NEEDS_APPROVAL, {"requires_human_approval": False}) is False


def test_41_condition_evaluator_approval_approved() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.APPROVAL_APPROVED, {"approval_decision": "APPROVED"}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.APPROVAL_APPROVED, {"approval_decision": "REJECTED"}) is False


def test_42_condition_evaluator_approval_rejected() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.APPROVAL_REJECTED, {"approval_decision": "REJECTED"}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.APPROVAL_REJECTED, {"approval_decision": "APPROVED"}) is False


def test_43_condition_evaluator_evidence_satisfied() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.EVIDENCE_SATISFIED, {"evidence_references": ["ev1"]}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.EVIDENCE_SATISFIED, {"evidence_references": []}) is False


def test_44_condition_evaluator_max_steps_reached() -> None:
    assert ConditionEvaluator.evaluate(ConditionCode.MAX_STEPS_REACHED, {"step_count": 25}) is True
    assert ConditionEvaluator.evaluate(ConditionCode.MAX_STEPS_REACHED, {"step_count": 10}) is False


def test_45_arbitrary_code_and_eval_rejection_in_evaluator() -> None:
    with pytest.raises(AgentValidationError) as exc_info:
        ConditionEvaluator.evaluate("lambda state: True", {})
    assert "Unregistered or unsupported condition code" in str(exc_info.value)

    with pytest.raises(AgentValidationError) as exc_info2:
        ConditionEvaluator.evaluate("__import__('os').system('ls')", {})
    assert "Unregistered or unsupported condition code" in str(exc_info2.value)


# ==============================================================================
# GROUP 6: RETRY SEMANTICS
# ==============================================================================

def test_46_retry_transition_allowed_when_retryable_and_under_max(
    clean_node_registry: NodeRegistry,
    clean_edge_registry: EdgeRegistry,
) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
        retryable=True,
        max_retries=3,
    )
    clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))

    retry_edge = AgentEdgeContract(
        edge_id="retry_research",
        from_node="research_agent",
        to_node="research_agent",
        edge_type=EdgeType.RETRY,
        reason_code=RoutingReasonCode.RETRYABLE_FAILURE.value,
        condition_code=ConditionCode.IS_RETRYABLE.value,
    )
    clean_edge_registry.register_edge(retry_edge)
    assert clean_edge_registry.has_edge("retry_research") is True


def test_47_retry_rejected_when_max_retries_reached(
    clean_node_registry: NodeRegistry,
    clean_edge_registry: EdgeRegistry,
) -> None:
    evaluator = RouteEvaluator(registry=clean_node_registry, edge_registry=clean_edge_registry)
    # State with retry_count >= max_retries (default 3 in state)
    state: AgentGraphStateDict = {
        "retry_count": 3,
        "max_retries": 3,
        "errors": [{"error": "network timeout"}],
        "step_count": 5,
    }
    decision = evaluator.evaluate(state)
    assert decision.next_node == "termination"
    assert decision.termination_flag is True


def test_48_retry_rejected_when_node_not_retryable(clean_node_registry: NodeRegistry) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Non Retry Research",
        description="No retries",
        stage=AgentStage.RESEARCH,
        retryable=False,
        max_retries=0,
    )
    edge = AgentEdgeContract(
        edge_id="invalid_retry",
        from_node="research_agent",
        to_node="research_agent",
        edge_type=EdgeType.RETRY,
        reason_code="RETRY",
    )
    clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)
    edge_reg.register_edge(edge, validate_stages=False)

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "not marked as retryable" in str(exc_info.value)


def test_49_retry_rejected_on_security_tenant_violation() -> None:
    err = AgentTenantIsolationError("Tenant mismatch")
    assert err.classification == ErrorClassification.NON_RETRYABLE


def test_50_retry_rejected_on_authorization_failure() -> None:
    err = AgentUnauthorizedNodeError("Unauthorized")
    assert err.classification == ErrorClassification.NON_RETRYABLE


def test_51_retry_rejected_on_evidence_integrity_failure() -> None:
    err = AgentEvidenceIntegrityError("Tampered bundle")
    assert err.classification == ErrorClassification.NON_RETRYABLE


def test_52_retry_cycle_bounded_enforcement(clean_node_registry: NodeRegistry) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
        retryable=True,
        max_retries=2,
    )
    clean_node_registry.register_node(contract, create_safe_placeholder_node(contract))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    # Valid bounded retry edge
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="start_to_research",
        from_node="START",
        to_node="research_agent",
        reason_code="START",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="retry_research",
        from_node="research_agent",
        to_node="research_agent",
        edge_type=EdgeType.RETRY,
        reason_code="RETRY",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="research_to_term",
        from_node="research_agent",
        to_node="termination",
        reason_code="DONE",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="term_to_end",
        from_node="termination",
        to_node="END",
        edge_type=EdgeType.TERMINATION,
        reason_code="END",
        is_terminal=True,
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    validator.validate()  # Passes because retry cycle is bounded by max_retries <= 10


# ==============================================================================
# GROUP 7: FAILURE TRANSITIONS & PRESERVATION
# ==============================================================================

def test_53_failure_edge_routing_on_error() -> None:
    evaluator = RouteEvaluator()
    decision = evaluator.evaluate({"errors": [{"error": "fatal failure"}]})
    assert decision.next_node == "termination"
    assert decision.termination_flag is True
    assert decision.reason_code == RoutingReasonCode.EXECUTION_ERROR.value


def test_54_failure_preserves_error_code_and_category() -> None:
    err = AgentNodeExecutionError("Node failed", node_name="risk_agent", details={"code": "ERR_01"})
    assert err.classification == ErrorClassification.NON_RETRYABLE
    assert err.error_code == "AGENT_NODE_EXECUTION_ERROR"
    assert err.details["node_name"] == "risk_agent"


def test_55_failure_preserves_node_and_correlation_id() -> None:
    err_state = AgentErrorState(
        error_code="TIMEOUT",
        message="Request timed out",
        node="research_agent",
        correlation_id="corr_999",
        retry_count=2,
    )
    assert err_state.node == "research_agent"
    assert err_state.correlation_id == "corr_999"
    assert err_state.retry_count == 2


def test_56_terminal_failure_routing_to_termination() -> None:
    evaluator = RouteEvaluator()
    decision = evaluator.evaluate({"status": AgentLifecycleStatus.FAILED.value})
    assert decision.next_node == "termination"
    assert decision.termination_flag is True


def test_57_non_retryable_failure_forces_termination() -> None:
    evaluator = RouteEvaluator()
    state: AgentGraphStateDict = {
        "status": AgentLifecycleStatus.FAILED.value,
        "can_retry": False,
        "errors": [{"error": "unrecoverable corruption"}],
    }
    decision = evaluator.evaluate(state)
    assert decision.next_node == "termination"
    assert decision.termination_flag is True


def test_58_failure_does_not_swallow_error() -> None:
    state_dict: AgentGraphStateDict = {
        "errors": [{"msg": "root cause exception", "error_code": "CRITICAL_FAIL"}],
        "status": AgentLifecycleStatus.RUNNING.value,
    }
    res = termination_node(state_dict)
    assert res["status"] == AgentLifecycleStatus.FAILED.value
    # Preserves existing errors
    assert len(res["errors"]) == 1
    assert res["errors"][0]["error_code"] == "CRITICAL_FAIL"


# ==============================================================================
# GROUP 8: TERMINATION LIFECYCLE & STATUSES
# ==============================================================================

def test_59_termination_node_completed_lifecycle() -> None:
    res = termination_node({"status": AgentLifecycleStatus.RUNNING.value})
    assert res["status"] == AgentLifecycleStatus.COMPLETED.value
    assert res["current_stage"] == AgentStage.TERMINATION.value


def test_60_termination_node_failed_lifecycle() -> None:
    res = termination_node({"status": AgentLifecycleStatus.FAILED.value})
    assert res["status"] == AgentLifecycleStatus.FAILED.value


def test_61_termination_node_blocked_lifecycle() -> None:
    res = termination_node({"status": AgentLifecycleStatus.BLOCKED.value})
    assert res["status"] == AgentLifecycleStatus.BLOCKED.value


def test_62_termination_node_no_action_required_lifecycle() -> None:
    res = termination_node({"status": AgentLifecycleStatus.NO_ACTION_REQUIRED.value})
    assert res["status"] == AgentLifecycleStatus.NO_ACTION_REQUIRED.value


def test_63_termination_node_waiting_for_approval_lifecycle() -> None:
    res = termination_node({"requires_human_approval": True, "status": AgentLifecycleStatus.RUNNING.value})
    assert res["status"] == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value


def test_64_termination_node_max_steps_reached_lifecycle() -> None:
    res = termination_node({"status": AgentLifecycleStatus.MAX_STEPS_REACHED.value})
    assert res["status"] == AgentLifecycleStatus.MAX_STEPS_REACHED.value


def test_65_termination_to_end_edge_execution() -> None:
    edge = AgentEdgeContract(
        edge_id="term_to_end",
        from_node="termination",
        to_node="END",
        edge_type=EdgeType.TERMINATION,
        reason_code=RoutingReasonCode.DEFAULT_COMPLETION.value,
        is_terminal=True,
    )
    assert edge.is_terminal is True
    assert edge.to_node == "END"


# ==============================================================================
# GROUP 9: APPROVAL GATE & SIDE-EFFECT BOUNDARY
# ==============================================================================

def test_66_approval_gate_blocks_transition_when_approval_required() -> None:
    evaluator = RouteEvaluator()
    decision = evaluator.evaluate({"requires_human_approval": True, "step_count": 1})
    assert decision.next_node == "termination"
    assert decision.reason_code == RoutingReasonCode.AWAITING_APPROVAL.value
    assert decision.termination_flag is True


def test_67_side_effecting_node_rejected_without_approval_permission(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="action_agent",
        name="Action Agent",
        description="Executes remediation action",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    def dummy_handler(s: AgentGraphStateDict) -> AgentGraphStateDict:
        return s

    wrapper = NodeExecutionWrapper(contract, dummy_handler)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.ACTION.value,
        "requires_human_approval": True,  # Approval still required!
        "side_effect_allowed": False,
    }
    with pytest.raises(AgentApprovalBoundaryViolationError) as exc_info:
        wrapper(state, sample_context)
    assert "requires verified human approval" in str(exc_info.value)


def test_68_side_effecting_node_requires_governance_approval(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="action_agent",
        name="Action Agent",
        description="Executes action",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    def dummy_handler(s: AgentGraphStateDict) -> AgentGraphStateDict:
        return s

    wrapper = NodeExecutionWrapper(contract, dummy_handler)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.ACTION.value,
        "requires_human_approval": False,
        "side_effect_allowed": False,  # Governance flag missing!
    }
    with pytest.raises(AgentApprovalBoundaryViolationError) as exc_info:
        wrapper(state, sample_context)
    assert "side_effect_allowed" in str(exc_info.value)


def test_69_read_only_node_bypasses_approval_requirement(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Read-only research",
        stage=AgentStage.RESEARCH,
        is_side_effecting=False,
    )
    def dummy_handler(s: AgentGraphStateDict) -> AgentGraphStateDict:
        return s

    wrapper = NodeExecutionWrapper(contract, dummy_handler)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.RESEARCH.value,
        "requires_human_approval": False,
    }
    result = wrapper(state, sample_context)
    assert result["run_id"] == "r1"


def test_70_approval_gate_unauthorized_transition_rejected(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="action_agent",
        name="Action Agent",
        description="Executes action",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
        required_permissions=["super_admin_execute"],
    )
    def dummy_handler(s: AgentGraphStateDict) -> AgentGraphStateDict:
        return s

    wrapper = NodeExecutionWrapper(contract, dummy_handler)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.ACTION.value,
        "requires_human_approval": False,
        "side_effect_allowed": True,
    }
    # sample_context has permissions: ["read", "write", "approve", "assess_risk"]
    with pytest.raises(AgentToolAuthorizationError) as exc_info:
        wrapper(state, sample_context)
    assert "missing required permissions" in str(exc_info.value)


def test_71_approval_boundary_node_sets_waiting_for_approval() -> None:
    res = approval_boundary_node({"step_count": 2})
    assert res["status"] == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value
    assert res["requires_human_approval"] is True
    assert res["current_stage"] == AgentStage.APPROVAL.value
    assert res["step_count"] == 3


def test_72_graph_validator_flags_unguarded_side_effecting_node(clean_node_registry: NodeRegistry) -> None:
    action_contract = AgentNodeContract(
        node_id="action_agent",
        name="Action",
        description="Action",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    clean_node_registry.register_node(action_contract, create_safe_placeholder_node(action_contract))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    # Edge enters action_agent directly from initialization without approval gate
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="start_to_init",
        from_node="START",
        to_node="initialization",
        reason_code="START",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="init_to_action",
        from_node="initialization",
        to_node="action_agent",
        edge_type=EdgeType.NORMAL,  # Not APPROVAL_GATE!
        reason_code="EXECUTE",
    ), validate_stages=False)
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="action_to_term",
        from_node="action_agent",
        to_node="termination",
        reason_code="DONE",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="term_to_end",
        from_node="termination",
        to_node="END",
        edge_type=EdgeType.TERMINATION,
        reason_code="END",
        is_terminal=True,
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "must have an incoming edge with APPROVAL_GATE" in str(exc_info.value)


def test_73_side_effecting_node_guarded_by_approval_passes_validation(clean_node_registry: NodeRegistry) -> None:
    action_contract = AgentNodeContract(
        node_id="action_agent",
        name="Action",
        description="Action",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    clean_node_registry.register_node(action_contract, create_safe_placeholder_node(action_contract))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    edge_reg.register_edge(AgentEdgeContract(
        edge_id="start_to_init",
        from_node="START",
        to_node="initialization",
        reason_code="START",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="init_to_approval",
        from_node="initialization",
        to_node="approval_boundary",
        edge_type=EdgeType.APPROVAL_GATE,
        reason_code="APPROVAL_GATE",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="approval_to_action",
        from_node="approval_boundary",
        to_node="action_agent",
        edge_type=EdgeType.NORMAL,
        reason_code="APPROVED",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="action_to_term",
        from_node="action_agent",
        to_node="termination",
        reason_code="DONE",
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="term_to_end",
        from_node="termination",
        to_node="END",
        edge_type=EdgeType.TERMINATION,
        reason_code="END",
        is_terminal=True,
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    validator.validate()  # Passes because approval_boundary is in AgentStage.APPROVAL


# ==============================================================================
# GROUP 10: SECURITY, TENANT ISOLATION & AUTHORIZATION
# ==============================================================================

def test_74_node_execution_wrapper_tenant_mismatch_fails_closed(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: s)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": "DIFFERENT_ORG_999",  # Mismatch!
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        wrapper(state, sample_context)
    assert "Tenant mismatch" in str(exc_info.value)


def test_75_node_execution_wrapper_foreign_evidence_reference_fails(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: s)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.RESEARCH.value,
        "evidence_references": ["foreign_tenant_ref:::evidence_001"],
    }
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        wrapper(state, sample_context)
    assert "foreign tenant" in str(exc_info.value).lower()


def test_76_node_execution_wrapper_foreign_risk_assessment_reference_fails(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="risk_agent",
        name="Risk",
        description="Risk",
        stage=AgentStage.RISK_ASSESSMENT,
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: s)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.RISK_ASSESSMENT.value,
        "risk_assessment": {"organization_id": "foreign_org_111", "assessment_id": "ra_1"},
    }
    with pytest.raises(AgentTenantIsolationError) as exc_info:
        wrapper(state, sample_context)
    assert "foreign tenant" in str(exc_info.value).lower()


def test_77_node_execution_wrapper_caller_missing_required_role_fails(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
        required_roles=["super_admin"],
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: s)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentToolAuthorizationError) as exc_info:
        wrapper(state, sample_context)
    assert "missing required roles" in str(exc_info.value)


def test_78_node_execution_wrapper_caller_missing_required_permission_fails(sample_context: AgentExecutionContext) -> None:
    contract = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
        required_permissions=["execute_kernel_bypass"],
    )
    wrapper = NodeExecutionWrapper(contract, lambda s: s)
    state: AgentGraphStateDict = {
        "run_id": "r1",
        "organization_id": sample_context.organization_id,
        "actor_id": sample_context.actor_id,
        "current_stage": AgentStage.RESEARCH.value,
    }
    with pytest.raises(AgentToolAuthorizationError) as exc_info:
        wrapper(state, sample_context)
    assert "missing required permissions" in str(exc_info.value)


def test_79_role_escalation_attempt_in_state_fails(sample_state: AgentGraphState) -> None:
    # Attempting to mutate identity fields in state update
    with pytest.raises(AgentStateOwnershipViolationError) as exc_info:
        validate_state_update(
            current_state=sample_state,
            update_payload={"actor_id": "attacker_escalated_admin"},
            writer_node_id="research_agent",
            writer_stage=AgentStage.RESEARCH,
        )
    assert "Immutable identity field" in str(exc_info.value)


def test_80_credential_in_state_update_fails_validation(sample_state: AgentGraphState) -> None:
    with pytest.raises(AgentValidationError) as exc_info:
        validate_state_update(
            current_state=sample_state,
            update_payload={"findings": [{"text": "secret_key = bearer sk-secret1234567890"}]},
            writer_node_id="research_agent",
            writer_stage=AgentStage.RESEARCH,
        )
    assert "Prohibited credential or secret key" in str(exc_info.value) or "sensitive" in str(exc_info.value).lower()


def test_81_chain_of_thought_in_state_update_fails_validation(sample_state: AgentGraphState) -> None:
    with pytest.raises(AgentValidationError) as exc_info:
        validate_state_update(
            current_state=sample_state,
            update_payload={"findings": [{"chain_of_thought": "I should first examine the supplier"}]},
            writer_node_id="research_agent",
            writer_stage=AgentStage.RESEARCH,
        )
    assert "chain-of-thought" in str(exc_info.value).lower()


def test_82_state_size_limit_exceeded_fails_validation(sample_state: AgentGraphState) -> None:
    huge_string = "x" * 600_000
    with pytest.raises(AgentStateSizeLimitError) as exc_info:
        validate_state_update(
            current_state=sample_state,
            update_payload={"findings": [{"text": huge_string}]},
            writer_node_id="research_agent",
            writer_stage=AgentStage.RESEARCH,
        )
    assert "State update payload size" in str(exc_info.value)


# ==============================================================================
# GROUP 11: OBSERVABILITY & REDACTION
# ==============================================================================

def test_83_node_execution_wrapper_emits_telemetry(sample_context: AgentExecutionContext) -> None:
    recorded: list[dict] = []
    def intercept_log(item: NodeExecutionTelemetry) -> None:
        recorded.append(item.model_dump())

    orig = AgentObservability.emit_node_telemetry
    AgentObservability.emit_node_telemetry = intercept_log  # type: ignore

    try:
        contract = AgentNodeContract(
            node_id="research_agent",
            name="Research",
            description="Research",
            stage=AgentStage.RESEARCH,
            allowed_outputs=["findings"],
        )
        wrapper = NodeExecutionWrapper(contract, lambda s: {"findings": [{"text": "result"}]})
        state: AgentGraphStateDict = {
            "run_id": "r1",
            "organization_id": sample_context.organization_id,
            "actor_id": sample_context.actor_id,
            "request_id": sample_context.request_id,
            "correlation_id": sample_context.correlation_id,
            "trace_id": sample_context.trace_id,
            "current_stage": AgentStage.RESEARCH.value,
        }
        wrapper(state, sample_context)

        assert len(recorded) == 1
        assert recorded[0]["node_name"] == "research_agent"
        assert recorded[0]["status"] == "SUCCESS"
        assert recorded[0]["duration_ms"] >= 0.0
    finally:
        AgentObservability.emit_node_telemetry = orig


def test_84_telemetry_captures_correlation_and_trace_ids(sample_context: AgentExecutionContext) -> None:
    item = NodeExecutionTelemetry(
        run_id="r1",
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        node_name="research_agent",
        duration_ms=12.5,
        status="SUCCESS",
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
    )
    dump = item.model_dump()
    assert dump["correlation_id"] == "corr_test_001"
    assert dump["trace_id"] == "trace_test_002"


def test_85_telemetry_captures_duration_and_step_count(sample_context: AgentExecutionContext) -> None:
    item = NodeExecutionTelemetry(
        run_id="r1",
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        node_name="research_agent",
        duration_ms=45.2,
        status="SUCCESS",
        step_count=3,
    )
    assert item.duration_ms == 45.2
    assert item.step_count == 3


def test_86_telemetry_captures_error_code_on_failure(sample_context: AgentExecutionContext) -> None:
    item = NodeExecutionTelemetry(
        run_id="r1",
        organization_id=sample_context.organization_id,
        actor_id=sample_context.actor_id,
        request_id=sample_context.request_id,
        correlation_id=sample_context.correlation_id,
        trace_id=sample_context.trace_id,
        node_name="research_agent",
        duration_ms=5.0,
        status="FAILED",
        error_code="TIMEOUT_ERROR",
    )
    assert item.status == "FAILED"
    assert item.error_code == "TIMEOUT_ERROR"


def test_87_observability_redacts_sensitive_tokens() -> None:
    from app.agents.security import sanitize_sensitive_data
    text = "User token is Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret"
    sanitized = sanitize_sensitive_data(text)
    assert "Bearer" not in sanitized
    assert "[REDACTED_BEARER_TOKEN]" in sanitized


def test_88_observability_excludes_chain_of_thought() -> None:
    from app.agents.security import screen_untrusted_input
    payload = {"chain_of_thought": "hidden reasoning step"}
    with pytest.raises(AgentValidationError) as exc_info:
        screen_untrusted_input(payload)
    assert "chain-of-thought" in str(exc_info.value).lower()


# ==============================================================================
# GROUP 12: GRAPH VALIDATION SUITE
# ==============================================================================

def test_89_graph_validator_valid_pipeline_passes(clean_node_registry: NodeRegistry) -> None:
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e1", from_node="START", to_node="initialization", reason_code="START"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e2", from_node="initialization", to_node="termination", reason_code="DONE"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e3", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    validator.validate()  # Passes cleanly


def test_90_graph_validator_unregistered_edge_endpoint_fails(clean_node_registry: NodeRegistry) -> None:
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)
    # Register an edge with non-existent destination
    edge = AgentEdgeContract(
        edge_id="e_broken",
        from_node="initialization",
        to_node="unregistered_ghost",
        reason_code="R1",
    )
    edge_reg.register_edge(edge, validate_endpoints=False)

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "unregistered destination node" in str(exc_info.value)


def test_91_graph_validator_unreachable_node_from_start_fails(clean_node_registry: NodeRegistry) -> None:
    orphan = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
    )
    clean_node_registry.register_node(orphan, create_safe_placeholder_node(orphan))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    # Edge from START to initialization, and termination to END, but research_agent is unlinked
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e1", from_node="START", to_node="initialization", reason_code="START"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e2", from_node="initialization", to_node="termination", reason_code="DONE"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e3", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "Unreachable node" in str(exc_info.value)
    assert "research_agent" in str(exc_info.value)


def test_92_graph_validator_missing_path_to_end_fails(clean_node_registry: NodeRegistry) -> None:
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)
    # Missing termination -> END edge
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e1", from_node="START", to_node="initialization", reason_code="START"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e2", from_node="initialization", to_node="termination", reason_code="DONE"
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "No terminal path exists" in str(exc_info.value)


def test_93_graph_validator_illegal_stage_transition_fails(clean_node_registry: NodeRegistry) -> None:
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)
    # termination (TERMINATION stage) -> initialization (INITIALIZATION stage)
    edge = AgentEdgeContract(
        edge_id="e_illegal_stage",
        from_node="termination",
        to_node="initialization",
        reason_code="LOOP",
    )
    edge_reg.register_edge(edge, validate_stages=False)
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e_term_end", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "Illegal stage transition" in str(exc_info.value)


def test_94_graph_validator_unguarded_side_effect_fails(clean_node_registry: NodeRegistry) -> None:
    action = AgentNodeContract(
        node_id="action_agent",
        name="Action",
        description="Action",
        stage=AgentStage.ACTION,
        is_side_effecting=True,
    )
    clean_node_registry.register_node(action, create_safe_placeholder_node(action))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e1", from_node="START", to_node="action_agent", reason_code="START"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e2", from_node="action_agent", to_node="termination", reason_code="DONE"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e3", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "must have an incoming edge with APPROVAL_GATE" in str(exc_info.value)


def test_95_graph_validator_unbounded_cycle_fails(clean_node_registry: NodeRegistry) -> None:
    r_node = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
        retryable=False,  # Unbounded!
    )
    clean_node_registry.register_node(r_node, create_safe_placeholder_node(r_node))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e1", from_node="START", to_node="research_agent", reason_code="START"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e2", from_node="research_agent", to_node="research_agent", edge_type=EdgeType.NORMAL, reason_code="CYCLE"
    ), validate_stages=False)
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e3", from_node="research_agent", to_node="termination", reason_code="DONE"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e4", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    with pytest.raises(AgentGraphValidationError) as exc_info:
        validator.validate()
    assert "Unbounded self-loop" in str(exc_info.value)


def test_96_graph_validator_bounded_retry_cycle_passes(clean_node_registry: NodeRegistry) -> None:
    r_node = AgentNodeContract(
        node_id="research_agent",
        name="Research",
        description="Research",
        stage=AgentStage.RESEARCH,
        retryable=True,
        max_retries=2,
    )
    clean_node_registry.register_node(r_node, create_safe_placeholder_node(r_node))
    edge_reg = EdgeRegistry(node_registry=clean_node_registry)

    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e1", from_node="START", to_node="research_agent", reason_code="START"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e2", from_node="research_agent", to_node="research_agent", edge_type=EdgeType.RETRY, reason_code="RETRY"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e3", from_node="research_agent", to_node="termination", reason_code="DONE"
    ))
    edge_reg.register_edge(AgentEdgeContract(
        edge_id="e4", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True
    ))

    validator = GraphValidator(registry=clean_node_registry, edge_registry=edge_reg)
    validator.validate()  # Passes because max_retries <= 10


# ==============================================================================
# GROUP 13: REAL LANGGRAPH EXECUTION
# ==============================================================================

def test_97_real_langgraph_start_to_init_to_termination_end(
    sample_context: AgentExecutionContext,
    sample_state: AgentGraphState,
) -> None:
    builder = AgentGraphBuilder()
    compiled = builder.build(checkpointer=MemorySaver(), validate_graph=True)

    initial_payload = sample_state.model_dump(mode="json")
    result = compiled.invoke(initial_payload, config={"configurable": {"thread_id": "t1"}})

    assert result["status"] == AgentLifecycleStatus.COMPLETED.value
    assert result["current_stage"] == AgentStage.TERMINATION.value
    assert result["step_count"] >= 2


def test_98_real_langgraph_with_custom_typed_node(
    sample_context: AgentExecutionContext,
    sample_state: AgentGraphState,
) -> None:
    registry = NodeRegistry()
    registry.register_node(INITIALIZATION_NODE_CONTRACT, initialization_node)
    registry.register_node(TERMINATION_NODE_CONTRACT, termination_node)
    registry.register_node(APPROVAL_BOUNDARY_NODE_CONTRACT, approval_boundary_node)

    research_contract = AgentNodeContract(
        node_id="research_agent",
        name="Research Agent",
        description="Deterministic mock research",
        stage=AgentStage.RESEARCH,
        allowed_outputs=["findings"],
    )
    def mock_research(state: AgentGraphStateDict) -> AgentGraphStateDict:
        state["findings"] = [{"finding_id": "f1", "title": "Verified Finding"}]
        state["selected_route"] = "termination"
        state["step_count"] = state.get("step_count", 0) + 1
        return state

    registry.register_node(research_contract, mock_research)

    edge_reg = EdgeRegistry(node_registry=registry)
    edge_reg.register_edge(AgentEdgeContract(edge_id="e1", from_node="START", to_node="initialization", reason_code="START"))
    edge_reg.register_edge(AgentEdgeContract(edge_id="e2", from_node="initialization", to_node="research_agent", reason_code="ROUTE"))
    edge_reg.register_edge(AgentEdgeContract(edge_id="e3", from_node="research_agent", to_node="termination", reason_code="DONE"))
    edge_reg.register_edge(AgentEdgeContract(edge_id="e4", from_node="termination", to_node="END", edge_type=EdgeType.TERMINATION, reason_code="END", is_terminal=True))

    builder = AgentGraphBuilder(registry=registry, edge_registry=edge_reg, auto_register_foundational_edges=False)
    compiled = builder.build(checkpointer=MemorySaver(), validate_graph=True)

    initial_payload = sample_state.model_dump(mode="json")
    initial_payload["selected_route"] = "research_agent"

    result = compiled.invoke(initial_payload, config={"configurable": {"thread_id": "t2"}})
    assert result["status"] == AgentLifecycleStatus.COMPLETED.value
    assert len(result["findings"]) == 1
    assert result["findings"][0]["title"] == "Verified Finding"


def test_99_real_langgraph_conditional_routing_branch(sample_state: AgentGraphState) -> None:
    builder = AgentGraphBuilder()
    compiled = builder.build(checkpointer=MemorySaver())

    # Branch 1: Normal flow -> termination
    p1 = sample_state.model_dump(mode="json")
    r1 = compiled.invoke(p1, config={"configurable": {"thread_id": "tb1"}})
    assert r1["status"] == AgentLifecycleStatus.COMPLETED.value

    # Branch 2: Requires approval -> termination (halts with WAITING_FOR_APPROVAL)
    p2 = sample_state.model_dump(mode="json")
    p2["requires_human_approval"] = True
    r2 = compiled.invoke(p2, config={"configurable": {"thread_id": "tb2"}})
    assert r2["status"] == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value


def test_100_real_langgraph_error_to_termination(sample_state: AgentGraphState) -> None:
    builder = AgentGraphBuilder()
    compiled = builder.build(checkpointer=MemorySaver())

    payload = sample_state.model_dump(mode="json")
    payload["errors"] = [{"msg": "Fatal error"}]

    res = compiled.invoke(payload, config={"configurable": {"thread_id": "terr"}})
    assert res["status"] == AgentLifecycleStatus.FAILED.value


def test_101_real_langgraph_approval_halt_at_boundary(sample_state: AgentGraphState) -> None:
    builder = AgentGraphBuilder()
    compiled = builder.build(checkpointer=MemorySaver())

    payload = sample_state.model_dump(mode="json")
    payload["selected_route"] = "approval_boundary"

    res = compiled.invoke(payload, config={"configurable": {"thread_id": "tappr"}})
    assert res["status"] == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value
    assert res["requires_human_approval"] is True


def test_102_real_langgraph_in_memory_checkpointer_persistence(sample_state: AgentGraphState) -> None:
    saver = MemorySaver()
    builder = AgentGraphBuilder()
    compiled = builder.build(checkpointer=saver)

    thread_id = "t_persist_01"
    config = {"configurable": {"thread_id": thread_id}}

    payload = sample_state.model_dump(mode="json")
    res = compiled.invoke(payload, config=config)

    # Verify checkpointer stored the state
    checkpoint = saver.get(config)
    assert checkpoint is not None
    assert checkpoint["channel_values"]["status"] == AgentLifecycleStatus.COMPLETED.value


def test_103_real_langgraph_multistep_state_preservation(
    sample_context: AgentExecutionContext,
    sample_state: AgentGraphState,
) -> None:
    result = execute_agent_graph(
        state=sample_state,
        context=sample_context,
        checkpointer=MemorySaver(),
    )
    assert result.run_id == sample_state.run_id
    assert result.organization_id == sample_context.organization_id
    assert result.status == AgentLifecycleStatus.COMPLETED


def test_104_real_langgraph_thread_isolation(sample_state: AgentGraphState) -> None:
    saver = MemorySaver()
    builder = AgentGraphBuilder()
    compiled = builder.build(checkpointer=saver)

    p1 = sample_state.model_dump(mode="json")
    p1["run_id"] = "run_thread_1"
    p2 = sample_state.model_dump(mode="json")
    p2["run_id"] = "run_thread_2"
    p2["requires_human_approval"] = True

    r1 = compiled.invoke(p1, config={"configurable": {"thread_id": "t_iso_1"}})
    r2 = compiled.invoke(p2, config={"configurable": {"thread_id": "t_iso_2"}})

    assert r1["status"] == AgentLifecycleStatus.COMPLETED.value
    assert r2["status"] == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value
