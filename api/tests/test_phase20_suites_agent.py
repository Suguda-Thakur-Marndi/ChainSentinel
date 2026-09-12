"""Tests for Agent, Research, Risk, RAG, and Claude Evaluation Suites (Phase 20)."""

import pytest
from app.evaluation.contracts import EvaluationStatus, EvaluationSuiteType
from app.evaluation.datasets.registry import DatasetRegistry
from app.evaluation.suites import (
    AgentEvaluationSuite,
    ResearchEvaluationSuite,
    RiskEvaluationSuite,
    RAGEvaluationSuite,
    ClaudeEvaluationSuite,
)


def test_agent_evaluation_suite_run():
    suite = AgentEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.AGENT_EVALUATION)
    report = suite.run(dataset)
    assert report.status in [EvaluationStatus.PASSED, EvaluationStatus.PARTIAL]
    assert report.total_cases == len(dataset.cases)
    assert len(report.metrics) >= 1
    assert len(report.result_fingerprint) == 64


def test_research_evaluation_suite_run():
    suite = ResearchEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.RESEARCH_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    assert report.total_cases >= 4
    assert len(report.metrics) >= 3


def test_risk_evaluation_suite_deterministic():
    suite = RiskEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.RISK_EVALUATION)
    report1 = suite.run(dataset)
    report2 = suite.run(dataset)
    # Bit-for-bit identical result fingerprints
    assert report1.status == EvaluationStatus.PASSED
    assert report1.result_fingerprint == report2.result_fingerprint


def test_rag_evaluation_suite_injection_defense():
    suite = RAGEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.RAG_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    assert report.failed_cases == 0


def test_claude_evaluation_suite_non_authoritative_boundary():
    suite = ClaudeEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.CLAUDE_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Verify Claude never usurps authority
    assert all(r.passed for r in report.results)
