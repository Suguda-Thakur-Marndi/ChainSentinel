"""Approvals API endpoints for RiskWise 2.0 (Phase 4 Step 7 & Phase 16 Human Approval).

Human-in-the-loop formal governance sign-off on recommendations and operational decisions.
Scoped hierarchically via organization ownership.
Strictly immutable.

Endpoints:
- GET /api/v1/approvals/pending (Protected, Viewer+: list pending decisions awaiting human sign-off)
- GET /api/v1/approvals/{id}/dossier (Protected, Viewer+: retrieve comprehensive review dossier)
- POST /api/v1/approvals/{id}/decide (Protected, RiskManager+: record human decision sign-off)
- POST /api/v1/approvals/{id}/approve (Protected, RiskManager+: approve operational mitigation)
- POST /api/v1/approvals/{id}/reject (Protected, RiskManager+: reject operational mitigation)
- GET /api/v1/approvals (Protected, Viewer+: list approvals with pagination, filter, search, sort)
- POST /api/v1/approvals (Protected, RiskManager+: record formal approval sign-off)
- GET /api/v1/approvals/{id} (Protected, Viewer+: get single approval by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.agents.approval.contract import (
    ApprovalDecision,
    ApprovalDossier,
    HumanDecisionRequest,
    PendingApprovalItem,
    PendingApprovalListResponse,
)
from app.agents.approval.errors import (
    ApprovalAlreadyFinalizedError,
    ApprovalAuthorizationError,
    ApprovalNotFoundError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
    InvalidApprovalTransitionError,
)
from app.agents.approval.persistence import ApprovalRepository
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


class SignoffCommentRequest(BaseModel):
    """Optional comments payload for direct approve/reject endpoints."""

    model_config = ConfigDict(extra="forbid")

    comments: Optional[str] = Field(default=None, max_length=1000)


def get_approval_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalService:
    """Dependency injecting configured ApprovalService."""
    return ApprovalService(uow=uow, context=context)


# ==============================================================================
# PHASE 16: HUMAN APPROVAL & REVIEW DOSSIER ENDPOINTS
# ==============================================================================


@router.get(
    "/pending",
    response_model=PendingApprovalListResponse,
    status_code=status.HTTP_200_OK,
    summary="List pending approvals",
    description="Retrieve all operational decisions pending formal human governance sign-off.",
)
def list_pending_approvals(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term across title, rationale, or ID"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> PendingApprovalListResponse:
    """List decisions pending human sign-off for authenticated tenant."""
    org_id = context.organization_id or ""
    offset = (page - 1) * limit

    with uow:
        items, total = ApprovalRepository.list_pending_approvals(
            db=uow.session,
            organization_id=org_id,
            limit=limit,
            offset=offset,
            search=search,
        )

    return PendingApprovalListResponse(
        items=items,
        total=total,
        page=page,
        page_size=limit,
    )


@router.get(
    "/{id}/dossier",
    response_model=ApprovalDossier,
    status_code=status.HTTP_200_OK,
    summary="Get approval review dossier",
    description="Retrieve comprehensive decision context, tradeoffs, Claude explanation, and audit trail for human review.",
)
def get_approval_dossier(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalDossier:
    """Retrieve full review dossier for human inspection before sign-off."""
    org_id = context.organization_id or ""
    try:
        with uow:
            return ApprovalRepository.get_approval_dossier(
                db=uow.session,
                organization_id=org_id,
                id_or_decision_id=id,
            )
    except ApprovalNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ApprovalTenantIsolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/{id}/decide",
    response_model=ApprovalDossier,
    status_code=status.HTTP_200_OK,
    summary="Record human approval decision",
    description="Record formal human sign-off (APPROVE or REJECT) on a decision candidate. Requires RiskManager or Admin.",
)
def record_human_decision(
    id: str,
    body: HumanDecisionRequest,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalDossier:
    """Record human approval or rejection with row-level concurrency lock and immutable audit logging."""
    org_id = context.organization_id or ""
    user_id = context.user_id or "unknown_human"
    role = getattr(context, "role", "RiskManager") or "RiskManager"
    request_id = getattr(context, "request_id", None)

    try:
        with uow:
            dossier = ApprovalRepository.record_human_decision(
                db=uow.session,
                organization_id=org_id,
                id_or_decision_id=id,
                decision=body.decision,
                actor_id=user_id,
                actor_role=role,
                comments=body.comments,
                request_id=request_id,
            )
            uow.commit()
            return dossier
    except ApprovalNotFoundError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ApprovalTenantIsolationError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ApprovalAuthorizationError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ApprovalAlreadyFinalizedError as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (InvalidApprovalRequestError, InvalidApprovalTransitionError) as e:
        uow.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


@router.post(
    "/{id}/approve",
    response_model=ApprovalDossier,
    status_code=status.HTTP_200_OK,
    summary="Approve decision candidate",
    description="Convenience endpoint to approve an operational decision candidate.",
)
def approve_decision(
    id: str,
    body: Optional[SignoffCommentRequest] = None,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalDossier:
    """Directly approve a decision candidate."""
    req = HumanDecisionRequest(
        decision=ApprovalDecision.APPROVE,
        comments=body.comments if body else None,
    )
    return record_human_decision(id=id, body=req, context=context, uow=uow)


@router.post(
    "/{id}/reject",
    response_model=ApprovalDossier,
    status_code=status.HTTP_200_OK,
    summary="Reject decision candidate",
    description="Convenience endpoint to reject an operational decision candidate.",
)
def reject_decision(
    id: str,
    body: Optional[SignoffCommentRequest] = None,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> ApprovalDossier:
    """Directly reject a decision candidate."""
    req = HumanDecisionRequest(
        decision=ApprovalDecision.REJECT,
        comments=body.comments if body else None,
    )
    return record_human_decision(id=id, body=req, context=context, uow=uow)


# ==============================================================================
# PHASE 4: GENERAL CRUD APPROVALS ENDPOINTS (PRESERVED)
# ==============================================================================


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
