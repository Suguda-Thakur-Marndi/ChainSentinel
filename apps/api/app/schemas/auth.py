"""Pydantic schemas for authentication contracts (Phase 3 Step 4)."""
from typing import Optional
from pydantic import BaseModel, Field


class OrganizationSummary(BaseModel):
    """Brief organization profile embedded in current user responses."""

    id: str
    name: str
    slug: Optional[str] = None
    plan: str
    is_active: bool


class UserMeResponse(BaseModel):
    """Profile payload returned by GET /api/v1/auth/me."""

    id: str
    email: str
    full_name: Optional[str] = None
    role: str
    org_id: Optional[str] = None
    organization: Optional[OrganizationSummary] = None
    permissions: list[str] = Field(default_factory=list)


class LogoutResponse(BaseModel):
    """Response payload returned by POST /api/v1/auth/logout."""

    status: str = "ok"
    message: str = "Successfully logged out"


class GoogleAuthUrlResponse(BaseModel):
    """Response payload returned when querying Google OAuth redirect URL."""

    authorization_url: str
    state: str
