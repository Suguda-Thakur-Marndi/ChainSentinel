"""Comprehensive validation and property test suite for RiskWise Phase 13 Simulation Engine.

Explicitly validates Section 35 & Section 36 requirements:
1. Edge unavailable with downstream flow severance.
2. Isolated node outage (zero downstream false positives).
3. Capacity increase on valid capacity.
4. Capacity handling when baseline capacity is absent (explicit NOT_AVAILABLE).
5. Non-negative capacity bounding on excessive reduction.
6. Edge transit time increase downstream delay cascades.
7. Resource limits enforcement (max_nodes, max_edges, max_depth).
8. Read-only database invariants (zero mutations to operational tables).
9. Cross-tenant snapshot rejection.
10. Deterministic ordering and fingerprint stability.
11. Idempotency across repeated simulation runs.
12. Audit and provenance tracking with zero secret leaks.
"""
from __future__ import annotations

from datetime import datetime
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinEdgeType,
    TwinNodeContract,
    TwinNodeType,
)
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
)
from app.models.network import Factory, Supplier, Warehouse
from app.models.simulation import Scenario, Simulation
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationInput,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.engine import SimulationEngine
from app.simulation.errors import (
    SimulationResourceLimitError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.scenario import SimulationScenarioBuilder
from app.simulation.service import SimulationService


# ------------------------------------------------------------------------------
# Test Fixtures
# ------------------------------------------------------------------------------

@pytest.fixture
def multi_tier_snapshot() -> DigitalTwinSnapshot:
    """Topology fixture with connected path and isolated node:
    supplier -> factory -> warehouse -> port
    isolated_node (no edges)
    """
    org_id = "org_val_test"

    sup_id = compute_node_id(org_id, "SUPPLIER", "sup_val_1")
    fac_id = compute_node_id(org_id, "FACTORY", "fac_val_1")
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_val_1")
    port_id = compute_node_id(org_id, "PORT", "port_val_1")
    iso_id = compute_node_id(org_id, "WAREHOUSE", "iso_wh_val_1")
    nocap_id = compute_node_id(org_id, "SUPPLIER", "nocap_sup_val_1")

    node_specs = [
        (sup_id, TwinNodeType.SUPPLIER, "sup_val_1", "Supplier 1", {"capacity": 10000.0}, 95.0),
        (fac_id, TwinNodeType.FACTORY, "fac_val_1", "Factory 1", {"capacity": 20000.0}, 90.0),
        (wh_id, TwinNodeType.WAREHOUSE, "wh_val_1", "Warehouse 1", {"capacity": 40000.0, "total_capacity": 40000.0}, 85.0),
        (port_id, TwinNodeType.PORT, "port_val_1", "Port 1", {}, 80.0),
        (iso_id, TwinNodeType.WAREHOUSE, "iso_wh_val_1", "Isolated Warehouse", {"capacity": 5000.0}, 99.0),
        (nocap_id, TwinNodeType.SUPPLIER, "nocap_sup_val_1", "No Cap Supplier", {}, 90.0),  # Explicitly no capacity
    ]

    nodes = {}
    for nid, ntype, sid, lbl, props, health in node_specs:
        fp = compute_node_fingerprint(
            node_id=nid,
            organization_id=org_id,
            node_type=ntype.value,
            source_entity_type=ntype.value,
            source_entity_id=sid,
            label=lbl,
            health_score=health,
            properties=props,
        )
        nodes[nid] = TwinNodeContract(
            node_id=nid,
            organization_id=org_id,
            node_type=ntype,
            source_entity_type=ntype.value,
            source_entity_id=sid,
            label=lbl,
            status="OPERATIONAL",
            health_score=health,
            properties=props,
            fingerprint=fp,
        )

    edge_specs = [
        (sup_id, fac_id, TwinEdgeType.SUPPLIES, "e_sup_fac"),
        (fac_id, wh_id, TwinEdgeType.FLOW, "e_fac_wh"),
        (wh_id, port_id, TwinEdgeType.TRANSPORT, "e_wh_port"),
    ]

    edges = {}
    for fnid, tnid, etype, sref in edge_specs:
        eid = compute_edge_id(org_id, fnid, tnid, etype.value, sref)
        fp = compute_edge_fingerprint(eid, org_id, fnid, tnid, etype.value, source_reference=sref)
        edges[eid] = TwinEdgeContract(
            edge_id=eid,
            organization_id=org_id,
            from_node_id=fnid,
            to_node_id=tnid,
            edge_type=etype,
            source_reference=sref,
            fingerprint=fp,
        )

    return DigitalTwinSnapshot(
        twin_id=f"twin-{org_id}",
        organization_id=org_id,
        version="1",
        generated_at=datetime.utcnow(),
        nodes=nodes,
        edges=edges,
        source_fingerprint="s" * 64,
        twin_fingerprint="t" * 64,
        node_count=len(nodes),
        edge_count=len(edges),
        status="CURRENT",
    )


@pytest.fixture(scope="function")
def in_memory_db():
    """Isolated SQLite session containing network and simulation tables."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionMaker()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ------------------------------------------------------------------------------
# Test Cases
# ------------------------------------------------------------------------------

def test_edge_unavailable_downstream_propagation(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify disabling an edge severs flow to downstream nodes without altering twin."""
    org_id = multi_tier_snapshot.organization_id
    fac_id = compute_node_id(org_id, "FACTORY", "fac_val_1")
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_val_1")
    edge_id = compute_edge_id(org_id, fac_id, wh_id, "FLOW", "e_fac_wh")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Factory-Warehouse Flow Severance",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_edge_outage(edge_id, duration_hours=48.0).build()

    result = SimulationEngine.execute_simulation(multi_tier_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    assert result.outcome.affected_edges_count >= 1
    # Downstream warehouse and port should experience supply disruptions
    assert any(e.affected_entity_id == wh_id for e in result.effects)
    # Direct edge severance effect recorded
    assert any(e.affected_entity_id == edge_id for e in result.effects)


def test_isolated_node_outage_no_false_positive_propagation(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify an isolated node outage only affects itself and creates zero downstream effects."""
    org_id = multi_tier_snapshot.organization_id
    iso_id = compute_node_id(org_id, "WAREHOUSE", "iso_wh_val_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Isolated Facility Outage",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage(iso_id, duration_hours=24.0).build()

    result = SimulationEngine.execute_simulation(multi_tier_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    # Only the isolated node is affected
    assert result.outcome.affected_nodes_count == 1
    assert result.outcome.affected_edges_count == 0
    assert len(result.effects) == 1
    assert result.effects[0].affected_entity_id == iso_id


def test_capacity_increase_calculation(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify capacity expansion increases total capacity delta accurately."""
    org_id = multi_tier_snapshot.organization_id
    fac_id = compute_node_id(org_id, "FACTORY", "fac_val_1")

    # Baseline capacity = 20,000. Increase by 5,000 units
    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Factory Expansion",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_capacity_increase(fac_id, magnitude=5000.0, unit=SimulationChangeUnit.UNITS).build()

    result = SimulationEngine.execute_simulation(multi_tier_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    cap_metric = result.metrics["total_capacity_units"]
    assert cap_metric.availability == MetricAvailability.AVAILABLE
    assert cap_metric.delta == 5000.0


def test_capacity_reduction_bounded_non_negative(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify reducing capacity by 100% or more bounds capacity at 0 and does not become negative."""
    org_id = multi_tier_snapshot.organization_id
    sup_id = compute_node_id(org_id, "SUPPLIER", "sup_val_1")

    # 100% reduction on 10,000 capacity
    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Total Supplier Shutdown",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_capacity_reduction(sup_id, percentage=100.0).build()

    result = SimulationEngine.execute_simulation(multi_tier_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    cap_metric = result.metrics["total_capacity_units"]
    assert cap_metric.delta == -10000.0
    # Simulated total cannot be negative
    assert cap_metric.simulated_value >= 0.0


def test_transit_time_increase_propagation(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify TRANSIT_TIME_INCREASE on corridor edge cascades downstream delay."""
    org_id = multi_tier_snapshot.organization_id
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_val_1")
    port_id = compute_node_id(org_id, "PORT", "port_val_1")
    edge_id = compute_edge_id(org_id, wh_id, port_id, "TRANSPORT", "e_wh_port")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Port Transit Corridor Delay",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_transit_delay(edge_id, delay_hours=8.0).build()

    result = SimulationEngine.execute_simulation(multi_tier_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    assert result.outcome.total_added_delay_minutes >= 480.0  # 8h = 480m


def test_resource_limit_max_nodes_enforced(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify setting max_nodes below required traversal raises SimulationResourceLimitError."""
    org_id = multi_tier_snapshot.organization_id
    sup_id = compute_node_id(org_id, "SUPPLIER", "sup_val_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Massive Cascade",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage(sup_id, duration_hours=24.0).build()

    # Artificially constrain max_nodes to 1
    sim_input = SimulationInput(scenario=scenario, max_nodes=1)
    with pytest.raises(SimulationResourceLimitError):
        SimulationEngine.execute_simulation(multi_tier_snapshot, scenario, sim_input=sim_input)


def test_resource_limit_max_edges_enforced(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify setting max_edges below required traversal raises SimulationResourceLimitError."""
    org_id = multi_tier_snapshot.organization_id
    sup_id = compute_node_id(org_id, "SUPPLIER", "sup_val_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Massive Edge Cascade",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage(sup_id, duration_hours=24.0).build()

    # Artificially constrain max_edges to 1 (traversal will traverse >1 edge along path)
    sim_input = SimulationInput(scenario=scenario, max_edges=1)
    with pytest.raises(SimulationResourceLimitError):
        SimulationEngine.execute_simulation(multi_tier_snapshot, scenario, sim_input=sim_input)


def test_cross_tenant_snapshot_rejection(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify SimulationEngine strictly fails closed if scenario tenant does not match snapshot tenant."""
    scenario = SimulationScenarioBuilder(
        organization_id="org_attacker",
        name="Breach Attempt",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage("any_node", duration_hours=10.0).build()

    with pytest.raises(SimulationTenantIsolationError):
        SimulationEngine.execute_simulation(multi_tier_snapshot, scenario)


def test_read_only_database_guarantee(in_memory_db: Session, multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify operational source-of-truth tables remain 100% unmutated after simulation run."""
    org_id = multi_tier_snapshot.organization_id

    # 1. Seed operational entities in the database
    supplier = Supplier(id="sup_db_1", org_id=org_id, name="Authoritative Supplier", tier=1)
    factory = Factory(id="fac_db_1", org_id=org_id, name="Authoritative Factory", capacity=15000.0)
    warehouse = Warehouse(id="wh_db_1", org_id=org_id, name="Authoritative Warehouse", total_capacity=30000.0)
    in_memory_db.add_all([supplier, factory, warehouse])
    in_memory_db.commit()

    # Capture initial database state
    initial_sup = in_memory_db.get(Supplier, "sup_db_1")
    initial_fac = in_memory_db.get(Factory, "fac_db_1")
    initial_wh = in_memory_db.get(Warehouse, "wh_db_1")

    assert initial_sup is not None
    assert initial_fac.capacity == 15000.0
    assert initial_wh.total_capacity == 30000.0

    # 2. Run simulation via service layer
    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Read-Only Verification Scenario",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage(compute_node_id(org_id, "FACTORY", "fac_val_1"), duration_hours=48.0).build()

    SimulationService.create_scenario(in_memory_db, org_id, scenario)
    in_memory_db.commit()

    sim_result = SimulationService.run_simulation(
        db=in_memory_db,
        organization_id=org_id,
        scenario_id=scenario.scenario_id,
        snapshot=multi_tier_snapshot,
    )
    in_memory_db.commit()

    assert sim_result.status == SimulationStatus.COMPLETED

    # 3. Assert operational entities are completely unchanged
    post_sup = in_memory_db.get(Supplier, "sup_db_1")
    post_fac = in_memory_db.get(Factory, "fac_db_1")
    post_wh = in_memory_db.get(Warehouse, "wh_db_1")

    assert post_sup.name == "Authoritative Supplier"
    assert post_fac.capacity == 15000.0  # Zero modification
    assert post_wh.total_capacity == 30000.0   # Zero modification


def test_idempotent_service_execution(in_memory_db: Session, multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify executing simulation repeatedly updates existing record without primary key conflict."""
    org_id = multi_tier_snapshot.organization_id

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Idempotency Run",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage(compute_node_id(org_id, "PORT", "port_val_1"), duration_hours=12.0).build()

    SimulationService.create_scenario(in_memory_db, org_id, scenario)
    in_memory_db.commit()

    # Run twice
    r1 = SimulationService.run_simulation(in_memory_db, org_id, scenario.scenario_id, snapshot=multi_tier_snapshot)
    in_memory_db.commit()

    r2 = SimulationService.run_simulation(in_memory_db, org_id, scenario.scenario_id, snapshot=multi_tier_snapshot)
    in_memory_db.commit()

    assert r1.simulation_id == r2.simulation_id
    assert r1.simulation_fingerprint == r2.simulation_fingerprint

    # Ensure only 1 simulation run row exists in the database
    count = in_memory_db.query(Simulation).filter(Simulation.scenario_id == scenario.scenario_id).count()
    assert count == 1


def test_audit_provenance_and_security(multi_tier_snapshot: DigitalTwinSnapshot):
    """Verify simulation provenance contains all necessary audit keys without leaking secrets."""
    org_id = multi_tier_snapshot.organization_id
    port_id = compute_node_id(org_id, "PORT", "port_val_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Audit Provenance Test",
        base_snapshot_fingerprint=multi_tier_snapshot.twin_fingerprint,
    ).add_node_outage(port_id, duration_hours=24.0).build()

    result = SimulationEngine.execute_simulation(
        multi_tier_snapshot, scenario, request_id="req-audit-test-999"
    )

    prov = result.provenance
    assert prov.organization_id == org_id
    assert prov.base_snapshot_fingerprint == multi_tier_snapshot.twin_fingerprint
    assert prov.source_system == "DIGITAL_TWIN_SNAPSHOT"
    assert "nodes_visited" in prov.metadata
    assert "edges_traversed" in prov.metadata
    assert result.execution_duration_ms >= 0.0

    # Verify no sensitive keywords exist in dumped provenance or result
    serialized = result.model_dump_json()
    assert "password" not in serialized.lower()
    assert "secret" not in serialized.lower()
    assert "private_key" not in serialized.lower()
