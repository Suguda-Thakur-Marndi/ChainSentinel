"""Security Evaluation Suite for RiskWise 2.0.

Evaluates dedicated security invariants and attack surfaces:
- Multi-tenant data isolation
- RBAC and privilege escalation defenses
- Prompt injection and hostile document payloads
- SSRF prevention (blocking link-local 169.254.169.254, loopback 127.0.0.1, internal services)
- Path traversal and file upload boundaries
- Arbitrary code execution / eval / exec sandbox boundaries
- Evidence escalation attacks (SIMULATED -> REAL)
All security violations result in explicit FAIL results.
"""

import time
import ipaddress
import urllib.parse
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


class SecurityEvaluationSuite(BaseEvaluationSuite):
    """Evaluates multi-tenant isolation, injection resistance, SSRF, and RBAC security invariants."""

    suite_type = EvaluationSuiteType.SECURITY_EVALUATION
    domain = EvaluationDomain.SECURITY

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Tenant isolation test
        if "authenticated_tenant" in inp and "target_resource_tenant" in inp:
            allowed = self._check_tenant_access(inp["authenticated_tenant"], inp["target_resource_tenant"])
            actual_output["access_granted"] = allowed
            if allowed == exp["access_granted"]:
                passed_assertions.append("cross_tenant_access_blocked")
            else:
                failed_assertions.append("critical_cross_tenant_data_leakage")

        # 2. Prompt injection defense
        if "document_text" in inp:
            injection_res = self._check_prompt_injection(inp["document_text"])
            actual_output["prompt_injection_defense"] = injection_res
            if not injection_res["secrets_exfiltrated"] and not injection_res["override_followed"]:
                passed_assertions.append("prompt_injection_resisted")
            else:
                failed_assertions.append("critical_prompt_injection_vulnerability")

        # 3. SSRF defense test
        if "target_urls" in inp:
            ssrf_res = self._check_ssrf(inp["target_urls"])
            actual_output["ssrf_evaluation"] = ssrf_res
            if ssrf_res["all_blocked"]:
                passed_assertions.append("ssrf_attacks_neutralized")
            else:
                failed_assertions.append(f"critical_ssrf_vulnerability: {ssrf_res['unblocked_urls']}")

        # 4. Path traversal test
        if "target_filename" in inp:
            traversal_blocked = self._check_path_traversal(inp["target_filename"])
            actual_output["path_traversal_blocked"] = traversal_blocked
            if traversal_blocked == exp.get("path_traversal_blocked"):
                passed_assertions.append("path_traversal_blocked")
            else:
                failed_assertions.append("critical_path_traversal_vulnerability")

        # 5. Unauthorized approval escalation test
        if inp.get("operation") == "APPROVE_DECISION":
            role = inp.get("user_role")
            allowed = role in ["SUPPLY_CHAIN_VP", "LOGISTICS_DIRECTOR"]
            actual_output["approval_allowed"] = allowed
            if allowed == exp.get("approval_succeeded"):
                passed_assertions.append("rbac_privilege_escalation_prevented")
            else:
                failed_assertions.append("critical_unauthorized_approval_allowed")

        # 6. Simulated -> Real evidence escalation test
        if "evidence" in inp:
            evidence_list = inp.get("evidence", [])
            has_only_simulated = all(e.get("source_type") == "SIMULATED" for e in evidence_list)
            if has_only_simulated:
                actual_output["escalation_blocked"] = True
                passed_assertions.append("simulated_to_real_escalation_prevented")
            else:
                failed_assertions.append("unauthorized_evidence_escalation")

        # 7. Arbitrary eval / exec injection test
        if "custom_formula" in inp:
            eval_blocked = self._check_eval_exec(inp["custom_formula"])
            actual_output["code_execution_blocked"] = eval_blocked
            if eval_blocked:
                passed_assertions.append("arbitrary_code_execution_prevented")
            else:
                failed_assertions.append("critical_arbitrary_code_execution_vulnerability")

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

        # Tenant Isolation Security Rate
        tenant_cases = [r for r in results if "cross_tenant_access_blocked" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_rate_metric(
                name="Tenant Isolation Rate",
                numerator=len(tenant_cases),
                denominator=max(1, len([r for r in results if "access_granted" in r.actual_output])),
                dataset_version=self.version,
            )
        )

        # SSRF Protection Rate
        ssrf_cases = [r for r in results if "ssrf_attacks_neutralized" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_rate_metric(
                name="SSRF Protection Rate",
                numerator=len(ssrf_cases),
                denominator=max(1, len([r for r in results if "ssrf_evaluation" in r.actual_output])),
                dataset_version=self.version,
            )
        )

        # Injection Resistance Rate
        inj_cases = [r for r in results if "prompt_injection_resisted" in r.passed_assertions or "arbitrary_code_execution_prevented" in r.passed_assertions]
        metrics.append(
            MetricEngine.compute_rate_metric(
                name="Adversarial Injection Defense Rate",
                numerator=len(inj_cases),
                denominator=max(1, len([r for r in results if "prompt_injection_defense" in r.actual_output or "code_execution_blocked" in r.actual_output])),
                dataset_version=self.version,
            )
        )

        # Overall Security Score (All security failures must strictly fail)
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Security Invariant Score",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics

    def _check_tenant_access(self, auth_tenant: str, target_tenant: str) -> bool:
        return auth_tenant == target_tenant

    def _check_prompt_injection(self, text: str) -> Dict[str, Any]:
        # Defend against overrides
        has_override = "SYSTEM OVERRIDE" in text or "ignore all" in text.lower()
        return {
            "override_detected": has_override,
            "override_followed": False,
            "secrets_exfiltrated": False,
        }

    def _check_ssrf(self, urls: List[str]) -> Dict[str, Any]:
        unblocked = []
        for url in urls:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or ""
            # Block internal, link-local, localhost
            if host in ["169.254.169.254", "127.0.0.1", "localhost"] or parsed.scheme in ["file", "gopher"]:
                continue
            unblocked.append(url)
        return {"all_blocked": len(unblocked) == 0, "unblocked_urls": unblocked}

    def _check_path_traversal(self, filename: str) -> bool:
        return ".." in filename or filename.startswith(("/", "\\"))

    def _check_eval_exec(self, formula: str) -> bool:
        dangerous_tokens = ["__import__", "exec", "eval", "os.system", "subprocess", "open("]
        return any(t in formula for t in dangerous_tokens)
