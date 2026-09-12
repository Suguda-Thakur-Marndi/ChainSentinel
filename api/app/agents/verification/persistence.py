"""Authoritative persistence and idempotency manager for the Verification Agent (Phase 18).

Reuses the existing `verification_results` table with zero schema changes:
- `id`
- `action_id`
- `verified`
- `risk_score_before`
- `risk_score_after`
- `observation_summary`
- `verified_at`

Persists structured verification metadata, fingerprints, and status within `observation_summary`.
Enforces idempotency:
- Replay with identical fingerprint returns the existing result without duplicate writes.
- Upgraded evidence with a new fingerprint updates the result and emits an audit record.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.action.contract import ActionType, TargetEntityType
from app.agents.verification.contract import (
    IntendedOutcome,
    ObservedOutcome,
    VerificationResultPayload,
    VerificationStatus,
)
from app.models.governance import Action, AuditLog, VerificationResult


def _serialize_observation_summary(payload: VerificationResultPayload) -> str:
    """Pack status, fingerprint, summary, and provenance into observation_summary (<= 1000 chars)."""
    meta = {
        "status": payload.status.value,
        "fingerprint": payload.fingerprint,
        "verification_id": payload.verification_id,
        "evidence_count": payload.observed_outcome.evidence_count,
        "highest_precedence": (
            payload.observed_outcome.highest_precedence.value
            if payload.observed_outcome.highest_precedence
            else None
        ),
        "summary": payload.observation_summary[:400],
    }
    raw_json = json.dumps(meta, separators=(",", ":"))
    if len(raw_json) > 1000:
        meta["summary"] = meta["summary"][:200]
        raw_json = json.dumps(meta, separators=(",", ":"))
    return raw_json[:1000]


def _parse_observation_summary(
    raw_summary: Optional[str],
) -> Dict[str, Any]:
    """Parse structured metadata from observation_summary."""
    if not raw_summary:
        return {}
    try:
        return json.loads(raw_summary)
    except Exception:
        return {"summary": raw_summary}


class VerificationPersistenceManager:
    """Manages transactional persistence, replay idempotency, and audit logging."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def load_existing(self, action_id: str) -> Optional[VerificationResult]:
        """Find existing verification result for an action."""
        return (
            self.db.execute(
                select(VerificationResult).where(VerificationResult.action_id == action_id)
            )
            .scalars()
            .first()
        )

    def persist(
        self,
        payload: VerificationResultPayload,
    ) -> Tuple[VerificationResult, bool]:
        """Persist or idempotently return the verification result.
        
        Returns:
            (VerificationResult, is_new_or_updated: bool)
        """
        existing = self.load_existing(payload.action_id)

        packed_summary = _serialize_observation_summary(payload)

        if existing:
            meta = _parse_observation_summary(existing.observation_summary)
            existing_fp = meta.get("fingerprint")
            if existing_fp == payload.fingerprint:
                # Idempotent replay: exact same fingerprint
                return existing, False

            # Update existing record with new evidence / outcome
            existing.verified = payload.verified
            existing.risk_score_before = payload.risk_score_before
            existing.risk_score_after = payload.risk_score_after
            existing.observation_summary = packed_summary
            existing.verified_at = payload.verified_at or datetime.now(timezone.utc)
            self.db.flush()

            self._record_audit(payload, action_name="VERIFICATION_UPDATED")
            self.db.commit()
            return existing, True

        # Insert new verification result
        rec = VerificationResult(
            id=payload.verification_id,
            action_id=payload.action_id,
            verified=payload.verified,
            risk_score_before=payload.risk_score_before,
            risk_score_after=payload.risk_score_after,
            observation_summary=packed_summary,
            verified_at=payload.verified_at or datetime.now(timezone.utc),
        )
        self.db.add(rec)
        self.db.flush()

        self._record_audit(payload, action_name="VERIFICATION_COMPLETED")
        self.db.commit()
        return rec, True

    def _record_audit(self, payload: VerificationResultPayload, action_name: str) -> None:
        """Create immutable audit trail record."""
        audit = AuditLog(
            org_id=payload.organization_id,
            actor_type="SYSTEM",
            actor_id="verification_agent",
            action=action_name,
            resource_type="VERIFICATION_RESULT",
            resource_id=payload.verification_id,
            status="SUCCESS",
            after_json={
                "verification_id": payload.verification_id,
                "action_id": payload.action_id,
                "status": payload.status.value,
                "verified": payload.verified,
                "fingerprint": payload.fingerprint,
                "action_type": payload.action_type.value,
                "target_entity_id": payload.target_entity_id,
                "evidence_count": payload.observed_outcome.evidence_count,
            },
        )
        self.db.add(audit)
        self.db.flush()
