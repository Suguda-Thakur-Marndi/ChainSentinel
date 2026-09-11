"""Extended contract and module tests for RiskWise Phase 13 Simulation Subsystem."""
from __future__ import annotations

from datetime import datetime
import pytest

from app.digital_twin.contracts import DigitalTwinSnapshot, TwinNodeType
from app.digital_twin.fingerprints import compute_node_fingerprint, compute_node_id
from app.simulation.config import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_EFFECTS,
    DEFAULT_MAX_NODES,
    HARD_MAX_DEPTH,
    HARD_MAX_EDGES,
    HARD_MAX_EFFECTS,
    HARD_MAX_NODES,
    MAX_SCENARIO_CHANGES,
    SIMULATION_ENGINE_VERSION,
    SOURCE_TYPE_SIMULATED,
    SimulationConfig,
)
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationEntityImpact,
    SimulationErrorContract,
    SimulationImpact,
    SimulationInput,
    SimulationMetric,
    SimulationOutcome,
    SimulationPropagation,
    SimulationProvenance,
    SimulationRequest,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
    SimulationSummary,
)
from app.simulation.errors import (
    SimulationError,
    SimulationPersistenceError,
    SimulationPropagationError,
    SimulationResourceLimitError,
    SimulationStateError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.persistence import SimulationRepository
from app.simulation.scenarios import SimulationScenarioBuilder
from app.simulation.validators import SimulationValidator


@pytest.fixture
def minimal_snapshot() -> DigitalTwinSnapshot:
    """Fixture creating a minimal 2-node digital twin snapshot."""
    org_id = "org_ext_test"
    port_id = compute_node_id(org_id, "PORT", "port_ext_1")
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_ext_1")

    fp1 = compute_node_fingerprint(
        node_id=port_id,
        organization_id=org_id,
        node_type="PORT",
        source_entity_type="PORT",
        source_entity_id="port_ext_1",
        label="Port Ext 1",
    )
    fp2 = compute_node_fingerprint(
        node_id=wh_id,
        organization_id=org_id,
        node_type="WAREHOUSE",
        source_entity_type="WAREHOUSE",
        source_entity_id="wh_ext_1",
        label="Warehouse Ext 1",
        properties={"capacity": 25000.0, "total_capacity": 25000.0},
    )

    from app.digital_twin.contracts import TwinNodeContract
    nodes = {
        port_id: TwinNodeContract(
            node_id=port_id,
            organization_id=org_id,
            node_type=TwinNodeType.PORT,
            source_entity_type="PORT",
            source_entity_id="port_ext_1",
            label="Port Ext 1",
            fingerprint=fp1,
        ),
        wh_id: TwinNodeContract(
            node_id=wh_id,
            organization_id=org_id,
            node_type=TwinNodeType.WAREHOUSE,
            source_entity_type="WAREHOUSE",
            source_entity_id="wh_ext_1",
            label="Warehouse Ext 1",
            properties={"capacity": 25000.0, "total_capacity": 25000.0},
            fingerprint=fp2,
        ),
    }

    from app.digital_twin.fingerprints import compute_twin_fingerprint
    twin_id = f"twin_{org_id}_1"
    twin_fp = compute_twin_fingerprint(twin_id, org_id, "1.0.0", sorted([fp1, fp2]), [])

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


def test_simulation_config_constants():
    """Verify configuration defaults and hard boundary constants."""
    config = SimulationConfig()
    assert config.max_depth == DEFAULT_MAX_DEPTH == 5
    assert config.max_nodes == DEFAULT_MAX_NODES == 200
    assert config.max_edges == DEFAULT_MAX_EDGES == 500
    assert config.max_effects == DEFAULT_MAX_EFFECTS == 100
    assert config.max_scenario_changes == MAX_SCENARIO_CHANGES == 50
    assert HARD_MAX_DEPTH == 10
    assert HARD_MAX_NODES == 1000
    assert HARD_MAX_EDGES == 2000
    assert HARD_MAX_EFFECTS == 500
    assert config.source_type == SOURCE_TYPE_SIMULATED == "SIMULATED"
    assert config.engine_version == SIMULATION_ENGINE_VERSION == "13.0.0"


def test_simulation_request_contract():
    """Verify SimulationRequest initializes and serializes deterministically."""
    req = SimulationRequest(
        scenario_id="sc_req_01",
        max_depth=4,
        max_nodes=150,
        max_edges=300,
        max_effects=50,
        evaluate_risk=True,
        evaluate_ml=False,
    )
    assert req.scenario_id == "sc_req_01"
    assert req.max_depth == 4
    assert req.evaluate_risk is True
    assert req.evaluate_ml is False

    dumped = req.model_dump()
    assert dumped["scenario_id"] == "sc_req_01"
    assert dumped["max_depth"] == 4


def test_simulation_entity_impact_contract():
    """Verify SimulationEntityImpact captures granular operational disruptions."""
    impact = SimulationEntityImpact(
        entity_id="node_123",
        entity_type="WAREHOUSE",
        impact_type="CAPACITY_REDUCTION",
        is_direct=True,
        effective_delay_minutes=120.0,
        capacity_lost=5000.0,
        is_available=True,
        propagation_depth=1,
        simulated_tags=["CAPACITY_REDUCED", "DELAYED"],
    )
    assert impact.entity_id == "node_123"
    assert impact.effective_delay_minutes == 120.0
    assert impact.capacity_lost == 5000.0
    assert impact.is_available is True
    assert "CAPACITY_REDUCED" in impact.simulated_tags


def test_simulation_propagation_contract():
    """Verify SimulationPropagation trace summary structure."""
    prop = SimulationPropagation(
        origin_nodes=["node_origin_1"],
        max_depth_reached=3,
        nodes_visited_count=12,
        edges_traversed_count=15,
        effects_generated_count=8,
        propagation_paths=[["node_origin_1", "edge_1", "node_dest_2"]],
    )
    assert prop.origin_nodes == ["node_origin_1"]
    assert prop.max_depth_reached == 3
    assert prop.nodes_visited_count == 12
    assert len(prop.propagation_paths) == 1


def test_simulation_summary_contract():
    """Verify SimulationSummary structure."""
    summary = SimulationSummary(
        simulation_id="sim_sum_01",
        scenario_id="sc_sum_01",
        organization_id="org_ext_test",
        status=SimulationStatus.COMPLETED,
        severity="MEDIUM",
        affected_nodes_count=3,
        affected_edges_count=2,
        affected_shipments_count=1,
        total_added_delay_minutes=180.0,
        risk_delta=12.5,
        execution_duration_ms=45.2,
        simulation_fingerprint="f" * 64,
    )
    assert summary.simulation_id == "sim_sum_01"
    assert summary.status == SimulationStatus.COMPLETED
    assert summary.severity == "MEDIUM"
    assert summary.risk_delta == 12.5


def test_simulation_error_contract():
    """Verify SimulationErrorContract serializes typed errors."""
    err = SimulationErrorContract(
        error_code="SIMULATION_VALIDATION_ERROR",
        message="Target entity 'invalid_id' not found in snapshot",
        details={"entity_id": "invalid_id"},
    )
    assert err.error_code == "SIMULATION_VALIDATION_ERROR"
    assert "invalid_id" in err.message


def test_delay_increase_change_type(minimal_snapshot: DigitalTwinSnapshot):
    """Verify SimulationChangeType.DELAY_INCREASE is supported and validated."""
    port_id = compute_node_id("org_ext_test", "PORT", "port_ext_1")
    ch = SimulationChange(
        change_id="ch_delay_inc",
        change_type=SimulationChangeType.DELAY_INCREASE,
        target_entity_type="PORT",
        target_entity_id=port_id,
        magnitude=48.0,
        unit=SimulationChangeUnit.HOURS,
    )
    assert ch.change_type == SimulationChangeType.DELAY_INCREASE
    # Validation against snapshot passes
    SimulationValidator.validate_change(ch, minimal_snapshot)

    # Negative magnitude is rejected
    ch_neg = SimulationChange(
        change_id="ch_delay_neg",
        change_type=SimulationChangeType.DELAY_INCREASE,
        target_entity_type="PORT",
        target_entity_id=port_id,
        magnitude=-5.0,
        unit=SimulationChangeUnit.HOURS,
    )
    with pytest.raises(SimulationValidationError, match="cannot be negative"):
        SimulationValidator.validate_change(ch_neg, minimal_snapshot)


def test_module_re_exports():
    """Verify validators, scenarios, and persistence module re-exports function identically."""
    from app.simulation.validators import SimulationValidator as V1
    from app.simulation.validation import SimulationValidator as V2
    assert V1 is V2

    from app.simulation.scenarios import SimulationScenarioBuilder as S1
    from app.simulation.scenario import SimulationScenarioBuilder as S2
    assert S1 is S2

    from app.simulation.persistence import SimulationRepository as R1
    from app.simulation.repository import SimulationRepository as R2
    assert R1 is R2
