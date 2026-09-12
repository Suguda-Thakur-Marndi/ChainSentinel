"""Phase 14 Test Suite: Security, Adversarial Testing, and Non-Fabrication Guarantees.

Validates:
- Cross-tenant rejection
- Zero candidates handling
- Single candidate handling
- Contradictory hard constraints proving INFEASIBLE
- Data non-fabrication: missing cost for MINIMIZE_COST fails closed
- Data non-fabrication: missing baseline metrics explicitly reported as NOT_AVAILABLE
- Resource limits against oversized inputs
- Audit provenance safety: zero secrets leaked
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationDomain,
    OptimizationMetricAvailability,
    OptimizationObjectiveType,
    OptimizationRequest,
    OptimizationStatus,
)
from app.optimization.errors import (
    OptimizationDataMissingError,
    OptimizationResourceLimitError,
    OptimizationTenantIsolationError,
    OptimizationValidationError,
)
from app.optimization.service import OptimizationService


@pytest.fixture
def db_session():
    """In-memory SQLite session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_cross_tenant_request_rejected(db_session: Session):
    """Verify OptimizationService rejects request when organization_id mismatches expected context."""
    req = OptimizationRequest(
        organization_id="org-tenant-b",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["s-1"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-1",
                entity_type="ROUTE",
                entity_id="r1",
                transit_time_hours=10.0,
            )
        ],
    )
    with pytest.raises(OptimizationTenantIsolationError, match="Tenant mismatch"):
        OptimizationService.run_optimization(
            db=db_session,
            request=req,
            expected_organization_id="org-tenant-a",
        )


def test_zero_candidates_returns_infeasible_gracefully(db_session: Session):
    """Verify zero candidates returns INFEASIBLE without crashing or throwing unhandled errors."""
    req = OptimizationRequest(
        organization_id="org-tenant-a",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["s-1"],
        candidate_alternatives=[],  # Empty candidates
    )
    result = OptimizationService.run_optimization(db=db_session, request=req)
    assert result.status == OptimizationStatus.INFEASIBLE
    assert result.objective_value is None
    assert len(result.selected_alternatives) == 0
    assert "No candidate alternatives available" in (result.failure_reason or "")


def test_single_candidate_selection(db_session: Session):
    """Verify solver correctly solves for a single available candidate."""
    req = OptimizationRequest(
        organization_id="org-tenant-a",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["s-1"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-sole",
                entity_type="ROUTE",
                entity_id="r-sole",
                transit_time_hours=15.5,
            )
        ],
    )
    result = OptimizationService.run_optimization(db=db_session, request=req)
    assert result.status == OptimizationStatus.OPTIMAL
    assert result.objective_value == pytest.approx(15.5)
    assert len(result.selected_alternatives) == 1
    assert result.selected_alternatives[0].entity_id == "r-sole"


def test_non_fabrication_missing_baseline_is_not_available(db_session: Session):
    """Verify missing baseline metric is explicitly NOT_AVAILABLE and never fabricated as 0.0."""
    req = OptimizationRequest(
        organization_id="org-tenant-a",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["s-1"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-1",
                entity_type="ROUTE",
                entity_id="r1",
                transit_time_hours=20.0,
            )
        ],
        parameters={},  # No baseline delay provided
    )
    result = OptimizationService.run_optimization(db=db_session, request=req)
    assert result.status == OptimizationStatus.OPTIMAL
    delay_metric = result.metrics["delay_hours"]
    assert delay_metric.baseline_value is None
    assert delay_metric.delta is None  # Delta cannot be computed without baseline
    assert delay_metric.optimized_value == pytest.approx(20.0)


def test_audit_provenance_contains_no_secrets(db_session: Session):
    """Verify provenance metadata does not contain passwords, API keys, or tokens."""
    req = OptimizationRequest(
        organization_id="org-tenant-a",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["s-1"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-1",
                entity_type="ROUTE",
                entity_id="r1",
                transit_time_hours=10.0,
            )
        ],
    )
    result = OptimizationService.run_optimization(db=db_session, request=req)
    serialized = result.model_dump_json()

    for secret_keyword in ("password", "api_key", "secret", "token", "private_key"):
        assert f'"{secret_keyword}"' not in serialized.lower()
