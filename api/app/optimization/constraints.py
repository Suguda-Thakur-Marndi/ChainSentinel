"""Constraint formulations for RiskWise Optimization Subsystem (Phase 14).

Implements hard and soft mathematical constraints:
- Exactly-one assignment constraints: sum_{r} x_{s,r} == 1
- Availability constraints: x_{s,r} == 0 for disrupted or unavailable candidates
- Capacity constraints: sum_{s} load_{s} * x_{s,r} <= Capacity_{r}
- Compatibility constraints: mode matching
- Soft constraint penalties for delay or deviation
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.optimization.contracts import (
    ConstraintType,
    OptimizationAlternative,
    OptimizationConstraint,
    OptimizationVariable,
)
from app.optimization.fingerprints import generate_constraint_id


class ConstraintBuilder:
    """Constructs explicit mathematical constraints for optimization problems."""

    @staticmethod
    def build_shipment_assignment_constraints(
        shipment_ids: List[str],
        variables: Dict[str, OptimizationVariable],
    ) -> Dict[str, OptimizationConstraint]:
        """Build exactly-one assignment constraint for each shipment: sum_r x_{s,r} == 1."""
        constraints: Dict[str, OptimizationConstraint] = {}

        for s_id in sorted(shipment_ids):
            # Find all variables assigning this shipment
            matching_vars = [
                vid for vid, var in variables.items()
                if var.source_entity_type == "SHIPMENT" and var.source_entity_id == s_id
            ]
            if not matching_vars:
                continue

            cid = generate_constraint_id("assignment", s_id)
            con = OptimizationConstraint(
                constraint_id=cid,
                constraint_type=ConstraintType.HARD,
                description=f"Shipment {s_id} must be assigned to exactly one candidate alternative",
                variable_coefficients={vid: 1.0 for vid in sorted(matching_vars)},
                relation="==",
                rhs_value=1.0,
            )
            constraints[cid] = con

        return constraints

    @staticmethod
    def build_availability_constraints(
        candidates: List[OptimizationAlternative],
        variables: Dict[str, OptimizationVariable],
    ) -> Dict[str, OptimizationConstraint]:
        """Build availability constraints forcing x == 0 for unavailable candidates."""
        constraints: Dict[str, OptimizationConstraint] = {}

        for cand in sorted(candidates, key=lambda c: c.alternative_id):
            if not cand.is_available:
                # Force all variables targeting this candidate to 0
                matching_vars = [
                    vid for vid, var in variables.items()
                    if var.target_entity_id == cand.entity_id
                ]
                for vid in sorted(matching_vars):
                    cid = generate_constraint_id("availability", cand.entity_id, vid)
                    con = OptimizationConstraint(
                        constraint_id=cid,
                        constraint_type=ConstraintType.HARD,
                        description=f"Candidate {cand.entity_type} {cand.entity_id} is unavailable (forced to 0)",
                        variable_coefficients={vid: 1.0},
                        relation="==",
                        rhs_value=0.0,
                    )
                    constraints[cid] = con

        return constraints

    @staticmethod
    def build_capacity_constraints(
        candidates: List[OptimizationAlternative],
        variables: Dict[str, OptimizationVariable],
        shipment_loads: Optional[Dict[str, float]] = None,
    ) -> Dict[str, OptimizationConstraint]:
        """Build capacity constraints: sum_s load_s * x_{s,r} <= Capacity_r."""
        constraints: Dict[str, OptimizationConstraint] = {}
        loads = shipment_loads or {}

        for cand in sorted(candidates, key=lambda c: c.alternative_id):
            if cand.capacity is not None and cand.capacity > 0.0:
                matching_vars = [
                    (vid, var.source_entity_id)
                    for vid, var in variables.items()
                    if var.target_entity_id == cand.entity_id
                ]
                if not matching_vars:
                    continue

                var_coeffs: Dict[str, float] = {}
                for vid, s_id in sorted(matching_vars, key=lambda pair: pair[0]):
                    # Default load per shipment is 1.0 if not specified
                    var_coeffs[vid] = loads.get(s_id, 1.0)

                cid = generate_constraint_id("capacity", cand.entity_id)
                con = OptimizationConstraint(
                    constraint_id=cid,
                    constraint_type=ConstraintType.HARD,
                    description=f"Total load assigned to {cand.entity_type} {cand.entity_id} must not exceed capacity {cand.capacity}",
                    variable_coefficients=var_coeffs,
                    relation="<=",
                    rhs_value=float(cand.capacity),
                )
                constraints[cid] = con

        return constraints
