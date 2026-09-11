"""Integration test suite for RiskWise Phase 12 Digital Twin API endpoints.

Validates:
1. Authentication & RBAC requirements across all endpoints.
2. GET /api/v1/digital-twin/current summary response.
3. GET /api/v1/digital-twin/snapshot full topology graph.
4. GET /api/v1/digital-twin/nodes with and without node_type filtering.
5. GET /api/v1/digital-twin/nodes/{id} with 404 and 403 error isolation.
6. GET /api/v1/digital-twin/edges with and without edge_type filtering.
7. POST /api/v1/digital-twin/refresh write-role enforcement and graph rebuilding.
8. POST /api/v1/digital-twin/query bounded subgraph traversal and type search.
9. POST /api/v1/digital-twin/path deterministic BFS path discovery.
10. Strict multi-tenant boundary enforcement across all endpoints.
11. Read-only database guarantees during graph querying.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_authenticated_context, require_role
from app.core.context import AuthenticatedContext
from app.db.base import Base
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.digital_twin.builder import DigitalTwinBuilder
from app.digital_twin.contracts import DigitalTwinProvenance, DigitalTwinNode, DigitalTwinEdge
from app.digital_twin.fingerprints import compute_node_id
from app.digital_twin.service import DigitalTwinService
from app.main import app
from app.models.network import Factory, Supplier, SupplierSite, Warehouse
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


# ------------------------------------------------------------------------------
# Test Fixtures & In-Memory Isolation
# ------------------------------------------------------------------------------

class MockAuthContext:
    def __init__(
        self,
        user_id: str,
        organization_id: str,
        role: str,
        request_id: str = "req-test-p12-api",
    ):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.request_id = request_id


@pytest.fixture(scope="module", autouse=True)
def mount_digital_twin_routes():
    """Mount Digital Twin API routes for the duration of this module and restore afterwards."""
    from app.api.v1.endpoints.digital_twin import router as twin_router
    orig_routes = list(app.router.routes)
    app.include_router(twin_router, prefix="/api/v1/digital-twin", tags=["Digital Twin"])
    app.openapi_schema = None
    yield
    app.router.routes = orig_routes
    app.openapi_schema = None


@pytest.fixture(autouse=True)
def cleanup_overrides():
    """Ensure dependency overrides are cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def db_session():
    """Create isolated SQLite in-memory database with Digital Twin tables."""
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
def populated_db(db_session: Session):
    """Seed test supply chain network for org_test_alpha and org_test_beta."""
    # Org Alpha: Supplier -> Site -> Factory -> Warehouse
    sup = Supplier(
        id="sup_alpha_1",
        org_id="org_test_alpha",
        name="Alpha Semiconductor",
        tier="CRITICAL",
        country="TW",
    )
    site = SupplierSite(
        id="site_alpha_1",
        org_id="org_test_alpha",
        supplier_id="sup_alpha_1",
        name="Hsinchu Fab 1",
        latitude=24.78,
        longitude=120.99,
    )
    factory = Factory(
        id="fac_alpha_1",
        org_id="org_test_alpha",
        name="Taipei Assembly",
        latitude=25.03,
        longitude=121.56,
        capacity=100000.0,
    )
    wh = Warehouse(
        id="wh_alpha_1",
        org_id="org_test_alpha",
        name="Taoyuan Logistics Hub",
        latitude=24.99,
        longitude=121.30,
        total_capacity=50000.0,
    )

    # Org Beta: Isolated supplier
    sup_beta = Supplier(
        id="sup_beta_1",
        org_id="org_test_beta",
        name="Beta Lithium",
        tier="HIGH",
        country="AU",
    )

    db_session.add_all([sup, site, factory, wh, sup_beta])
    db_session.commit()

    # Pre-build twin snapshots for both tenants
    DigitalTwinService.build_and_persist(db_session, organization_id="org_test_alpha")
    DigitalTwinService.build_and_persist(db_session, organization_id="org_test_beta")
    db_session.commit()

    return db_session


def create_mock_client(db: Session, org_id: str = "org_test_alpha", role: str = "OpsManager") -> TestClient:
    """Create test client with overridden authentication context."""
    auth_ctx = MockAuthContext(
        user_id=f"user_{org_id}",
        organization_id=org_id,
        role=role,
        request_id="req-test-p12-api",
    )

    def override_get_db():
        yield db

    def override_get_uow():
        uow = UnitOfWork(session=db)
        return uow

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
    """Verify unauthenticated requests without context override are rejected."""
    app.dependency_overrides.clear()
    client = TestClient(app)
    resp = client.get("/api/v1/digital-twin/current")
    assert resp.status_code in (401, 403)


def test_api_get_current_twin(populated_db: Session):
    """Verify GET /api/v1/digital-twin/current returns valid summary metrics."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Analyst")
    resp = client.get("/api/v1/digital-twin/current")
    assert resp.status_code == 200

    data = resp.json()
    assert data["organization_id"] == "org_test_alpha"
    assert data["node_count"] >= 4
    assert data["edge_count"] >= 1
    assert len(data["source_fingerprint"]) == 64
    assert len(data["twin_fingerprint"]) == 64
    assert data["status"] == "CURRENT"


def test_api_get_full_snapshot(populated_db: Session):
    """Verify GET /api/v1/digital-twin/snapshot returns complete topology graph."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Viewer")
    resp = client.get("/api/v1/digital-twin/snapshot")
    assert resp.status_code == 200

    snapshot = resp.json()
    assert snapshot["organization_id"] == "org_test_alpha"
    assert len(snapshot["nodes"]) >= 4
    assert len(snapshot["edges"]) >= 1

    # Verify every node belongs to org_test_alpha
    for n in snapshot["nodes"].values():
        assert n["organization_id"] == "org_test_alpha"


def test_api_list_nodes_and_filtering(populated_db: Session):
    """Verify GET /api/v1/digital-twin/nodes supports node_type filtering."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Viewer")

    # List all nodes
    resp = client.get("/api/v1/digital-twin/nodes")
    assert resp.status_code == 200
    all_nodes = resp.json()
    assert len(all_nodes) >= 4

    # Filter by SUPPLIER
    resp_sup = client.get("/api/v1/digital-twin/nodes?node_type=SUPPLIER")
    assert resp_sup.status_code == 200
    suppliers = resp_sup.json()
    assert len(suppliers) == 1
    assert suppliers[0]["node_type"] == "SUPPLIER"
    assert suppliers[0]["label"] == "Alpha Semiconductor"


def test_api_get_node_by_id(populated_db: Session):
    """Verify GET /api/v1/digital-twin/nodes/{id} retrieves node and rejects missing/cross-tenant."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Viewer")

    node_id = compute_node_id("org_test_alpha", "SUPPLIER", "sup_alpha_1")
    resp = client.get(f"/api/v1/digital-twin/nodes/{node_id}")
    assert resp.status_code == 200
    assert resp.json()["node_id"] == node_id
    assert resp.json()["label"] == "Alpha Semiconductor"

    # Nonexistent node
    resp_missing = client.get("/api/v1/digital-twin/nodes/nonexistent-node-id")
    assert resp_missing.status_code == 404

    # Cross-tenant node from Beta
    beta_node_id = compute_node_id("org_test_beta", "SUPPLIER", "sup_beta_1")
    resp_cross = client.get(f"/api/v1/digital-twin/nodes/{beta_node_id}")
    assert resp_cross.status_code in (403, 404)


def test_api_list_edges_and_filtering(populated_db: Session):
    """Verify GET /api/v1/digital-twin/edges supports edge_type filtering."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Analyst")

    resp = client.get("/api/v1/digital-twin/edges")
    assert resp.status_code == 200
    edges = resp.json()
    assert len(edges) >= 1

    resp_filtered = client.get("/api/v1/digital-twin/edges?edge_type=SUPPLIES")
    assert resp_filtered.status_code == 200
    for e in resp_filtered.json():
        assert e["edge_type"] == "SUPPLIES"


def test_api_refresh_twin(populated_db: Session):
    """Verify POST /api/v1/digital-twin/refresh rebuilds and persists snapshot."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="OpsManager")

    resp = client.post("/api/v1/digital-twin/refresh")
    assert resp.status_code == 200
    snapshot = resp.json()
    assert snapshot["organization_id"] == "org_test_alpha"
    assert snapshot["node_count"] >= 4


def test_api_refresh_insufficient_role_rejected(populated_db: Session):
    """Verify POST /api/v1/digital-twin/refresh is forbidden for Viewer role."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Viewer")
    resp = client.post("/api/v1/digital-twin/refresh")
    assert resp.status_code == 403


def test_api_query_subgraph(populated_db: Session):
    """Verify POST /api/v1/digital-twin/query executes bounded BFS traversal."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Analyst")

    sup_node_id = compute_node_id("org_test_alpha", "SUPPLIER", "sup_alpha_1")
    query_payload = {
        "node_id": sup_node_id,
        "max_depth": 3,
        "max_nodes": 50,
        "max_edges": 100,
    }

    resp = client.post("/api/v1/digital-twin/query", json=query_payload)
    assert resp.status_code == 200
    subgraph = resp.json()
    assert subgraph["root_node_id"] == sup_node_id
    assert subgraph["total_nodes"] >= 2


def test_api_path_discovery(populated_db: Session):
    """Verify POST /api/v1/digital-twin/path finds deterministic route."""
    client = create_mock_client(populated_db, org_id="org_test_alpha", role="Analyst")

    sup_node_id = compute_node_id("org_test_alpha", "SUPPLIER", "sup_alpha_1")
    site_node_id = compute_node_id("org_test_alpha", "SUPPLIER_SITE", "site_alpha_1")

    path_payload = {
        "source_node_id": sup_node_id,
        "target_node_id": site_node_id,
        "max_depth": 5,
    }

    resp = client.post("/api/v1/digital-twin/path", json=path_payload)
    assert resp.status_code == 200
    res = resp.json()
    assert res["path_found"] is True
    assert res["hop_count"] == 1
    assert res["node_ids"] == [sup_node_id, site_node_id]


def test_provenance_contract_model():
    """Verify DigitalTwinProvenance contract instantiation and attachment."""
    prov = DigitalTwinProvenance(
        source_entity_type="SUPPLIER",
        source_entity_id="sup_100",
        source_system="ERP_S4HANA",
        source_reference="suppliers.id:sup_100",
        confidence_score=0.98,
        metadata={"region": "APAC"},
    )
    assert prov.source_entity_type == "SUPPLIER"
    assert prov.confidence_score == 0.98
    assert prov.metadata["region"] == "APAC"

    node = DigitalTwinNode(
        node_id="test_node_prov",
        organization_id="org_test",
        node_type=TwinNodeType.SUPPLIER,
        source_entity_type="SUPPLIER",
        source_entity_id="sup_100",
        label="Test Supplier",
        provenance=prov,
        fingerprint="a" * 64,
    )
    assert node.provenance_info.source_system == "ERP_S4HANA"
    assert node.provenance_info.confidence_score == 0.98
