"""Graph structural integrity, reachability, cycle bounding, and governance validation.

Validates that a LangGraph multi-agent orchestration graph satisfies all safety invariants:
no dangling edges, no unbounded cycles, valid terminal paths, and strict approval gating
preceding any side-effecting nodes.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from app.agents.contracts import AgentStage, EdgeType, ToolSideEffectType
from app.agents.edges import EdgeRegistry, StageTransitionValidator, global_edge_registry
from app.agents.errors import AgentGraphValidationError
from app.agents.registry import NodeRegistry, global_node_registry


class GraphValidator:
    """Validates global structural and governance invariants of an agent graph."""

    def __init__(
        self,
        node_registry: Optional[NodeRegistry] = None,
        edge_registry: Optional[EdgeRegistry] = None,
        registry: Optional[NodeRegistry] = None,
    ) -> None:
        self.node_registry = node_registry or registry or global_node_registry
        self.edge_registry = edge_registry or global_edge_registry

    def validate(self, start_node: Optional[str] = None) -> None:
        """Run all structural, topological, and governance validations.

        Raises:
            AgentGraphValidationError: If any graph invariant fails.
        """
        actual_start = start_node
        if actual_start is None:
            start_edges = [e for e in self.edge_registry.list_edges() if e.from_node == "START"]
            if start_edges:
                actual_start = start_edges[0].to_node
            elif self.node_registry.has_node("initialization"):
                actual_start = "initialization"
            else:
                actual_start = "START"

        self._validate_node_endpoints()
        self._validate_approval_gates_and_side_effects()
        self._validate_cycles_are_bounded()
        self._validate_stage_transitions()
        self._validate_terminal_reachability(start_node=actual_start)

    def _validate_node_endpoints(self) -> None:
        """Ensure all edge endpoints correspond to registered nodes."""
        special_nodes = {"START", "END"}
        for edge in self.edge_registry.list_edges():
            if edge.from_node not in special_nodes and not self.node_registry.has_node(edge.from_node):
                raise AgentGraphValidationError(
                    f"Edge '{edge.edge_id}' has unregistered source node '{edge.from_node}'.",
                    details={"edge_id": edge.edge_id, "from_node": edge.from_node},
                )
            if edge.to_node not in special_nodes and not self.node_registry.has_node(edge.to_node):
                raise AgentGraphValidationError(
                    f"Edge '{edge.edge_id}' has unregistered destination node '{edge.to_node}'.",
                    details={"edge_id": edge.edge_id, "to_node": edge.to_node},
                )

    def _validate_stage_transitions(self) -> None:
        """Ensure all registered edges conform to the allowable stage topology."""
        special_nodes = {"START", "END"}
        for edge in self.edge_registry.list_edges():
            if edge.from_node not in special_nodes and edge.to_node not in special_nodes:
                src_contract = self.node_registry.get_node(edge.from_node).contract
                dst_contract = self.node_registry.get_node(edge.to_node).contract
                is_retry = edge.edge_type == EdgeType.RETRY
                try:
                    StageTransitionValidator.validate_transition(
                        current_stage=src_contract.stage,
                        destination_stage=dst_contract.stage,
                        is_retry=is_retry,
                    )
                except Exception as exc:
                    raise AgentGraphValidationError(
                        f"Edge '{edge.edge_id}' violates stage topology: {str(exc)}",
                        details={"edge_id": edge.edge_id, "from_node": edge.from_node, "to_node": edge.to_node},
                    ) from exc

    def _validate_terminal_reachability(self, start_node: str = "initialization") -> None:
        """Ensure a terminal node or END is reachable from every node reachable from start."""
        has_terminal_edge = any(e.to_node == "END" for e in self.edge_registry.list_edges())
        if not has_terminal_edge:
            raise AgentGraphValidationError(
                "No terminal path exists in graph. The graph must contain at least one transition to 'END'.",
                details={"registered_edges": len(self.edge_registry.list_edges())},
            )

        if not self.node_registry.has_node(start_node) and start_node != "START":
            raise AgentGraphValidationError(f"Start node '{start_node}' is not registered.")

        # Build adjacency graph
        adj: Dict[str, List[str]] = {}
        for edge in self.edge_registry.list_edges():
            if edge.from_node not in adj:
                adj[edge.from_node] = []
            adj[edge.from_node].append(edge.to_node)

        # Find all reachable nodes from start
        reachable: Set[str] = set()
        queue = [start_node]
        while queue:
            curr = queue.pop(0)
            if curr not in reachable:
                reachable.add(curr)
                for neighbor in adj.get(curr, []):
                    if neighbor not in reachable:
                        queue.append(neighbor)

        # Check for unreached registered operational nodes
        for contract in self.node_registry.list_nodes():
            if contract.node_id not in ("initialization", "termination", "approval_boundary", "START", "END"):
                if contract.node_id not in reachable:
                    raise AgentGraphValidationError(
                        f"Unreachable node '{contract.node_id}' detected from start node '{start_node}'.",
                        details={"node_id": contract.node_id, "start_node": start_node},
                    )

        # Identify terminal destinations
        terminal_nodes: Set[str] = {"END"}
        for contract in self.node_registry.list_nodes():
            if contract.is_terminal:
                terminal_nodes.add(contract.node_id)

        # Check if terminal path exists from all reachable nodes
        for node in reachable:
            if node in terminal_nodes or node == "END":
                continue
            visited: Set[str] = set()
            can_terminate = False
            sub_queue = [node]
            while sub_queue:
                sub_curr = sub_queue.pop(0)
                if sub_curr in terminal_nodes:
                    can_terminate = True
                    break
                if sub_curr not in visited:
                    visited.add(sub_curr)
                    for nxt in adj.get(sub_curr, []):
                        if nxt not in visited:
                            sub_queue.append(nxt)

            if not can_terminate:
                raise AgentGraphValidationError(
                    f"Node '{node}' is reachable but has no path to a terminal node or END.",
                    details={"node": node},
                )

    def _validate_approval_gates_and_side_effects(self) -> None:
        """Ensure any side-effecting node is guarded by an approval stage or approval gate edge."""
        for contract in self.node_registry.list_nodes():
            if contract.is_side_effecting or contract.side_effect_type == ToolSideEffectType.SIDE_EFFECTING:
                # Find all incoming edges to this side-effecting node
                incoming = [e for e in self.edge_registry.list_edges() if e.to_node == contract.node_id]
                if not incoming:
                    raise AgentGraphValidationError(
                        f"Side-effecting node '{contract.node_id}' has no incoming edges.",
                        details={"node_id": contract.node_id},
                    )
                for edge in incoming:
                    is_guarded = False
                    if edge.edge_type == EdgeType.APPROVAL_GATE:
                        is_guarded = True
                    elif edge.from_node != "START" and self.node_registry.has_node(edge.from_node):
                        src_contract = self.node_registry.get_node(edge.from_node).contract
                        if src_contract.stage == AgentStage.APPROVAL:
                            is_guarded = True
                    if not is_guarded:
                        raise AgentGraphValidationError(
                            f"Side-effecting node '{contract.node_id}' must have an incoming edge with APPROVAL_GATE or originate from an APPROVAL stage. "
                            f"Edge '{edge.edge_id}' from non-approval source '{edge.from_node}' violates governance.",
                            details={"node_id": contract.node_id, "edge_id": edge.edge_id, "from_node": edge.from_node},
                        )

    def _validate_cycles_are_bounded(self) -> None:
        """Ensure any cycles in the graph are explicitly bounded retry loops."""
        # 1. Check direct self-loops
        for edge in self.edge_registry.list_edges():
            if edge.from_node == edge.to_node and edge.from_node not in ("START", "END"):
                dest_contract = (
                    self.node_registry.get_node(edge.to_node).contract
                    if self.node_registry.has_node(edge.to_node)
                    else None
                )
                if edge.edge_type != EdgeType.RETRY:
                    raise AgentGraphValidationError(
                        f"Unbounded self-loop detected on node '{edge.to_node}'. Self-loops must be explicit RETRY transitions.",
                        details={"node_id": edge.to_node, "edge_id": edge.edge_id},
                    )
                if not (dest_contract and dest_contract.retryable and dest_contract.max_retries > 0):
                    raise AgentGraphValidationError(
                        f"Node '{edge.to_node}' has a RETRY edge but is not marked as retryable in its contract.",
                        details={"node_id": edge.to_node, "edge_id": edge.edge_id},
                    )

        # 2. Check multi-node cycles via DFS
        adj: Dict[str, List[AgentEdgeContract]] = {}
        for edge in self.edge_registry.list_edges():
            if edge.from_node not in adj:
                adj[edge.from_node] = []
            adj[edge.from_node].append(edge)

        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def dfs(node: str, path: List[str], edge_path: List[AgentEdgeContract]) -> None:
            visited.add(node)
            rec_stack.add(node)

            for edge in adj.get(node, []):
                neighbor = edge.to_node
                if neighbor not in visited:
                    dfs(neighbor, path + [neighbor], edge_path + [edge])
                elif neighbor in rec_stack:
                    # Cycle detected: from neighbor to neighbor
                    cycle_edges = edge_path[path.index(neighbor):] if neighbor in path else [edge]
                    has_retry_edge = any(e.edge_type == EdgeType.RETRY for e in cycle_edges)
                    dest_contract = (
                        self.node_registry.get_node(neighbor).contract
                        if self.node_registry.has_node(neighbor)
                        else None
                    )
                    if not has_retry_edge:
                        if not (dest_contract and dest_contract.retryable and dest_contract.max_retries > 0):
                            raise AgentGraphValidationError(
                                f"Unbounded cycle detected involving node '{neighbor}'. "
                                "Cycles must be explicitly designated as bounded RETRY transitions.",
                                details={"node": neighbor, "cycle_path": path + [neighbor]},
                            )
                    else:
                        if not (dest_contract and dest_contract.retryable and dest_contract.max_retries > 0):
                            raise AgentGraphValidationError(
                                f"Node '{neighbor}' has a RETRY edge but is not marked as retryable in its contract.",
                                details={"node": neighbor},
                            )

            rec_stack.remove(node)

        for edge in self.edge_registry.list_edges():
            if edge.from_node not in visited and edge.from_node != "END":
                dfs(edge.from_node, [edge.from_node], [])
