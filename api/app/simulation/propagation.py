"""Deterministic, bounded graph effect propagation engine for what-if scenarios."""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationEffect,
    SimulationEntityImpact,
    SimulationPropagation,
)
from app.simulation.effects import SimulationEffectFactory
from app.simulation.errors import SimulationResourceLimitError
from app.simulation.state import SimulationState


class SimulationPropagationEngine:
    """Propagates operational disruptions deterministically through the supply chain graph."""

    def __init__(
        self,
        simulation_id: str,
        max_depth: int = 5,
        max_nodes: int = 200,
        max_edges: int = 500,
        max_effects: int = 100,
    ):
        self.simulation_id = simulation_id
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self.max_effects = max_effects
        self.entity_impacts: List[SimulationEntityImpact] = []
        self.propagation_summary: Optional[SimulationPropagation] = None

    def propagate(self, state: SimulationState) -> Tuple[List[SimulationEffect], int, int]:
        """Execute bounded BFS effect propagation across the isolated simulation state."""
        effects: List[SimulationEffect] = []
        visited_nodes: Set[str] = set()
        traversed_edges: Set[str] = set()
        recorded_impacts: Dict[str, SimulationEntityImpact] = {}
        propagation_paths: List[List[str]] = []
        all_origin_nodes: List[str] = []
        max_depth_reached = 0

        for change in state.applied_changes:
            if len(effects) >= self.max_effects:
                break

            # 1. Generate Direct Primary Effect
            primary_effects = self._generate_primary_effect(change, state)
            for pe in primary_effects:
                if len(effects) < self.max_effects:
                    effects.append(pe)

            # Record direct entity impact
            target_nid = state.resolve_node_id(change.target_entity_id)
            if target_nid and target_nid in state.nodes:
                target_node = state.nodes[target_nid]
                cap_lost = None
                if target_node.baseline_capacity is not None and target_node.capacity is not None:
                    cap_lost = max(0.0, target_node.baseline_capacity - target_node.capacity)
                recorded_impacts[target_nid] = SimulationEntityImpact(
                    entity_id=target_nid,
                    entity_type=target_node.node_type,
                    impact_type=f"DIRECT_{change.change_type.value}",
                    is_direct=True,
                    effective_delay_minutes=target_node.effective_delay_minutes,
                    capacity_lost=cap_lost,
                    is_available=target_node.is_available,
                    propagation_depth=0,
                    simulated_tags=sorted(target_node.simulated_tags),
                )

            # 2. Identify start nodes for downstream propagation
            start_nodes = self._resolve_propagation_origins(change, state)
            for onode in sorted(start_nodes):
                if onode not in all_origin_nodes:
                    all_origin_nodes.append(onode)

            for origin_node_id in sorted(start_nodes):
                if len(effects) >= self.max_effects:
                    break

                # If node has no outgoing edges, explicitly mark as having no known dependencies
                outgoing = state.outgoing_edges.get(origin_node_id, [])
                if not outgoing:
                    origin_node = state.nodes.get(origin_node_id)
                    if origin_node:
                        origin_node.simulated_tags.add("NO_KNOWN_DEPENDENCY")

                # Queue elements: (node_id, current_depth, path, accumulated_delay_mins)
                initial_delay = state.nodes[origin_node_id].effective_delay_minutes
                queue = deque([(origin_node_id, 0, [origin_node_id], initial_delay)])
                visited_in_change: Set[str] = {origin_node_id}
                visited_nodes.add(origin_node_id)

                while queue:
                    if len(effects) >= self.max_effects:
                        break
                    if len(visited_nodes) > self.max_nodes:
                        raise SimulationResourceLimitError(
                            f"Propagation visited nodes ({len(visited_nodes)}) exceeded maximum allowed ({self.max_nodes})"
                        )
                    if len(traversed_edges) > self.max_edges:
                        raise SimulationResourceLimitError(
                            f"Propagation traversed edges ({len(traversed_edges)}) exceeded maximum allowed ({self.max_edges})"
                        )

                    current_node_id, depth, path, acc_delay = queue.popleft()
                    max_depth_reached = max(max_depth_reached, depth)

                    if depth >= self.max_depth:
                        continue

                    current_node = state.nodes[current_node_id]
                    outgoing_edge_ids = sorted(state.outgoing_edges.get(current_node_id, []))

                    for edge_id in outgoing_edge_ids:
                        if len(effects) >= self.max_effects:
                            break

                        traversed_edges.add(edge_id)
                        edge = state.edges[edge_id]
                        dest_node_id = edge.to_node_id

                        if dest_node_id not in state.nodes:
                            continue

                        dest_node = state.nodes[dest_node_id]
                        new_path = path + [edge_id, dest_node_id]
                        propagation_paths.append(new_path)
                        edge_delay = edge.added_transit_time_minutes
                        new_delay = acc_delay + edge_delay

                        # -------------------------------------------------------------
                        # RULE A: Downstream Supply Severance from Node/Edge Outage
                        # -------------------------------------------------------------
                        if not current_node.is_available or not edge.is_available:
                            dest_node.simulated_tags.add("FLOW_SEVERED")
                            eff = SimulationEffectFactory.create_effect(
                                simulation_id=self.simulation_id,
                                originating_change_id=change.change_id,
                                affected_entity_id=dest_node_id,
                                affected_entity_type=dest_node.node_type,
                                effect_type="SUPPLY_FLOW_SEVERED",
                                rule_applied="OUTAGE_FLOW_INTERRUPTION",
                                description=(
                                    f"Inflow to '{dest_node.label}' severed due to upstream outage at "
                                    f"'{current_node.label}' or edge '{edge.edge_type}'"
                                ),
                                propagation_path=new_path,
                                confidence_score=1.0,
                            )
                            effects.append(eff)

                        # -------------------------------------------------------------
                        # RULE B: Delay Propagation to Downstream Facilities/Shipments
                        # -------------------------------------------------------------
                        elif new_delay > 0.0:
                            dest_node.effective_delay_minutes += new_delay
                            dest_node.simulated_tags.add("DELAYED")
                            eff = SimulationEffectFactory.create_effect(
                                simulation_id=self.simulation_id,
                                originating_change_id=change.change_id,
                                affected_entity_id=dest_node_id,
                                affected_entity_type=dest_node.node_type,
                                effect_type="DOWNSTREAM_DELAY_PROPAGATED",
                                rule_applied="ARRIVAL_DELAY_CASCADE",
                                description=(
                                    f"Downstream arrival delay of {new_delay:.1f} minutes propagated to "
                                    f"'{dest_node.label}' via {edge.edge_type}"
                                ),
                                magnitude=new_delay,
                                unit=SimulationChangeUnit.MINUTES,
                                propagation_path=new_path,
                                confidence_score=0.95,
                            )
                            effects.append(eff)

                        # -------------------------------------------------------------
                        # RULE C: Warehouse / Facility Bottleneck or Inventory Exposure
                        # -------------------------------------------------------------
                        if dest_node.node_type in ("WAREHOUSE", "FACTORY"):
                            if not current_node.is_available or not edge.is_available:
                                dest_node.simulated_tags.add("INVENTORY_RISK")
                                eff = SimulationEffectFactory.create_effect(
                                    simulation_id=self.simulation_id,
                                    originating_change_id=change.change_id,
                                    affected_entity_id=dest_node_id,
                                    affected_entity_type=dest_node.node_type,
                                    effect_type="INVENTORY_REPLENISHMENT_RISK",
                                    rule_applied="STOCKOUT_EXPOSURE_RISK",
                                    description=(
                                        f"Facility '{dest_node.label}' is at risk of stockout due to "
                                        f"unavailability of replenishment channel from '{current_node.label}'"
                                    ),
                                    magnitude=dest_node.capacity or 0.0,
                                    unit=SimulationChangeUnit.UNITS,
                                    propagation_path=new_path,
                                    confidence_score=0.90,
                                )
                                effects.append(eff)

                        # Track propagated entity impact
                        if dest_node_id not in recorded_impacts:
                            cap_lost = None
                            if dest_node.baseline_capacity is not None and dest_node.capacity is not None:
                                cap_lost = max(0.0, dest_node.baseline_capacity - dest_node.capacity)
                            recorded_impacts[dest_node_id] = SimulationEntityImpact(
                                entity_id=dest_node_id,
                                entity_type=dest_node.node_type,
                                impact_type="PROPAGATED_DISRUPTION",
                                is_direct=False,
                                effective_delay_minutes=dest_node.effective_delay_minutes,
                                capacity_lost=cap_lost,
                                is_available=dest_node.is_available,
                                propagation_depth=depth + 1,
                                simulated_tags=sorted(dest_node.simulated_tags),
                            )

                        # Cycle prevention: only enqueue if not visited in this change traversal
                        if dest_node_id not in visited_in_change:
                            visited_in_change.add(dest_node_id)
                            visited_nodes.add(dest_node_id)
                            queue.append((dest_node_id, depth + 1, new_path, new_delay))

        self.entity_impacts = sorted(recorded_impacts.values(), key=lambda x: x.entity_id)
        self.propagation_summary = SimulationPropagation(
            origin_nodes=all_origin_nodes,
            max_depth_reached=max_depth_reached,
            nodes_visited_count=len(visited_nodes),
            edges_traversed_count=len(traversed_edges),
            effects_generated_count=len(effects),
            propagation_paths=propagation_paths[:50],  # bounded sample for audit
        )

        return effects, len(visited_nodes), len(traversed_edges)

    def _generate_primary_effect(
        self,
        change: SimulationChange,
        state: SimulationState,
    ) -> List[SimulationEffect]:
        """Generate direct, non-propagated primary effects on the target entity."""
        effects = []
        target_node_id = state.resolve_node_id(change.target_entity_id)
        if target_node_id and target_node_id in state.nodes:
            node = state.nodes[target_node_id]
            desc = f"Primary change applied: {change.change_type.value} on {node.node_type} '{node.label}'"
            if change.reason:
                desc += f" (Reason: {change.reason})"
            eff = SimulationEffectFactory.create_effect(
                simulation_id=self.simulation_id,
                originating_change_id=change.change_id,
                affected_entity_id=target_node_id,
                affected_entity_type=node.node_type,
                effect_type=f"DIRECT_{change.change_type.value}",
                rule_applied="PRIMARY_SCENARIO_INJECTION",
                description=desc,
                magnitude=change.magnitude,
                unit=change.unit,
                propagation_path=[target_node_id],
                confidence_score=1.0,
            )
            effects.append(eff)
            return effects

        target_edge_id = state.resolve_edge_id(change.target_entity_id)
        if target_edge_id and target_edge_id in state.edges:
            edge = state.edges[target_edge_id]
            eff = SimulationEffectFactory.create_effect(
                simulation_id=self.simulation_id,
                originating_change_id=change.change_id,
                affected_entity_id=target_edge_id,
                affected_entity_type="EDGE",
                effect_type=f"DIRECT_{change.change_type.value}",
                rule_applied="PRIMARY_SCENARIO_INJECTION",
                description=f"Primary change applied to edge '{edge.edge_type}' ({change.change_type.value})",
                magnitude=change.magnitude,
                unit=change.unit,
                propagation_path=[target_edge_id],
                confidence_score=1.0,
            )
            effects.append(eff)

        return effects

    def _resolve_propagation_origins(
        self,
        change: SimulationChange,
        state: SimulationState,
    ) -> Set[str]:
        """Find the root node IDs from which graph propagation should originate."""
        origins = set()
        node_id = state.resolve_node_id(change.target_entity_id)
        if node_id and node_id in state.nodes:
            origins.add(node_id)
            return origins

        edge_id = state.resolve_edge_id(change.target_entity_id)
        if edge_id and edge_id in state.edges:
            # Propagate from the origin of the edge so the edge itself and its destination are evaluated
            edge = state.edges[edge_id]
            origins.add(edge.from_node_id)

        return origins
