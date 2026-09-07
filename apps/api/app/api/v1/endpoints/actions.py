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
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
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
