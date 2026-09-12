"""Mathematical objective function formulations for RiskWise Optimization Subsystem (Phase 14).

Formulates explicit objectives:
- MINIMIZE_DELAY: Minimizes total projected delay or transit duration across shipments
- MINIMIZE_COST: Minimizes authoritative financial costs (fails closed if cost data is missing)
- MINIMIZE_RISK: Minimizes network risk exposure scores
- MINIMIZE_ROUTE_DEVIATION: Minimizes diversion from authoritative baseline routes
"""
from __future__ import annotations

from typing import Dict, List

from app.optimization.contracts import (
    ObjectiveDirection,
    OptimizationAlternative,
    OptimizationObjective,
    OptimizationObjectiveType,
    OptimizationVariable,
)
from app.optimization.errors import OptimizationDataMissingError


class ObjectiveBuilder:
    """Builds explicit linear objective functions."""

    @staticmethod
    def build_objective(
        objective_type: OptimizationObjectiveType,
        variables: Dict[str, OptimizationVariable],
        candidates: List[OptimizationAlternative],
    ) -> OptimizationObjective:
        """Build linear objective function matching the requested objective type."""
        candidate_map = {c.entity_id: c for c in candidates}
        coeffs: Dict[str, float] = {}

        for vid, var in sorted(variables.items()):
            target_id = var.target_entity_id
            if not target_id:
                continue
            cand = candidate_map.get(target_id)
            if not cand:
                continue

            if objective_type == OptimizationObjectiveType.MINIMIZE_DELAY:
                # Use transit time in hours or 0.0 if zero delay
                time_val = cand.transit_time_hours if cand.transit_time_hours is not None else 0.0
                coeffs[vid] = float(time_val)

            elif objective_type == OptimizationObjectiveType.MINIMIZE_COST:
                if cand.cost is None:
                    raise OptimizationDataMissingError(
                        f"Candidate '{cand.alternative_id}' has no authoritative cost data. "
                        f"Cost cannot be fabricated for MINIMIZE_COST objective."
                    )
                coeffs[vid] = float(cand.cost)

            elif objective_type == OptimizationObjectiveType.MINIMIZE_RISK:
                risk_val = cand.risk_score if cand.risk_score is not None else 0.0
                coeffs[vid] = float(risk_val)

            elif objective_type == OptimizationObjectiveType.MINIMIZE_ROUTE_DEVIATION:
                # Deviation: 0.0 if preferred/baseline route, 1.0 if alternate
                is_baseline = cand.properties.get("is_baseline", False)
                coeffs[vid] = 0.0 if is_baseline else 1.0

            else:
                # Default delay
                time_val = cand.transit_time_hours if cand.transit_time_hours is not None else 0.0
                coeffs[vid] = float(time_val)

        return OptimizationObjective(
            objective_type=objective_type,
            direction=ObjectiveDirection.MINIMIZE,
            variable_coefficients=coeffs,
            offset=0.0,
            description=f"Explicit objective to {objective_type.value.lower().replace('_', ' ')}",
        )
