"""Risks API endpoints for RiskWise 2.0 (Phase 4 Step 6).

Identified geopolitical, climatic, supplier, or lane risk entities.
Organization-scoped.

Endpoints:
- GET /api/v1/risks (Protected, Viewer+: list risks with pagination, search, filter, sort)
- POST /api/v1/risks (Protected, Analyst+: create new risk entity)
- GET /api/v1/risks/{id} (Protected, Viewer+: get single risk by ID with 404 masking)
- PATCH /api/v1/risks/{id} (Protected, Analyst+: update risk attributes)
- GET /api/v1/risks/{id}/factors (Protected, Viewer+: list factors linked to risk)
- GET /api/v1/risks/{id}/assessments (Protected, Viewer+: list assessments linked to risk)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.risk_repositories import RISK_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.risk import (
    RiskAssessmentListResponse,
    RiskCreate,
    RiskFactorListResponse,
    RiskListResponse,
    RiskResponse,
    RiskUpdate,
)
from app.services.risk_services import (
    RiskAssessmentService,
    RiskFactorService,
    RiskService,
)

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
MUTATION_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_risk_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RiskService:
    """Dependency injecting configured RiskService."""
    return RiskService(uow=uow, context=context)


def get_risk_factor_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RiskFactorService:
    """Dependency injecting configured RiskFactorService."""
    return RiskFactorService(uow=uow, context=context)


def get_risk_assessment_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RiskAssessmentService:
    """Dependency injecting configured RiskAssessmentService."""
    return RiskAssessmentService(uow=uow, context=context)


@router.get(
    "",
    response_model=RiskListResponse,
    status_code=status.HTTP_200_OK,
    summary="List risks",
    description="Retrieve a paginated list of risk entities within the authenticated organization boundary.",
)
def list_risks(
    request: Request,
    params: PaginationParams = Depends(),
    severity: Optional[str] = Query(None, description="Filter by severity level (LOW, MEDIUM, HIGH, CRITICAL)"),
    trend: Optional[str] = Query(None, description="Filter by trend (INCREASING, DECREASING, STABLE, VOLATILE)"),
    risk_type: Optional[str] = Query(None, description="Filter by risk classification/type"),
    search: Optional[str] = Query(None, description="Substring search across title, location, risk_type, source"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. detected_at, -detected_at, risk_score, -risk_score)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskService = Depends(get_risk_service),
) -> RiskListResponse:
    """List risks with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in RISK_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(RISK_FILTER_ALLOWLIST.keys()))

    return service.list_risks(
        params=params,
        severity=severity,
        trend=trend,
        risk_type=risk_type,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=RiskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create risk",
    description="Create a new risk entity within the tenant partition. Requires Analyst role or higher.",
)
def create_risk(
    body: RiskCreate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskService = Depends(get_risk_service),
) -> RiskResponse:
    """Create a new risk record."""
    return service.create_risk(body)


@router.get(
    "/{id}",
    response_model=RiskResponse,
    status_code=status.HTTP_200_OK,
    summary="Get risk by ID",
    description="Retrieve a single risk entity by ID. Returns 404 if missing or belonging to another organization.",
)
def get_risk(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskService = Depends(get_risk_service),
) -> RiskResponse:
    """Retrieve an individual risk entity enforcing tenant isolation."""
    return service.get_risk(id)


@router.patch(
    "/{id}",
    response_model=RiskResponse,
    status_code=status.HTTP_200_OK,
    summary="Update risk",
    description="Update an existing risk entity's attributes. Requires Analyst role or higher.",
)
def update_risk(
    id: str,
    body: RiskUpdate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskService = Depends(get_risk_service),
) -> RiskResponse:
    """Update an existing risk within the authenticated organization boundary."""
    return service.update_risk(id, body)


@router.get(
    "/{id}/factors",
    response_model=RiskFactorListResponse,
    status_code=status.HTTP_200_OK,
    summary="List factors for risk",
    description="Retrieve all causal factors associated with a given risk owned by the tenant.",
)
def list_factors_for_risk(
    id: str,
    params: PaginationParams = Depends(),
    category: Optional[str] = Query(None, description="Filter by category"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. score, -score, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    factor_service: RiskFactorService = Depends(get_risk_factor_service),
) -> RiskFactorListResponse:
    """Retrieve causal factors linked to a specific risk."""
    return factor_service.list_factors(
        params=params,
        risk_id=id,
        category=category,
        sort_param=sort,
    )


@router.get(
    "/{id}/assessments",
    response_model=RiskAssessmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List assessments for risk",
    description="Retrieve all historical evaluation assessments associated with a given risk owned by the tenant.",
)
def list_assessments_for_risk(
    id: str,
    params: PaginationParams = Depends(),
    assessor_type: Optional[str] = Query(None, description="Filter by assessor type"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    assessment_service: RiskAssessmentService = Depends(get_risk_assessment_service),
) -> RiskAssessmentListResponse:
    """Retrieve evaluation assessments linked to a specific risk."""
    return assessment_service.list_assessments(
        params=params,
        risk_id=id,
        assessor_type=assessor_type,
        sort_param=sort,
    )
