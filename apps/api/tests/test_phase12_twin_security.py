"""Unit tests for Phase 12 Digital Twin Security, tenant isolation, and bounding protections."""

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
from app.digital_twin.observability import TwinObservability
from app.digital_twin.query import (
    MAX_ALLOWED_DEPTH,
    MAX_ALLOWED_EDGES,
    MAX_ALLOWED_NODES,
    DigitalTwinQueryService,
)
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType
from app.services.audit_service import sanitize_payload


def _make_node(org_id: str, node_type: TwinNodeType, entity_id: str, label: str) -> TwinNodeContract:
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


def test_tenant_isolation_node_access():
    n_a = _make_node("org_alpha", TwinNodeType.FACTORY, "f1", "Alpha Plant")
    n_b = _make_node("org_beta", TwinNodeType.FACTORY, "f2", "Beta Plant")

    snap_a = DigitalTwinSnapshot(
        twin_id="twin_a",
        organization_id="org_alpha",
        version="1",
        node_count=1,
        edge_count=0,
        nodes={n_a.node_id: n_a},
        edges={},
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    query_svc = DigitalTwinQueryService(snap_a)

    # Accessing Alpha's node succeeds
    assert query_svc.get_node(n_a.node_id).label == "Alpha Plant"

    # Querying Beta's node fails with TwinQueryError
    with pytest.raises(TwinQueryError):
        query_svc.get_node(n_b.node_id)


def test_traversal_hard_limits_enforced():
    org = "org_limits"
    # Create a linear chain of 20 nodes: N0 -> N1 -> N2 -> ... -> N19
    nodes: dict[str, TwinNodeContract] = {}
    edges: dict[str, TwinEdgeContract] = {}

    prev_id = None
    for i in range(20):
        node = _make_node(org, TwinNodeType.WAREHOUSE, f"w{i}", f"WH {i}")
        nodes[node.node_id] = node
        if prev_id:
            eid = compute_edge_id(org, prev_id, node.node_id, "TRANSPORT", f"e{i}")
            efp = compute_edge_fingerprint(
                edge_id=eid,
                organization_id=org,
                from_node_id=prev_id,
                to_node_id=node.node_id,
                edge_type="TRANSPORT",
            )
            edges[eid] = TwinEdgeContract(
                edge_id=eid,
                organization_id=org,
                from_node_id=prev_id,
                to_node_id=node.node_id,
                edge_type=TwinEdgeType.TRANSPORT,
                fingerprint=efp,
            )
        prev_id = node.node_id

    snap = DigitalTwinSnapshot(
        twin_id="twin_limits",
        organization_id=org,
        version="1",
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=nodes,
        edges=edges,
        source_fingerprint="0" * 64,
        twin_fingerprint="0" * 64,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    svc = DigitalTwinQueryService(snap)
    first_node_id = list(nodes.keys())[0]

    # Request excessive depth (e.g. 999). Should be clamped to MAX_ALLOWED_DEPTH (10)
    subgraph = svc.get_subgraph(root_node_id=first_node_id, max_depth=999)
    assert subgraph.depth == MAX_ALLOWED_DEPTH
    assert subgraph.total_nodes <= MAX_ALLOWED_DEPTH + 1


def test_forged_node_id_rejected():
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
        svc.get_node("synthetic-forged-node-id")


def test_audit_scrubbing_sensitive_keys():
    raw_payload = {
        "twin_id": "twin-123",
        "api_key": "sk-secret-token-12345",
        "password": "super-secret-password",
        "access_token": "bearer-eyJh...",
        "organization_id": "org-safe",
    }
    cleaned = sanitize_payload(raw_payload)
    assert cleaned["twin_id"] == "twin-123"
    assert cleaned["organization_id"] == "org-safe"
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["access_token"] == "[REDACTED]"


def test_query_service_read_only_semantics():
    snap = DigitalTwinSnapshot(
        twin_id="twin_ro",
        organization_id="org_ro",
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

    # Verify that query service has no mutating methods
    mutating_methods = [m for m in dir(svc) if any(kw in m for kw in ["save", "delete", "update", "insert", "write", "mutate"])]
    assert len(mutating_methods) == 0
