"""SQLAlchemy models for governance, recommendations, approvals, actions, verification, audit trails, and notifications."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Recommendation(Base):
    """AI-generated or analyst mitigation proposal for an active incident."""
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    incident_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_benefit_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    approvals: Mapped[list["Approval"]] = relationship(
        "Approval", back_populates="recommendation", cascade="all, delete-orphan"
    )


class Approval(Base):
    """Human-in-the-loop sign-off on a mitigation recommendation."""
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    recommendation_id: Mapped[str] = mapped_column(String(64), ForeignKey("recommendations.id"), nullable=False)
    decided_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("users.id"), nullable=True)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    comments: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    recommendation: Mapped["Recommendation"] = relationship("Recommendation", back_populates="approvals")


class Action(Base):
    """Executed mitigation action altering supply chain operations."""
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    recommendation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_entity_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="EXECUTING")
    execution_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    verification: Mapped[Optional["VerificationResult"]] = relationship(
        "VerificationResult", back_populates="action", uselist=False
    )


class VerificationResult(Base):
    """Post-action observational verification comparing risk before and after."""
    __tablename__ = "verification_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    action_id: Mapped[str] = mapped_column(String(64), ForeignKey("actions.id"), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score_before: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_score_after: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observation_summary: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    action: Mapped["Action"] = relationship("Action", back_populates="verification")


class AuditLog(Base):
    """Immutable audit trail of all security and domain modifications."""
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(50), default="USER")
    actor_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="SUCCESS")
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    before_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    """User notifications and alerts."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("users.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="RISK_ALERT")
    severity: Mapped[str] = mapped_column(String(50), default="INFO")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
