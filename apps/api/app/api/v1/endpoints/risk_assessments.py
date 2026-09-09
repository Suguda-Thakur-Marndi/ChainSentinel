"""Risk Assessments API endpoints for RiskWise 2.0 (Phase 4 Step 6).

Evaluation run analyzing a risk by AI agents or human analysts.
Organization-scoped, linked to risk_id. Immutable evaluation record.

Endpoints:
- GET /api/v1/risk-assessments (Protected, Viewer+: list assessments with pagination, filter, search, sort)
- POST /api/v1/risk-assessments (Protected, Analyst+: record new evaluation assessment)
- GET /api/v1/risk-assessments/{id} (Protected, Viewer+: get single evaluation assessment by ID)
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError, NotFoundError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.risk_repositories import RISK_ASSESSMENT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.risk import (
    AssessmentComparisonResponse,
    RiskAssessmentCreate,
    RiskAssessmentDetailResponse,
    RiskAssessmentListResponse,
    RiskAssessmentResponse,
    RiskEvaluationRequest,
    RiskHistorySummaryResponse,
)
from app.services.risk_evaluation_service import RiskEvaluationService
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


def get_risk_evaluation_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RiskEvaluationService:
    """Dependency injecting configured RiskEvaluationService."""
    return RiskEvaluationService(uow=uow, context=context)


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
    assessor_type: Optional[str] = Query(None, description="Filter by assessor type (AI_AGENT, HUMAN_ANALYST, DETERMINISTIC_ENGINE)"),
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


@router.post(
    "/evaluate",
    response_model=RiskAssessmentDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate risk with deterministic engine",
    description="Execute the deterministic Phase 7 Risk Engine on normalized risk signals and transactionally persist the assessment. Requires Analyst role or higher.",
    include_in_schema=False,
)
def evaluate_risk(
    body: RiskEvaluationRequest,
    response: Response,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskEvaluationService = Depends(get_risk_evaluation_service),
) -> RiskAssessmentDetailResponse:
    """Evaluate and persist deterministic risk assessment."""
    _, detail_dict, is_idempotent = service.evaluate_and_persist(
        signals=body.signals,
        scope=body.scope,
        scope_entity_id=body.scope_entity_id,
        scope_entity_type=body.scope_entity_type,
        risk_id=body.risk_id,
        metadata=body.metadata,
    )
    if is_idempotent:
        response.status_code = status.HTTP_200_OK
    return RiskAssessmentDetailResponse.model_validate(detail_dict)


@router.get(
    "/latest",
    response_model=RiskAssessmentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest risk assessment",
    description="Retrieve the most recent risk assessment evaluation record within the tenant boundary.",
    include_in_schema=False,
)
def get_latest_risk_assessment(
    scope: Optional[str] = Query(None, description="Filter by evaluation scope (GLOBAL, SHIPMENT, etc.)"),
    scope_entity_id: Optional[str] = Query(None, description="Filter by scope entity ID"),
    risk_id: Optional[str] = Query(None, description="Filter by evaluated risk ID"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskEvaluationService = Depends(get_risk_evaluation_service),
) -> RiskAssessmentDetailResponse:
    """Retrieve the latest risk assessment for the tenant partition."""
    latest = service.get_latest_assessment(
        scope=scope,
        scope_entity_id=scope_entity_id,
        risk_id=risk_id,
    )
    if not latest:
        raise NotFoundError(
            message="No risk assessments found matching criteria for this organization.",
            code="ASSESSMENT_NOT_FOUND",
        )
    return RiskAssessmentDetailResponse.model_validate(latest)


@router.get(
    "/{id}/detail",
    response_model=RiskAssessmentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full risk assessment details",
    description="Retrieve complete RiskAssessment detail with factor contributions, evidence traces, and source summary.",
    include_in_schema=False,
)
def get_risk_assessment_detail(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskEvaluationService = Depends(get_risk_evaluation_service),
) -> RiskAssessmentDetailResponse:
    """Retrieve full detail representation for a risk assessment."""
    detail = service.get_assessment_detail(id)
    return RiskAssessmentDetailResponse.model_validate(detail)


@router.get(
    "/history",
    response_model=RiskHistorySummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get risk assessment history and trend summary",
    description="Retrieve chronological assessment history and deterministic trend analysis within tenant boundary.",
    include_in_schema=False,
)
def get_risk_assessment_history(
    scope: Optional[str] = Query(None, description="Optional evaluation scope (GLOBAL, SHIPMENT, SUPPLIER, PORT, ROUTE)"),
    scope_entity_id: Optional[str] = Query(None, description="Target entity ID"),
    risk_id: Optional[str] = Query(None, description="Optional parent risk ID"),
    start_time: Optional[datetime] = Query(None, description="Filter evaluations on or after timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter evaluations on or before timestamp"),
    limit: int = Query(50, ge=1, le=100, description="Maximum history items to retrieve (1-100)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskEvaluationService = Depends(get_risk_evaluation_service),
) -> RiskHistorySummaryResponse:
    """Retrieve deterministic historical risk summary and trends for an entity or scope."""
    history_summary = service.get_history(
        scope=scope,
        scope_entity_id=scope_entity_id,
        risk_id=risk_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return RiskHistorySummaryResponse.model_validate(history_summary.model_dump())


@router.get(
    "/{id}/compare/{other_id}",
    response_model=AssessmentComparisonResponse,
    status_code=status.HTTP_200_OK,
    summary="Compare two risk assessments",
    description="Perform deterministic comparative analysis between two assessments within tenant boundary.",
    include_in_schema=False,
)
def compare_risk_assessments(
    id: str,
    other_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskEvaluationService = Depends(get_risk_evaluation_service),
) -> AssessmentComparisonResponse:
    """Compare two risk assessments deterministically."""
    comparison = service.compare_assessments(
        assessment_id_1=id,
        assessment_id_2=other_id,
    )
    return AssessmentComparisonResponse.model_validate(comparison.model_dump())


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
