"""Risk Assessments API endpoints for RiskWise 2.0 (Phase 4 Step 6).

Evaluation run analyzing a risk by AI agents or human analysts.
Organization-scoped, linked to risk_id. Immutable evaluation record.

Endpoints:
- GET /api/v1/risk-assessments (Protected, Viewer+: list assessments with pagination, filter, search, sort)
- POST /api/v1/risk-assessments (Protected, Analyst+: record new evaluation assessment)
- GET /api/v1/risk-assessments/{id} (Protected, Viewer+: get single evaluation assessment by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.risk_repositories import RISK_ASSESSMENT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.risk import (
    RiskAssessmentCreate,
    RiskAssessmentListResponse,
    RiskAssessmentResponse,
)
from app.services.risk_services import RiskAssessmentService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
MUTATION_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_risk_assessment_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RiskAssessmentService:
    """Dependency injecting configured RiskAssessmentService."""
    return RiskAssessmentService(uow=uow, context=context)


@router.get(
    "",
    response_model=RiskAssessmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List risk assessments",
    description="Retrieve a paginated list of risk assessment evaluation records within the tenant partition.",
)
def list_risk_assessments(
    request: Request,
    params: PaginationParams = Depends(),
    risk_id: Optional[str] = Query(None, description="Filter by evaluated risk ID"),
    assessor_type: Optional[str] = Query(None, description="Filter by assessor type (AI_AGENT, HUMAN_ANALYST)"),
    search: Optional[str] = Query(None, description="Substring search across methodology, assessor_type, assessor_id"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. created_at, -created_at, score, -score, confidence, -confidence)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskAssessmentService = Depends(get_risk_assessment_service),
) -> RiskAssessmentListResponse:
    """List risk assessments with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in RISK_ASSESSMENT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(RISK_ASSESSMENT_FILTER_ALLOWLIST.keys()))

    return service.list_assessments(
        params=params,
        risk_id=risk_id,
        assessor_type=assessor_type,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=RiskAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create risk assessment",
    description="Record an immutable risk assessment evaluation snapshot. Requires Analyst role or higher.",
)
def create_risk_assessment(
    body: RiskAssessmentCreate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskAssessmentService = Depends(get_risk_assessment_service),
) -> RiskAssessmentResponse:
    """Record an immutable risk evaluation record."""
    return service.create_assessment(body)


@router.get(
    "/{id}",
    response_model=RiskAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get risk assessment by ID",
    description="Retrieve an individual risk assessment record by ID with 404 masking.",
)
def get_risk_assessment(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskAssessmentService = Depends(get_risk_assessment_service),
) -> RiskAssessmentResponse:
    """Retrieve a single risk assessment record enforcing tenant isolation."""
    return service.get_assessment(id)
