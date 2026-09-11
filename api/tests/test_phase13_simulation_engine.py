"""Core engine and propagation tests for RiskWise Phase 13 Simulation Engine."""
from __future__ import annotations

from datetime import datetime
import pytest

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
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationInput,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.engine import SimulationEngine
from app.simulation.scenario import SimulationScenarioBuilder
from app.simulation.state import SimulationState


# ------------------------------------------------------------------------------
# Topology Fixtures: Multi-tier Supply Chain Network
# ------------------------------------------------------------------------------

@pytest.fixture
def complex_network_snapshot() -> DigitalTwinSnapshot:
    """Create a multi-tier network:
    Supplier -> Supplier Site -> Port -> Route -> Warehouse -> Factory
    Plus a cycle: Factory -> Warehouse
    """
    org_id = "org_acme"

    # Nodes
    sup_id = compute_node_id(org_id, "SUPPLIER", "sup_1")
    site_id = compute_node_id(org_id, "SUPPLIER_SITE", "site_1")
    port_id = compute_node_id(org_id, "PORT", "port_1")
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_1")
    fac_id = compute_node_id(org_id, "FACTORY", "fac_1")

    node_defs = [
        (sup_id, TwinNodeType.SUPPLIER, "SUPPLIER", "sup_1", "Acme Raw Materials", {}, 95.0),
        (site_id, TwinNodeType.SUPPLIER_SITE, "SUPPLIER_SITE", "site_1", "Acme Refining Facility", {"capacity": 10000.0}, 90.0),
        (port_id, TwinNodeType.PORT, "PORT", "port_1", "Port of Kaohsiung", {}, 85.0),
        (wh_id, TwinNodeType.WAREHOUSE, "WAREHOUSE", "wh_1", "Hub Warehouse", {"capacity": 50000.0, "total_capacity": 50000.0}, 88.0),
        (fac_id, TwinNodeType.FACTORY, "FACTORY", "fac_1", "Assembly Plant", {"capacity": 25000.0}, 92.0),
    ]

    nodes = {}
    for nid, ntype, stype, sid, lbl, props, health in node_defs:
        fp = compute_node_fingerprint(
            node_id=nid,
            organization_id=org_id,
            node_type=ntype.value,
            source_entity_type=stype,
            source_entity_id=sid,
            label=lbl,
            health_score=health,
            properties=props,
        )
        nodes[nid] = TwinNodeContract(
            node_id=nid,
            organization_id=org_id,
            node_type=ntype,
            source_entity_type=stype,
            source_entity_id=sid,
            label=lbl,
            status="OPERATIONAL",
            health_score=health,
            properties=props,
            fingerprint=fp,
        )

    # Edges
    edge_defs = [
        (sup_id, site_id, TwinEdgeType.SUPPLIES, "e_sup_site"),
        (site_id, port_id, TwinEdgeType.FLOW, "e_site_port"),
        (port_id, wh_id, TwinEdgeType.TRANSPORT, "e_port_wh"),
        (wh_id, fac_id, TwinEdgeType.FLOW, "e_wh_fac"),
        (fac_id, wh_id, TwinEdgeType.FLOW, "e_fac_wh_cycle"),  # Intentional feedback loop / cycle
    ]

    edges = {}
    for fnid, tnid, etype, sref in edge_defs:
        eid = compute_edge_id(org_id, fnid, tnid, etype.value, sref)
        fp = compute_edge_fingerprint(
            edge_id=eid,
            organization_id=org_id,
            from_node_id=fnid,
            to_node_id=tnid,
            edge_type=etype.value,
            source_reference=sref,
        )
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


# ------------------------------------------------------------------------------
# Test Cases
# ------------------------------------------------------------------------------

def test_simulation_state_isolation(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify modifying SimulationState does not alter the underlying Digital Twin snapshot."""
    snapshot_before = complex_network_snapshot.model_dump()
    state = SimulationState.from_digital_twin_snapshot(complex_network_snapshot)

    # Mutate simulation state
    target_node = list(state.nodes.values())[0]
    target_node.is_available = False
    target_node.effective_delay_minutes = 500.0

    # Assert underlying snapshot remains completely unaltered
    snapshot_after = complex_network_snapshot.model_dump()
    assert snapshot_before == snapshot_after
    assert complex_network_snapshot.nodes[target_node.node_id].status == "OPERATIONAL"


def test_node_outage_propagation(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify port outage propagates downstream flow severance and inventory exposure."""
    org_id = complex_network_snapshot.organization_id
    port_node_id = compute_node_id(org_id, "PORT", "port_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Port Closure 72h",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_node_outage(port_node_id, target_entity_type="PORT", duration_hours=72.0).build()

    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    assert result.outcome.affected_nodes_count >= 2
    assert len(result.effects) >= 2

    # Check for primary outage effect
    primary_eff = next(e for e in result.effects if e.affected_entity_id == port_node_id)
    assert "DIRECT_NODE_UNAVAILABLE" in primary_eff.effect_type
    assert primary_eff.magnitude == 72.0

    # Check for downstream flow severance
    wh_node_id = compute_node_id(org_id, "WAREHOUSE", "wh_1")
    wh_eff = next(e for e in result.effects if e.affected_entity_id == wh_node_id)
    assert wh_eff.effect_type in ("SUPPLY_FLOW_SEVERED", "INVENTORY_REPLENISHMENT_RISK")


def test_delay_propagation_downstream(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify shipment/corridor delay cascades downstream with non-negative delays."""
    org_id = complex_network_snapshot.organization_id
    port_node_id = compute_node_id(org_id, "PORT", "port_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Port Congestion Delay",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_delay(port_node_id, target_entity_type="PORT", delay_hours=12.0).build()

    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    total_delay_metric = result.metrics["total_delay_minutes"]
    assert total_delay_metric.simulated_value >= 720.0  # 12h = 720m
    assert total_delay_metric.delta >= 720.0


def test_capacity_reduction_impact(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify warehouse capacity reduction calculates capacity impact correctly."""
    org_id = complex_network_snapshot.organization_id
    wh_node_id = compute_node_id(org_id, "WAREHOUSE", "wh_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Warehouse Capacity Squeeze",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_capacity_reduction(wh_node_id, percentage=30.0).build()

    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    cap_metric = result.metrics["total_capacity_units"]
    assert cap_metric.availability == MetricAvailability.AVAILABLE
    # 50,000 * 30% reduction = 15,000 unit reduction
    assert cap_metric.delta == -15000.0


def test_multi_change_scenario(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify multi-change scenario combines node outage and capacity changes deterministically."""
    org_id = complex_network_snapshot.organization_id
    port_node_id = compute_node_id(org_id, "PORT", "port_1")
    wh_node_id = compute_node_id(org_id, "WAREHOUSE", "wh_1")

    scenario = (
        SimulationScenarioBuilder(
            organization_id=org_id,
            name="Compound Disruption",
            base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
        )
        .add_node_outage(port_node_id, duration_hours=48.0)
        .add_capacity_reduction(wh_node_id, percentage=20.0)
        .build()
    )

    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)

    assert result.status == SimulationStatus.COMPLETED
    assert len(result.changes) == 2
    assert result.metrics["total_capacity_units"].delta == -10000.0  # 20% of 50k
    assert result.outcome.affected_nodes_count >= 2


def test_cycle_handling_terminates(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify circular feedback (Warehouse -> Factory -> Warehouse) terminates cleanly without infinite loop."""
    org_id = complex_network_snapshot.organization_id
    wh_node_id = compute_node_id(org_id, "WAREHOUSE", "wh_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Cyclic Disruption Test",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_delay(wh_node_id, target_entity_type="WAREHOUSE", delay_hours=6.0).build()

    sim_input = SimulationInput(scenario=scenario, max_depth=8)
    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario, sim_input=sim_input)

    assert result.status == SimulationStatus.COMPLETED
    # Must finish rapidly without recursion limit or timeout
    assert result.execution_duration_ms > 0.0


def test_bounded_depth_limit(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify propagation stops strictly at max_depth."""
    org_id = complex_network_snapshot.organization_id
    sup_node_id = compute_node_id(org_id, "SUPPLIER", "sup_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Depth Limit Test",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_node_outage(sup_node_id, duration_hours=24.0).build()

    # With max_depth=1, only direct neighbors (site_1) should be visited, not port or warehouse
    sim_input = SimulationInput(scenario=scenario, max_depth=1)
    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario, sim_input=sim_input)

    wh_node_id = compute_node_id(org_id, "WAREHOUSE", "wh_1")
    wh_affected = any(e.affected_entity_id == wh_node_id for e in result.effects)
    assert wh_affected is False  # Beyond max_depth=1


def test_determinism_across_executions(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify repeated execution with identical inputs produces identical fingerprints and metrics."""
    org_id = complex_network_snapshot.organization_id
    port_node_id = compute_node_id(org_id, "PORT", "port_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Deterministic Test",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_node_outage(port_node_id, duration_hours=24.0).build()

    r1 = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)
    r2 = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)

    assert r1.simulation_fingerprint == r2.simulation_fingerprint
    assert r1.simulation_id == r2.simulation_id
    assert r1.outcome.total_added_delay_minutes == r2.outcome.total_added_delay_minutes
    assert len(r1.effects) == len(r2.effects)


def test_read_only_risk_evaluation(complex_network_snapshot: DigitalTwinSnapshot):
    """Verify risk evaluation calculates baseline and simulated delta without mutating DB."""
    org_id = complex_network_snapshot.organization_id
    port_node_id = compute_node_id(org_id, "PORT", "port_1")

    scenario = SimulationScenarioBuilder(
        organization_id=org_id,
        name="Risk Impact Test",
        base_snapshot_fingerprint=complex_network_snapshot.twin_fingerprint,
    ).add_node_outage(port_node_id, duration_hours=48.0).build()

    result = SimulationEngine.execute_simulation(complex_network_snapshot, scenario)

    risk_metric = result.metrics["overall_risk_score"]
    assert risk_metric.availability == MetricAvailability.AVAILABLE
    assert risk_metric.baseline_value is not None
    assert risk_metric.simulated_value is not None
    assert risk_metric.delta > 0.0  # Risk increased due to outage
