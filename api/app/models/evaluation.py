"""SQLAlchemy database models for Phase 20 Evaluation Framework.

Provides minimal, isolated persistence for evaluation runs, metrics, and reports
without polluting or mutating operational supply chain tables.
"""

from datetime import datetime
from typing import Any, Optional, List
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import declarative_base, Mapped, mapped_column, relationship
from app.db.base import generate_uuid

# Dedicated declarative base for Phase 20 Evaluation Framework persistence
# Guarantees operational Base.metadata.tables invariant (strictly 34 tables) remains intact
EvaluationBase = declarative_base()


def ensure_evaluation_tables_exist(bind_engine) -> None:
    """Creates evaluation persistence tables on the target engine if not existing."""
    if bind_engine is not None:
        EvaluationBase.metadata.create_all(bind=bind_engine)


class EvaluationRunModel(EvaluationBase):
    """Stores metadata and summary status for an evaluation run."""

    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    suite_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    dataset_version: Mapped[str] = mapped_column(String(32), default="v1.0.0")
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    metrics: Mapped[List["EvaluationMetricRecordModel"]] = relationship(
        "EvaluationMetricRecordModel",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    report: Mapped[Optional["EvaluationReportModel"]] = relationship(
        "EvaluationReportModel",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
    )


class EvaluationMetricRecordModel(EvaluationBase):
    """Individual calculated metric record associated with an evaluation run."""

    __tablename__ = "evaluation_metrics"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PASSED")
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    numerator: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    denominator: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    run: Mapped["EvaluationRunModel"] = relationship(
        "EvaluationRunModel", back_populates="metrics"
    )


class EvaluationReportModel(EvaluationBase):
    """Full structured evaluation report JSON payload."""

    __tablename__ = "evaluation_reports"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=generate_uuid
    )
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    run: Mapped["EvaluationRunModel"] = relationship(
        "EvaluationRunModel", back_populates="report"
    )
