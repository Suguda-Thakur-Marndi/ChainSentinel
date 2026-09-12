"""Evaluation API endpoints for RiskWise 2.0 (Phase 20).

Provides authenticated, tenant-isolated access to deterministic evaluation suites,
benchmarks, golden datasets, and historical evaluation reports.
"""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthenticatedContext, get_authenticated_context
from app.db.session import get_db
from app.evaluation.contracts import (
    EvaluationSuiteType,
    EvaluationReport,
    EvaluationStatus,
    EvaluationDomain,
)
from app.evaluation.datasets.registry import DatasetRegistry
from app.evaluation.runner import EvaluationRunner
from app.evaluation.suites import SUITE_REGISTRY

router = APIRouter()


class RunSuiteRequest(BaseModel):
    """Payload for triggering an evaluation suite."""

    suite_type: EvaluationSuiteType = Field(..., description="Target evaluation suite to execute")
    dataset_version: str = Field("v1.0.0", description="Golden dataset version to evaluate against")
    persist_results: bool = Field(True, description="Whether to persist the run record to the evaluation store")


class EvaluationRunSummaryResponse(BaseModel):
    """Summary of an evaluation run."""

    id: str
    suite_type: str
    domain: str
    status: str
    tenant_id: Optional[str]
    dataset_version: str
    config_fingerprint: str
    result_fingerprint: str
    duration_ms: float
    total_cases: int
    passed_cases: int
    failed_cases: int
    summary: Optional[str]
    created_at: Optional[str]


class EvaluationSuiteMetadataResponse(BaseModel):
    suite_type: str
    domain: str
    version: str
    description: str


class EvaluationDatasetMetadataResponse(BaseModel):
    dataset_id: str
    name: str
    domain: str
    version: str
    case_count: int
    fingerprint: str
    is_eval_only: bool


@router.get("/suites", response_model=List[EvaluationSuiteMetadataResponse], status_code=status.HTTP_200_OK)
def list_evaluation_suites(
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> List[EvaluationSuiteMetadataResponse]:
    """List all registered evaluation suites available for benchmarking."""
    suites = []
    for st, suite_cls in SUITE_REGISTRY.items():
        instance = suite_cls()
        suites.append(
            EvaluationSuiteMetadataResponse(
                suite_type=st.value,
                domain=instance.domain.value,
                version=instance.version,
                description=f"Deterministic evaluation suite for {st.value}",
            )
        )
    return suites


@router.get("/datasets", response_model=List[EvaluationDatasetMetadataResponse], status_code=status.HTTP_200_OK)
def list_evaluation_datasets(
    context: AuthenticatedContext = Depends(get_authenticated_context),
) -> List[EvaluationDatasetMetadataResponse]:
    """List all immutable, versioned golden evaluation datasets."""
    datasets = DatasetRegistry.list_datasets()
    return [
        EvaluationDatasetMetadataResponse(
            dataset_id=ds.dataset_id,
            name=ds.name,
            domain=ds.domain.value,
            version=ds.version,
            case_count=len(ds.cases),
            fingerprint=ds.fingerprint,
            is_eval_only=ds.is_eval_only,
        )
        for ds in datasets
    ]


@router.post("/run", response_model=EvaluationReport, status_code=status.HTTP_200_OK)
def run_evaluation_suite(
    payload: RunSuiteRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> EvaluationReport:
    """Executes an evaluation suite against golden datasets.

    Enforces:
    - Authenticated caller
    - Tenant scoping
    - Zero production mutation
    """
    tenant_id = context.org_id
    db_session = db if payload.persist_results else None

    try:
        report = EvaluationRunner.run_suite(
            suite_type=payload.suite_type,
            dataset_version=payload.dataset_version,
            tenant_id=tenant_id,
            db_session=db_session,
        )
        return report
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation execution failed: {str(e)}",
        )


@router.get("/runs", response_model=List[EvaluationRunSummaryResponse], status_code=status.HTTP_200_OK)
def list_evaluation_runs(
    suite_type: Optional[str] = Query(None, description="Filter by suite type"),
    limit: int = Query(50, ge=1, le=100, description="Max runs to return"),
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> List[EvaluationRunSummaryResponse]:
    """Lists historical evaluation runs for the caller's tenant."""
    tenant_id = context.org_id
    runs = EvaluationRunner.list_runs(
        session=db,
        tenant_id=tenant_id,
        suite_type=suite_type,
        limit=limit,
    )
    return [
        EvaluationRunSummaryResponse(
            id=r.id,
            suite_type=r.suite_type,
            domain=r.domain,
            status=r.status,
            tenant_id=r.tenant_id,
            dataset_version=r.dataset_version,
            config_fingerprint=r.config_fingerprint,
            result_fingerprint=r.result_fingerprint,
            duration_ms=r.duration_ms,
            total_cases=r.total_cases,
            passed_cases=r.passed_cases,
            failed_cases=r.failed_cases,
            summary=r.summary,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=EvaluationRunSummaryResponse, status_code=status.HTTP_200_OK)
def get_evaluation_run(
    run_id: str,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> EvaluationRunSummaryResponse:
    """Retrieve details of a specific evaluation run."""
    run = EvaluationRunner.get_run(run_id, db)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")

    # Tenant check
    if run.tenant_id and run.tenant_id != context.org_id and context.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access to evaluation run denied")

    return EvaluationRunSummaryResponse(
        id=run.id,
        suite_type=run.suite_type,
        domain=run.domain,
        status=run.status,
        tenant_id=run.tenant_id,
        dataset_version=run.dataset_version,
        config_fingerprint=run.config_fingerprint,
        result_fingerprint=run.result_fingerprint,
        duration_ms=run.duration_ms,
        total_cases=run.total_cases,
        passed_cases=run.passed_cases,
        failed_cases=run.failed_cases,
        summary=run.summary,
        created_at=run.created_at.isoformat() if run.created_at else None,
    )


@router.get("/runs/{run_id}/report", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
def get_evaluation_report(
    run_id: str,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve the full JSON evaluation report for a run."""
    run = EvaluationRunner.get_run(run_id, db)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")

    if run.tenant_id and run.tenant_id != context.org_id and context.role != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access to evaluation report denied")

    report_json = EvaluationRunner.get_report(run_id, db)
    if not report_json:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation report payload not found")

    return report_json
