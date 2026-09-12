"""Tests for Phase 20 MetricEngine (Deterministic Calculations & Not-Available Rules)."""

import pytest
from app.evaluation.contracts import EvaluationDomain, EvaluationStatus
from app.evaluation.metrics import MetricEngine


def test_metric_engine_accuracy_calculation():
    actual = ["research", "risk_engine", "decision", "action"]
    expected = ["research", "risk_engine", "decision", "action"]
    metric = MetricEngine.calculate_accuracy(
        actual=actual,
        expected=expected,
        name="Routing Accuracy",
        domain=EvaluationDomain.AGENT,
    )
    assert metric.value == 1.0
    assert metric.status == EvaluationStatus.PASSED
    assert metric.sample_size == 4


def test_metric_engine_accuracy_with_errors():
    actual = ["research", "wrong_node", "decision", "action"]
    expected = ["research", "risk_engine", "decision", "action"]
    metric = MetricEngine.calculate_accuracy(
        actual=actual,
        expected=expected,
        name="Routing Accuracy",
        domain=EvaluationDomain.AGENT,
    )
    assert metric.value == 0.75
    assert metric.status == EvaluationStatus.FAILED


def test_metric_engine_insufficient_samples_emits_not_available():
    # When samples < min_samples, value must be None and status must be NOT_AVAILABLE
    metric = MetricEngine.calculate_accuracy(
        actual=["node_a"],
        expected=["node_a"],
        min_samples=5,
        name="Small Sample Accuracy",
    )
    assert metric.status == EvaluationStatus.NOT_AVAILABLE
    assert metric.value is None
    assert metric.sample_size == 1


def test_metric_engine_compute_accuracy_helper():
    metric = MetricEngine.compute_accuracy(
        name="Test Accuracy",
        correct=8,
        total=10,
        domain=EvaluationDomain.AGENT,
    )
    assert metric.value == 0.8
    assert metric.status == EvaluationStatus.FAILED  # Since 0.8 < 1.0


def test_metric_engine_compute_rate_metric():
    metric = MetricEngine.compute_rate_metric(
        name="Success Rate",
        numerator=15.0,
        denominator=20.0,
        domain=EvaluationDomain.ACTION,
    )
    assert metric.value == 0.75
    assert metric.sample_size == 20
    assert metric.status == EvaluationStatus.PASSED


def test_metric_engine_compute_mae_and_rmse():
    preds = [10.0, 20.0, 30.0]
    acts = [12.0, 19.0, 28.0]
    mae_metric = MetricEngine.compute_mae(preds, acts, domain=EvaluationDomain.ML)
    assert mae_metric.value == round((2.0 + 1.0 + 2.0) / 3, 4)
    assert mae_metric.status == EvaluationStatus.PASSED

    rmse_metric = MetricEngine.compute_rmse(preds, acts, domain=EvaluationDomain.ML)
    assert rmse_metric.value is not None
    assert rmse_metric.status == EvaluationStatus.PASSED


def test_metric_engine_aggregate_domain_score():
    m1 = MetricEngine.compute_accuracy("M1", 10, 10, domain=EvaluationDomain.RISK)
    m2 = MetricEngine.compute_accuracy("M2", 9, 10, domain=EvaluationDomain.RISK)
    score = MetricEngine.aggregate_domain_score(EvaluationDomain.RISK, [m1, m2])
    assert score.overall_score is not None
    assert 0.0 <= score.overall_score <= 1.0
    assert score.sample_count == 2
