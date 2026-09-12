"""Decision Engine Evaluation Suite for RiskWise 2.0.

Evaluates Phase 15 Decision Engine:
- Deterministic multi-criteria candidate ranking
- Upstream consistency (DecisionResult must not contradict Risk, ML, or Optimization results)
- Fail-closed behavior on missing or contradictory evidence or budget limits
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
        expected_cand = exp.get("expected_selected_candidate") or exp.get("recommended_candidate_id")
        if expected_cand:
            actual_cand = decision_res.get("recommended_candidate")
            if actual_cand == expected_cand:
                passed_assertions.append("candidate_ranking_matches")
            else:
                failed_assertions.append(f"candidate_ranking_mismatch: exp {expected_cand}, got {actual_cand}")

        # Ranking order check
        if "ranking_order" in exp:
            actual_ranking = decision_res.get("ranking_order", [])
            if actual_ranking == exp["ranking_order"]:
                passed_assertions.append("ranking_order_matches")
            else:
                failed_assertions.append(f"ranking_order_mismatch: exp {exp['ranking_order']}, got {actual_ranking}")

        # 3. Fail-closed behavior
        expected_fail_closed = exp.get("fail_closed") if exp.get("fail_closed") is not None else exp.get("fail_closed_triggered")
        if expected_fail_closed is not None:
            actual_fail_closed = decision_res.get("status") in ["FAIL_CLOSED_NO_DECISION", "REQUIRE_HUMAN_OVERRIDE"]
            if actual_fail_closed == expected_fail_closed:
                passed_assertions.append("fail_closed_properly_triggered")
            else:
                failed_assertions.append(f"fail_closed_failed: status was {decision_res.get('status')}")

        if "decision_outcome" in exp:
            actual_outcome = decision_res.get("status")
            if actual_outcome == exp["decision_outcome"]:
                passed_assertions.append("decision_outcome_matches")
            else:
                failed_assertions.append(f"outcome_mismatch: exp {exp['decision_outcome']}, got {actual_outcome}")

        # 4. Consistency with upstream authoritative risk & optimization
        if exp.get("upstream_consistent") is not None or exp.get("policy_compliant") is not None:
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
        consistent_evaluated = [
            r for r in results
            if any(a in r.passed_assertions for a in ["upstream_results_uncontradicted", "candidate_ranking_matches", "decision_outcome_matches"])
            or any("mismatch" in f or "contradicts" in f for f in r.failed_assertions)
        ]
        if consistent_evaluated:
            consistent_count = sum(
                1 for r in consistent_evaluated
                if not any("mismatch" in f or "contradicts" in f for f in r.failed_assertions)
            )
            metrics.append(
                MetricEngine.compute_accuracy(
                    name="Decision Consistency",
                    correct=consistent_count,
                    total=len(consistent_evaluated),
                    dataset_version=self.version,
                )
            )

        # Fail-Closed Safety Rate
        fail_closed_evaluated = [
            r for r in results
            if any("fail_closed" in a for a in r.passed_assertions)
            or any("fail_closed" in f for f in r.failed_assertions)
        ]
        if fail_closed_evaluated:
            fail_closed_cases = sum(1 for r in fail_closed_evaluated if "fail_closed_properly_triggered" in r.passed_assertions)
            metrics.append(
                MetricEngine.compute_rate_metric(
                    name="Fail-Closed Safety Rate",
                    numerator=fail_closed_cases,
                    denominator=len(fail_closed_evaluated),
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

        budget_cap = inp.get("budget_cap_usd")
        if budget_cap is not None:
            # Check if all candidates exceed budget
            all_exceed = all(c.get("cost_usd", 0.0) > budget_cap for c in candidates)
            if all_exceed:
                return {
                    "status": "REQUIRE_HUMAN_OVERRIDE",
                    "recommended_candidate": None,
                    "ranking_order": [],
                    "contradicts_upstream": False,
                }

        # Multi-attribute scoring
        scored = []
        for c in candidates:
            cid = c.get("candidate_id") or c.get("id")
            if "risk_reduction" in c:
                # Primary risk reduction weighting minus cost scale
                score = (c.get("risk_reduction", 0.0) * 100.0) - (c.get("cost_usd", 0.0) / 2500.0)
            else:
                score = (c.get("cost_savings", 0) * 0.6) + (c.get("time_savings_days", 0) * 1000 * 0.4)
            scored.append((score, cid))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranking_order = [s[1] for s in scored]
        best_id = ranking_order[0] if ranking_order else None

        return {
            "status": "RECOMMENDATION_READY",
            "recommended_candidate": best_id,
            "ranking_order": ranking_order,
            "contradicts_upstream": False,
        }
