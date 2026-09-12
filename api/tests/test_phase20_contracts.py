"""Tests for Phase 20 Evaluation Contracts, Pydantic Models, and Fingerprinting."""

import pytest
from app.evaluation.contracts import (
    EvaluationCase,
    EvaluationDomain,
    EvaluationFailure,
    EvaluationMetric,
    EvaluationReport,
    EvaluationResult,
    EvaluationScore,
    EvaluationStatus,
    EvaluationSuiteType,
    DatasetCategory,
    compute_sha256,
)


def test_evaluation_case_creation_and_fingerprint():
    case = EvaluationCase(
        case_id="test-case-001",
        name="Test Routing Case",
        domain=EvaluationDomain.AGENT,
        category=DatasetCategory.NORMAL,
        description="Verify agent routing behavior",
        input_data={"event": "STRIKE"},
        expected_output={"next_node": "research"},
    )
    assert case.case_id == "test-case-001"
    assert case.domain == EvaluationDomain.AGENT
    assert case.suite_type == EvaluationSuiteType.AGENT_EVALUATION
    assert case.category == DatasetCategory.NORMAL


def test_evaluation_result_passed_and_fingerprint():
    result = EvaluationResult(
        case_id="test-case-001",
        status=EvaluationStatus.PASSED,
        actual_output={"next_node": "research"},
        passed_assertions=["matches_expected"],
        failed_assertions=[],
        execution_time_ms=12.5,
    )
    assert result.passed is True
    assert len(result.fingerprint) == 64


def test_evaluation_metric_serialization_and_validation():
    metric = EvaluationMetric(
        name="Agent Routing Accuracy",
        domain=EvaluationDomain.AGENT,
        value=0.985,
        numerator=197.0,
        denominator=200.0,
        sample_size=200,
        status=EvaluationStatus.PASSED,
    )
    dumped = metric.model_dump()
    assert dumped["value"] == 0.985
    assert dumped["sample_size"] == 200
    assert dumped["status"] == "PASSED"


def test_metric_nan_rejected():
    with pytest.raises(ValueError, match="finite number"):
        EvaluationMetric(
            name="InvalidMetric",
            domain=EvaluationDomain.ML,
            value=float("nan"),
            sample_size=10,
        )


def test_evaluation_score_domain_bounds():
    score = EvaluationScore(
        domain=EvaluationDomain.SECURITY,
        overall_score=1.0,
        status=EvaluationStatus.PASSED,
        sample_count=15,
        minimum_sample_met=True,
        summary="Perfect security invariant score",
    )
    assert score.overall_score == 1.0
    assert score.domain == EvaluationDomain.SECURITY


def test_compute_sha256_deterministic():
    payload1 = {"key": "value", "count": 42}
    payload2 = {"count": 42, "key": "value"}
    # JSON key sorting guarantees determinism
    assert compute_sha256(payload1) == compute_sha256(payload2)
