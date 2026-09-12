"""Authentication API endpoints for RiskWise 2.0 (Phase 3 Step 4).

Endpoints:
- GET /api/v1/auth/me (Protected: returns authenticated user profile & organization)
- POST /api/v1/auth/logout (Authenticated/Session: revokes server session & clears cookie)
- GET /api/v1/auth/google (Public: initiates Google OAuth redirect)
- GET /api/v1/auth/google/callback (Public: handles Google OAuth callback)
"""
import secrets
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from sqlalchemy.orm import Session
from app.api.deps import AuthenticatedContext, get_authenticated_context
from app.core.config import settings
from app.db.session import get_db
from app.schemas.auth import LogoutResponse, OrganizationSummary, UserMeResponse
from app.services.oauth_service import OAuthService, OAuthValidationError, get_oauth_service
from app.services.session_service import SessionService, clear_session_cookie, get_session_service

router = APIRouter()

# Canonical RBAC permissions mapped from docs/google-authentication-architecture.md §12.2
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "VIEWER": ["views:read", "risks:read", "shipments:read"],
    "ANALYST": [
        "views:read", "risks:read", "shipments:read",
        "scenarios:run", "recommendations:write", "agents:trigger",
    ],
    "OPSMANAGER": [
        "views:read", "risks:read", "shipments:read",
        "scenarios:run", "recommendations:write", "agents:trigger",
        "actions:execute",
    ],
    "RISKMANAGER": [
        "views:read", "risks:read", "shipments:read",
        "scenarios:run", "recommendations:write", "agents:trigger",
        "actions:execute", "mitigations:approve", "audit:read",
    ],
    "ADMIN": [
        "views:read", "risks:read", "shipments:read",
        "scenarios:run", "recommendations:write", "agents:trigger",
        "actions:execute", "mitigations:approve", "audit:read",
        "users:manage", "org:manage",
    ],
}


def get_role_permissions(role: str) -> list[str]:
    """Return granted capability strings for a given role name."""
    normalized = role.strip().upper() if role else "VIEWER"
    return ROLE_PERMISSIONS.get(normalized, ROLE_PERMISSIONS["VIEWER"])


@router.get("/me", response_model=UserMeResponse, status_code=status.HTTP_200_OK)
def get_current_user_profile(
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> UserMeResponse:
    """Retrieve profile and organization context for the currently authenticated user.

    Requires a valid HttpOnly session cookie.
    """
    org_summary = None
    if context.organization:
        org_summary = OrganizationSummary(
            id=context.organization.id,
            name=context.organization.name,
            slug=context.organization.slug,
            plan=context.organization.plan,
            is_active=context.organization.is_active,
        )

    return UserMeResponse(
        id=context.user.id,
        email=context.user.email,
        full_name=context.user.full_name,
        role=context.user.role,
        org_id=context.organization_id,
        organization=org_summary,
        permissions=get_role_permissions(context.user.role),
    )


@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
def logout(
    request: Request,
    response: Response,
    session_service: SessionService = Depends(get_session_service),
) -> LogoutResponse:
    """Terminate the application session, revoke server-side state, and clear the session cookie."""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.delete_session(session_id)

    clear_session_cookie(response)
    return LogoutResponse(status="ok", message="Successfully logged out")


import app.models as models


@router.api_route(
    "/demo-login",
    methods=["GET", "POST"],
    status_code=status.HTTP_302_FOUND,
    include_in_schema=False,
)
def demo_login(
    response: Response,
    return_to: str = Query("/", description="Destination path after login"),
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
    oauth_service: OAuthService = Depends(get_oauth_service),
) -> RedirectResponse:
    """Development and demo workspace login: provisions an ADMIN session and sets session cookie."""
    from app.db.session import ensure_tables_exist
    ensure_tables_exist()
    org = db.query(models.Organization).filter_by(slug="acme-global").first()
    if not org:
        org = models.Organization(
            name="Acme Global Logistics",
            slug="acme-global",
            plan="ENTERPRISE",
            is_active=True,
        )
        db.add(org)
        db.commit()
        db.refresh(org)

    user = db.query(models.User).filter_by(email="director@riskwise.internal").first()
    if not user:
        user = models.User(
            email="director@riskwise.internal",
            full_name="RiskWise Mission Director",
            role="ADMIN",
            org_id=org.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    session = session_service.create_session(
        user_id=user.id,
        role=user.role,
        organization_id=org.id,
    )
    safe_return_to = oauth_service.sanitize_return_to(return_to)
    target_url = f"{settings.FRONTEND_URL}{safe_return_to}"
    redirect_resp = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    SessionService.set_session_cookie(redirect_resp, session.session_id)
    SessionService.set_session_cookie(response, session.session_id)
    return redirect_resp


@router.get("/google", status_code=status.HTTP_302_FOUND)
def initiate_google_oauth(
    return_to: str = Query("/", description="Post-login destination path"),
    oauth_service: OAuthService = Depends(get_oauth_service),
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> RedirectResponse:
    """Initiate Google OAuth 2.0 authorization code flow."""
    if not settings.is_google_oauth_configured:
        if settings.APP_ENV == "development":
            return demo_login(
                response=Response(),
                return_to=return_to,
                db=db,
                session_service=session_service,
                oauth_service=oauth_service,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured on this server",
        )

    safe_return_to = oauth_service.sanitize_return_to(return_to)
    state = oauth_service.generate_state(return_to=safe_return_to)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    google_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=google_url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback")
def google_oauth_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    db: Session = Depends(get_db),
    oauth_service: OAuthService = Depends(get_oauth_service),
    session_service: SessionService = Depends(get_session_service),
):
    """Callback receiver for Google OAuth authorization code exchange."""
    # 1. Provider error from Google
    if error:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={error}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    # 2. Verify state token anti-CSRF
    is_valid, safe_return_to, state_err = oauth_service.verify_state(state)
    if not is_valid:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={state_err or 'invalid_state'}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    # 3. Check authorization code
    if not code:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error=missing_code"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    # 4. Exchange code for identity claims
    try:
        claims = oauth_service.exchange_code_for_claims(code)
    except OAuthValidationError as exc:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={exc.error_code}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)
    except Exception:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error=oauth_exchange_failed"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    # 5. User & Organization resolution
    try:
        user, org = oauth_service.resolve_or_create_google_user(db, claims)
    except OAuthValidationError as exc:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={exc.error_code}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    # 6. Mint server-side session
    session = session_service.create_session(
        user_id=user.id,
        role=user.role,
        organization_id=org.id if org else None,
    )

    # 7. Issue session cookie and redirect to safe frontend destination
    target_url = f"{settings.FRONTEND_URL}{safe_return_to}"
    response = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    SessionService.set_session_cookie(response, session.session_id)
    return response
