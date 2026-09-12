"""Actions API endpoints for RiskWise 2.0 (Phase 4 Step 7).

Executed operational mitigation actions altering supply chain operations.
Organization-scoped.

Endpoints:
- GET /api/v1/actions (Protected, Viewer+: list actions with pagination, filter, search, sort)
- POST /api/v1/actions (Protected, RiskManager+: record operational mitigation action)
- GET /api/v1/actions/{id} (Protected, Viewer+: get single action by ID)
- PATCH /api/v1/actions/{id} (Protected, RiskManager+: update execution status or payload)
- POST /api/v1/actions/{id}/execute (Protected, RiskManager+: advance action execution lifecycle)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.agents.action import (
    ActionAgent,
    ActionApprovalInvalidError,
    ActionApprovalMismatchError,
    ActionApprovalMissingError,
    ActionAuthorizationError,
    ActionCommand,
    ActionIdempotencyConflictError,
    ActionResult,
    ActionSecurityViolationError,
    ActionStaleDecisionError,
    ActionTargetNotFoundError,
    ActionTargetStateConflictError,
    ActionTenantIsolationError,
    ActionUnsupportedTypeError,
)
from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.models.governance import Approval, Recommendation
from app.repositories.governance_repositories import ACTION_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.governance import (
    ActionCreate,
    ActionListResponse,
    ActionResponse,
    ActionUpdate,
)
from app.services.governance_services import ActionService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
EXECUTE_ROLES = ("RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_action_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ActionService:
    """Dependency injecting configured ActionService."""
    return ActionService(uow=uow, context=context)


@router.get(
    "",
    response_model=ActionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List actions",
    description="Retrieve a paginated list of operational mitigation actions for the tenant.",
)
def list_actions(
    request: Request,
    params: PaginationParams = Depends(),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by action status (PENDING, EXECUTING, COMPLETED, FAILED)"),
    action_type: Optional[str] = Query(None, description="Filter by action type"),
    target_entity_type: Optional[str] = Query(None, description="Filter by target entity type (SHIPMENT, SUPPLIER, FACILITY, ROUTE, INVENTORY)"),
    recommendation_id: Optional[str] = Query(None, description="Filter by associated recommendation ID"),
    search: Optional[str] = Query(None, description="Substring search across action_type, target_entity_type, target_entity_id"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. executed_at, -executed_at, status, -status, action_type)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ActionService = Depends(get_action_service),
) -> ActionListResponse:
    """List actions with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in ACTION_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(ACTION_FILTER_ALLOWLIST.keys()))

    return service.list_actions(
        params=params,
        status=status_filter,
        action_type=action_type,
        target_entity_type=target_entity_type,
        recommendation_id=recommendation_id,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=ActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create action",
    description="Record an operational mitigation action within the tenant partition. Requires RiskManager role or higher.",
)
def create_action(
    body: ActionCreate,
    context: AuthenticatedContext = Depends(require_role(*EXECUTE_ROLES)),
    service: ActionService = Depends(get_action_service),
) -> ActionResponse:
    """Create a new operational mitigation action record."""
    return service.create_action(body)


@router.get(
    "/{id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get action by ID",
    description="Retrieve an individual action record by ID with 404 masking.",
)
def get_action(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ActionService = Depends(get_action_service),
) -> ActionResponse:
    """Retrieve a single action record enforcing tenant isolation."""
    return service.get_action(id)


@router.patch(
    "/{id}",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update action",
    description="Update execution status or result payload for an active action. Requires RiskManager role or higher.",
)
def update_action(
    id: str,
    body: ActionUpdate,
    context: AuthenticatedContext = Depends(require_role(*EXECUTE_ROLES)),
    service: ActionService = Depends(get_action_service),
) -> ActionResponse:
    """Update action status and result payload with state machine validation."""
    return service.update_action(id, body)


@router.post(
    "/{id}/execute",
    response_model=ActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute action",
    description="Advance the execution lifecycle of an action. Requires RiskManager role or higher.",
)
def execute_action(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*EXECUTE_ROLES)),
    service: ActionService = Depends(get_action_service),
) -> ActionResponse:
    """Trigger lifecycle progression on an operational action."""
    return service.execute_action(id)


@router.post(
    "/execute",
    response_model=ActionResult,
    status_code=status.HTTP_200_OK,
    summary="Execute approved operational mitigation action (Phase 17)",
    description="Execute an approved operational mitigation action. Strictly requires prior human approval and RiskManager role.",
)
def execute_approved_action(
    body: ActionCommand,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    context: AuthenticatedContext = Depends(require_role(*EXECUTE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> ActionResult:
    """Dispatches allowlisted operational mitigation action requiring valid human approval."""
    org_id = context.organization_id or ""
    user_id = context.user_id or "user_operator"
    role = getattr(context, "role", "RiskManager") or "RiskManager"

    # Enforce tenant match
    if body.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cross-tenant action request: payload tenant '{body.organization_id}' does not match authenticated tenant '{org_id}'.",
        )

    # Use header idempotency key if provided
    if x_idempotency_key and not body.idempotency_key:
        body.idempotency_key = x_idempotency_key.strip()

    try:
        with uow:
            # Query approval record
            approval = (
                uow.session.query(Approval)
                .filter(
                    (Approval.id == body.approval_id) | (Approval.recommendation_id == body.decision_id)
                )
                .first()
            )
            if not approval:
                # Also check recommendation if recommendation is approved
                rec = (
                    uow.session.query(Recommendation)
                    .filter(
                        Recommendation.id == body.decision_id,
                        Recommendation.org_id == org_id,
                    )
                    .first()
                )
                if rec and rec.status == "APPROVED":
                    approval = Approval(
                        id=body.approval_id,
                        recommendation_id=body.decision_id,
                        decision="APPROVE",
                        decided_by_user_id=user_id,
                    )

            agent = ActionAgent()
            result, _ = agent.execute(command=body, approval=approval, db=uow.session, uow=uow)
            uow.commit()
            return result

    except ActionApprovalMissingError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ActionApprovalInvalidError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    except (ActionApprovalMismatchError, ActionIdempotencyConflictError, ActionStaleDecisionError, ActionTargetStateConflictError) as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ActionTargetNotFoundError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (ActionTenantIsolationError, ActionAuthorizationError) as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (ActionSecurityViolationError, ActionUnsupportedTypeError) as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))

