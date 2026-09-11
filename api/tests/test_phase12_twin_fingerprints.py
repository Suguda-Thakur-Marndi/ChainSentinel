"""Unit tests for Phase 12 Digital Twin deterministic identities and canonical fingerprints."""

from __future__ import annotations

import pytest

from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_edge_id,
    compute_node_fingerprint,
    compute_node_id,
    compute_source_fingerprint,
    compute_twin_fingerprint,
)


def test_node_id_is_deterministic():
    id1 = compute_node_id("org_alpha", "FACTORY", "fac_001")
    id2 = compute_node_id("org_alpha", "FACTORY", "fac_001")
    assert id1 == id2
    assert len(id1) == 36  # standard UUID format


def test_node_id_tenant_isolation():
    id_alpha = compute_node_id("org_alpha", "FACTORY", "fac_001")
    id_beta = compute_node_id("org_beta", "FACTORY", "fac_001")
    assert id_alpha != id_beta


def test_node_id_entity_type_isolation():
    id_fac = compute_node_id("org_alpha", "FACTORY", "item_001")
    id_wh = compute_node_id("org_alpha", "WAREHOUSE", "item_001")
    assert id_fac != id_wh


def test_node_id_entity_id_isolation():
    id_1 = compute_node_id("org_alpha", "FACTORY", "fac_001")
    id_2 = compute_node_id("org_alpha", "FACTORY", "fac_002")
    assert id_1 != id_2


def test_node_id_normalizes_case_and_whitespace():
    id1 = compute_node_id("ORG_ALPHA  ", "  factory  ", "fac_001")
    id2 = compute_node_id("org_alpha", "FACTORY", "fac_001")
    assert id1 == id2


def test_edge_id_is_deterministic():
    eid1 = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW", "rel_1")
    eid2 = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW", "rel_1")
    assert eid1 == eid2
    assert len(eid1) == 36


def test_edge_id_tenant_isolation():
    eid_alpha = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW", "rel_1")
    eid_beta = compute_edge_id("org_beta", "node_1", "node_2", "FLOW", "rel_1")
    assert eid_alpha != eid_beta


def test_edge_id_endpoint_isolation():
    eid1 = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW")
    eid2 = compute_edge_id("org_alpha", "node_2", "node_1", "FLOW")
    assert eid1 != eid2


def test_edge_id_type_isolation():
    eid_flow = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW")
    eid_trans = compute_edge_id("org_alpha", "node_1", "node_2", "TRANSPORT")
    assert eid_flow != eid_trans


def test_edge_id_relationship_disambiguation():
    eid_a = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW", "shipment_1")
    eid_b = compute_edge_id("org_alpha", "node_1", "node_2", "FLOW", "shipment_2")
    assert eid_a != eid_b


def test_node_fingerprint_deterministic_and_order_invariant():
    props_1 = {"capacity": 500, "lead_time": 10, "tags": ["critical", "electronics"]}
    props_2 = {"tags": ["critical", "electronics"], "lead_time": 10, "capacity": 500}

    fp1 = compute_node_fingerprint(
        node_id="n1",
        organization_id="org1",
        node_type="FACTORY",
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Plant",
        latitude=30.123456,
        longitude=100.654321,
        health_score=88.5,
        status="OPERATIONAL",
        properties=props_1,
    )
    fp2 = compute_node_fingerprint(
        node_id="n1",
        organization_id="org1",
        node_type="FACTORY",
        source_entity_type="FACTORY",
        source_entity_id="f1",
        label="Plant",
        latitude=30.123456,
        longitude=100.654321,
        health_score=88.5,
        status="OPERATIONAL",
        properties=props_2,
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_node_fingerprint_sensitivity_to_attribute_change():
    base_args = {
        "node_id": "n1",
        "organization_id": "org1",
        "node_type": "FACTORY",
        "source_entity_type": "FACTORY",
        "source_entity_id": "f1",
        "label": "Plant",
        "latitude": 30.0,
        "longitude": 100.0,
        "health_score": 90.0,
        "status": "OPERATIONAL",
        "properties": {"tier": 1},
    }
    base_fp = compute_node_fingerprint(**base_args)

    # Change label
    args_changed_label = dict(base_args, label="New Plant")
    assert compute_node_fingerprint(**args_changed_label) != base_fp

    # Change health score
    args_changed_health = dict(base_args, health_score=91.0)
    assert compute_node_fingerprint(**args_changed_health) != base_fp

    # Change coordinates
    args_changed_coord = dict(base_args, latitude=31.0)
    assert compute_node_fingerprint(**args_changed_coord) != base_fp


def test_edge_fingerprint_deterministic_and_order_invariant():
    props_1 = {"mode": "AIR", "carrier": "DHL"}
    props_2 = {"carrier": "DHL", "mode": "AIR"}

    fp1 = compute_edge_fingerprint(
        edge_id="e1",
        organization_id="org1",
        from_node_id="n1",
        to_node_id="n2",
        edge_type="FLOW",
        status="ACTIVE",
        flow_capacity=100.0,
        current_flow=50.0,
        risk_score=12.0,
        properties=props_1,
    )
    fp2 = compute_edge_fingerprint(
        edge_id="e1",
        organization_id="org1",
        from_node_id="n1",
        to_node_id="n2",
        edge_type="FLOW",
        status="ACTIVE",
        flow_capacity=100.0,
        current_flow=50.0,
        risk_score=12.0,
        properties=props_2,
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_edge_fingerprint_sensitivity():
    base_args = {
        "edge_id": "e1",
        "organization_id": "org1",
        "from_node_id": "n1",
        "to_node_id": "n2",
        "edge_type": "FLOW",
        "status": "ACTIVE",
        "current_flow": 50.0,
    }
    base_fp = compute_edge_fingerprint(**base_args)

    args_changed_flow = dict(base_args, current_flow=60.0)
    assert compute_edge_fingerprint(**args_changed_flow) != base_fp

    args_changed_status = dict(base_args, status="CONGESTED")
    assert compute_edge_fingerprint(**args_changed_status) != base_fp


def test_source_fingerprint_order_invariance():
    digests_a = ["SUPPLIER:1:abc", "FACTORY:2:def", "ROUTE:3:ghi"]
    digests_b = ["ROUTE:3:ghi", "SUPPLIER:1:abc", "FACTORY:2:def"]

    fp_a = compute_source_fingerprint(digests_a)
    fp_b = compute_source_fingerprint(digests_b)
    assert fp_a == fp_b
    assert len(fp_a) == 64


def test_twin_fingerprint_order_invariance():
    node_fps_1 = ["fp_node_1", "fp_node_2", "fp_node_3"]
    node_fps_2 = ["fp_node_3", "fp_node_1", "fp_node_2"]
    edge_fps_1 = ["fp_edge_1", "fp_edge_2"]
    edge_fps_2 = ["fp_edge_2", "fp_edge_1"]

    tfp1 = compute_twin_fingerprint("twin1", "org1", "1", node_fps_1, edge_fps_1)
    tfp2 = compute_twin_fingerprint("twin1", "org1", "1", node_fps_2, edge_fps_2)
    assert tfp1 == tfp2
    assert len(tfp1) == 64


def test_twin_fingerprint_sensitivity():
    tfp_base = compute_twin_fingerprint("twin1", "org1", "1", ["node1"], ["edge1"])
    tfp_diff_ver = compute_twin_fingerprint("twin1", "org1", "2", ["node1"], ["edge1"])
    tfp_diff_node = compute_twin_fingerprint("twin1", "org1", "1", ["node2"], ["edge1"])
    tfp_diff_org = compute_twin_fingerprint("twin1", "org2", "1", ["node1"], ["edge1"])

    assert tfp_base != tfp_diff_ver
    assert tfp_base != tfp_diff_node
    assert tfp_base != tfp_diff_org
