"""Golden evaluation test cases for Phase 14 OR-Tools Prescriptive Optimization (Phase 20)."""
from typing import List
from app.evaluation.contracts import DatasetCategory, EvaluationCase, EvaluationSuiteType


def get_optimization_evaluation_cases() -> List[EvaluationCase]:
    """Return golden test cases for solver status semantics, constraint satisfaction, and objective optimization."""
    return [
        EvaluationCase(
            case_id="opt-case-001",
            suite_type=EvaluationSuiteType.OPTIMIZATION_EVALUATION,
            category=DatasetCategory.NORMAL,
            name="Multi-Route Flow Cost Optimization",
            description="Optimal linear routing flow satisfying capacity constraints with minimum cost.",
            input_data={
                "demand": 1000,
                "routes": [
                    {"route_id": "r-air", "cost_per_unit": 12.0, "lead_time_days": 2, "capacity": 500},
                    {"route_id": "r-ocean", "cost_per_unit": 2.5, "lead_time_days": 18, "capacity": 800},
                    {"route_id": "r-rail", "cost_per_unit": 5.0, "lead_time_days": 9, "capacity": 400},
                ],
                "max_allowed_days": 20,
            },
            expected_output={
                "status": "OPTIMAL",
                "is_feasible": True,
                "total_cost": 3000.0,
                "allocation": {"r-ocean": 800, "r-rail": 200, "r-air": 0},
            },
            version="1.0.0",
            tags=["optimization", "linear_programming", "optimal"],
        ),
        EvaluationCase(
            case_id="opt-case-002",
            suite_type=EvaluationSuiteType.OPTIMIZATION_EVALUATION,
            category=DatasetCategory.BOUNDARY,
            name="Feasible vs Optimal Solver Status Delineation",
            description="When solver hits time limit with a candidate, status must be FEASIBLE, never OPTIMAL.",
            input_data={
                "solver_exit_condition": "TIME_LIMIT",
                "solution_found": True,
                "gap": 0.045,
            },
            expected_output={
                "reported_status": "FEASIBLE",
                "is_optimal": False,
                "violated_optimal_claim": False,
            },
            version="1.0.0",
            tags=["optimization", "solver_status", "invariants"],
        ),
        EvaluationCase(
            case_id="opt-case-003",
            suite_type=EvaluationSuiteType.OPTIMIZATION_EVALUATION,
            category=DatasetCategory.FAILURE,
            name="Infeasible Constraint Handling",
            description="Demanding 2000 units when total available capacity across all routes is 1700 must yield INFEASIBLE.",
            input_data={
                "demand": 2000,
                "routes": [
                    {"route_id": "r-1", "capacity": 1000},
                    {"route_id": "r-2", "capacity": 700},
                ],
            },
            expected_output={
                "status": "INFEASIBLE",
                "is_feasible": False,
                "candidate_count": 0,
            },
            version="1.0.0",
            tags=["optimization", "infeasible"],
        ),
        EvaluationCase(
            case_id="opt-case-004",
            suite_type=EvaluationSuiteType.OPTIMIZATION_EVALUATION,
            category=DatasetCategory.BOUNDARY,
            name="Unbounded Problem Rejection Invariant",
            description="Unbounded linear formulation must never be claimed as a valid optimal solution.",
            input_data={
                "solver_exit_condition": "UNBOUNDED",
                "solution_found": False,
            },
            expected_output={
                "reported_status": "UNBOUNDED",
                "is_optimal": False,
                "is_valid_solution": False,
            },
            version="1.0.0",
            tags=["optimization", "unbounded", "invariants"],
        ),
    ]
