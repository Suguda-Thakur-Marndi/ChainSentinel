"""Action Agent orchestrator for executing strictly approved operational mitigations (Phase 17).

Coordinates:
- Safety policy validation and action allowlist verification
- Mandatory human approval binding checks
- Target entity verification (shipment, carrier, facility, route)
- Idempotency evaluation (replay vs execution vs conflict)
- Allowlisted executor adapter execution
- Transactional persistence, audit trail generation, and finding assembly
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.action.contract import (
    ActionCommand,
    ActionResult,
    ExecutionStatus,
    IdempotencyResult,
    compute_action_fingerprint,
)
from app.agents.action.errors import ActionIdempotencyConflictError
from app.agents.action.executors import ActionExecutorRegistry
from app.agents.action.persistence import ActionPersistenceService
from app.agents.action.policy import ActionSafetyPolicy
from app.agents.contracts import AgentFinding
from app.db.unit_of_work import UnitOfWork


class ActionAgent:
    """Orchestrator for operational action execution."""

    def __init__(
        self,
        policy: Optional[ActionSafetyPolicy] = None,
        persistence: Optional[ActionPersistenceService] = None,
    ) -> None:
        self.policy = policy or ActionSafetyPolicy()
        self.persistence = persistence or ActionPersistenceService()

    def execute(
        self,
        command: ActionCommand,
        approval: Any,
        db: Optional[Session] = None,
        uow: Optional[UnitOfWork] = None,
    ) -> Tuple[ActionResult, List[AgentFinding]]:
        """Execute an approved operational command.

        Returns:
            Tuple of (ActionResult, List[AgentFinding]).
        """
        # 1. Policy allowlist verification
        spec = self.policy.validate_command_against_policy(command)

        # 2. Mandatory human approval binding verification
        self.policy.validate_approval(command, approval)

        # 3. Check idempotency if database session is provided
        if db:
            existing = self.persistence.check_idempotency(
                db=db,
                organization_id=command.organization_id,
                idempotency_key=command.idempotency_key,
                action_id=command.action_id,
            )
            if existing:
                existing_payload = existing.execution_payload or {}
                existing_fp = existing_payload.get("fingerprint")

                current_fp = compute_action_fingerprint(
                    organization_id=command.organization_id,
                    decision_id=command.decision_id,
                    approval_id=command.approval_id,
                    action_type=command.action_type.value,
                    target_entity_type=command.target_entity_type.value,
                    target_entity_id=command.target_entity_id,
                    parameters=command.parameters,
                    policy_version=command.policy_version,
                    approval_fingerprint=command.approval_fingerprint,
                )

                if existing_fp == current_fp and existing.result_payload:
                    cached_data = dict(existing.result_payload)
                    cached_data["idempotency_result"] = IdempotencyResult.REPLAYED_IDEMPOTENT.value
                    cached_res = ActionResult.model_validate(cached_data)

                    replay_finding = AgentFinding(
                        finding_id=f"find-act-idemp-{cached_res.action_id[:8]}",
                        category="ACTION_IDEMPOTENT_REPLAY",
                        title=f"Action Idempotent Replay: {cached_res.action_type}",
                        summary=f"Action '{cached_res.action_id}' replayed idempotently. No duplicate execution performed.",
                        severity="LOW",
                        confidence=1.0,
                        evidence_ids=[],
                        source_references=[f"action:{cached_res.action_id}"],
                        limitations=[],
                        created_by_node="action_agent",
                    )
                    return cached_res, [replay_finding]

                # Different action fingerprint on same idempotency key: reject as conflict!
                raise ActionIdempotencyConflictError(
                    f"Idempotency key '{command.idempotency_key}' was already used with different parameters.",
                    details={
                        "idempotency_key": command.idempotency_key,
                        "existing_action_id": existing.id,
                        "existing_fingerprint": existing_fp,
                        "current_fingerprint": current_fp,
                    },
                )

        # 4. Target entity verification (existence and tenant scoping)
        self.policy.validate_target_entity(command, db=db)

        # 5. Resolve allowlisted execution adapter
        executor = ActionExecutorRegistry.get_executor(command.action_type)

        # 6. Execute operational adapter
        result = executor.execute(command, db=db)

        # 7. Persist execution outcome and audit log
        if db:
            result = self.persistence.record_action_execution(
                db=db,
                command=command,
                result=result,
                uow=uow,
            )

        # 8. Assemble structured findings
        finding_cat = "ACTION_EXECUTED" if result.status in (ExecutionStatus.SUCCEEDED.value, ExecutionStatus.SUBMITTED.value) else "ACTION_FAILED"
        severity = "INFO" if result.status == ExecutionStatus.SUCCEEDED.value else ("MEDIUM" if result.status == ExecutionStatus.SUBMITTED.value else "HIGH")

        finding = AgentFinding(
            finding_id=f"find-act-exec-{result.action_id[:8]}",
            category=finding_cat,
            title=f"Action Execution: {result.action_type}",
            summary=(
                f"Operational action '{result.action_type}' for target '{result.target_entity_type}:{result.target_entity_id}' "
                f"executed with status '{result.status}' by adapter '{result.adapter}'."
            ),
            severity=severity,
            confidence=1.0,
            evidence_ids=[],
            source_references=[f"action:{result.action_id}", f"decision:{result.decision_id}", f"approval:{result.approval_id}"],
            limitations=[],
            created_by_node="action_agent",
        )

        return result, [finding]
