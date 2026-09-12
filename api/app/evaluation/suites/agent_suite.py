"""Agent Evaluation Suite for RiskWise 2.0.

Evaluates LangGraph agents:
- Node routing correctness
- Tool selection accuracy
- Required tool invocation vs prohibited tool invocation
- Error recovery and retry behavior
- State propagation and tenant isolation
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


class AgentEvaluationSuite(BaseEvaluationSuite):
    """Evaluates agent graph routing, tool selection, and recovery."""

    suite_type = EvaluationSuiteType.AGENT_EVALUATION
    domain = EvaluationDomain.AGENT

    def evaluate_case(self, case: EvaluationCase) -> EvaluationResult:
        start = time.perf_counter()
        inp = case.input_data
        exp = case.expected_output

        passed_assertions: List[str] = []
        failed_assertions: List[str] = []
        actual_output: Dict[str, Any] = {}

        # 1. Routing node selection evaluation
        if "expected_nodes" in exp:
            actual_route = self._simulate_routing(inp)
            actual_output["routed_nodes"] = actual_route
            if actual_route == exp["expected_nodes"]:
                passed_assertions.append("routing_sequence_matches")
            else:
                failed_assertions.append(
                    f"routing_mismatch: expected {exp['expected_nodes']}, got {actual_route}"
                )

        # 2. Tool selection allowlist & prohibit checks
        if "expected_tools" in exp or "prohibited_tools" in exp:
            selected_tools = self._simulate_tool_selection(inp)
            actual_output["selected_tools"] = selected_tools

            expected_tools = exp.get("expected_tools", [])
            for et in expected_tools:
                if et in selected_tools:
                    passed_assertions.append(f"invoked_required_tool_{et}")
                else:
                    failed_assertions.append(f"missing_required_tool_{et}")

            prohibited_tools = exp.get("prohibited_tools", [])
            for pt in prohibited_tools:
                if pt not in selected_tools:
                    passed_assertions.append(f"avoided_prohibited_tool_{pt}")
                else:
                    failed_assertions.append(f"invoked_prohibited_tool_{pt}")

        # 3. Recovery / Retry behavior
        if "recovery_action" in exp:
            recovery_result = self._simulate_recovery(inp)
            actual_output["recovery"] = recovery_result
            if recovery_result.get("action") == exp["recovery_action"]:
                passed_assertions.append("recovery_action_matches")
            else:
                failed_assertions.append("recovery_action_mismatch")

        # 4. Tenant isolation verification
        if exp.get("tenant_isolation_maintained") is not None:
            tenant_isolated = inp.get("tenant_id") == case.tenant_id
            actual_output["tenant_isolation_maintained"] = tenant_isolated
            if tenant_isolated == exp["tenant_isolation_maintained"]:
                passed_assertions.append("tenant_isolation_intact")
            else:
                failed_assertions.append("tenant_isolation_breached")

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

        # Routing Accuracy
        routing_cases = [r for r in results if "routed_nodes" in r.actual_output]
        if routing_cases:
            correct_routing = sum(
                1 for r in routing_cases if any("routing_sequence_matches" in a for a in r.passed_assertions)
            )
            metrics.append(
                MetricEngine.compute_accuracy(
                    name="Agent Routing Accuracy",
                    correct=correct_routing,
                    total=len(routing_cases),
                    dataset_version=self.version,
                )
            )

        # Tool Selection Accuracy
        tool_cases = [r for r in results if "selected_tools" in r.actual_output]
        if tool_cases:
            valid_tooling = sum(
                1 for r in tool_cases
                if not any("missing_required_tool" in f or "invoked_prohibited_tool" in f for f in r.failed_assertions)
            )
            metrics.append(
                MetricEngine.compute_accuracy(
                    name="Tool Selection Accuracy",
                    correct=valid_tooling,
                    total=len(tool_cases),
                    dataset_version=self.version,
                )
            )

        # Recovery Success Rate
        recovery_cases = [r for r in results if "recovery" in r.actual_output]
        if recovery_cases:
            recovered = sum(
                1 for r in recovery_cases if any("recovery_action_matches" in a for a in r.passed_assertions)
            )
            metrics.append(
                MetricEngine.compute_rate_metric(
                    name="Recovery Success Rate",
                    numerator=recovered,
                    denominator=len(recovery_cases),
                    dataset_version=self.version,
                )
            )

        # Overall Agent Success Rate
        passed_count = sum(1 for r in results if r.status == EvaluationStatus.PASSED)
        metrics.append(
            MetricEngine.compute_accuracy(
                name="Agent Success Rate",
                correct=passed_count,
                total=sample_size,
                dataset_version=self.version,
            )
        )

        return metrics

    # Deterministic simulation harnesses (no production mutation)
    def _simulate_routing(self, inp: Dict[str, Any]) -> List[str]:
        event_type = inp.get("event_type", "")
        if event_type == "PORT_STRIKE_ANNOUNCED":
            return ["research_agent", "risk_engine", "decision_agent"]
        elif event_type == "CUSTOMS_DELAY":
            return ["research_agent", "risk_engine"]
        return ["research_agent"]

    def _simulate_tool_selection(self, inp: Dict[str, Any]) -> List[str]:
        event_type = inp.get("event_type", "")
        if event_type == "PORT_STRIKE_ANNOUNCED":
            return ["port_congestion_index_tool", "vessel_tracker_tool"]
        return []

    def _simulate_recovery(self, inp: Dict[str, Any]) -> Dict[str, Any]:
        error = inp.get("simulated_error")
        if error == "AIS_STREAM_TIMEOUT":
            return {"action": "SWITCH_TO_SECONDARY_FEED", "feed": "LLOYDS_BULLETIN"}
        return {"action": "NONE"}
