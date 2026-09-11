"""Foundational LangGraph graph builder, execution lifecycle, and checkpointing boundary.

Constructs a verified, allowlist-backed StateGraph with START, initialization,
conditional routing, termination, and END boundaries.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.contracts import (
    AgentEdgeContract,
    AgentExecutionContext,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    EdgeType,
    RoutingReasonCode,
)
from app.agents.edges import EdgeRegistry, global_edge_registry
from app.agents.errors import (
    AgentGraphError,
    AgentTenantIsolationError,
    AgentValidationError,
)
from app.agents.nodes import (
    APPROVAL_BOUNDARY_NODE_CONTRACT,
    HUMAN_APPROVAL_NODE_CONTRACT,
    INITIALIZATION_NODE_CONTRACT,
    TERMINATION_NODE_CONTRACT,
    approval_boundary_node,
    human_approval_node,
    initialization_node,
    termination_node,
)
from app.agents.observability import AgentObservability
from app.agents.registry import NodeRegistry, global_node_registry
from app.agents.routing import RouteEvaluator
from app.agents.security import validate_tenant_isolation
from app.agents.validator import GraphValidator


class AgentGraphBuilder:
    """Constructs, validates, and compiles a LangGraph StateGraph instance."""

    def __init__(
        self,
        registry: Optional[NodeRegistry] = None,
        edge_registry: Optional[EdgeRegistry] = None,
        evaluator: Optional[RouteEvaluator] = None,
        auto_register_foundational_edges: bool = True,
    ) -> None:
        self.registry = registry or global_node_registry
        self.edge_registry = edge_registry or global_edge_registry
        if self.edge_registry.node_registry is None:
            self.edge_registry.node_registry = self.registry
        self.evaluator = evaluator or RouteEvaluator(
            registry=self.registry,
            edge_registry=self.edge_registry,
        )
        self._ensure_foundational_nodes_registered()
        if auto_register_foundational_edges:
            self._ensure_foundational_edges_registered()

    def _ensure_foundational_nodes_registered(self) -> None:
        """Register the foundational infrastructure nodes if not already present."""
        if not self.registry.has_node("initialization"):
            self.registry.register_node(INITIALIZATION_NODE_CONTRACT, initialization_node)
        if not self.registry.has_node("termination"):
            self.registry.register_node(TERMINATION_NODE_CONTRACT, termination_node)
        if not self.registry.has_node("approval_boundary"):
            self.registry.register_node(APPROVAL_BOUNDARY_NODE_CONTRACT, approval_boundary_node)
        if not self.registry.has_node("human_approval"):
            self.registry.register_node(HUMAN_APPROVAL_NODE_CONTRACT, human_approval_node)

    def _ensure_foundational_edges_registered(self) -> None:
        """Register default foundational edges if not already present."""
        foundational_edges = [
            AgentEdgeContract(
                edge_id="start_to_init",
                from_node="START",
                to_node="initialization",
                edge_type=EdgeType.NORMAL,
                reason_code=RoutingReasonCode.GRAPH_START.value,
            ),
            AgentEdgeContract(
                edge_id="init_to_termination",
                from_node="initialization",
                to_node="termination",
                edge_type=EdgeType.NORMAL,
                reason_code=RoutingReasonCode.NO_ACTION_REQUIRED.value,
            ),
            AgentEdgeContract(
                edge_id="init_to_approval",
                from_node="initialization",
                to_node="approval_boundary",
                edge_type=EdgeType.APPROVAL_GATE,
                reason_code=RoutingReasonCode.APPROVAL_REQUIRED.value,
            ),
            AgentEdgeContract(
                edge_id="approval_to_termination",
                from_node="approval_boundary",
                to_node="termination",
                edge_type=EdgeType.NORMAL,
                reason_code=RoutingReasonCode.APPROVAL_GRANTED.value,
            ),
            AgentEdgeContract(
                edge_id="termination_to_end",
                from_node="termination",
                to_node="END",
                edge_type=EdgeType.TERMINATION,
                reason_code=RoutingReasonCode.DEFAULT_COMPLETION.value,
                is_terminal=True,
            ),
        ]
        for edge in foundational_edges:
            if not self.edge_registry.has_edge(edge.edge_id):
                self.edge_registry.register_edge(edge, validate_stages=False)

    def validate(self) -> None:
        """Validate the structural and topological integrity of the graph before compilation."""
        validator = GraphValidator(
            registry=self.registry,
            edge_registry=self.edge_registry,
        )
        validator.validate()

    def build(self, checkpointer: Optional[Any] = None, validate_graph: bool = False) -> Any:
        """Construct and compile the LangGraph StateGraph.
        
        Args:
            checkpointer: Optional persistence checkpointer.
            validate_graph: If True, executes full graph validation before compiling.

        Returns:
            Compiled LangGraph application.
        """
        if validate_graph:
            self.validate()
        # 1. Initialize StateGraph with typed dictionary schema
        builder = StateGraph(state_schema=AgentGraphStateDict)

        # 2. Add all registered nodes from the registry
        for contract in self.registry.list_nodes():
            entry = self.registry.get_node(contract.node_id)
            builder.add_node(contract.node_id, entry.handler)

        # 3. Connect START -> initialization
        builder.add_edge(START, "initialization")

        # 4. Conditional routing helper
        def route_fn(state: AgentGraphStateDict) -> str:
            decision = self.evaluator.evaluate(state)
            return decision.next_node

        # Compute possible routing destinations based on registry
        possible_destinations = {
            c.node_id: c.node_id for c in self.registry.list_nodes()
        }

        # Add conditional routing from initialization
        builder.add_conditional_edges(
            "initialization",
            route_fn,
            possible_destinations,
        )

        # Add routing from all non-termination nodes
        for contract in self.registry.list_nodes():
            if contract.node_id not in ("initialization", "termination"):
                builder.add_conditional_edges(
                    contract.node_id,
                    route_fn,
                    possible_destinations,
                )

        # 5. Connect termination -> END
        builder.add_edge("termination", END)

        # 6. Compile with optional checkpointer (defaults to MemorySaver for pure in-memory execution)
        active_checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        return builder.compile(checkpointer=active_checkpointer)


def execute_agent_graph(
    state: AgentGraphState,
    context: AgentExecutionContext,
    builder: Optional[AgentGraphBuilder] = None,
    checkpointer: Optional[Any] = None,
    checkpoint_manager: Optional[Any] = None,
    uow: Optional[Any] = None,
) -> AgentGraphState:
    """Execute a single end-to-end agent graph run with tenant validation, checkpointing, and telemetry.
    
    Raises:
        AgentTenantIsolationError: On tenant mismatch between context and state.
        AgentGraphError: On internal graph or routing failures.
    """
    start_time = time.perf_counter()
    from app.agents.observability import (
        AgentRunTelemetry,
        global_metrics_collector,
    )
    from app.agents.recovery import (
        RecoveryDecision,
        RecoveryPolicy,
        compute_state_hash,
    )

    input_state_hash = compute_state_hash(state)

    try:
        # 1. Enforce tenant boundary & trace alignment
        if context.organization_id != state.organization_id:
            global_metrics_collector.record_security_failure()
            raise AgentTenantIsolationError(
                f"Tenant mismatch: Context organization '{context.organization_id}' does not match state organization '{state.organization_id}'."
            )

        if context.trace_id != state.trace_id:
            global_metrics_collector.record_security_failure()
            raise AgentTenantIsolationError(
                f"Context trace_id '{context.trace_id}' does not match state trace_id '{state.trace_id}'."
            )

        validate_tenant_isolation(
            context_organization_id=context.organization_id,
            state_organization_id=state.organization_id,
            evidence_bundle_org=state.evidence_bundle.organization_id if state.evidence_bundle else None,
            risk_assessment_org=state.risk_assessment.organization_id if state.risk_assessment else None,
            prediction_org=(
                state.prediction_result.get("organization_id")
                if isinstance(state.prediction_result, dict)
                else None
            ),
            scenario_org=(
                state.scenario_result.get("organization_id")
                if isinstance(state.scenario_result, dict)
                else None
            ),
            decision_org=(
                state.decision_result.get("organization_id")
                if isinstance(state.decision_result, dict)
                else None
            ),
            approval_org=(
                state.approval_result.get("organization_id")
                if isinstance(state.approval_result, dict)
                else None
            ),
            evidence_references=state.evidence_references,
            risk_alert_references=state.risk_alert_references,
            recommendation_references=state.recommendation_references,
            approval_reference=state.approval_reference,
        )

        graph_builder = builder or AgentGraphBuilder()
        compiled_app = graph_builder.build(checkpointer=checkpointer)

        if checkpoint_manager is not None:
            checkpoint_manager.save_checkpoint(state.run_id, state, step=state.step_count)

        # Emit audit log: GRAPH_STARTED
        if uow is not None and hasattr(uow, "audit_logs"):
            try:
                from app.services.audit_service import AuditService
                AuditService.log_event(
                    uow=uow,
                    action="GRAPH_STARTED",
                    resource_type="AGENT_GRAPH",
                    org_id=state.organization_id,
                    actor_id=state.actor_id,
                    resource_id=state.run_id,
                    status="SUCCESS",
                    after_data={"stage": state.current_stage.value, "input_state_hash": input_state_hash},
                    request_id=state.request_id,
                )
            except Exception:
                pass

        # 2. Serialize initial Pydantic state to typed dictionary
        initial_payload = state.model_dump(mode="json")
        thread_config = {"configurable": {"thread_id": state.run_id}}
        # 3. Invoke compiled graph
        result_dict = compiled_app.invoke(initial_payload, config=thread_config)
        duration_ms = (time.perf_counter() - start_time) * 1000

        # 4. Validate and construct resulting AgentGraphState
        final_state = AgentGraphState.model_validate(result_dict)
        output_state_hash = compute_state_hash(final_state)

        if checkpoint_manager is not None:
            checkpoint_manager.save_checkpoint(final_state.run_id, final_state, step=final_state.step_count)

        global_metrics_collector.record_graph_execution(final_state.status.value, duration_ms)

        AgentObservability.record_node_execution(
            run_id=final_state.run_id,
            organization_id=final_state.organization_id,
            actor_id=final_state.actor_id,
            request_id=final_state.request_id,
            correlation_id=final_state.correlation_id,
            trace_id=final_state.trace_id,
            node_name="graph_orchestrator",
            duration_ms=duration_ms,
            status=final_state.status.value,
            step_count=final_state.step_count,
        )

        run_telemetry = AgentRunTelemetry(
            organization_id=final_state.organization_id,
            agent_run_id=final_state.run_id,
            execution_id=final_state.run_id,
            request_id=final_state.request_id,
            correlation_id=final_state.correlation_id,
            trace_id=final_state.trace_id,
            node_id="graph_orchestrator",
            stage=final_state.current_stage.value,
            attempt=1,
            status=final_state.status.value,
            duration_ms=round(duration_ms, 2),
            retry_count=final_state.retry_count,
            selected_route=final_state.selected_route,
            input_state_hash=input_state_hash,
            output_state_hash=output_state_hash,
            metadata={"step_count": final_state.step_count},
        )
        AgentObservability.record_run_telemetry(run_telemetry)

        # Emit audit log: GRAPH_TERMINATED / GRAPH_COMPLETED
        if uow is not None and hasattr(uow, "audit_logs"):
            try:
                from app.services.audit_service import AuditService
                action = "GRAPH_TERMINATED" if final_state.status.value == "TERMINATED" else "GRAPH_SUCCEEDED"
                AuditService.log_event(
                    uow=uow,
                    action=action,
                    resource_type="AGENT_GRAPH",
                    org_id=final_state.organization_id,
                    actor_id=final_state.actor_id,
                    resource_id=final_state.run_id,
                    status="SUCCESS",
                    after_data={"stage": final_state.current_stage.value, "output_state_hash": output_state_hash},
                    request_id=final_state.request_id,
                )
            except Exception:
                pass

        return final_state

    except AgentGraphError as age:
        duration_ms = (time.perf_counter() - start_time) * 1000
        global_metrics_collector.record_graph_execution("FAILED", duration_ms)

        AgentObservability.record_node_execution(
            run_id=state.run_id,
            organization_id=state.organization_id,
            actor_id=state.actor_id,
            request_id=state.request_id,
            correlation_id=state.correlation_id,
            trace_id=state.trace_id,
            node_name="graph_orchestrator",
            duration_ms=duration_ms,
            status="FAILED",
            error_code=age.error_code,
        )

        run_telemetry = AgentRunTelemetry(
            organization_id=state.organization_id,
            agent_run_id=state.run_id,
            execution_id=state.run_id,
            request_id=state.request_id,
            correlation_id=state.correlation_id,
            trace_id=state.trace_id,
            node_id="graph_orchestrator",
            stage=state.current_stage.value,
            attempt=1,
            status="FAILED",
            duration_ms=round(duration_ms, 2),
            error_code=age.error_code,
            error_category=age.category.value,
            input_state_hash=input_state_hash,
            metadata={"error_message": age.message},
        )
        AgentObservability.record_run_telemetry(run_telemetry)

        if uow is not None and hasattr(uow, "audit_logs"):
            try:
                from app.services.audit_service import AuditService
                AuditService.log_event(
                    uow=uow,
                    action="GRAPH_FAILED",
                    resource_type="AGENT_GRAPH",
                    org_id=state.organization_id,
                    actor_id=state.actor_id,
                    resource_id=state.run_id,
                    status="FAILURE",
                    after_data={"error_code": age.error_code, "category": age.category.value},
                    request_id=state.request_id,
                )
            except Exception:
                pass

        raise

    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000
        global_metrics_collector.record_graph_execution("FAILED", duration_ms)

        AgentObservability.record_node_execution(
            run_id=state.run_id,
            organization_id=state.organization_id,
            actor_id=state.actor_id,
            request_id=state.request_id,
            correlation_id=state.correlation_id,
            trace_id=state.trace_id,
            node_name="graph_orchestrator",
            duration_ms=duration_ms,
            status="FAILED",
            error_code="UNEXPECTED_GRAPH_ERROR",
        )
        raise AgentGraphError(
            f"Unexpected error during agent graph execution: {str(exc)}",
            details={"raw_error": str(exc)},
        ) from exc

