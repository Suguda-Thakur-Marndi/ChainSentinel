"""Recommendations API endpoints for RiskWise 2.0 (Phase 4 Step 7).

Mitigation proposals generated for active incidents.
Organization-scoped.

Endpoints:
- GET /api/v1/recommendations (Protected, Viewer+: list recommendations with pagination, filter, search, sort)
- POST /api/v1/recommendations (Protected, Analyst+: create recommendation record)
- GET /api/v1/recommendations/{id} (Protected, Viewer+: get single recommendation by ID)
- PATCH /api/v1/recommendations/{id} (Protected, Analyst+: update recommendation details)
- POST /api/v1/recommendations/{id}/approve (Protected, RiskManager+: formal approval transition)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.governance_repositories import RECOMMENDATION_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.governance import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalResponse,
    RecommendationCreate,
    RecommendationListResponse,
    RecommendationResponse,
    RecommendationUpdate,
)
from app.services.governance_services import ApprovalService, RecommendationService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
MUTATION_ROLES = ("Analyst", "RiskManager", "Admin")
APPROVAL_ROLES = ("RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_recommendation_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RecommendationService:
    """Dependency injecting configured RecommendationService."""
    return RecommendationService(uow=uow, context=context)


def get_approval_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalService:
    """Dependency injecting configured ApprovalService."""
    return ApprovalService(uow=uow, context=context)


@router.get(
    "",
    response_model=RecommendationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List recommendations",
    description="Retrieve a paginated list of mitigation proposals for the tenant.",
)
def list_recommendations(
    request: Request,
    params: PaginationParams = Depends(),
    incident_id: Optional[str] = Query(None, description="Filter by associated incident ID"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by recommendation status (PENDING, APPROVED, REJECTED, EXECUTED)"),
    search: Optional[str] = Query(None, description="Substring search across title and rationale"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. created_at, -created_at, confidence, -confidence, estimated_cost)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationListResponse:
    """List recommendations with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in RECOMMENDATION_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(RECOMMENDATION_FILTER_ALLOWLIST.keys()))

    return service.list_recommendations(
        params=params,
        incident_id=incident_id,
        status=status_filter,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=RecommendationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create recommendation",
    description="Record a new mitigation recommendation proposal. Requires Analyst role or higher.",
)
def create_recommendation(
    body: RecommendationCreate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationResponse:
    """Create a new recommendation proposal within the authenticated tenant boundary."""
    return service.create_recommendation(body)


@router.get(
    "/{id}",
    response_model=RecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get recommendation by ID",
    description="Retrieve an individual recommendation record by ID with 404 masking.",
)
def get_recommendation(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationResponse:
    """Retrieve a single recommendation record enforcing tenant isolation."""
    return service.get_recommendation(id)


@router.patch(
    "/{id}",
    response_model=RecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update recommendation",
    description="Update an existing recommendation record prior to formal approval. Requires Analyst role or higher.",
)
def update_recommendation(
    id: str,
    body: RecommendationUpdate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RecommendationService = Depends(get_recommendation_service),
) -> RecommendationResponse:
    """Update a recommendation record enforcing state machine constraints."""
    return service.update_recommendation(id, body)


@router.post(
    "/{id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve recommendation",
    description="Convenience RPC endpoint for Risk Managers to formally sign off on a recommendation.",
)
def approve_recommendation(
    id: str,
    comments: Optional[str] = Query(None, description="Optional approval comments"),
    context: AuthenticatedContext = Depends(require_role(*APPROVAL_ROLES)),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    """Formally approve a pending recommendation proposal."""
    approval_data = ApprovalCreate(
        recommendation_id=id,
        decision=ApprovalDecision.APPROVE,
        comments=comments,
    )
    return approval_service.create_approval(approval_data)
