"""Deterministic, bounded graph effect propagation engine for what-if scenarios."""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Set, Tuple

from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationEffect,
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

    def propagate(self, state: SimulationState) -> Tuple[List[SimulationEffect], int, int]:
        """Execute bounded BFS effect propagation across the isolated simulation state."""
        effects: List[SimulationEffect] = []
        visited_nodes: Set[str] = set()
        traversed_edges: Set[str] = set()

        for change in state.applied_changes:
            if len(effects) >= self.max_effects:
                break

            # 1. Generate Direct Primary Effect
            primary_effects = self._generate_primary_effect(change, state)
            for pe in primary_effects:
                if len(effects) < self.max_effects:
                    effects.append(pe)

            # 2. Identify start nodes for downstream propagation
            start_nodes = self._resolve_propagation_origins(change, state)

            for origin_node_id in sorted(start_nodes):
                if len(effects) >= self.max_effects:
                    break

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

                        # Cycle prevention: only enqueue if not visited in this change traversal
                        if dest_node_id not in visited_in_change:
                            visited_in_change.add(dest_node_id)
                            visited_nodes.add(dest_node_id)
                            queue.append((dest_node_id, depth + 1, new_path, new_delay))

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
            # Propagate from the destination of the edge
            edge = state.edges[edge_id]
            origins.add(edge.to_node_id)

        return origins
