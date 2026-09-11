"""Pydantic schemas for application session management (Phase 3 Step 4)."""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class SessionData(BaseModel):
    """Internal session payload stored in server-side session cache."""

    session_id: str = Field(..., description="Cryptographically secure unique session token")
    user_id: str = Field(..., description="RiskWise internal user identifier")
    organization_id: Optional[str] = Field(None, description="Active multi-tenant organization boundary")
    role: str = Field(..., description="Assigned RBAC role")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Session creation timestamp",
    )
    expires_at: datetime = Field(..., description="Session expiration timestamp (UTC)")

    @property
    def is_expired(self) -> bool:
        """Check whether the session has passed its expiration timestamp."""
        return datetime.now(timezone.utc) >= self.expires_at
