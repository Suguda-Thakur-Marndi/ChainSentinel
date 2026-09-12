"""Evaluation Runner for RiskWise 2.0.

Orchestrates execution of evaluation suites against versioned golden datasets.
Guarantees:
- Zero production database mutation (evaluation runs in isolated memory/fixtures)
- Tenant isolation and safety
- Strict metric calculation without fabrication
- Optional persistence of evaluation run records and reports
"""

from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.evaluation.contracts import (
    EvaluationSuiteType,
    EvaluationReport,
    EvaluationStatus,
)
from app.evaluation.datasets.registry import DatasetRegistry, DEFAULT_DATASET_VERSION
from app.evaluation.suites import get_suite, SUITE_REGISTRY
from app.models.evaluation import (
    EvaluationRunModel,
    EvaluationMetricRecordModel,
    EvaluationReportModel,
    ensure_evaluation_tables_exist,
)


class EvaluationRunner:
    """Orchestrator for executing deterministic Phase 20 evaluation suites."""

    @classmethod
    def run_suite(
        cls,
        suite_type: EvaluationSuiteType,
        dataset_version: str = DEFAULT_DATASET_VERSION,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> EvaluationReport:
        """Executes a single evaluation suite and optionally persists the report."""
        dataset = DatasetRegistry.get_dataset(suite_type, version=dataset_version)
        DatasetRegistry.guard_against_contamination(dataset, target_subsystem="EVALUATION_HARNESS")

        suite = get_suite(suite_type)
        run_id = f"run-{suite_type.value.lower().replace('_', '-')}-{uuid.uuid4().hex[:8]}"

        report = suite.run(dataset, tenant_id=tenant_id, run_id=run_id)

        if db_session is not None:
            cls.persist_report(report, db_session)

        return report

    @classmethod
    def run_all_suites(
        cls,
        dataset_version: str = DEFAULT_DATASET_VERSION,
        tenant_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> List[EvaluationReport]:
        """Executes all registered evaluation suites across all domains."""
        reports: List[EvaluationReport] = []
        for suite_type in SUITE_REGISTRY.keys():
            report = cls.run_suite(
                suite_type=suite_type,
                dataset_version=dataset_version,
                tenant_id=tenant_id,
                db_session=db_session,
            )
            reports.append(report)
        return reports

    @classmethod
    def persist_report(cls, report: EvaluationReport, session: Session) -> EvaluationRunModel:
        """Persists evaluation summary and metric records to the database."""
        bind = session.get_bind() if hasattr(session, "get_bind") else getattr(session, "bind", None)
        if bind is not None:
            ensure_evaluation_tables_exist(bind)

        run_record = EvaluationRunModel(
            id=report.run_id,
            suite_type=report.suite_type.value,
            domain=report.domain.value,
            status=report.status.value,
            tenant_id=report.tenant_id,
            dataset_version=report.dataset_version,
            config_fingerprint=report.configuration_fingerprint,
            result_fingerprint=report.result_fingerprint,
            duration_ms=report.duration_ms,
            total_cases=report.total_cases,
            passed_cases=report.passed_cases,
            failed_cases=report.failed_cases,
            summary=report.summary,
        )
        session.add(run_record)

        # Persist individual metrics
        for m in report.metrics:
            metric_record = EvaluationMetricRecordModel(
                id=f"met-{uuid.uuid4().hex[:12]}",
                run_id=report.run_id,
                name=m.name,
                domain=m.domain.value,
                value=m.value,
                status=m.status.value,
                sample_size=m.sample_size,
                numerator=m.numerator,
                denominator=m.denominator,
            )
            session.add(metric_record)

        # Persist report JSON
        report_record = EvaluationReportModel(
            id=report.report_id,
            run_id=report.run_id,
            report_json=report.model_dump(mode="json"),
        )
        session.add(report_record)

        try:
            session.commit()
            session.refresh(run_record)
        except Exception:
            session.rollback()
            raise

        return run_record

    @classmethod
    def get_run(cls, run_id: str, session: Session) -> Optional[EvaluationRunModel]:
        bind = session.get_bind() if hasattr(session, "get_bind") else getattr(session, "bind", None)
        if bind is not None:
            ensure_evaluation_tables_exist(bind)
        return session.query(EvaluationRunModel).filter(EvaluationRunModel.id == run_id).first()

    @classmethod
    def list_runs(
        cls,
        session: Session,
        tenant_id: Optional[str] = None,
        suite_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[EvaluationRunModel]:
        bind = session.get_bind() if hasattr(session, "get_bind") else getattr(session, "bind", None)
        if bind is not None:
            ensure_evaluation_tables_exist(bind)
        q = session.query(EvaluationRunModel)
        if tenant_id:
            q = q.filter(EvaluationRunModel.tenant_id == tenant_id)
        if suite_type:
            q = q.filter(EvaluationRunModel.suite_type == suite_type)
        return q.order_by(EvaluationRunModel.created_at.desc()).limit(limit).all()

    @classmethod
    def get_report(cls, run_id: str, session: Session) -> Optional[Dict[str, Any]]:
        bind = session.get_bind() if hasattr(session, "get_bind") else getattr(session, "bind", None)
        if bind is not None:
            ensure_evaluation_tables_exist(bind)
        report_record = (
            session.query(EvaluationReportModel)
            .filter(EvaluationReportModel.run_id == run_id)
            .first()
        )
        return report_record.report_json if report_record else None

