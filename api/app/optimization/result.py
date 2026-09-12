"""Optimization result assembly and baseline comparative metric calculation.

Computes:
- Selected candidate alternatives from solver variable assignments
- Comparative baseline vs optimized metrics (delay, cost, risk)
- Cryptographic result fingerprints
- Strict non-fabrication handling (missing baseline/cost remains NOT_AVAILABLE)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationMetric,
    OptimizationMetricAvailability,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationProvenance,
    OptimizationResult,
    OptimizationStatus,
    OptimizationSummary,
    SelectedAlternative,
)
from app.optimization.fingerprints import compute_result_fingerprint

logger = logging.getLogger("riskwise.optimization.result")


class ResultBuilder:
    """Assembles final OptimizationResult with strictly validated comparative metrics."""

    @staticmethod
    def build_result(
        problem: OptimizationProblem,
        status: OptimizationStatus,
        objective_value: Optional[float],
        variable_assignments: Dict[str, float],
        solver_metadata: Dict[str, Any],
        provenance: OptimizationProvenance,
        request_fingerprint: str,
        duration_ms: float,
        baseline_metrics: Optional[Dict[str, float]] = None,
        failure_reason: Optional[str] = None,
    ) -> OptimizationResult:
        """Assemble complete immutable OptimizationResult."""
        selected_alts: List[SelectedAlternative] = []
        cand_map = {c.entity_id: c for c in problem.candidates}

        # 1. Identify selected alternatives
        if status in (OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE):
            for vid, val in sorted(variable_assignments.items()):
                if val >= 0.5:  # Binary selected threshold
                    var = problem.variables.get(vid)
                    if not var:
                        continue
                    cand = cand_map.get(var.target_entity_id or "")
                    selected_alts.append(
                        SelectedAlternative(
                            entity_type=var.target_entity_type or "UNKNOWN",
                            entity_id=var.target_entity_id or "",
                            variable_id=vid,
                            assigned_value=round(val, 4),
                            associated_shipment_id=var.source_entity_id if var.source_entity_type == "SHIPMENT" else None,
                            properties=cand.properties if cand else {},
                        )
                    )

        selected_alt_ids = [sa.entity_id for sa in selected_alts]

        # 2. Result fingerprint
        result_fp = compute_result_fingerprint(
            optimization_id=problem.problem_id,
            status=status.value,
            objective_value=objective_value,
            variable_assignments=variable_assignments,
            selected_alternative_ids=selected_alt_ids,
        )

        # 3. Formulate comparative metrics
        metrics: Dict[str, OptimizationMetric] = {}
        base_m = baseline_metrics or {}

        # Delay metric
        if problem.objective.objective_type == OptimizationObjectiveType.MINIMIZE_DELAY:
            opt_delay = objective_value
            base_delay = base_m.get("baseline_delay_hours")
            delta = (opt_delay - base_delay) if (opt_delay is not None and base_delay is not None) else None
            metrics["delay_hours"] = OptimizationMetric(
                metric_name="total_transit_delay_hours",
                baseline_value=base_delay,
                optimized_value=opt_delay,
                delta=delta,
                unit="HOURS",
                availability=OptimizationMetricAvailability.AVAILABLE
                if opt_delay is not None
                else OptimizationMetricAvailability.NOT_AVAILABLE,
            )

        # Cost metric
        if problem.objective.objective_type == OptimizationObjectiveType.MINIMIZE_COST:
            opt_cost = objective_value
            base_cost = base_m.get("baseline_cost")
            delta = (opt_cost - base_cost) if (opt_cost is not None and base_cost is not None) else None
            metrics["total_cost"] = OptimizationMetric(
                metric_name="total_transport_cost",
                baseline_value=base_cost,
                optimized_value=opt_cost,
                delta=delta,
                unit="USD",
                availability=OptimizationMetricAvailability.AVAILABLE
                if opt_cost is not None
                else OptimizationMetricAvailability.NOT_AVAILABLE,
            )

        # Risk metric
        if problem.objective.objective_type == OptimizationObjectiveType.MINIMIZE_RISK:
            opt_risk = objective_value
            base_risk = base_m.get("baseline_risk")
            delta = (opt_risk - base_risk) if (opt_risk is not None and base_risk is not None) else None
            metrics["risk_score"] = OptimizationMetric(
                metric_name="network_risk_score",
                baseline_value=base_risk,
                optimized_value=opt_risk,
                delta=delta,
                unit="SCORE_0_100",
                availability=OptimizationMetricAvailability.AVAILABLE
                if opt_risk is not None
                else OptimizationMetricAvailability.NOT_AVAILABLE,
            )

        # 4. Formulate summary
        summary = OptimizationSummary(
            optimization_id=problem.problem_id,
            organization_id=problem.organization_id,
            domain=problem.domain,
            status=status,
            objective_type=problem.objective.objective_type,
            objective_value=objective_value,
            selected_alternatives_count=len(selected_alts),
            total_variables=len(problem.variables),
            total_constraints=len(problem.constraints),
            solver_wall_time_ms=solver_metadata.get("wall_time_ms", 0.0),
            request_fingerprint=request_fingerprint,
            result_fingerprint=result_fp,
        )

        return OptimizationResult(
            optimization_id=problem.problem_id,
            organization_id=problem.organization_id,
            domain=problem.domain,
            status=status,
            objective=problem.objective,
            objective_value=objective_value,
            selected_alternatives=selected_alts,
            variable_assignments=variable_assignments,
            constraint_outcomes={},
            metrics=metrics,
            summary=summary,
            solver_metadata=solver_metadata,
            provenance=provenance,
            request_fingerprint=request_fingerprint,
            result_fingerprint=result_fp,
            executed_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            failure_reason=failure_reason,
        )
