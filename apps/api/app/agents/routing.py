"""Deterministic routing contracts and fail-closed route evaluation for LangGraph.

Ensures that dynamic or deterministic routing choices only target registered, allowlisted
nodes. If an invalid or unpermitted route is selected, the router fails closed immediately.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentLifecycleStatus,
    ConditionCode,
    EdgeType,
    RouteDecision,
    RoutingReasonCode,
)
from app.agents.edges import ConditionEvaluator, EdgeRegistry, global_edge_registry
from app.agents.errors import AgentInvalidRouteError
from app.agents.registry import NodeRegistry, global_node_registry


class RouteEvaluator:
    """Evaluates graph state to make deterministic routing decisions."""

    def __init__(
        self,
        registry: Optional[NodeRegistry] = None,
        edge_registry: Optional[EdgeRegistry] = None,
        max_steps: int = 25,
    ) -> None:
        self.registry = registry or global_node_registry
        self.edge_registry = edge_registry or global_edge_registry
        self.max_steps = max_steps

    def evaluate(self, state: AgentGraphStateDict) -> RouteDecision:
        """Evaluate state and return a strongly typed RouteDecision.
        
        Raises:
            AgentInvalidRouteError: If an unauthorized or unregistered route is selected.
        """
        step_count = state.get("step_count", 0)
        errors = state.get("errors", [])
        requires_approval = state.get("requires_human_approval", False)
        status = state.get("status")

        # 1. Check max steps limit to prevent infinite loops
        if step_count >= self.max_steps:
            return RouteDecision(
                next_node="termination",
                reason_code=RoutingReasonCode.MAX_STEPS_EXCEEDED.value,
                condition_code=ConditionCode.MAX_STEPS_REACHED.value,
                termination_flag=True,
            )

        # 2. Check errors
        if errors or status == AgentLifecycleStatus.FAILED.value:
            return RouteDecision(
                next_node="termination",
                reason_code=RoutingReasonCode.EXECUTION_ERROR.value,
                condition_code=ConditionCode.HAS_ERRORS.value,
                termination_flag=True,
            )

        # 3. Check human approval boundary
        if requires_approval or status == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value:
            return RouteDecision(
                next_node="termination",
                reason_code=RoutingReasonCode.AWAITING_APPROVAL.value,
                condition_code=ConditionCode.NEEDS_APPROVAL.value,
                termination_flag=True,
            )

        # 4. Check explicit selected_route or next_node
        selected_route = state.get("selected_route") or state.get("next_node")
        if selected_route:
            # Enforce repeated-node loop protection
            route_history = state.get("route_history", [])
            if len(route_history) >= 3:
                recent_targets = []
                for ev in route_history[-3:]:
                    if isinstance(ev, dict):
                        recent_targets.append(ev.get("to_node"))
                    elif hasattr(ev, "to_node"):
                        recent_targets.append(ev.to_node)
                if len(recent_targets) == 3 and all(t == selected_route for t in recent_targets) and selected_route != "termination":
                    return RouteDecision(
                        next_node="termination",
                        reason_code=RoutingReasonCode.REPEATED_NODE_LOOP_DETECTED.value,
                        termination_flag=True,
                    )

            # Enforce allowlist check (fail-closed)
            if not self.registry.is_allowed(selected_route):
                raise AgentInvalidRouteError(
                    f"Selected route '{selected_route}' is not in the allowlist of permissible nodes.",
                    details={
                        "selected_route": selected_route,
                        "allowed_nodes": sorted(list(self.registry.allowlist)),
                    },
                )
            if not self.registry.has_node(selected_route) and selected_route != "termination":
                raise AgentInvalidRouteError(
                    f"Selected route '{selected_route}' is allowlisted but not currently registered in graph.",
                    details={"selected_route": selected_route},
                )

            # Match with registered edge if available
            current_node = state.get("current_node")
            matched_edge_id = None
            if current_node and self.edge_registry:
                for edge in self.edge_registry.get_outgoing_edges(current_node):
                    if edge.to_node == selected_route:
                        matched_edge_id = edge.edge_id
                        break

            return RouteDecision(
                next_node=selected_route,
                reason_code=RoutingReasonCode.EXPLICIT_SELECTION.value,
                selected_edge=matched_edge_id,
                termination_flag=(selected_route == "termination"),
            )

        # 5. Check outgoing edges from current_node if registered
        current_node = state.get("current_node")
        if current_node and self.edge_registry:
            for edge in self.edge_registry.get_outgoing_edges(current_node):
                if edge.condition_code:
                    if ConditionEvaluator.evaluate(edge.condition_code, state):
                        return RouteDecision(
                            next_node=edge.to_node,
                            reason_code=edge.reason_code,
                            selected_edge=edge.edge_id,
                            condition_code=edge.condition_code,
                            termination_flag=(edge.to_node == "termination" or edge.is_terminal),
                        )
                elif edge.edge_type == EdgeType.NORMAL:
                    return RouteDecision(
                        next_node=edge.to_node,
                        reason_code=edge.reason_code,
                        selected_edge=edge.edge_id,
                        condition_code=ConditionCode.ALWAYS.value,
                        termination_flag=(edge.to_node == "termination" or edge.is_terminal),
                    )

        # 6. Default safe transition to termination
        return RouteDecision(
            next_node="termination",
            reason_code=RoutingReasonCode.DEFAULT_COMPLETION.value,
            condition_code=ConditionCode.ALWAYS.value,
            termination_flag=True,
        )



def make_conditional_routing_fn(
    evaluator: Optional[RouteEvaluator] = None,
) -> Any:
    """Create a LangGraph-compatible conditional routing function."""
    ev = evaluator or RouteEvaluator()

    def route_condition(state: AgentGraphStateDict) -> str:
        decision = ev.evaluate(state)
        return decision.next_node

    return route_condition
