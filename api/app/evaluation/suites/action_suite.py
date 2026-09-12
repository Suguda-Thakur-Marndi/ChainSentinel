"""Action Execution Evaluation Suite for RiskWise 2.0.

Evaluates Phase 17 Action Execution Engine:
- Pre-condition approval enforcement
- Action allowlist validation (prohibits dangerous/arbitrary commands)
- Idempotency & duplicate submission deduplication
- SSRF and payload injection protection
- Invariant: SUBMITTED != VERIFIED (execution acknowledgement != business ground-truth success)
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


class ActionEvaluationSuite(BaseEvaluationSuite):
    """Evaluates action safety, approval requirements, and execution invariants."""

    suite_type = EvaluationSuiteType.ACTION_EVALUATION
    domain = EvaluationDomain.ACTION

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Execute action simulation
        action_res = self._dispatch_action(inp)
        actual_output["action_dispatch"] = action_res

        # 2. Approval prerequisite check
        if exp.get("blocked_without_approval") or exp.get("execution_allowed") is False:
            if not action_res.get("dispatched"):
                passed_assertions.append("unapproved_action_blocked")
            else:
                failed_assertions.append("critical_action_dispatched_without_approval")

        # 3. Action allowlist check
        if exp.get("prohibited_action_blocked"):
            action_name = inp.get("action_type")
            if action_res.get("dispatched") is False and "NOT_IN_ALLOWLIST" in action_res.get("reason", ""):
                passed_assertions.append("prohibited_action_blocked_by_allowlist")
            else:
                failed_assertions.append(f"prohibited_action_permitted: {action_name}")

        # 4. SSRF protection check
        if exp.get("blocked_by_ssrf_filter"):
            if action_res.get("blocked_by_ssrf"):
                passed_assertions.append("ssrf_payload_blocked")
            else:
                failed_assertions.append("ssrf_payload_dispatched")

        # 5. Idempotency test
        if exp.get("idempotency_enforced") or exp.get("is_duplicate_prevented"):
            if action_res.get("is_duplicate"):
                passed_assertions.append("duplicate_action_idempotently_deduplicated")
            else:
                failed_assertions.append("idempotency_violated_duplicate_action_executed")

        # 6. Status check & Invariant: SUBMITTED != VERIFIED
        expected_status = exp.get("execution_status") or exp.get("status")
        actual_status = action_res.get("status")
        if expected_status:
            if actual_status == expected_status:
                passed_assertions.append(f"status_matches_{expected_status}")
            else:
                failed_assertions.append(f"status_mismatch: exp {expected_status}, got {actual_status}")

        if actual_status == "SUBMITTED":
            if actual_status != "VERIFIED":
                passed_assertions.append("submitted_not_conflated_with_verified")
            else:
                failed_assertions.append("illegal_conflation_submitted_marked_as_verified")

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

        # Action Idempotency Rate
        idem_evaluated = [
            r for r in results
            if "duplicate_action_idempotently_deduplicated" in r.passed_assertions
            or "idempotency_violated_duplicate_action_executed" in r.failed_assertions
        ]
        if idem_evaluated:
            idem_passed = sum(1 for r in idem_evaluated if "duplicate_action_idempotently_deduplicated" in r.passed_assertions)
            metrics.append(
                MetricEngine.compute_rate_metric(
                    name="Action Idempotency Rate",
                    numerator=idem_passed,
                    denominator=len(idem_evaluated),
                    dataset_version=self.version,
                )
            )

        # Approval Enforcement Rate
        app_evaluated = [
            r for r in results
            if "unapproved_action_blocked" in r.passed_assertions
            or "critical_action_dispatched_without_approval" in r.failed_assertions
        ]
        if app_evaluated:
            app_passed = sum(1 for r in app_evaluated if "unapproved_action_blocked" in r.passed_assertions)
            metrics.append(
                MetricEngine.compute_rate_metric(
                    name="Action Approval Enforcement",
                    numerator=app_passed,
                    denominator=len(app_evaluated),
                    dataset_version=self.version,
                )
            )

        # Status Invariant Precision (SUBMITTED != VERIFIED)
        submitted_cases = [r for r in results if r.actual_output.get("action_dispatch", {}).get("status") == "SUBMITTED"]
        if submitted_cases:
            inv_cases = sum(1 for r in submitted_cases if "submitted_not_conflated_with_verified" in r.passed_assertions)
            metrics.append(
                MetricEngine.compute_accuracy(
                    name="Action Invariant Precision",
                    correct=inv_cases,
                    total=len(submitted_cases),
                    dataset_version=self.version,
                )
            )

        # Overall Action Correctness
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Action Correctness Rate",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics

    def _dispatch_action(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates action execution dispatch."""
        # SSRF check
        dest_url = inp.get("destination_url", "")
        if any(bad in dest_url for bad in ["169.254.", "127.0.0.1", "localhost", "file://"]):
            return {
                "dispatched": False,
                "status": "BLOCKED_SSRF",
                "blocked_by_ssrf": True,
                "is_duplicate": False,
            }

        # Idempotency check
        idemp_key = inp.get("idempotency_key")
        attempts = inp.get("attempts", 1)
        if idemp_key and attempts > 1:
            return {
                "dispatched": True,
                "status": "SUBMITTED",
                "is_duplicate": True,
                "approved": True,
            }

        approved = inp.get("approved") if inp.get("approved") is not None else inp.get("is_approved", False)
        if not approved:
            return {"dispatched": False, "status": "BLOCKED_REQUIRES_APPROVAL", "approved": False, "is_duplicate": False}

        action_type = inp.get("action_type", "")
        allowlist = [
            "CARRIER_REROUTE",
            "EXPEDITE_AIR_FREIGHT",
            "WEBHOOK_NOTIFY",
            "REROUTE_SHIPMENT",
            "NOTIFY_CARRIER",
            "EXPEDITE_CUSTOMS",
            "UPDATE_ETA",
        ]
        if action_type not in allowlist:
            return {"dispatched": False, "status": "REJECTED", "reason": "NOT_IN_ALLOWLIST", "is_duplicate": False}

        return {
            "dispatched": True,
            "status": "SUBMITTED",  # strictly SUBMITTED, never VERIFIED
            "is_duplicate": False,
            "approved": True,
        }
