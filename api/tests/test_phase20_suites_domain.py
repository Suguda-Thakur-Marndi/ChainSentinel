"""Tests for ML, Digital Twin, Simulation, Optimization, and Decision Suites (Phase 20)."""

import pytest
from app.evaluation.contracts import EvaluationStatus, EvaluationSuiteType
from app.evaluation.datasets.registry import DatasetRegistry
from app.evaluation.suites import (
    MLEvaluationSuite,
    DigitalTwinEvaluationSuite,
    SimulationEvaluationSuite,
    OptimizationEvaluationSuite,
    DecisionEvaluationSuite,
)


def test_ml_evaluation_suite_run():
    suite = MLEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.ML_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    assert report.failed_cases == 0
    assert len(report.metrics) >= 3


def test_digital_twin_evaluation_suite_run():
    suite = DigitalTwinEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.DIGITAL_TWIN_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    assert report.total_cases >= 2


def test_simulation_evaluation_suite_non_mutation():
    suite = SimulationEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.SIMULATION_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Verify SIMULATED evidence does not escalate to REAL
    for r in report.results:
        assert r.passed is True


def test_optimization_evaluation_suite_solver_semantics():
    suite = OptimizationEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.OPTIMIZATION_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Confirms INFEASIBLE != FAILED and FEASIBLE != OPTIMAL
    assert report.failed_cases == 0


def test_decision_evaluation_suite_consistency():
    suite = DecisionEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.DECISION_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    assert report.total_cases >= 2
