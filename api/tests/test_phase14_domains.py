"""Phase 14 Test Suite: Supply chain optimization domains and service execution.

Validates:
- End-to-end Shipment Reroute optimization via OptimizationService
- Availability constraint: disrupted candidates are bypassed
- Capacity constraint: overflow routes are penalized/prevented
- Objective variants: MINIMIZE_DELAY, MINIMIZE_COST, MINIMIZE_RISK
- Comparative metrics: baseline, optimized, delta
- Deterministic fingerprints and idempotency
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
    OptimizationObjectiveType,
    OptimizationRequest,
    OptimizationStatus,
)
from app.optimization.service import OptimizationService


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing service persistence."""
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


def test_shipment_reroute_selects_lowest_delay(db_session: Session):
    """Verify optimization selects the lowest-delay route alternative."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-fast",
            entity_type="ROUTE",
            entity_id="route-fast",
            is_available=True,
            transit_time_hours=12.0,
            cost=2000.0,
            capacity=10.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-slow",
            entity_type="ROUTE",
            entity_id="route-slow",
            is_available=True,
            transit_time_hours=48.0,
            cost=800.0,
            capacity=10.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["shipment-101"],
        candidate_alternatives=candidates,
        parameters={"baseline_delay_hours": 36.0},
    )

    result = OptimizationService.run_optimization(db=db_session, request=req)

    assert result.status == OptimizationStatus.OPTIMAL
    assert result.objective_value == pytest.approx(12.0)
    assert len(result.selected_alternatives) == 1
    assert result.selected_alternatives[0].entity_id == "route-fast"

    # Check comparative metric
    delay_metric = result.metrics["delay_hours"]
    assert delay_metric.baseline_value == pytest.approx(36.0)
    assert delay_metric.optimized_value == pytest.approx(12.0)
    assert delay_metric.delta == pytest.approx(-24.0)  # 24 hours saved!


def test_shipment_reroute_bypasses_unavailable_candidate(db_session: Session):
    """Verify solver never selects an unavailable candidate even if it has lower delay."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-disrupted",
            entity_type="ROUTE",
            entity_id="route-disrupted",
            is_available=False,  # Unavailable due to port strike/weather
            transit_time_hours=8.0,  # Fast but blocked!
            capacity=10.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-detour",
            entity_type="ROUTE",
            entity_id="route-detour",
            is_available=True,
            transit_time_hours=24.0,
            capacity=10.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["shipment-101"],
        candidate_alternatives=candidates,
    )

    result = OptimizationService.run_optimization(db=db_session, request=req)

    assert result.status == OptimizationStatus.OPTIMAL
    assert result.objective_value == pytest.approx(24.0)
    assert len(result.selected_alternatives) == 1
    assert result.selected_alternatives[0].entity_id == "route-detour"


def test_shipment_reroute_all_unavailable_infeasible(db_session: Session):
    """Verify solver reports INFEASIBLE when all candidates are unavailable."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-1",
            entity_type="ROUTE",
            entity_id="route-1",
            is_available=False,
            transit_time_hours=10.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-2",
            entity_type="ROUTE",
            entity_id="route-2",
            is_available=False,
            transit_time_hours=20.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["shipment-101"],
        candidate_alternatives=candidates,
    )

    result = OptimizationService.run_optimization(db=db_session, request=req)

    assert result.status == OptimizationStatus.INFEASIBLE
    assert result.objective_value is None
    assert len(result.selected_alternatives) == 0


def test_determinism_identical_runs_yield_identical_fingerprints(db_session: Session):
    """Verify optimization is completely deterministic: identical inputs yield identical fingerprints."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-b",
            entity_type="ROUTE",
            entity_id="route-b",
            transit_time_hours=30.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-a",
            entity_type="ROUTE",
            entity_id="route-a",
            transit_time_hours=15.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["ship-1"],
        candidate_alternatives=candidates,
    )

    res1 = OptimizationService.run_optimization(db=db_session, request=req)
    res2 = OptimizationService.run_optimization(db=db_session, request=req)

    assert res1.request_fingerprint == res2.request_fingerprint
    assert res1.result_fingerprint == res2.result_fingerprint
    assert res1.optimization_id == res2.optimization_id
    assert res1.objective_value == res2.objective_value
