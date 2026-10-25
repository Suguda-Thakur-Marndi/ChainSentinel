"""SQLAlchemy models for multi-tenant organizations and users."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Organization(Base):
    """Multi-tenant organization boundary entity."""
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    plan: Mapped[str] = mapped_column(String(50), default="ENTERPRISE")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    users: Mapped[list["User"]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership", back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base):
    """User account entity associated with an organization."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    org_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("organizations.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="ANALYST")
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sso_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="users"
    )
    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        "OrganizationMembership", back_populates="user", cascade="all, delete-orphan"
    )


class OrganizationMembership(Base):
    """Associates a user with an authorized organization tenant and assigned RBAC role."""
    __tablename__ = "organization_memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_user_org_membership"),)

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), default="ANALYST")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="memberships")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="memberships")


class OrganizationInvitation(Base):
    """Pending or accepted employee invitation to join an organization tenant."""
    __tablename__ = "organization_invitations"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    org_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="ANALYST")
    token_hash: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="PENDING")  # PENDING, ACCEPTED, EXPIRED, REVOKED
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    invited_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by_user_id])


class PasswordResetToken(Base):
    """Secure single-use token for account password recovery."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User")

