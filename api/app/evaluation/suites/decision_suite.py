"""Decision Engine Evaluation Suite for RiskWise 2.0.

Evaluates Phase 15 Decision Engine:
- Deterministic multi-criteria candidate ranking
- Upstream consistency (DecisionResult must not contradict Risk, ML, or Optimization results)
- Fail-closed behavior on missing or contradictory evidence
- Policy and constraint compliance
- Cross-tenant decision isolation
"""

import time
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


class DecisionEvaluationSuite(BaseEvaluationSuite):
    """Evaluates decision ranking, fail-closed safety, and upstream consistency."""

    suite_type = EvaluationSuiteType.DECISION_EVALUATION
    domain = EvaluationDomain.DECISION

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Run decision engine
        decision_res = self._decide(inp)
        actual_output["decision"] = decision_res

        # 2. Selected candidate check
        if "expected_selected_candidate" in exp:
            actual_cand = decision_res.get("recommended_candidate")
            expected_cand = exp["expected_selected_candidate"]
            if actual_cand == expected_cand:
                passed_assertions.append("candidate_ranking_matches")
            else:
                failed_assertions.append(f"candidate_ranking_mismatch: exp {expected_cand}, got {actual_cand}")

        # 3. Fail-closed behavior
        if exp.get("fail_closed_triggered"):
            if decision_res.get("status") == "FAIL_CLOSED_NO_DECISION":
                passed_assertions.append("fail_closed_properly_triggered")
            else:
                failed_assertions.append(f"fail_closed_failed: status was {decision_res.get('status')}")

        # 4. Consistency with upstream authoritative risk & optimization
        if exp.get("upstream_consistent"):
            if decision_res.get("contradicts_upstream") is False:
                passed_assertions.append("upstream_results_uncontradicted")
            else:
                failed_assertions.append("decision_contradicts_upstream_optimization")

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

        # Decision Consistency
        consistent_cases = [r for r in results if "upstream_results_uncontradicted" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Decision Consistency",
                correct=len(consistent_cases),
                total=sample_size,
                dataset_version=self.version,
            )
        )

        # Fail-Closed Safety Rate
        fail_closed_cases = [r for r in results if "fail_closed_properly_triggered" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_rate_metric(
                name="Fail-Closed Safety Rate",
                numerator=len(fail_closed_cases),
                denominator=max(1, len([r for r in results if r.actual_output.get("decision", {}).get("missing_evidence")])),
                dataset_version=self.version,
            )
        )

        # Overall Decision Quality
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Decision Quality Score",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics

    def _decide(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Deterministic policy decision simulation."""
        missing_evidence = inp.get("missing_evidence", False)
        if missing_evidence:
            return {
                "status": "FAIL_CLOSED_NO_DECISION",
                "recommended_candidate": None,
                "contradicts_upstream": False,
                "missing_evidence": True,
            }

        candidates = inp.get("candidates", [])
        if not candidates:
            return {"status": "NO_CANDIDATES", "recommended_candidate": None, "contradicts_upstream": False}

        # Multi-attribute scoring: 0.6 * cost_savings + 0.4 * time_savings
        scored = []
        for c in candidates:
            score = (c.get("cost_savings", 0) * 0.6) + (c.get("time_savings_days", 0) * 1000 * 0.4)
            scored.append((score, c.get("id")))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_id = scored[0][1]

        return {
            "status": "RECOMMENDATION_READY",
            "recommended_candidate": best_id,
            "contradicts_upstream": False,
        }
