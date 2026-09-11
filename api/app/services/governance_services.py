"""Domain services for Decision & Governance resources (Phase 4 Step 7).

Services:
- RecommendationService (mitigation proposals & lifecycle)
- ApprovalService (human-in-the-loop sign-off with concurrency lock)
- ActionService (operational mitigation execution records)
- VerificationResultService (immutable observational post-action verification)
- AuditLogQueryService (compliance audit trail query service)
- NotificationService (user and broadcast alert lifecycle)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from pydantic import BaseModel

from app.core.context import AuthenticatedContext
from app.core.errors import (
    ConflictError,
    ImmutableResourceError,
    LifecycleStateError,
    NotFoundError,
    ValidationDomainError,
)
from app.models.governance import (
    Action,
    Approval,
    AuditLog,
    Notification,
    Recommendation,
    VerificationResult,
)
from app.repositories.audit_log import (
    AUDIT_LOG_FILTER_ALLOWLIST,
    AUDIT_LOG_SORT_ALLOWLIST,
)
from app.repositories.governance_repositories import (
    ACTION_FILTER_ALLOWLIST,
    ACTION_SEARCH_COLUMNS,
    ACTION_SORT_ALLOWLIST,
    APPROVAL_FILTER_ALLOWLIST,
    APPROVAL_SEARCH_COLUMNS,
    APPROVAL_SORT_ALLOWLIST,
    NOTIFICATION_FILTER_ALLOWLIST,
    NOTIFICATION_SEARCH_COLUMNS,
    NOTIFICATION_SORT_ALLOWLIST,
    RECOMMENDATION_FILTER_ALLOWLIST,
    RECOMMENDATION_SEARCH_COLUMNS,
    RECOMMENDATION_SORT_ALLOWLIST,
    VERIFICATION_RESULT_FILTER_ALLOWLIST,
    VERIFICATION_RESULT_SEARCH_COLUMNS,
    VERIFICATION_RESULT_SORT_ALLOWLIST,
)
from app.schemas.common import PaginationMeta, PaginationParams
from app.schemas.governance import (
    ActionCreate,
    ActionListResponse,
    ActionResponse,
    ActionStatus,
    ActionUpdate,
    ApprovalCreate,
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalResponse,
    AuditLogListResponse,
    AuditLogResponse,
    BatchNotificationReadResponse,
    NotificationCreate,
    NotificationListResponse,
    NotificationResponse,
    NotificationUpdate,
    RecommendationCreate,
    RecommendationListResponse,
    RecommendationResponse,
    RecommendationStatus,
    RecommendationUpdate,
    VerificationResultCreate,
    VerificationResultListResponse,
    VerificationResultResponse,
)
from app.services.audit_service import AuditService
from app.services.base import BaseService

if TYPE_CHECKING:
    from app.db.unit_of_work import UnitOfWork


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
# 1. RECOMMENDATION SERVICE
# ==============================================================================
class RecommendationService(BaseService[Recommendation]):
    """Domain service managing organization-scoped Recommendation entities."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Recommendation, uow, context)

    def create_recommendation(self, data: RecommendationCreate) -> RecommendationResponse:
        """Create a new recommendation entity scoped to the authenticated organization."""
        org_id = self._enforce_tenant_scope()

        # If incident_id is specified, verify ownership within same tenant
        if data.incident_id:
            incident = self.uow.incidents.get(data.incident_id, org_id=org_id)
            if not incident:
                raise NotFoundError(
                    message=f"Incident with id '{data.incident_id}' not found in organization",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Incident", "resource_id": data.incident_id},
                )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            rec = Recommendation(**payload)
            self.uow.recommendations.create(rec, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Recommendation",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=rec.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return RecommendationResponse.model_validate(rec)

    def get_recommendation(self, rec_id: str) -> RecommendationResponse:
        """Retrieve an individual recommendation by ID enforcing tenant isolation."""
        rec = self.get_by_id(rec_id)
        return RecommendationResponse.model_validate(rec)

    def list_recommendations(
        self,
        params: PaginationParams,
        incident_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> RecommendationListResponse:
        """List recommendations with safe filters, sorting, search, and pagination."""
        org_id = self._enforce_tenant_scope()
        filters: dict[str, Any] = {}
        if incident_id:
            filters["incident_id"] = incident_id
        if status:
            filters["status"] = status

        items = self.uow.recommendations.list(
            org_id=org_id,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=RECOMMENDATION_FILTER_ALLOWLIST,
            sort_allowlist=RECOMMENDATION_SORT_ALLOWLIST,
            search_columns=RECOMMENDATION_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )

        total = self.uow.recommendations.count(
            org_id=org_id,
            filters=filters,
            search=search,
            filter_allowlist=RECOMMENDATION_FILTER_ALLOWLIST,
            search_columns=RECOMMENDATION_SEARCH_COLUMNS,
        )

        return RecommendationListResponse(
            items=[RecommendationResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=(total + params.limit - 1) // params.limit if total > 0 else 0,
            ),
        )

    def update_recommendation(self, rec_id: str, data: RecommendationUpdate) -> RecommendationResponse:
        """Update an existing recommendation record with row-level concurrency locking and lifecycle enforcement."""
        org_id = self._enforce_tenant_scope()
        update_data = _clean_payload(data)

        if not update_data:
            return self.get_recommendation(rec_id)

        with self.uow:
            rec = self.uow.recommendations.get_for_update(rec_id, org_id=org_id)
            if not rec:
                raise NotFoundError(
                    message=f"Recommendation with id '{rec_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Recommendation", "resource_id": rec_id},
                )

            # Contract lifecycle rule: recommendations can only be edited prior to approval/execution
            if rec.status in (
                RecommendationStatus.APPROVED.value,
                RecommendationStatus.REJECTED.value,
                RecommendationStatus.EXECUTED.value,
            ):
                # If only status update is attempted, validate allowed lifecycle transition
                if "status" in update_data and len(update_data) == 1:
                    new_status = update_data["status"]
                    if rec.status == RecommendationStatus.APPROVED.value and new_status == RecommendationStatus.EXECUTED.value:
                        pass  # Allowed transition
                    else:
                        raise LifecycleStateError(
                            message=f"Cannot transition recommendation from '{rec.status}' to '{new_status}'",
                            code="INVALID_LIFECYCLE_TRANSITION",
                            details={"current_status": rec.status, "target_status": new_status},
                        )
                else:
                    raise LifecycleStateError(
                        message=f"Cannot update recommendation in finalized status '{rec.status}'",
                        code="RECOMMENDATION_ALREADY_FINALIZED",
                        details={"current_status": rec.status},
                    )

            # If status is being updated, validate valid target state
            if "status" in update_data:
                valid_targets = {
                    RecommendationStatus.PENDING.value,
                    RecommendationStatus.APPROVED.value,
                    RecommendationStatus.REJECTED.value,
                    RecommendationStatus.EXECUTED.value,
                }
                if update_data["status"] not in valid_targets:
                    raise LifecycleStateError(
                        message=f"Invalid target recommendation status '{update_data['status']}'",
                        code="INVALID_LIFECYCLE_STATE",
                    )

            before_data = {
                "title": rec.title,
                "rationale": rec.rationale,
                "estimated_cost": rec.estimated_cost,
                "expected_benefit_json": rec.expected_benefit_json,
                "confidence": rec.confidence,
                "status": rec.status,
            }

            for field, val in update_data.items():
                setattr(rec, field, val)

            self.uow.recommendations.update(rec, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Recommendation",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=rec.id,
                before_data=before_data,
                after_data=update_data,
                auto_commit=False,
            )
            self.uow.commit()

        return RecommendationResponse.model_validate(rec)


# ==============================================================================
# 2. APPROVAL SERVICE
# ==============================================================================
class ApprovalService(BaseService[Approval]):
    """Domain service managing human-in-the-loop Approval decisions with concurrency protection."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Approval, uow, context)

    def create_approval(self, data: ApprovalCreate) -> ApprovalResponse:
        """Record formal sign-off on a recommendation and atomically transition its lifecycle state."""
        org_id = self._enforce_tenant_scope()

        with self.uow:
            # Row-level lock on recommendation prevents concurrent dual decisions
            rec = self.uow.recommendations.get_for_update(data.recommendation_id, org_id=org_id)
            if not rec:
                raise NotFoundError(
                    message=f"Recommendation with id '{data.recommendation_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Recommendation", "resource_id": data.recommendation_id},
                )

            # Contract lifecycle rule: only PENDING recommendations can receive formal approval decisions
            if rec.status != RecommendationStatus.PENDING.value:
                raise LifecycleStateError(
                    message=f"Recommendation is in '{rec.status}' status and cannot be decided upon",
                    code="INVALID_LIFECYCLE_STATE",
                    details={"current_status": rec.status},
                )

            decision_str = data.decision.value if hasattr(data.decision, "value") else str(data.decision)

            # Map decision to recommendation lifecycle status
            if decision_str == ApprovalDecision.APPROVE.value:
                rec.status = RecommendationStatus.APPROVED.value
            elif decision_str == ApprovalDecision.REJECT.value:
                rec.status = RecommendationStatus.REJECTED.value
            elif decision_str == ApprovalDecision.REQUEST_MODIFICATION.value:
                rec.status = RecommendationStatus.PENDING.value
            else:
                raise LifecycleStateError(
                    message=f"Unknown approval decision '{decision_str}'",
                    code="INVALID_APPROVAL_DECISION",
                )

            self.uow.recommendations.update(rec, auto_commit=False)

            user_id = self.context.user_id if self.context else None

            approval = Approval(
                recommendation_id=rec.id,
                decided_by_user_id=user_id,
                decision=decision_str,
                comments=data.comments,
            )
            self.uow.approvals.create(approval, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action=f"APPROVAL_{decision_str}",
                resource_type="Approval",
                org_id=org_id,
                actor_id=user_id,
                resource_id=approval.id,
                after_data={
                    "recommendation_id": rec.id,
                    "decision": decision_str,
                    "comments": data.comments,
                    "new_recommendation_status": rec.status,
                },
                auto_commit=False,
            )
            self.uow.commit()

        return ApprovalResponse.model_validate(approval)

    def get_approval(self, approval_id: str) -> ApprovalResponse:
        """Retrieve an individual approval record verifying parent recommendation belongs to the tenant."""
        org_id = self._enforce_tenant_scope()
        approval = self.uow.approvals.get_approval_in_org(approval_id, org_id)
        if not approval:
            raise NotFoundError(
                message=f"Approval with id '{approval_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Approval", "resource_id": approval_id},
            )
        return ApprovalResponse.model_validate(approval)

    def list_approvals(
        self,
        params: PaginationParams,
        recommendation_id: Optional[str] = None,
        decision: Optional[str] = None,
        decided_by_user_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> ApprovalListResponse:
        """List approvals scoped to tenant recommendations with pagination, filters, and sorting."""
        org_id = self._enforce_tenant_scope()
        items, total = self.uow.approvals.list_approvals_for_org(
            org_id=org_id,
            recommendation_id=recommendation_id,
            decision=decision,
            decided_by_user_id=decided_by_user_id,
            page=params.page,
            limit=params.limit,
            sort_param=sort_param,
            search=search,
        )

        return ApprovalListResponse(
            items=[ApprovalResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=(total + params.limit - 1) // params.limit if total > 0 else 0,
            ),
        )


# ==============================================================================
# 3. ACTION SERVICE
# ==============================================================================
class ActionService(BaseService[Action]):
    """Domain service managing operational mitigation execution records."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Action, uow, context)

    def create_action(self, data: ActionCreate) -> ActionResponse:
        """Record an operational mitigation action within the authenticated organization."""
        org_id = self._enforce_tenant_scope()

        # If linked to a recommendation, verify tenant ownership and APPROVED status
        if data.recommendation_id:
            rec = self.uow.recommendations.get(data.recommendation_id, org_id=org_id)
            if not rec:
                raise NotFoundError(
                    message=f"Recommendation with id '{data.recommendation_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Recommendation", "resource_id": data.recommendation_id},
                )
            if rec.status != RecommendationStatus.APPROVED.value:
                raise LifecycleStateError(
                    message=f"Cannot create action for recommendation with status '{rec.status}'. Recommendation must be APPROVED.",
                    code="RECOMMENDATION_NOT_APPROVED",
                    details={"current_status": rec.status},
                )

        payload = _clean_payload(data)
        payload["org_id"] = org_id
        payload.setdefault("status", ActionStatus.EXECUTING.value)

        with self.uow:
            action = Action(**payload)
            self.uow.actions.create(action, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Action",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=action.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return ActionResponse.model_validate(action)

    def get_action(self, action_id: str) -> ActionResponse:
        """Retrieve an individual action record by ID enforcing tenant isolation."""
        action = self.get_by_id(action_id)
        return ActionResponse.model_validate(action)

    def list_actions(
        self,
        params: PaginationParams,
        status: Optional[str] = None,
        action_type: Optional[str] = None,
        target_entity_type: Optional[str] = None,
        recommendation_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> ActionListResponse:
        """List actions with safe filters, sorting, search, and pagination."""
        org_id = self._enforce_tenant_scope()
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if action_type:
            filters["action_type"] = action_type
        if target_entity_type:
            filters["target_entity_type"] = target_entity_type
        if recommendation_id:
            filters["recommendation_id"] = recommendation_id

        items = self.uow.actions.list(
            org_id=org_id,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=ACTION_FILTER_ALLOWLIST,
            sort_allowlist=ACTION_SORT_ALLOWLIST,
            search_columns=ACTION_SEARCH_COLUMNS,
            default_sort_field="executed_at",
            default_sort_desc=True,
        )

        total = self.uow.actions.count(
            org_id=org_id,
            filters=filters,
            search=search,
            filter_allowlist=ACTION_FILTER_ALLOWLIST,
            search_columns=ACTION_SEARCH_COLUMNS,
        )

        return ActionListResponse(
            items=[ActionResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=(total + params.limit - 1) // params.limit if total > 0 else 0,
            ),
        )

    def update_action(self, action_id: str, data: ActionUpdate) -> ActionResponse:
        """Update an action's execution status or result payload with row-level concurrency locking."""
        org_id = self._enforce_tenant_scope()
        update_data = _clean_payload(data)

        if not update_data:
            return self.get_action(action_id)

        with self.uow:
            action = self.uow.actions.get_for_update(action_id, org_id=org_id)
            if not action:
                raise NotFoundError(
                    message=f"Action with id '{action_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Action", "resource_id": action_id},
                )

            # Contract lifecycle rule: terminal states cannot transition further
            if action.status in (ActionStatus.COMPLETED.value, ActionStatus.FAILED.value):
                raise LifecycleStateError(
                    message=f"Cannot transition action from finalized terminal state '{action.status}'",
                    code="ACTION_ALREADY_FINALIZED",
                    details={"current_status": action.status},
                )

            new_status = update_data.get("status")
            if new_status:
                valid_transitions = {
                    ActionStatus.PENDING.value: {ActionStatus.EXECUTING.value, ActionStatus.FAILED.value},
                    ActionStatus.EXECUTING.value: {ActionStatus.COMPLETED.value, ActionStatus.FAILED.value},
                }
                allowed = valid_transitions.get(action.status, set())
                if new_status not in allowed:
                    raise LifecycleStateError(
                        message=f"Invalid action state transition from '{action.status}' to '{new_status}'",
                        code="INVALID_LIFECYCLE_TRANSITION",
                        details={"current_status": action.status, "target_status": new_status},
                    )

                # If action completed and is linked to a recommendation, mark recommendation EXECUTED
                if new_status == ActionStatus.COMPLETED.value and action.recommendation_id:
                    rec = self.uow.recommendations.get_for_update(action.recommendation_id, org_id=org_id)
                    if rec:
                        rec.status = RecommendationStatus.EXECUTED.value
                        self.uow.recommendations.update(rec, auto_commit=False)

            before_data = {
                "status": action.status,
                "result_payload": action.result_payload,
            }

            for field, val in update_data.items():
                setattr(action, field, val)

            self.uow.actions.update(action, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Action",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=action.id,
                before_data=before_data,
                after_data=update_data,
                auto_commit=False,
            )
            self.uow.commit()

        return ActionResponse.model_validate(action)

    def execute_action(self, action_id: str) -> ActionResponse:
        """Trigger execution progression on an action record."""
        org_id = self._enforce_tenant_scope()

        with self.uow:
            action = self.uow.actions.get_for_update(action_id, org_id=org_id)
            if not action:
                raise NotFoundError(
                    message=f"Action with id '{action_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Action", "resource_id": action_id},
                )

            if action.status == ActionStatus.PENDING.value:
                action.status = ActionStatus.EXECUTING.value
            elif action.status == ActionStatus.EXECUTING.value:
                action.status = ActionStatus.COMPLETED.value
                if action.recommendation_id:
                    rec = self.uow.recommendations.get_for_update(action.recommendation_id, org_id=org_id)
                    if rec:
                        rec.status = RecommendationStatus.EXECUTED.value
                        self.uow.recommendations.update(rec, auto_commit=False)
            else:
                raise LifecycleStateError(
                    message=f"Action is already in finalized state '{action.status}'",
                    code="ACTION_ALREADY_FINALIZED",
                    details={"current_status": action.status},
                )

            self.uow.actions.update(action, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="EXECUTE",
                resource_type="Action",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=action.id,
                after_data={"status": action.status},
                auto_commit=False,
            )
            self.uow.commit()

        return ActionResponse.model_validate(action)


# ==============================================================================
# 4. VERIFICATION RESULT SERVICE
# ==============================================================================
class VerificationResultService(BaseService[VerificationResult]):
    """Domain service managing post-action observational verification records (Strictly Immutable)."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(VerificationResult, uow, context)

    def create_verification_result(self, data: VerificationResultCreate) -> VerificationResultResponse:
        """Record an immutable verification result for an action."""
        org_id = self._enforce_tenant_scope()

        with self.uow:
            # Verify parent action exists and belongs to the tenant
            action = self.uow.actions.get(data.action_id, org_id=org_id)
            if not action:
                raise NotFoundError(
                    message=f"Action with id '{data.action_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Action", "resource_id": data.action_id},
                )

            # Verification result is 1:1 with action
            existing = self.uow.verification_results.get_by_action_id_in_org(data.action_id, org_id)
            if existing:
                raise ConflictError(
                    message=f"Verification result already exists for action '{data.action_id}'",
                    code="VERIFICATION_RESULT_ALREADY_EXISTS",
                    details={"action_id": data.action_id, "existing_result_id": existing.id},
                )

            payload = _clean_payload(data)
            result = VerificationResult(**payload)
            self.uow.verification_results.create(result, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="VerificationResult",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=result.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return VerificationResultResponse.model_validate(result)

    def get_verification_result(self, result_id: str) -> VerificationResultResponse:
        """Retrieve an individual verification result verifying parent action belongs to tenant."""
        org_id = self._enforce_tenant_scope()
        result = self.uow.verification_results.get_result_in_org(result_id, org_id)
        if not result:
            raise NotFoundError(
                message=f"Verification result with id '{result_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "VerificationResult", "resource_id": result_id},
            )
        return VerificationResultResponse.model_validate(result)

    def list_verification_results(
        self,
        params: PaginationParams,
        action_id: Optional[str] = None,
        verified: Optional[bool] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> VerificationResultListResponse:
        """List verification results scoped to tenant actions with pagination, filters, and sorting."""
        org_id = self._enforce_tenant_scope()
        items, total = self.uow.verification_results.list_results_for_org(
            org_id=org_id,
            action_id=action_id,
            verified=verified,
            page=params.page,
            limit=params.limit,
            sort_param=sort_param,
            search=search,
        )

        return VerificationResultListResponse(
            items=[VerificationResultResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=(total + params.limit - 1) // params.limit if total > 0 else 0,
            ),
        )


# ==============================================================================
# 5. AUDIT LOG QUERY SERVICE
# ==============================================================================
class AuditLogQueryService(BaseService[AuditLog]):
    """Domain service providing read-only compliance query access to tenant audit logs."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(AuditLog, uow, context)

    def get_audit_log(self, log_id: str) -> AuditLogResponse:
        """Retrieve an individual audit log entry with tenant isolation."""
        log = self.get_by_id(log_id)
        return AuditLogResponse.model_validate(log)

    def list_audit_logs(
        self,
        params: PaginationParams,
        actor_type: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        status: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> AuditLogListResponse:
        """List audit log entries with safe filters, sorting, and pagination."""
        org_id = self._enforce_tenant_scope()
        filters: dict[str, Any] = {}
        if actor_type:
            filters["actor_type"] = actor_type
        if action:
            filters["action"] = action
        if resource_type:
            filters["resource_type"] = resource_type
        if status:
            filters["status"] = status

        items = self.uow.audit_logs.list(
            org_id=org_id,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            filter_allowlist=AUDIT_LOG_FILTER_ALLOWLIST,
            sort_allowlist=AUDIT_LOG_SORT_ALLOWLIST,
            default_sort_field="timestamp",
            default_sort_desc=True,
        )

        total = self.uow.audit_logs.count(
            org_id=org_id,
            filters=filters,
            filter_allowlist=AUDIT_LOG_FILTER_ALLOWLIST,
        )

        return AuditLogListResponse(
            items=[AuditLogResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=(total + params.limit - 1) // params.limit if total > 0 else 0,
            ),
        )


# ==============================================================================
# 6. NOTIFICATION SERVICE
# ==============================================================================
class NotificationService(BaseService[Notification]):
    """Domain service managing user alerts and team notifications."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Notification, uow, context)

    def create_notification(self, data: NotificationCreate) -> NotificationResponse:
        """Create a notification for a user or broadcast to tenant organization."""
        org_id = self._enforce_tenant_scope()
        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            notification = Notification(**payload)
            self.uow.notifications.create(notification, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Notification",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=notification.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return NotificationResponse.model_validate(notification)

    def get_notification(self, notif_id: str) -> NotificationResponse:
        """Retrieve a notification by ID enforcing tenant and user scoping."""
        org_id = self._enforce_tenant_scope()
        user_id = self.context.user_id if self.context else None

        notif = self.uow.notifications.get(notif_id, org_id=org_id)
        if not notif:
            raise NotFoundError(
                message=f"Notification with id '{notif_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Notification", "resource_id": notif_id},
            )

        # Scoped to recipient user or organization broadcast
        if notif.user_id and user_id and notif.user_id != user_id:
            raise NotFoundError(
                message=f"Notification with id '{notif_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Notification", "resource_id": notif_id},
            )

        return NotificationResponse.model_validate(notif)

    def list_notifications(
        self,
        params: PaginationParams,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        is_read: Optional[bool] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> NotificationListResponse:
        """List notifications for current user/organization with safe filters, sorting, and pagination."""
        org_id = self._enforce_tenant_scope()
        user_id = self.context.user_id if self.context else None

        items, total = self.uow.notifications.list_for_user(
            org_id=org_id,
            user_id=user_id,
            category=category,
            severity=severity,
            is_read=is_read,
            page=params.page,
            limit=params.limit,
            sort_param=sort_param,
            search=search,
        )

        return NotificationListResponse(
            items=[NotificationResponse.model_validate(item) for item in items],
            pagination=PaginationMeta(
                total=total,
                page=params.page,
                limit=params.limit,
                pages=(total + params.limit - 1) // params.limit if total > 0 else 0,
            ),
        )

    def mark_as_read(self, notif_id: str, is_read: bool = True) -> NotificationResponse:
        """Update notification read status."""
        org_id = self._enforce_tenant_scope()
        user_id = self.context.user_id if self.context else None

        with self.uow:
            notif = self.uow.notifications.get(notif_id, org_id=org_id)
            if not notif:
                raise NotFoundError(
                    message=f"Notification with id '{notif_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Notification", "resource_id": notif_id},
                )

            if notif.user_id and user_id and notif.user_id != user_id:
                raise NotFoundError(
                    message=f"Notification with id '{notif_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Notification", "resource_id": notif_id},
                )

            notif.is_read = is_read
            self.uow.notifications.update(notif, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Notification",
                org_id=org_id,
                actor_id=user_id,
                resource_id=notif.id,
                after_data={"is_read": is_read},
                auto_commit=False,
            )
            self.uow.commit()

        return NotificationResponse.model_validate(notif)

    def mark_all_as_read(self) -> BatchNotificationReadResponse:
        """Mark all unread notifications for the user/organization as read."""
        org_id = self._enforce_tenant_scope()
        user_id = self.context.user_id if self.context else None

        with self.uow:
            updated_count = self.uow.notifications.mark_all_read_for_user(org_id=org_id, user_id=user_id)
            if updated_count > 0:
                AuditService.log_event(
                    uow=self.uow,
                    action="BATCH_MARK_READ",
                    resource_type="Notification",
                    org_id=org_id,
                    actor_id=user_id,
                    after_data={"updated_count": updated_count},
                    auto_commit=False,
                )
            self.uow.commit()

        return BatchNotificationReadResponse(
            updated_count=updated_count,
            message="All notifications marked as read",
        )
