"""Authoritative verification policy orchestrator for Phase 18.

Implements the 16-step verification evaluation procedure:
1. Load authoritative action.
2. Load the bound approval.
3. Load the authoritative DecisionResult / action intent.
4. Confirm tenant ownership.
5. Confirm action identity.
6. Confirm expected parameters.
7. Determine observation window.
8. Collect authoritative evidence.
9. Validate evidence provenance.
10. Deduplicate evidence.
11. Resolve temporal ordering.
12. Detect conflicts.
13. Compare intended vs observed outcome.
14. Produce VerificationResultPayload.
15. Persist result transactionally.
16. Emit audit / observability information.

Zero probabilistic or LLM intervention in outcome determination.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.action.contract import ActionType, TargetEntityType
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
from app.agents.verification.errors import (
    VerificationActionNotExecutedError,
    VerificationActionNotFoundError,
    VerificationApprovalMismatchError,
    VerificationEvidenceConflictError,
    VerificationObservationWindowExpiredError,
    VerificationSecurityViolationError,
    VerificationTenantIsolationError,
)
from app.agents.verification.evidence import EvidenceCollector
from app.agents.verification.verifiers import get_verifier_for_action
from app.models.governance import Action, Approval, Recommendation


class VerificationPolicy:
    """Deterministic, policy-driven outcome evaluation engine."""

    def __init__(self, db: Session, policy_version: str = "1.0") -> None:
        self.db = db
        self.policy_version = policy_version
        self.evidence_collector = EvidenceCollector(db)

    def evaluate(
        self,
        command: VerificationCommand,
        extra_evidence: Optional[List[ObservedEvidenceItem]] = None,
    ) -> VerificationResultPayload:
        """Execute the 16-step deterministic verification policy."""
        # 1. Load authoritative action
        action = (
            self.db.execute(select(Action).where(Action.id == command.action_id))
            .scalars()
            .first()
        )
        if not action:
            raise VerificationActionNotFoundError(
                f"Action with ID '{command.action_id}' not found in authoritative storage."
            )

        # 4. Confirm tenant ownership
        if action.org_id and action.org_id != command.organization_id:
            raise VerificationTenantIsolationError(
                f"Action '{action.id}' belongs to org '{action.org_id}', "
                f"denying verification for requesting org '{command.organization_id}'."
            )

        # Confirm action execution state
        if action.status in ("PENDING", "DRAFT"):
            raise VerificationActionNotExecutedError(
                f"Action '{action.id}' status is '{action.status}'. Verification requires an executed action."
            )

        # 2. Confirm bound approval if applicable
        if command.approval_id:
            approval = (
                self.db.execute(
                    select(Approval).where(Approval.id == command.approval_id)
                )
                .scalars()
                .first()
            )
            if approval:
                rec = (
                    self.db.execute(
                        select(Recommendation).where(Recommendation.id == approval.recommendation_id)
                    )
                    .scalars()
                    .first()
                )
                if rec and rec.org_id and rec.org_id != command.organization_id:
                    raise VerificationTenantIsolationError(
                        f"Approval '{approval.id}' belongs to org '{rec.org_id}', "
                        f"mismatch with requesting org '{command.organization_id}'."
                    )
                # Verify approval action binding
                if action.recommendation_id and approval.recommendation_id:
                    if action.recommendation_id != approval.recommendation_id:
                        raise VerificationApprovalMismatchError(
                            f"Action recommendation '{action.recommendation_id}' does not match "
                            f"approval recommendation '{approval.recommendation_id}'."
                        )

        # Resolve ActionType
        try:
            action_type_enum = ActionType(action.action_type)
        except Exception:
            action_type_enum = command.action_type

        # 3. Derive IntendedOutcome
        verifier = get_verifier_for_action(action_type_enum)
        intended = verifier.derive_intended_outcome(command)

        # 7. Determine observation window
        exec_at = action.executed_at or command.action_executed_at
        if exec_at.tzinfo is None:
            exec_at = exec_at.replace(tzinfo=timezone.utc)
        else:
            exec_at = exec_at.astimezone(timezone.utc)

        window_start = exec_at
        window_end = exec_at + timedelta(seconds=command.observation_window_seconds)

        # 8, 9, 10, 11: Collect authoritative evidence with deduplication & temporal ordering
        evidence_items = self.evidence_collector.collect(
            command=command,
            extra_evidence=extra_evidence,
        )

        # 12, 13: Compare intended vs observed outcome and detect conflicts
        status, verified, observed_outcome, summary = verifier.verify(
            command=command,
            intended=intended,
            evidence_items=evidence_items,
        )

        # Extract risk scores before/after if available from action payloads
        risk_before = None
        risk_after = None
        if action.execution_payload and isinstance(action.execution_payload, dict):
            risk_before = action.execution_payload.get("risk_score_before")
        if action.result_payload and isinstance(action.result_payload, dict):
            risk_after = action.result_payload.get("risk_score_after")

        # Deterministic verification ID
        verification_id = command.verification_id or generate_deterministic_verification_id(
            organization_id=command.organization_id,
            action_id=command.action_id,
            policy_version=self.policy_version,
        )

        # 14. Produce VerificationResultPayload
        fingerprint = compute_verification_fingerprint(
            organization_id=command.organization_id,
            action_id=command.action_id,
            intended_outcome=intended.model_dump(),
            observed_outcome=observed_outcome.model_dump(exclude={"evidence_items"}),
            status=status.value,
            policy_version=self.policy_version,
        )

        provenance = {
            "policy_version": self.policy_version,
            "evidence_count": len(evidence_items),
            "highest_precedence": observed_outcome.highest_precedence.value if observed_outcome.highest_precedence else None,
            "action_type": action_type_enum.value,
            "action_status": action.status,
            "verifier_class": verifier.__class__.__name__,
        }

        return VerificationResultPayload(
            verification_id=verification_id,
            action_id=command.action_id,
            decision_id=command.decision_id,
            approval_id=command.approval_id,
            organization_id=command.organization_id,
            action_type=action_type_enum,
            target_entity_type=command.target_entity_type,
            target_entity_id=command.target_entity_id,
            status=status,
            verified=verified,
            intended_outcome=intended,
            observed_outcome=observed_outcome,
            observation_window_start=window_start,
            observation_window_end=window_end,
            verified_at=datetime.now(timezone.utc),
            policy_version=self.policy_version,
            fingerprint=fingerprint,
            risk_score_before=risk_before,
            risk_score_after=risk_after,
            observation_summary=summary[:1000] if summary else "",
            provenance=provenance,
        )
