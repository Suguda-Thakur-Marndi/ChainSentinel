"""Mathematical problem model assembly for RiskWise Optimization Subsystem (Phase 14).

Constructs and canonicalizes OptimizationProblem objects with deterministic ordering
and cryptographic SHA-256 fingerprints.
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from app.optimization.config import DEFAULT_SOLVER_TIMEOUT_SECONDS
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationConstraint,
    OptimizationDomain,
    OptimizationObjective,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationSolverConfig,
    OptimizationVariable,
)
from app.optimization.fingerprints import compute_problem_fingerprint
from app.optimization.validators import OptimizationValidator


class ModelBuilder:
    """Builds and canonicalizes complete OptimizationProblem formulations."""

    @staticmethod
    def create_problem(
        organization_id: str,
        domain: OptimizationDomain,
        variables: Dict[str, OptimizationVariable],
        constraints: Dict[str, OptimizationConstraint],
        objective: OptimizationObjective,
        candidates: List[OptimizationAlternative],
        solver_config: Optional[OptimizationSolverConfig] = None,
    ) -> OptimizationProblem:
        """Create and validate a canonicalized OptimizationProblem."""
        cfg = solver_config or OptimizationSolverConfig(
            time_limit_seconds=DEFAULT_SOLVER_TIMEOUT_SECONDS
        )

        sorted_variables = {k: variables[k] for k in sorted(variables.keys())}
        sorted_constraints = {k: constraints[k] for k in sorted(constraints.keys())}
        sorted_candidates = sorted(candidates, key=lambda c: c.alternative_id)

        problem_fp = compute_problem_fingerprint(
            organization_id=organization_id,
            domain=domain.value,
            variable_ids=list(sorted_variables.keys()),
            constraint_ids=list(sorted_constraints.keys()),
            objective_dict=objective.model_dump(mode="json"),
        )

        problem_id = f"prob_{problem_fp[:16]}"

        problem = OptimizationProblem(
            problem_id=problem_id,
            organization_id=organization_id,
            domain=domain,
            variables=sorted_variables,
            constraints=sorted_constraints,
            objective=objective,
            candidates=sorted_candidates,
            solver_config=cfg,
            fingerprint=problem_fp,
        )

        OptimizationValidator.validate_problem(problem)
        return problem
