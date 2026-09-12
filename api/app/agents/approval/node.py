"""LangGraph execution node for the Human Approval governance boundary.

Enforces zero autonomous approval, explicit human sign-off capture, decision immutability,
and robust telemetry.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.approval.agent import HumanApprovalAgent
from app.agents.approval.contract import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
)
from app.agents.approval.errors import (
    ApprovalAgentError,
    ApprovalCandidateMismatchError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
)
from app.agents.approval.service import HumanApprovalService
from app.agents.contracts import (
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentStage,
    NodeContract,
    ToolSideEffectType,
    validate_no_sensitive_values,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.db.unit_of_work import UnitOfWork

# Node contract definition for LangGraph registration
HUMAN_APPROVAL_NODE_CONTRACT = NodeContract(
    node_id="human_approval",
    name="Human Approval Agent",
    description="Enforces human-in-the-loop governance sign-off on operational decision candidates.",
    stage=AgentStage.APPROVAL,
    is_side_effecting=False,
    side_effect_type=ToolSideEffectType.HUMAN_GOVERNED,
    input_keys=["decision_result", "decision_id", "decision_reference", "organization_id"],
    output_keys=[
        "approval_id",
        "approval_reference",
        "approval_result",
        "approval_status",
        "requires_human_approval",
        "side_effect_allowed",
        "current_stage",
        "current_node",
        "status",
        "step_count",
        "structured_findings",
        "warnings",
    ],
    requires_evidence=True,
    timeout_seconds=10.0,
    max_retries=0,
    retryable=False,
)


def human_approval_node(
    state: AgentGraphStateDict,
    service: Optional[HumanApprovalService] = None,
    uow: Optional[UnitOfWork] = None,
) -> Dict[str, Any]:
    """LangGraph node executing human approval governance evaluation.

    If no human approval input exists in state:
        Transitions to PENDING, sets requires_human_approval=True, halts execution.
    If human approval input exists in state:
        Validates actor RBAC and tenant, records decision (APPROVED or REJECTED).
    """
    start_time = time.perf_counter()
    telemetry_status = "SUCCESS"
    error_code: Optional[str] = None
    approval_id: Optional[str] = None
    candidate_id: Optional[str] = None

    run_id = str(state.get("run_id", "unknown_run"))
    org_id = state.get("organization_id")
    actor_id = str(state.get("actor_id", "unknown_actor"))
    request_id = str(state.get("request_id", "unknown_request"))
    correlation_id = str(state.get("correlation_id", "unknown_corr"))
    trace_id = str(state.get("trace_id", "unknown_trace"))

    try:
        # 1. Tenant validation
        if not org_id or not isinstance(org_id, str) or not org_id.strip():
            telemetry_status = "FAILED"
            error_code = "INVALID_TENANT"
            raise ApprovalTenantIsolationError("State organization_id is missing or empty.")

        org_clean = org_id.strip()

        # 2. Extract upstream decision context
        dec_res = state.get("decision_result")
        dec_ref = state.get("decision_reference")
        dec_id = state.get("decision_id") or (
            dec_res.get("decision_id") if isinstance(dec_res, dict) else (
                dec_ref.get("decision_id") if isinstance(dec_ref, dict) else None
            )
        )

        if not dec_id or not dec_res or not isinstance(dec_res, dict):
            telemetry_status = "FAILED"
            error_code = "MISSING_DECISION_CONTEXT"
            raise InvalidApprovalRequestError(
                "Upstream decision context (decision_result and decision_id) must be present in state."
            )

        # Cross-tenant decision validation
        dec_org = dec_res.get("organization_id")
        if dec_org and dec_org.strip() != org_clean:
            telemetry_status = "FAILED"
            error_code = "TENANT_MISMATCH"
            raise ApprovalTenantIsolationError(
                f"Upstream decision tenant '{dec_org}' does not match state tenant '{org_clean}'."
            )

        # 3. Extract target decision candidate
        pref_cand = dec_res.get("preferred_candidate")
        candidates = dec_res.get("candidates", [])
        target_cand = pref_cand or (candidates[0] if candidates else None)

        if not target_cand or not isinstance(target_cand, dict):
            telemetry_status = "FAILED"
            error_code = "MISSING_CANDIDATE"
            raise InvalidApprovalRequestError(
                "Upstream decision_result does not contain any valid candidate for approval."
            )

        candidate_id = target_cand.get("candidate_id")
        if not candidate_id:
            telemetry_status = "FAILED"
            error_code = "INVALID_CANDIDATE_ID"
            raise InvalidApprovalRequestError("Target candidate is missing candidate_id.")

        rec_id = target_cand.get("parameters", {}).get("recommendation_id") or target_cand.get("provenance", {}).get("source_recommendation_id")

        # 4. Assemble typed ApprovalRequest
        req = ApprovalRequest(
            organization_id=org_clean,
            decision_id=dec_id,
            decision_reference=dec_ref if isinstance(dec_ref, dict) else None,
            candidate_id=candidate_id,
            recommendation_id=rec_id,
            requester_id=actor_id,
            required_role="RiskManager",
            evidence_references=list(state.get("evidence_references", [])),
            constraints=list(dec_res.get("constraints", [])),
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # 5. Check for explicit human decision payload in state
        raw_decision_input = (
            state.get("human_approval_decision")
            or state.get("approval_input")
            or state.get("metadata", {}).get("human_approval_decision")
            or state.get("metadata", {}).get("approval_input")
        )
        decision_input: Optional[ApprovalDecisionInput] = None

        if raw_decision_input:
            if isinstance(raw_decision_input, ApprovalDecisionInput):
                decision_input = raw_decision_input
            elif isinstance(raw_decision_input, dict):
                actor_data = raw_decision_input.get("actor", {})
                if isinstance(actor_data, dict):
                    if "organization_id" not in actor_data or not actor_data["organization_id"]:
                        actor_data["organization_id"] = org_clean
                decision_input = ApprovalDecisionInput(
                    decision=ApprovalDecision(raw_decision_input["decision"]),
                    actor=ApprovalActor.model_validate(actor_data),
                    comments=raw_decision_input.get("comments"),
                    decided_at=raw_decision_input.get("decided_at"),
                )

        # 6. Execute HumanApprovalAgent
        agent = HumanApprovalAgent(service=service)
        result, findings = agent.evaluate(req, decision_input=decision_input, uow=uow)
        approval_id = result.approval_id

        # 7. Assemble state updates
        existing_findings = list(state.get("structured_findings", []))
        findings_serialized = [f.model_dump(mode="json") for f in findings]
        updated_findings = existing_findings + findings_serialized

        current_findings = dict(state.get("findings", {}))
        current_findings["approval"] = {
            "approval_id": result.approval_id,
            "status": result.status,
            "candidate_id": result.candidate_id,
            "decision_id": result.decision_id,
            "actor_id": result.actor_id,
            "fingerprint": result.fingerprint,
        }

        step_count = state.get("step_count", 0) + 1
        warnings = list(state.get("warnings", []))

        update_payload: Dict[str, Any] = {
            "approval_id": result.approval_id,
            "approval_reference": f"{org_clean}:approval:{result.approval_id}",
            "approval_result": result.model_dump(mode="json"),
            "approval_status": result.status,
            "requires_human_approval": result.requires_human_approval,
            "side_effect_allowed": result.side_effect_allowed,
            "structured_findings": updated_findings,
            "findings": current_findings,
            "current_stage": AgentStage.APPROVAL.value,
            "current_node": "human_approval",
            "step_count": step_count,
            "warnings": warnings,
        }

        if result.status == ApprovalStatus.PENDING.value:
            warnings.append(
                f"Human approval required for candidate '{candidate_id}'. Halting execution for governance review."
            )
            update_payload["status"] = AgentLifecycleStatus.WAITING_FOR_APPROVAL.value
            update_payload["selected_route"] = "termination"
            update_payload["route_reason"] = "Awaiting explicit human sign-off."
        elif result.status == ApprovalStatus.APPROVED.value:
            warnings.append(f"Human approval granted by actor '{result.actor_id}'. Ready for action stage.")
            update_payload["selected_route"] = "termination"
            update_payload["route_reason"] = "Candidate approved by human authority. Ready for action stage."
        elif result.status == ApprovalStatus.REJECTED.value:
            warnings.append(f"Candidate rejected by human approver '{result.actor_id}'. Halting execution.")
            update_payload["selected_route"] = "termination"
            update_payload["route_reason"] = "Candidate explicitly rejected by human authority."
        else:
            update_payload["selected_route"] = "termination"
            update_payload["route_reason"] = f"Approval lifecycle state: {result.status}"

        return update_payload

    except (ApprovalAgentError, ApprovalTenantIsolationError, InvalidApprovalRequestError) as aae:
        telemetry_status = "FAILED"
        if not error_code or error_code == "NONE":
            error_code = getattr(aae, "error_code", "APPROVAL_ERROR")
        raise
    except Exception as exc:
        telemetry_status = "FAILED"
        error_code = "APPROVAL_NODE_UNEXPECTED_ERROR"
        raise ApprovalAgentError(f"Unexpected error in human_approval_node: {str(exc)}") from exc
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        telemetry = NodeExecutionTelemetry(
            node_name="human_approval",
            stage=AgentStage.APPROVAL,
            run_id=run_id,
            organization_id=org_id or "unknown",
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            status=telemetry_status,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata={
                "approval_id": approval_id,
                "candidate_id": candidate_id,
            },
        )
        AgentObservability.emit_node_telemetry(telemetry)
