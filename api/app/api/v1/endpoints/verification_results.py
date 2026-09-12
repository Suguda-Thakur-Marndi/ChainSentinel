"""Verification Results API endpoints for RiskWise 2.0 (Phase 4 Step 7).

Post-action observational verification comparing risk metrics before and after mitigation.
Scoped hierarchically via parent action's organization ownership.
Strictly immutable.

Endpoints:
- GET /api/v1/verification-results (Protected, Viewer+: list verification results with pagination, filter, search, sort)
- POST /api/v1/verification-results (Protected, RiskManager+: record observational verification result)
- GET /api/v1/verification-results/{id} (Protected, Viewer+: get single verification result by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.agents.verification import (
    VerificationActionNotExecutedError,
    VerificationActionNotFoundError,
    VerificationAgent,
    VerificationApprovalMismatchError,
    VerificationCommand,
    VerificationEvidenceConflictError,
    VerificationObservationWindowExpiredError,
    VerificationResultPayload,
    VerificationSecurityViolationError,
    VerificationTenantIsolationError,
)
from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.governance_repositories import VERIFICATION_RESULT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.governance import (
    VerificationResultCreate,
    VerificationResultListResponse,
    VerificationResultResponse,
)
from app.services.governance_services import VerificationResultService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_verification_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> VerificationResultService:
    """Dependency injecting configured VerificationResultService."""
    return VerificationResultService(uow=uow, context=context)


@router.get(
    "",
    response_model=VerificationResultListResponse,
    status_code=status.HTTP_200_OK,
    summary="List verification results",
    description="Retrieve a paginated list of observational verification results for tenant actions.",
)
def list_verification_results(
    request: Request,
    params: PaginationParams = Depends(),
    action_id: Optional[str] = Query(None, description="Filter by parent action ID"),
    verified: Optional[bool] = Query(None, description="Filter by verified boolean status"),
    search: Optional[str] = Query(None, description="Substring search across observation summary"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. verified_at, -verified_at, risk_score_after)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: VerificationResultService = Depends(get_verification_service),
) -> VerificationResultListResponse:
    """List verification results with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in VERIFICATION_RESULT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(VERIFICATION_RESULT_FILTER_ALLOWLIST.keys()))

    return service.list_verification_results(
        params=params,
        action_id=action_id,
        verified=verified,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=VerificationResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create verification result",
    description="Record an immutable post-action verification result. Requires RiskManager role or higher.",
)
def create_verification_result(
    body: VerificationResultCreate,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    service: VerificationResultService = Depends(get_verification_service),
) -> VerificationResultResponse:
    """Record an observational verification result for an action."""
    return service.create_verification_result(body)


@router.post(
    "/verify",
    response_model=VerificationResultPayload,
    status_code=status.HTTP_200_OK,
    summary="Verify action outcome",
    description="Deterministically verify post-action operational outcome against authoritative evidence. Requires RiskManager role or higher.",
)
def verify_action_outcome(
    body: VerificationCommand,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> VerificationResultPayload:
    """Run deterministic outcome verification for an executed action."""
    org_id = context.organization_id
    if body.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cross-tenant verification request: payload tenant '{body.organization_id}' does not match authenticated tenant '{org_id}'.",
        )

    try:
        agent = VerificationAgent(db=uow.session)
        result = agent.execute_verification(command=body)
        return result
    except VerificationActionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except VerificationTenantIsolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except VerificationActionNotExecutedError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (VerificationApprovalMismatchError, VerificationEvidenceConflictError) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (VerificationObservationWindowExpiredError, VerificationSecurityViolationError) as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))



@router.get(
    "/{id}",
    response_model=VerificationResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Get verification result by ID",
    description="Retrieve an individual verification result by ID ensuring parent action belongs to tenant.",
)
def get_verification_result(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: VerificationResultService = Depends(get_verification_service),
) -> VerificationResultResponse:
    """Retrieve a single verification result enforcing tenant isolation."""
    return service.get_verification_result(id)
