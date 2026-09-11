"""Domain services for Risk intelligence, RiskFactor child entity, RiskAssessment, and Incident resources."""
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel

from app.core.context import AuthenticatedContext
from app.core.errors import (
    ImmutableResourceError,
    LifecycleStateError,
    NotFoundError,
    ValidationDomainError,
)
from app.db.unit_of_work import UnitOfWork
from app.models.risk import Incident, Risk, RiskAssessment, RiskFactor
from app.repositories.risk_repositories import (
    INCIDENT_FILTER_ALLOWLIST,
    INCIDENT_SEARCH_COLUMNS,
    INCIDENT_SORT_ALLOWLIST,
    RISK_ASSESSMENT_FILTER_ALLOWLIST,
    RISK_ASSESSMENT_SEARCH_COLUMNS,
    RISK_ASSESSMENT_SORT_ALLOWLIST,
    RISK_FACTOR_FILTER_ALLOWLIST,
    RISK_FACTOR_SEARCH_COLUMNS,
    RISK_FACTOR_SORT_ALLOWLIST,
    RISK_FILTER_ALLOWLIST,
    RISK_SEARCH_COLUMNS,
    RISK_SORT_ALLOWLIST,
)
from app.schemas.common import PaginationMeta, PaginationParams
from app.schemas.risk import (
    IncidentCreate,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdate,
    RiskAssessmentCreate,
    RiskAssessmentListResponse,
    RiskAssessmentResponse,
    RiskCreate,
    RiskFactorCreate,
    RiskFactorListResponse,
    RiskFactorResponse,
    RiskFactorUpdate,
    RiskListResponse,
    RiskResponse,
    RiskUpdate,
)
from app.services.audit_service import AuditService
from app.services.base import BaseService


def _clean_payload(data: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Extract dict and convert Enum and datetime attributes to primitive values."""
    payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)
    for k, v in list(payload.items()):
        if hasattr(v, "value"):
            payload[k] = v.value
        elif isinstance(v, datetime):
            payload[k] = v
    return payload


# ==============================================================================
# 1. RISK SERVICE
# ==============================================================================
class RiskService(BaseService[Risk]):
    """Domain service managing organization-scoped Risk entities."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Risk, uow, context)

    def create_risk(self, data: RiskCreate) -> RiskResponse:
        """Create a new risk entity scoped to the authenticated organization."""
        org_id = self._enforce_tenant_scope()
        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            risk = Risk(**payload)
            self.uow.risks.create(risk, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Risk",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=risk.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return RiskResponse.model_validate(risk)

    def get_risk(self, risk_id: str) -> RiskResponse:
        """Retrieve an individual risk entity by ID enforcing tenant isolation and 404 masking."""
        risk = self.get_by_id(risk_id)
        return RiskResponse.model_validate(risk)

    def list_risks(
        self,
        params: PaginationParams,
        severity: Optional[str] = None,
        trend: Optional[str] = None,
        risk_type: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> RiskListResponse:
        """List risks with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if severity:
            filters["severity"] = severity
        if trend:
            filters["trend"] = trend
        if risk_type:
            filters["risk_type"] = risk_type

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=RISK_FILTER_ALLOWLIST,
            sort_allowlist=RISK_SORT_ALLOWLIST,
            search_columns=RISK_SEARCH_COLUMNS,
            default_sort_field="detected_at",
            default_sort_desc=True,
        )
        items = [RiskResponse.model_validate(item) for item in paginated.items]
        return RiskListResponse(items=items, pagination=paginated.pagination)

    def update_risk(self, risk_id: str, data: RiskUpdate) -> RiskResponse:
        """Update risk attributes with audit logging."""
        risk = self.get_by_id(risk_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "detected_at", "updated_at"):
            update_dict.pop(forbidden, None)

        before_data = {
            "title": risk.title,
            "severity": risk.severity,
            "trend": risk.trend,
            "probability": risk.probability,
            "impact": risk.impact,
            "risk_score": risk.risk_score,
            "confidence": risk.confidence,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(risk, k, v)
            risk.updated_at = datetime.now(timezone.utc)
            self.uow.risks.update(risk, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Risk",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=risk.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return RiskResponse.model_validate(risk)


# ==============================================================================
# 2. RISK FACTOR SERVICE (CHILD ENTITY OF RISK)
# ==============================================================================
class RiskFactorService(BaseService[RiskFactor]):
    """Domain service managing RiskFactor child entities scoped via parent Risk.org_id."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(RiskFactor, uow, context)

    def create_factor(self, data: RiskFactorCreate) -> RiskFactorResponse:
        """Create a new risk factor verifying that the parent risk belongs to the tenant."""
        org_id = self._enforce_tenant_scope()

        # Validate parent risk exists and belongs to current tenant
        parent_risk = self.uow.risks.get(data.risk_id, org_id=org_id)
        if not parent_risk:
            raise NotFoundError(
                message=f"Risk with ID '{data.risk_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Risk", "resource_id": data.risk_id},
            )

        payload = _clean_payload(data)

        with self.uow:
            factor = RiskFactor(**payload)
            self.uow.risk_factors.create(factor, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="RiskFactor",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=factor.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return RiskFactorResponse.model_validate(factor)

    def get_factor(self, factor_id: str) -> RiskFactorResponse:
        """Retrieve a single risk factor verifying parent risk tenant isolation."""
        org_id = self._enforce_tenant_scope()
        factor = self.uow.risk_factors.get_factor_in_org(factor_id, org_id=org_id)
        if not factor:
            raise NotFoundError(
                message=f"RiskFactor with ID '{factor_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "RiskFactor", "resource_id": factor_id},
            )
        return RiskFactorResponse.model_validate(factor)

    def list_factors(
        self,
        params: PaginationParams,
        risk_id: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> RiskFactorListResponse:
        """List risk factors scoped to tenant via parent risks."""
        org_id = self._enforce_tenant_scope()

        if risk_id:
            parent_risk = self.uow.risks.get(risk_id, org_id=org_id)
            if not parent_risk:
                raise NotFoundError(
                    message=f"Risk with ID '{risk_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Risk", "resource_id": risk_id},
                )

        filters: dict[str, Any] = {}
        if category:
            filters["category"] = category

        items, total = self.uow.risk_factors.list_factors_for_org(
            org_id=org_id,
            risk_id=risk_id,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
        )

        pages = (total + params.limit - 1) // params.limit if total > 0 else 0
        validated_items = [RiskFactorResponse.model_validate(f) for f in items]
        return RiskFactorListResponse(
            items=validated_items,
            pagination=PaginationMeta(total=total, page=params.page, limit=params.limit, pages=pages),
        )

    def update_factor(self, factor_id: str, data: RiskFactorUpdate) -> RiskFactorResponse:
        """Update an existing risk factor within tenant boundary."""
        org_id = self._enforce_tenant_scope()
        factor = self.uow.risk_factors.get_factor_in_org(factor_id, org_id=org_id)
        if not factor:
            raise NotFoundError(
                message=f"RiskFactor with ID '{factor_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "RiskFactor", "resource_id": factor_id},
            )

        update_dict = _clean_payload(data)
        for forbidden in ("id", "risk_id", "created_at"):
            update_dict.pop(forbidden, None)

        before_data = {
            "name": factor.name,
            "category": factor.category,
            "weight": factor.weight,
            "score": factor.score,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(factor, k, v)
            self.uow.risk_factors.update(factor, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="RiskFactor",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=factor.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return RiskFactorResponse.model_validate(factor)

    def delete_factor(self, factor_id: str) -> None:
        """Delete an obsolete risk factor within tenant boundary."""
        org_id = self._enforce_tenant_scope()
        factor = self.uow.risk_factors.get_factor_in_org(factor_id, org_id=org_id)
        if not factor:
            raise NotFoundError(
                message=f"RiskFactor with ID '{factor_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "RiskFactor", "resource_id": factor_id},
            )

        with self.uow:
            self.uow.session.delete(factor)

            AuditService.log_event(
                uow=self.uow,
                action="DELETE",
                resource_type="RiskFactor",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=factor.id,
                before_data={"name": factor.name, "risk_id": factor.risk_id},
                auto_commit=False,
            )
            self.uow.commit()


# ==============================================================================
# 3. RISK ASSESSMENT SERVICE (IMMUTABLE EVALUATION SNAPSHOTS)
# ==============================================================================
class RiskAssessmentService(BaseService[RiskAssessment]):
    """Domain service managing immutable RiskAssessment evaluation snapshots."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(RiskAssessment, uow, context)

    def create_assessment(self, data: RiskAssessmentCreate) -> RiskAssessmentResponse:
        """Record an immutable risk assessment snapshot with tenant verification."""
        org_id = self._enforce_tenant_scope()

        # Validate parent risk exists and belongs to current tenant
        parent_risk = self.uow.risks.get(data.risk_id, org_id=org_id)
        if not parent_risk:
            raise NotFoundError(
                message=f"Risk with ID '{data.risk_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Risk", "resource_id": data.risk_id},
            )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            assessment = RiskAssessment(**payload)
            self.uow.risk_assessments.create(assessment, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="RiskAssessment",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=assessment.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return RiskAssessmentResponse.model_validate(assessment)

    def get_assessment(self, assessment_id: str) -> RiskAssessmentResponse:
        """Retrieve an individual risk assessment record enforcing tenant isolation."""
        assessment = self.get_by_id(assessment_id)
        return RiskAssessmentResponse.model_validate(assessment)

    def list_assessments(
        self,
        params: PaginationParams,
        risk_id: Optional[str] = None,
        assessor_type: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> RiskAssessmentListResponse:
        """List risk assessments with tenant isolation, safe filters, sorting, and search."""
        org_id = self._enforce_tenant_scope()

        if risk_id:
            parent_risk = self.uow.risks.get(risk_id, org_id=org_id)
            if not parent_risk:
                raise NotFoundError(
                    message=f"Risk with ID '{risk_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Risk", "resource_id": risk_id},
                )

        filters: dict[str, Any] = {}
        if risk_id:
            filters["risk_id"] = risk_id
        if assessor_type:
            filters["assessor_type"] = assessor_type

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=RISK_ASSESSMENT_FILTER_ALLOWLIST,
            sort_allowlist=RISK_ASSESSMENT_SORT_ALLOWLIST,
            search_columns=RISK_ASSESSMENT_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [RiskAssessmentResponse.model_validate(item) for item in paginated.items]
        return RiskAssessmentListResponse(items=items, pagination=paginated.pagination)

    def update_assessment(self, assessment_id: str, data: Any) -> None:
        """Attempting to modify an immutable risk assessment raises 405/ImmutableResourceError."""
        raise ImmutableResourceError(
            message="RiskAssessment is an immutable evaluation snapshot and cannot be modified."
        )

    def delete_assessment(self, assessment_id: str) -> None:
        """Attempting to delete an immutable risk assessment raises 405/ImmutableResourceError."""
        raise ImmutableResourceError(
            message="RiskAssessment is an immutable evaluation snapshot and cannot be deleted."
        )


# ==============================================================================
# 4. INCIDENT SERVICE
# ==============================================================================
class IncidentService(BaseService[Incident]):
    """Domain service managing real-time disruption incidents and lifecycle state."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Incident, uow, context)

    def create_incident(self, data: IncidentCreate) -> IncidentResponse:
        """Create a new incident with tenant boundary and parent risk validation."""
        org_id = self._enforce_tenant_scope()

        if data.risk_id:
            parent_risk = self.uow.risks.get(data.risk_id, org_id=org_id)
            if not parent_risk:
                raise NotFoundError(
                    message=f"Risk with ID '{data.risk_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Risk", "resource_id": data.risk_id},
                )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            incident = Incident(**payload)
            self.uow.incidents.create(incident, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Incident",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=incident.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return IncidentResponse.model_validate(incident)

    def get_incident(self, incident_id: str) -> IncidentResponse:
        """Retrieve an individual incident entity by ID enforcing tenant isolation."""
        incident = self.get_by_id(incident_id)
        return IncidentResponse.model_validate(incident)

    def list_incidents(
        self,
        params: PaginationParams,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        risk_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> IncidentListResponse:
        """List incidents with tenant isolation, safe filters, sorting, and search."""
        org_id = self._enforce_tenant_scope()

        if risk_id:
            parent_risk = self.uow.risks.get(risk_id, org_id=org_id)
            if not parent_risk:
                raise NotFoundError(
                    message=f"Risk with ID '{risk_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Risk", "resource_id": risk_id},
                )

        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if severity:
            filters["severity"] = severity
        if risk_id:
            filters["risk_id"] = risk_id

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=INCIDENT_FILTER_ALLOWLIST,
            sort_allowlist=INCIDENT_SORT_ALLOWLIST,
            search_columns=INCIDENT_SEARCH_COLUMNS,
            default_sort_field="detected_at",
            default_sort_desc=True,
        )
        items = [IncidentResponse.model_validate(item) for item in paginated.items]
        return IncidentListResponse(items=items, pagination=paginated.pagination)

    def update_incident(self, incident_id: str, data: IncidentUpdate) -> IncidentResponse:
        """Update incident attributes and manage lifecycle transitions."""
        incident = self.get_by_id(incident_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "detected_at", "updated_at"):
            update_dict.pop(forbidden, None)

        if "risk_id" in update_dict and update_dict["risk_id"] is not None:
            parent_risk = self.uow.risks.get(update_dict["risk_id"], org_id=org_id)
            if not parent_risk:
                raise NotFoundError(
                    message=f"Risk with ID '{update_dict['risk_id']}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Risk", "resource_id": update_dict["risk_id"]},
                )

        # Lifecycle management: auto-set resolved_at on resolution
        if "status" in update_dict and update_dict["status"] in ("RESOLVED", "CLOSED"):
            if not incident.resolved_at and "resolved_at" not in update_dict:
                update_dict["resolved_at"] = datetime.now(timezone.utc)

        before_data = {
            "title": incident.title,
            "status": incident.status,
            "severity": incident.severity,
            "location": incident.location,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(incident, k, v)
            incident.updated_at = datetime.now(timezone.utc)
            self.uow.incidents.update(incident, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Incident",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=incident.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return IncidentResponse.model_validate(incident)
