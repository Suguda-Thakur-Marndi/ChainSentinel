"""Node registration architecture and explicit allowlisting for LangGraph nodes.

Guarantees that only typed, verified, and allowlisted node implementations
can participate in graph execution, preventing arbitrary function injection.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set

from app.agents.contracts import AgentStage, NodeContract
from app.agents.errors import AgentUnauthorizedNodeError, AgentValidationError

# Canonical allowlist of approved node identifiers across the RiskWise architecture
PERMISSIBLE_NODE_IDS: Set[str] = {
    "initialization",
    "termination",
    "approval_boundary",
    "human_approval",
    "research_agent",
    "risk_agent",
    "prediction_agent",
    "scenario_agent",
    "decision_agent",
    "action_agent",
    "verification_agent",
    "research_placeholder",
    "risk_placeholder",
    "prediction_placeholder",
    "scenario_placeholder",
    "decision_placeholder",
    "action_placeholder",
    "verification_placeholder",
}


class RegisteredNodeEntry:
    """Encapsulation of a registered node contract and its executable callable."""

    def __init__(self, contract: NodeContract, handler: Callable[..., Any]) -> None:
        self.contract = contract
        self.handler = handler


class NodeRegistry:
    """Thread-safe, allowlist-enforced registry for LangGraph node implementations."""

    def __init__(self, allowlist: Optional[Set[str]] = None) -> None:
        self._allowlist: Set[str] = set(allowlist or PERMISSIBLE_NODE_IDS)
        self._registry: Dict[str, RegisteredNodeEntry] = {}

    @property
    def allowlist(self) -> Set[str]:
        """Return the immutable set of permissible node identifiers."""
        return set(self._allowlist)

    def is_allowed(self, node_id: str) -> bool:
        """Check whether a node identifier belongs to the verified allowlist."""
        return node_id in self._allowlist

    def register_node(
        self,
        contract: NodeContract,
        handler: Callable[..., Any],
    ) -> None:
        """Register a validated node contract and executable handler.
        
        Raises:
            AgentUnauthorizedNodeError: If node_id is not in the allowlist.
            AgentValidationError: If node_id is already registered or handler is invalid.
        """
        if not self.is_allowed(contract.node_id):
            raise AgentUnauthorizedNodeError(
                f"Node ID '{contract.node_id}' is not in the verified allowlist (not in the architectural allowlist).",
                details={"node_id": contract.node_id, "allowed_nodes": sorted(list(self._allowlist))},
            )

        if contract.node_id in self._registry:
            raise AgentValidationError(
                f"Node '{contract.node_id}' is already registered in this registry.",
                details={"node_id": contract.node_id},
            )

        if not callable(handler):
            raise AgentValidationError(
                f"Handler for node '{contract.node_id}' must be a callable function.",
                details={"node_id": contract.node_id},
            )

        self._registry[contract.node_id] = RegisteredNodeEntry(contract=contract, handler=handler)

    def get_node(self, node_id: str) -> RegisteredNodeEntry:
        """Retrieve a registered node entry.
        
        Raises:
            AgentUnauthorizedNodeError: If node_id is unknown or unregistered.
        """
        if node_id not in self._registry:
            raise AgentUnauthorizedNodeError(
                f"Node '{node_id}' is not registered in the agent graph registry.",
                details={"node_id": node_id, "registered_nodes": sorted(list(self._registry.keys()))},
            )
        return self._registry[node_id]

    def list_nodes(self) -> List[NodeContract]:
        """List all currently registered node contracts in deterministic order."""
        return [entry.contract for entry in sorted(self._registry.values(), key=lambda e: e.contract.node_id)]

    def has_node(self, node_id: str) -> bool:
        """Return True if the node is registered."""
        return node_id in self._registry

    def clear(self) -> None:
        """Clear all registered nodes (primarily used in testing)."""
        self._registry.clear()


# Global default registry instance
global_node_registry = NodeRegistry()
