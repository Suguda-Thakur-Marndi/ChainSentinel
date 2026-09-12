"""Transactional persistence for RiskWise Decision Agent (Phase 15).

Stores DecisionResult records and audit trails using existing database tables:
- recommendations table (for structured decision and recommendation records)
- audit_logs table (for compliance, provenance, and decision execution audit trails)

Invariants:
- 0 schema changes, 0 new tables, 0 migrations
- Multi-tenant isolation enforced on every query and mutation
- Idempotency guaranteed via deterministic decision_id and SHA-256 fingerprint
- Strict fail-closed error handling
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.decision.contract import DecisionResult
from app.agents.decision.errors import DecisionTenantIsolationError
from app.models.governance import AuditLog, Recommendation

logger = logging.getLogger("riskwise.decision.persistence")


class DecisionRepository:
    """Repository handling database operations for Decision records in recommendations table."""

    @staticmethod
    def save_decision(
        db: Session,
        result: DecisionResult,
        request_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> Recommendation:
        """Persist a DecisionResult to the recommendations table with audit log.

        Guarantees idempotency via result.decision_id.
        """
        org_id = result.organization_id.strip()
        decision_id = result.decision_id.strip()

        # Compute cost estimate if available from preferred candidate or optimization
        estimated_cost: Optional[float] = None
        if result.preferred_candidate and "cost" in result.preferred_candidate.parameters:
            try:
                estimated_cost = float(result.preferred_candidate.parameters["cost"])
            except (ValueError, TypeError):
                pass
        elif result.optimization_summary and result.optimization_summary.objective_type == "MINIMIZE_COST":
            estimated_cost = result.optimization_summary.objective_value

        title = (
            result.preferred_candidate.title
            if result.preferred_candidate
            else f"Decision: {result.decision_type.value}"
        )
        rationale = (
            result.rationales[0].explanation_code
            if result.rationales
            else f"Deterministic decision formulated under policy {result.decision_policy_version}."
        )

        # Store complete structured payload inside expected_benefit_json
        payload_dict = result.model_dump(mode="json")

        # Check existing record for idempotency
        stmt = select(Recommendation).where(Recommendation.id == decision_id)
        existing = db.scalars(stmt).first()

        if existing:
            if existing.org_id and existing.org_id != org_id:
                raise DecisionTenantIsolationError(
                    f"Decision '{decision_id}' belongs to another tenant '{existing.org_id}'."
                )
            existing.title = title[:255]
            existing.rationale = rationale[:1000]
            existing.estimated_cost = estimated_cost
            existing.expected_benefit_json = payload_dict
            existing.confidence = result.confidence
            existing.status = result.status
            db.flush()
            return existing

        record = Recommendation(
            id=decision_id,
            org_id=org_id,
            incident_id=result.scenario_id,
            title=title[:255],
            rationale=rationale[:1000],
            estimated_cost=estimated_cost,
            expected_benefit_json=payload_dict,
            confidence=result.confidence,
            status=result.status,
        )
        db.add(record)

        # Record audit log event
        audit = AuditLog(
            org_id=org_id,
            actor_type="AGENT",
            actor_id=actor_id or "decision_agent",
            action="DECISION_GENERATED",
            resource_type="DECISION",
            resource_id=decision_id,
            status="SUCCESS",
            request_id=request_id,
            after_json={
                "decision_id": decision_id,
                "status": result.status,
                "decision_type": result.decision_type.value,
                "fingerprint": result.fingerprint,
                "policy_version": result.decision_policy_version,
            },
        )
        db.add(audit)
        db.flush()
        return record

    @staticmethod
    def get_by_id(
        db: Session,
        organization_id: str,
        decision_id: str,
    ) -> Optional[Recommendation]:
        """Retrieve a decision record enforcing strict tenant isolation."""
        stmt = select(Recommendation).where(Recommendation.id == decision_id)
        record = db.scalars(stmt).first()
        if not record:
            return None

        if record.org_id and record.org_id != organization_id:
            raise DecisionTenantIsolationError(
                f"Decision '{decision_id}' belongs to another organization."
            )
        return record

    @staticmethod
    def list_by_organization(
        db: Session,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Recommendation]:
        """List decision recommendations for the specified tenant with pagination."""
        stmt = (
            select(Recommendation)
            .where(Recommendation.org_id == organization_id)
            .order_by(Recommendation.created_at.desc())
            .offset(offset)
            .limit(min(limit, 100))
        )
        return list(db.scalars(stmt).all())
