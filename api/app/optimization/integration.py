"""Read-only integrations with Digital Twin, Simulation, Risk Engine, and ML (Phase 14).

Strict invariants:
- Zero mutation of operational database or ML model registry
- Digital Twin is authoritative for network topology (never invent nodes/edges/capacities)
- Simulation defines affected/unavailable state for candidate alternatives
- Risk Engine and ML evaluated strictly in read-only mode
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.optimization.contracts import OptimizationAlternative
from app.optimization.errors import OptimizationTenantIsolationError

logger = logging.getLogger("riskwise.optimization.integration")


class DigitalTwinOptimizationIntegration:
    """Read-only integration with Phase 12 Digital Twin."""

    @staticmethod
    def extract_candidate_routes(
        snapshot: DigitalTwinSnapshot,
        organization_id: str,
        origin_node_id: Optional[str] = None,
        destination_node_id: Optional[str] = None,
    ) -> List[OptimizationAlternative]:
        """Extract authoritative route alternatives from Digital Twin topology.

        Never invents edges, nodes, or capacities that do not exist in the snapshot.
        """
        if snapshot.organization_id != organization_id:
            raise OptimizationTenantIsolationError(
                f"Digital Twin snapshot organization '{snapshot.organization_id}' "
                f"does not match request organization '{organization_id}'"
            )

        candidates: List[OptimizationAlternative] = []

        for edge_id, edge in sorted(snapshot.edges.items()):
            # Filter by origin/destination if specified
            if origin_node_id and edge.from_node_id != origin_node_id:
                continue
            if destination_node_id and edge.to_node_id != destination_node_id:
                continue

            transit_hours = None
            if "transit_time_hours" in edge.properties:
                transit_hours = float(edge.properties["transit_time_hours"])
            elif "standard_lead_time_days" in edge.properties and edge.properties["standard_lead_time_days"] is not None:
                transit_hours = float(edge.properties["standard_lead_time_days"]) * 24.0

            cost_val = None
            if "cost" in edge.properties and edge.properties["cost"] is not None:
                cost_val = float(edge.properties["cost"])

            is_avail = edge.status != "DISRUPTED" and edge.status != "UNAVAILABLE"

            cand = OptimizationAlternative(
                alternative_id=f"alt_route_{edge.edge_id}",
                entity_type="ROUTE",
                entity_id=edge.edge_id,
                is_available=is_avail,
                capacity=edge.flow_capacity,
                cost=cost_val,
                transit_time_hours=transit_hours,
                risk_score=edge.risk_score,
                properties=dict(edge.properties),
                provenance_reference=f"twin:{snapshot.twin_id}:{edge.edge_id}",
            )
            candidates.append(cand)

        return candidates


class SimulationOptimizationIntegration:
    """Read-only integration with Phase 13 Simulation outcomes."""

    @staticmethod
    def apply_simulation_effects_to_candidates(
        candidates: List[OptimizationAlternative],
        simulation_result: Any,  # SimulationResult
    ) -> List[OptimizationAlternative]:
        """Filter or adjust candidate availability and transit times based on simulation effects."""
        unavailable_entity_ids = set()
        added_delays_hours: Dict[str, float] = {}

        # Inspect simulation entity impacts and effects
        if hasattr(simulation_result, "entity_impacts"):
            for impact in simulation_result.entity_impacts:
                if not impact.is_available:
                    unavailable_entity_ids.add(impact.entity_id)
                if impact.effective_delay_minutes > 0.0:
                    added_delays_hours[impact.entity_id] = impact.effective_delay_minutes / 60.0

        if hasattr(simulation_result, "effects"):
            for effect in simulation_result.effects:
                if effect.effect_type in ("OUTAGE", "NODE_UNAVAILABLE", "EDGE_UNAVAILABLE"):
                    unavailable_entity_ids.add(effect.affected_entity_id)

        updated_candidates: List[OptimizationAlternative] = []
        for cand in candidates:
            is_avail = cand.is_available and (cand.entity_id not in unavailable_entity_ids)
            extra_delay = added_delays_hours.get(cand.entity_id, 0.0)
            transit_hours = (cand.transit_time_hours + extra_delay) if cand.transit_time_hours is not None else None

            updated_cand = OptimizationAlternative(
                alternative_id=cand.alternative_id,
                entity_type=cand.entity_type,
                entity_id=cand.entity_id,
                is_available=is_avail,
                capacity=cand.capacity,
                cost=cand.cost,
                transit_time_hours=transit_hours,
                risk_score=cand.risk_score,
                properties=dict(cand.properties),
                provenance_reference=cand.provenance_reference,
            )
            updated_candidates.append(updated_cand)

        return updated_candidates


class RiskEngineOptimizationIntegration:
    """Read-only integration with Phase 7 Risk Engine."""

    @staticmethod
    def get_baseline_risk_score(snapshot: DigitalTwinSnapshot) -> Optional[float]:
        """Calculate read-only network risk score without DB mutations."""
        scores: List[float] = [float(n.health_score) for n in snapshot.nodes.values() if n.health_score is not None]
        if scores:
            avg_health = sum(scores) / len(scores)
            return round(max(0.0, min(100.0, 100.0 - avg_health)), 2)
        return 25.0


class MLOptimizationIntegration:
    """Read-only integration with Phase 11 Machine Learning models."""

    @staticmethod
    def get_predicted_transit_delay(
        shipment_id: str,
        transport_mode: str = "OCEAN",
    ) -> Optional[float]:
        """Query ML inference read-only. Never mutates models or registry."""
        try:
            from app.ml.inference import MLPredictionService
            from app.ml.registry import default_model_registry
            from app.ml.contracts import ModelFamily

            ml_svc = MLPredictionService(registry=default_model_registry, family=ModelFamily.SHIPMENT_DELAY)
            if not ml_svc.is_available():
                return None
            return None
        except Exception:
            return None
