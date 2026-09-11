"""Scenario builders and multi-change composition utilities."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationScenario,
)
from app.simulation.fingerprints import (
    compute_change_id,
    compute_scenario_fingerprint,
    compute_scenario_id,
)


class SimulationScenarioBuilder:
    """Fluent builder for constructing validated, deterministic what-if scenarios."""

    def __init__(self, organization_id: str, name: str, base_snapshot_fingerprint: str):
        self.organization_id = organization_id.strip()
        self.name = name.strip()
        self.base_snapshot_fingerprint = base_snapshot_fingerprint.strip()
        self.description: Optional[str] = None
        self.changes: List[SimulationChange] = []
        self.parameters: Dict[str, Any] = {}
        self.scenario_id: str = compute_scenario_id(
            self.organization_id, self.name, self.base_snapshot_fingerprint
        )

    def with_description(self, description: str) -> SimulationScenarioBuilder:
        self.description = description
        return self

    def with_parameter(self, key: str, value: Any) -> SimulationScenarioBuilder:
        self.parameters[key] = value
        return self

    def add_node_outage(
        self,
        target_entity_id: str,
        target_entity_type: str = "PORT",
        duration_hours: float = 72.0,
        reason: Optional[str] = None,
    ) -> SimulationScenarioBuilder:
        """Add a NODE_UNAVAILABLE outage change."""
        change_id = compute_change_id(
            self.scenario_id, target_entity_id, SimulationChangeType.NODE_UNAVAILABLE.value, duration_hours
        )
        ch = SimulationChange(
            change_id=change_id,
            change_type=SimulationChangeType.NODE_UNAVAILABLE,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            magnitude=duration_hours,
            unit=SimulationChangeUnit.HOURS,
            duration_minutes=duration_hours * 60.0,
            reason=reason or f"{target_entity_type} outage of {duration_hours}h",
            source_type="SIMULATED",
        )
        self.changes.append(ch)
        return self

    def add_edge_outage(
        self,
        target_edge_id: str,
        duration_hours: float = 48.0,
        reason: Optional[str] = None,
    ) -> SimulationScenarioBuilder:
        """Add an EDGE_UNAVAILABLE corridor disruption change."""
        change_id = compute_change_id(
            self.scenario_id, target_edge_id, SimulationChangeType.EDGE_UNAVAILABLE.value, duration_hours
        )
        ch = SimulationChange(
            change_id=change_id,
            change_type=SimulationChangeType.EDGE_UNAVAILABLE,
            target_entity_type="ROUTE",
            target_entity_id=target_edge_id,
            magnitude=duration_hours,
            unit=SimulationChangeUnit.HOURS,
            duration_minutes=duration_hours * 60.0,
            reason=reason or f"Route corridor outage of {duration_hours}h",
            source_type="SIMULATED",
        )
        self.changes.append(ch)
        return self

    def add_delay(
        self,
        target_entity_id: str,
        target_entity_type: str = "SHIPMENT",
        delay_hours: float = 24.0,
        reason: Optional[str] = None,
    ) -> SimulationScenarioBuilder:
        """Add a DELAY change."""
        change_id = compute_change_id(
            self.scenario_id, target_entity_id, SimulationChangeType.DELAY.value, delay_hours
        )
        ch = SimulationChange(
            change_id=change_id,
            change_type=SimulationChangeType.DELAY,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            magnitude=delay_hours,
            unit=SimulationChangeUnit.HOURS,
            duration_minutes=delay_hours * 60.0,
            reason=reason or f"Delay of {delay_hours}h",
            source_type="SIMULATED",
        )
        self.changes.append(ch)
        return self

    def add_capacity_reduction(
        self,
        target_entity_id: str,
        target_entity_type: str = "WAREHOUSE",
        percentage: float = 30.0,
        reason: Optional[str] = None,
    ) -> SimulationScenarioBuilder:
        """Add a CAPACITY_REDUCTION change."""
        change_id = compute_change_id(
            self.scenario_id, target_entity_id, SimulationChangeType.CAPACITY_REDUCTION.value, percentage
        )
        ch = SimulationChange(
            change_id=change_id,
            change_type=SimulationChangeType.CAPACITY_REDUCTION,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            magnitude=percentage,
            unit=SimulationChangeUnit.PERCENT,
            reason=reason or f"Capacity reduction of {percentage}%",
            source_type="SIMULATED",
        )
        self.changes.append(ch)
        return self

    def add_capacity_increase(
        self,
        target_entity_id: str,
        target_entity_type: str = "WAREHOUSE",
        magnitude: float = 20.0,
        unit: SimulationChangeUnit = SimulationChangeUnit.PERCENT,
        reason: Optional[str] = None,
    ) -> SimulationScenarioBuilder:
        """Add a CAPACITY_INCREASE change."""
        change_id = compute_change_id(
            self.scenario_id, target_entity_id, SimulationChangeType.CAPACITY_INCREASE.value, magnitude
        )
        ch = SimulationChange(
            change_id=change_id,
            change_type=SimulationChangeType.CAPACITY_INCREASE,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            magnitude=magnitude,
            unit=unit,
            reason=reason or f"Capacity increase of {magnitude} {unit.value}",
            source_type="SIMULATED",
        )
        self.changes.append(ch)
        return self

    def add_transit_delay(
        self,
        target_edge_id: str,
        delay_hours: float = 12.0,
        reason: Optional[str] = None,
    ) -> SimulationScenarioBuilder:
        """Add a TRANSIT_TIME_INCREASE change on an edge/route corridor."""
        change_id = compute_change_id(
            self.scenario_id, target_edge_id, SimulationChangeType.TRANSIT_TIME_INCREASE.value, delay_hours
        )
        ch = SimulationChange(
            change_id=change_id,
            change_type=SimulationChangeType.TRANSIT_TIME_INCREASE,
            target_entity_type="ROUTE",
            target_entity_id=target_edge_id,
            magnitude=delay_hours,
            unit=SimulationChangeUnit.HOURS,
            duration_minutes=delay_hours * 60.0,
            reason=reason or f"Transit corridor delay of {delay_hours}h",
            source_type="SIMULATED",
        )
        self.changes.append(ch)
        return self

    def add_change(self, change: SimulationChange) -> SimulationScenarioBuilder:
        """Add a pre-constructed SimulationChange directly."""
        self.changes.append(change)
        return self

    def build(self) -> SimulationScenario:
        """Construct the immutable, fingerprinted SimulationScenario."""
        fp = compute_scenario_fingerprint(
            organization_id=self.organization_id,
            name=self.name,
            base_snapshot_fingerprint=self.base_snapshot_fingerprint,
            changes=self.changes,
            parameters=self.parameters,
        )
        return SimulationScenario(
            scenario_id=self.scenario_id,
            organization_id=self.organization_id,
            name=self.name,
            description=self.description,
            base_snapshot_fingerprint=self.base_snapshot_fingerprint,
            changes=list(self.changes),
            parameters=dict(self.parameters),
            fingerprint=fp,
        )
