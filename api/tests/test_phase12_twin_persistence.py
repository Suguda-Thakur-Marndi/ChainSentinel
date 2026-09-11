"""Unit tests for Phase 12 Digital Twin database persistence, transactional integrity, and idempotency."""

from __future__ import annotations

import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.digital_twin.errors import TwinPersistenceError, TwinTenantIsolationError
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_twin_fingerprint,
)
from app.digital_twin.repository import DigitalTwinRepository
from app.digital_twin.service import DigitalTwinService
from app.models.digital_twin import TwinEdge, TwinNode
from app.models.network import Factory, Warehouse
from app.models.tenancy import Organization
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


@pytest.fixture(scope="function")
def db_session():
    """Create an isolated in-memory test database and session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionMaker()

    # Seed test organization
    org = Organization(id="org_test", name="Test Org", slug="test-org")
    session.add(org)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _build_test_snapshot(org_id: str) -> DigitalTwinSnapshot:
    n1_id = compute_node_id(org_id, "FACTORY", "f1")
    n1_fp = compute_node_fingerprint(
        node_id=n1_id,
        organization_id=org_id,
        node_type="FACTORY",
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Assembly Factory",
        latitude=35.0,
        longitude=135.0,
        health_score=92.0,
        status="OPERATIONAL",
    )
    n1 = TwinNodeContract(
        node_id=n1_id,
        organization_id=org_id,
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Assembly Factory",
        latitude=35.0,
        longitude=135.0,
        health_score=92.0,
        status="OPERATIONAL",
        fingerprint=n1_fp,
    )

    n2_id = compute_node_id(org_id, "WAREHOUSE", "w1")
    n2_fp = compute_node_fingerprint(
        node_id=n2_id,
        organization_id=org_id,
        node_type="WAREHOUSE",
        source_entity_type="WAREHOUSE",
        source_entity_id="w1",
        label="Storage Warehouse",
        latitude=36.0,
        longitude=136.0,
        health_score=88.0,
        status="OPERATIONAL",
    )
    n2 = TwinNodeContract(
        node_id=n2_id,
        organization_id=org_id,
        node_type=TwinNodeType.WAREHOUSE,
        source_entity_type="WAREHOUSE",
        source_entity_id="w1",
        label="Storage Warehouse",
        latitude=36.0,
        longitude=136.0,
        health_score=88.0,
        status="OPERATIONAL",
        fingerprint=n2_fp,
    )

    e1_id = compute_edge_id(org_id, n1_id, n2_id, "TRANSPORT", "rel1")
    e1_fp = compute_edge_fingerprint(
        edge_id=e1_id,
        organization_id=org_id,
        from_node_id=n1_id,
        to_node_id=n2_id,
        edge_type="TRANSPORT",
        status="OPERATIONAL",
        flow_capacity=500.0,
        current_flow=200.0,
        risk_score=10.0,
    )
    e1 = TwinEdgeContract(
        edge_id=e1_id,
        organization_id=org_id,
        from_node_id=n1_id,
        to_node_id=n2_id,
        edge_type=TwinEdgeType.TRANSPORT,
        status="OPERATIONAL",
        flow_capacity=500.0,
        current_flow=200.0,
        risk_score=10.0,
        fingerprint=e1_fp,
    )

    twin_fp = compute_twin_fingerprint(
        f"twin-{org_id}", org_id, "1", [n1_fp, n2_fp], [e1_fp]
    )

    return DigitalTwinSnapshot(
        twin_id=f"twin-{org_id}",
        organization_id=org_id,
        version="1",
        node_count=2,
        edge_count=1,
        nodes={n1.node_id: n1, n2.node_id: n2},
        edges={e1.edge_id: e1},
        source_fingerprint=twin_fp,
        twin_fingerprint=twin_fp,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )


def test_persist_and_load_snapshot(db_session: Session):
    snapshot = _build_test_snapshot("org_test")

    # Persist into DB
    DigitalTwinRepository.persist_snapshot(db_session, snapshot)

    # Verify directly via ORM
    db_nodes = db_session.query(TwinNode).filter(TwinNode.org_id == "org_test").all()
    assert len(db_nodes) == 2
    db_edges = db_session.query(TwinEdge).filter(TwinEdge.org_id == "org_test").all()
    assert len(db_edges) == 1

    # Load via Repository
    loaded = DigitalTwinRepository.load_snapshot(db_session, "org_test")
    assert loaded is not None
    assert loaded.organization_id == "org_test"
    assert loaded.node_count == 2
    assert loaded.edge_count == 1
    assert set(loaded.nodes.keys()) == set(snapshot.nodes.keys())
    assert set(loaded.edges.keys()) == set(snapshot.edges.keys())


def test_persistence_is_idempotent(db_session: Session):
    snapshot = _build_test_snapshot("org_test")

    # First persistence
    DigitalTwinRepository.persist_snapshot(db_session, snapshot)
    count1_nodes = db_session.query(TwinNode).count()
    count1_edges = db_session.query(TwinEdge).count()

    # Second persistence with same snapshot (rebuild)
    DigitalTwinRepository.persist_snapshot(db_session, snapshot)
    count2_nodes = db_session.query(TwinNode).count()
    count2_edges = db_session.query(TwinEdge).count()

    assert count1_nodes == count2_nodes == 2
    assert count1_edges == count2_edges == 1


def test_persistence_rejects_invalid_snapshot_and_rolls_back(db_session: Session):
    snapshot = _build_test_snapshot("org_test")
    DigitalTwinRepository.persist_snapshot(db_session, snapshot)

    # Corrupt snapshot (orphan edge)
    corrupt_edge = TwinEdgeContract(
        edge_id="bad-edge",
        organization_id="org_test",
        from_node_id="nonexistent-1",
        to_node_id="nonexistent-2",
        edge_type=TwinEdgeType.TRANSPORT,
        fingerprint="0" * 64,
    )
    invalid_snapshot = DigitalTwinSnapshot(
        twin_id="twin-org_test",
        organization_id="org_test",
        version="1",
        node_count=2,
        edge_count=1,
        nodes=snapshot.nodes,
        edges={"bad-edge": corrupt_edge},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )

    with pytest.raises(TwinPersistenceError):
        DigitalTwinRepository.persist_snapshot(db_session, invalid_snapshot)

    # Previous valid state remains intact (no partial overwrite or deletion)
    assert db_session.query(TwinNode).filter(TwinNode.org_id == "org_test").count() == 2
    assert db_session.query(TwinEdge).filter(TwinEdge.org_id == "org_test").count() == 1


def test_persistence_tenant_isolation(db_session: Session):
    # Org A
    snap_a = _build_test_snapshot("org_test")
    DigitalTwinRepository.persist_snapshot(db_session, snap_a)

    # Org B
    org_b = Organization(id="org_b", name="Org B", slug="org-b")
    db_session.add(org_b)
    db_session.commit()
    snap_b = _build_test_snapshot("org_b")
    DigitalTwinRepository.persist_snapshot(db_session, snap_b)

    # Assert tenant separation
    loaded_a = DigitalTwinRepository.load_snapshot(db_session, "org_test")
    loaded_b = DigitalTwinRepository.load_snapshot(db_session, "org_b")
    assert loaded_a is not None and loaded_b is not None

    for node in loaded_a.nodes.values():
        assert node.organization_id == "org_test"
    for node in loaded_b.nodes.values():
        assert node.organization_id == "org_b"


def test_digital_twin_service_end_to_end(db_session: Session):
    # Seed operational tables in DB
    fac = Factory(
        id="fac_100",
        org_id="org_test",
        name="Auto Plant Alpha",
        capacity=10000.0,
        status="OPERATIONAL",
    )
    wh = Warehouse(
        id="wh_100",
        org_id="org_test",
        name="Distribution Center Beta",
        total_capacity=20000.0,
        status="OPERATIONAL",
    )
    db_session.add_all([fac, wh])
    db_session.commit()

    # Build and persist via Service
    snapshot = DigitalTwinService.build_and_persist(db_session, organization_id="org_test")
    assert snapshot.node_count == 2
    assert snapshot.edge_count == 0

    # Query via Service
    query_svc = DigitalTwinService.get_query_service(db_session, organization_id="org_test")
    assert query_svc.get_snapshot().node_count == 2

    fac_node_id = compute_node_id("org_test", "FACTORY", "fac_100")
    node = query_svc.get_node(fac_node_id)
    assert node.label == "Auto Plant Alpha"
