"""Audit Logs API endpoints for RiskWise 2.0 (Phase 4 Step 7).

Immutable compliance audit trail of security, configuration, and data mutations.
Organization-scoped. Strictly read-only query interface.

Endpoints:
- GET /api/v1/audit-logs (Protected, Admin/RiskManager: list audit log entries with pagination, filter, sort)
- GET /api/v1/audit-logs/{id} (Protected, Admin/RiskManager: get single audit log entry by ID)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.audit_log import AUDIT_LOG_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.governance import (
    AuditLogListResponse,
    AuditLogResponse,
)
from app.services.governance_services import AuditLogQueryService

router = APIRouter()

AUDIT_ROLES = ("RiskManager", "Admin")
KNOWN_QUERY_PARAMS = {"page", "limit", "sort"}


def get_audit_log_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> AuditLogQueryService:
    """Dependency injecting configured AuditLogQueryService."""
    return AuditLogQueryService(uow=uow, context=context)


@router.get(
    "",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List audit logs",
    description="Retrieve a paginated compliance audit trail for the tenant organization. Requires Admin or RiskManager role.",
)
def list_audit_logs(
    request: Request,
    params: PaginationParams = Depends(),
    actor_type: Optional[str] = Query(None, description="Filter by actor type (USER, SYSTEM, AGENT)"),
    action: Optional[str] = Query(None, description="Filter by mutation action (CREATE, UPDATE, DELETE, etc.)"),
    resource_type: Optional[str] = Query(None, description="Filter by target resource entity type"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by audit status (SUCCESS, FAILED)"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. timestamp, -timestamp, action, resource_type)"),
    context: AuthenticatedContext = Depends(require_role(*AUDIT_ROLES)),
    service: AuditLogQueryService = Depends(get_audit_log_service),
) -> AuditLogListResponse:
    """List audit log entries with pagination, safe filters, and sorting."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in AUDIT_LOG_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(AUDIT_LOG_FILTER_ALLOWLIST.keys()))

    return service.list_audit_logs(
        params=params,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        status=status_filter,
        sort_param=sort,
    )


@router.get(
    "/{id}",
    response_model=AuditLogResponse,
    status_code=status.HTTP_200_OK,
    summary="Get audit log by ID",
    description="Retrieve an individual compliance audit log entry by ID with 404 masking. Requires Admin or RiskManager role.",
)
def get_audit_log(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*AUDIT_ROLES)),
    service: AuditLogQueryService = Depends(get_audit_log_service),
) -> AuditLogResponse:
    """Retrieve a single audit log entry enforcing tenant isolation."""
    return service.get_audit_log(id)
