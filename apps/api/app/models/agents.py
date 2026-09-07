"""SQLAlchemy models for multi-agent autonomous investigation runs, tasks, and tool call audits."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class AgentRun(Base):
    """End-to-end orchestrated multi-agent incident investigation pipeline execution."""
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    incident_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("incidents.id"), nullable=True)
    workflow_name: Mapped[str] = mapped_column(String(100), default="STANDARD_INVESTIGATION")
    current_stage: Mapped[str] = mapped_column(String(50), default="DETECTION")
    status: Mapped[str] = mapped_column(String(50), default="RUNNING")
    trigger_type: Mapped[str] = mapped_column(String(50), default="SIGNAL_THRESHOLD")
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_summary: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tasks: Mapped[list["AgentTask"]] = relationship(
        "AgentTask", back_populates="agent_run", cascade="all, delete-orphan"
    )


class AgentTask(Base):
    """Execution step performed by a specialized agent (Detection, Research, Simulation)."""
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    agent_run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    findings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent_run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="tasks")
    tool_calls: Mapped[list["AgentToolCall"]] = relationship(
        "AgentToolCall", back_populates="agent_task", cascade="all, delete-orphan"
    )


class AgentToolCall(Base):
    """Audit record of external tools invoked during an agent task (AIS, Weather, Solvers)."""
    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    agent_task_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_tasks.id"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="SUCCESS")
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    agent_task: Mapped["AgentTask"] = relationship("AgentTask", back_populates="tool_calls")
