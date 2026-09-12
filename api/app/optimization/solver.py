"""Google OR-Tools solver integration for RiskWise Optimization Subsystem (Phase 14).

Executes deterministic mathematical optimization using OR-Tools linear solver (pywraplp).
Enforces:
- Hard solver time limits to prevent infinite execution
- Strict mapping of solver outcomes: OPTIMAL, FEASIBLE, INFEASIBLE, UNBOUNDED, TIME_LIMIT, NOT_AVAILABLE, FAILED
- Safe fallback when solver backend is unavailable
- Zero fabrication of variable values or objectives
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

from app.optimization.contracts import (
    ObjectiveDirection,
    OptimizationProblem,
    OptimizationStatus,
    VariableType,
)
from app.optimization.errors import OptimizationSolverUnavailableError

logger = logging.getLogger("riskwise.optimization.solver")


class OrToolsSolver:
    """Wrapper around Google OR-Tools pywraplp linear solver."""

    @staticmethod
    def solve(
        problem: OptimizationProblem,
    ) -> Tuple[OptimizationStatus, Optional[float], Dict[str, float], Dict[str, Any]]:
        """Solve canonical OptimizationProblem using Google OR-Tools.

        Returns:
            (status, objective_value, variable_assignments, solver_metadata)
        """
        try:
            from ortools.linear_solver import pywraplp  # type: ignore
        except ImportError:
            logger.warning("Google OR-Tools is not installed or import failed.")
            return (
                OptimizationStatus.NOT_AVAILABLE,
                None,
                {},
                {"reason": "OR-Tools library not available"},
            )

        start_time = time.perf_counter()
        timeout_seconds = problem.solver_config.time_limit_seconds

        # Create solver instance
        solver = pywraplp.Solver.CreateSolver("CBC")
        if not solver:
            # Fallback to SCIP or GLOP if CBC is not compiled in
            solver = pywraplp.Solver.CreateSolver("SCIP")
        if not solver:
            return (
                OptimizationStatus.NOT_AVAILABLE,
                None,
                {},
                {"reason": "No supported OR-Tools MIP solver backend found (tried CBC, SCIP)"},
            )

        # Set time limit in milliseconds
        time_limit_ms = int(timeout_seconds * 1000)
        solver.set_time_limit(time_limit_ms)

        # 1. Instantiate variables
        ortools_vars: Dict[str, Any] = {}
        for vid, var in problem.variables.items():
            if var.variable_type == VariableType.BINARY:
                ortools_vars[vid] = solver.BoolVar(vid)
            elif var.variable_type == VariableType.INTEGER:
                ortools_vars[vid] = solver.IntVar(var.lower_bound, var.upper_bound, vid)
            else:
                ortools_vars[vid] = solver.NumVar(var.lower_bound, var.upper_bound, vid)

        # 2. Instantiate constraints
        infinity = solver.infinity()
        for cid, con in problem.constraints.items():
            if con.relation == "==":
                row = solver.RowConstraint(con.rhs_value, con.rhs_value, cid)
            elif con.relation == "<=":
                row = solver.RowConstraint(-infinity, con.rhs_value, cid)
            elif con.relation == ">=":
                row = solver.RowConstraint(con.rhs_value, infinity, cid)
            else:
                continue

            for vid, coeff in con.variable_coefficients.items():
                if vid in ortools_vars:
                    row.SetCoefficient(ortools_vars[vid], float(coeff))

        # 3. Instantiate objective
        objective = solver.Objective()
        for vid, coeff in problem.objective.variable_coefficients.items():
            if vid in ortools_vars:
                objective.SetCoefficient(ortools_vars[vid], float(coeff))

        if problem.objective.direction == ObjectiveDirection.MAXIMIZE:
            objective.SetMaximization()
        else:
            objective.SetMinimization()

        # 4. Execute solve
        try:
            solver_status = solver.Solve()
        except Exception as e:
            logger.error(f"Unexpected error in solver.Solve(): {e}", exc_info=True)
            return (
                OptimizationStatus.FAILED,
                None,
                {},
                {"error": str(e)},
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        metadata = {
            "wall_time_ms": elapsed_ms,
            "solver_wall_time_reported_ms": solver.wall_time(),
            "iterations": solver.iterations(),
            "nodes": solver.nodes(),
        }

        # 5. Map solver status
        if solver_status == pywraplp.Solver.OPTIMAL:
            status = OptimizationStatus.OPTIMAL
            obj_val = float(objective.Value())
            assignments = {
                vid: float(ortools_vars[vid].solution_value())
                for vid in problem.variables.keys()
            }
            return status, obj_val, assignments, metadata

        elif solver_status == pywraplp.Solver.FEASIBLE:
            status = OptimizationStatus.FEASIBLE
            obj_val = float(objective.Value())
            assignments = {
                vid: float(ortools_vars[vid].solution_value())
                for vid in problem.variables.keys()
            }
            return status, obj_val, assignments, metadata

        elif solver_status == pywraplp.Solver.INFEASIBLE:
            return OptimizationStatus.INFEASIBLE, None, {}, metadata

        elif solver_status == pywraplp.Solver.UNBOUNDED:
            return OptimizationStatus.UNBOUNDED, None, {}, metadata

        elif solver_status == pywraplp.Solver.NOT_SOLVED:
            # Check if wall time exceeded limit
            if elapsed_ms >= (timeout_seconds * 950.0):
                return OptimizationStatus.TIME_LIMIT, None, {}, metadata
            return OptimizationStatus.FAILED, None, {}, metadata

        else:
            return OptimizationStatus.FAILED, None, {}, metadata
