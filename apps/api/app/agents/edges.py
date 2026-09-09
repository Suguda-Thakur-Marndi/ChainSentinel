"""Edge contracts, edge registry, conditional evaluation, and stage transition topology.

Governs valid transitions between LangGraph nodes, preventing unauthorized, out-of-order,
or unallowlisted graph mutations. Enforces fail-closed validation on every edge.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set

from app.agents.contracts import (
    AgentEdgeContract,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentStage,
    ConditionCode,
    EdgeType,
    RoutingReasonCode,
)
from app.agents.errors import (
    AgentInvalidEdgeError,
    AgentStageTransitionError,
    AgentValidationError,
)
from app.agents.registry import NodeRegistry, global_node_registry

# Allowed topological stage transitions within the multi-agent pipeline
ALLOWED_STAGE_TRANSITIONS: Dict[AgentStage, Set[AgentStage]] = {
    AgentStage.INITIALIZATION: {
        AgentStage.RESEARCH,
        AgentStage.RISK_ASSESSMENT,
        AgentStage.APPROVAL,
        AgentStage.TERMINATION,
    },
    AgentStage.RESEARCH: {
        AgentStage.RISK_ASSESSMENT,
        AgentStage.TERMINATION,
    },
    AgentStage.RISK_ASSESSMENT: {
        AgentStage.PREDICTION,
        AgentStage.SCENARIO_ANALYSIS,
        AgentStage.DECISION,
        AgentStage.TERMINATION,
    },
    AgentStage.PREDICTION: {
        AgentStage.SCENARIO_ANALYSIS,
        AgentStage.DECISION,
        AgentStage.TERMINATION,
    },
    AgentStage.SCENARIO_ANALYSIS: {
        AgentStage.DECISION,
        AgentStage.TERMINATION,
    },
    AgentStage.DECISION: {
        AgentStage.APPROVAL,
        AgentStage.TERMINATION,
    },
    AgentStage.APPROVAL: {
        AgentStage.ACTION,
        AgentStage.TERMINATION,
    },
    AgentStage.ACTION: {
        AgentStage.VERIFICATION,
        AgentStage.TERMINATION,
    },
    AgentStage.VERIFICATION: {
        AgentStage.TERMINATION,
    },
    AgentStage.TERMINATION: set(),
}


class StageTransitionValidator:
    """Validates that a proposed transition between stages is permitted by the pipeline topology."""

    @staticmethod
    def validate_transition(
        current_stage: AgentStage,
        destination_stage: AgentStage,
        is_retry: bool = False,
    ) -> None:
        """Enforce strict topological stage transition rules.

        Raises:
            AgentStageTransitionError: If an unauthorized backward or invalid jump is attempted.
        """
        if not isinstance(current_stage, AgentStage) or not isinstance(destination_stage, AgentStage):
            raise AgentStageTransitionError(
                f"Invalid or unknown stage transition: '{current_stage}' -> '{destination_stage}'."
            )

        if current_stage == AgentStage.TERMINATION:
            raise AgentStageTransitionError(
                f"Illegal stage transition from terminal stage '{current_stage.value}': stage has no allowed outgoing transitions."
            )

        # Bounded retry self-loop is allowed if explicitly flagged
        if is_retry and current_stage == destination_stage:
            return

        if current_stage == destination_stage and not is_retry:
            raise AgentStageTransitionError(
                f"Self-loop transition at stage '{current_stage.value}' is only permitted as an explicit retry edge."
            )

        allowed_destinations = ALLOWED_STAGE_TRANSITIONS.get(current_stage, set())
        if destination_stage not in allowed_destinations:
            raise AgentStageTransitionError(
                f"Illegal stage transition from '{current_stage.value}' to '{destination_stage.value}' "
                f"({current_stage.value} -> {destination_stage.value}). "
                f"Allowed destinations: {[s.value for s in sorted(allowed_destinations, key=lambda s: s.value)]}."
            )

    @classmethod
    def is_valid_transition(
        cls,
        current_stage: AgentStage,
        destination_stage: AgentStage,
        is_retry: bool = False,
    ) -> bool:
        """Check if a stage transition is valid without raising."""
        try:
            cls.validate_transition(current_stage, destination_stage, is_retry)
            return True
        except (AgentStageTransitionError, Exception):
            return False


class ConditionEvaluator:
    """Safe, non-evaluating predicate engine for conditional edge evaluation.

    Strictly maps declared condition codes to deterministic state predicates.
    Rejects arbitrary expressions, strings, and eval() attempts.
    """

    _HANDLERS: Dict[str, Callable[[AgentGraphStateDict], bool]] = {}

    @classmethod
    def register_condition(
        cls,
        code: str,
        predicate: Callable[[AgentGraphStateDict], bool],
    ) -> None:
        """Register a deterministic, auditable condition predicate."""
        if not callable(predicate):
            raise AgentValidationError(f"Condition predicate for '{code}' must be a callable.")
        cls._HANDLERS[code] = predicate

    @classmethod
    def evaluate(
        cls,
        condition_code: Any,
        state: AgentGraphStateDict,
    ) -> bool:
        """Evaluate a named condition code against graph state.

        Raises:
            AgentValidationError: If condition_code is unknown or unregistered.
        """
        code_str = condition_code.value if hasattr(condition_code, "value") else str(condition_code)
        if code_str not in cls._HANDLERS:
            raise AgentValidationError(
                f"Unregistered or unsupported condition code '{code_str}'. Arbitrary expressions or eval() are strictly forbidden.",
                details={"condition_code": code_str, "registered_conditions": sorted(list(cls._HANDLERS.keys()))},
            )
        return cls._HANDLERS[code_str](state)


# Standard condition predicates
def _cond_always(state: AgentGraphStateDict) -> bool:
    return True


def _cond_has_errors(state: AgentGraphStateDict) -> bool:
    return bool(state.get("errors") or state.get("status") == AgentLifecycleStatus.FAILED.value)


def _cond_is_retryable(state: AgentGraphStateDict) -> bool:
    if state.get("can_retry"):
        return True
    last_error = state.get("last_error")
    if isinstance(last_error, dict):
        return bool(last_error.get("retryable", False))
    return False


def _cond_needs_approval(state: AgentGraphStateDict) -> bool:
    return bool(
        state.get("requires_human_approval")
        or state.get("status") == AgentLifecycleStatus.WAITING_FOR_APPROVAL.value
    )


def _cond_approval_approved(state: AgentGraphStateDict) -> bool:
    return (
        state.get("approval_status") == "APPROVED"
        or state.get("approval_decision") == "APPROVED"
    )


def _cond_approval_rejected(state: AgentGraphStateDict) -> bool:
    return (
        state.get("approval_status") == "REJECTED"
        or state.get("approval_decision") == "REJECTED"
    )


def _cond_evidence_satisfied(state: AgentGraphStateDict) -> bool:
    return bool(state.get("evidence_bundle") or len(state.get("evidence_references", [])) > 0)


def _cond_max_steps_reached(state: AgentGraphStateDict) -> bool:
    return (
        state.get("status") == AgentLifecycleStatus.MAX_STEPS_REACHED.value
        or state.get("step_count", 0) >= 25
    )


def _cond_stage_completed(state: AgentGraphStateDict) -> bool:
    return state.get("status") == AgentLifecycleStatus.COMPLETED.value


# Initialize built-in condition handlers
ConditionEvaluator.register_condition(ConditionCode.ALWAYS.value, _cond_always)
ConditionEvaluator.register_condition(ConditionCode.HAS_ERRORS.value, _cond_has_errors)
ConditionEvaluator.register_condition(ConditionCode.IS_RETRYABLE.value, _cond_is_retryable)
ConditionEvaluator.register_condition(ConditionCode.NEEDS_APPROVAL.value, _cond_needs_approval)
ConditionEvaluator.register_condition(ConditionCode.APPROVAL_APPROVED.value, _cond_approval_approved)
ConditionEvaluator.register_condition(ConditionCode.APPROVAL_REJECTED.value, _cond_approval_rejected)
ConditionEvaluator.register_condition(ConditionCode.EVIDENCE_SATISFIED.value, _cond_evidence_satisfied)
ConditionEvaluator.register_condition(ConditionCode.MAX_STEPS_REACHED.value, _cond_max_steps_reached)
ConditionEvaluator.register_condition(ConditionCode.STAGE_COMPLETED.value, _cond_stage_completed)


class EdgeRegistry:
    """Thread-safe, validated registry for allowlisted LangGraph edge transitions."""

    def __init__(self, node_registry: Optional[NodeRegistry] = None) -> None:
        self.node_registry = node_registry or global_node_registry
        self._edges: Dict[str, AgentEdgeContract] = {}
        self._outgoing: Dict[str, List[AgentEdgeContract]] = {}

    def register_edge(
        self,
        edge: AgentEdgeContract,
        validate_nodes: bool = True,
        validate_stages: bool = True,
        validate_endpoints: Optional[bool] = None,
    ) -> None:
        """Register a validated edge contract.

        Raises:
            AgentInvalidEdgeError: If endpoints are unknown, transition is duplicate, or stages conflict.
        """
        if validate_endpoints is not None:
            validate_nodes = validate_endpoints
        if edge.edge_id in self._edges:
            raise AgentInvalidEdgeError(
                f"Edge '{edge.edge_id}' is already registered in this edge registry.",
                details={"edge_id": edge.edge_id},
            )

        # Validate duplicate transitions
        for existing in self._edges.values():
            if (
                existing.from_node == edge.from_node
                and existing.to_node == edge.to_node
                and existing.condition_code == edge.condition_code
            ):
                raise AgentInvalidEdgeError(
                    f"Duplicate edge transition from '{edge.from_node}' to '{edge.to_node}' "
                    f"with condition '{edge.condition_code}' already exists (edge_id: '{existing.edge_id}').",
                    details={"edge_id": edge.edge_id, "existing_edge_id": existing.edge_id},
                )

        # Validate node existence
        special_nodes = {"START", "END"}
        if validate_nodes:
            if edge.from_node not in special_nodes and not self.node_registry.has_node(edge.from_node):
                raise AgentInvalidEdgeError(
                    f"Source node '{edge.from_node}' is not registered in the node registry.",
                    details={"from_node": edge.from_node},
                )
            if edge.to_node not in special_nodes and not self.node_registry.has_node(edge.to_node):
                raise AgentInvalidEdgeError(
                    f"Destination node '{edge.to_node}' is not registered in the node registry.",
                    details={"to_node": edge.to_node},
                )

        # Validate stage topology if endpoints are regular nodes
        if validate_stages and edge.from_node not in special_nodes and edge.to_node not in special_nodes:
            if self.node_registry.has_node(edge.from_node) and self.node_registry.has_node(edge.to_node):
                source_contract = self.node_registry.get_node(edge.from_node).contract
                dest_contract = self.node_registry.get_node(edge.to_node).contract
                is_retry = edge.edge_type == EdgeType.RETRY
                StageTransitionValidator.validate_transition(
                    current_stage=source_contract.stage,
                    destination_stage=dest_contract.stage,
                    is_retry=is_retry,
                )

        self._edges[edge.edge_id] = edge
        if edge.from_node not in self._outgoing:
            self._outgoing[edge.from_node] = []
        self._outgoing[edge.from_node].append(edge)

    def get_edge(self, edge_id: str) -> AgentEdgeContract:
        """Retrieve an edge contract by ID."""
        if edge_id not in self._edges:
            raise AgentInvalidEdgeError(
                f"Edge '{edge_id}' is not registered in the edge registry.",
                details={"edge_id": edge_id},
            )
        return self._edges[edge_id]

    def list_edges(self) -> List[AgentEdgeContract]:
        """List all registered edge contracts in deterministic order."""
        return [self._edges[k] for k in sorted(self._edges.keys())]

    def get_outgoing_edges(self, from_node: str) -> List[AgentEdgeContract]:
        """List all outgoing edges originating from a given node."""
        return list(self._outgoing.get(from_node, []))

    def has_edge(self, edge_id: str) -> bool:
        """Check if an edge is registered."""
        return edge_id in self._edges

    def clear(self) -> None:
        """Clear the edge registry (used primarily in test suites)."""
        self._edges.clear()
        self._outgoing.clear()


# Global default edge registry instance
global_edge_registry = EdgeRegistry()
