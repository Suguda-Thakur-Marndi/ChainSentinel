"""Domain service coordinating deterministic Risk Engine evaluation, persistence, and audit logging."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.context import AuthenticatedContext
from app.core.errors import NotFoundError, ValidationDomainError
from app.db.unit_of_work import UnitOfWork
from app.models.risk import Risk as ORMRisk
from app.models.risk import RiskAssessment as ORMRiskAssessment
from app.models.risk import RiskFactor as ORMRiskFactor
from app.normalization.contract import EntityType, NormalizedRiskSignal
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import RiskAssessment
from app.risk_engine.history import (
    AssessmentComparison,
    HistoricalRiskComparator,
    RiskHistorySummary,
)
from app.risk_engine.persistence import RiskAssessmentPersistenceAdapter
from app.risk_engine.pipeline import BaselineRiskEngine
from app.services.audit_service import AuditService
from app.services.base import BaseService

logger = logging.getLogger("riskwise.services.risk_evaluation")


class RiskEvaluationService(BaseService[ORMRiskAssessment]):
    """Orchestrates deterministic Risk Engine execution, transactional persistence, and retrieval."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(ORMRiskAssessment, uow, context)
        self.engine = BaselineRiskEngine()

    def evaluate_and_persist(
        self,
        signals: List[NormalizedRiskSignal],
        scope: str = "GLOBAL",
        scope_entity_id: Optional[str] = None,
        scope_entity_type: Optional[EntityType] = None,
        risk_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[RiskAssessment, Dict[str, Any], bool]:
        """Execute a deterministic risk evaluation run and transactionally persist the result.

        Args:
            signals: List of validated Phase 6 NormalizedRiskSignal instances.
            scope: Evaluation scope (e.g. GLOBAL, SHIPMENT, SUPPLIER, PORT, ROUTE).
            scope_entity_id: Target entity identifier if scope is entity-specific.
            scope_entity_type: Target entity type.
            risk_id: Optional existing parent Risk ID.
            metadata: Diagnostic or contextual metadata.

        Returns:
            Tuple of (domain RiskAssessment, response detail dictionary, is_idempotent_hit boolean).
        """
        org_id = self._enforce_tenant_scope()

        # Strict input boundary: validate signals
        if not isinstance(signals, list):
            raise ValidationDomainError(
                message="Signals parameter must be a list of NormalizedRiskSignal instances.",
                code="INVALID_SIGNAL_PAYLOAD",
            )

        for idx, sig in enumerate(signals):
            if not isinstance(sig, NormalizedRiskSignal):
                raise ValidationDomainError(
                    message=f"Signal at index {idx} is not a NormalizedRiskSignal (got {type(sig).__name__}). Raw provider payloads are strictly rejected.",
                    code="UNNORMALIZED_SIGNAL_REJECTED",
                    details={"index": idx, "type": type(sig).__name__},
                )
            if not sig.signal_id:
                raise ValidationDomainError(
                    message=f"Signal at index {idx} missing required signal_id.",
                    code="INVALID_SIGNAL_ID",
                )

        eval_time = datetime.now(timezone.utc)
        meta = metadata.copy() if metadata else {}
        correlation_id = getattr(self.context, "request_id", None) if self.context else None

        # Build pure domain evaluation context
        eval_context = RiskEvaluationContext(
            organization_id=org_id,
            evaluation_time=eval_time,
            signals=signals,
            scope=scope,
            scope_entity_id=scope_entity_id,
            scope_entity_type=scope_entity_type,
            correlation_id=correlation_id,
            metadata=meta,
        )

        # Execute pure deterministic Risk Engine pipeline
        assessment: RiskAssessment = self.engine.evaluate(eval_context)

        # Idempotency check: check if assessment with identical semantic fingerprint already exists
        if assessment.fingerprint:
            existing_orm = self.uow.risk_assessments.find_by_fingerprint(
                org_id=org_id,
                fingerprint=assessment.fingerprint,
            )
            if existing_orm is not None:
                logger.info(
                    "Idempotency hit for assessment fingerprint %s; returning existing record %s",
                    assessment.fingerprint,
                    existing_orm.id,
                )
                domain_reconstructed = RiskAssessmentPersistenceAdapter.from_orm(existing_orm)
                detail_dict = RiskAssessmentPersistenceAdapter.to_detail_dict(existing_orm)
                return domain_reconstructed, detail_dict, True

        # Transactional Persistence
        with self.uow:
            # 1. Resolve or create parent Risk entity
            parent_risk: Optional[ORMRisk] = None
            if risk_id:
                parent_risk = self.uow.risks.get(risk_id, org_id=org_id)
                if not parent_risk:
                    raise NotFoundError(
                        message=f"Risk with ID '{risk_id}' not found in organization tenant boundary.",
                        code="RISK_NOT_FOUND",
                        details={"risk_id": risk_id, "organization_id": org_id},
                    )
            else:
                # Find or create a scope-level Risk record
                target_title = f"Risk Evaluation: {scope}"
                if scope_entity_id:
                    target_title += f" ({scope_entity_id})"

                # Try finding existing Risk with identical scope title
                parent_risk = self.uow.risks.find_one(
                    org_id=org_id,
                    title=target_title,
                )
                if not parent_risk:
                    parent_risk = ORMRisk(
                        org_id=org_id,
                        title=target_title[:255],
                        risk_type="COMPOSITE",
                        severity=assessment.risk_level.value if assessment.risk_level else "MEDIUM",
                        location=scope_entity_id[:255] if scope_entity_id else None,
                        probability=None,  # Phase 7 rule: strictly None
                        impact=None,       # Phase 7 rule: strictly None
                        risk_score=round(float(assessment.score or 0.0), 2),
                        confidence=round(float(assessment.confidence), 4),
                        trend="STABLE",
                        source="DETERMINISTIC_ENGINE",
                    )
                    self.uow.risks.create(parent_risk, auto_commit=False)

            # Update parent risk metrics
            if assessment.score is not None:
                parent_risk.risk_score = round(float(assessment.score), 2)
            if assessment.risk_level is not None:
                parent_risk.severity = assessment.risk_level.value
            parent_risk.confidence = round(float(assessment.confidence), 4)
            parent_risk.updated_at = eval_time
            self.uow.risks.update(parent_risk, auto_commit=False)

            # 2. Map domain assessment to ORM models
            orm_assessment, orm_factors = RiskAssessmentPersistenceAdapter.to_orm(
                assessment=assessment,
                risk_id=parent_risk.id,
            )

            # 3. Persist RiskAssessment
            self.uow.risk_assessments.create(orm_assessment, auto_commit=False)

            # 4. Persist RiskFactor records
            for f_orm in orm_factors:
                self.uow.session.merge(f_orm)

            # 5. Record Audit Log
            AuditService.log_event(
                uow=self.uow,
                action="EVALUATE",
                resource_type="RiskAssessment",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=orm_assessment.id,
                after_data={
                    "assessment_id": orm_assessment.id,
                    "risk_id": parent_risk.id,
                    "score": orm_assessment.score,
                    "risk_level": assessment.risk_level.value if assessment.risk_level else None,
                    "fingerprint": assessment.fingerprint,
                    "factors_count": len(orm_factors),
                    "evidence_count": len(assessment.evidence),
                },
                auto_commit=False,
            )

            # 6. Commit atomic transaction
            self.uow.commit()

        # Build response detail
        detail_dict = RiskAssessmentPersistenceAdapter.to_detail_dict(orm_assessment)
        return assessment, detail_dict, False

    def get_assessment_domain(self, assessment_id: str) -> RiskAssessment:
        """Retrieve a persisted assessment and reconstruct the full domain model enforcing tenant isolation."""
        org_id = self._enforce_tenant_scope()
        orm_assessment = self.uow.risk_assessments.get_assessment(org_id=org_id, assessment_id=assessment_id)
        if not orm_assessment:
            raise NotFoundError(
                message=f"RiskAssessment with ID '{assessment_id}' not found.",
                code="RESOURCE_NOT_FOUND",
                details={"assessment_id": assessment_id, "organization_id": org_id},
            )
        return RiskAssessmentPersistenceAdapter.from_orm(orm_assessment)

    def get_assessment_detail(self, assessment_id: str) -> Dict[str, Any]:
        """Retrieve full detail dictionary for an assessment with 404 masking."""
        org_id = self._enforce_tenant_scope()
        orm_assessment = self.uow.risk_assessments.get_assessment(org_id=org_id, assessment_id=assessment_id)
        if not orm_assessment:
            raise NotFoundError(
                message=f"RiskAssessment with ID '{assessment_id}' not found.",
                code="RESOURCE_NOT_FOUND",
                details={"assessment_id": assessment_id, "organization_id": org_id},
            )
        return RiskAssessmentPersistenceAdapter.to_detail_dict(orm_assessment)

    def get_latest_assessment(
        self,
        scope: Optional[str] = None,
        scope_entity_id: Optional[str] = None,
        risk_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the latest assessment record matching scope/entity/risk within tenant boundary."""
        org_id = self._enforce_tenant_scope()
        orm_assessment: Optional[ORMRiskAssessment] = None

        if risk_id:
            orm_assessment = self.uow.risk_assessments.get_latest_for_risk(org_id=org_id, risk_id=risk_id)
        elif scope and scope_entity_id:
            orm_assessment = self.uow.risk_assessments.get_latest_for_entity(
                org_id=org_id,
                scope=scope,
                scope_entity_id=scope_entity_id,
            )
        else:
            orm_assessment = self.uow.risk_assessments.get_latest_for_org(org_id=org_id, scope=scope)

        if not orm_assessment:
            return None

        return RiskAssessmentPersistenceAdapter.to_detail_dict(orm_assessment)

    def get_history(
        self,
        scope: Optional[str] = None,
        scope_entity_id: Optional[str] = None,
        risk_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
    ) -> RiskHistorySummary:
        """Retrieve chronological assessment history and calculate deterministic trends.

        Enforces server-side tenant isolation, read-only immutability, and safe pagination.
        """
        org_id = self._enforce_tenant_scope()
        orm_assessments = self.uow.risk_assessments.get_assessment_history(
            org_id=org_id,
            risk_id=risk_id,
            scope=scope,
            scope_entity_id=scope_entity_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            ascending=True,  # Chronological order
        )

        details = [RiskAssessmentPersistenceAdapter.to_detail_dict(a) for a in orm_assessments]

        return HistoricalRiskComparator.summarize_history(
            org_id=org_id,
            assessments=details,
            entity_scope=scope,
            entity_id=scope_entity_id or risk_id,
        )

    def compare_assessments(
        self,
        assessment_id_1: str,
        assessment_id_2: str,
    ) -> AssessmentComparison:
        """Compare two specific risk assessments deterministically within the tenant boundary.

        The earlier assessment is treated as previous and the later as current.
        Enforces tenant isolation: both assessments must belong to the caller's organization.
        """
        org_id = self._enforce_tenant_scope()

        orm_1 = self.uow.risk_assessments.get_assessment(org_id=org_id, assessment_id=assessment_id_1)
        if not orm_1:
            raise NotFoundError(
                message=f"RiskAssessment with ID '{assessment_id_1}' not found.",
                code="RESOURCE_NOT_FOUND",
                details={"assessment_id": assessment_id_1, "organization_id": org_id},
            )

        orm_2 = self.uow.risk_assessments.get_assessment(org_id=org_id, assessment_id=assessment_id_2)
        if not orm_2:
            raise NotFoundError(
                message=f"RiskAssessment with ID '{assessment_id_2}' not found.",
                code="RESOURCE_NOT_FOUND",
                details={"assessment_id": assessment_id_2, "organization_id": org_id},
            )

        detail_1 = RiskAssessmentPersistenceAdapter.to_detail_dict(orm_1)
        detail_2 = RiskAssessmentPersistenceAdapter.to_detail_dict(orm_2)

        time_1 = detail_1.get("created_at") or orm_1.created_at
        time_2 = detail_2.get("created_at") or orm_2.created_at

        if time_1 <= time_2:
            previous_detail, current_detail = detail_1, detail_2
        else:
            previous_detail, current_detail = detail_2, detail_1

        return HistoricalRiskComparator.compare(current=current_detail, previous=previous_detail)
