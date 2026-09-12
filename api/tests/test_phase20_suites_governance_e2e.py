"""Tests for Approval, Action, Verification, End-to-End, and Security Suites (Phase 20)."""

import pytest
from app.evaluation.contracts import EvaluationStatus, EvaluationSuiteType
from app.evaluation.datasets.registry import DatasetRegistry
from app.evaluation.suites import (
    ApprovalEvaluationSuite,
    ActionEvaluationSuite,
    VerificationEvaluationSuite,
    EndToEndEvaluationSuite,
    SecurityEvaluationSuite,
)


def test_approval_evaluation_suite_human_gate():
    suite = ApprovalEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.APPROVAL_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Confirms LLM/agent cannot approve decisions
    assert report.failed_cases == 0


def test_action_evaluation_suite_allowlist_and_idempotency():
    suite = ActionEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.ACTION_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Confirms SUBMITTED != VERIFIED
    assert report.failed_cases == 0


def test_verification_evaluation_suite_evidence_precedence():
    suite = VerificationEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.VERIFICATION_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Confirms SIMULATED cannot verify real-world
    assert report.failed_cases == 0


def test_end_to_end_evaluation_suite_lifecycle():
    suite = EndToEndEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.END_TO_END_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    assert report.total_cases >= 3


def test_security_evaluation_suite_all_invariants():
    suite = SecurityEvaluationSuite()
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.SECURITY_EVALUATION)
    report = suite.run(dataset)
    assert report.status == EvaluationStatus.PASSED
    # Every security invariant check must pass (no failures)
    assert report.failed_cases == 0
    assert report.total_cases >= 7
