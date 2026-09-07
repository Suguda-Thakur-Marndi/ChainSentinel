"""SQLAlchemy models for risk intelligence, risk factors, assessments, and disruption incidents."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Risk(Base):
    """Identified geopolitical, climatic, supplier, or lane risk."""
    __tablename__ = "risks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    severity: Mapped[str] = mapped_column(String(50), default="MEDIUM")
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    impact: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trend: Mapped[str] = mapped_column(String(50), default="STABLE")
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    factors: Mapped[list["RiskFactor"]] = relationship(
        "RiskFactor", back_populates="risk", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["RiskAssessment"]] = relationship(
        "RiskAssessment", back_populates="risk", cascade="all, delete-orphan"
    )
    incidents: Mapped[list["Incident"]] = relationship("Incident", back_populates="risk")


class RiskFactor(Base):
    """Causal driver contributing to a composite risk score."""
    __tablename__ = "risk_factors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    risk_id: Mapped[str] = mapped_column(String(64), ForeignKey("risks.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    score: Mapped[float] = mapped_column(Float, default=50.0)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    risk: Mapped["Risk"] = relationship("Risk", back_populates="factors")


class RiskAssessment(Base):
    """Evaluation run analyzing a risk (AI agent or human analyst)."""
    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    risk_id: Mapped[str] = mapped_column(String(64), ForeignKey("risks.id"), nullable=False)
    assessor_type: Mapped[str] = mapped_column(String(50), default="AI_AGENT")
    assessor_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    methodology: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    findings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=50.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    risk: Mapped["Risk"] = relationship("Risk", back_populates="assessments")


class Incident(Base):
    """Realized disruption actively investigated or mitigated."""
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    risk_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("risks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="DETECTED")
    severity: Mapped[str] = mapped_column(String(50), default="MEDIUM")
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    affected_assets: Mapped[list[Any]] = mapped_column(JSON, default=list)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    risk: Mapped[Optional["Risk"]] = relationship("Risk", back_populates="incidents")
