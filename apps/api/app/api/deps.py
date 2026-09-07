"""Reusable FastAPI dependencies for authentication, tenancy, and authorization (Phase 3 Step 4)."""
from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.context import AuthenticatedContext
from app.db.session import get_db
from app.models.tenancy import Organization, User
from app.schemas.session import SessionData
from app.services.session_service import SessionService, get_session_service


def get_session_data(
    request: Request,
    session_service: SessionService = Depends(get_session_service),
) -> SessionData:
    """Read and validate the session cookie from the incoming request.

    Raises:
        HTTPException(401): If the cookie is absent, expired, or invalid.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    session_data = session_service.get_session(session_id)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    return session_data


def get_authenticated_context(
    request: Request,
    session_data: SessionData = Depends(get_session_data),
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> AuthenticatedContext:
    """Resolve full authenticated context: user, active status, organization boundary, and role.

    Raises:
        HTTPException(401): If user does not exist or has been deactivated.
        HTTPException(403): If the user's organization has been suspended.
    """
    user = db.get(User, session_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        # Revoke the invalid session immediately
        session_service.delete_session(session_data.session_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account has been deactivated",
        )

    organization: Optional[Organization] = None
    if user.org_id:
        organization = user.organization or db.get(Organization, user.org_id)
        if organization and not organization.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive",
            )

    return AuthenticatedContext(
        user=user,
        session_data=session_data,
        organization=organization,
    )


def get_current_user(
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> User:
    """FastAPI dependency returning the currently authenticated User entity."""
    return context.user


def get_current_active_user(
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> User:
    """FastAPI dependency returning the currently active User entity."""
    return context.user


def get_current_organization(
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> Organization:
    """FastAPI dependency returning the current User's Organization boundary.

    Raises:
        HTTPException(403): If user has no active organization assignment.
    """
    if not context.organization:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to an organization",
        )
    return context.organization


def require_role(*allowed_roles: str):
    """Dependency factory enforcing that the user has at least one of the specified roles.

    Behavior:
        Unauthenticated: 401 Unauthorized (enforced via get_authenticated_context)
        Insufficient Role: 403 Forbidden
    """
    normalized_allowed = {r.strip().upper() for r in allowed_roles}

    def role_checker(
        context: AuthenticatedContext = Depends(get_authenticated_context),
    ) -> AuthenticatedContext:
        user_role = context.role.strip().upper() if context.role else ""
        if user_role not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return context

    return role_checker


def verify_tenant_access(
    record_org_id: Optional[str],
    context: AuthenticatedContext,
) -> None:
    """Enforce strict multi-tenant boundary isolation on individual records.

    Raises:
        HTTPException(403): If the record belongs to another organization.
    """
    if not context.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not assigned to an organization",
        )
    if record_org_id != context.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization boundary mismatch",
        )
