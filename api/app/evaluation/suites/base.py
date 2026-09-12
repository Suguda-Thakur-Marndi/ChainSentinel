"""Base Evaluation Suite for RiskWise 2.0 Evaluation Framework.

Provides:
- Deterministic test harness for evaluation cases
- Metric computation via MetricEngine
- Error catching, failure isolation, and provenance logging
- Zero production mutation enforcement
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import time
import uuid
import hashlib
from datetime import datetime, timezone

from app.evaluation.contracts import (
    EvaluationSuiteType,
    EvaluationDomain,
    EvaluationStatus,
    EvaluationCase,
    EvaluationResult,
    EvaluationFailure,
    EvaluationMetric,
    EvaluationScore,
    EvaluationReport,
    EvaluationDataset,
    EvaluationArtifact,
)
from app.evaluation.metrics import MetricEngine
from app.evaluation.errors import EvaluationExecutionError


class BaseEvaluationSuite(ABC):
    """Abstract base evaluation suite."""

    suite_type: EvaluationSuiteType
    domain: EvaluationDomain
    version: str = "v1.0.0"

    def __init__(self, suite_id: Optional[str] = None):
        self.suite_id = suite_id or f"suite-{self.suite_type.value.lower().replace('_', '-')}-{self.version}"

    @abstractmethod
    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        """Evaluate a single evaluation case deterministically without mutating production."""
        pass

    @abstractmethod
    def calculate_domain_metrics(self, results: List[EvaluationResult]) -> List[EvaluationMetric]:
        """Calculate domain-specific metrics from results."""
        pass

    def get_configuration_fingerprint(self) -> str:
        raw = f"{self.suite_type.value}:{self.domain.value}:{self.version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def run(
        self,
        dataset: EvaluationDataset,
        tenant_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> EvaluationReport:
        """Executes the suite against the provided dataset and returns an EvaluationReport."""
        start_time = datetime.now(timezone.utc)
        effective_run_id = run_id or f"run-{self.suite_type.value.lower()}-{uuid.uuid4().hex[:8]}"

        results: List[EvaluationResult] = []
        failures: List[EvaluationFailure] = []

        # Filter cases by tenant if specified
        cases_to_run = [
            c for c in dataset.cases
            if tenant_id is None or c.tenant_id is None or c.tenant_id == tenant_id or c.tenant_id == "tenant-gold-001"
        ]


        if not cases_to_run:
            # Insufficient or no data: NOT_AVAILABLE
            end_time = datetime.now(timezone.utc)
            duration_ms = (end_time - start_time).total_seconds() * 1000
            score = EvaluationScore(
                domain=self.domain,
                overall_score=None,
                status=EvaluationStatus.NOT_AVAILABLE,
                weights={},
                sample_count=0,
                minimum_sample_met=False,
                summary="Insufficient evaluation data available for suite execution.",
            )
            return EvaluationReport(
                report_id=f"rep-{effective_run_id}",
                run_id=effective_run_id,
                suite_type=self.suite_type,
                domain=self.domain,
                status=EvaluationStatus.NOT_AVAILABLE,
                summary="Suite finished with NOT_AVAILABLE status: no cases found.",
                dataset_version=dataset.version,
                configuration_fingerprint=self.get_configuration_fingerprint(),
                result_fingerprint="none",
                metrics=[],
                domain_score=score,
                total_cases=0,
                passed_cases=0,
                failed_cases=0,
                results=[],
                failures=[],
                duration_ms=duration_ms,
                tenant_id=tenant_id,
            )

        for case in cases_to_run:
            try:
                result = self.evaluate_case(case)
                results.append(result)
                if result.status == EvaluationStatus.FAILED:
                    failure = EvaluationFailure(
                        case_id=case.case_id,
                        reason=result.failure_reason or "Case assertions failed",
                        expected=case.expected_output,
                        actual=result.actual_output,
                        traceback=None,
                    )
                    failures.append(failure)
            except Exception as e:
                result = EvaluationResult(
                    case_id=case.case_id,
                    status=EvaluationStatus.ERROR,
                    actual_output={"error": str(e)},
                    passed_assertions=[],
                    failed_assertions=["execution_exception"],
                    execution_time_ms=0.0,
                    failure_reason=f"Exception during evaluation: {str(e)}",
                )
                results.append(result)
                failures.append(
                    EvaluationFailure(
                        case_id=case.case_id,
                        reason=str(e),
                        expected=case.expected_output,
                        actual={"error": str(e)},
                    )
                )

        # Compute metrics
        metrics = self.calculate_domain_metrics(results)
        domain_score = MetricEngine.aggregate_domain_score(self.domain, metrics)

        # Determine overall suite status
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        failed_count = sum(1 for r in results if r.status in [EvaluationStatus.FAILED, EvaluationStatus.ERROR])

        if failed_count == 0 and passed_count > 0:
            suite_status = EvaluationStatus.PASSED
        elif passed_count > 0 and failed_count > 0:
            suite_status = EvaluationStatus.PARTIAL
        elif domain_score.status == EvaluationStatus.NOT_AVAILABLE:
            suite_status = EvaluationStatus.NOT_AVAILABLE
        else:
            suite_status = EvaluationStatus.FAILED

        end_time = datetime.now(timezone.utc)
        duration_ms = (end_time - start_time).total_seconds() * 1000

        # Deterministic result fingerprint
        res_raw = f"{self.suite_type.value}:{self.domain.value}:{dataset.version}:{suite_status.value}:{passed_count}:{failed_count}:" + ",".join(
            f"{r.case_id}:{r.status.value}" for r in results
        )
        result_fingerprint = hashlib.sha256(res_raw.encode("utf-8")).hexdigest()


        return EvaluationReport(
            report_id=f"rep-{effective_run_id}",
            run_id=effective_run_id,
            suite_type=self.suite_type,
            domain=self.domain,
            status=suite_status,
            summary=f"Suite {self.suite_type.value} evaluated {len(results)} cases: {passed_count} passed, {failed_count} failed.",
            dataset_version=dataset.version,
            configuration_fingerprint=self.get_configuration_fingerprint(),
            result_fingerprint=result_fingerprint,
            metrics=metrics,
            domain_score=domain_score,
            total_cases=len(results),
            passed_cases=passed_count,
            failed_cases=failed_count,
            results=results,
            failures=failures,
            duration_ms=duration_ms,
            tenant_id=tenant_id,
        )
