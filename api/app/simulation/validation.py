"""Validation logic for RiskWise Simulation Engine scenarios, changes, and inputs."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationInput,
    SimulationScenario,
)
from app.simulation.errors import (
    SimulationResourceLimitError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)

# Hard resource limits to prevent denial of service or unbounded execution
MAX_SCENARIO_CHANGES = 50
HARD_MAX_DEPTH = 10
HARD_MAX_NODES = 1000
HARD_MAX_EDGES = 2000
HARD_MAX_EFFECTS = 500


class SimulationValidator:
    """Validator enforcing strict integrity, tenant boundaries, and operational constraints."""

    @staticmethod
    def validate_scenario(
        scenario: SimulationScenario,
        snapshot: DigitalTwinSnapshot,
    ) -> None:
        """Validate scenario definition against the authoritative Digital Twin snapshot."""
        if not scenario.scenario_id or not scenario.scenario_id.strip():
            raise SimulationValidationError("scenario_id must be non-empty")

        if not scenario.organization_id or not scenario.organization_id.strip():
            raise SimulationValidationError("organization_id must be non-empty")

        # 1. Multi-tenant boundary check
        if scenario.organization_id != snapshot.organization_id:
            raise SimulationTenantIsolationError(
                f"Tenant mismatch: scenario organization '{scenario.organization_id}' "
                f"does not match snapshot organization '{snapshot.organization_id}'"
            )

        # 2. Snapshot fingerprint match
        if scenario.base_snapshot_fingerprint != snapshot.twin_fingerprint:
            raise SimulationValidationError(
                f"Base snapshot fingerprint mismatch: scenario specifies '{scenario.base_snapshot_fingerprint}', "
                f"but snapshot has '{snapshot.twin_fingerprint}'"
            )

        # 3. Change count bounding
        if len(scenario.changes) > MAX_SCENARIO_CHANGES:
            raise SimulationResourceLimitError(
                f"Scenario changes ({len(scenario.changes)}) exceed maximum limit of {MAX_SCENARIO_CHANGES}"
            )

        # 4. Validate individual changes and conflict detection
        seen_targets: Dict[str, Set[SimulationChangeType]] = {}
        for change in scenario.changes:
            SimulationValidator.validate_change(change, snapshot)

            target = change.target_entity_id
            if target not in seen_targets:
                seen_targets[target] = set()

            # Disallow conflicting duplicate change types on the exact same target entity
            if change.change_type in seen_targets[target]:
                raise SimulationValidationError(
                    f"Conflicting redundant change: entity '{target}' already has a '{change.change_type.value}' change declared"
                )

            # Disallow mutually exclusive changes (e.g. capacity reduction and capacity increase simultaneously)
            if (
                change.change_type == SimulationChangeType.CAPACITY_REDUCTION
                and SimulationChangeType.CAPACITY_INCREASE in seen_targets[target]
            ) or (
                change.change_type == SimulationChangeType.CAPACITY_INCREASE
                and SimulationChangeType.CAPACITY_REDUCTION in seen_targets[target]
            ):
                raise SimulationValidationError(
                    f"Conflicting mutually exclusive changes on entity '{target}': cannot apply both CAPACITY_REDUCTION and CAPACITY_INCREASE"
                )

            seen_targets[target].add(change.change_type)

    @staticmethod
    def validate_change(change: SimulationChange, snapshot: DigitalTwinSnapshot) -> None:
        """Validate an individual hypothetical change against snapshot topology and physical rules."""
        if not change.change_id or not change.change_id.strip():
            raise SimulationValidationError("change_id must be non-empty")

        if not change.target_entity_id or not change.target_entity_id.strip():
            raise SimulationValidationError("target_entity_id must be non-empty")

        # 1. Target entity must exist in the snapshot
        target_found = False
        if change.change_type in (SimulationChangeType.NODE_UNAVAILABLE, SimulationChangeType.CAPACITY_REDUCTION, SimulationChangeType.CAPACITY_INCREASE):
            if change.target_entity_id in snapshot.nodes:
                target_found = True
            else:
                # Check if target is a source_entity_id
                for node in snapshot.nodes.values():
                    if node.source_entity_id == change.target_entity_id:
                        target_found = True
                        break
        elif change.change_type in (SimulationChangeType.EDGE_UNAVAILABLE, SimulationChangeType.TRANSIT_TIME_INCREASE):
            if change.target_entity_id in snapshot.edges:
                target_found = True
            else:
                # Check if target matches edge source_reference
                for edge in snapshot.edges.values():
                    if edge.source_reference == change.target_entity_id or edge.edge_id == change.target_entity_id:
                        target_found = True
                        break
        else:
            # DELAY, DEMAND_CHANGE, INVENTORY_CHANGE can target nodes, shipments, or products
            if change.target_entity_id in snapshot.nodes or change.target_entity_id in snapshot.edges:
                target_found = True
            else:
                for node in snapshot.nodes.values():
                    if node.source_entity_id == change.target_entity_id:
                        target_found = True
                        break

        if not target_found:
            raise SimulationValidationError(
                f"Target entity '{change.target_entity_id}' of type '{change.target_entity_type}' "
                f"does not exist in base Digital Twin snapshot '{snapshot.twin_id}'"
            )

        # 2. Magnitude & Unit validations
        if change.change_type == SimulationChangeType.CAPACITY_REDUCTION:
            if change.unit == SimulationChangeUnit.PERCENT and (change.magnitude < 0.0 or change.magnitude > 100.0):
                raise SimulationValidationError(
                    f"CAPACITY_REDUCTION percentage must be between 0.0 and 100.0, got {change.magnitude}"
                )
            elif change.magnitude < 0.0:
                raise SimulationValidationError(f"CAPACITY_REDUCTION magnitude cannot be negative, got {change.magnitude}")

        elif change.change_type == SimulationChangeType.CAPACITY_INCREASE:
            if change.magnitude < 0.0:
                raise SimulationValidationError(f"CAPACITY_INCREASE magnitude cannot be negative, got {change.magnitude}")

        elif change.change_type == SimulationChangeType.DELAY:
            if change.magnitude < 0.0:
                raise SimulationValidationError(f"DELAY magnitude cannot be negative, got {change.magnitude}")

        elif change.change_type == SimulationChangeType.TRANSIT_TIME_INCREASE:
            if change.magnitude < 0.0:
                raise SimulationValidationError(f"TRANSIT_TIME_INCREASE magnitude cannot be negative, got {change.magnitude}")

        # 3. Timestamp sanity check
        if change.start_time and change.end_time:
            if change.end_time < change.start_time:
                raise SimulationValidationError(
                    f"Change end_time ({change.end_time}) cannot be earlier than start_time ({change.start_time})"
                )

    @staticmethod
    def validate_simulation_input(sim_input: SimulationInput) -> None:
        """Validate execution parameters and resource limits."""
        if sim_input.max_depth > HARD_MAX_DEPTH:
            raise SimulationResourceLimitError(
                f"Requested max_depth ({sim_input.max_depth}) exceeds hard maximum {HARD_MAX_DEPTH}"
            )
        if sim_input.max_nodes > HARD_MAX_NODES:
            raise SimulationResourceLimitError(
                f"Requested max_nodes ({sim_input.max_nodes}) exceeds hard maximum {HARD_MAX_NODES}"
            )
        if sim_input.max_edges > HARD_MAX_EDGES:
            raise SimulationResourceLimitError(
                f"Requested max_edges ({sim_input.max_edges}) exceeds hard maximum {HARD_MAX_EDGES}"
            )
        if sim_input.max_effects > HARD_MAX_EFFECTS:
            raise SimulationResourceLimitError(
                f"Requested max_effects ({sim_input.max_effects}) exceeds hard maximum {HARD_MAX_EFFECTS}"
            )
