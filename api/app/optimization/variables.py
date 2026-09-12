"""Decision variable formulations for RiskWise Optimization Subsystem (Phase 14).

Creates explicit, deterministic mathematical decision variables for supported domains:
- SHIPMENT_REROUTE: Binary assignment of shipment to candidate route
- ROUTE_SELECTION: Binary selection of transport corridor
- CARRIER_ALLOCATION: Allocation of volume/shipments to freight carriers
- FACILITY_ALLOCATION: Allocation of load to warehouses/factories
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationDomain,
    OptimizationVariable,
    VariableType,
)
from app.optimization.fingerprints import generate_variable_id


class VariableBuilder:
    """Constructs explicit decision variables for supply chain optimization domains."""

    @staticmethod
    def build_shipment_reroute_variables(
        shipment_ids: List[str],
        candidates: List[OptimizationAlternative],
    ) -> Dict[str, OptimizationVariable]:
        """Build binary decision variables x_{shipment, route} for shipment rerouting."""
        variables: Dict[str, OptimizationVariable] = {}
        # Deterministic sorting
        sorted_shipment_ids = sorted(shipment_ids)
        sorted_candidates = sorted(candidates, key=lambda c: c.alternative_id)

        for s_id in sorted_shipment_ids:
            for cand in sorted_candidates:
                var_id = generate_variable_id("reroute", s_id, cand.entity_id)
                var = OptimizationVariable(
                    variable_id=var_id,
                    variable_type=VariableType.BINARY,
                    domain=OptimizationDomain.SHIPMENT_REROUTE,
                    lower_bound=0.0,
                    upper_bound=1.0,
                    source_entity_type="SHIPMENT",
                    source_entity_id=s_id,
                    target_entity_type=cand.entity_type,
                    target_entity_id=cand.entity_id,
                    description=f"Assign shipment {s_id} to candidate {cand.entity_type} {cand.entity_id}",
                    metadata={
                        "alternative_id": cand.alternative_id,
                        "candidate_capacity": cand.capacity,
                        "candidate_cost": cand.cost,
                        "candidate_transit_hours": cand.transit_time_hours,
                        "candidate_risk": cand.risk_score,
                    },
                )
                variables[var_id] = var

        return variables

    @staticmethod
    def build_route_selection_variables(
        candidates: List[OptimizationAlternative],
    ) -> Dict[str, OptimizationVariable]:
        """Build binary decision variables for selecting route corridors."""
        variables: Dict[str, OptimizationVariable] = {}
        sorted_candidates = sorted(candidates, key=lambda c: c.alternative_id)

        for cand in sorted_candidates:
            var_id = generate_variable_id("selection", "network", cand.entity_id)
            var = OptimizationVariable(
                variable_id=var_id,
                variable_type=VariableType.BINARY,
                domain=OptimizationDomain.ROUTE_SELECTION,
                lower_bound=0.0,
                upper_bound=1.0,
                source_entity_type="NETWORK",
                source_entity_id="active_network",
                target_entity_type=cand.entity_type,
                target_entity_id=cand.entity_id,
                description=f"Select corridor {cand.entity_id}",
                metadata={"alternative_id": cand.alternative_id},
            )
            variables[var_id] = var

        return variables
