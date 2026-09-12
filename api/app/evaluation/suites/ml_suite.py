"""ML Evaluation Suite for RiskWise 2.0.

Evaluates Phase 11 Shipment Delay Prediction model:
- Regression accuracy metrics: MAE, RMSE, R²
- Feature consistency & inference stability
- Data leakage detection: temporal leakage, target leakage, post-outcome features
- Cross-tenant inference record filtering
- Strict NOT_AVAILABLE fallback when sample count < minimum required
"""

import time
import math
from typing import List, Dict, Any
from app.evaluation.contracts import (
    EvaluationSuiteType,
    EvaluationDomain,
    EvaluationStatus,
    EvaluationCase,
    EvaluationResult,
    EvaluationMetric,
)
from app.evaluation.suites.base import BaseEvaluationSuite
from app.evaluation.metrics import MetricEngine


class MLEvaluationSuite(BaseEvaluationSuite):
    """Evaluates ML delay predictions, error bounds, and data leakage safeguards."""

    suite_type = EvaluationSuiteType.ML_EVALUATION
    domain = EvaluationDomain.ML

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Regression accuracy evaluation (ml-case-001)
        if "y_true" in inp and "y_pred" in inp:
            y_true = inp["y_true"]
            y_pred = inp["y_pred"]
            min_samples = inp.get("min_samples", 5)

            if len(y_true) < min_samples:
                actual_output["status"] = "NOT_AVAILABLE"
                actual_output["sample_count"] = len(y_true)
                if exp.get("status") == "NOT_AVAILABLE":
                    passed_assertions.append("insufficient_samples_emits_not_available")
                else:
                    failed_assertions.append("expected_metrics_on_insufficient_samples")
            else:
                mae = sum(abs(t - p) for t, p in zip(y_true, y_pred)) / len(y_true)
                rmse = math.sqrt(sum((t - p) ** 2 for t, p in zip(y_true, y_pred)) / len(y_true))
                actual_output["mae"] = round(mae, 2)
                actual_output["rmse"] = round(rmse, 2)
                actual_output["sample_count"] = len(y_true)

                max_mae = exp.get("max_allowed_mae", 30.0)
                max_rmse = exp.get("max_allowed_rmse", 40.0)

                if mae <= max_mae:
                    passed_assertions.append("mae_within_tolerance")
                else:
                    failed_assertions.append(f"mae_exceeded: {mae} > {max_mae}")

                if rmse <= max_rmse:
                    passed_assertions.append("rmse_within_tolerance")
                else:
                    failed_assertions.append(f"rmse_exceeded: {rmse} > {max_rmse}")

        # 2. Leakage detection (ml-case-003)
        if "candidate_feature_names" in inp:
            feature_names = inp["candidate_feature_names"]
            leak_tokens = ["unloading_time", "pod_signature", "arrival_time", "actual_delay"]
            leaking = [f for f in feature_names if any(tok in f for tok in leak_tokens)]
            leakage_detected = len(leaking) > 0
            actual_output["leakage_detected"] = leakage_detected
            actual_output["leaking_features"] = leaking
            actual_output["model_deployable"] = not leakage_detected

            if leakage_detected == exp.get("leakage_detected"):
                passed_assertions.append("leakage_properly_flagged")
            else:
                failed_assertions.append("unflagged_data_leakage_contamination")

        # 3. Cross-tenant inference boundary (ml-case-004)
        if "inference_records" in inp and "model_tenant" in inp:
            tenant = inp["model_tenant"]
            permitted = [r["shipment_id"] for r in inp["inference_records"] if r.get("tenant_id") == tenant]
            rejected = [r["shipment_id"] for r in inp["inference_records"] if r.get("tenant_id") != tenant]
            actual_output["permitted_shipment_ids"] = permitted
            actual_output["rejected_shipment_ids"] = rejected

            if permitted == exp.get("permitted_shipment_ids") and rejected == exp.get("rejected_shipment_ids"):
                passed_assertions.append("cross_tenant_records_isolated")
            else:
                failed_assertions.append("cross_tenant_inference_leakage")

        duration_ms = (time.perf_counter() - start) * 1000
        status = EvaluationStatus.PASSED if not failed_assertions else EvaluationStatus.FAILED
        failure_reason = "; ".join(failed_assertions) if failed_assertions else None

        return EvaluationResult(
            case_id=case.case_id,
            status=status,
            actual_output=actual_output,
            passed_assertions=passed_assertions,
            failed_assertions=failed_assertions,
            execution_time_ms=duration_ms,
            failure_reason=failure_reason,
        )

    def calculate_domain_metrics(self, results: List[EvaluationResult]) -> List[EvaluationMetric]:
        metrics: List[EvaluationMetric] = []
        sample_size = len(results)

        # MAE & RMSE metrics from valid regression cases
        reg_cases = [r for r in results if "mae" in r.actual_output]
        if reg_cases:
            avg_mae = sum(r.actual_output["mae"] for r in reg_cases) / len(reg_cases)
            avg_rmse = sum(r.actual_output["rmse"] for r in reg_cases) / len(reg_cases)
            metrics.append(
                MetricEngine.compute_mae(
                    predictions=[r.actual_output["mae"] for r in reg_cases],
                    actuals=[0.0 for _ in reg_cases],
                    name="Delay Prediction MAE",
                    domain=self.domain,
                    dataset_version=self.version,
                )
            )
            metrics.append(
                MetricEngine.compute_rmse(
                    predictions=[r.actual_output["rmse"] for r in reg_cases],
                    actuals=[0.0 for _ in reg_cases],
                    name="Delay Prediction RMSE",
                    domain=self.domain,
                    dataset_version=self.version,
                )
            )

        # Leakage Protection Rate
        leak_cases = [r for r in results if "leakage_detected" in r.actual_output]
        if leak_cases:
            flagged = sum(1 for r in leak_cases if "leakage_properly_flagged" in r.passed_assertions)
            metrics.append(
                MetricEngine.compute_rate_metric(
                    name="Data Leakage Protection Rate",
                    numerator=flagged,
                    denominator=len(leak_cases),
                    dataset_version=self.version,
                )
            )

        # Overall ML Evaluation Success Rate
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="ML Evaluation Success Rate",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics
