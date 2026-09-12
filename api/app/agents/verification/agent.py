"""Core orchestrator for the RiskWise Verification Agent (Phase 18).

Coordinates:
- Verification policy evaluation
- Authoritative evidence ingestion
- Outcome comparison (intended vs observed)
- Replay idempotency and transactional persistence
- Observability and audit emission
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.agents.action.contract import TargetEntityType
from app.agents.verification.contract import (
    IntendedOutcome,
    ObservedEvidenceItem,
    ObservedOutcome,
    VerificationCommand,
    VerificationResultPayload,
    VerificationStatus,
    compute_verification_fingerprint,
    generate_deterministic_verification_id,
)
from app.agents.verification.errors import VerificationAgentError
from app.agents.verification.persistence import VerificationPersistenceManager
from app.agents.verification.policy import VerificationPolicy


logger = logging.getLogger("riskwise.agents.verification")


class VerificationAgent:
    """Production-grade verification agent establishing post-action operational truth."""

    def __init__(self, db: Session, policy_version: str = "1.0") -> None:
        self.db = db
        self.policy_version = policy_version
        self.policy = VerificationPolicy(db, policy_version=policy_version)
        self.persistence = VerificationPersistenceManager(db)

    def execute_verification(
        self,
        command: VerificationCommand,
        extra_evidence: Optional[List[ObservedEvidenceItem]] = None,
    ) -> VerificationResultPayload:
        """Run end-to-end outcome verification for an executed action."""
        start_time = time.monotonic()
        logger.info(
            "Initiating verification",
            extra={
                "action_id": command.action_id,
                "organization_id": command.organization_id,
                "action_type": command.action_type.value,
                "target_entity_id": command.target_entity_id,
            },
        )

        try:
            # 1. Deterministic evaluation through policy
            payload = self.policy.evaluate(command=command, extra_evidence=extra_evidence)

            # 2. Transactional persistence & idempotency
            _, is_new = self.persistence.persist(payload)

            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            logger.info(
                "Verification completed",
                extra={
                    "verification_id": payload.verification_id,
                    "action_id": payload.action_id,
                    "status": payload.status.value,
                    "verified": payload.verified,
                    "is_new": is_new,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )
            return payload

        except VerificationAgentError as e:
            # Domain-specific verification errors
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            logger.warning(
                f"Verification domain error: {e}",
                extra={"error_code": e.error_code, "elapsed_ms": round(elapsed_ms, 2)},
            )
            raise

        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000.0
            logger.error(
                f"Unexpected error during verification: {e}",
                exc_info=True,
                extra={"elapsed_ms": round(elapsed_ms, 2)},
            )
            # Produce fallback ERROR payload
            ver_id = command.verification_id or generate_deterministic_verification_id(
                organization_id=command.organization_id,
                action_id=command.action_id,
                policy_version=self.policy_version,
            )
            intended = IntendedOutcome(
                action_type=command.action_type,
                target_entity_type=command.target_entity_type,
                target_entity_id=command.target_entity_id,
            )
            observed = ObservedOutcome(
                target_entity_type=command.target_entity_type,
                target_entity_id=command.target_entity_id,
                conflict_detected=True,
                conflict_details=f"Internal verification error: {str(e)[:200]}",
            )
            fp = compute_verification_fingerprint(
                organization_id=command.organization_id,
                action_id=command.action_id,
                intended_outcome=intended.model_dump(),
                observed_outcome=observed.model_dump(exclude={"evidence_items"}),
                status=VerificationStatus.ERROR.value,
                policy_version=self.policy_version,
            )
            error_payload = VerificationResultPayload(
                verification_id=ver_id,
                action_id=command.action_id,
                decision_id=command.decision_id,
                approval_id=command.approval_id,
                organization_id=command.organization_id,
                action_type=command.action_type,
                target_entity_type=command.target_entity_type,
                target_entity_id=command.target_entity_id,
                status=VerificationStatus.ERROR,
                verified=False,
                intended_outcome=intended,
                observed_outcome=observed,
                observation_window_start=command.action_executed_at,
                observation_window_end=command.action_executed_at,
                verified_at=datetime.now(timezone.utc),
                fingerprint=fp,
                observation_summary=f"System error during verification: {str(e)[:200]}",
            )
            return error_payload
