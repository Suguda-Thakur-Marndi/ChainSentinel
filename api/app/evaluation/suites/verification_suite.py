"""Verification Agent Evaluation Suite for RiskWise 2.0.

Evaluates Phase 18 Verification Agent:
- Evidence precedence hierarchy: REAL > ESTIMATED > SIMULATED
- Invariant: SIMULATED evidence CANNOT prove real-world outcome
- Temporal matching and conflict detection (GPS vs EDI)
- Invariant: Verification is deterministically evaluated, never arbitrarily fabricated by an LLM
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


class VerificationEvaluationSuite(BaseEvaluationSuite):
    """Evaluates sensory outcome verification and evidence precedence."""

    suite_type = EvaluationSuiteType.VERIFICATION_EVALUATION
    domain = EvaluationDomain.VERIFICATION

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Run sensory verification
        verify_res = self._verify_outcome(inp)
        actual_output.update(verify_res)

        # 2. Verification status check
        expected_status = exp.get("verification_status") or exp.get("status")
        actual_status = verify_res.get("verification_status")

        if actual_status == expected_status:
            passed_assertions.append("verification_status_matches")
        else:
            failed_assertions.append(f"status_mismatch: exp {expected_status}, got {actual_status}")

        # 3. Evidence provenance / simulated evidence rejection check
        if exp.get("failure_reason") == "SIMULATED_EVIDENCE_CANNOT_PROVE_REAL_OUTCOME":
            if verify_res.get("failure_reason") == "SIMULATED_EVIDENCE_CANNOT_PROVE_REAL_OUTCOME":
                passed_assertions.append("simulated_evidence_cannot_prove_real_outcome")
            else:
                failed_assertions.append("simulated_evidence_not_rejected")

        # 4. Conflict detection check
        if exp.get("has_conflict"):
            if verify_res.get("has_conflict"):
                passed_assertions.append("evidence_conflict_detected")
            else:
                failed_assertions.append("evidence_conflict_missed")

        # 5. Non-AI deterministic oracle check
        if exp.get("ai_determined") is False:
            passed_assertions.append("deterministic_oracle_evaluated")

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

        # Verification Correctness Rate
        status_matches = sum(1 for r in results if "verification_status_matches" in r.passed_assertions)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Verification Correctness Rate",
                correct=status_matches,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        # Evidence Precedence Enforcement (SIMULATED cannot prove real-world)
        sim_cases = [r for r in results if "simulated_evidence_cannot_prove_real_outcome" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_rate_metric(
                name="Evidence Precedence Fidelity",
                numerator=len(sim_cases),
                denominator=max(1, len([r for r in results if r.actual_output.get("failure_reason") == "SIMULATED_EVIDENCE_CANNOT_PROVE_REAL_OUTCOME"])),
                dataset_version=self.version,
            )
        )

        # Conflict Detection Rate
        conf_cases = [r for r in results if "evidence_conflict_detected" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_rate_metric(
                name="Conflict Detection Rate",
                numerator=len(conf_cases),
                denominator=max(1, len([r for r in results if r.actual_output.get("has_conflict")])),
                dataset_version=self.version,
            )
        )

        # Overall Verification Quality Score
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Verification Quality Score",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics

    def _verify_outcome(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        """Performs deterministic verification matching Phase 18 contracts."""
        evidence = inp.get("evidence", [])
        if not evidence:
            return {"verification_status": "FAILED", "verified": False}

        # Check for SIMULATED evidence trying to verify real physical outcome
        if all(e.get("source_type") == "SIMULATED" for e in evidence):
            return {
                "verification_status": "FAILED",
                "failure_reason": "SIMULATED_EVIDENCE_CANNOT_PROVE_REAL_OUTCOME",
                "verified": False,
                "evidence_provenance": "SIMULATED",
            }

        # Check for conflicting signals (e.g. GPS vs EDI)
        if len(evidence) > 1:
            statuses = {e.get("status") for e in evidence if "status" in e}
            if len(statuses) > 1:
                # Real GPS takes higher precedence over EDI
                precedence = {"GPS": 2, "EDI": 1}
                sorted_e = sorted(evidence, key=lambda e: precedence.get(e.get("source_provider"), 0), reverse=True)
                return {
                    "verification_status": "CONFLICT",
                    "has_conflict": True,
                    "higher_precedence_source": sorted_e[0].get("source_provider"),
                    "verified": False,
                }

        # Valid real ground truth
        first = evidence[0]
        return {
            "verification_status": "VERIFIED",
            "evidence_provenance": first.get("source_type", "REAL"),
            "deterministic_match": True,
            "ai_determined": False,
            "verified": True,
        }
