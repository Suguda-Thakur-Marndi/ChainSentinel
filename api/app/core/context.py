"""Execution and authentication context definitions for RiskWise."""
from typing import Optional
from app.models.tenancy import Organization, User
from app.schemas.session import SessionData


class AuthenticatedContext:
    """Consistent authenticated request context encapsulating user, tenancy, and role."""

    def __init__(
        self,
        user: User,
        session_data: SessionData,
        organization: Optional[Organization] = None,
        organization_id: Optional[str] = None,
        role: Optional[str] = None,
    ):
        self.user = user
        self.session_data = session_data
        self.user_id: str = user.id
        self.organization: Optional[Organization] = organization
        self.organization_id: Optional[str] = (
            organization_id
            if organization_id is not None
            else (organization.id if organization else user.org_id)
        )
        self.role: str = role if role is not None else (user.role or "ANALYST")

    @property
    def org_id(self) -> Optional[str]:
        return self.organization_id

