"""Tests for Phase 20 EvaluationRunner, Minimal Persistence, and API Endpoints."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.base import Base
from app.evaluation.contracts import EvaluationSuiteType, EvaluationStatus
from app.evaluation.runner import EvaluationRunner
from app.main import app
from app.models.evaluation import EvaluationRunModel, EvaluationReportModel, EvaluationBase
from app.models.tenancy import User
from app.schemas.session import SessionData
from app.api.deps import get_authenticated_context, AuthenticatedContext


@pytest.fixture
def test_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    EvaluationBase.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


from datetime import datetime, timezone, timedelta

def _get_test_context():
    user = User(
        id="user-eval-1",
        email="evaluator@riskwise.internal",
        role="ANALYST",
        org_id="org-acme-01",
        is_active=True,
    )
    session_data = SessionData(
        session_id="sess-eval-123",
        user_id="user-eval-1",
        email="evaluator@riskwise.internal",
        org_id="org-acme-01",
        role="ANALYST",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    return AuthenticatedContext(user=user, session_data=session_data)



def test_evaluation_runner_executes_suite_and_persists(test_db_session):
    report = EvaluationRunner.run_suite(
        suite_type=EvaluationSuiteType.SECURITY_EVALUATION,
        tenant_id="tenant-gold-001",
        db_session=test_db_session,
    )
    assert report.status == EvaluationStatus.PASSED

    # Verify persistence in DB
    run_record = test_db_session.query(EvaluationRunModel).filter_by(id=report.run_id).first()
    assert run_record is not None
    assert run_record.suite_type == "SECURITY_EVALUATION"
    assert run_record.tenant_id == "tenant-gold-001"

    # Verify report JSON stored
    report_record = test_db_session.query(EvaluationReportModel).filter_by(run_id=report.run_id).first()
    assert report_record is not None
    assert report_record.report_json["suite_type"] == "SECURITY_EVALUATION"


def test_evaluation_runner_get_and_list_runs(test_db_session):
    EvaluationRunner.run_suite(
        suite_type=EvaluationSuiteType.RISK_EVALUATION,
        tenant_id="tenant-gold-001",
        db_session=test_db_session,
    )
    runs = EvaluationRunner.list_runs(test_db_session, tenant_id="tenant-gold-001")
    assert len(runs) >= 1
    assert runs[0].suite_type == "RISK_EVALUATION"


def test_evaluation_api_suites_endpoint():
    client = TestClient(app)
    app.dependency_overrides[get_authenticated_context] = _get_test_context
    try:
        response = client.get("/api/v1/evaluations/suites")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 10
        suite_names = [s["suite_type"] for s in data]
        assert "SECURITY_EVALUATION" in suite_names
        assert "RISK_EVALUATION" in suite_names
    finally:
        app.dependency_overrides.pop(get_authenticated_context, None)


def test_evaluation_api_datasets_endpoint():
    client = TestClient(app)
    app.dependency_overrides[get_authenticated_context] = _get_test_context
    try:
        response = client.get("/api/v1/evaluations/datasets")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 10
        assert all(d["is_eval_only"] is True for d in data)
    finally:
        app.dependency_overrides.pop(get_authenticated_context, None)


def test_evaluation_api_run_suite_endpoint():
    client = TestClient(app)
    app.dependency_overrides[get_authenticated_context] = _get_test_context
    try:
        payload = {
            "suite_type": "RISK_EVALUATION",
            "dataset_version": "v1.0.0",
            "persist_results": False,
        }
        response = client.post("/api/v1/evaluations/run", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["suite_type"] == "RISK_EVALUATION"
        assert data["status"] == "PASSED"
        assert data["total_cases"] >= 1
    finally:
        app.dependency_overrides.pop(get_authenticated_context, None)
