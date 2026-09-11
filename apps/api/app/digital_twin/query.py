"""Deterministic, read-only graph query and bounded traversal service for Digital Twin.

Enforces:
- Strict multi-tenant isolation.
- Completely read-only semantics (no mutation of DB or graph).
- Cycle handling with visited sets to prevent infinite loops (A -> B -> C -> A).
- Enforced hard upper bounds on depth (<=10), nodes (<=500), and edges (<=1000).
- Pure graph traversal reachability without optimization, simulation, or ranking.
"""

from __future__ import annotations

from collections import deque
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
    TwinPathResult,
    TwinQuery,
    TwinSubgraph,
)
from app.digital_twin.errors import (
    TwinQueryError,
    TwinTenantIsolationError,
    TwinTraversalError,
)
from app.digital_twin.observability import TwinObservability
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType

# Hard Security Limits for Graph Traversal
MAX_ALLOWED_DEPTH = 10
MAX_ALLOWED_NODES = 500
MAX_ALLOWED_EDGES = 1000


class DigitalTwinQueryService:
    """Read-only query service operating on an immutable Digital Twin snapshot."""

    def __init__(self, snapshot: DigitalTwinSnapshot):
        if not snapshot:
            raise TwinQueryError("A valid DigitalTwinSnapshot is required to initialize query service")
        self._snapshot = snapshot
        self.organization_id = snapshot.organization_id
        self.twin_id = snapshot.twin_id

        # Index outbound and inbound edges for O(1) adjacency lookup
        self._outbound_edges: Dict[str, List[TwinEdgeContract]] = {}
        self._inbound_edges: Dict[str, List[TwinEdgeContract]] = {}
        for edge in snapshot.edges.values():
            self._outbound_edges.setdefault(edge.from_node_id, []).append(edge)
            self._inbound_edges.setdefault(edge.to_node_id, []).append(edge)

    def get_snapshot(self) -> DigitalTwinSnapshot:
        """Return the underlying immutable Digital Twin snapshot."""
        return self._snapshot

    def get_node(self, node_id: str) -> TwinNodeContract:
        """Fetch a specific node by deterministic ID, enforcing tenant isolation."""
        if not node_id:
            raise TwinQueryError("node_id must be provided")

        node = self._snapshot.nodes.get(node_id)
        if not node:
            raise TwinQueryError(f"Node '{node_id}' not found in Digital Twin '{self.twin_id}'")

        if node.organization_id != self.organization_id:
            raise TwinTenantIsolationError(
                f"Access denied: Node '{node_id}' belongs to a different tenant"
            )

        return node

    def get_outbound_edges(self, node_id: str) -> List[TwinEdgeContract]:
        """Return all edges originating from the specified node."""
        self.get_node(node_id)  # verifies existence and tenant
        return list(self._outbound_edges.get(node_id, []))

    def get_inbound_edges(self, node_id: str) -> List[TwinEdgeContract]:
        """Return all edges directed toward the specified node."""
        self.get_node(node_id)  # verifies existence and tenant
        return list(self._inbound_edges.get(node_id, []))

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        node_type: Optional[TwinNodeType] = None,
        edge_type: Optional[TwinEdgeType] = None,
    ) -> List[TwinNodeContract]:
        """Return distinct adjacent nodes across outbound, inbound, or both edge directions."""
        self.get_node(node_id)
        neighbor_ids: Set[str] = set()

        if direction in ("outbound", "both"):
            for edge in self._outbound_edges.get(node_id, []):
                if edge_type is None or edge.edge_type == edge_type:
                    neighbor_ids.add(edge.to_node_id)

        if direction in ("inbound", "both"):
            for edge in self._inbound_edges.get(node_id, []):
                if edge_type is None or edge.edge_type == edge_type:
                    neighbor_ids.add(edge.from_node_id)

        neighbors: List[TwinNodeContract] = []
        for nid in sorted(neighbor_ids):
            node = self._snapshot.nodes.get(nid)
            if node and (node_type is None or node.node_type == node_type):
                neighbors.append(node)

        return neighbors

    def get_subgraph(
        self,
        root_node_id: str,
        max_depth: int = 3,
        max_nodes: int = 100,
        max_edges: int = 200,
        direction: str = "outbound",
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> TwinSubgraph:
        """Perform bounded BFS traversal from root node with cycle detection and strict bounds."""
        start_time = time.perf_counter()

        # Enforce security bounds
        effective_depth = min(max(1, max_depth), MAX_ALLOWED_DEPTH)
        effective_max_nodes = min(max(1, max_nodes), MAX_ALLOWED_NODES)
        effective_max_edges = min(max(1, max_edges), MAX_ALLOWED_EDGES)

        root = self.get_node(root_node_id)

        visited_node_ids: Set[str] = {root.node_id}
        collected_nodes: Dict[str, TwinNodeContract] = {root.node_id: root}
        collected_edges: Dict[str, TwinEdgeContract] = {}

        # Queue contains (current_node_id, current_depth)
        queue: deque[Tuple[str, int]] = deque([(root.node_id, 0)])

        while queue:
            curr_id, curr_depth = queue.popleft()

            if curr_depth >= effective_depth:
                continue

            # Identify candidate edges based on direction
            candidate_edges: List[TwinEdgeContract] = []
            if direction in ("outbound", "both"):
                candidate_edges.extend(self._outbound_edges.get(curr_id, []))
            if direction in ("inbound", "both"):
                candidate_edges.extend(self._inbound_edges.get(curr_id, []))

            for edge in candidate_edges:
                if len(collected_edges) >= effective_max_edges:
                    break

                collected_edges[edge.edge_id] = edge

                # Next node depends on edge orientation
                next_node_id = (
                    edge.to_node_id if edge.from_node_id == curr_id else edge.from_node_id
                )

                # Cycle handling: if already visited, do NOT enqueue again
                if next_node_id not in visited_node_ids:
                    if len(collected_nodes) >= effective_max_nodes:
                        break

                    next_node = self._snapshot.nodes.get(next_node_id)
                    if next_node:
                        visited_node_ids.add(next_node_id)
                        collected_nodes[next_node_id] = next_node
                        queue.append((next_node_id, curr_depth + 1))

        query_duration_ms = (time.perf_counter() - start_time) * 1000
        TwinObservability.log_query(
            organization_id=self.organization_id,
            twin_id=self.twin_id,
            query_type="get_subgraph",
            query_details={
                "root_node_id": root_node_id,
                "max_depth": effective_depth,
                "direction": direction,
            },
            query_duration_ms=query_duration_ms,
            result_node_count=len(collected_nodes),
            result_edge_count=len(collected_edges),
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )

        return TwinSubgraph(
            root_node_id=root_node_id,
            depth=effective_depth,
            nodes=list(collected_nodes.values()),
            edges=list(collected_edges.values()),
            total_nodes=len(collected_nodes),
            total_edges=len(collected_edges),
        )

    def find_path(
        self,
        source_node_id: str,
        target_node_id: str,
        max_depth: int = 5,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> TwinPathResult:
        """Deterministic BFS path reachability discovery with cycle prevention.

        NOTE: This is graph traversal only; it does NOT calculate or claim optimal cost or shortest distance.
        """
        start_time = time.perf_counter()

        effective_depth = min(max(1, max_depth), MAX_ALLOWED_DEPTH)

        source_node = self.get_node(source_node_id)
        target_node = self.get_node(target_node_id)

        if source_node.node_id == target_node.node_id:
            return TwinPathResult(
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                path_found=True,
                node_ids=[source_node_id],
                edge_ids=[],
                hop_count=0,
            )

        # BFS queue stores (current_node_id, [path_node_ids], [path_edge_ids])
        queue: deque[Tuple[str, List[str], List[str]]] = deque(
            [(source_node.node_id, [source_node.node_id], [])]
        )
        visited_nodes: Set[str] = {source_node.node_id}

        found_result: Optional[TwinPathResult] = None

        while queue:
            curr_id, path_nodes, path_edges = queue.popleft()

            if len(path_nodes) - 1 >= effective_depth:
                continue

            for edge in self._outbound_edges.get(curr_id, []):
                next_node_id = edge.to_node_id

                if next_node_id == target_node.node_id:
                    found_result = TwinPathResult(
                        source_node_id=source_node_id,
                        target_node_id=target_node_id,
                        path_found=True,
                        node_ids=path_nodes + [next_node_id],
                        edge_ids=path_edges + [edge.edge_id],
                        hop_count=len(path_edges) + 1,
                    )
                    break

                if next_node_id not in visited_nodes:
                    visited_nodes.add(next_node_id)
                    queue.append(
                        (next_node_id, path_nodes + [next_node_id], path_edges + [edge.edge_id])
                    )

            if found_result:
                break

        query_duration_ms = (time.perf_counter() - start_time) * 1000
        TwinObservability.log_query(
            organization_id=self.organization_id,
            twin_id=self.twin_id,
            query_type="find_path",
            query_details={
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "max_depth": effective_depth,
            },
            query_duration_ms=query_duration_ms,
            result_node_count=len(found_result.node_ids) if found_result else 0,
            result_edge_count=len(found_result.edge_ids) if found_result else 0,
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )

        if found_result:
            return found_result

        return TwinPathResult(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            path_found=False,
            node_ids=[],
            edge_ids=[],
            hop_count=0,
        )
