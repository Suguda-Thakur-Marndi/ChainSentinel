"""Input validation and security boundary checks for Phase 14 Optimization.

Enforces:
- Tenant isolation boundaries
- Hard resource bounds (variables, candidates, constraints)
- Data non-fabrication guarantees (no missing cost/capacity/demand/transit)
- Mathematical consistency
"""
from __future__ import annotations

from typing import List, Optional

from app.optimization.config import (
    HARD_MAX_CANDIDATES,
    HARD_MAX_CONSTRAINTS,
    HARD_MAX_OBJECTIVE_TERMS,
    HARD_MAX_VARIABLES,
)
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationRequest,
)
from app.optimization.errors import (
    OptimizationDataMissingError,
    OptimizationResourceLimitError,
    OptimizationTenantIsolationError,
    OptimizationValidationError,
)


class OptimizationValidator:
    """Validates optimization requests, problems, and candidate data."""

    @staticmethod
    def validate_request(
        request: OptimizationRequest,
        expected_organization_id: Optional[str] = None,
    ) -> None:
        """Validate request structure, tenant context, and resource bounds."""
        if not request.organization_id or not request.organization_id.strip():
            raise OptimizationValidationError("organization_id must not be empty")

        if expected_organization_id and request.organization_id != expected_organization_id:
            raise OptimizationTenantIsolationError(
                f"Tenant mismatch: request specifies organization '{request.organization_id}' "
                f"but context belongs to '{expected_organization_id}'"
            )

        if len(request.candidate_alternatives) > HARD_MAX_CANDIDATES:
            raise OptimizationResourceLimitError(
                f"Candidate alternatives count {len(request.candidate_alternatives)} "
                f"exceeds hard limit {HARD_MAX_CANDIDATES}"
            )

        # Validate candidate properties
        for cand in request.candidate_alternatives:
            if not cand.alternative_id or not cand.entity_id:
                raise OptimizationValidationError("Candidate alternatives must have alternative_id and entity_id")
            if cand.cost is not None and cand.cost < 0.0:
                raise OptimizationValidationError(f"Candidate '{cand.alternative_id}' has negative cost {cand.cost}")
            if cand.transit_time_hours is not None and cand.transit_time_hours < 0.0:
                raise OptimizationValidationError(
                    f"Candidate '{cand.alternative_id}' has negative transit time {cand.transit_time_hours}"
                )
            if cand.capacity is not None and cand.capacity < 0.0:
                raise OptimizationValidationError(
                    f"Candidate '{cand.alternative_id}' has negative capacity {cand.capacity}"
                )

        # Non-fabrication check for cost objective
        if request.objective_type == OptimizationObjectiveType.MINIMIZE_COST:
            for cand in request.candidate_alternatives:
                if cand.cost is None:
                    raise OptimizationDataMissingError(
                        f"Objective requires MINIMIZE_COST, but candidate alternative '{cand.alternative_id}' "
                        f"has no authoritative cost data. Cost must never be fabricated."
                    )

    @staticmethod
    def validate_problem(problem: OptimizationProblem) -> None:
        """Validate formulated mathematical problem before solver execution."""
        if len(problem.variables) > HARD_MAX_VARIABLES:
            raise OptimizationResourceLimitError(
                f"Variable count {len(problem.variables)} exceeds hard limit {HARD_MAX_VARIABLES}"
            )
        if len(problem.constraints) > HARD_MAX_CONSTRAINTS:
            raise OptimizationResourceLimitError(
                f"Constraint count {len(problem.constraints)} exceeds hard limit {HARD_MAX_CONSTRAINTS}"
            )
        if len(problem.objective.variable_coefficients) > HARD_MAX_OBJECTIVE_TERMS:
            raise OptimizationResourceLimitError(
                f"Objective terms {len(problem.objective.variable_coefficients)} "
                f"exceed hard limit {HARD_MAX_OBJECTIVE_TERMS}"
            )

        # Verify all variables in constraints and objective exist in problem.variables
        for cid, con in problem.constraints.items():
            for vid in con.variable_coefficients.keys():
                if vid not in problem.variables:
                    raise OptimizationValidationError(
                        f"Constraint '{cid}' references undeclared variable '{vid}'"
                    )

        for vid in problem.objective.variable_coefficients.keys():
            if vid not in problem.variables:
                raise OptimizationValidationError(
                    f"Objective references undeclared variable '{vid}'"
                )
