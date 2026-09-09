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
from app.models.governance import Recommendation
from app.normalization.contract import EntityType, NormalizedRiskSignal
from app.risk_engine.alerts import (
    RiskAlert,
    RiskAlertEvaluator,
    RiskAlertNotificationAdapter,
)
from app.risk_engine.recommendations import (
    RiskRecommendation,
    RiskRecommendationAdapter,
    RiskRecommendationEvaluator,
)
from app.risk_engine.context import RiskEvaluationContext
from sqlalchemy import select
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
                # Query existing alerts for this assessment if any
                existing_notifs, _ = self.uow.notifications.list_for_user(
                    org_id=org_id,
                    category="RISK_ALERT",
                    limit=100,
                )
                matching_alerts = [
                    RiskAlertNotificationAdapter.from_notification_model(n).model_dump()
                    for n in existing_notifs
                    if n.summary and existing_orm.id in n.summary
                ]
                detail_dict["alerts"] = matching_alerts
                if "findings" in detail_dict and isinstance(detail_dict["findings"], dict):
                    detail_dict["findings"]["alerts"] = matching_alerts

                # Query existing recommendations for this assessment
                existing_recs_orm = list(
                    self.uow.session.scalars(
                        select(Recommendation).where(Recommendation.org_id == org_id)
                    ).all()
                )
                matching_recs = [
                    RiskRecommendationAdapter.from_orm(r).model_dump()
                    for r in existing_recs_orm
                    if r.expected_benefit_json and r.expected_benefit_json.get("assessment_id") == existing_orm.id
                ]
                detail_dict["recommendations"] = matching_recs
                if "findings" in detail_dict and isinstance(detail_dict["findings"], dict):
                    detail_dict["findings"]["recommendations"] = matching_recs

                return domain_reconstructed, detail_dict, True

        # Resolve previous assessment for comparison and alert rules
        previous_domain: Optional[RiskAssessment] = None
        try:
            previous_orm: Optional[ORMRiskAssessment] = None
            if risk_id:
                previous_orm = self.uow.risk_assessments.get_latest_for_risk(org_id=org_id, risk_id=risk_id)
            elif scope_entity_id:
                previous_orm = self.uow.risk_assessments.get_latest_for_entity(
                    org_id=org_id, scope=scope, scope_entity_id=scope_entity_id
                )
            else:
                previous_orm = self.uow.risk_assessments.get_latest_for_org(org_id=org_id, scope=scope)

            if previous_orm is not None:
                previous_domain = RiskAssessmentPersistenceAdapter.from_orm(previous_orm)
        except Exception as ex:
            logger.warning("Could not load previous assessment for alert evaluation: %s", ex)
            previous_domain = None

        # Evaluate deterministic risk alerts
        alerts = RiskAlertEvaluator.evaluate_alerts(current=assessment, previous=previous_domain)

        # Evaluate deterministic operational recommendations (Phase 7 Step 7)
        recommendations = RiskRecommendationEvaluator.evaluate_recommendations(
            current=assessment,
            previous=previous_domain,
            alerts=alerts,
        )

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

            # 5. Persist Risk Alerts as Notifications (deterministic idempotency)
            for alert in alerts:
                alert.risk_id = parent_risk.id
                existing_notif = self.uow.notifications.get(alert.alert_id, org_id=org_id)
                if not existing_notif:
                    notif_orm = RiskAlertNotificationAdapter.to_notification_model(alert)
                    self.uow.notifications.create(notif_orm, auto_commit=False)
                    AuditService.log_event(
                        uow=self.uow,
                        action="ALERT_TRIGGERED",
                        resource_type="Notification",
                        org_id=org_id,
                        actor_id=self.context.user_id if self.context else None,
                        resource_id=alert.alert_id,
                        after_data={
                            "alert_id": alert.alert_id,
                            "alert_type": alert.alert_type.value,
                            "severity": alert.severity.value,
                            "assessment_id": orm_assessment.id,
                            "risk_id": parent_risk.id,
                            "trigger_reason": alert.trigger_reason,
                        },
                        auto_commit=False,
                    )

            # 6. Persist Risk Recommendations (deterministic idempotency)
            for rec in recommendations:
                rec.risk_id = parent_risk.id
                existing_rec = self.uow.recommendations.get(rec.recommendation_id, org_id=org_id)
                if not existing_rec:
                    rec_orm = RiskRecommendationAdapter.to_orm(rec)
                    self.uow.recommendations.create(rec_orm, auto_commit=False)
                    AuditService.log_event(
                        uow=self.uow,
                        action="RECOMMENDATION_PROPOSED",
                        resource_type="Recommendation",
                        org_id=org_id,
                        actor_id=self.context.user_id if self.context else None,
                        resource_id=rec.recommendation_id,
                        after_data={
                            "recommendation_id": rec.recommendation_id,
                            "recommendation_type": rec.recommendation_type.value,
                            "priority": rec.priority.value,
                            "assessment_id": orm_assessment.id,
                            "risk_id": parent_risk.id,
                            "title": rec.title,
                            "expected_objective": rec.expected_objective,
                        },
                        auto_commit=False,
                    )

            # 7. Record Audit Log for Assessment
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
                    "alerts_count": len(alerts),
                    "recommendations_count": len(recommendations),
                },
                auto_commit=False,
            )

            # 8. Commit atomic transaction
            self.uow.commit()

        # Build response detail
        detail_dict = RiskAssessmentPersistenceAdapter.to_detail_dict(orm_assessment)
        alert_dicts = [alert.model_dump() for alert in alerts]
        detail_dict["alerts"] = alert_dicts
        if "findings" in detail_dict and isinstance(detail_dict["findings"], dict):
            detail_dict["findings"]["alerts"] = alert_dicts

        rec_dicts = [rec.model_dump() for rec in recommendations]
        detail_dict["recommendations"] = rec_dicts
        if "findings" in detail_dict and isinstance(detail_dict["findings"], dict):
            detail_dict["findings"]["recommendations"] = rec_dicts

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

    def list_alerts(
        self,
        assessment_id: Optional[str] = None,
        severity: Optional[str] = None,
        alert_type: Optional[str] = None,
        is_read: Optional[bool] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[RiskAlert], int]:
        """List risk alerts for the authenticated tenant organization with filtering, pagination, and deterministic ordering."""
        org_id = self._enforce_tenant_scope()

        # Query notifications repository scoped to category="RISK_ALERT"
        notifs, total = self.uow.notifications.list_for_user(
            org_id=org_id,
            user_id=None,
            category="RISK_ALERT",
            severity=severity,
            is_read=is_read,
            page=page,
            limit=limit,
        )
        alerts = [RiskAlertNotificationAdapter.from_notification_model(n) for n in notifs]

        if assessment_id:
            alerts = [a for a in alerts if a.assessment_id == assessment_id]
        if alert_type:
            alerts = [a for a in alerts if a.alert_type.value == alert_type]

        return alerts, total

    def get_alert(self, alert_id: str) -> RiskAlert:
        """Retrieve a single risk alert enforcing tenant scoping."""
        org_id = self._enforce_tenant_scope()
        notif = self.uow.notifications.get(alert_id, org_id=org_id)
        if not notif or notif.category != "RISK_ALERT":
            raise NotFoundError(
                message=f"Risk alert with ID '{alert_id}' not found.",
                code="ALERT_NOT_FOUND",
                details={"alert_id": alert_id, "organization_id": org_id},
            )
        return RiskAlertNotificationAdapter.from_notification_model(notif)

    def acknowledge_alert(self, alert_id: str, is_read: bool = True) -> RiskAlert:
        """Mark a risk alert as acknowledged/read enforcing tenant isolation."""
        org_id = self._enforce_tenant_scope()
        with self.uow:
            notif = self.uow.notifications.get(alert_id, org_id=org_id)
            if not notif or notif.category != "RISK_ALERT":
                raise NotFoundError(
                    message=f"Risk alert with ID '{alert_id}' not found.",
                    code="ALERT_NOT_FOUND",
                    details={"alert_id": alert_id, "organization_id": org_id},
                )
            notif.is_read = is_read
            self.uow.notifications.update(notif, auto_commit=False)
            AuditService.log_event(
                uow=self.uow,
                action="ALERT_ACKNOWLEDGED" if is_read else "ALERT_UNREAD",
                resource_type="Notification",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=alert_id,
                after_data={"alert_id": alert_id, "is_read": is_read},
                auto_commit=False,
            )
            self.uow.commit()
        return RiskAlertNotificationAdapter.from_notification_model(notif)

    def list_recommendations(
        self,
        assessment_id: Optional[str] = None,
        priority: Optional[str] = None,
        recommendation_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Tuple[List[RiskRecommendation], int]:
        """List recommendations for the authenticated tenant organization with filtering, pagination, and deterministic ordering."""
        org_id = self._enforce_tenant_scope()

        stmt = select(Recommendation).where(Recommendation.org_id == org_id)
        if status:
            stmt = stmt.where(Recommendation.status == status)
        stmt = stmt.order_by(Recommendation.created_at.desc(), Recommendation.id.asc())

        all_orm = list(self.uow.session.scalars(stmt).all())
        all_recs = [RiskRecommendationAdapter.from_orm(r) for r in all_orm]

        if assessment_id:
            all_recs = [r for r in all_recs if r.assessment_id == assessment_id]
        if priority:
            all_recs = [r for r in all_recs if r.priority.value == priority]
        if recommendation_type:
            all_recs = [r for r in all_recs if r.recommendation_type.value == recommendation_type]

        total = len(all_recs)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        return all_recs[start_idx:end_idx], total

    def get_recommendation(self, recommendation_id: str) -> RiskRecommendation:
        """Retrieve a single recommendation enforcing tenant scoping."""
        org_id = self._enforce_tenant_scope()
        orm_rec = self.uow.recommendations.get(recommendation_id, org_id=org_id)
        if not orm_rec:
            raise NotFoundError(
                message=f"Recommendation with ID '{recommendation_id}' not found.",
                code="RECOMMENDATION_NOT_FOUND",
                details={"recommendation_id": recommendation_id, "organization_id": org_id},
            )
        return RiskRecommendationAdapter.from_orm(orm_rec)


