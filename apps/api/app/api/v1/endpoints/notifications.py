"""Notifications API endpoints for RiskWise 2.0 (Phase 4 Step 7).

User and team alerts regarding risks, disruptions, and approvals.
Organization-scoped, filtered by recipient user_id.

Endpoints:
- GET /api/v1/notifications (Protected, Viewer+: list notifications with pagination, filter, search, sort)
- POST /api/v1/notifications (Protected, Admin: record notification/alert)
- GET /api/v1/notifications/{id} (Protected, Viewer+: get single notification by ID)
- PATCH /api/v1/notifications/{id} (Protected, Viewer+: mark notification as read)
- POST /api/v1/notifications/mark-all-read (Protected, Viewer+: batch mark all notifications as read)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.errors import InvalidFilterFieldError
from app.db.unit_of_work import UnitOfWork, get_uow
from app.repositories.governance_repositories import NOTIFICATION_FILTER_ALLOWLIST
from app.schemas.common import PaginationParams
from app.schemas.governance import (
    BatchNotificationReadResponse,
    NotificationCreate,
    NotificationListResponse,
    NotificationResponse,
    NotificationUpdate,
)
from app.services.governance_services import NotificationService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
ADMIN_ROLES = ("Admin",)
KNOWN_QUERY_PARAMS = {"page", "limit", "search", "sort"}


def get_notification_service(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
) -> NotificationService:
    """Dependency injecting configured NotificationService."""
    return NotificationService(uow=uow, context=context)


@router.get(
    "",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List notifications",
    description="Retrieve a paginated list of alerts and notifications for the authenticated user.",
)
def list_notifications(
    request: Request,
    params: PaginationParams = Depends(),
    category: Optional[str] = Query(None, description="Filter by category (RISK_ALERT, SHIPMENT_DELAY, RECOMMENDATION, SYSTEM)"),
    severity: Optional[str] = Query(None, description="Filter by severity (INFO, WARNING, CRITICAL)"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    search: Optional[str] = Query(None, description="Substring search across title, summary, category"),
    sort: Optional[str] = Query(None, description="Sort expression (e.g. created_at, -created_at, severity)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    """List notifications with pagination, safe filters, sorting, and search."""
    for param_key in request.query_params.keys():
        if param_key not in KNOWN_QUERY_PARAMS and param_key not in NOTIFICATION_FILTER_ALLOWLIST:
            raise InvalidFilterFieldError(param_key, list(NOTIFICATION_FILTER_ALLOWLIST.keys()))

    return service.list_notifications(
        params=params,
        category=category,
        severity=severity,
        is_read=is_read,
        search=search,
        sort_param=sort,
    )


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create notification",
    description="Create an alert or notification record within the organization. Requires Admin role.",
)
def create_notification(
    body: NotificationCreate,
    context: AuthenticatedContext = Depends(require_role(*ADMIN_ROLES)),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    """Create a new notification entry."""
    return service.create_notification(body)


@router.get(
    "/{id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get notification by ID",
    description="Retrieve an individual notification record by ID with 404 masking.",
)
def get_notification(
    id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    """Retrieve a single notification record enforcing tenant and recipient scoping."""
    return service.get_notification(id)


@router.patch(
    "/{id}",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update notification read status",
    description="Mark a notification as read or unread.",
)
def update_notification(
    id: str,
    body: NotificationUpdate,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationResponse:
    """Mark a notification as read."""
    return service.mark_as_read(id, is_read=body.is_read)


@router.post(
    "/mark-all-read",
    response_model=BatchNotificationReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark all notifications read",
    description="Mark all unread notifications for the authenticated user as read.",
)
def mark_all_notifications_read(
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    service: NotificationService = Depends(get_notification_service),
) -> BatchNotificationReadResponse:
    """Mark all unread notifications for the user as read."""
    return service.mark_all_as_read()
