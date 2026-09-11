"""SQLAlchemy models for scenarios, simulation projections, and prescriptive optimization runs."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Scenario(Base):
    """What-if simulation scenario definition."""
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    variables_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation", back_populates="scenario", cascade="all, delete-orphan"
    )


class Simulation(Base):
    """Execution run and projected impact metrics of a scenario."""
    __tablename__ = "simulations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    scenario_id: Mapped[str] = mapped_column(String(64), ForeignKey("scenarios.id"), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), default="DETERMINISTIC")
    status: Mapped[str] = mapped_column(String(50), default="COMPLETED")
    baseline_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    projected_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence_interval_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence_interval_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    scenario: Mapped["Scenario"] = relationship("Scenario", back_populates="simulations")


class OptimizationRun(Base):
    """Prescriptive optimization solver execution for mitigation planning."""
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    objective: Mapped[str] = mapped_column(String(255), default="MINIMIZE_DELAY_AND_COST")
    candidate_actions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    recommended_plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_savings_estimate: Mapped[float] = mapped_column(Float, default=0.0)
    delay_reduction_days: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
