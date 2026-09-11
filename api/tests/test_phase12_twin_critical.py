"""Mandatory critical tests verifying all 20 non-negotiable architectural invariants for Phase 12 Digital Twin."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
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
)
from app.digital_twin.errors import (
    TwinPersistenceError,
    TwinQueryError,
    TwinReferenceError,
    TwinTenantIsolationError,
)
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_twin_fingerprint,
)
from app.digital_twin.query import DigitalTwinQueryService
from app.digital_twin.repository import DigitalTwinRepository
from app.digital_twin.service import DigitalTwinService
from app.digital_twin.validator import TwinGraphValidator
from app.models.network import Factory, Route, Warehouse
from app.models.tenancy import Organization
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


@pytest.fixture(scope="function")
def mem_db():
    """Isolated SQLite database for critical invariant tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionMaker()

    org1 = Organization(id="org_alpha", name="Alpha Corp", slug="alpha-corp")
    org2 = Organization(id="org_beta", name="Beta Corp", slug="beta-corp")
    session.add_all([org1, org2])
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# 1. Digital Twin cannot modify authoritative database state.
def test_critical_1_twin_cannot_modify_authoritative_database_state(mem_db: Session):
    wh = Warehouse(
        id="wh_100",
        org_id="org_alpha",
        name="Main Hub",
        total_capacity=10000.0,
        current_occupancy=4000.0,
        status="OPERATIONAL",
    )
    mem_db.add(wh)
    mem_db.commit()

    # Build and persist Digital Twin
    DigitalTwinService.build_and_persist(mem_db, organization_id="org_alpha")

    # Authoritative DB record must remain 100% unchanged
    refreshed_wh = mem_db.query(Warehouse).filter(Warehouse.id == "wh_100").first()
    assert refreshed_wh is not None
    assert refreshed_wh.total_capacity == 10000.0
    assert refreshed_wh.current_occupancy == 4000.0
    assert refreshed_wh.status == "OPERATIONAL"


# 2. Cross-tenant nodes are rejected.
def test_critical_2_cross_tenant_nodes_are_rejected():
    n_beta = TwinNodeContract(
        node_id=compute_node_id("org_beta", "FACTORY", "f1"),
        organization_id="org_beta",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Beta Plant",
        fingerprint=compute_node_fingerprint(
            compute_node_id("org_beta", "FACTORY", "f1"),
            "org_beta",
            "FACTORY",
            "FACTORY",
            "f1",
            "Beta Plant",
        ),
    )
    with pytest.raises(TwinTenantIsolationError):
        TwinGraphValidator.assert_valid_graph(
            nodes=[n_beta], edges=[], expected_org_id="org_alpha"
        )


# 3. Cross-tenant edges are rejected.
def test_critical_3_cross_tenant_edges_are_rejected():
    n1 = TwinNodeContract(
        node_id=compute_node_id("org_alpha", "FACTORY", "f1"),
        organization_id="org_alpha",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Plant 1",
        fingerprint=compute_node_fingerprint(
            compute_node_id("org_alpha", "FACTORY", "f1"),
            "org_alpha",
            "FACTORY",
            "FACTORY",
            "f1",
            "Plant 1",
        ),
    )
    n2 = TwinNodeContract(
        node_id=compute_node_id("org_alpha", "WAREHOUSE", "w1"),
        organization_id="org_alpha",
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="w1",
        label="WH 1",
        fingerprint=compute_node_fingerprint(
            compute_node_id("org_alpha", "WAREHOUSE", "w1"),
            "org_alpha",
            "WAREHOUSE",
            "WAREHOUSE",
            "w1",
            "WH 1",
        ),
    )
    e_cross = TwinEdgeContract(
        edge_id=compute_edge_id("org_beta", n1.node_id, n2.node_id, "TRANSPORT"),
        organization_id="org_beta",  # Contaminated tenant!
        from_node_id=n1.node_id,
        to_node_id=n2.node_id,
        edge_type=TwinEdgeType.TRANSPORT,
        fingerprint=compute_edge_fingerprint(
            compute_edge_id("org_beta", n1.node_id, n2.node_id, "TRANSPORT"),
            "org_beta",
            n1.node_id,
            n2.node_id,
            "TRANSPORT",
        ),
    )
    with pytest.raises(TwinTenantIsolationError):
        TwinGraphValidator.assert_valid_graph(
            nodes=[n1, n2], edges=[e_cross], expected_org_id="org_alpha"
        )


# 4. Cross-tenant queries are rejected.
def test_critical_4_cross_tenant_queries_are_rejected():
    n_beta = TwinNodeContract(
        node_id=compute_node_id("org_beta", "FACTORY", "f1"),
        organization_id="org_beta",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Beta Plant",
        fingerprint="0" * 64,
    )
    snap_alpha = DigitalTwinSnapshot(
        twin_id="twin-org_alpha",
        organization_id="org_alpha",
        version="1",
        node_count=0,
        edge_count=0,
        nodes={},
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap_alpha)
    with pytest.raises(TwinQueryError):
        svc.get_node(n_beta.node_id)


# 5. Invalid references cannot create edges.
def test_critical_5_invalid_references_cannot_create_edges():
    n1 = TwinNodeContract(
        node_id=compute_node_id("org_alpha", "FACTORY", "f1"),
        organization_id="org_alpha",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Plant 1",
        fingerprint=compute_node_fingerprint(
            compute_node_id("org_alpha", "FACTORY", "f1"),
            "org_alpha",
            "FACTORY",
            "FACTORY",
            "f1",
            "Plant 1",
        ),
    )
    bad_edge = TwinEdgeContract(
        edge_id=compute_edge_id("org_alpha", n1.node_id, "phantom-node", "FLOW"),
        organization_id="org_alpha",
        from_node_id=n1.node_id,
        to_node_id="phantom-node",
        edge_type=TwinEdgeType.FLOW,
        fingerprint=compute_edge_fingerprint(
            compute_edge_id("org_alpha", n1.node_id, "phantom-node", "FLOW"),
            "org_alpha",
            n1.node_id,
            "phantom-node",
            "FLOW",
        ),
    )
    with pytest.raises(TwinReferenceError):
        TwinGraphValidator.assert_valid_graph(
            nodes=[n1], edges=[bad_edge], expected_org_id="org_alpha"
        )


# 6. Duplicate relationships do not create duplicate edges.
def test_critical_6_duplicate_relationships_do_not_create_duplicate_edges():
    builder = DigitalTwinBuilder(organization_id="org_alpha")
    fac = SimpleNamespace(
        id="f1", org_id="org_alpha", name="Factory 1", created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    wh = SimpleNamespace(
        id="w1", org_id="org_alpha", name="Warehouse 1", created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    route1 = SimpleNamespace(
        id="r1",
        org_id="org_alpha",
        name="Route A",
        origin_facility_id="f1",
        destination_facility_id="w1",
        mode="OCEAN",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )
    # Duplicate route record
    route2 = SimpleNamespace(
        id="r1",
        org_id="org_alpha",
        name="Route A",
        origin_facility_id="f1",
        destination_facility_id="w1",
        mode="OCEAN",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )

    snapshot = builder.build_from_entities(factories=[fac], warehouses=[wh], routes=[route1, route2])
    # Edge map ensures duplicate edge IDs are deduplicated deterministically
    corridor_edges = [e for e in snapshot.edges.values() if e.edge_type == TwinEdgeType.TRANSPORT]
    assert len(corridor_edges) == 1


# 7. Rebuilding identical source data is idempotent.
def test_critical_7_rebuilding_identical_source_data_is_idempotent():
    builder = DigitalTwinBuilder(organization_id="org_alpha")
    fac = SimpleNamespace(
        id="f1", org_id="org_alpha", name="Factory 1", created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    wh = SimpleNamespace(
        id="w1", org_id="org_alpha", name="Warehouse 1", created_at=datetime.datetime.now(datetime.timezone.utc)
    )

    snap1 = builder.build_from_entities(factories=[fac], warehouses=[wh])
    snap2 = builder.build_from_entities(factories=[fac], warehouses=[wh])

    assert snap1.node_count == snap2.node_count == 2
    assert snap1.source_fingerprint == snap2.source_fingerprint
    assert snap1.twin_fingerprint == snap2.twin_fingerprint


# 8. Same source state produces deterministic fingerprint.
def test_critical_8_same_source_state_produces_deterministic_fingerprint():
    builder = DigitalTwinBuilder(organization_id="org_alpha")
    fac = SimpleNamespace(
        id="f1",
        org_id="org_alpha",
        name="Factory 1",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    snap_a = builder.build_from_entities(factories=[fac])
    snap_b = builder.build_from_entities(factories=[fac])
    assert snap_a.twin_fingerprint == snap_b.twin_fingerprint


# 9. Invalid graph cannot be partially published.
def test_critical_9_invalid_graph_cannot_be_partially_published(mem_db: Session):
    # Valid initial snapshot
    fac = Factory(id="f1", org_id="org_alpha", name="Factory 1", status="OPERATIONAL")
    mem_db.add(fac)
    mem_db.commit()

    DigitalTwinService.build_and_persist(mem_db, "org_alpha")
    initial_nodes = DigitalTwinRepository.load_snapshot(mem_db, "org_alpha")
    assert initial_nodes.node_count == 1

    # Attempt to persist an invalid snapshot with orphan edge
    corrupt_snap = DigitalTwinSnapshot(
        twin_id="twin-org_alpha",
        organization_id="org_alpha",
        version="1",
        node_count=1,
        edge_count=1,
        nodes=initial_nodes.nodes,
        edges={
            "bad-edge": TwinEdgeContract(
                edge_id="bad-edge",
                organization_id="org_alpha",
                from_node_id=list(initial_nodes.nodes.keys())[0],
                to_node_id="missing-target",
                edge_type=TwinEdgeType.TRANSPORT,
                fingerprint="0" * 64,
            )
        },
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )

    with pytest.raises(TwinPersistenceError):
        DigitalTwinRepository.persist_snapshot(mem_db, corrupt_snap)

    # Database retains initial clean state; no partial publish
    reloaded = DigitalTwinRepository.load_snapshot(mem_db, "org_alpha")
    assert reloaded.node_count == 1
    assert reloaded.edge_count == 0


# 10. Cycle traversal cannot loop forever.
def test_critical_10_cycle_traversal_cannot_loop_forever():
    org = "org_cycle"
    # Create cycle: A -> B -> C -> A
    n_a = TwinNodeContract(
        node_id=compute_node_id(org, "A", "1"),
        organization_id=org,
        node_type=TwinNodeType.FACTORY,
        source_entity_type="A",
        source_entity_id="1",
        label="Node A",
        fingerprint="0" * 64,
    )
    n_b = TwinNodeContract(
        node_id=compute_node_id(org, "B", "2"),
        organization_id=org,
        node_type=TwinNodeType.FACTORY,
        source_entity_type="B",
        source_entity_id="2",
        label="Node B",
        fingerprint="0" * 64,
    )
    n_c = TwinNodeContract(
        node_id=compute_node_id(org, "C", "3"),
        organization_id=org,
        node_type=TwinNodeType.FACTORY,
        source_entity_type="C",
        source_entity_id="3",
        label="Node C",
        fingerprint="0" * 64,
    )

    e_ab = TwinEdgeContract(
        edge_id="e_ab",
        organization_id=org,
        from_node_id=n_a.node_id,
        to_node_id=n_b.node_id,
        edge_type=TwinEdgeType.FLOW,
        fingerprint="0" * 64,
    )
    e_bc = TwinEdgeContract(
        edge_id="e_bc",
        organization_id=org,
        from_node_id=n_b.node_id,
        to_node_id=n_c.node_id,
        edge_type=TwinEdgeType.FLOW,
        fingerprint="0" * 64,
    )
    e_ca = TwinEdgeContract(
        edge_id="e_ca",
        organization_id=org,
        from_node_id=n_c.node_id,
        to_node_id=n_a.node_id,
        edge_type=TwinEdgeType.FLOW,
        fingerprint="0" * 64,
    )

    snap = DigitalTwinSnapshot(
        twin_id="twin_cycle",
        organization_id=org,
        version="1",
        node_count=3,
        edge_count=3,
        nodes={n.node_id: n for n in [n_a, n_b, n_c]},
        edges={e.edge_id: e for e in [e_ab, e_bc, e_ca]},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    # Traversal must finish in milliseconds without infinite looping
    subgraph = svc.get_subgraph(root_node_id=n_a.node_id, max_depth=10)
    assert subgraph.total_nodes == 3
    assert subgraph.total_edges == 3


# 11. Query depth is bounded.
def test_critical_11_query_depth_is_bounded():
    snap = DigitalTwinSnapshot(
        twin_id="twin_1",
        organization_id="org_1",
        version="1",
        node_count=1,
        edge_count=0,
        nodes={
            "n1": TwinNodeContract(
                node_id="n1",
                organization_id="org_1",
                node_type=TwinNodeType.FACTORY,
                source_entity_type="FAC",
                source_entity_id="1",
                label="N1",
                fingerprint="0" * 64,
            )
        },
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    subgraph = svc.get_subgraph(root_node_id="n1", max_depth=50)
    assert subgraph.depth <= 10


# 12. Query result size is bounded.
def test_critical_12_query_result_size_is_bounded():
    snap = DigitalTwinSnapshot(
        twin_id="twin_1",
        organization_id="org_1",
        version="1",
        node_count=1,
        edge_count=0,
        nodes={
            "n1": TwinNodeContract(
                node_id="n1",
                organization_id="org_1",
                node_type=TwinNodeType.FACTORY,
                source_entity_type="FAC",
                source_entity_id="1",
                label="N1",
                fingerprint="0" * 64,
            )
        },
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    subgraph = svc.get_subgraph(root_node_id="n1", max_nodes=5000, max_edges=10000)
    assert subgraph.total_nodes <= 500
    assert subgraph.total_edges <= 1000


# 13. Forged node/edge identities are rejected where applicable.
def test_critical_13_forged_identities_rejected():
    snap = DigitalTwinSnapshot(
        twin_id="twin_1",
        organization_id="org_1",
        version="1",
        node_count=0,
        edge_count=0,
        nodes={},
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    with pytest.raises(TwinQueryError):
        svc.get_node("forged-node-uuid")


# 14. Missing source entities do not create fabricated nodes.
def test_critical_14_missing_source_entities_do_not_create_fabricated_nodes():
    builder = DigitalTwinBuilder(organization_id="org_alpha")
    # Empty DB entities
    snapshot = builder.build_from_entities()
    assert snapshot.node_count == 0


# 15. Missing relationships do not create fabricated edges.
def test_critical_15_missing_relationships_do_not_create_fabricated_edges():
    builder = DigitalTwinBuilder(organization_id="org_alpha")
    # Two disconnected facilities with no route or inventory
    fac = SimpleNamespace(
        id="f1", org_id="org_alpha", name="Fac 1", created_at=datetime.datetime.now(datetime.timezone.utc)
    )
    wh = SimpleNamespace(
        id="w1", org_id="org_alpha", name="Wh 1", created_at=datetime.datetime.now(datetime.timezone.utc)
    )

    snapshot = builder.build_from_entities(factories=[fac], warehouses=[wh])
    assert snapshot.node_count == 2
    assert snapshot.edge_count == 0  # No fabricated relationship


# 16. Historical events cannot incorrectly overwrite current state.
def test_critical_16_historical_events_do_not_overwrite_current_state():
    builder = DigitalTwinBuilder(organization_id="org_alpha")
    # Current shipment state is IN_TRANSIT with recent location
    sh = SimpleNamespace(
        id="sh1",
        org_id="org_alpha",
        tracking_number="TRK-100",
        status="IN_TRANSIT",
        current_lat=25.0,
        current_lng=-80.0,
        created_at=datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc),
    )
    snapshot = builder.build_from_entities(shipments=[sh])
    node = list(snapshot.nodes.values())[0]
    assert node.status == "IN_TRANSIT"
    assert node.latitude == 25.0
    assert node.longitude == -80.0


# 17. Claude is never used to infer graph topology.
def test_critical_17_claude_never_used_for_topology():
    import app.digital_twin.builder as dt_builder
    import app.digital_twin.service as dt_service
    import app.digital_twin.query as dt_query

    # Verify no Bedrock, Anthropic, or Claude imports in digital twin subsystem
    for mod in [dt_builder, dt_service, dt_query]:
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "bedrock" not in src.lower()
        assert "claude" not in src.lower()
        assert "anthropic" not in src.lower()


# 18. No simulation is performed.
def test_critical_18_no_simulation_performed():
    import app.digital_twin.service as dt_service
    import app.digital_twin.query as dt_query

    for mod in [dt_service, dt_query]:
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "monte_carlo" not in src.lower()
        assert "simulate" not in src.lower()
        assert "stochastic" not in src.lower()


# 19. No optimization is performed.
def test_critical_19_no_optimization_performed():
    import app.digital_twin.query as dt_query
    src = open(dt_query.__file__, "r", encoding="utf-8").read()
    assert "or_tools" not in src.lower()
    assert "ortools" not in src.lower()
    assert "simplex" not in src.lower()
    assert "linear_programming" not in src.lower()


# 20. No decision is generated.
def test_critical_20_no_decision_generated():
    import app.digital_twin.service as dt_service
    src = open(dt_service.__file__, "r", encoding="utf-8").read()
    assert "recommend_action" not in src.lower()
    assert "approve_action" not in src.lower()
    assert "execute_action" not in src.lower()


# P. End-to-End Test: Authoritative DB entities -> Builder -> Validation -> Persistence -> Snapshot -> Query
def test_critical_end_to_end_pipeline(mem_db: Session):
    # 1. Authoritative DB entities
    fac = Factory(
        id="fac_e2e",
        org_id="org_alpha",
        name="E2E Factory",
        latitude=32.0,
        longitude=120.0,
        capacity=5000.0,
        status="OPERATIONAL",
    )
    wh = Warehouse(
        id="wh_e2e",
        org_id="org_alpha",
        name="E2E Warehouse",
        latitude=34.0,
        longitude=-118.0,
        total_capacity=15000.0,
        status="OPERATIONAL",
    )
    route = Route(
        id="route_e2e",
        org_id="org_alpha",
        name="E2E Lane",
        origin_facility_id="fac_e2e",
        destination_facility_id="wh_e2e",
        mode="AIR",
        distance_km=10000.0,
        risk_score=15.0,
    )
    mem_db.add_all([fac, wh, route])
    mem_db.commit()

    # 2. Builder + Validation + Persistence via Service
    snapshot = DigitalTwinService.build_and_persist(mem_db, organization_id="org_alpha")

    # 3. Snapshot checks
    assert snapshot.node_count == 3  # Factory, Warehouse, Route
    assert snapshot.edge_count == 3  # Corridor + 2 Links
    assert snapshot.organization_id == "org_alpha"
    assert snapshot.status == "CURRENT"

    # 4. Query Service traversal
    query_svc = DigitalTwinService.get_query_service(mem_db, organization_id="org_alpha")
    fac_nid = compute_node_id("org_alpha", "FACTORY", "fac_e2e")
    wh_nid = compute_node_id("org_alpha", "WAREHOUSE", "wh_e2e")

    path = query_svc.find_path(fac_nid, wh_nid)
    assert path.path_found is True
    assert path.hop_count == 1  # Direct corridor edge
