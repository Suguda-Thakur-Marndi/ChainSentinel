"""Approvals API endpoints for RiskWise 2.0 (Phase 4 Step 7).

Human-in-the-loop formal governance sign-off on recommendations.
Scoped hierarchically via parent recommendation's organization ownership.
Strictly immutable.

Endpoints:
- GET /api/v1/approvals (Protected, Viewer+: list approvals with pagination, filter, search, sort)
- POST /api/v1/approvals (Protected, RiskManager+: record formal approval sign-off)
- GET /api/v1/approvals/{id} (Protected, Viewer+: get single approval by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.governance_repositories import APPROVAL_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.governance import (
    ApprovalCreate,
    ApprovalListResponse,
    ApprovalResponse,
)
from app.services.governance_services import ApprovalService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_approval_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalService:
    """Dependency injecting configured ApprovalService."""
    return ApprovalService(uow=uow, context=context)


@router.get(
    "",
    response_model=ApprovalListResponse,
    status_code=status.HTTP_200_OK,
    summary="List approvals",
    description="Retrieve a paginated list of formal approval sign-offs for tenant recommendations.",
)
def list_approvals(
    request: Request,
    params: PaginationParams = Depends(),
    recommendation_id: Optional[str] = Query(None, description="Filter by parent recommendation ID"),
    decision: Optional[str] = Query(None, description="Filter by decision (APPROVE, REJECT, REQUEST_MODIFICATION)"),
    decided_by_user_id: Optional[str] = Query(None, description="Filter by approver user ID"),
    search: Optional[str] = Query(None, description="Substring search across decision and comments"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. decided_at, -decided_at, decision)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalListResponse:
    """List approvals with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in APPROVAL_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(APPROVAL_FILTER_ALLOWLIST.keys()))

    return service.list_approvals(
        params=params,
        recommendation_id=recommendation_id,
        decision=decision,
        decided_by_user_id=decided_by_user_id,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=ApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create approval",
    description="Record formal sign-off on a recommendation. Requires RiskManager role or higher.",
)
def create_approval(
    body: ApprovalCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    """Record formal sign-off on a recommendation with concurrency lock and lifecycle transition."""
    return service.create_approval(body)


@router.get(
    "/{id}",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get approval by ID",
    description="Retrieve an individual approval record by ID ensuring parent recommendation belongs to tenant.",
)
def get_approval(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    """Retrieve a single approval record enforcing tenant isolation."""
    return service.get_approval(id)
