from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, model_validator


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
    organization_id: Optional[str] = None
    organization: Optional[OrganizationSummary] = None
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
