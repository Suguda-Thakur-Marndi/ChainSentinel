from __future__ import annotations

"""Service-level audit logging hook ensuring secret scrubbing and ledger immutability."""
import re
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.db.unit_of_work import UnitOfWork

from app.models.governance import AuditLog

# Regex pattern identifying keys that must never be logged in cleartext
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|api_key|credentials|authorization|cookie|access_token|refresh_token)",
    re.IGNORECASE,
)


def sanitize_payload(payload: Any) -> Any:
    """Recursively scrub sensitive credential keys from before/after audit payloads."""
    if isinstance(payload, (datetime, date)):
        return payload.isoformat()
    elif isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    return payload


class AuditService:
    """Centralized service for emitting immutable audit log events across the application."""

    @staticmethod
    def log_event(
        uow: UnitOfWork,
        action: str,
        resource_type: str,
        org_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        actor_type: str = "USER",
        resource_id: Optional[str] = None,
        status: str = "SUCCESS",
        before_data: Optional[dict[str, Any]] = None,
        after_data: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
        auto_commit: bool = False,
    ) -> AuditLog:
        """Sanitize payloads and persist an immutable audit log entry via the active Unit of Work."""
        clean_before = sanitize_payload(before_data) if before_data is not None else None
        clean_after = sanitize_payload(after_data) if after_data is not None else None

        return uow.audit_logs.append_log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            request_id=request_id,
            before_json=clean_before,
            after_json=clean_after,
            auto_commit=auto_commit,
        )
