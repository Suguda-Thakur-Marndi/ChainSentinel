"""Standardized execution harness and policy enforcement wrapper for LangGraph agent nodes.

Guarantees that every node execution is validated against tenant boundaries, caller authorization,
mandatory input contracts, evidence requirements, execution step limits, and state ownership,
while emitting structured, credential-scrubbed observability metrics.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphStateDict,
    AgentStage,
    NodeContract,
)
from app.agents.errors import (
    AgentApprovalBoundaryViolationError,
    AgentMaxStepsExceededError,
    AgentMissingInputError,
    AgentNodeExecutionError,
    AgentStateOwnershipViolationError,
    AgentTenantIsolationError,
    AgentToolAuthorizationError,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.security import validate_tenant_isolation


class NodeExecutionWrapper:
    """Harness wrapping a node handler with pre/post-execution safeguards and telemetry."""

    def __init__(
        self,
        contract: NodeContract,
        handler: Callable[[AgentGraphStateDict], Dict[str, Any]],
    ) -> None:
        self.contract = contract
        self.handler = handler

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
            AgentNodeExecutionError: On unhandled internal execution failures.
        """
        # 1. Tenant validation
        state_org = state.get("organization_id")
        if not state_org or not str(state_org).strip():
            raise AgentTenantIsolationError(
                f"Missing organization_id in state before executing node '{self.contract.node_id}'."
            )

        if context:
            eb = state.get("evidence_bundle")
            eb_org = eb.get("organization_id") if isinstance(eb, dict) else getattr(eb, "organization_id", None)
            ra = state.get("risk_assessment")
            ra_org = ra.get("organization_id") if isinstance(ra, dict) else getattr(ra, "organization_id", None)

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

        # 2. Authorization validation
        if context and not context.is_admin:
            caller_roles = set(context.roles) if context.roles else {context.role}
            if self.contract.required_roles and not caller_roles.intersection(set(self.contract.required_roles)):
                raise AgentToolAuthorizationError(
                    f"Caller role '{context.role}' is missing required roles {self.contract.required_roles} "
                    f"for node '{self.contract.node_id}'.",
                    details={"node_id": self.contract.node_id, "role": context.role, "required_roles": self.contract.required_roles},
                )
            if self.contract.required_permissions and not set(context.permissions).issuperset(set(self.contract.required_permissions)):
                raise AgentToolAuthorizationError(
                    f"Caller is missing required permissions {self.contract.required_permissions} "
                    f"for node '{self.contract.node_id}'.",
                    details={"node_id": self.contract.node_id, "required_permissions": self.contract.required_permissions},
                )
            if context.allowed_stages and self.contract.stage not in context.allowed_stages:
                raise AgentToolAuthorizationError(
                    f"Node stage '{self.contract.stage.value}' is not in context allowed stages.",
                    details={"node_id": self.contract.node_id, "stage": self.contract.stage.value},
                )

        # 3. Side-effect boundary guard
        if self.contract.is_side_effecting:
            side_effect_allowed = state.get("side_effect_allowed", False)
            requires_approval = state.get("requires_human_approval", False)
            if requires_approval:
                raise AgentApprovalBoundaryViolationError(
                    f"Node '{self.contract.node_id}' is SIDE_EFFECTING but requires verified human approval before execution.",
                    details={"node_id": self.contract.node_id},
                )
            if not side_effect_allowed:
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
            raise AgentMaxStepsExceededError(
                f"Maximum step count ({max_steps}) reached before executing '{self.contract.node_id}'.",
                details={"node_id": self.contract.node_id, "step_count": step_count, "max_steps": max_steps},
            )

        # 6. Handler invocation with telemetry
        start_time = time.perf_counter()
        run_id = str(state.get("run_id", "run_unknown"))
        actor_id = str(state.get("actor_id", "actor_unknown"))
        request_id = str(state.get("request_id", "req_unknown"))
        correlation_id = str(state.get("correlation_id", "corr_unknown"))
        trace_id = str(state.get("trace_id", "trace_unknown"))

        try:
            updates = self.handler(state)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # 7. Output permission validation
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
                })
                for out_key in updates.keys():
                    if out_key not in allowed_set:
                        raise AgentStateOwnershipViolationError(
                            f"Node '{self.contract.node_id}' produced output key '{out_key}' "
                            f"which is not in declared allowed_outputs {self.contract.allowed_outputs}.",
                            details={"node_id": self.contract.node_id, "unauthorized_key": out_key},
                        )

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
            )
            AgentObservability.emit_node_telemetry(telemetry_success)
            return updates

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            error_code = getattr(exc, "error_code", "AGENT_NODE_EXECUTION_ERROR")
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
            )
            AgentObservability.emit_node_telemetry(telemetry_failure)
            raise
