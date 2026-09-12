"""LangGraph node implementation for the Verification Agent (Phase 18).

Responsible for:
- Consuming authoritative ActionResult and operational context from state
- Constructing and validating a deterministic VerificationCommand
- Invoking the VerificationAgent orchestrator
- Producing strongly typed VerificationResult updates for AgentGraphState
- Halting pipeline at Stage VERIFICATION -> TERMINATION (no autonomous remediation loops)
- Emitting node execution telemetry and audit records
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.contracts import (
    AgentFinding,
    AgentGraphStateDict,
    AgentStage,
    NodeContract,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.verification.agent import VerificationAgent
from app.agents.verification.contract import (
    VerificationCommand,
    VerificationResultPayload,
    VerificationStatus,
)
from app.agents.verification.errors import (
    VerificationActionNotExecutedError,
    VerificationActionNotFoundError,
    VerificationAgentError,
    VerificationTenantIsolationError,
)
from app.db.unit_of_work import UnitOfWork


logger = logging.getLogger("riskwise.agents.verification.node")


VERIFICATION_NODE_CONTRACT = NodeContract(
    node_id="verification_agent",
    name="Verification Agent Node",
    description="Deterministically verifies whether executed operational actions achieved their intended real-world outcome.",
    stage=AgentStage.VERIFICATION,
    is_side_effecting=False,
    input_keys=["action_result", "action_id", "organization_id"],
    output_keys=[
        "verification_id",
        "verification_reference",
        "verification_result",
        "verification_status",
        "findings",
        "structured_findings",
        "current_stage",
        "current_node",
        "selected_route",
        "route_reason",
        "step_count",
    ],
)


def verification_node(
    state: AgentGraphStateDict,
    uow: Optional[UnitOfWork] = None,
    agent: Optional[VerificationAgent] = None,
) -> Dict[str, Any]:
    """Execute the Verification Agent node in the LangGraph pipeline."""
    start_time = time.perf_counter()
    telemetry_status = "SUCCESS"
    error_code: Optional[str] = None
    verification_id_for_telemetry = "unknown_verification"

    org_id = str(state.get("organization_id", "")).strip()
    run_id = str(state.get("run_id", "run_verif_default"))
    actor_id = str(state.get("actor_id", "user_operator"))
    correlation_id = str(state.get("correlation_id", "corr_verif"))
    trace_id = str(state.get("trace_id", "trace_verif"))

    try:
        # 1. Tenant boundary enforcement
        if not org_id:
            raise VerificationTenantIsolationError("organization_id is missing from agent state.")

        # 2. Extract executed action context
        action_result = state.get("action_result")
        action_id = state.get("action_id")

        if not action_id and isinstance(action_result, dict):
            action_id = action_result.get("action_id")

        if not action_id:
            raise VerificationActionNotFoundError(
                "Cannot perform verification without prior executed action_id in state."
            )

        # 3. Determine action parameters and metadata
        action_res_dict = action_result if isinstance(action_result, dict) else {}
        action_type_raw = action_res_dict.get("action_type") or "SHIPMENT_REROUTE"
        try:
            action_type = ActionType(action_type_raw)
        except ValueError:
            action_type = ActionType.SHIPMENT_REROUTE

        target_entity_type_raw = action_res_dict.get("target_entity_type") or "SHIPMENT"
        try:
            target_entity_type = TargetEntityType(target_entity_type_raw)
        except ValueError:
            target_entity_type = TargetEntityType.SHIPMENT

        target_entity_id = str(
            action_res_dict.get("target_entity_id")
            or state.get("target_reference")
            or state.get("shipment_id")
            or "target_default"
        )

        exec_details = action_res_dict.get("execution_details") or {}
        action_params = dict(exec_details) if isinstance(exec_details, dict) else {}

        # Parse executed_at
        raw_exec_at = action_res_dict.get("executed_at")
        if isinstance(raw_exec_at, str):
            try:
                exec_at = datetime.fromisoformat(raw_exec_at)
            except Exception:
                exec_at = datetime.now(timezone.utc)
        elif isinstance(raw_exec_at, datetime):
            exec_at = raw_exec_at
        else:
            exec_at = datetime.now(timezone.utc)

        command = VerificationCommand(
            action_id=str(action_id),
            decision_id=state.get("decision_id") or action_res_dict.get("decision_id"),
            approval_id=state.get("approval_id") or action_res_dict.get("approval_id"),
            organization_id=org_id,
            action_type=action_type,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            action_parameters=action_params,
            action_executed_at=exec_at,
            observation_window_seconds=int(state.get("observation_window_seconds", 86400)),
            trace_id=trace_id,
        )
        verification_id_for_telemetry = command.verification_id or "pending_verif"

        # 4. Invoke VerificationAgent
        if agent is not None:
            verif_agent = agent
        elif uow is not None:
            verif_agent = VerificationAgent(db=uow.session)
        else:
            raise VerificationAgentError("No database session or UnitOfWork provided to verification node.")

        payload = verif_agent.execute_verification(command=command)

        # 5. Assemble state update
        existing_findings = list(state.get("structured_findings", []))
        verif_finding = AgentFinding(
            finding_id=f"find_verif_{payload.verification_id[:12]}",
            category="OUTCOME_VERIFICATION",
            title=f"Verification: {payload.action_type.value}",
            summary=f"Action '{payload.action_type.value}' outcome status: {payload.status.value}. Verified: {payload.verified}.",
            created_by_node="verification_agent",
            confidence=1.0 if payload.verified else 0.8,
        )
        existing_findings.append(verif_finding.model_dump(mode="json"))

        current_findings = dict(state.get("findings", {}))
        current_findings["verification"] = {
            "verification_id": payload.verification_id,
            "status": payload.status.value,
            "verified": payload.verified,
            "fingerprint": payload.fingerprint,
            "summary": payload.observation_summary,
        }

        step_count = state.get("step_count", 0) + 1
        warnings = list(state.get("warnings", []))
        warnings.append(
            f"Verification complete: status='{payload.status.value}', verified={payload.verified}."
        )

        update_payload: Dict[str, Any] = {
            "verification_id": payload.verification_id,
            "verification_reference": f"{org_id}:verification:{payload.verification_id}",
            "verification_result": payload.model_dump(mode="json"),
            "verification_status": payload.status.value,
            "structured_findings": existing_findings,
            "findings": current_findings,
            "current_stage": AgentStage.VERIFICATION.value,
            "current_node": "verification_agent",
            "selected_route": "termination",
            "route_reason": f"Operational verification completed with status '{payload.status.value}'. Pipeline halted.",
            "step_count": step_count,
            "warnings": warnings,
        }

        return update_payload

    except VerificationAgentError as vae:
        telemetry_status = "FAILED"
        error_code = vae.error_code
        raise
    except Exception as exc:
        telemetry_status = "FAILED"
        error_code = "VERIFICATION_NODE_UNEXPECTED_ERROR"
        raise VerificationAgentError(
            f"Verification node failed unexpectedly: {exc}", error_code=error_code
        ) from exc
    finally:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        try:
            telemetry = NodeExecutionTelemetry(
                node_name="verification_agent",
                stage=AgentStage.VERIFICATION,
                run_id=run_id,
                organization_id=org_id or "unknown",
                actor_id=actor_id,
                request_id=str(state.get("request_id", "req_verif_default")),
                correlation_id=correlation_id,
                trace_id=trace_id,
                status=telemetry_status,
                duration_ms=latency_ms,
                error_code=error_code,
                metadata={
                    "verification_id": verification_id_for_telemetry,
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                },
            )
            AgentObservability.emit_node_telemetry(telemetry)
        except Exception:
            pass
