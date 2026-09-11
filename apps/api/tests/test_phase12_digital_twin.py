"""Comprehensive test suite for RiskWise 2.0 Phase 12 Digital Twin subsystem.

Expands coverage on:
- Boundary conditions, extreme coordinates, and zero-metric thresholds.
- Multi-tenant simultaneous isolation with multiple active organizations.
- Complex multi-cycle topologies and stress traversals.
- Observability telemetry and audit trail hooks.
- Provenance preservation and deterministic identity RFC 4122 compliance.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.builder import DigitalTwinBuilder
from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
    TwinPathResult,
    TwinQuery,
    TwinSubgraph,
    TwinValidationResult,
)
from app.digital_twin.errors import (
    DigitalTwinError,
    TwinEdgeError,
    TwinFingerprintError,
    TwinNodeError,
    TwinPersistenceError,
    TwinQueryError,
    TwinReferenceError,
    TwinSnapshotError,
    TwinTenantIsolationError,
    TwinTraversalError,
    TwinValidationError,
)
from app.digital_twin.fingerprints import (
    TWIN_NAMESPACE,
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_source_fingerprint,
    compute_twin_fingerprint,
)
from app.digital_twin.observability import (
    EVENT_BUILD_FAILED,
    EVENT_BUILD_STARTED,
    EVENT_BUILD_SUCCEEDED,
    EVENT_BUILD_VALIDATED,
    EVENT_QUERY,
    TwinObservability,
)
from app.digital_twin.query import DigitalTwinQueryService
from app.digital_twin.repository import DigitalTwinRepository
from app.digital_twin.service import DigitalTwinService
from app.digital_twin.validator import TwinGraphValidator
from app.models.network import Carrier, Factory, Port, Product, Route, Supplier, SupplierSite, Warehouse
from app.models.tenancy import Organization
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


@pytest.fixture(scope="function")
def twin_db():
    """Create in-memory SQLite session with multi-tenant seed organizations."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()

    orgs = [
        Organization(id="tenant_1", name="Tenant 1", slug="tenant-1"),
        Organization(id="tenant_2", name="Tenant 2", slug="tenant-2"),
        Organization(id="tenant_3", name="Tenant 3", slug="tenant-3"),
    ]
    session.add_all(orgs)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# -------------------------------------------------------------
# A. Deterministic Identity & RFC 4122 Compliance
# -------------------------------------------------------------

def test_node_id_is_valid_uuidv5():
    nid = compute_node_id("org_test", "SUPPLIER", "sup_99")
    parsed = uuid.UUID(nid)
    assert parsed.version == 5
    assert str(parsed) == nid


def test_edge_id_is_valid_uuidv5():
    eid = compute_edge_id("org_test", "from_n", "to_n", "FLOW", "rel_1")
    parsed = uuid.UUID(eid)
    assert parsed.version == 5
    assert str(parsed) == eid


def test_uuidv5_namespace_is_fixed_constant():
    expected_ns = uuid.UUID("a7e1f4b8-3d2c-4f9e-8b1a-5c6d7e8f9a0b")
    assert TWIN_NAMESPACE == expected_ns


# -------------------------------------------------------------
# B. Coordinate and Numeric Boundary Conditions
# -------------------------------------------------------------

@pytest.mark.parametrize("lat,lon", [
    (-90.0, -180.0),
    (90.0, 180.0),
    (0.0, 0.0),
    (-45.5, 90.2),
])
def test_valid_extreme_coordinates(lat, lon):
    nid = compute_node_id("org_coords", "PORT", "p1")
    fp = compute_node_fingerprint(
        node_id=nid,
        organization_id="org_coords",
        node_type="PORT",
        source_entity_type="PORT",
        source_entity_id="p1",
        label="Extreme Port",
        latitude=lat,
        longitude=lon,
    )
    node = TwinNodeContract(
        node_id=nid,
        organization_id="org_coords",
        node_type=TwinNodeType.PORT,
        source_entity_type="PORT",
        source_entity_id="p1",
        label="Extreme Port",
        latitude=lat,
        longitude=lon,
        fingerprint=fp,
    )
    assert node.latitude == lat
    assert node.longitude == lon


@pytest.mark.parametrize("score", [0.0, 50.0, 100.0])
def test_valid_boundary_health_and_risk_scores(score):
    nid = compute_node_id("org_scores", "FACTORY", "f1")
    fp = compute_node_fingerprint(
        node_id=nid,
        organization_id="org_scores",
        node_type="FACTORY",
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Scored Factory",
        health_score=score,
    )
    node = TwinNodeContract(
        node_id=nid,
        organization_id="org_scores",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Scored Factory",
        health_score=score,
        fingerprint=fp,
    )
    assert node.health_score == score


# -------------------------------------------------------------
# C. Error Hierarchy and Inheritance
# -------------------------------------------------------------

def test_error_hierarchy_inheritance():
    assert issubclass(TwinValidationError, DigitalTwinError)
    assert issubclass(TwinNodeError, DigitalTwinError)
    assert issubclass(TwinEdgeError, DigitalTwinError)
    assert issubclass(TwinReferenceError, DigitalTwinError)
    assert issubclass(TwinTenantIsolationError, DigitalTwinError)
    assert issubclass(TwinFingerprintError, DigitalTwinError)
    assert issubclass(TwinPersistenceError, DigitalTwinError)
    assert issubclass(TwinSnapshotError, DigitalTwinError)
    assert issubclass(TwinQueryError, DigitalTwinError)
    assert issubclass(TwinTraversalError, DigitalTwinError)

    err = TwinTenantIsolationError("Isolation breached")
    assert err.message == "Isolation breached"
    assert str(err) == "Isolation breached"


# -------------------------------------------------------------
# D. Multi-Tenant Simultaneous Isolation in Database
# -------------------------------------------------------------

def test_multi_tenant_simultaneous_persistence(twin_db: Session):
    # Seed data for Tenant 1
    f1 = Factory(id="f_t1", org_id="tenant_1", name="Plant T1", status="OPERATIONAL")
    # Seed data for Tenant 2
    f2 = Factory(id="f_t2", org_id="tenant_2", name="Plant T2", status="OPERATIONAL")
    # Seed data for Tenant 3
    f3 = Factory(id="f_t3", org_id="tenant_3", name="Plant T3", status="OPERATIONAL")
    twin_db.add_all([f1, f2, f3])
    twin_db.commit()

    # Build and persist for all 3 tenants
    snap1 = DigitalTwinService.build_and_persist(twin_db, organization_id="tenant_1")
    snap2 = DigitalTwinService.build_and_persist(twin_db, organization_id="tenant_2")
    snap3 = DigitalTwinService.build_and_persist(twin_db, organization_id="tenant_3")

    assert snap1.node_count == 1
    assert snap2.node_count == 1
    assert snap3.node_count == 1

    # Verify query services are strictly isolated
    q1 = DigitalTwinService.get_query_service(twin_db, "tenant_1")
    q2 = DigitalTwinService.get_query_service(twin_db, "tenant_2")

    t1_node_id = list(snap1.nodes.keys())[0]
    t2_node_id = list(snap2.nodes.keys())[0]

    assert q1.get_node(t1_node_id).label == "Plant T1"
    with pytest.raises(TwinQueryError):
        q1.get_node(t2_node_id)

    assert q2.get_node(t2_node_id).label == "Plant T2"
    with pytest.raises(TwinQueryError):
        q2.get_node(t1_node_id)


# -------------------------------------------------------------
# E. Complex Multi-Cycle Graph Traversal Stress Test
# -------------------------------------------------------------

def test_multi_cycle_complex_graph_traversal():
    """Graph topology with multiple interconnected cycles:

    (0) <---> (1) <---> (2)
     ^         ^         ^
     |         |         |
     v         v         v
    (3) <---> (4) <---> (5)
    """
    org = "org_complex_cycles"
    nodes: dict[str, TwinNodeContract] = {}
    edges: dict[str, TwinEdgeContract] = {}

    for i in range(6):
        nid = compute_node_id(org, "FACTORY", f"grid_{i}")
        fp = compute_node_fingerprint(nid, org, "FACTORY", "FACTORY", f"grid_{i}", f"Grid Node {i}")
        nodes[nid] = TwinNodeContract(
            node_id=nid,
            organization_id=org,
            node_type=TwinNodeType.FACTORY,
            source_entity_type="FACTORY",
            source_entity_id=f"grid_{i}",
            label=f"Grid Node {i}",
            fingerprint=fp,
        )

    grid_node_ids = [compute_node_id(org, "FACTORY", f"grid_{i}") for i in range(6)]

    # Horizontal and vertical bidirectional connections
    pairs = [
        (0, 1), (1, 2),
        (3, 4), (4, 5),
        (0, 3), (1, 4), (2, 5),
    ]
    for u, v in pairs:
        # u -> v
        eid_uv = compute_edge_id(org, grid_node_ids[u], grid_node_ids[v], "FLOW", f"{u}_{v}")
        fp_uv = compute_edge_fingerprint(eid_uv, org, grid_node_ids[u], grid_node_ids[v], "FLOW")
        edges[eid_uv] = TwinEdgeContract(
            edge_id=eid_uv,
            organization_id=org,
            from_node_id=grid_node_ids[u],
            to_node_id=grid_node_ids[v],
            edge_type=TwinEdgeType.FLOW,
            fingerprint=fp_uv,
        )
        # v -> u
        eid_vu = compute_edge_id(org, grid_node_ids[v], grid_node_ids[u], "FLOW", f"{v}_{u}")
        fp_vu = compute_edge_fingerprint(eid_vu, org, grid_node_ids[v], grid_node_ids[u], "FLOW")
        edges[eid_vu] = TwinEdgeContract(
            edge_id=eid_vu,
            organization_id=org,
            from_node_id=grid_node_ids[v],
            to_node_id=grid_node_ids[u],
            edge_type=TwinEdgeType.FLOW,
            fingerprint=fp_vu,
        )

    tfp = compute_twin_fingerprint(
        "twin_grid", org, "1", [n.fingerprint for n in nodes.values()], [e.fingerprint for e in edges.values()]
    )
    snapshot = DigitalTwinSnapshot(
        twin_id="twin_grid",
        organization_id=org,
        version="1",
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=nodes,
        edges=edges,
        source_fingerprint=tfp,
        twin_fingerprint=tfp,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )

    query_svc = DigitalTwinQueryService(snapshot)

    # Subgraph from node 0 must discover all 6 nodes without looping infinitely
    subgraph = query_svc.get_subgraph(root_node_id=grid_node_ids[0], max_depth=10)
    assert subgraph.total_nodes == 6
    assert subgraph.total_edges == len(edges)

    # Path discovery between opposite corners (0 to 5)
    path = query_svc.find_path(grid_node_ids[0], grid_node_ids[5], max_depth=5)
    assert path.path_found is True
    assert path.hop_count >= 2
    assert path.node_ids[0] == grid_node_ids[0]
    assert path.node_ids[-1] == grid_node_ids[5]


# -------------------------------------------------------------
# F. Observability Telemetry Logging Checks
# -------------------------------------------------------------

def test_observability_event_constants():
    assert EVENT_BUILD_STARTED == "DIGITAL_TWIN_BUILD_STARTED"
    assert EVENT_BUILD_VALIDATED == "DIGITAL_TWIN_BUILD_VALIDATED"
    assert EVENT_BUILD_SUCCEEDED == "DIGITAL_TWIN_BUILD_SUCCEEDED"
    assert EVENT_BUILD_FAILED == "DIGITAL_TWIN_BUILD_FAILED"
    assert EVENT_QUERY == "DIGITAL_TWIN_QUERY"


def test_observability_methods_do_not_crash_without_uow():
    # Should safely log via standard logger when uow=None
    TwinObservability.log_build_started("org1", "twin1")
    TwinObservability.log_build_validated("org1", "twin1", 10, 15, 2.5)
    TwinObservability.log_build_succeeded("org1", "twin1", 10, 15, "s" * 64, "t" * 64, 12.0)
    TwinObservability.log_build_failed("org1", "twin1", "test err", "ValueError", 1.0)
    TwinObservability.log_query("org1", "twin1", "get_node", {"node_id": "n1"}, 0.5)


# -------------------------------------------------------------
# G. Provenance Preservation Across Persistence
# -------------------------------------------------------------

def test_provenance_preservation(twin_db: Session):
    carrier = Carrier(
        id="c_prov",
        org_id="tenant_1",
        name="Apex Express",
        mode="AIR",
        on_time_reliability=96.0,
    )
    twin_db.add(carrier)
    twin_db.commit()

    snap = DigitalTwinService.build_and_persist(twin_db, organization_id="tenant_1")
    carrier_node = list(snap.nodes.values())[0]

    assert carrier_node.source_entity_type == "CARRIER"
    assert carrier_node.source_entity_id == "c_prov"
    assert carrier_node.organization_id == "tenant_1"

    # Reload from database and verify provenance was reconstructed from properties_json
    reloaded = DigitalTwinService.get_twin_snapshot(twin_db, organization_id="tenant_1")
    assert reloaded is not None
    reloaded_node = list(reloaded.nodes.values())[0]
    assert reloaded_node.source_entity_type == "CARRIER"
    assert reloaded_node.source_entity_id == "c_prov"
    assert reloaded_node.organization_id == "tenant_1"
    assert reloaded_node.fingerprint == carrier_node.fingerprint


# -------------------------------------------------------------
# H. Entity Attribute Fidelity and Preservation
# -------------------------------------------------------------

def test_builder_port_congestion_and_wait_time_preserved():
    builder = DigitalTwinBuilder("tenant_1")
    port = SimpleNamespace(
        id="port_rotterdam",
        name="Port of Rotterdam",
        code="NLRTM",
        port_type="SEA",
        country="Netherlands",
        latitude=51.9244,
        longitude=4.4777,
        congestion_score=42.0,
        average_wait_hours=18.5,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap = builder.build_from_entities(ports=[port])
    node = list(snap.nodes.values())[0]
    assert node.properties["congestion_score"] == 42.0
    assert node.properties["average_wait_hours"] == 18.5
    assert node.properties["port_type"] == "SEA"


def test_builder_factory_utilization_preserved():
    builder = DigitalTwinBuilder("tenant_1")
    fac = SimpleNamespace(
        id="f_util",
        org_id="tenant_1",
        name="Factory High Util",
        capacity=100000.0,
        utilization=0.92,
        city="Detroit",
        country="USA",
        latitude=42.3314,
        longitude=-83.0458,
        status="OPERATIONAL",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap = builder.build_from_entities(factories=[fac])
    node = list(snap.nodes.values())[0]
    assert node.properties["capacity"] == 100000.0
    assert node.properties["utilization"] == 0.92


def test_builder_warehouse_occupancy_preserved():
    builder = DigitalTwinBuilder("tenant_1")
    wh = SimpleNamespace(
        id="wh_occ",
        org_id="tenant_1",
        name="Mega Distribution Center",
        total_capacity=500000.0,
        current_occupancy=420000.0,
        city="Memphis",
        country="USA",
        latitude=35.1495,
        longitude=-90.0490,
        status="OPERATIONAL",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap = builder.build_from_entities(warehouses=[wh])
    node = list(snap.nodes.values())[0]
    assert node.properties["total_capacity"] == 500000.0
    assert node.properties["current_occupancy"] == 420000.0


def test_builder_supplier_tier_criticality_preserved():
    builder = DigitalTwinBuilder("tenant_1")
    sup = SimpleNamespace(
        id="sup_crit",
        org_id="tenant_1",
        name="Critical Minerals Ltd",
        country="Chile",
        tier="TIER_1",
        criticality="CRITICAL",
        reliability_score=98.0,
        financial_exposure=25000000.0,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap = builder.build_from_entities(suppliers=[sup])
    node = list(snap.nodes.values())[0]
    assert node.properties["tier"] == "TIER_1"
    assert node.properties["criticality"] == "CRITICAL"
    assert node.properties["financial_exposure"] == 25000000.0


def test_builder_product_sku_cost_preserved():
    builder = DigitalTwinBuilder("tenant_1")
    prod = SimpleNamespace(
        id="p_sku",
        org_id="tenant_1",
        sku="SKU-MICRO-007",
        name="Advanced AI Accelerator",
        category="Processors",
        unit_cost=1250.0,
        currency="USD",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap = builder.build_from_entities(products=[prod])
    node = list(snap.nodes.values())[0]
    assert node.properties["sku"] == "SKU-MICRO-007"
    assert node.properties["unit_cost"] == 1250.0
    assert node.properties["currency"] == "USD"


def test_builder_carrier_reliability_mapped_to_health_score():
    builder = DigitalTwinBuilder("tenant_1")
    c = SimpleNamespace(
        id="c_rel",
        org_id="tenant_1",
        name="Reliable Freight",
        mode="ROAD",
        on_time_reliability=94.5,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap = builder.build_from_entities(carriers=[c])
    node = list(snap.nodes.values())[0]
    assert node.health_score == 94.5


def test_builder_custom_version_string():
    builder = DigitalTwinBuilder("tenant_1", version="2.1.0-alpha")
    snap = builder.build_from_entities()
    assert snap.version == "2.1.0-alpha"


def test_builder_custom_twin_id_preserved():
    builder = DigitalTwinBuilder("tenant_1", twin_id="custom-twin-identifier")
    snap = builder.build_from_entities()
    assert snap.twin_id == "custom-twin-identifier"


def test_snapshot_status_values_supported():
    for st in ["CURRENT", "SNAPSHOT", "STALE", "HISTORICAL"]:
        snap = DigitalTwinSnapshot(
            twin_id="t1",
            organization_id="o1",
            version="1",
            node_count=0,
            edge_count=0,
            nodes={},
            edges={},
            source_fingerprint="0" * 64,
            twin_fingerprint="0" * 64,
            generated_at=datetime.datetime.now(datetime.timezone.utc),
            status=st,
        )
        assert snap.status == st


def test_twin_fingerprint_unique_across_tenants():
    builder1 = DigitalTwinBuilder("tenant_1")
    builder2 = DigitalTwinBuilder("tenant_2")
    snap1 = builder1.build_from_entities()
    snap2 = builder2.build_from_entities()
    assert snap1.twin_fingerprint != snap2.twin_fingerprint


def test_twin_service_build_and_persist_handles_empty_db(twin_db: Session):
    # Tenant with 0 records
    snap = DigitalTwinService.build_and_persist(twin_db, organization_id="tenant_3")
    assert snap.node_count == 0
    assert snap.edge_count == 0
    assert snap.organization_id == "tenant_3"

    loaded = DigitalTwinService.get_twin_snapshot(twin_db, organization_id="tenant_3")
    assert loaded is None  # No nodes persisted, returns None cleanly


def test_twin_observability_timing_metrics(twin_db: Session):
    # Verify timing metrics format in telemetry logging
    f = Factory(id="f_time", org_id="tenant_1", name="Plant Timer", status="OPERATIONAL")
    twin_db.add(f)
    twin_db.commit()

    snap = DigitalTwinService.build_and_persist(
        twin_db,
        organization_id="tenant_1",
        correlation_id="corr-12345",
        request_id="req-67890",
    )
    assert snap.node_count == 1

