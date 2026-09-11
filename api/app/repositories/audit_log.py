"""Repository for AuditLog entity data access."""
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.errors import ImmutableResourceError
from app.models.governance import AuditLog
from app.repositories.base import BaseRepository

AUDIT_LOG_SORT_ALLOWLIST = {
    "timestamp": AuditLog.timestamp,
    "action": AuditLog.action,
    "resource_type": AuditLog.resource_type,
}

AUDIT_LOG_FILTER_ALLOWLIST = {
    "action": AuditLog.action,
    "resource_type": AuditLog.resource_type,
    "actor_id": AuditLog.actor_id,
    "status": AuditLog.status,
    "timestamp_after": AuditLog.timestamp,
    "timestamp_before": AuditLog.timestamp,
}


class AuditLogRepository(BaseRepository[AuditLog]):
    """Data access repository for AuditLog entities (Tenant scope, Append-Only Ledger)."""

    def __init__(self, session: Session):
        super().__init__(AuditLog, session)

    def append_log(
        self,
        org_id: Optional[str],
        actor_id: Optional[str],
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        status: str = "SUCCESS",
        actor_type: str = "USER",
        before_json: Optional[dict[str, Any]] = None,
        after_json: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
        auto_commit: bool = False,
    ) -> AuditLog:
        """Append an immutable audit entry to the ledger."""
        entry = AuditLog(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            request_id=request_id,
            before_json=before_json,
            after_json=after_json,
        )
        return self.create(entry, auto_commit=auto_commit)

    def update(self, entity: AuditLog, auto_commit: bool = True) -> AuditLog:
        """Audit logs are strictly immutable."""
        raise ImmutableResourceError("Audit log records are immutable and cannot be updated")

    def delete(self, id: str, org_id: Optional[str] = None, auto_commit: bool = True) -> bool:
        """Audit logs are strictly immutable."""
        raise ImmutableResourceError("Audit log records are immutable and cannot be deleted")
