from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.security import validate_password_strength


class OrganizationSummary(BaseModel):
    """Brief organization profile embedded in current user responses."""

    id: str
    name: str
    slug: Optional[str] = None
    plan: str
    is_active: bool


class OrganizationMembershipSummary(BaseModel):
    """Authorized organization membership summary for multi-organization users."""

    org_id: str
    organization_name: str
    organization_slug: Optional[str] = None
    role: str
    is_active: bool


class UserMeResponse(BaseModel):
    """Profile payload returned by GET /api/v1/auth/me."""

    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    org_id: Optional[str] = None
    organization_id: Optional[str] = None
    organization: Optional[OrganizationSummary] = None
    organizations: list[OrganizationMembershipSummary] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_organization_id(self) -> UserMeResponse:
        if not self.organization_id and self.org_id:
            self.organization_id = self.org_id
        elif not self.org_id and self.organization_id:
            self.org_id = self.organization_id
        return self


class LogoutResponse(BaseModel):
    """Response payload returned by POST /api/v1/auth/logout."""

    status: str = "ok"
    message: str = "Successfully logged out"


class GoogleAuthUrlResponse(BaseModel):
    """Response payload returned when querying Google OAuth redirect URL."""

    authorization_url: str
    state: str


# ==========================================
# COMPANY REGISTRATION & LOGIN SCHEMAS
# ==========================================

class CompanyRegisterRequest(BaseModel):
    """Payload for organization creation and company owner registration."""

    full_name: str = Field(..., min_length=2, max_length=100, description="Full name of registering administrator")
    company_name: str = Field(..., min_length=2, max_length=100, description="Enterprise company name")
    email: EmailStr = Field(..., description="Corporate work email address")
    password: str = Field(..., min_length=8, max_length=128, description="Strong account password")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Password confirmation")
    terms_accepted: bool = Field(..., description="Explicit acknowledgement of Terms of Service and Privacy Policy")

    @field_validator("full_name", "company_name")
    @classmethod
    def strip_and_clean(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Field must contain at least 2 non-whitespace characters")
        return cleaned

    @model_validator(mode="after")
    def validate_registration(self) -> CompanyRegisterRequest:
        if not self.terms_accepted:
            raise ValueError("Terms of Service and Privacy Policy must be accepted")
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        is_strong, msg = validate_password_strength(self.password)
        if not is_strong:
            raise ValueError(msg)
        return self


class LoginRequest(BaseModel):
    """Credentials payload for email and password authentication."""

    email: EmailStr = Field(..., description="Registered work email address")
    password: str = Field(..., min_length=1, max_length=128, description="Account password")


class ForgotPasswordRequest(BaseModel):
    """Request payload to initiate a secure password reset email."""

    email: EmailStr = Field(..., description="Account email address")


class ForgotPasswordResponse(BaseModel):
    """Safe response for password reset requests preventing user enumeration."""

    status: str = "ok"
    message: str = "If that email address is registered, password reset instructions have been sent."


class ResetPasswordRequest(BaseModel):
    """Payload to complete password recovery using a single-use token."""

    token: str = Field(..., min_length=10, max_length=128, description="Password reset verification token")
    new_password: str = Field(..., min_length=8, max_length=128, description="New strong password")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Confirm new password")

    @model_validator(mode="after")
    def validate_passwords(self) -> ResetPasswordRequest:
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        is_strong, msg = validate_password_strength(self.new_password)
        if not is_strong:
            raise ValueError(msg)
        return self


class ResetPasswordResponse(BaseModel):
    """Confirmation payload after successful password change."""

    status: str = "ok"
    message: str = "Password has been successfully updated. You may now sign in."


# ==========================================
# EMPLOYEE INVITATION SCHEMAS
# ==========================================

VALID_INVITATION_ROLES = {"VIEWER", "ANALYST", "OPSMANAGER", "RISKMANAGER", "ADMIN"}


class InviteEmployeeRequest(BaseModel):
    """Payload sent by administrators to invite an employee into their organization."""

    email: EmailStr = Field(..., description="Work email of the invited employee")
    role: str = Field(default="ANALYST", description="Granted role: VIEWER, ANALYST, OPSMANAGER, RISKMANAGER, ADMIN")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in VALID_INVITATION_ROLES:
            valid_str = ", ".join(sorted(VALID_INVITATION_ROLES))
            raise ValueError(f"Invalid role '{value}'. Must be one of: {valid_str}")
        return normalized


class InvitationResponse(BaseModel):
    """Detailed employee invitation record."""

    id: str
    email: str
    role: str
    status: str
    org_id: str
    organization_name: Optional[str] = None
    expires_at: datetime
    invitation_link: Optional[str] = None
    created_at: datetime


class InvitationDetailsResponse(BaseModel):
    """Public invitation summary displayed on the invitation acceptance page."""

    email: str
    role: str
    organization_name: str
    organization_slug: Optional[str] = None
    expires_at: datetime


class AcceptInvitationRequest(BaseModel):
    """Payload submitted by an invited employee to activate their account and join the tenant."""

    full_name: str = Field(..., min_length=2, max_length=100, description="Full name of employee")
    password: str = Field(..., min_length=8, max_length=128, description="Account password")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Password confirmation")

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Full name must contain at least 2 characters")
        return cleaned

    @model_validator(mode="after")
    def validate_submission(self) -> AcceptInvitationRequest:
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        is_strong, msg = validate_password_strength(self.password)
        if not is_strong:
            raise ValueError(msg)
        return self


class SwitchOrgRequest(BaseModel):
    """Request payload to switch active organization context."""

    org_id: str = Field(..., description="Target authorized organization ID to switch into")


class SwitchOrgResponse(BaseModel):
    """Response payload when active organization has switched successfully."""

    status: str = "ok"
    active_organization_id: str
    role: str
    user: UserMeResponse

