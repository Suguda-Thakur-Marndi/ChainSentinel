"""Unit and integration tests for RiskWise Phase 13 simulation persistence and scenario comparison."""
from __future__ import annotations

from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.contracts import DigitalTwinSnapshot
from app.models.simulation import Scenario, Simulation
from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationComparison,
    SimulationOutcome,
    SimulationProvenance,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.errors import (
    SimulationPersistenceError,
    SimulationTenantIsolationError,
)
from app.simulation.repository import SimulationRepository
from app.simulation.scenario import SimulationScenarioBuilder
from app.simulation.service import SimulationService


@pytest.fixture(scope="function")
def db_session():
    """Create isolated in-memory SQLite session with simulation tables."""
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


@pytest.fixture
def mock_scenario() -> SimulationScenario:
    return SimulationScenarioBuilder(
        organization_id="org_alpha",
        name="Alpha Port Outage",
        base_snapshot_fingerprint="a" * 64,
    ).add_node_outage("port_alpha_1", duration_hours=48.0).build()


def test_repository_save_and_get_scenario(db_session: Session, mock_scenario: SimulationScenario):
    """Verify saving and retrieving a scenario preserves contracts and fields."""
    repo = SimulationRepository(db_session, "org_alpha")
    record = repo.save_scenario(mock_scenario, user_id="user_test")
    db_session.commit()

    assert record.id == mock_scenario.scenario_id
    assert record.name == "Alpha Port Outage"

    retrieved = repo.get_scenario(mock_scenario.scenario_id)
    assert retrieved is not None
    assert retrieved.scenario_id == mock_scenario.scenario_id
    assert retrieved.organization_id == "org_alpha"
    assert len(retrieved.changes) == 1
    assert retrieved.changes[0].change_type == SimulationChangeType.NODE_UNAVAILABLE


def test_repository_tenant_isolation_scenario(db_session: Session, mock_scenario: SimulationScenario):
    """Verify Org Beta cannot access Org Alpha's scenario."""
    repo_alpha = SimulationRepository(db_session, "org_alpha")
    repo_alpha.save_scenario(mock_scenario)
    db_session.commit()

    repo_beta = SimulationRepository(db_session, "org_beta")

    # Attempt cross-tenant get
    with pytest.raises(SimulationTenantIsolationError):
        repo_beta.get_scenario(mock_scenario.scenario_id)

    # Attempt cross-tenant save
    with pytest.raises(SimulationTenantIsolationError):
        repo_beta.save_scenario(mock_scenario)


def test_repository_list_scenarios_scoped_by_tenant(db_session: Session):
    """Verify list_scenarios returns only the authenticated tenant's scenarios."""
    repo_alpha = SimulationRepository(db_session, "org_alpha")
    repo_beta = SimulationRepository(db_session, "org_beta")

    s_a1 = SimulationScenarioBuilder("org_alpha", "Scenario A1", "a" * 64).build()
    s_a2 = SimulationScenarioBuilder("org_alpha", "Scenario A2", "a" * 64).build()
    s_b1 = SimulationScenarioBuilder("org_beta", "Scenario B1", "b" * 64).build()

    repo_alpha.save_scenario(s_a1)
    repo_alpha.save_scenario(s_a2)
    repo_beta.save_scenario(s_b1)
    db_session.commit()

    scenarios_alpha = repo_alpha.list_scenarios()
    scenarios_beta = repo_beta.list_scenarios()

    assert len(scenarios_alpha) == 2
    assert len(scenarios_beta) == 1
    assert all(s.organization_id == "org_alpha" for s in scenarios_alpha)
    assert all(s.organization_id == "org_beta" for s in scenarios_beta)


def test_repository_save_and_get_simulation_result(db_session: Session, mock_scenario: SimulationScenario):
    """Verify persisting and retrieving a SimulationResult."""
    repo = SimulationRepository(db_session, "org_alpha")
    repo.save_scenario(mock_scenario)
    db_session.commit()

    outcome = SimulationOutcome(
        affected_nodes_count=2,
        affected_edges_count=1,
        total_added_delay_minutes=120.0,
        severity="HIGH",
    )
    prov = SimulationProvenance(
        base_snapshot_fingerprint="a" * 64,
        organization_id="org_alpha",
    )
    result = SimulationResult(
        simulation_id="sim_alpha_01",
        scenario_id=mock_scenario.scenario_id,
        organization_id="org_alpha",
        base_snapshot_fingerprint="a" * 64,
        simulation_fingerprint="f" * 64,
        status=SimulationStatus.COMPLETED,
        outcome=outcome,
        changes=list(mock_scenario.changes),
        effects=[],
        metrics={},
        provenance=prov,
        executed_at=datetime.utcnow(),
        execution_duration_ms=45.2,
    )

    repo.save_simulation_result(result)
    db_session.commit()

    retrieved = repo.get_simulation_result("sim_alpha_01")
    assert retrieved is not None
    assert retrieved.simulation_id == "sim_alpha_01"
    assert retrieved.status == SimulationStatus.COMPLETED
    assert retrieved.outcome.severity == "HIGH"
    assert retrieved.outcome.total_added_delay_minutes == 120.0


def test_repository_simulation_result_tenant_isolation(db_session: Session, mock_scenario: SimulationScenario):
    """Verify Org Beta cannot access Org Alpha's simulation results."""
    repo_alpha = SimulationRepository(db_session, "org_alpha")
    repo_alpha.save_scenario(mock_scenario)

    result = SimulationResult(
        simulation_id="sim_alpha_02",
        scenario_id=mock_scenario.scenario_id,
        organization_id="org_alpha",
        base_snapshot_fingerprint="a" * 64,
        simulation_fingerprint="f" * 64,
        status=SimulationStatus.COMPLETED,
        outcome=SimulationOutcome(),
        changes=[],
        effects=[],
        metrics={},
        provenance=SimulationProvenance(base_snapshot_fingerprint="a" * 64, organization_id="org_alpha"),
    )
    repo_alpha.save_simulation_result(result)
    db_session.commit()

    repo_beta = SimulationRepository(db_session, "org_beta")
    with pytest.raises(SimulationTenantIsolationError):
        repo_beta.get_simulation_result("sim_alpha_02")


def test_scenario_comparison_service(db_session: Session):
    """Verify SimulationService.compare_scenarios calculates metric differences."""
    # Create simple mock snapshot with warehouse
    from app.digital_twin.contracts import TwinNodeContract, TwinNodeType
    from app.digital_twin.fingerprints import compute_node_fingerprint, compute_node_id

    org_id = "org_compare"
    wh_id = compute_node_id(org_id, "WAREHOUSE", "wh_c1")
    node = TwinNodeContract(
        node_id=wh_id,
        organization_id=org_id,
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="wh_c1",
        label="Test WH",
        status="OPERATIONAL",
        properties={"delay_minutes": 0.0},
        fingerprint=compute_node_fingerprint(wh_id, org_id, "WAREHOUSE", "WAREHOUSE", "wh_c1", "Test WH"),
    )
    snapshot = DigitalTwinSnapshot(
        twin_id=f"twin-{org_id}",
        organization_id=org_id,
        version="1",
        generated_at=datetime.utcnow(),
        nodes={wh_id: node},
        edges={},
        source_fingerprint="1" * 64,
        twin_fingerprint="2" * 64,
        node_count=1,
        edge_count=0,
        status="CURRENT",
    )

    s1 = SimulationScenarioBuilder(org_id, "Scenario Minor Delay", snapshot.twin_fingerprint).add_delay(wh_id, delay_hours=2.0).build()
    s2 = SimulationScenarioBuilder(org_id, "Scenario Major Delay", snapshot.twin_fingerprint).add_delay(wh_id, delay_hours=10.0).build()

    SimulationService.create_scenario(db_session, org_id, s1)
    SimulationService.create_scenario(db_session, org_id, s2)
    db_session.commit()

    comp = SimulationService.compare_scenarios(
        db=db_session,
        organization_id=org_id,
        scenario_a_id=s1.scenario_id,
        scenario_b_id=s2.scenario_id,
        snapshot=snapshot,
    )

    assert comp.organization_id == org_id
    assert comp.scenario_a_id == s1.scenario_id
    assert comp.scenario_b_id == s2.scenario_id
    assert "total_delay_minutes" in comp.metric_comparisons
    delay_comp = comp.metric_comparisons["total_delay_minutes"]
    assert delay_comp["scenario_a"] == 120.0  # 2h = 120m
    assert delay_comp["scenario_b"] == 600.0  # 10h = 600m
    assert delay_comp["difference_b_minus_a"] == 480.0
    assert len(comp.summary_findings) >= 1
