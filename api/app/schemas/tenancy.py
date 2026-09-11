"""Pydantic schemas for multi-tenant organizations and users."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import PaginatedResponse


class UserRole(str, Enum):
    VIEWER = "Viewer"
    ANALYST = "Analyst"
    OPS_MANAGER = "OpsManager"
    RISK_MANAGER = "RiskManager"
    ADMIN = "Admin"


class OrgPlan(str, Enum):
    STARTER = "STARTER"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


# Organization Schemas
class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=255)
    settings_json: Optional[dict[str, Any]] = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: Optional[str] = None
    plan: OrgPlan
    settings_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


# User Schemas
class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=255)
    role: UserRole = Field(default=UserRole.ANALYST)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(None, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    email: str
    full_name: Optional[str] = None
    role: str
    sso_provider: Optional[str] = None
    is_active: bool
    last_active_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class UserListResponse(PaginatedResponse[UserResponse]):
    pass
