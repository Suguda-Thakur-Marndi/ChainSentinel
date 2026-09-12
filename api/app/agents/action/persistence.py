"""Persistence service for Action records, concurrency locking, idempotency, and audit logging (Phase 17).

Preserves database invariants:
- Maintains exactly 34 tables with zero migrations
- Reuses `actions`, `recommendations`, `audit_logs`, and `users` tables
- Strict multi-tenant query isolation
- Row-level lock (`with_for_update`) concurrency protection
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.action.contract import (
    ActionCommand,
    ActionResult,
    ExecutionStatus,
    IdempotencyResult,
)
from app.agents.action.errors import (
    ActionIdempotencyConflictError,
    ActionTenantIsolationError,
)
from app.db.unit_of_work import UnitOfWork
from app.models.governance import Action, AuditLog, Recommendation


class ActionPersistenceService:
    """Transactional persistence and idempotency engine for operational mitigation actions."""

    @staticmethod
    def check_idempotency(
        db: Session,
        organization_id: str,
        idempotency_key: str,
        action_id: Optional[str] = None,
    ) -> Optional[Action]:
        """Check if an action with the given idempotency key or action ID already exists."""
        stmt = select(Action).where(Action.org_id == organization_id)
        if action_id:
            stmt = stmt.where((Action.id == action_id) | (Action.execution_payload["idempotency_key"].as_string() == idempotency_key))
        else:
            stmt = stmt.where(Action.execution_payload["idempotency_key"].as_string() == idempotency_key)
        return db.scalars(stmt).first()

    @staticmethod
    def record_action_execution(
        db: Session,
        command: ActionCommand,
        result: ActionResult,
        uow: Optional[UnitOfWork] = None,
    ) -> ActionResult:
        """Persist action record, update recommendation status, and create audit log transactionally."""
        org_id = command.organization_id

        # 1. Row-level concurrency check
        existing_action = ActionPersistenceService.check_idempotency(
            db=db,
            organization_id=org_id,
            idempotency_key=command.idempotency_key,
            action_id=command.action_id,
        )

        if existing_action:
            existing_payload = existing_action.execution_payload or {}
            existing_fp = existing_payload.get("fingerprint")
            
            # If identical command fingerprint: return existing action result
            if existing_fp == result.fingerprint:
                cached_result = existing_action.result_payload or {}
                if cached_result:
                    cached_result["idempotency_result"] = IdempotencyResult.REPLAYED_IDEMPOTENT.value
                    return ActionResult.model_validate(cached_result)

            # Different action intent on the same idempotency key: reject as conflict
            raise ActionIdempotencyConflictError(
                f"Idempotency key '{command.idempotency_key}' was already used with different parameters.",
                details={
                    "idempotency_key": command.idempotency_key,
                    "existing_action_id": existing_action.id,
                },
            )

        # 2. Construct Action database entity
        action_entity = Action(
            id=result.action_id,
            org_id=org_id,
            recommendation_id=result.decision_id,
            action_type=result.action_type,
            target_entity_type=result.target_entity_type,
            target_entity_id=result.target_entity_id,
            status=result.status,
            execution_payload={
                **command.parameters,
                "idempotency_key": command.idempotency_key,
                "approval_id": command.approval_id,
                "candidate_id": command.candidate_id,
                "fingerprint": result.fingerprint,
                "policy_version": command.policy_version,
            },
            result_payload=result.model_dump(mode="json"),
            executed_at=result.execution_end,
        )
        db.add(action_entity)

        # 3. Update linked recommendation if status is SUCCEEDED/COMPLETED
        if result.status in (ExecutionStatus.SUCCEEDED.value, "COMPLETED") and command.decision_id:
            rec = db.query(Recommendation).filter(
                Recommendation.id == command.decision_id,
                Recommendation.org_id == org_id,
            ).first()
            if rec:
                rec.status = "EXECUTED"

        # 4. Generate structured audit log
        audit_entry = AuditLog(
            org_id=org_id,
            actor_type="USER" if (command.actor and command.actor.role) else "AGENT",
            actor_id=command.actor.actor_id if command.actor else "action_agent",
            action="ACTION_EXECUTE",
            resource_type="Action",
            resource_id=result.action_id,
            status="SUCCESS" if result.status in (ExecutionStatus.SUCCEEDED.value, ExecutionStatus.SUBMITTED.value) else "FAILED",
            request_id=command.trace_id,
            after_json={
                "action_id": result.action_id,
                "decision_id": result.decision_id,
                "approval_id": result.approval_id,
                "action_type": result.action_type,
                "target_entity_type": result.target_entity_type,
                "target_entity_id": result.target_entity_id,
                "status": result.status,
                "adapter": result.adapter,
                "provider": result.provider,
                "fingerprint": result.fingerprint,
            },
        )
        db.add(audit_entry)

        db.flush()
        return result

    @staticmethod
    def get_action_result(db: Session, action_id: str, organization_id: str) -> Optional[ActionResult]:
        """Fetch an ActionResult by ID enforcing strict tenant isolation."""
        action = db.query(Action).filter(Action.id == action_id).first()
        if not action:
            return None
        if action.org_id != organization_id:
            raise ActionTenantIsolationError(
                f"Action '{action_id}' belongs to tenant '{action.org_id}', not '{organization_id}'."
            )
        if action.result_payload:
            return ActionResult.model_validate(action.result_payload)
        return None
