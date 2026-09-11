"""Standardized execution harness and policy enforcement wrapper for LangGraph agent nodes.

Guarantees that every node execution is validated against tenant boundaries, caller authorization,
mandatory input contracts, evidence requirements, execution step limits, and state ownership,
while enforcing state integrity hashing, bounded retries, timeout safeguards, and telemetry.
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import time
from typing import Any, Callable, Dict, Optional

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphStateDict,
    AgentStage,
    NodeContract,
)
from app.agents.errors import (
    AgentErrorCategory,
    AgentApprovalBoundaryViolationError,
    AgentGraphError,
    AgentMaxStepsExceededError,
    AgentMissingInputError,
    AgentNodeExecutionError,
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentTimeoutError,
    AgentToolAuthorizationError,
    categorize_error,
    is_retryable_error,
)
from app.agents.observability import (
    AgentObservability,
    AgentRunTelemetry,
    NodeExecutionTelemetry,
    global_metrics_collector,
)
from app.agents.recovery import (
    RecoveryDecision,
    RecoveryPolicy,
    RetryPolicy,
    compute_state_hash,
)
from app.agents.security import validate_tenant_isolation


class NodeExecutionWrapper:
    """Harness wrapping a node handler with pre/post-execution safeguards, retries, and telemetry."""

    def __init__(
        self,
        contract: NodeContract,
        handler: Callable[[AgentGraphStateDict], Dict[str, Any]],
        retry_policy: Optional[RetryPolicy] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.contract = contract
        self.handler = handler
        self.retry_policy = retry_policy or RetryPolicy(base_delay_seconds=0.01, max_delay_seconds=0.05)
        self.timeout_seconds = timeout_seconds

    def __call__(
        self,
        state: AgentGraphStateDict,
        context: Optional[AgentExecutionContext] = None,
    ) -> Dict[str, Any]:
        """Make wrapper callable directly."""
        return self.execute(state=state, context=context)

    def execute(
        self,
        state: AgentGraphStateDict,
        context: Optional[AgentExecutionContext] = None,
    ) -> Dict[str, Any]:
        """Execute the wrapped node handler under strict security and contract invariants.

        Raises:
            AgentTenantIsolationError: On tenant absence or mismatch.
            AgentToolAuthorizationError: If caller lacks required roles or allowed stages.
            AgentApprovalBoundaryViolationError: If side-effecting action lacks explicit approval.
            AgentMissingInputError: If declared input requirements or evidence counts are missing.
            AgentMaxStepsExceededError: If step limits are exceeded.
            AgentStateOwnershipViolationError: If output keys violate contract output permissions.
            AgentTimeoutError: If execution exceeds configured node timeout.
            AgentNodeExecutionError: On unhandled internal execution failures.
        """
        # 1. Tenant validation
        state_org = state.get("organization_id")
        if not state_org or not str(state_org).strip():
            global_metrics_collector.record_security_failure()
            raise AgentTenantIsolationError(
                f"Missing organization_id in state before executing node '{self.contract.node_id}'."
            )

        if context:
            eb = state.get("evidence_bundle")
            eb_org = eb.get("organization_id") if isinstance(eb, dict) else getattr(eb, "organization_id", None)
            ra = state.get("risk_assessment")
            ra_org = ra.get("organization_id") if isinstance(ra, dict) else getattr(ra, "organization_id", None)

            try:
                validate_tenant_isolation(
                    context_organization_id=context.organization_id,
                    state_organization_id=str(state_org),
                    evidence_bundle_org=eb_org,
                    risk_assessment_org=ra_org,
                    evidence_references=state.get("evidence_references"),
                    risk_alert_references=state.get("risk_alert_references"),
                    recommendation_references=state.get("recommendation_references"),
                    approval_reference=state.get("approval_reference"),
                )
            except AgentTenantIsolationError:
                global_metrics_collector.record_security_failure()
                raise

        # 2. Authorization validation
        if context and not context.is_admin:
            caller_roles = set(context.roles) if context.roles else {context.role}
            if self.contract.required_roles and not caller_roles.intersection(set(self.contract.required_roles)):
                global_metrics_collector.record_security_failure()
                raise AgentToolAuthorizationError(
                    f"Caller role '{context.role}' is missing required roles {self.contract.required_roles} "
                    f"for node '{self.contract.node_id}'.",
                    details={"node_id": self.contract.node_id, "role": context.role, "required_roles": self.contract.required_roles},
                )
            if self.contract.required_permissions and not set(context.permissions).issuperset(set(self.contract.required_permissions)):
                global_metrics_collector.record_security_failure()
                raise AgentToolAuthorizationError(
                    f"Caller is missing required permissions {self.contract.required_permissions} "
                    f"for node '{self.contract.node_id}'.",
                    details={"node_id": self.contract.node_id, "required_permissions": self.contract.required_permissions},
                )
            if context.allowed_stages and self.contract.stage not in context.allowed_stages:
                global_metrics_collector.record_security_failure()
                raise AgentToolAuthorizationError(
                    f"Node stage '{self.contract.stage.value}' is not in context allowed stages.",
                    details={"node_id": self.contract.node_id, "stage": self.contract.stage.value},
                )

        # 3. Side-effect boundary guard
        if self.contract.is_side_effecting:
            side_effect_allowed = state.get("side_effect_allowed", False)
            requires_approval = state.get("requires_human_approval", False)
            if requires_approval:
                global_metrics_collector.record_security_failure()
                raise AgentApprovalBoundaryViolationError(
                    f"Node '{self.contract.node_id}' is SIDE_EFFECTING but requires verified human approval before execution.",
                    details={"node_id": self.contract.node_id},
                )
            if not side_effect_allowed:
                global_metrics_collector.record_security_failure()
                raise AgentApprovalBoundaryViolationError(
                    f"Node '{self.contract.node_id}' is SIDE_EFFECTING but side_effect_allowed governance flag is False.",
                    details={"node_id": self.contract.node_id, "side_effect_allowed": side_effect_allowed},
                )

        # 4. Mandatory input requirements check
        for required_key in self.contract.required_inputs:
            val = state.get(required_key)
            if val is None or val == "" or (isinstance(val, (dict, list)) and len(val) == 0):
                raise AgentMissingInputError(
                    f"Node '{self.contract.node_id}' requires input field '{required_key}', but it is missing or empty.",
                    details={"node_id": self.contract.node_id, "missing_key": required_key},
                )

        # Evidence requirements check
        if self.contract.requires_evidence:
            evidence_count = len(state.get("evidence_references", []))
            if state.get("evidence_bundle"):
                evidence_count = max(evidence_count, 1)
            if evidence_count < self.contract.minimum_evidence:
                raise AgentMissingInputError(
                    f"Node '{self.contract.node_id}' requires at least {self.contract.minimum_evidence} "
                    f"evidence item(s), found {evidence_count}.",
                    details={"node_id": self.contract.node_id, "found": evidence_count, "minimum": self.contract.minimum_evidence},
                )

        # Required reference check
        for ref_key in self.contract.required_references:
            refs = state.get("input_references", {})
            evidence_refs = state.get("evidence_references", [])
            if ref_key not in refs and ref_key not in evidence_refs:
                raise AgentMissingInputError(
                    f"Node '{self.contract.node_id}' requires reference '{ref_key}', but it is not bound in state.",
                    details={"node_id": self.contract.node_id, "required_reference": ref_key},
                )

        # 5. Execution limits check
        max_steps = context.max_steps if context else 25
        step_count = state.get("step_count", 0)
        if step_count >= max_steps:
            global_metrics_collector.record_routing_failure()
            raise AgentMaxStepsExceededError(
                f"Maximum step count ({max_steps}) reached before executing '{self.contract.node_id}'.",
                details={"node_id": self.contract.node_id, "step_count": step_count, "max_steps": max_steps},
            )

        # 6. State integrity hash before invocation
        input_state_hash = compute_state_hash(state)

        run_id = str(state.get("run_id", "run_unknown"))
        actor_id = str(state.get("actor_id", "actor_unknown"))
        request_id = str(state.get("request_id", "req_unknown"))
        correlation_id = str(state.get("correlation_id", "corr_unknown"))
        trace_id = str(state.get("trace_id", "trace_unknown"))
        execution_id = str(state.get("execution_id", run_id))

        max_retries = context.max_retries if context else 3
        timeout_seconds = (
            self.timeout_seconds
            if self.timeout_seconds is not None
            else (context.timeout_seconds if context else 120.0)
        )
        attempt = 1

        # 7. Execution and Bounded Retry Loop
        while True:
            start_time = time.perf_counter()
            try:
                # Invoke handler under timeout guard
                if timeout_seconds and timeout_seconds < 600.0:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(self.handler, state)
                        try:
                            updates = future.result(timeout=timeout_seconds)
                        except concurrent.futures.TimeoutError as te:
                            global_metrics_collector.record_node_timeout(self.contract.node_id)
                            raise AgentTimeoutError(
                                f"Node '{self.contract.node_id}' timed out after {timeout_seconds}s.",
                                details={"node_id": self.contract.node_id, "timeout_seconds": timeout_seconds},
                            ) from te
                else:
                    updates = self.handler(state)

                duration_ms = (time.perf_counter() - start_time) * 1000

                # 8. Output permission validation
                if self.contract.allowed_outputs:
                    allowed_set = set(self.contract.allowed_outputs)
                    # Standard lifecycle & telemetry fields are always permitted
                    allowed_set.update({
                        "current_stage",
                        "current_node",
                        "step_count",
                        "status",
                        "metadata",
                        "warnings",
                        "route_history",
                        "completed_at",
                        "termination_reason",
                        "selected_route",
                        "next_node",
                        "route_reason",
                    })
                    for out_key in updates.keys():
                        if out_key not in allowed_set:
                            raise AgentStateOwnershipViolationError(
                                f"Node '{self.contract.node_id}' produced output key '{out_key}' "
                                f"which is not in declared allowed_outputs {self.contract.allowed_outputs}.",
                                details={"node_id": self.contract.node_id, "unauthorized_key": out_key},
                            )

                # Compute output state hash
                merged_state = {**state, **updates}
                output_state_hash = compute_state_hash(merged_state)

                # Record legacy telemetry
                telemetry_success = NodeExecutionTelemetry(
                    run_id=run_id,
                    organization_id=str(state_org),
                    actor_id=actor_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    node_name=self.contract.node_id,
                    duration_ms=duration_ms,
                    status="SUCCESS",
                    step_count=step_count + 1,
                    retry_count=attempt - 1,
                    stage=self.contract.stage.value,
                )
                AgentObservability.emit_node_telemetry(telemetry_success)

                # Record Step 10 strongly typed AgentRunTelemetry
                run_telemetry = AgentRunTelemetry(
                    organization_id=str(state_org),
                    agent_run_id=run_id,
                    execution_id=execution_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    node_id=self.contract.node_id,
                    stage=self.contract.stage.value,
                    attempt=attempt,
                    status="SUCCESS",
                    duration_ms=round(duration_ms, 2),
                    retry_count=attempt - 1,
                    selected_route=updates.get("selected_route") or updates.get("next_node"),
                    input_state_hash=input_state_hash,
                    output_state_hash=output_state_hash,
                    metadata={"step_count": step_count + 1},
                )
                AgentObservability.record_run_telemetry(run_telemetry)

                return updates

            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000
                category = categorize_error(exc)
                retryable = is_retryable_error(exc)
                error_code = getattr(exc, "error_code", "AGENT_NODE_EXECUTION_ERROR")

                # If security or tenant error, immediately record security failure metric
                if category in (AgentErrorCategory.SECURITY_ERROR, AgentErrorCategory.TENANT_ISOLATION_ERROR):
                    global_metrics_collector.record_security_failure()

                # Check if retry is allowed
                if retryable and attempt < max_retries:
                    global_metrics_collector.record_node_retry(self.contract.node_id)
                    backoff = self.retry_policy.compute_backoff(attempt)

                    telemetry_retry = AgentRunTelemetry(
                        organization_id=str(state_org),
                        agent_run_id=run_id,
                        execution_id=execution_id,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        trace_id=trace_id,
                        node_id=self.contract.node_id,
                        stage=self.contract.stage.value,
                        attempt=attempt,
                        status="RECOVERABLE_FAILURE",
                        duration_ms=round(duration_ms, 2),
                        retry_count=attempt,
                        error_code=error_code,
                        error_category=category.value,
                        input_state_hash=input_state_hash,
                        metadata={"backoff_delay_seconds": backoff},
                    )
                    AgentObservability.record_run_telemetry(telemetry_retry)

                    if backoff > 0:
                        time.sleep(backoff)
                    attempt += 1
                    continue

                # Not retryable or budget exhausted -> Record failure telemetry and raise
                telemetry_failure = NodeExecutionTelemetry(
                    run_id=run_id,
                    organization_id=str(state_org),
                    actor_id=actor_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    node_name=self.contract.node_id,
                    duration_ms=duration_ms,
                    status="FAILED",
                    error_code=error_code,
                    step_count=step_count,
                    retry_count=attempt - 1,
                    stage=self.contract.stage.value,
                )
                AgentObservability.emit_node_telemetry(telemetry_failure)

                final_run_telemetry = AgentRunTelemetry(
                    organization_id=str(state_org),
                    agent_run_id=run_id,
                    execution_id=execution_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    node_id=self.contract.node_id,
                    stage=self.contract.stage.value,
                    attempt=attempt,
                    status="FAILED",
                    duration_ms=round(duration_ms, 2),
                    retry_count=attempt - 1,
                    error_code=error_code,
                    error_category=category.value,
                    input_state_hash=input_state_hash,
                    metadata={"error_message": str(exc)},
                )
                AgentObservability.record_run_telemetry(final_run_telemetry)

                raise
