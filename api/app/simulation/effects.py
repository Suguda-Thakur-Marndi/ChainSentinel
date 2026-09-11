"""Effect definitions and cataloging for simulation propagation."""
from __future__ import annotations

from typing import List, Optional

from app.simulation.contracts import SimulationChangeUnit, SimulationEffect
from app.simulation.fingerprints import compute_effect_id


class SimulationEffectFactory:
    """Factory creating deterministic, explainable simulation effects."""

    @staticmethod
    def create_effect(
        simulation_id: str,
        originating_change_id: str,
        affected_entity_id: str,
        affected_entity_type: str,
        effect_type: str,
        rule_applied: str,
        description: str,
        magnitude: Optional[float] = None,
        unit: Optional[SimulationChangeUnit] = None,
        propagation_path: Optional[List[str]] = None,
        confidence_score: float = 1.0,
    ) -> SimulationEffect:
        """Construct a strongly-typed SimulationEffect with deterministic ID."""
        effect_id = compute_effect_id(
            simulation_id=simulation_id,
            originating_change_id=originating_change_id,
            affected_entity_id=affected_entity_id,
            effect_type=effect_type,
        )
        return SimulationEffect(
            effect_id=effect_id,
            originating_change_id=originating_change_id,
            affected_entity_id=affected_entity_id,
            affected_entity_type=affected_entity_type,
            effect_type=effect_type,
            magnitude=magnitude,
            unit=unit,
            propagation_path=propagation_path or [affected_entity_id],
            rule_applied=rule_applied,
            description=description,
            confidence_score=confidence_score,
            is_simulated=True,
        )
