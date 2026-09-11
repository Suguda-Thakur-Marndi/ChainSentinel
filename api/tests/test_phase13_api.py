"""REST API integration tests for RiskWise Phase 13 Simulation Engine."""
from __future__ import annotations

from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_authenticated_context
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinNodeContract,
    TwinNodeType,
)
from app.digital_twin.fingerprints import compute_node_fingerprint, compute_node_id
from app.digital_twin.service import DigitalTwinService
from app.main import app
from app.models.network import Supplier, SupplierSite
from app.models.simulation import Scenario, Simulation
from app.simulation.contracts import (
    SimulationChange,
    SimulationChangeType,
    SimulationChangeUnit,
    SimulationScenario,
)
from app.simulation.scenario import SimulationScenarioBuilder


class MockAuthContext:
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        role: str,
        request_id: str = "req-test-p13-api",
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.request_id = request_id


@pytest.fixture(scope="module", autouse=True)
def mount_simulation_routes():
    """Mount Simulation API routes dynamically for this module and cleanly restore afterwards."""
    from app.api.v1.endpoints.simulation import router as sim_router
    orig_routes = list(app.router.routes)
    app.include_router(sim_router, prefix="/api/v1/simulation", tags=["Simulation"])
    app.openapi_schema = None
    yield
    app.router.routes = orig_routes
    app.openapi_schema = None


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Clean up FastAPI dependency overrides after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def db_session():
    """Isolated SQLite in-memory database fixture."""
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


@pytest.fixture(scope="function")
def populated_twin_db(db_session: Session):
    """Seed DB with network data and generate initial Digital Twin snapshots for Org Alpha and Org Beta."""
    sup = Supplier(
        id="sup_api_1",
        org_id="org_test_alpha",
        name="API Test Semiconductor",
        tier="CRITICAL",
        country="TW",
    )
    site = SupplierSite(
        id="site_api_1",
        org_id="org_test_alpha",
        supplier_id="sup_api_1",
        name="Fab API Site 1",
        latitude=24.78,
        longitude=120.99,
    )
    sup_beta = Supplier(
        id="sup_beta_1",
        org_id="org_test_beta",
        name="Beta Logistics",
        tier="HIGH",
        country="AU",
    )
    db_session.add_all([sup, site, sup_beta])
    db_session.commit()

    # Pre-build digital twins
    DigitalTwinService.build_and_persist(db_session, organization_id="org_test_alpha")
    DigitalTwinService.build_and_persist(db_session, organization_id="org_test_beta")
    db_session.commit()

    return db_session


def create_client(db: Session, org_id: str = "org_test_alpha", role: str = "OpsManager") -> TestClient:
    """Create test client with mocked auth context."""
    auth_ctx = MockAuthContext(
        user_id=f"user_{org_id}",
        organization_id=org_id,
        role=role,
    )

    def override_get_db():
        yield db

    def override_get_uow():
        return UnitOfWork(session=db)

    def override_auth_context():
        return auth_ctx

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_uow] = override_get_uow
    app.dependency_overrides[get_authenticated_context] = override_auth_context

    return TestClient(app)


# ------------------------------------------------------------------------------
# Test Cases
# ------------------------------------------------------------------------------

def test_api_unauthenticated_rejected(db_session: Session):
    """Verify unauthenticated requests are rejected."""
    app.dependency_overrides.clear()
    client = TestClient(app)
    resp = client.get("/api/v1/simulation/scenarios")
    assert resp.status_code in (401, 403)


def test_api_create_and_get_scenario(populated_twin_db: Session):
    """Verify POST /scenarios creates scenario and GET /scenarios/{id} retrieves it."""
    client = create_client(populated_twin_db, org_id="org_test_alpha", role="RiskManager")

    snapshot = DigitalTwinService.retrieve_current_twin(populated_twin_db, "org_test_alpha")
    sup_node_id = compute_node_id("org_test_alpha", "SUPPLIER", "sup_api_1")

    scenario_payload = {
        "scenario_id": "sc_test_01",
        "organization_id": "org_test_alpha",
        "name": "Supplier API Delay",
        "description": "Simulate 24h delay",
        "base_snapshot_fingerprint": snapshot.twin_fingerprint,
        "changes": [
            {
                "change_id": "ch_01",
                "change_type": "DELAY",
                "target_entity_type": "SUPPLIER",
                "target_entity_id": sup_node_id,
                "magnitude": 24.0,
                "unit": "HOURS",
                "source_type": "SIMULATED",
            }
        ],
        "parameters": {},
        "fingerprint": "f" * 64,
    }

    resp = client.post("/api/v1/simulation/scenarios", json=scenario_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["scenario_id"] == "sc_test_01"
    assert data["name"] == "Supplier API Delay"

    # Fetch scenario
    resp_get = client.get("/api/v1/simulation/scenarios/sc_test_01")
    assert resp_get.status_code == 200
    assert resp_get.json()["scenario_id"] == "sc_test_01"


def test_api_viewer_cannot_create_scenario(populated_twin_db: Session):
    """Verify Viewer role is forbidden from creating scenarios."""
    client = create_client(populated_twin_db, org_id="org_test_alpha", role="Viewer")
    resp = client.post("/api/v1/simulation/scenarios", json={})
    assert resp.status_code == 403


def test_api_run_simulation_and_get_result(populated_twin_db: Session):
    """Verify POST /scenarios/{id}/simulate executes and returns SimulationResult."""
    client = create_client(populated_twin_db, org_id="org_test_alpha", role="OpsManager")
    snapshot = DigitalTwinService.retrieve_current_twin(populated_twin_db, "org_test_alpha")
    sup_node_id = compute_node_id("org_test_alpha", "SUPPLIER", "sup_api_1")

    # Create scenario first
    scenario = SimulationScenarioBuilder(
        "org_test_alpha", "Execution Test Scenario", snapshot.twin_fingerprint
    ).add_delay(sup_node_id, delay_hours=12.0).build()
    from app.simulation.service import SimulationService
    SimulationService.create_scenario(populated_twin_db, "org_test_alpha", scenario)
    populated_twin_db.commit()

    # Run simulation
    resp = client.post(f"/api/v1/simulation/scenarios/{scenario.scenario_id}/simulate")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "COMPLETED"
    assert res_data["scenario_id"] == scenario.scenario_id
    sim_id = res_data["simulation_id"]

    # Fetch result
    resp_fetch = client.get(f"/api/v1/simulation/simulations/{sim_id}")
    assert resp_fetch.status_code == 200
    assert resp_fetch.json()["simulation_id"] == sim_id


def test_api_tenant_isolation_cross_access_rejected(populated_twin_db: Session):
    """Verify Org Beta cannot view or execute Org Alpha scenarios."""
    snapshot = DigitalTwinService.retrieve_current_twin(populated_twin_db, "org_test_alpha")
    scenario = SimulationScenarioBuilder(
        "org_test_alpha", "Alpha Secret Scenario", snapshot.twin_fingerprint
    ).build()
    from app.simulation.service import SimulationService
    SimulationService.create_scenario(populated_twin_db, "org_test_alpha", scenario)
    populated_twin_db.commit()

    # Org Beta client attempts access
    client_beta = create_client(populated_twin_db, org_id="org_test_beta", role="Admin")

    resp_get = client_beta.get(f"/api/v1/simulation/scenarios/{scenario.scenario_id}")
    assert resp_get.status_code in (403, 404)

    resp_sim = client_beta.post(f"/api/v1/simulation/scenarios/{scenario.scenario_id}/simulate")
    assert resp_sim.status_code in (403, 404, 422)


def test_api_compare_scenarios(populated_twin_db: Session):
    """Verify POST /simulations/compare compares two valid scenarios."""
    client = create_client(populated_twin_db, org_id="org_test_alpha", role="Analyst")
    snapshot = DigitalTwinService.retrieve_current_twin(populated_twin_db, "org_test_alpha")
    sup_node_id = compute_node_id("org_test_alpha", "SUPPLIER", "sup_api_1")

    s1 = SimulationScenarioBuilder("org_test_alpha", "Compare A", snapshot.twin_fingerprint).add_delay(sup_node_id, delay_hours=4.0).build()
    s2 = SimulationScenarioBuilder("org_test_alpha", "Compare B", snapshot.twin_fingerprint).add_delay(sup_node_id, delay_hours=16.0).build()

    from app.simulation.service import SimulationService
    SimulationService.create_scenario(populated_twin_db, "org_test_alpha", s1)
    SimulationService.create_scenario(populated_twin_db, "org_test_alpha", s2)
    populated_twin_db.commit()

    payload = {
        "scenario_a_id": s1.scenario_id,
        "scenario_b_id": s2.scenario_id,
    }
    resp = client.post("/api/v1/simulation/simulations/compare", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario_a_id"] == s1.scenario_id
    assert data["scenario_b_id"] == s2.scenario_id
    assert "total_delay_minutes" in data["metric_comparisons"]
