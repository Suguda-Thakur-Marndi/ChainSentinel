"""Unit tests for Phase 12 Digital Twin Query Service, BFS traversal, and cycle handling."""

from __future__ import annotations

import datetime
import pytest

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.digital_twin.errors import TwinQueryError, TwinTenantIsolationError
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_twin_fingerprint,
)
from app.digital_twin.query import DigitalTwinQueryService
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


def _create_node(org_id: str, node_type: TwinNodeType, entity_id: str, label: str) -> TwinNodeContract:
    nid = compute_node_id(org_id, node_type.value, entity_id)
    fp = compute_node_fingerprint(
        node_id=nid,
        organization_id=org_id,
        node_type=node_type.value,
        source_entity_type=node_type.value,
        source_entity_id=entity_id,
        label=label,
    )
    return TwinNodeContract(
        node_id=nid,
        organization_id=org_id,
        node_type=node_type,
        source_entity_type=node_type.value,
        source_entity_id=entity_id,
        label=label,
        fingerprint=fp,
    )


def _create_edge(org_id: str, from_nid: str, to_nid: str, edge_type: TwinEdgeType, rel_id: str = "") -> TwinEdgeContract:
    eid = compute_edge_id(org_id, from_nid, to_nid, edge_type.value, rel_id)
    fp = compute_edge_fingerprint(
        edge_id=eid,
        organization_id=org_id,
        from_node_id=from_nid,
        to_node_id=to_nid,
        edge_type=edge_type.value,
    )
    return TwinEdgeContract(
        edge_id=eid,
        organization_id=org_id,
        from_node_id=from_nid,
        to_node_id=to_nid,
        edge_type=edge_type,
        fingerprint=fp,
    )


@pytest.fixture
def sample_query_service():
    """Create a sample query service with a multi-hop cyclic graph:

    (A) -> (B) -> (C) -> (A)  [Cycle]
            |
            v
           (D) -> (E)
    """
    org = "org_query"
    node_a = _create_node(org, TwinNodeType.SUPPLIER, "a", "Supplier A")
    node_b = _create_node(org, TwinNodeType.FACTORY, "b", "Factory B")
    node_c = _create_node(org, TwinNodeType.WAREHOUSE, "c", "Warehouse C")
    node_d = _create_node(org, TwinNodeType.PORT, "d", "Port D")
    node_e = _create_node(org, TwinNodeType.WAREHOUSE, "e", "Warehouse E")

    edge_ab = _create_edge(org, node_a.node_id, node_b.node_id, TwinEdgeType.FLOW, "ab")
    edge_bc = _create_edge(org, node_b.node_id, node_c.node_id, TwinEdgeType.FLOW, "bc")
    edge_ca = _create_edge(org, node_c.node_id, node_a.node_id, TwinEdgeType.FLOW, "ca")  # Cycle!
    edge_bd = _create_edge(org, node_b.node_id, node_d.node_id, TwinEdgeType.TRANSPORT, "bd")
    edge_de = _create_edge(org, node_d.node_id, node_e.node_id, TwinEdgeType.TRANSPORT, "de")

    nodes = {n.node_id: n for n in [node_a, node_b, node_c, node_d, node_e]}
    edges = {e.edge_id: e for e in [edge_ab, edge_bc, edge_ca, edge_bd, edge_de]}

    tfp = compute_twin_fingerprint(
        "twin_query", org, "1", [n.fingerprint for n in nodes.values()], [e.fingerprint for e in edges.values()]
    )
    snapshot = DigitalTwinSnapshot(
        twin_id="twin_query",
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
    return DigitalTwinQueryService(snapshot), nodes, edges


def test_query_get_node(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = list(nodes.values())[0]

    retrieved = service.get_node(node_a.node_id)
    assert retrieved.node_id == node_a.node_id
    assert retrieved.label == "Supplier A"


def test_query_get_unknown_node(sample_query_service):
    service, _, _ = sample_query_service
    with pytest.raises(TwinQueryError):
        service.get_node("non-existent-node-id")


def test_query_outbound_and_inbound_edges(sample_query_service):
    service, nodes, _ = sample_query_service
    # Node B has outbound edges to C and D, and inbound edge from A
    node_b = [n for n in nodes.values() if n.label == "Factory B"][0]

    out_edges = service.get_outbound_edges(node_b.node_id)
    assert len(out_edges) == 2

    in_edges = service.get_inbound_edges(node_b.node_id)
    assert len(in_edges) == 1
    assert in_edges[0].from_node_id == [n for n in nodes.values() if n.label == "Supplier A"][0].node_id


def test_query_neighbors(sample_query_service):
    service, nodes, _ = sample_query_service
    node_b = [n for n in nodes.values() if n.label == "Factory B"][0]

    out_neighbors = service.get_neighbors(node_b.node_id, direction="outbound")
    assert len(out_neighbors) == 2
    out_labels = {n.label for n in out_neighbors}
    assert out_labels == {"Warehouse C", "Port D"}

    in_neighbors = service.get_neighbors(node_b.node_id, direction="inbound")
    assert len(in_neighbors) == 1
    assert in_neighbors[0].label == "Supplier A"

    both_neighbors = service.get_neighbors(node_b.node_id, direction="both")
    assert len(both_neighbors) == 3


def test_query_neighbors_filtered_by_type(sample_query_service):
    service, nodes, _ = sample_query_service
    node_b = [n for n in nodes.values() if n.label == "Factory B"][0]

    port_neighbors = service.get_neighbors(
        node_b.node_id, direction="outbound", node_type=TwinNodeType.PORT
    )
    assert len(port_neighbors) == 1
    assert port_neighbors[0].label == "Port D"


def test_query_subgraph_cycle_handling(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]

    # Traversal starting at A encountering cycle A -> B -> C -> A
    # Must terminate without infinite loop
    subgraph = service.get_subgraph(
        root_node_id=node_a.node_id, max_depth=5, max_nodes=50, max_edges=50
    )
    assert subgraph.root_node_id == node_a.node_id
    assert subgraph.total_nodes == 5  # Reaches all 5 nodes
    assert subgraph.total_edges == 5


def test_query_subgraph_bounded_depth(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]

    # At depth 1, only A and its direct neighbor B should be reached
    subgraph = service.get_subgraph(root_node_id=node_a.node_id, max_depth=1)
    assert subgraph.depth == 1
    labels = {n.label for n in subgraph.nodes}
    assert labels == {"Supplier A", "Factory B"}


def test_query_find_path_reachability(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]
    node_e = [n for n in nodes.values() if n.label == "Warehouse E"][0]

    # Path from A -> B -> D -> E
    res = service.find_path(source_node_id=node_a.node_id, target_node_id=node_e.node_id)
    assert res.path_found is True
    assert res.hop_count == 3
    assert res.node_ids == [
        node_a.node_id,
        [n for n in nodes.values() if n.label == "Factory B"][0].node_id,
        [n for n in nodes.values() if n.label == "Port D"][0].node_id,
        node_e.node_id,
    ]


def test_query_find_path_same_node(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]

    res = service.find_path(source_node_id=node_a.node_id, target_node_id=node_a.node_id)
    assert res.path_found is True
    assert res.hop_count == 0
    assert res.node_ids == [node_a.node_id]


def test_query_find_path_unreachable():
    org = "org_unreach"
    n1 = _create_node(org, TwinNodeType.FACTORY, "f1", "Factory 1")
    n2 = _create_node(org, TwinNodeType.WAREHOUSE, "w1", "Warehouse 1")
    snap = DigitalTwinSnapshot(
        twin_id="twin_unreach",
        organization_id=org,
        version="1",
        node_count=2,
        edge_count=0,
        nodes={n1.node_id: n1, n2.node_id: n2},
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    service = DigitalTwinQueryService(snap)
    res = service.find_path(source_node_id=n1.node_id, target_node_id=n2.node_id)
    assert res.path_found is False
    assert res.hop_count == 0
    assert res.node_ids == []


def test_query_constructor_rejects_none():
    with pytest.raises(TwinQueryError):
        DigitalTwinQueryService(None)  # type: ignore


def test_query_empty_node_id_raises_error(sample_query_service):
    service, _, _ = sample_query_service
    with pytest.raises(TwinQueryError):
        service.get_node("")


def test_query_inbound_edges_none_exists(sample_query_service):
    service, nodes, _ = sample_query_service
    # Node A is the root with no inbound edges from outside the cycle except C -> A
    # Warehouse E has no outbound edges
    node_e = [n for n in nodes.values() if n.label == "Warehouse E"][0]
    out_edges = service.get_outbound_edges(node_e.node_id)
    assert len(out_edges) == 0


def test_query_neighbors_empty_for_disconnected_node():
    org = "org_disc"
    n1 = _create_node(org, TwinNodeType.PORT, "p1", "Island Port")
    snap = DigitalTwinSnapshot(
        twin_id="twin_disc",
        organization_id=org,
        version="1",
        node_count=1,
        edge_count=0,
        nodes={n1.node_id: n1},
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    assert svc.get_neighbors(n1.node_id) == []


def test_query_neighbors_non_matching_node_type(sample_query_service):
    service, nodes, _ = sample_query_service
    node_b = [n for n in nodes.values() if n.label == "Factory B"][0]
    # Node B connects to Warehouse C and Port D, none are CUSTOMER
    matches = service.get_neighbors(
        node_b.node_id, direction="outbound", node_type=TwinNodeType.CUSTOMER
    )
    assert matches == []


def test_query_neighbors_non_matching_edge_type(sample_query_service):
    service, nodes, _ = sample_query_service
    node_b = [n for n in nodes.values() if n.label == "Factory B"][0]
    # Outbound edges are FLOW and TRANSPORT, none are CARRIES
    matches = service.get_neighbors(
        node_b.node_id, direction="outbound", edge_type=TwinEdgeType.CARRIES
    )
    assert matches == []


def test_query_subgraph_inbound_direction(sample_query_service):
    service, nodes, _ = sample_query_service
    node_e = [n for n in nodes.values() if n.label == "Warehouse E"][0]
    # Inbound from E: D -> E, B -> D, etc.
    subgraph = service.get_subgraph(root_node_id=node_e.node_id, direction="inbound", max_depth=2)
    labels = {n.label for n in subgraph.nodes}
    assert "Warehouse E" in labels
    assert "Port D" in labels
    assert "Factory B" in labels


def test_query_subgraph_both_directions(sample_query_service):
    service, nodes, _ = sample_query_service
    node_d = [n for n in nodes.values() if n.label == "Port D"][0]
    # Both: inbound from B, outbound to E
    subgraph = service.get_subgraph(root_node_id=node_d.node_id, direction="both", max_depth=1)
    labels = {n.label for n in subgraph.nodes}
    assert "Port D" in labels
    assert "Factory B" in labels
    assert "Warehouse E" in labels


def test_query_subgraph_max_nodes_clamp(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]
    subgraph = service.get_subgraph(root_node_id=node_a.node_id, max_nodes=2)
    assert subgraph.total_nodes <= 2


def test_query_subgraph_max_edges_clamp(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]
    subgraph = service.get_subgraph(root_node_id=node_a.node_id, max_edges=1)
    assert subgraph.total_edges <= 1


def test_query_path_depth_boundary_exceeded(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]
    node_e = [n for n in nodes.values() if n.label == "Warehouse E"][0]
    # Path is 3 hops: A -> B -> D -> E. If max_depth=2, it cannot reach E
    res = service.find_path(source_node_id=node_a.node_id, target_node_id=node_e.node_id, max_depth=2)
    assert res.path_found is False


def test_query_path_single_hop(sample_query_service):
    service, nodes, _ = sample_query_service
    node_a = [n for n in nodes.values() if n.label == "Supplier A"][0]
    node_b = [n for n in nodes.values() if n.label == "Factory B"][0]
    res = service.find_path(source_node_id=node_a.node_id, target_node_id=node_b.node_id)
    assert res.path_found is True
    assert res.hop_count == 1
    assert res.node_ids == [node_a.node_id, node_b.node_id]


def test_query_linear_chain_five_nodes():
    org = "org_chain"
    chain_nodes = [_create_node(org, TwinNodeType.WAREHOUSE, f"chain_{i}", f"Chain {i}") for i in range(5)]
    chain_edges = [
        _create_edge(org, chain_nodes[i].node_id, chain_nodes[i + 1].node_id, TwinEdgeType.FLOW, f"e{i}")
        for i in range(4)
    ]
    nodes = {n.node_id: n for n in chain_nodes}
    edges = {e.edge_id: e for e in chain_edges}
    tfp = compute_twin_fingerprint("twin_chain", org, "1", [n.fingerprint for n in chain_nodes], [e.fingerprint for e in chain_edges])
    snap = DigitalTwinSnapshot(
        twin_id="twin_chain",
        organization_id=org,
        version="1",
        node_count=5,
        edge_count=4,
        nodes=nodes,
        edges=edges,
        source_fingerprint=tfp,
        twin_fingerprint=tfp,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    path = svc.find_path(chain_nodes[0].node_id, chain_nodes[4].node_id, max_depth=6)
    assert path.path_found is True
    assert path.hop_count == 4


def test_query_star_topology_fanout():
    org = "org_star"
    center = _create_node(org, TwinNodeType.PORT, "hub", "Central Hub")
    spokes = [_create_node(org, TwinNodeType.WAREHOUSE, f"spoke_{i}", f"Spoke {i}") for i in range(8)]
    edges_list = [
        _create_edge(org, center.node_id, sp.node_id, TwinEdgeType.TRANSPORT, f"sp_{i}")
        for i, sp in enumerate(spokes)
    ]
    all_nodes = {n.node_id: n for n in [center] + spokes}
    all_edges = {e.edge_id: e for e in edges_list}
    tfp = compute_twin_fingerprint("twin_star", org, "1", [n.fingerprint for n in all_nodes.values()], [e.fingerprint for e in all_edges.values()])
    snap = DigitalTwinSnapshot(
        twin_id="twin_star",
        organization_id=org,
        version="1",
        node_count=len(all_nodes),
        edge_count=len(all_edges),
        nodes=all_nodes,
        edges=all_edges,
        source_fingerprint=tfp,
        twin_fingerprint=tfp,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    neighbors = svc.get_neighbors(center.node_id, direction="outbound")
    assert len(neighbors) == 8

