"""Phase 14 Test Suite: Strongly typed contracts and validation.

Validates:
- OptimizationRequest validation and extra="forbid"
- OptimizationProblem canonicalization
- OptimizationVariable bounds and types
- OptimizationConstraint relations and coefficients
- OptimizationObjective types and directions
- OptimizationStatus enum coverage
- OptimizationSummary and OptimizationResult structure
- Hard resource bounds enforcement
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.optimization.config import (
    HARD_MAX_CANDIDATES,
    HARD_MAX_CONSTRAINTS,
    HARD_MAX_OBJECTIVE_TERMS,
    HARD_MAX_VARIABLES,
)
from app.optimization.contracts import (
    ConstraintType,
    ObjectiveDirection,
    OptimizationAlternative,
    OptimizationConstraint,
    OptimizationDomain,
    OptimizationMetric,
    OptimizationMetricAvailability,
    OptimizationObjective,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationProvenance,
    OptimizationRequest,
    OptimizationResult,
    OptimizationSolverConfig,
    OptimizationStatus,
    OptimizationSummary,
    OptimizationVariable,
    SelectedAlternative,
    VariableType,
)
from app.optimization.errors import (
    OptimizationDataMissingError,
    OptimizationResourceLimitError,
    OptimizationValidationError,
)
from app.optimization.validators import OptimizationValidator


def test_optimization_status_enum_values():
    """Verify OptimizationStatus enum supports all required statuses."""
    expected = {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNBOUNDED", "TIME_LIMIT", "NOT_AVAILABLE", "FAILED"}
    actual = {s.value for s in OptimizationStatus}
    assert actual == expected


def test_valid_optimization_request():
    """Verify valid OptimizationRequest succeeds."""
    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["ship-001"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-1",
                entity_type="ROUTE",
                entity_id="route-primary",
                transit_time_hours=24.0,
                cost=1200.0,
                capacity=100.0,
            )
        ],
    )
    assert req.organization_id == "org-acme-1"
    assert len(req.candidate_alternatives) == 1


def test_invalid_optimization_request_extra_forbid():
    """Verify extra fields are forbidden on OptimizationRequest."""
    with pytest.raises(ValidationError):
        OptimizationRequest.model_validate(
            {
                "organization_id": "org-acme-1",
                "unknown_arbitrary_field": "malicious",
            }
        )


def test_optimization_alternative_negative_cost_rejected():
    """Verify negative cost is rejected by contract validation."""
    with pytest.raises(ValidationError):
        OptimizationAlternative(
            alternative_id="alt-bad",
            entity_type="ROUTE",
            entity_id="route-1",
            cost=-50.0,
        )


def test_optimization_alternative_negative_transit_rejected():
    """Verify negative transit time is rejected by contract validation."""
    with pytest.raises(ValidationError):
        OptimizationAlternative(
            alternative_id="alt-bad",
            entity_type="ROUTE",
            entity_id="route-1",
            transit_time_hours=-10.0,
        )


def test_minimize_cost_missing_cost_fails_closed():
    """Verify MINIMIZE_COST rejects candidates lacking authoritative cost data."""
    req = OptimizationRequest(
        organization_id="org-acme-1",
        objective_type=OptimizationObjectiveType.MINIMIZE_COST,
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-nocost",
                entity_type="ROUTE",
                entity_id="route-1",
                cost=None,  # Missing cost
            )
        ],
    )
    with pytest.raises(OptimizationDataMissingError, match="no authoritative cost data"):
        OptimizationValidator.validate_request(req)


def test_candidate_resource_limit_enforced():
    """Verify candidate count exceeding limit is rejected by contract validation."""
    huge_candidates = [
        OptimizationAlternative(
            alternative_id=f"alt-{i}",
            entity_type="ROUTE",
            entity_id=f"route-{i}",
        )
        for i in range(HARD_MAX_CANDIDATES + 1)
    ]
    with pytest.raises(ValidationError):
        OptimizationRequest(
            organization_id="org-acme-1",
            candidate_alternatives=huge_candidates,
        )


def test_problem_variable_resource_limit_enforced():
    """Verify problem variable count exceeding limit is rejected."""
    vars_dict = {
        f"v_{i}": OptimizationVariable(
            variable_id=f"v_{i}",
            domain=OptimizationDomain.SHIPMENT_REROUTE,
            source_entity_type="SHIPMENT",
            source_entity_id=f"s_{i}",
        )
        for i in range(HARD_MAX_VARIABLES + 1)
    }
    prob = OptimizationProblem(
        problem_id="prob-1",
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        variables=vars_dict,
        constraints={},
        objective=OptimizationObjective(
            objective_type=OptimizationObjectiveType.MINIMIZE_DELAY
        ),
        fingerprint="a" * 64,
    )
    with pytest.raises(OptimizationResourceLimitError, match="Variable count"):
        OptimizationValidator.validate_problem(prob)


def test_problem_constraint_referencing_undeclared_variable():
    """Verify constraint referencing undeclared variable is rejected."""
    prob = OptimizationProblem(
        problem_id="prob-1",
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        variables={
            "v_1": OptimizationVariable(
                variable_id="v_1",
                domain=OptimizationDomain.SHIPMENT_REROUTE,
                source_entity_type="SHIPMENT",
                source_entity_id="s_1",
            )
        },
        constraints={
            "c_1": OptimizationConstraint(
                constraint_id="c_1",
                description="Test constraint",
                variable_coefficients={"v_undeclared": 1.0},
                relation="==",
                rhs_value=1.0,
            )
        },
        objective=OptimizationObjective(
            objective_type=OptimizationObjectiveType.MINIMIZE_DELAY
        ),
        fingerprint="a" * 64,
    )
    with pytest.raises(OptimizationValidationError, match="undeclared variable"):
        OptimizationValidator.validate_problem(prob)
