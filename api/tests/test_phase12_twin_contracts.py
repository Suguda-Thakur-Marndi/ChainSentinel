"""Unit tests for Phase 12 Digital Twin contracts, Pydantic schemas, and immutability invariants."""

from __future__ import annotations

import datetime
import pytest
from pydantic import ValidationError

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
    TwinPathResult,
    TwinQuery,
    TwinSubgraph,
    TwinValidationResult,
)
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


def test_valid_twin_node_contract_creation():
    node = TwinNodeContract(
        node_id="node-12345678-1234-1234-1234-123456789abc",
        organization_id="org-acme",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="fac-001",
        label="Acme Assembly Plant",
        latitude=37.7749,
        longitude=-122.4194,
        health_score=95.0,
        status="OPERATIONAL",
        properties={"capacity": 50000},
        source_timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        fingerprint="a" * 64,
    )
    assert node.node_id == "node-12345678-1234-1234-1234-123456789abc"
    assert node.organization_id == "org-acme"
    assert node.node_type == TwinNodeType.FACTORY
    assert node.latitude == 37.7749
    assert node.longitude == -122.4194
    assert node.health_score == 95.0
    assert node.properties["capacity"] == 50000


def test_twin_node_contract_extra_field_forbidden():
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.SUPPLIER,
            source_entity_type="SUPPLIER",
            source_entity_id="sup-001",
            label="Acme Supplier",
            fingerprint="b" * 64,
            unexpected_field="disallowed",
        )


def test_twin_node_contract_immutability():
    node = TwinNodeContract(
        node_id="node-123",
        organization_id="org-acme",
        node_type=TwinNodeType.SUPPLIER,
        source_entity_type="SUPPLIER",
        source_entity_id="sup-001",
        label="Acme Supplier",
        fingerprint="c" * 64,
    )
    with pytest.raises(ValidationError):
        node.label = "Modified Name"  # type: ignore


def test_twin_node_contract_latitude_bounds():
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.PORT,
            source_entity_type="PORT",
            source_entity_id="port-01",
            label="Port South",
            latitude=-95.0,  # invalid < -90
            longitude=0.0,
            fingerprint="d" * 64,
        )
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.PORT,
            source_entity_type="PORT",
            source_entity_id="port-01",
            label="Port North",
            latitude=95.0,  # invalid > 90
            longitude=0.0,
            fingerprint="d" * 64,
        )


def test_twin_node_contract_longitude_bounds():
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.PORT,
            source_entity_type="PORT",
            source_entity_id="port-01",
            label="Port West",
            latitude=0.0,
            longitude=-185.0,  # invalid < -180
            fingerprint="e" * 64,
        )
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.PORT,
            source_entity_type="PORT",
            source_entity_id="port-01",
            label="Port East",
            latitude=0.0,
            longitude=185.0,  # invalid > 180
            fingerprint="e" * 64,
        )


def test_twin_node_contract_health_score_bounds():
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.WAREHOUSE,
            source_entity_type="WAREHOUSE",
            source_entity_id="wh-01",
            label="Warehouse 1",
            health_score=-5.0,
            fingerprint="f" * 64,
        )
    with pytest.raises(ValidationError):
        TwinNodeContract(
            node_id="node-123",
            organization_id="org-acme",
            node_type=TwinNodeType.WAREHOUSE,
            source_entity_type="WAREHOUSE",
            source_entity_id="wh-01",
            label="Warehouse 1",
            health_score=105.0,
            fingerprint="f" * 64,
        )


def test_twin_edge_contract_valid_creation():
    edge = TwinEdgeContract(
        edge_id="edge-12345678-1234-1234-1234-123456789abc",
        organization_id="org-acme",
        from_node_id="node-origin",
        to_node_id="node-destination",
        edge_type=TwinEdgeType.TRANSPORT,
        status="OPERATIONAL",
        flow_capacity=1000.0,
        current_flow=450.0,
        risk_score=15.0,
        properties={"mode": "OCEAN"},
        source_reference="route:rt-001",
        fingerprint="1" * 64,
    )
    assert edge.edge_id == "edge-12345678-1234-1234-1234-123456789abc"
    assert edge.organization_id == "org-acme"
    assert edge.edge_type == TwinEdgeType.TRANSPORT
    assert edge.flow_capacity == 1000.0
    assert edge.current_flow == 450.0
    assert edge.risk_score == 15.0


def test_twin_edge_contract_extra_field_forbidden():
    with pytest.raises(ValidationError):
        TwinEdgeContract(
            edge_id="edge-123",
            organization_id="org-acme",
            from_node_id="node-1",
            to_node_id="node-2",
            edge_type=TwinEdgeType.FLOW,
            fingerprint="2" * 64,
            forbidden_attr="illegal",
        )


def test_twin_edge_contract_immutability():
    edge = TwinEdgeContract(
        edge_id="edge-123",
        organization_id="org-acme",
        from_node_id="node-1",
        to_node_id="node-2",
        edge_type=TwinEdgeType.FLOW,
        fingerprint="3" * 64,
    )
    with pytest.raises(ValidationError):
        edge.current_flow = 999.0  # type: ignore


def test_twin_edge_contract_metrics_bounds():
    with pytest.raises(ValidationError):
        TwinEdgeContract(
            edge_id="edge-1",
            organization_id="org-1",
            from_node_id="n1",
            to_node_id="n2",
            edge_type=TwinEdgeType.FLOW,
            flow_capacity=-1.0,
            fingerprint="4" * 64,
        )
    with pytest.raises(ValidationError):
        TwinEdgeContract(
            edge_id="edge-1",
            organization_id="org-1",
            from_node_id="n1",
            to_node_id="n2",
            edge_type=TwinEdgeType.FLOW,
            current_flow=-5.0,
            fingerprint="4" * 64,
        )
    with pytest.raises(ValidationError):
        TwinEdgeContract(
            edge_id="edge-1",
            organization_id="org-1",
            from_node_id="n1",
            to_node_id="n2",
            edge_type=TwinEdgeType.FLOW,
            risk_score=105.0,
            fingerprint="4" * 64,
        )


def test_digital_twin_snapshot_creation_and_immutability():
    snapshot = DigitalTwinSnapshot(
        twin_id="twin-org1",
        organization_id="org1",
        version="1",
        node_count=0,
        edge_count=0,
        nodes={},
        edges={},
        source_fingerprint="s" * 64,
        twin_fingerprint="t" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    assert snapshot.twin_id == "twin-org1"
    assert snapshot.version == "1"
    assert snapshot.node_count == 0

    with pytest.raises(ValidationError):
        snapshot.version = "2"  # type: ignore


def test_twin_subgraph_contract():
    subgraph = TwinSubgraph(
        root_node_id="root-1",
        depth=2,
        nodes=[],
        edges=[],
        total_nodes=0,
        total_edges=0,
    )
    assert subgraph.root_node_id == "root-1"
    assert subgraph.depth == 2
    assert subgraph.total_nodes == 0


def test_twin_query_bounds():
    query = TwinQuery(max_depth=5, max_nodes=50, max_edges=100)
    assert query.max_depth == 5
    assert query.max_nodes == 50

    with pytest.raises(ValidationError):
        TwinQuery(max_depth=15)  # exceeds le=10

    with pytest.raises(ValidationError):
        TwinQuery(max_nodes=600)  # exceeds le=500

    with pytest.raises(ValidationError):
        TwinQuery(max_edges=2000)  # exceeds le=1000


def test_twin_path_result_contract():
    result = TwinPathResult(
        source_node_id="n1",
        target_node_id="n3",
        path_found=True,
        node_ids=["n1", "n2", "n3"],
        edge_ids=["e1", "e2"],
        hop_count=2,
    )
    assert result.path_found is True
    assert result.hop_count == 2
    assert len(result.node_ids) == 3


def test_twin_validation_result_contract():
    res = TwinValidationResult(
        is_valid=True,
        errors=[],
        warnings=["Non-critical warning"],
        node_count=10,
        edge_count=15,
    )
    assert res.is_valid is True
    assert len(res.warnings) == 1
    assert res.node_count == 10


def test_twin_node_type_enums_supported():
    expected_types = [
        "SUPPLIER",
        "SUPPLIER_SITE",
        "FACTORY",
        "WAREHOUSE",
        "PORT",
        "CARRIER",
        "ROUTE",
        "SHIPMENT",
        "PRODUCT",
        "CUSTOMER",
        "CUSTOM",
    ]
    for et in expected_types:
        assert et in [t.value for t in TwinNodeType]


def test_twin_edge_type_enums_supported():
    expected_edges = [
        "FLOW",
        "TRANSPORT",
        "DEPENDENCY",
        "LOCATED_AT",
        "OPERATES",
        "CONNECTS",
        "CARRIES",
        "SUPPLIES",
    ]
    for ee in expected_edges:
        assert ee in [e.value for e in TwinEdgeType]


def test_twin_node_contract_empty_properties_default():
    node = TwinNodeContract(
        node_id="nid-101",
        organization_id="org1",
        node_type=TwinNodeType.PORT,
        source_entity_type="PORT",
        source_entity_id="p101",
        label="Default Props Port",
        fingerprint="0" * 64,
    )
    assert node.properties == {}
    assert node.latitude is None
    assert node.longitude is None
    assert node.health_score is None


def test_twin_node_contract_custom_status():
    node = TwinNodeContract(
        node_id="nid-102",
        organization_id="org1",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f102",
        label="Custom Status Plant",
        status="MAINTENANCE",
        fingerprint="0" * 64,
    )
    assert node.status == "MAINTENANCE"


def test_twin_edge_contract_zero_flow_and_risk():
    edge = TwinEdgeContract(
        edge_id="eid-103",
        organization_id="org1",
        from_node_id="n1",
        to_node_id="n2",
        edge_type=TwinEdgeType.FLOW,
        flow_capacity=0.0,
        current_flow=0.0,
        risk_score=0.0,
        fingerprint="0" * 64,
    )
    assert edge.flow_capacity == 0.0
    assert edge.current_flow == 0.0
    assert edge.risk_score == 0.0


def test_twin_edge_contract_max_risk_score():
    edge = TwinEdgeContract(
        edge_id="eid-104",
        organization_id="org1",
        from_node_id="n1",
        to_node_id="n2",
        edge_type=TwinEdgeType.TRANSPORT,
        risk_score=100.0,
        fingerprint="0" * 64,
    )
    assert edge.risk_score == 100.0


def test_twin_edge_contract_nested_properties():
    nested = {
        "corridor_stats": {"avg_speed_kmh": 45.2, "reliability": 0.98},
        "carrier_history": ["C1", "C2"],
    }
    edge = TwinEdgeContract(
        edge_id="eid-105",
        organization_id="org1",
        from_node_id="n1",
        to_node_id="n2",
        edge_type=TwinEdgeType.CONNECTS,
        properties=nested,
        fingerprint="0" * 64,
    )
    assert edge.properties["corridor_stats"]["avg_speed_kmh"] == 45.2
    assert len(edge.properties["carrier_history"]) == 2


def test_snapshot_model_dump_roundtrip():
    node = TwinNodeContract(
        node_id="n1",
        organization_id="org1",
        node_type=TwinNodeType.SUPPLIER,
        source_entity_type="SUPPLIER",
        source_entity_id="s1",
        label="Supplier S1",
        fingerprint="1" * 64,
    )
    edge = TwinEdgeContract(
        edge_id="e1",
        organization_id="org1",
        from_node_id="n1",
        to_node_id="n1",
        edge_type=TwinEdgeType.DEPENDENCY,
        fingerprint="2" * 64,
    )
    snap = DigitalTwinSnapshot(
        twin_id="twin-roundtrip",
        organization_id="org1",
        version="1",
        node_count=1,
        edge_count=1,
        nodes={node.node_id: node},
        edges={edge.edge_id: edge},
        source_fingerprint="s" * 64,
        twin_fingerprint="t" * 64,
        generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        status="CURRENT",
    )
    dumped = snap.model_dump()
    assert dumped["twin_id"] == "twin-roundtrip"
    assert dumped["node_count"] == 1
    assert dumped["edge_count"] == 1

    restored = DigitalTwinSnapshot.model_validate(dumped)
    assert restored.twin_id == snap.twin_id
    assert restored.nodes["n1"].label == "Supplier S1"


def test_twin_query_defaults():
    q = TwinQuery()
    assert q.max_depth == 3
    assert q.max_nodes == 100
    assert q.max_edges == 200
    assert q.node_id is None
    assert q.node_types is None


def test_twin_query_min_bounds():
    with pytest.raises(ValidationError):
        TwinQuery(max_depth=0)
    with pytest.raises(ValidationError):
        TwinQuery(max_nodes=0)
    with pytest.raises(ValidationError):
        TwinQuery(max_edges=0)


def test_twin_path_result_empty_discovery():
    res = TwinPathResult(
        source_node_id="src",
        target_node_id="dst",
        path_found=False,
    )
    assert res.path_found is False
    assert res.node_ids == []
    assert res.edge_ids == []
    assert res.hop_count == 0


def test_twin_subgraph_zero_depth():
    sub = TwinSubgraph(
        root_node_id="root-zero",
        depth=0,
        nodes=[],
        edges=[],
        total_nodes=0,
        total_edges=0,
    )
    assert sub.depth == 0
    assert sub.total_nodes == 0


def test_twin_validation_result_warning_collection():
    res = TwinValidationResult(
        is_valid=True,
        errors=[],
        warnings=["High latency observed", "Minor data gap"],
        node_count=5,
        edge_count=4,
    )
    assert res.is_valid is True
    assert len(res.warnings) == 2


def test_twin_node_type_str_enum_equality():
    assert TwinNodeType.FACTORY == "FACTORY"
    assert TwinNodeType.WAREHOUSE == "WAREHOUSE"
    assert TwinNodeType.SHIPMENT == "SHIPMENT"


def test_twin_edge_type_str_enum_equality():
    assert TwinEdgeType.FLOW == "FLOW"
    assert TwinEdgeType.TRANSPORT == "TRANSPORT"
    assert TwinEdgeType.CARRIES == "CARRIES"
    assert TwinEdgeType.SUPPLIES == "SUPPLIES"

