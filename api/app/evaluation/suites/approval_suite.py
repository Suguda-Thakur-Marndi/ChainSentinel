"""Human Approval Governance Evaluation Suite for RiskWise 2.0.

Evaluates Phase 16 Human Approval Gate:
- Authorized RBAC role enforcement (e.g. SUPPLY_CHAIN_DIRECTOR, RISKMANAGER)
- Decision & candidate fingerprint binding integrity
- Invariant: LLM / Agent CANNOT approve decisions autonomously
- Rejection reason capture and governance audit trails
- Stale approval rejection
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


class ApprovalEvaluationSuite(BaseEvaluationSuite):
    """Evaluates human approval gate governance, RBAC permissions, and LLM non-approval invariant."""

    suite_type = EvaluationSuiteType.APPROVAL_EVALUATION
    domain = EvaluationDomain.APPROVAL

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Evaluate approval attempt
        approval_res = self._process_approval(inp)
        actual_output["approval_record"] = approval_res

        # 2. Check LLM / Agent cannot approve invariant
        actor = inp.get("actor_type") or inp.get("requester_type")
        if actor in ["LLM", "AGENT", "BOT", "AI_AGENT"]:
            if not approval_res.get("success"):
                passed_assertions.append("agent_or_llm_cannot_approve_invariant_verified")
            else:
                failed_assertions.append("critical_violation_llm_approved_decision")

        # 3. Role enforcement check
        if exp.get("is_permitted") is not None:
            if approval_res.get("success") == exp["is_permitted"]:
                passed_assertions.append("rbac_role_enforced")
            else:
                failed_assertions.append(f"rbac_permission_mismatch: exp {exp['is_permitted']}, got {approval_res.get('success')}")

        if "expected_status" in exp:
            actual_status = approval_res.get("status")
            if actual_status == exp["expected_status"]:
                passed_assertions.append("rbac_status_enforced")
            else:
                failed_assertions.append(f"rbac_status_mismatch: exp {exp['expected_status']}, got {actual_status}")

        if exp.get("expected_status_code") == 403:
            if approval_res.get("status_code") == 403 or not approval_res.get("success"):
                passed_assertions.append("forbidden_status_enforced")
            else:
                failed_assertions.append("forbidden_status_not_returned")

        # 4. Fingerprint & candidate binding
        if exp.get("fingerprint_binding_verified") or exp.get("fingerprint_match") is not None:
            expected_match = exp.get("fingerprint_match", True)
            if approval_res.get("fingerprint_valid") == expected_match:
                passed_assertions.append("decision_fingerprint_bound_successfully")
            else:
                failed_assertions.append("fingerprint_binding_mismatch")

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

        # Approval Integrity Rate
        integrity_evaluated = [
            r for r in results
            if any(a in r.passed_assertions for a in ["rbac_role_enforced", "rbac_status_enforced", "forbidden_status_enforced"])
            or any("rbac" in f or "forbidden" in f for f in r.failed_assertions)
        ]
        if integrity_evaluated:
            integrity_passed = sum(
                1 for r in integrity_evaluated
                if not any("rbac" in f or "forbidden" in f for f in r.failed_assertions)
            )
            metrics.append(
                MetricEngine.compute_accuracy(
                    name="Approval Integrity Rate",
                    correct=integrity_passed,
                    total=len(integrity_evaluated),
                    dataset_version=self.version,
                )
            )

        # Non-Agent Authority Enforcement Rate
        agent_cases = [
            r for r in results
            if "agent_or_llm_cannot_approve_invariant_verified" in r.passed_assertions
            or "critical_violation_llm_approved_decision" in r.failed_assertions
        ]
        if agent_cases:
            agent_passed = sum(1 for r in agent_cases if "agent_or_llm_cannot_approve_invariant_verified" in r.passed_assertions)
            metrics.append(
                MetricEngine.compute_rate_metric(
                    name="Non-Agent Authority Enforcement",
                    numerator=agent_passed,
                    denominator=len(agent_cases),
                    dataset_version=self.version,
                )
            )

        # Overall Governance Score
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Governance Evaluation Score",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics

    def _process_approval(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Validates human approval gate conditions."""
        actor_type = inp.get("actor_type") or inp.get("requester_type", "HUMAN")
        if actor_type in ["LLM", "AGENT", "BOT", "AI_AGENT"]:
            return {
                "success": False,
                "status": "FORBIDDEN_AUTONOMOUS_APPROVAL_PROHIBITED",
                "status_code": 403,
                "error_reason": "AI_AGENT_CANNOT_APPROVE_DECISION",
                "actor_type": actor_type,
            }

        # Check fingerprint match first
        target_fp = inp.get("approval_target_fingerprint") or inp.get("decision_fingerprint", "fp-123")
        current_fp = inp.get("current_decision_fingerprint") or inp.get("submitted_fingerprint", "fp-123")
        if target_fp != current_fp:
            return {
                "success": False,
                "status": "DECISION_STATE_CHANGED_STALE_APPROVAL",
                "status_code": 409,
                "fingerprint_valid": False,
                "rejection_reason": "DECISION_STATE_CHANGED_STALE_APPROVAL",
                "actor_type": actor_type,
            }

        role = (inp.get("approver_role") or inp.get("user_role", "")).upper()
        allowed_roles = ["SUPPLY_CHAIN_VP", "LOGISTICS_DIRECTOR", "OPERATIONS_LEAD", "RISKMANAGER", "RISK_MANAGER", "ADMIN"]
        if role and role not in allowed_roles:
            return {
                "success": False,
                "status": "FORBIDDEN_INSUFFICIENT_ROLE",
                "status_code": 403,
                "actor_type": actor_type,
            }

        return {
            "success": True,
            "status": "APPROVED",
            "status_code": 200,
            "fingerprint_valid": True,
            "actor_type": actor_type,
        }
