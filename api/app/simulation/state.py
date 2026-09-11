"""Isolated in-memory simulation state cloned from Digital Twin snapshots."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.digital_twin.contracts import DigitalTwinSnapshot, TwinEdgeContract, TwinNodeContract
from app.simulation.contracts import SimulationChange, SimulationChangeType, SimulationChangeUnit
from app.simulation.errors import SimulationStateError
from app.simulation.fingerprints import compute_sha256, canonical_json


@dataclass
class SimulatedNodeState:
    """Isolated, mutable in-memory representation of a graph node inside a simulation."""

    node_id: str
    organization_id: str
    node_type: str
    source_entity_type: str
    source_entity_id: str
    label: str
    is_available: bool = True
    status: str = "OPERATIONAL"
    capacity: Optional[float] = None
    baseline_capacity: Optional[float] = None
    effective_delay_minutes: float = 0.0
    health_score: Optional[float] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    simulated_tags: Set[str] = field(default_factory=set)
    source_type: str = "SIMULATED"

    @classmethod
    def from_twin_node(cls, node: TwinNodeContract) -> SimulatedNodeState:
        cap = node.properties.get("capacity") or node.properties.get("total_capacity")
        return cls(
            node_id=node.node_id,
            organization_id=node.organization_id,
            node_type=node.node_type.value,
            source_entity_type=node.source_entity_type,
            source_entity_id=node.source_entity_id,
            label=node.label,
            is_available=(node.status != "INACTIVE"),
            status=node.status or "OPERATIONAL",
            capacity=float(cap) if cap is not None else None,
            baseline_capacity=float(cap) if cap is not None else None,
            effective_delay_minutes=float(node.properties.get("delay_minutes") or 0.0),
            health_score=node.health_score,
            properties=copy.deepcopy(node.properties),
            source_type="SIMULATED",
        )


@dataclass
class SimulatedEdgeState:
    """Isolated, mutable in-memory representation of a graph relationship edge inside a simulation."""

    edge_id: str
    organization_id: str
    from_node_id: str
    to_node_id: str
    edge_type: str
    is_available: bool = True
    status: str = "ACTIVE"
    flow_capacity: Optional[float] = None
    baseline_flow_capacity: Optional[float] = None
    current_flow: Optional[float] = None
    added_transit_time_minutes: float = 0.0
    risk_score: Optional[float] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    source_reference: Optional[str] = None
    simulated_tags: Set[str] = field(default_factory=set)
    source_type: str = "SIMULATED"

    @classmethod
    def from_twin_edge(cls, edge: TwinEdgeContract) -> SimulatedEdgeState:
        return cls(
            edge_id=edge.edge_id,
            organization_id=edge.organization_id,
            from_node_id=edge.from_node_id,
            to_node_id=edge.to_node_id,
            edge_type=edge.edge_type.value,
            is_available=(edge.status != "DISRUPTED"),
            status=edge.status or "ACTIVE",
            flow_capacity=edge.flow_capacity,
            baseline_flow_capacity=edge.flow_capacity,
            current_flow=edge.current_flow,
            added_transit_time_minutes=0.0,
            risk_score=edge.risk_score,
            properties=copy.deepcopy(edge.properties),
            source_reference=edge.source_reference,
            source_type="SIMULATED",
        )


class SimulationState:
    """Cloned, fully isolated graph state for scenario evaluation."""

    def __init__(
        self,
        organization_id: str,
        base_snapshot_fingerprint: str,
        nodes: Dict[str, SimulatedNodeState],
        edges: Dict[str, SimulatedEdgeState],
    ):
        self.organization_id = organization_id
        self.base_snapshot_fingerprint = base_snapshot_fingerprint
        self.nodes = nodes
        self.edges = edges

        # Build fast lookup indexes
        self.source_id_to_node_id: Dict[str, str] = {
            n.source_entity_id: n.node_id for n in self.nodes.values()
        }
        self.source_ref_to_edge_id: Dict[str, str] = {
            e.source_reference: e.edge_id for e in self.edges.values() if e.source_reference
        }

        # Build adjacency maps
        self.outgoing_edges: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        self.incoming_edges: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        for edge_id, edge in self.edges.items():
            if edge.from_node_id in self.outgoing_edges:
                self.outgoing_edges[edge.from_node_id].append(edge_id)
            if edge.to_node_id in self.incoming_edges:
                self.incoming_edges[edge.to_node_id].append(edge_id)

        self.applied_changes: List[SimulationChange] = []

    @classmethod
    def from_digital_twin_snapshot(cls, snapshot: DigitalTwinSnapshot) -> SimulationState:
        """Construct an isolated in-memory simulation state from an authoritative snapshot."""
        sim_nodes = {
            nid: SimulatedNodeState.from_twin_node(n)
            for nid, n in snapshot.nodes.items()
        }
        sim_edges = {
            eid: SimulatedEdgeState.from_twin_edge(e)
            for eid, e in snapshot.edges.items()
        }
        return cls(
            organization_id=snapshot.organization_id,
            base_snapshot_fingerprint=snapshot.twin_fingerprint,
            nodes=sim_nodes,
            edges=sim_edges,
        )

    def resolve_node_id(self, target_id: str) -> Optional[str]:
        """Resolve either a twin node_id or a source_entity_id to a valid node_id."""
        if target_id in self.nodes:
            return target_id
        return self.source_id_to_node_id.get(target_id)

    def resolve_edge_id(self, target_id: str) -> Optional[str]:
        """Resolve either an edge_id or a source_reference to a valid edge_id."""
        if target_id in self.edges:
            return target_id
        return self.source_ref_to_edge_id.get(target_id)

    def apply_change(self, change: SimulationChange) -> None:
        """Apply a single hypothetical change strictly in-memory."""
        # 1. NODE_UNAVAILABLE
        if change.change_type == SimulationChangeType.NODE_UNAVAILABLE:
            node_id = self.resolve_node_id(change.target_entity_id)
            if not node_id or node_id not in self.nodes:
                raise SimulationStateError(f"Target node '{change.target_entity_id}' not found in state")
            node = self.nodes[node_id]
            node.is_available = False
            node.status = "SIMULATED_UNAVAILABLE"
            node.simulated_tags.add("OUTAGE")
            # All outgoing and incoming edges become practically unusable
            for edge_id in self.outgoing_edges.get(node_id, []):
                self.edges[edge_id].is_available = False
                self.edges[edge_id].status = "SEVERED_BY_NODE_OUTAGE"
            for edge_id in self.incoming_edges.get(node_id, []):
                self.edges[edge_id].is_available = False
                self.edges[edge_id].status = "SEVERED_BY_NODE_OUTAGE"

        # 2. EDGE_UNAVAILABLE
        elif change.change_type == SimulationChangeType.EDGE_UNAVAILABLE:
            edge_id = self.resolve_edge_id(change.target_entity_id)
            if not edge_id or edge_id not in self.edges:
                raise SimulationStateError(f"Target edge '{change.target_entity_id}' not found in state")
            edge = self.edges[edge_id]
            edge.is_available = False
            edge.status = "SIMULATED_UNAVAILABLE"
            edge.simulated_tags.add("OUTAGE")

        # 3. DELAY / DELAY_INCREASE
        elif change.change_type in (SimulationChangeType.DELAY, SimulationChangeType.DELAY_INCREASE):
            node_id = self.resolve_node_id(change.target_entity_id)
            if node_id and node_id in self.nodes:
                node = self.nodes[node_id]
                delay_mins = self._convert_to_minutes(change.magnitude, change.unit)
                node.effective_delay_minutes += delay_mins
                node.simulated_tags.add("DELAYED")
            else:
                edge_id = self.resolve_edge_id(change.target_entity_id)
                if edge_id and edge_id in self.edges:
                    edge = self.edges[edge_id]
                    delay_mins = self._convert_to_minutes(change.magnitude, change.unit)
                    edge.added_transit_time_minutes += delay_mins
                    edge.simulated_tags.add("DELAYED")
                else:
                    raise SimulationStateError(
                        f"Target entity '{change.target_entity_id}' for {change.change_type.value} not found"
                    )

        # 4. CAPACITY_REDUCTION
        elif change.change_type == SimulationChangeType.CAPACITY_REDUCTION:
            node_id = self.resolve_node_id(change.target_entity_id)
            if not node_id or node_id not in self.nodes:
                raise SimulationStateError(f"Target node '{change.target_entity_id}' for CAPACITY_REDUCTION not found")
            node = self.nodes[node_id]
            if node.baseline_capacity is not None:
                if change.unit == SimulationChangeUnit.PERCENT:
                    reduction_factor = max(0.0, 1.0 - (change.magnitude / 100.0))
                    node.capacity = node.baseline_capacity * reduction_factor
                else:
                    node.capacity = max(0.0, node.baseline_capacity - change.magnitude)
                node.simulated_tags.add("CAPACITY_REDUCED")
            else:
                node.simulated_tags.add("CAPACITY_NOT_AVAILABLE")

        # 5. CAPACITY_INCREASE
        elif change.change_type == SimulationChangeType.CAPACITY_INCREASE:
            node_id = self.resolve_node_id(change.target_entity_id)
            if not node_id or node_id not in self.nodes:
                raise SimulationStateError(f"Target node '{change.target_entity_id}' for CAPACITY_INCREASE not found")
            node = self.nodes[node_id]
            if node.baseline_capacity is not None:
                if change.unit == SimulationChangeUnit.PERCENT:
                    increase_factor = 1.0 + (change.magnitude / 100.0)
                    node.capacity = node.baseline_capacity * increase_factor
                else:
                    node.capacity = node.baseline_capacity + change.magnitude
                node.simulated_tags.add("CAPACITY_INCREASED")
            else:
                node.simulated_tags.add("CAPACITY_NOT_AVAILABLE")

        # 6. TRANSIT_TIME_INCREASE
        elif change.change_type == SimulationChangeType.TRANSIT_TIME_INCREASE:
            edge_id = self.resolve_edge_id(change.target_entity_id)
            if not edge_id or edge_id not in self.edges:
                raise SimulationStateError(f"Target edge '{change.target_entity_id}' for TRANSIT_TIME_INCREASE not found")
            edge = self.edges[edge_id]
            added_mins = self._convert_to_minutes(change.magnitude, change.unit)
            edge.added_transit_time_minutes += added_mins
            edge.simulated_tags.add("TRANSIT_DELAYED")

        # 7. INVENTORY_CHANGE / DEMAND_CHANGE
        elif change.change_type in (SimulationChangeType.INVENTORY_CHANGE, SimulationChangeType.DEMAND_CHANGE):
            node_id = self.resolve_node_id(change.target_entity_id)
            if node_id and node_id in self.nodes:
                node = self.nodes[node_id]
                node.properties[f"simulated_{change.change_type.value.lower()}"] = change.magnitude
                node.simulated_tags.add(change.change_type.value)

        self.applied_changes.append(change)

    def _convert_to_minutes(self, magnitude: float, unit: SimulationChangeUnit) -> float:
        """Helper to convert time durations to minutes deterministically."""
        if unit == SimulationChangeUnit.MINUTES:
            return float(magnitude)
        elif unit == SimulationChangeUnit.HOURS:
            return float(magnitude) * 60.0
        elif unit == SimulationChangeUnit.DAYS:
            return float(magnitude) * 1440.0
        return float(magnitude)

    def compute_state_fingerprint(self) -> str:
        """Compute deterministic hash of the active in-memory state."""
        node_summaries = sorted([
            f"{n.node_id}:{n.status}:{n.is_available}:{n.capacity}:{n.effective_delay_minutes}"
            for n in self.nodes.values()
        ])
        edge_summaries = sorted([
            f"{e.edge_id}:{e.status}:{e.is_available}:{e.flow_capacity}:{e.added_transit_time_minutes}"
            for e in self.edges.values()
        ])
        payload = {
            "base_fingerprint": self.base_snapshot_fingerprint,
            "nodes": node_summaries,
            "edges": edge_summaries,
            "change_count": len(self.applied_changes),
        }
        return compute_sha256(canonical_json(payload))
