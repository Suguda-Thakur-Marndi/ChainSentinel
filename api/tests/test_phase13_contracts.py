"""Unit tests for RiskWise Phase 13 Simulation Engine contracts, validation, and fingerprints."""
from __future__ import annotations

from datetime import datetime, timedelta
import pytest
from pydantic import ValidationError

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
    TwinNodeType,
    TwinEdgeType,
)
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
)
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationEffect,
    SimulationInput,
    SimulationMetric,
    SimulationOutcome,
    SimulationProvenance,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.errors import (
    SimulationResourceLimitError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.fingerprints import (
    compute_change_fingerprint,
    compute_change_id,
    compute_effect_id,
    compute_scenario_fingerprint,
    compute_scenario_id,
    compute_simulation_fingerprint,
    compute_simulation_id,
)
from app.simulation.scenario import SimulationScenarioBuilder
from app.simulation.validation import SimulationValidator


# ------------------------------------------------------------------------------
# Test Fixtures
# ------------------------------------------------------------------------------

@pytest.fixture
def sample_snapshot() -> DigitalTwinSnapshot:
    """Create a valid mock Digital Twin snapshot for testing."""
    org_id = "org_test_123"
    n1_id = compute_node_id(org_id, "PORT", "port_01")
    n2_id = compute_node_id(org_id, "WAREHOUSE", "wh_01")

    fp_n1 = compute_node_fingerprint(
        node_id=n1_id,
        organization_id=org_id,
        node_type="PORT",
        source_entity_type="PORT",
        source_entity_id="port_01",
        label="Kaohsiung Port",
    )
    node1 = TwinNodeContract(
        node_id=n1_id,
        organization_id=org_id,
        node_type=TwinNodeType.PORT,
        source_entity_type="PORT",
        source_entity_id="port_01",
        label="Kaohsiung Port",
        fingerprint=fp_n1,
    )

    fp_n2 = compute_node_fingerprint(
        node_id=n2_id,
        organization_id=org_id,
        node_type="WAREHOUSE",
        source_entity_type="WAREHOUSE",
        source_entity_id="wh_01",
        label="Taipei Central Warehouse",
        properties={"capacity": 50000.0, "total_capacity": 50000.0},
    )
    node2 = TwinNodeContract(
        node_id=n2_id,
        organization_id=org_id,
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="wh_01",
        label="Taipei Central Warehouse",
        properties={"capacity": 50000.0, "total_capacity": 50000.0},
        fingerprint=fp_n2,
    )

    e1_id = compute_edge_id(org_id, n1_id, n2_id, "TRANSPORT", "route_01")
    fp_e1 = compute_edge_fingerprint(
        edge_id=e1_id,
        organization_id=org_id,
        from_node_id=n1_id,
        to_node_id=n2_id,
        edge_type="TRANSPORT",
        source_reference="route_01",
    )
    edge1 = TwinEdgeContract(
        edge_id=e1_id,
        organization_id=org_id,
        from_node_id=n1_id,
        to_node_id=n2_id,
        edge_type=TwinEdgeType.TRANSPORT,
        source_reference="route_01",
        fingerprint=fp_e1,
    )

    nodes = {n1_id: node1, n2_id: node2}
    edges = {e1_id: edge1}

    return DigitalTwinSnapshot(
        twin_id=f"twin-{org_id}",
        organization_id=org_id,
        version="1",
        generated_at=datetime.utcnow(),
        nodes=nodes,
        edges=edges,
        source_fingerprint="1" * 64,
        twin_fingerprint="2" * 64,
        node_count=2,
        edge_count=1,
        status="CURRENT",
    )


# ------------------------------------------------------------------------------
# Contract Tests
# ------------------------------------------------------------------------------

def test_change_contract_immutability():
    """Verify SimulationChange is immutable and forbids extra fields."""
    ch = SimulationChange(
        change_id="ch_1",
        change_type=SimulationChangeType.NODE_UNAVAILABLE,
        target_entity_type="PORT",
        target_entity_id="port_01",
        magnitude=72.0,
        unit=SimulationChangeUnit.HOURS,
    )
    with pytest.raises(ValidationError):
        ch.magnitude = 48.0  # Frozen


def test_change_contract_source_type_simulated():
    """Verify source_type must strictly be 'SIMULATED'."""
    with pytest.raises(ValidationError):
        SimulationChange(
            change_id="ch_1",
            change_type=SimulationChangeType.NODE_UNAVAILABLE,
            target_entity_type="PORT",
            target_entity_id="port_01",
            magnitude=72.0,
            unit=SimulationChangeUnit.HOURS,
            source_type="REAL",  # Must be SIMULATED
        )


def test_scenario_builder_fluent():
    """Verify SimulationScenarioBuilder constructs valid fingerprinted scenario."""
    builder = SimulationScenarioBuilder(
        organization_id="org_test_123",
        name="Port Outage Scenario",
        base_snapshot_fingerprint="2" * 64,
    )
    builder.with_description("Simulate 72h port outage")
    builder.add_node_outage("port_01", duration_hours=72.0)
    scenario = builder.build()

    assert scenario.organization_id == "org_test_123"
    assert scenario.name == "Port Outage Scenario"
    assert len(scenario.changes) == 1
    assert len(scenario.fingerprint) == 64
    assert scenario.changes[0].change_type == SimulationChangeType.NODE_UNAVAILABLE


def test_deterministic_fingerprints_repeatable():
    """Verify fingerprinting identical scenarios produces identical hashes."""
    b1 = SimulationScenarioBuilder("org_1", "Scenario Alpha", "a" * 64).add_delay("sh_1", delay_hours=12.0)
    b2 = SimulationScenarioBuilder("org_1", "Scenario Alpha", "a" * 64).add_delay("sh_1", delay_hours=12.0)
    s1 = b1.build()
    s2 = b2.build()

    assert s1.scenario_id == s2.scenario_id
    assert s1.fingerprint == s2.fingerprint


def test_deterministic_fingerprints_change_with_magnitude():
    """Verify changing change magnitude changes the scenario fingerprint."""
    s1 = SimulationScenarioBuilder("org_1", "Scenario Alpha", "a" * 64).add_delay("sh_1", delay_hours=12.0).build()
    s2 = SimulationScenarioBuilder("org_1", "Scenario Alpha", "a" * 64).add_delay("sh_1", delay_hours=24.0).build()

    assert s1.fingerprint != s2.fingerprint


# ------------------------------------------------------------------------------
# Validation Tests
# ------------------------------------------------------------------------------

def test_validation_tenant_mismatch_rejected(sample_snapshot: DigitalTwinSnapshot):
    """Verify scenario from org_other is rejected against snapshot from org_test_123."""
    scenario = SimulationScenarioBuilder(
        organization_id="org_hostile",
        name="Attacker Scenario",
        base_snapshot_fingerprint=sample_snapshot.twin_fingerprint,
    ).build()

    with pytest.raises(SimulationTenantIsolationError):
        SimulationValidator.validate_scenario(scenario, sample_snapshot)


def test_validation_fingerprint_mismatch_rejected(sample_snapshot: DigitalTwinSnapshot):
    """Verify scenario specifying wrong snapshot fingerprint is rejected."""
    scenario = SimulationScenarioBuilder(
        organization_id=sample_snapshot.organization_id,
        name="Stale Scenario",
        base_snapshot_fingerprint="f" * 64,  # Does not match sample_snapshot
    ).build()

    with pytest.raises(SimulationValidationError, match="Base snapshot fingerprint mismatch"):
        SimulationValidator.validate_scenario(scenario, sample_snapshot)


def test_validation_nonexistent_entity_rejected(sample_snapshot: DigitalTwinSnapshot):
    """Verify change targeting nonexistent node is rejected."""
    scenario = SimulationScenarioBuilder(
        organization_id=sample_snapshot.organization_id,
        name="Missing Target Scenario",
        base_snapshot_fingerprint=sample_snapshot.twin_fingerprint,
    ).add_node_outage("nonexistent_node_xyz", duration_hours=24.0).build()

    with pytest.raises(SimulationValidationError, match="does not exist in base Digital Twin snapshot"):
        SimulationValidator.validate_scenario(scenario, sample_snapshot)


def test_validation_negative_delay_rejected(sample_snapshot: DigitalTwinSnapshot):
    """Verify negative delay magnitude is rejected."""
    ch = SimulationChange(
        change_id="ch_neg",
        change_type=SimulationChangeType.DELAY,
        target_entity_type="PORT",
        target_entity_id="port_01",
        magnitude=-10.0,
        unit=SimulationChangeUnit.HOURS,
    )
    with pytest.raises(SimulationValidationError, match="cannot be negative"):
        SimulationValidator.validate_change(ch, sample_snapshot)


def test_validation_capacity_reduction_percent_bounds(sample_snapshot: DigitalTwinSnapshot):
    """Verify capacity reduction percent cannot exceed 100%."""
    ch = SimulationChange(
        change_id="ch_over",
        change_type=SimulationChangeType.CAPACITY_REDUCTION,
        target_entity_type="WAREHOUSE",
        target_entity_id="wh_01",
        magnitude=150.0,  # > 100%
        unit=SimulationChangeUnit.PERCENT,
    )
    with pytest.raises(SimulationValidationError, match="must be between 0.0 and 100.0"):
        SimulationValidator.validate_change(ch, sample_snapshot)


def test_validation_conflicting_changes_rejected(sample_snapshot: DigitalTwinSnapshot):
    """Verify conflicting changes on same entity are rejected."""
    ch1 = SimulationChange(
        change_id="ch_1",
        change_type=SimulationChangeType.CAPACITY_REDUCTION,
        target_entity_type="WAREHOUSE",
        target_entity_id="wh_01",
        magnitude=30.0,
        unit=SimulationChangeUnit.PERCENT,
    )
    ch2 = SimulationChange(
        change_id="ch_2",
        change_type=SimulationChangeType.CAPACITY_INCREASE,
        target_entity_type="WAREHOUSE",
        target_entity_id="wh_01",
        magnitude=20.0,
        unit=SimulationChangeUnit.PERCENT,
    )
    scenario = SimulationScenario(
        scenario_id="sc_conflict",
        organization_id=sample_snapshot.organization_id,
        name="Conflicting Scenario",
        base_snapshot_fingerprint=sample_snapshot.twin_fingerprint,
        changes=[ch1, ch2],
        fingerprint="0" * 64,
    )
    with pytest.raises(SimulationValidationError, match="Conflicting mutually exclusive changes"):
        SimulationValidator.validate_scenario(scenario, sample_snapshot)


def test_validation_resource_limits_enforced():
    """Verify exceeding hard traversal bounds raises ValidationError or SimulationResourceLimitError."""
    with pytest.raises(ValidationError):
        SimulationInput(
            scenario=SimulationScenario(
                scenario_id="s1",
                organization_id="org1",
                name="Test",
                base_snapshot_fingerprint="0" * 64,
                fingerprint="0" * 64,
            ),
            max_depth=99,  # Exceeds HARD_MAX_DEPTH=10
        )
