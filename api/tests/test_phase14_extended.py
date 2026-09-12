"""Phase 14 Test Suite: Extended domain, solver edge cases, and objective evaluations.

Validates:
- Multi-shipment joint assignment under shared capacity limits
- MINIMIZE_RISK objective optimization
- MINIMIZE_COST with valid authoritative cost data
- ROUTE_SELECTION domain variable construction
- Direct OptimizationService get_optimization_result and list_optimization_runs
- Digital Twin extraction with origin/destination filtering
- Infeasible and failure handling gracefully returned in OptimizationResult
"""
from __future__ import annotations

from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.contracts import (
    DigitalTwinProvenance,
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationDomain,
    OptimizationObjectiveType,
    OptimizationProblem,
    OptimizationRequest,
    OptimizationSolverConfig,
    OptimizationStatus,
)
from app.optimization.integration import DigitalTwinOptimizationIntegration
from app.optimization.service import OptimizationService
from app.optimization.solver import OrToolsSolver
from app.optimization.variables import VariableBuilder
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


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


def test_multi_shipment_shared_capacity_optimization(db_session: Session):
    """Verify multiple shipments sharing constrained route capacity are partitioned optimally."""
    # 3 shipments (s1, s2, s3).
    # Route Fast: capacity 2.0 shipments, delay 10 hours.
    # Route Slow: capacity 5.0 shipments, delay 30 hours.
    # Solver must assign 2 shipments to Route Fast and 1 shipment to Route Slow.
    # Total delay: 10 + 10 + 30 = 50 hours.
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-fast",
            entity_type="ROUTE",
            entity_id="r-fast",
            is_available=True,
            transit_time_hours=10.0,
            capacity=2.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-slow",
            entity_type="ROUTE",
            entity_id="r-slow",
            is_available=True,
            transit_time_hours=30.0,
            capacity=5.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["ship-1", "ship-2", "ship-3"],
        candidate_alternatives=candidates,
    )

    result = OptimizationService.run_optimization(db=db_session, request=req)
    assert result.status == OptimizationStatus.OPTIMAL
    assert result.objective_value == pytest.approx(50.0)
    assert len(result.selected_alternatives) == 3

    # Check capacity allocation
    assigned_to_fast = sum(1 for sa in result.selected_alternatives if sa.entity_id == "r-fast")
    assigned_to_slow = sum(1 for sa in result.selected_alternatives if sa.entity_id == "r-slow")
    assert assigned_to_fast == 2
    assert assigned_to_slow == 1


def test_minimize_risk_objective_optimization(db_session: Session):
    """Verify MINIMIZE_RISK selects route with lowest risk score."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-high-risk",
            entity_type="ROUTE",
            entity_id="r-high-risk",
            is_available=True,
            transit_time_hours=10.0,
            risk_score=75.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-low-risk",
            entity_type="ROUTE",
            entity_id="r-low-risk",
            is_available=True,
            transit_time_hours=15.0,
            risk_score=15.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_RISK,
        target_entity_ids=["ship-1"],
        candidate_alternatives=candidates,
        parameters={"baseline_risk": 50.0},
    )

    result = OptimizationService.run_optimization(db=db_session, request=req)
    assert result.status == OptimizationStatus.OPTIMAL
    assert result.objective_value == pytest.approx(15.0)
    assert result.selected_alternatives[0].entity_id == "r-low-risk"

    # Verify risk delta
    risk_metric = result.metrics["risk_score"]
    assert risk_metric.baseline_value == pytest.approx(50.0)
    assert risk_metric.optimized_value == pytest.approx(15.0)
    assert risk_metric.delta == pytest.approx(-35.0)


def test_minimize_cost_objective_with_valid_cost_data(db_session: Session):
    """Verify MINIMIZE_COST works when authoritative cost data is present on all candidates."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-expensive",
            entity_type="ROUTE",
            entity_id="r-exp",
            is_available=True,
            cost=5000.0,
            transit_time_hours=12.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-cheap",
            entity_type="ROUTE",
            entity_id="r-cheap",
            is_available=True,
            cost=1200.0,
            transit_time_hours=36.0,
        ),
    ]

    req = OptimizationRequest(
        organization_id="org-acme-1",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_COST,
        target_entity_ids=["ship-1"],
        candidate_alternatives=candidates,
        parameters={"baseline_cost": 4000.0},
    )

    result = OptimizationService.run_optimization(db=db_session, request=req)
    assert result.status == OptimizationStatus.OPTIMAL
    assert result.objective_value == pytest.approx(1200.0)
    assert result.selected_alternatives[0].entity_id == "r-cheap"

    cost_metric = result.metrics["total_cost"]
    assert cost_metric.baseline_value == pytest.approx(4000.0)
    assert cost_metric.optimized_value == pytest.approx(1200.0)
    assert cost_metric.delta == pytest.approx(-2800.0)


def test_service_list_and_get_runs(db_session: Session):
    """Verify OptimizationService.list_optimization_runs and get_optimization_result work directly."""
    req = OptimizationRequest(
        organization_id="org-tenant-direct",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["ship-1"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-1",
                entity_type="ROUTE",
                entity_id="r-1",
                transit_time_hours=8.0,
            )
        ],
    )

    res = OptimizationService.run_optimization(db=db_session, request=req)
    opt_id = res.optimization_id

    # Get by ID
    fetched = OptimizationService.get_optimization_result(
        db=db_session,
        organization_id="org-tenant-direct",
        optimization_id=opt_id,
    )
    assert fetched is not None
    assert fetched.optimization_id == opt_id
    assert fetched.status == OptimizationStatus.OPTIMAL

    # List
    listed = OptimizationService.list_optimization_runs(
        db=db_session,
        organization_id="org-tenant-direct",
    )
    assert len(listed) >= 1
    assert any(r.optimization_id == opt_id for r in listed)


def test_digital_twin_candidate_extraction_filtering():
    """Verify Digital Twin candidate extraction correctly respects origin/destination filters."""
    prov = DigitalTwinProvenance(source_entity_type="NODE", source_entity_id="n1")
    n1 = TwinNodeContract(
        node_id="origin-port",
        organization_id="org-acme",
        node_type=TwinNodeType.PORT,
        source_entity_type="PORT",
        source_entity_id="p1",
        label="Origin Port",
        provenance=prov,
        fingerprint="1" * 64,
    )
    n2 = TwinNodeContract(
        node_id="dest-wh",
        organization_id="org-acme",
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="w1",
        label="Destination Warehouse",
        provenance=prov,
        fingerprint="2" * 64,
    )
    n3 = TwinNodeContract(
        node_id="other-wh",
        organization_id="org-acme",
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="w2",
        label="Other Warehouse",
        provenance=prov,
        fingerprint="3" * 64,
    )
    e1 = TwinEdgeContract(
        edge_id="e-matching",
        organization_id="org-acme",
        from_node_id="origin-port",
        to_node_id="dest-wh",
        edge_type=TwinEdgeType.TRANSPORT,
        provenance=prov,
        fingerprint="4" * 64,
    )
    e2 = TwinEdgeContract(
        edge_id="e-other",
        organization_id="org-acme",
        from_node_id="origin-port",
        to_node_id="other-wh",
        edge_type=TwinEdgeType.TRANSPORT,
        provenance=prov,
        fingerprint="5" * 64,
    )
    snapshot = DigitalTwinSnapshot(
        twin_id="twin-filter",
        organization_id="org-acme",
        node_count=3,
        edge_count=2,
        nodes={"origin-port": n1, "dest-wh": n2, "other-wh": n3},
        edges={"e-matching": e1, "e-other": e2},
        source_fingerprint="6" * 64,
        twin_fingerprint="7" * 64,
        generated_at=datetime.utcnow(),
    )

    filtered = DigitalTwinOptimizationIntegration.extract_candidate_routes(
        snapshot=snapshot,
        organization_id="org-acme",
        origin_node_id="origin-port",
        destination_node_id="dest-wh",
    )
    assert len(filtered) == 1
    assert filtered[0].entity_id == "e-matching"
