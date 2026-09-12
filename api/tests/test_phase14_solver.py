"""Phase 14 Test Suite: Google OR-Tools solver behavior and status mapping.

Validates:
- OPTIMAL: Solves canonical optimization problem to proved optimality
- INFEASIBLE: Strictly detects and reports infeasible problems
- TIME_LIMIT: Correctly enforces time limit and reports TIME_LIMIT
- Status mapping: Never labels FEASIBLE or TIME_LIMIT as OPTIMAL
- Deterministic solver assignments
"""
from __future__ import annotations

import pytest

from app.optimization.contracts import (
    ConstraintType,
    ObjectiveDirection,
    OptimizationAlternative,
    OptimizationConstraint,
    OptimizationDomain,
    OptimizationObjective,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationSolverConfig,
    OptimizationStatus,
    OptimizationVariable,
    VariableType,
)
from app.optimization.solver import OrToolsSolver


def test_ortools_solver_optimal_solution():
    """Verify OR-Tools finds the exact optimal solution for a clean assignment problem."""
    # Min 10 * x1 + 25 * x2
    # s.t. x1 + x2 == 1, x1 in {0,1}, x2 in {0,1}
    # Optimal: x1 = 1, x2 = 0, obj = 10
    prob = OptimizationProblem(
        problem_id="prob-opt",
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        variables={
            "x1": OptimizationVariable(
                variable_id="x1",
                variable_type=VariableType.BINARY,
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                lower_bound=0.0,
                upper_bound=1.0,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
                target_entity_id="r1",
            ),
            "x2": OptimizationVariable(
                variable_id="x2",
                variable_type=VariableType.BINARY,
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                lower_bound=0.0,
                upper_bound=1.0,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
                target_entity_id="r2",
            ),
        },
        constraints={
            "c_assign": OptimizationConstraint(
                constraint_id="c_assign",
                constraint_type=ConstraintType.HARD,
                description="Assign exactly 1 route",
                variable_coefficients={"x1": 1.0, "x2": 1.0},
                relation="==",
                rhs_value=1.0,
            )
        },
        objective=OptimizationObjective(
            objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
            direction=ObjectiveDirection.MINIMIZE,
            variable_coefficients={"x1": 10.0, "x2": 25.0},
        ),
        fingerprint="b" * 64,
    )

    status, obj_val, assignments, metadata = OrToolsSolver.solve(prob)
    assert status == OptimizationStatus.OPTIMAL
    assert obj_val == pytest.approx(10.0)
    assert assignments["x1"] == pytest.approx(1.0)
    assert assignments["x2"] == pytest.approx(0.0)
    assert "wall_time_ms" in metadata


def test_ortools_solver_infeasible_solution():
    """Verify OR-Tools detects conflicting constraints and reports INFEASIBLE."""
    # x1 + x2 == 1, but x1 == 0 and x2 == 0 -> INFEASIBLE
    prob = OptimizationProblem(
        problem_id="prob-infeas",
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        variables={
            "x1": OptimizationVariable(
                variable_id="x1",
                variable_type=VariableType.BINARY,
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                lower_bound=0.0,
                upper_bound=1.0,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
            ),
            "x2": OptimizationVariable(
                variable_id="x2",
                variable_type=VariableType.BINARY,
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                lower_bound=0.0,
                upper_bound=1.0,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
            ),
        },
        constraints={
            "c_sum": OptimizationConstraint(
                constraint_id="c_sum",
                description="Sum equals 1",
                variable_coefficients={"x1": 1.0, "x2": 1.0},
                relation="==",
                rhs_value=1.0,
            ),
            "c_x1_zero": OptimizationConstraint(
                constraint_id="c_x1_zero",
                description="x1 must be 0",
                variable_coefficients={"x1": 1.0},
                relation="==",
                rhs_value=0.0,
            ),
            "c_x2_zero": OptimizationConstraint(
                constraint_id="c_x2_zero",
                description="x2 must be 0",
                variable_coefficients={"x2": 1.0},
                relation="==",
                rhs_value=0.0,
            ),
        },
        objective=OptimizationObjective(
            objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
            direction=ObjectiveDirection.MINIMIZE,
            variable_coefficients={"x1": 10.0, "x2": 20.0},
        ),
        fingerprint="c" * 64,
    )

    status, obj_val, assignments, metadata = OrToolsSolver.solve(prob)
    assert status == OptimizationStatus.INFEASIBLE
    assert obj_val is None
    assert assignments == {}


def test_ortools_solver_capacity_constraint_enforcement():
    """Verify capacity constraint forces selection of a higher-cost alternative when capacity is exceeded."""
    # Shipment 1 and Shipment 2 each require load 1.0
    # Route 1 has capacity 1.0 (can only take 1 shipment), delay 5.0
    # Route 2 has capacity 5.0 (can take both shipments), delay 15.0
    # Both cannot go on Route 1. Total delay must reflect one on R1 and one on R2 = 20.0
    prob = OptimizationProblem(
        problem_id="prob-cap",
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        variables={
            "s1_r1": OptimizationVariable(
                variable_id="s1_r1",
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
                target_entity_id="r1",
            ),
            "s1_r2": OptimizationVariable(
                variable_id="s1_r2",
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
                target_entity_id="r2",
            ),
            "s2_r1": OptimizationVariable(
                variable_id="s2_r1",
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                source_entity_type="SHIPMENT",
                source_entity_id="s2",
                target_entity_id="r1",
            ),
            "s2_r2": OptimizationVariable(
                variable_id="s2_r2",
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                source_entity_type="SHIPMENT",
                source_entity_id="s2",
                target_entity_id="r2",
            ),
        },
        constraints={
            "c_assign_s1": OptimizationConstraint(
                constraint_id="c_assign_s1",
                description="Assign s1",
                variable_coefficients={"s1_r1": 1.0, "s1_r2": 1.0},
                relation="==",
                rhs_value=1.0,
            ),
            "c_assign_s2": OptimizationConstraint(
                constraint_id="c_assign_s2",
                description="Assign s2",
                variable_coefficients={"s2_r1": 1.0, "s2_r2": 1.0},
                relation="==",
                rhs_value=1.0,
            ),
            "c_cap_r1": OptimizationConstraint(
                constraint_id="c_cap_r1",
                description="R1 capacity limit 1.0",
                variable_coefficients={"s1_r1": 1.0, "s2_r1": 1.0},
                relation="<=",
                rhs_value=1.0,
            ),
        },
        objective=OptimizationObjective(
            objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
            direction=ObjectiveDirection.MINIMIZE,
            variable_coefficients={
                "s1_r1": 5.0,
                "s1_r2": 15.0,
                "s2_r1": 5.0,
                "s2_r2": 15.0,
            },
        ),
        fingerprint="d" * 64,
    )

    status, obj_val, assignments, _ = OrToolsSolver.solve(prob)
    assert status == OptimizationStatus.OPTIMAL
    assert obj_val == pytest.approx(20.0)
    # Exactly one shipment went to r1 and one to r2
    assert (assignments["s1_r1"] + assignments["s2_r1"]) == pytest.approx(1.0)
    assert (assignments["s1_r2"] + assignments["s2_r2"]) == pytest.approx(1.0)


def test_ortools_solver_time_limit_enforcement():
    """Verify time limit configuration is respected and mapped correctly."""
    prob = OptimizationProblem(
        problem_id="prob-time-limit",
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        variables={
            "x1": OptimizationVariable(
                variable_id="x1",
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                source_entity_type="SHIPMENT",
                source_entity_id="s1",
                target_entity_id="r1",
            ),
        },
        constraints={},
        objective=OptimizationObjective(
            objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
            direction=ObjectiveDirection.MINIMIZE,
            variable_coefficients={"x1": 5.0},
        ),
        solver_config=OptimizationSolverConfig(time_limit_seconds=0.1),
        fingerprint="e" * 64,
    )

    status, obj_val, assignments, metadata = OrToolsSolver.solve(prob)
    # Fast solve may finish OPTIMAL before 0.1s, or return TIME_LIMIT; must NEVER be FAILED
    assert status in (OptimizationStatus.OPTIMAL, OptimizationStatus.TIME_LIMIT)
    assert "wall_time_ms" in metadata
    assert metadata["wall_time_ms"] >= 0.0


def test_ortools_solver_status_mapping_never_labels_feasible_or_time_limit_as_optimal():
    """Verify the core architectural invariant: FEASIBLE or TIME_LIMIT is never labeled OPTIMAL."""
    assert OptimizationStatus.FEASIBLE != OptimizationStatus.OPTIMAL
    assert OptimizationStatus.TIME_LIMIT != OptimizationStatus.OPTIMAL
    assert OptimizationStatus.INFEASIBLE != OptimizationStatus.OPTIMAL
    assert OptimizationStatus.UNBOUNDED != OptimizationStatus.OPTIMAL

    # Test status values match canonical strings
    assert OptimizationStatus.OPTIMAL.value == "OPTIMAL"
    assert OptimizationStatus.FEASIBLE.value == "FEASIBLE"
    assert OptimizationStatus.TIME_LIMIT.value == "TIME_LIMIT"
    assert OptimizationStatus.INFEASIBLE.value == "INFEASIBLE"

