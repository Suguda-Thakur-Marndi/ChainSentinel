"""Unit tests for Phase 12 Digital Twin graph validation engine."""

from __future__ import annotations

import datetime
import pytest

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.digital_twin.errors import (
    TwinFingerprintError,
    TwinReferenceError,
    TwinTenantIsolationError,
    TwinValidationError,
)
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_twin_fingerprint,
)
from app.digital_twin.validator import TwinGraphValidator
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


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


def _make_edge(org_id: str, from_nid: str, to_nid: str, edge_type: TwinEdgeType, rel_id: str = "") -> TwinEdgeContract:
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


def test_validation_passes_on_valid_graph():
    n1 = _make_node("org1", TwinNodeType.FACTORY, "f1", "Factory 1")
    n2 = _make_node("org1", TwinNodeType.WAREHOUSE, "w1", "Warehouse 1")
    e1 = _make_edge("org1", n1.node_id, n2.node_id, TwinEdgeType.TRANSPORT)

    res = TwinGraphValidator.validate_graph(nodes=[n1, n2], edges=[e1], expected_org_id="org1")
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_validation_detects_orphan_edge_source():
    n2 = _make_node("org1", TwinNodeType.WAREHOUSE, "w1", "Warehouse 1")
    e1 = _make_edge("org1", "missing-source-id", n2.node_id, TwinEdgeType.TRANSPORT)

    res = TwinGraphValidator.validate_graph(nodes=[n2], edges=[e1], expected_org_id="org1")
    assert res.is_valid is False
    assert any("source node 'missing-source-id' does not exist" in err for err in res.errors)

    with pytest.raises(TwinReferenceError):
        TwinGraphValidator.assert_valid_graph(nodes=[n2], edges=[e1], expected_org_id="org1")


def test_validation_detects_orphan_edge_target():
    n1 = _make_node("org1", TwinNodeType.FACTORY, "f1", "Factory 1")
    e1 = _make_edge("org1", n1.node_id, "missing-target-id", TwinEdgeType.TRANSPORT)

    res = TwinGraphValidator.validate_graph(nodes=[n1], edges=[e1], expected_org_id="org1")
    assert res.is_valid is False
    assert any("target node 'missing-target-id' does not exist" in err for err in res.errors)

    with pytest.raises(TwinReferenceError):
        TwinGraphValidator.assert_valid_graph(nodes=[n1], edges=[e1], expected_org_id="org1")


def test_validation_detects_cross_tenant_node():
    n1 = _make_node("org_beta", TwinNodeType.FACTORY, "f1", "Factory 1")

    res = TwinGraphValidator.validate_graph(nodes=[n1], edges=[], expected_org_id="org_alpha")
    assert res.is_valid is False
    assert any("tenant mismatch" in err for err in res.errors)

    with pytest.raises(TwinTenantIsolationError):
        TwinGraphValidator.assert_valid_graph(nodes=[n1], edges=[], expected_org_id="org_alpha")


def test_validation_detects_cross_tenant_edge():
    n1 = _make_node("org_alpha", TwinNodeType.FACTORY, "f1", "Factory 1")
    n2 = _make_node("org_alpha", TwinNodeType.WAREHOUSE, "w1", "Warehouse 1")
    e1 = _make_edge("org_beta", n1.node_id, n2.node_id, TwinEdgeType.TRANSPORT)

    res = TwinGraphValidator.validate_graph(nodes=[n1, n2], edges=[e1], expected_org_id="org_alpha")
    assert res.is_valid is False
    assert any("tenant mismatch" in err for err in res.errors)

    with pytest.raises(TwinTenantIsolationError):
        TwinGraphValidator.assert_valid_graph(nodes=[n1, n2], edges=[e1], expected_org_id="org_alpha")


def test_validation_detects_duplicate_node_id():
    n1 = _make_node("org1", TwinNodeType.FACTORY, "f1", "Factory 1")

    res = TwinGraphValidator.validate_graph(nodes=[n1, n1], edges=[], expected_org_id="org1")
    assert res.is_valid is False
    assert any("Duplicate node ID detected" in err for err in res.errors)


def test_validation_detects_duplicate_edge_id():
    n1 = _make_node("org1", TwinNodeType.FACTORY, "f1", "Factory 1")
    n2 = _make_node("org1", TwinNodeType.WAREHOUSE, "w1", "Warehouse 1")
    e1 = _make_edge("org1", n1.node_id, n2.node_id, TwinEdgeType.TRANSPORT)

    res = TwinGraphValidator.validate_graph(nodes=[n1, n2], edges=[e1, e1], expected_org_id="org1")
    assert res.is_valid is False
    assert any("Duplicate edge ID detected" in err for err in res.errors)


def test_validation_detects_corrupt_node_fingerprint():
    nid = compute_node_id("org1", "FACTORY", "f1")
    node_bad_fp = TwinNodeContract(
        node_id=nid,
        organization_id="org1",
        node_type=TwinNodeType.FACTORY,
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Factory 1",
        fingerprint="f" * 64,  # forged/incorrect fingerprint
    )

    res = TwinGraphValidator.validate_graph(nodes=[node_bad_fp], edges=[], expected_org_id="org1")
    assert res.is_valid is False
    assert any("fingerprint mismatch" in err for err in res.errors)

    with pytest.raises(TwinFingerprintError):
        TwinGraphValidator.assert_valid_graph(nodes=[node_bad_fp], edges=[], expected_org_id="org1")


def test_validation_detects_corrupt_edge_fingerprint():
    n1 = _make_node("org1", TwinNodeType.FACTORY, "f1", "Factory 1")
    n2 = _make_node("org1", TwinNodeType.WAREHOUSE, "w1", "Warehouse 1")
    eid = compute_edge_id("org1", n1.node_id, n2.node_id, "TRANSPORT")
    edge_bad_fp = TwinEdgeContract(
        edge_id=eid,
        organization_id="org1",
        from_node_id=n1.node_id,
        to_node_id=n2.node_id,
        edge_type=TwinEdgeType.TRANSPORT,
        fingerprint="e" * 64,  # forged fingerprint
    )

    res = TwinGraphValidator.validate_graph(nodes=[n1, n2], edges=[edge_bad_fp], expected_org_id="org1")
    assert res.is_valid is False
    assert any("fingerprint mismatch" in err for err in res.errors)


def test_snapshot_count_and_fingerprint_validation():
    n1 = _make_node("org1", TwinNodeType.FACTORY, "f1", "Factory 1")
    tfp = compute_twin_fingerprint("twin1", "org1", "1", [n1.fingerprint], [])

    # Valid snapshot
    valid_snap = DigitalTwinSnapshot(
        twin_id="twin1",
        organization_id="org1",
        version="1",
        node_count=1,
        edge_count=0,
        nodes={n1.node_id: n1},
        edges={},
        source_fingerprint=tfp,
        twin_fingerprint=tfp,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    res = TwinGraphValidator.validate_snapshot(valid_snap)
    assert res.is_valid is True

    # Bad count
    bad_count_snap = DigitalTwinSnapshot(
        twin_id="twin1",
        organization_id="org1",
        version="1",
        node_count=99,  # Mismatch!
        edge_count=0,
        nodes={n1.node_id: n1},
        edges={},
        source_fingerprint=tfp,
        twin_fingerprint=tfp,
        generated_at=datetime.datetime.now(datetime.timezone.utc),
        status="CURRENT",
    )
    res_bad = TwinGraphValidator.validate_snapshot(bad_count_snap)
    assert res_bad.is_valid is False
    assert any("node_count mismatch" in err for err in res_bad.errors)
