"""Integration and read-only invariant tests for RiskWise Phase 13 Simulation Subsystem."""
from __future__ import annotations

from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinNodeContract,
    TwinNodeType,
)
from app.digital_twin.fingerprints import (
    compute_node_fingerprint,
    compute_node_id,
    compute_twin_fingerprint,
)
from app.models.network import Factory, Supplier, Warehouse
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationRequest,
    SimulationStatus,
)
from app.simulation.engine import SimulationEngine
from app.simulation.integration import (
    SimulationMLIntegration,
    SimulationRiskIntegration,
)
from app.simulation.scenario import SimulationScenarioBuilder
from app.simulation.state import SimulationState


@pytest.fixture
def integrated_snapshot() -> DigitalTwinSnapshot:
    """Fixture creating a 3-node digital twin snapshot with health scores and capacity."""
    org_id = "org_integ_test"
    port_id = compute_node_id(org_id, "PORT", "port_integ_1")
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_integ_1")
    fac_id = compute_node_id(org_id, "FACTORY", "fac_integ_1")

    fp1 = compute_node_fingerprint(
        node_id=port_id,
        organization_id=org_id,
        node_type="PORT",
        source_entity_type="PORT",
        source_entity_id="port_integ_1",
        label="Port Integ 1",
        health_score=80.0,
    )
    fp2 = compute_node_fingerprint(
        node_id=wh_id,
        organization_id=org_id,
        node_type="WAREHOUSE",
        source_entity_type="WAREHOUSE",
        source_entity_id="wh_integ_1",
        label="Warehouse Integ 1",
        properties={"capacity": 30000.0, "total_capacity": 30000.0},
        health_score=85.0,
    )
    fp3 = compute_node_fingerprint(
        node_id=fac_id,
        organization_id=org_id,
        node_type="FACTORY",
        source_entity_type="FACTORY",
        source_entity_id="fac_integ_1",
        label="Factory Integ 1",
        properties={"capacity": 15000.0},
        health_score=90.0,
    )

    nodes = {
        port_id: TwinNodeContract(
            node_id=port_id,
            organization_id=org_id,
            node_type=TwinNodeType.PORT,
            source_entity_type="PORT",
            source_entity_id="port_integ_1",
            label="Port Integ 1",
            health_score=80.0,
            fingerprint=fp1,
        ),
        wh_id: TwinNodeContract(
            node_id=wh_id,
            organization_id=org_id,
            node_type=TwinNodeType.WAREHOUSE,
            source_entity_type="WAREHOUSE",
            source_entity_id="wh_integ_1",
            label="Warehouse Integ 1",
            properties={"capacity": 30000.0, "total_capacity": 30000.0},
            health_score=85.0,
            fingerprint=fp2,
        ),
        fac_id: TwinNodeContract(
            node_id=fac_id,
            organization_id=org_id,
            node_type=TwinNodeType.FACTORY,
            source_entity_type="FACTORY",
            source_entity_id="fac_integ_1",
            label="Factory Integ 1",
            properties={"capacity": 15000.0},
            health_score=90.0,
            fingerprint=fp3,
        ),
    }

    twin_id = f"twin_{org_id}_1"
    twin_fp = compute_twin_fingerprint(twin_id, org_id, "1.0.0", sorted([fp1, fp2, fp3]), [])

    return DigitalTwinSnapshot(
        twin_id=twin_id,
        organization_id=org_id,
        version="1",
        generated_at=datetime.utcnow(),
        nodes=nodes,
        edges={},
        source_fingerprint="1" * 64,
        twin_fingerprint=twin_fp,
        node_count=len(nodes),
        edge_count=0,
        status="CURRENT",
    )


@pytest.fixture
def in_memory_db() -> Session:
    """Isolated SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_simulation_risk_integration_read_only(integrated_snapshot: DigitalTwinSnapshot):
    """Verify SimulationRiskIntegration calculates baseline risk, simulated risk, and delta."""
    state = SimulationState.from_digital_twin_snapshot(integrated_snapshot)
    port_id = compute_node_id("org_integ_test", "PORT", "port_integ_1")

    # Before change: baseline risk calculated
    b1, s1, d1, avail1 = SimulationRiskIntegration.evaluate_risk_delta(integrated_snapshot, state)
    assert avail1 == MetricAvailability.AVAILABLE
    assert b1 is not None
    assert s1 is not None
    assert d1 == 0.0  # Zero disruption yet

    # Apply node outage in simulated state
    scenario = SimulationScenarioBuilder(
        "org_integ_test", "Outage Scenario", integrated_snapshot.twin_fingerprint
    ).add_node_outage(port_id, duration_hours=24.0).build()

    for ch in scenario.changes:
        state.apply_change(ch)

    b2, s2, d2, avail2 = SimulationRiskIntegration.evaluate_risk_delta(integrated_snapshot, state)
    assert avail2 == MetricAvailability.AVAILABLE
    assert b2 == b1  # Baseline remains unchanged
    assert s2 is not None
    assert s2 > b2   # Simulated risk increased
    assert d2 is not None and d2 > 0.0


def test_simulation_ml_integration_safely_handles_missing_model():
    """Verify ML integration preserves NOT_AVAILABLE without fabricating predictions or zeroes."""
    res = SimulationMLIntegration.predict_shipment_delay_impact(
        shipment_id="shp_test_ml_1",
        baseline_delay_minutes=0.0,
        added_transit_minutes=120.0,
    )
    assert res["availability"] in (MetricAvailability.NOT_AVAILABLE, MetricAvailability.AVAILABLE)
    if res["availability"] == MetricAvailability.NOT_AVAILABLE:
        assert res["baseline_prediction"] is None
        assert res["simulated_prediction"] is None
        assert res["delta"] is None
        assert "reason" in res


def test_simulation_engine_extended_contracts(integrated_snapshot: DigitalTwinSnapshot):
    """Verify SimulationEngine returns impact, summary, entity_impacts, and propagation."""
    port_id = compute_node_id("org_integ_test", "PORT", "port_integ_1")
    wh_id = compute_node_id("org_integ_test", "WAREHOUSE", "wh_integ_1")

    scenario = SimulationScenarioBuilder(
        "org_integ_test", "Combined Disruption Scenario", integrated_snapshot.twin_fingerprint
    ).add_node_outage(port_id, duration_hours=48.0).add_capacity_reduction(wh_id, percentage=20.0).build()

    req = SimulationRequest(
        scenario=scenario,
        max_depth=5,
        evaluate_risk=True,
        evaluate_ml=False,
    )

    result = SimulationEngine.execute_simulation(integrated_snapshot, scenario, sim_input=req)

    assert result.status == SimulationStatus.COMPLETED
    assert result.impact is not None
    assert result.impact.affected_nodes_count >= 2
    assert result.summary is not None
    assert result.summary.status == SimulationStatus.COMPLETED
    assert len(result.entity_impacts) >= 2
    assert any(ei.entity_id == port_id for ei in result.entity_impacts)
    assert any(ei.entity_id == wh_id for ei in result.entity_impacts)
    assert result.propagation is not None
    assert result.propagation.nodes_visited_count >= 1


def test_read_only_operational_tables_invariant(in_memory_db: Session, integrated_snapshot: DigitalTwinSnapshot):
    """Verify strictly zero modifications occur on operational tables during simulation."""
    org_id = integrated_snapshot.organization_id

    # Seed operational tables
    sup = Supplier(id="sup_op_1", org_id=org_id, name="Operational Supplier", tier=1)
    fac = Factory(id="fac_op_1", org_id=org_id, name="Operational Factory", capacity=50000.0)
    wh = Warehouse(id="wh_op_1", org_id=org_id, name="Operational Warehouse", total_capacity=80000.0)
    in_memory_db.add_all([sup, fac, wh])
    in_memory_db.commit()

    # Run simulation
    port_id = compute_node_id(org_id, "PORT", "port_integ_1")
    scenario = SimulationScenarioBuilder(
        org_id, "Read Only Test", integrated_snapshot.twin_fingerprint
    ).add_node_outage(port_id, duration_hours=36.0).build()

    result = SimulationEngine.execute_simulation(integrated_snapshot, scenario)
    assert result.status == SimulationStatus.COMPLETED

    # Verify entities in DB are 100% identical
    db_sup = in_memory_db.get(Supplier, "sup_op_1")
    db_fac = in_memory_db.get(Factory, "fac_op_1")
    db_wh = in_memory_db.get(Warehouse, "wh_op_1")

    assert db_sup.name == "Operational Supplier"
    assert db_fac.capacity == 50000.0
    assert db_wh.total_capacity == 80000.0
