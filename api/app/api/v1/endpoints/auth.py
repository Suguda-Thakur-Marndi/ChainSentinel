"""Authentication API endpoints for ChainSentinel.

Endpoints:
- GET /api/v1/auth/me (Protected: returns authenticated user profile & organization)
- POST /api/v1/auth/logout (Authenticated/Session: revokes server session & clears cookie)
- POST /api/v1/auth/register-company (Public: company sign up, provisions organization and sets initial owner as ADMIN)
- POST /api/v1/auth/login (Public: email & password login using server sessions)
- POST /api/v1/auth/forgot-password (Public: request password recovery)
- POST /api/v1/auth/reset-password (Public: reset password using single-use token)
- POST /api/v1/auth/invitations (Protected, ADMIN: invite employee to current tenant)
- GET /api/v1/auth/invitations (Protected, ADMIN: list active/pending employee invitations)
- GET /api/v1/auth/invitations/{token} (Public: validate invitation token details)
- POST /api/v1/auth/invitations/{token}/accept (Public: accept employee invitation and join tenant)
- GET /api/v1/auth/demo-login (Development only)
- GET /api/v1/auth/google (Public: initiates Google OAuth redirect)
- GET /api/v1/auth/google/callback (Public: handles Google OAuth callback)
"""
from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.core.config import settings
from app.core.security import generate_secure_token, hash_password, hash_token, verify_password
from app.db.session import get_db
import app.models as models
from app.schemas.auth import (
    AcceptInvitationRequest,
    CompanyRegisterRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    InvitationDetailsResponse,
    InvitationResponse,
    InviteEmployeeRequest,
    LoginRequest,
    LogoutResponse,
    OrganizationMembershipSummary,
    OrganizationSummary,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SwitchOrgRequest,
    SwitchOrgResponse,
    UserMeResponse,
)
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


def _normalize_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware UTC, safe for SQLite and PostgreSQL comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_user_me_response(
    user: models.User,
    organization: Optional[models.Organization],
    db: Optional[Session] = None,
    active_role: Optional[str] = None,
    active_org_id: Optional[str] = None,
) -> UserMeResponse:
    """Helper to format a standardized UserMeResponse including multi-organization memberships."""
    org_summary = None
    if organization:
        org_summary = OrganizationSummary(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            plan=organization.plan,
            is_active=organization.is_active,
        )

    effective_role = active_role or user.role or "ANALYST"
    effective_org_id = active_org_id or (organization.id if organization else user.org_id)

    memberships_list: list[OrganizationMembershipSummary] = []
    if db:
        memberships = (
            db.query(models.OrganizationMembership)
            .join(models.Organization, models.OrganizationMembership.org_id == models.Organization.id)
            .filter(
                models.OrganizationMembership.user_id == user.id,
                models.OrganizationMembership.is_active == True,
                models.Organization.is_active == True,
            )
            .all()
        )
        for m in memberships:
            memberships_list.append(
                OrganizationMembershipSummary(
                    org_id=m.org_id,
                    organization_name=m.organization.name if m.organization else m.org_id,
                    organization_slug=m.organization.slug if m.organization else None,
                    role=m.role,
                    is_active=m.is_active,
                )
            )

        if organization and organization.is_active and not any(m.org_id == organization.id for m in memberships_list):
            memberships_list.append(
                OrganizationMembershipSummary(
                    org_id=organization.id,
                    organization_name=organization.name,
                    organization_slug=organization.slug,
                    role=effective_role,
                    is_active=True,
                )
            )
    elif organization:
        memberships_list.append(
            OrganizationMembershipSummary(
                org_id=organization.id,
                organization_name=organization.name,
                organization_slug=organization.slug,
                role=effective_role,
                is_active=True,
            )
        )

    return UserMeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=effective_role,
        org_id=effective_org_id,
        organization_id=effective_org_id,
        organization=org_summary,
        organizations=memberships_list,
        permissions=get_role_permissions(effective_role),
    )


# ==============================================================================
# CURRENT PROFILE & LOGOUT
# ==============================================================================

@router.get("/me", response_model=UserMeResponse, status_code=status.HTTP_200_OK)
def get_current_user_profile(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> UserMeResponse:
    """Retrieve profile and organization context for the currently authenticated user.

    Requires a valid HttpOnly session cookie.
    """
    return _build_user_me_response(
        context.user,
        context.organization,
        db=db,
        active_role=context.role,
        active_org_id=context.organization_id,
    )


@router.post(
    "/switch-org",
    response_model=SwitchOrgResponse,
    status_code=status.HTTP_200_OK,
    summary="Switch active organization tenant",
)
def switch_organization(
    data: SwitchOrgRequest,
    request: Request,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> SwitchOrgResponse:
    """Switch the authenticated user's active tenant organization context.

    - Verifies caller has an active, valid membership in the requested organization.
    - Ensures the target organization is active.
    - Updates server-side session state and persistent user preference.
    """
    target_org_id = data.org_id.strip()

    # 1. Query membership
    membership = (
        db.query(models.OrganizationMembership)
        .filter(
            models.OrganizationMembership.user_id == context.user.id,
            models.OrganizationMembership.org_id == target_org_id,
            models.OrganizationMembership.is_active == True,
        )
        .first()
    )

    if not membership:
        if context.user.org_id == target_org_id:
            membership = models.OrganizationMembership(
                user_id=context.user.id,
                org_id=target_org_id,
                role=context.user.role or "ANALYST",
                is_active=True,
            )
            db.add(membership)
            db.commit()
            db.refresh(membership)
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: user is not an authorized member of this organization",
            )

    # 2. Check target organization status
    target_org = db.get(models.Organization, target_org_id)
    if not target_org or not target_org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization is inactive or not found",
        )

    # 3. Update server-side session
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.update_session(
            session_id=session_id,
            organization_id=target_org_id,
            role=membership.role,
        )

    # 4. Update user active preference
    context.user.org_id = target_org_id
    context.user.role = membership.role
    db.commit()
    db.refresh(context.user)

    user_me = _build_user_me_response(
        context.user,
        target_org,
        db=db,
        active_role=membership.role,
        active_org_id=target_org_id,
    )

    return SwitchOrgResponse(
        status="ok",
        active_organization_id=target_org_id,
        role=membership.role,
        user=user_me,
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


# ==============================================================================
# COMPANY REGISTRATION & ONBOARDING
# ==============================================================================

@router.post(
    "/register-company",
    response_model=UserMeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new company tenant and owner account",
)
def register_company(
    data: CompanyRegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> UserMeResponse:
    """Company registration flow.

    - Validates company and administrator credentials.
    - Ensures work email uniqueness.
    - Transactionally provisions a new Organization and binds the user with the ADMIN role.
    - Issues a server-side session and sets the HttpOnly session cookie.
    """
    clean_email = data.email.strip().lower()

    # 1. Prevent duplicate registrations
    existing_user = db.query(models.User).filter(models.User.email == clean_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 2. Generate slug for organization boundary
    base_slug = re.sub(r"[^a-zA-Z0-9]+", "-", data.company_name).strip("-").lower()
    base_slug = base_slug[:40] if base_slug else "company"
    slug = base_slug
    suffix = 1
    while db.query(models.Organization).filter(models.Organization.slug == slug).first():
        slug = f"{base_slug}-{secrets.token_hex(2)}"
        suffix += 1
        if suffix > 10:
            slug = f"{base_slug}-{secrets.token_hex(4)}"
            break

    # 3. Transactionally create Organization and Owner User
    try:
        new_org = models.Organization(
            name=data.company_name,
            slug=slug,
            plan="ENTERPRISE",
            settings_json={"onboarding_completed": False},
            is_active=True,
        )
        db.add(new_org)
        db.flush()

        hashed_pw = hash_password(data.password)
        new_user = models.User(
            email=clean_email,
            full_name=data.full_name,
            role="ADMIN",  # Initial registrant is always Organization Owner / Admin
            org_id=new_org.id,
            hashed_password=hashed_pw,
            sso_provider="local",
            is_active=True,
            last_active_at=datetime.now(timezone.utc),
        )
        db.add(new_user)
        db.flush()

        new_membership = models.OrganizationMembership(
            user_id=new_user.id,
            org_id=new_org.id,
            role="ADMIN",
            is_active=True,
        )
        db.add(new_membership)
        db.commit()
        db.refresh(new_user)
        db.refresh(new_org)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create organization: {str(exc)}",
        ) from exc

    # 4. Mint server-side session and set cookie
    session = session_service.create_session(
        user_id=new_user.id,
        role=new_user.role,
        organization_id=new_org.id,
    )
    SessionService.set_session_cookie(response, session.session_id)

    return _build_user_me_response(new_user, new_org, db=db, active_role=new_user.role, active_org_id=new_org.id)


# ==============================================================================
# COMPANY USER LOGIN
# ==============================================================================

@router.post(
    "/login",
    response_model=UserMeResponse,
    status_code=status.HTTP_200_OK,
    summary="Sign in with email and password",
)
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> UserMeResponse:
    """Authenticate an existing company user with email and password."""
    clean_email = data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == clean_email).first()

    # Timing-safe comparison check
    if not user or not user.hashed_password:
        # Perform dummy hash verification to minimize timing attack discrepancy
        verify_password("dummy_password", "pbkdf2_sha256$600000$00$00")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account has been deactivated",
        )

    # Resolve active organization from trusted memberships
    memberships = (
        db.query(models.OrganizationMembership)
        .join(models.Organization, models.OrganizationMembership.org_id == models.Organization.id)
        .filter(
            models.OrganizationMembership.user_id == user.id,
            models.OrganizationMembership.is_active == True,
            models.Organization.is_active == True,
        )
        .all()
    )

    active_org_id = user.org_id
    active_role = user.role or "ANALYST"
    org = user.organization

    if memberships:
        matching_m = next((m for m in memberships if m.org_id == active_org_id), None)
        if not matching_m:
            matching_m = memberships[0]
            active_org_id = matching_m.org_id
            active_role = matching_m.role
        else:
            active_role = matching_m.role
        org = matching_m.organization
    elif user.org_id:
        if not org:
            org = db.query(models.Organization).filter(models.Organization.id == user.org_id).first()
        if org and not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive",
            )
        if org and org.is_active:
            membership = models.OrganizationMembership(
                user_id=user.id,
                org_id=user.org_id,
                role=user.role or "ANALYST",
                is_active=True,
            )
            db.add(membership)
            db.commit()
            db.refresh(membership)
            active_role = membership.role

    # Update last active timestamp and persisted preference
    user.last_active_at = datetime.now(timezone.utc)
    if active_org_id:
        user.org_id = active_org_id
        user.role = active_role
    db.commit()
    db.refresh(user)

    # Mint session
    session = session_service.create_session(
        user_id=user.id,
        role=active_role,
        organization_id=active_org_id,
    )
    SessionService.set_session_cookie(response, session.session_id)

    return _build_user_me_response(
        user,
        org,
        db=db,
        active_role=active_role,
        active_org_id=active_org_id,
    )


# ==============================================================================
# PASSWORD RECOVERY FLOW
# ==============================================================================

@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a password reset email",
)
def forgot_password(
    data: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    """Initiate a password reset flow.

    Returns a generic message regardless of email existence to prevent account enumeration.
    """
    clean_email = data.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == clean_email).first()

    if user and user.is_active:
        # Invalidate any previously unexpired reset tokens for this user
        existing_tokens = db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.user_id == user.id,
            models.PasswordResetToken.is_used == False,
        ).all()
        for tok in existing_tokens:
            tok.is_used = True

        raw_token = generate_secure_token()
        token_digest = hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        reset_record = models.PasswordResetToken(
            user_id=user.id,
            token_hash=token_digest,
            expires_at=expires_at,
            is_used=False,
        )
        db.add(reset_record)
        db.commit()

    return ForgotPasswordResponse(
        status="ok",
        message="If that email address is registered, password reset instructions have been sent.",
    )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password using a single-use token",
)
def reset_password(
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> ResetPasswordResponse:
    """Complete password reset using a cryptographically validated token."""
    token_digest = hash_token(data.token)
    reset_record = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token_hash == token_digest,
    ).first()

    now = datetime.now(timezone.utc)
    if not reset_record or reset_record.is_used or _normalize_utc(reset_record.expires_at) <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    user = db.get(models.User, reset_record.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    # Update password and invalidate token
    user.hashed_password = hash_password(data.new_password)
    reset_record.is_used = True
    reset_record.used_at = now
    db.commit()

    return ResetPasswordResponse(
        status="ok",
        message="Password has been successfully updated. You may now sign in.",
    )


# ==============================================================================
# EMPLOYEE INVITATION SYSTEM
# ==============================================================================

@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite employee to organization",
)
def invite_employee(
    data: InviteEmployeeRequest,
    context: AuthenticatedContext = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> InvitationResponse:
    """Invite an employee to join the authenticated organization with a specific role.

    Requires ADMIN role. Generates an expiring single-use invitation token.
    """
    clean_email = data.email.strip().lower()

    # 1. Check if user already in organization
    existing_member = db.query(models.User).filter(
        models.User.email == clean_email,
        models.User.org_id == context.organization_id,
    ).first()
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email is already a member of this organization",
        )

    # 2. Revoke any pending invitations for the same email in this organization
    prior_invitations = db.query(models.OrganizationInvitation).filter(
        models.OrganizationInvitation.org_id == context.organization_id,
        models.OrganizationInvitation.email == clean_email,
        models.OrganizationInvitation.status == "PENDING",
    ).all()
    for inv in prior_invitations:
        inv.status = "REVOKED"

    # 3. Create high-entropy token and persistent hash
    raw_token = generate_secure_token()
    token_digest = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    invitation = models.OrganizationInvitation(
        org_id=context.organization_id,
        invited_by_user_id=context.user.id,
        email=clean_email,
        role=data.role,
        token_hash=token_digest,
        status="PENDING",
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    invitation_link = f"{settings.FRONTEND_URL}/auth/invite/{raw_token}"
    org_name = context.organization.name if context.organization else "Organization"

    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        org_id=invitation.org_id,
        organization_name=org_name,
        expires_at=invitation.expires_at,
        invitation_link=invitation_link,
        created_at=invitation.created_at,
    )


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    status_code=status.HTTP_200_OK,
    summary="List tenant employee invitations",
)
def list_invitations(
    context: AuthenticatedContext = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> list[InvitationResponse]:
    """List all invitations for the authenticated organization."""
    invitations = db.query(models.OrganizationInvitation).filter(
        models.OrganizationInvitation.org_id == context.organization_id,
    ).order_by(models.OrganizationInvitation.created_at.desc()).all()

    org_name = context.organization.name if context.organization else "Organization"
    return [
        InvitationResponse(
            id=inv.id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            org_id=inv.org_id,
            organization_name=org_name,
            expires_at=inv.expires_at,
            invitation_link=None,  # Raw tokens are never exposed in bulk listings
            created_at=inv.created_at,
        )
        for inv in invitations
    ]


@router.get(
    "/invitations/{token}",
    response_model=InvitationDetailsResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate an invitation token",
)
def get_invitation_details(
    token: str,
    db: Session = Depends(get_db),
) -> InvitationDetailsResponse:
    """Public endpoint to validate an invitation link before account creation."""
    token_digest = hash_token(token)
    invitation = db.query(models.OrganizationInvitation).filter(
        models.OrganizationInvitation.token_hash == token_digest,
    ).first()

    now = datetime.now(timezone.utc)
    if not invitation or invitation.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation is invalid or has already been used",
        )

    if _normalize_utc(invitation.expires_at) <= now:
        invitation.status = "EXPIRED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has expired",
        )

    org = invitation.organization
    return InvitationDetailsResponse(
        email=invitation.email,
        role=invitation.role,
        organization_name=org.name if org else "Organization",
        organization_slug=org.slug if org else None,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/invitations/{token}/accept",
    response_model=UserMeResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept employee invitation",
)
def accept_invitation(
    token: str,
    data: AcceptInvitationRequest,
    response: Response,
    db: Session = Depends(get_db),
    session_service: SessionService = Depends(get_session_service),
) -> UserMeResponse:
    """Accept an employee invitation, initialize password, and join organization."""
    token_digest = hash_token(token)
    invitation = db.query(models.OrganizationInvitation).filter(
        models.OrganizationInvitation.token_hash == token_digest,
    ).first()

    now = datetime.now(timezone.utc)
    if not invitation or invitation.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation is invalid or has already been used",
        )

    if _normalize_utc(invitation.expires_at) <= now:
        invitation.status = "EXPIRED"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation has expired",
        )

    # Check organization status
    org = invitation.organization
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization is inactive or suspended",
        )

    # Single-use transition: mark invitation ACCEPTED
    invitation.status = "ACCEPTED"
    invitation.accepted_at = now

    # Provision user or bind to tenant
    clean_email = invitation.email.strip().lower()
    existing_user = db.query(models.User).filter(models.User.email == clean_email).first()

    hashed_pw = hash_password(data.password)
    if existing_user:
        existing_user.org_id = invitation.org_id
        existing_user.role = invitation.role
        existing_user.full_name = data.full_name
        existing_user.hashed_password = hashed_pw
        existing_user.is_active = True
        existing_user.last_active_at = now
        user = existing_user
    else:
        user = models.User(
            email=clean_email,
            full_name=data.full_name,
            role=invitation.role,
            org_id=invitation.org_id,
            hashed_password=hashed_pw,
            sso_provider="local",
            is_active=True,
            last_active_at=now,
        )
        db.add(user)

    db.flush()

    # Record or update OrganizationMembership
    membership = (
        db.query(models.OrganizationMembership)
        .filter(
            models.OrganizationMembership.user_id == user.id,
            models.OrganizationMembership.org_id == invitation.org_id,
        )
        .first()
    )
    if not membership:
        membership = models.OrganizationMembership(
            user_id=user.id,
            org_id=invitation.org_id,
            role=invitation.role,
            is_active=True,
        )
        db.add(membership)
    else:
        membership.role = invitation.role
        membership.is_active = True

    db.commit()
    db.refresh(user)

    # Mint server session
    session = session_service.create_session(
        user_id=user.id,
        role=user.role,
        organization_id=user.org_id,
    )
    SessionService.set_session_cookie(response, session.session_id)

    return _build_user_me_response(
        user,
        org,
        db=db,
        active_role=user.role,
        active_org_id=user.org_id,
    )


# ==============================================================================
# DEMO & GOOGLE OAUTH
# ==============================================================================

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
    if settings.APP_ENV.lower() not in ("development", "test", "testing"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Endpoint not found",
        )

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

    m = db.query(models.OrganizationMembership).filter_by(user_id=user.id, org_id=org.id).first()
    if not m:
        m = models.OrganizationMembership(
            user_id=user.id,
            org_id=org.id,
            role="ADMIN",
            is_active=True,
        )
        db.add(m)
        db.commit()

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
    if error:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={error}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    is_valid, safe_return_to, state_err = oauth_service.verify_state(state)
    if not is_valid:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={state_err or 'invalid_state'}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    if not code:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error=missing_code"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    try:
        claims = oauth_service.exchange_code_for_claims(code)
    except OAuthValidationError as exc:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={exc.error_code}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)
    except Exception:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error=oauth_exchange_failed"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    try:
        user, org = oauth_service.resolve_or_create_google_user(db, claims)
    except OAuthValidationError as exc:
        frontend_error_url = f"{settings.FRONTEND_URL}/auth?error={exc.error_code}"
        return RedirectResponse(url=frontend_error_url, status_code=status.HTTP_302_FOUND)

    session = session_service.create_session(
        user_id=user.id,
        role=user.role,
        organization_id=org.id if org else None,
    )

    target_url = f"{settings.FRONTEND_URL}{safe_return_to}"
    response = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    SessionService.set_session_cookie(response, session.session_id)
    return response
