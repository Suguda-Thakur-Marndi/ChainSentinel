"""Risk Factors API endpoints for RiskWise 2.0 (Phase 4 Step 6).

Causal drivers contributing to a composite risk score.
Child entity scoped via parent risk_id (risk.org_id).

Endpoints:
- GET /api/v1/risk-factors (Protected, Viewer+: list risk factors with pagination, filter, search, sort)
- POST /api/v1/risk-factors (Protected, Analyst+: create risk factor under tenant risk)
- GET /api/v1/risk-factors/{id} (Protected, Viewer+: get single risk factor by ID)
- PATCH /api/v1/risk-factors/{id} (Protected, Analyst+: update risk factor attributes)
- DELETE /api/v1/risk-factors/{id} (Protected, Analyst+: delete obsolete risk factor)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.risk_repositories import RISK_FACTOR_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.risk import (
    RiskFactorCreate,
    RiskFactorListResponse,
    RiskFactorResponse,
    RiskFactorUpdate,
)
from app.services.risk_services import RiskFactorService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
MUTATION_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_risk_factor_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> RiskFactorService:
    """Dependency injecting configured RiskFactorService."""
    return RiskFactorService(uow=uow, context=context)


@router.get(
    "",
    response_model=RiskFactorListResponse,
    status_code=status.HTTP_200_OK,
    summary="List risk factors",
    description="Retrieve a paginated list of risk factors for tenant-owned risks.",
)
def list_risk_factors(
    request: Request,
    params: PaginationParams = Depends(),
    risk_id: Optional[str] = Query(None, description="Filter by parent risk ID"),
    category: Optional[str] = Query(None, description="Filter by factor category"),
    search: Optional[str] = Query(None, description="Substring search across factor name and category"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. score, -score, weight, -weight, created_at, -created_at)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskFactorService = Depends(get_risk_factor_service),
) -> RiskFactorListResponse:
    """List risk factors with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in RISK_FACTOR_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(RISK_FACTOR_FILTER_ALLOWLIST.keys()))

    return service.list_factors(
        params=params,
        risk_id=risk_id,
        category=category,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=RiskFactorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create risk factor",
    description="Create a new causal factor linked to a tenant-owned risk. Requires Analyst role or higher.",
)
def create_risk_factor(
    body: RiskFactorCreate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskFactorService = Depends(get_risk_factor_service),
) -> RiskFactorResponse:
    """Create a new risk factor record."""
    return service.create_factor(body)


@router.get(
    "/{id}",
    response_model=RiskFactorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get risk factor by ID",
    description="Retrieve an individual risk factor by ID ensuring parent risk belongs to the tenant.",
)
def get_risk_factor(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: RiskFactorService = Depends(get_risk_factor_service),
) -> RiskFactorResponse:
    """Retrieve a single risk factor enforcing parent risk tenant isolation."""
    return service.get_factor(id)


@router.patch(
    "/{id}",
    response_model=RiskFactorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update risk factor",
    description="Update an existing risk factor's details. Requires Analyst role or higher.",
)
def update_risk_factor(
    id: str,
    body: RiskFactorUpdate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskFactorService = Depends(get_risk_factor_service),
) -> RiskFactorResponse:
    """Update an existing risk factor."""
    return service.update_factor(id, body)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete risk factor",
    description="Delete an obsolete causal risk factor from a tenant risk. Requires Analyst role or higher.",
)
def delete_risk_factor(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: RiskFactorService = Depends(get_risk_factor_service),
) -> None:
    """Delete an obsolete risk factor."""
    service.delete_factor(id)
