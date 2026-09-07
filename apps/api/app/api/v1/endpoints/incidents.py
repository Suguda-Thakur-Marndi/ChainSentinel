"""Incidents API endpoints for RiskWise 2.0 (Phase 4 Step 6).

Realized disruptions actively investigated or mitigated.
Organization-scoped.

Endpoints:
- GET /api/v1/incidents (Protected, Viewer+: list incidents with pagination, filter, search, sort)
- POST /api/v1/incidents (Protected, Analyst+: create new incident record)
- GET /api/v1/incidents/{id} (Protected, Viewer+: get single incident by ID with 404 masking)
- PATCH /api/v1/incidents/{id} (Protected, Analyst+: update incident details and lifecycle status)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.risk_repositories import INCIDENT_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.risk import (
    IncidentCreate,
    IncidentListResponse,
    IncidentResponse,
    IncidentUpdate,
)
from app.services.risk_services import IncidentService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
MUTATION_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_incident_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> IncidentService:
    """Dependency injecting configured IncidentService."""
    return IncidentService(uow=uow, context=context)


@router.get(
    "",
    response_model=IncidentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List incidents",
    description="Retrieve a paginated list of operational disruption incidents for the tenant.",
)
def list_incidents(
    request: Request,
    params: PaginationParams = Depends(),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (DETECTED, INVESTIGATING, MITIGATING, RESOLVED, CLOSED)"),
    severity: Optional[str] = Query(None, description="Filter by severity (LOW, MEDIUM, HIGH, CRITICAL)"),
    risk_id: Optional[str] = Query(None, description="Filter by associated risk ID"),
    search: Optional[str] = Query(None, description="Substring search across title, location, source"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. detected_at, -detected_at, severity, -severity, title)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentListResponse:
    """List incidents with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in INCIDENT_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(INCIDENT_FILTER_ALLOWLIST.keys()))

    return service.list_incidents(
        params=params,
        status=status_filter,
        severity=severity,
        risk_id=risk_id,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create incident",
    description="Record a new disruption incident within the tenant partition. Requires Analyst role or higher.",
)
def create_incident(
    body: IncidentCreate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Create a new incident record."""
    return service.create_incident(body)


@router.get(
    "/{id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get incident by ID",
    description="Retrieve an individual incident record by ID with 404 masking.",
)
def get_incident(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Retrieve a single incident record enforcing tenant isolation."""
    return service.get_incident(id)


@router.patch(
    "/{id}",
    response_model=IncidentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update incident",
    description="Update an existing incident's operational details, mitigation progress, or lifecycle status. Requires Analyst role or higher.",
)
def update_incident(
    id: str,
    body: IncidentUpdate,
    context: AuthenticatedContext = Depends(require_role(*MUTATION_ROLES)),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    """Update an existing incident record within the authenticated tenant boundary."""
    return service.update_incident(id, body)
