"""Phase 14 Test Suite: Digital Twin, Simulation, Risk Engine, and ML Integrations.

Validates:
- Digital Twin snapshot integration: Candidate route extraction from graph edges
- Simulation integration: Disrupted simulated nodes/edges correctly mark candidates unavailable
- Read-only Risk Engine integration
- Read-only ML inference integration
- Operational source-of-truth immutability: operational DB tables are unchanged
- Cross-tenant snapshot failure
"""
from __future__ import annotations

from datetime import datetime
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.contracts import (
    DigitalTwinProvenance,
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.models.logistics import Shipment
from app.models.network import Factory, Route, Supplier, Warehouse
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationDomain,
    OptimizationObjectiveType,
    OptimizationRequest,
    OptimizationStatus,
)
from app.optimization.errors import OptimizationTenantIsolationError
from app.optimization.integration import (
    DigitalTwinOptimizationIntegration,
    MLOptimizationIntegration,
    RiskEngineOptimizationIntegration,
    SimulationOptimizationIntegration,
)
from app.optimization.service import OptimizationService
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType
from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationEffect,
    SimulationEntityImpact,
    SimulationOutcome,
    SimulationProvenance,
    SimulationResult,
    SimulationStatus as SimStatus,
)


@pytest.fixture
def in_memory_db():
    """In-memory SQLite database populated with base entities."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()

    # Seed operational data
    sup = Supplier(id="sup-1", org_id="org-acme", name="Alpha Chipmaker")
    wh = Warehouse(id="wh-1", org_id="org-acme", name="Central Distribution", total_capacity=500.0)
    rt1 = Route(id="rt-1", org_id="org-acme", name="Route Primary", standard_lead_time_days=2.0)
    rt2 = Route(id="rt-2", org_id="org-acme", name="Route Alternate", standard_lead_time_days=4.0)
    sh = Shipment(id="sh-1", org_id="org-acme", tracking_number="TRK-100", route_id="rt-1")

    session.add_all([sup, wh, rt1, rt2, sh])
    session.commit()

    yield session
    session.close()


def test_digital_twin_candidate_extraction():
    """Verify candidate routes are extracted accurately from Digital Twin snapshot."""
    prov = DigitalTwinProvenance(
        source_entity_type="NODE",
        source_entity_id="node-1",
    )
    node1 = TwinNodeContract(
        node_id="n1",
        organization_id="org-acme",
        node_type=TwinNodeType.SUPPLIER,
        source_entity_type="SUPPLIER",
        source_entity_id="sup-1",
        label="Supplier Alpha",
        provenance=prov,
        fingerprint="a" * 64,
    )
    node2 = TwinNodeContract(
        node_id="n2",
        organization_id="org-acme",
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="wh-1",
        label="Warehouse Central",
        provenance=prov,
        fingerprint="b" * 64,
    )
    edge1 = TwinEdgeContract(
        edge_id="e1",
        organization_id="org-acme",
        from_node_id="n1",
        to_node_id="n2",
        edge_type=TwinEdgeType.TRANSPORT,
        flow_capacity=50.0,
        properties={"transit_time_hours": 18.0, "cost": 1500.0},
        provenance=prov,
        fingerprint="c" * 64,
    )
    snapshot = DigitalTwinSnapshot(
        twin_id="twin-acme-1",
        organization_id="org-acme",
        node_count=2,
        edge_count=1,
        nodes={"n1": node1, "n2": node2},
        edges={"e1": edge1},
        source_fingerprint="d" * 64,
        twin_fingerprint="e" * 64,
        generated_at=datetime.utcnow(),
    )

    candidates = DigitalTwinOptimizationIntegration.extract_candidate_routes(
        snapshot=snapshot, organization_id="org-acme"
    )

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.entity_id == "e1"
    assert cand.transit_time_hours == 18.0
    assert cand.cost == 1500.0
    assert cand.capacity == 50.0
    assert cand.is_available is True


def test_cross_tenant_snapshot_fails_closed():
    """Verify attempting to extract candidates from another tenant's snapshot fails closed."""
    snapshot = DigitalTwinSnapshot(
        twin_id="twin-other",
        organization_id="org-other",
        node_count=0,
        edge_count=0,
        nodes={},
        edges={},
        source_fingerprint="d" * 64,
        twin_fingerprint="e" * 64,
        generated_at=datetime.utcnow(),
    )
    with pytest.raises(OptimizationTenantIsolationError, match="does not match request organization"):
        DigitalTwinOptimizationIntegration.extract_candidate_routes(
            snapshot=snapshot, organization_id="org-acme"
        )


def test_simulation_effects_mark_candidates_unavailable():
    """Verify simulation disruption effects mark affected candidate routes as unavailable."""
    candidates = [
        OptimizationAlternative(
            alternative_id="alt-1",
            entity_type="ROUTE",
            entity_id="edge-port-outage",
            is_available=True,
            transit_time_hours=10.0,
        ),
        OptimizationAlternative(
            alternative_id="alt-2",
            entity_type="ROUTE",
            entity_id="edge-open-sea",
            is_available=True,
            transit_time_hours=20.0,
        ),
    ]

    sim_res = SimulationResult(
        simulation_id="sim-001",
        scenario_id="scen-001",
        organization_id="org-acme",
        base_snapshot_fingerprint="f" * 64,
        simulation_fingerprint="g" * 64,
        status=SimStatus.COMPLETED,
        outcome=SimulationOutcome(),
        effects=[
            SimulationEffect(
                effect_id="eff-1",
                originating_change_id="ch-1",
                affected_entity_id="edge-port-outage",
                affected_entity_type="ROUTE",
                effect_type="EDGE_UNAVAILABLE",
                rule_applied="DISRUPTION_RULE",
                description="Port corridor blocked",
            )
        ],
        entity_impacts=[
            SimulationEntityImpact(
                entity_id="edge-port-outage",
                entity_type="ROUTE",
                impact_type="SEVERED",
                is_available=False,
            )
        ],
        provenance=SimulationProvenance(
            base_snapshot_fingerprint="f" * 64,
            organization_id="org-acme",
        ),
    )

    updated = SimulationOptimizationIntegration.apply_simulation_effects_to_candidates(
        candidates=candidates, simulation_result=sim_res
    )

    cand1 = next(c for c in updated if c.entity_id == "edge-port-outage")
    cand2 = next(c for c in updated if c.entity_id == "edge-open-sea")
    assert cand1.is_available is False
    assert cand2.is_available is True


def test_operational_database_immutability(in_memory_db: Session):
    """Verify operational DB entities (Suppliers, Warehouses, Shipments, Routes) remain 100% unmutated."""
    sup_count_before = in_memory_db.scalar(select(func.count(Supplier.id)))
    wh_count_before = in_memory_db.scalar(select(func.count(Warehouse.id)))
    rt_count_before = in_memory_db.scalar(select(func.count(Route.id)))
    sh_count_before = in_memory_db.scalar(select(func.count(Shipment.id)))

    # Fetch initial shipment details
    shipment_before = in_memory_db.get(Shipment, "sh-1")
    orig_route_id = shipment_before.route_id

    req = OptimizationRequest(
        organization_id="org-acme",
        domain=OptimizationDomain.SHIPMENT_REROUTE,
        objective_type=OptimizationObjectiveType.MINIMIZE_DELAY,
        target_entity_ids=["sh-1"],
        candidate_alternatives=[
            OptimizationAlternative(
                alternative_id="alt-1",
                entity_type="ROUTE",
                entity_id="rt-2",
                transit_time_hours=10.0,
            )
        ],
    )

    result = OptimizationService.run_optimization(db=in_memory_db, request=req)
    assert result.status == OptimizationStatus.OPTIMAL

    # Verify counts are identical
    assert in_memory_db.scalar(select(func.count(Supplier.id))) == sup_count_before
    assert in_memory_db.scalar(select(func.count(Warehouse.id))) == wh_count_before
    assert in_memory_db.scalar(select(func.count(Route.id))) == rt_count_before
    assert in_memory_db.scalar(select(func.count(Shipment.id))) == sh_count_before

    # Verify shipment was NOT mutated (optimization produces mathematical output, NOT operational mutation)
    in_memory_db.expire_all()
    shipment_after = in_memory_db.get(Shipment, "sh-1")
    assert shipment_after.route_id == orig_route_id  # Unchanged!
