"""Unit tests for Phase 12 Digital Twin Builder: entity conversion, relationship mapping, and idempotency."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
import pytest

from app.digital_twin.builder import DigitalTwinBuilder
from app.digital_twin.errors import TwinValidationError
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


def test_builder_empty_entities():
    builder = DigitalTwinBuilder(organization_id="org_empty")
    snapshot = builder.build_from_entities()
    assert snapshot.node_count == 0
    assert snapshot.edge_count == 0
    assert snapshot.organization_id == "org_empty"
    assert snapshot.twin_id == "twin-org_empty"
    assert len(snapshot.source_fingerprint) == 64
    assert len(snapshot.twin_fingerprint) == 64


def test_builder_rejects_empty_org():
    with pytest.raises(TwinValidationError):
        DigitalTwinBuilder(organization_id="")


def test_builder_single_supplier():
    sup = SimpleNamespace(
        id="sup_100",
        org_id="org_test",
        name="Global Semiconductors",
        country="Japan",
        tier="TIER_1",
        criticality="HIGH",
        reliability_score=94.0,
        financial_exposure=500000.0,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    builder = DigitalTwinBuilder(organization_id="org_test")
    snapshot = builder.build_from_entities(suppliers=[sup])

    assert snapshot.node_count == 1
    assert snapshot.edge_count == 0
    node = list(snapshot.nodes.values())[0]
    assert node.node_type == TwinNodeType.SUPPLIER
    assert node.source_entity_id == "sup_100"
    assert node.label == "Global Semiconductors"
    assert node.health_score == 94.0
    assert node.properties["country"] == "Japan"
    assert node.properties["tier"] == "TIER_1"


def test_builder_supplier_and_site_relationship():
    sup = SimpleNamespace(
        id="sup_1",
        org_id="org_test",
        name="Apex Supply",
        reliability_score=90.0,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    site = SimpleNamespace(
        id="site_1",
        org_id="org_test",
        supplier_id="sup_1",
        name="Apex Site Alpha",
        city="Osaka",
        country="Japan",
        latitude=34.6937,
        longitude=135.5023,
        capacity=10000.0,
        status="OPERATIONAL",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    builder = DigitalTwinBuilder(organization_id="org_test")
    snapshot = builder.build_from_entities(suppliers=[sup], supplier_sites=[site])

    assert snapshot.node_count == 2
    assert snapshot.edge_count == 1
    edge = list(snapshot.edges.values())[0]
    assert edge.edge_type == TwinEdgeType.SUPPLIES
    assert edge.flow_capacity == 10000.0
    assert edge.status == "ACTIVE"


def test_builder_route_and_facilities():
    fac = SimpleNamespace(
        id="fac_1",
        org_id="org_test",
        name="Assembly Plant 1",
        latitude=31.2304,
        longitude=121.4737,
        capacity=20000.0,
        status="OPERATIONAL",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    wh = SimpleNamespace(
        id="wh_1",
        org_id="org_test",
        name="Distribution Hub West",
        latitude=37.7749,
        longitude=-122.4194,
        total_capacity=50000.0,
        status="OPERATIONAL",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    route = SimpleNamespace(
        id="rt_1",
        org_id="org_test",
        name="Transpacific Express Lane",
        origin_facility_id="fac_1",
        destination_facility_id="wh_1",
        mode="OCEAN",
        distance_km=9800.0,
        standard_lead_time_days=14.0,
        risk_score=22.5,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )

    builder = DigitalTwinBuilder(organization_id="org_test")
    snapshot = builder.build_from_entities(factories=[fac], warehouses=[wh], routes=[route])

    # 3 nodes: Factory, Warehouse, Route
    assert snapshot.node_count == 3
    # 3 edges: Corridor (fac -> wh), Link (fac -> route), Link (route -> wh)
    assert snapshot.edge_count == 3

    corridor_edges = [e for e in snapshot.edges.values() if e.edge_type == TwinEdgeType.TRANSPORT]
    assert len(corridor_edges) == 1
    assert corridor_edges[0].risk_score == 22.5
    assert corridor_edges[0].properties["distance_km"] == 9800.0


def test_builder_shipment_with_carrier_and_product():
    carrier = SimpleNamespace(
        id="c_1",
        org_id="org_test",
        name="Maersk Line",
        mode="OCEAN",
        on_time_reliability=89.0,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    prod = SimpleNamespace(
        id="pr_1",
        org_id="org_test",
        sku="SKU-CHIP-400",
        name="Microcontroller IC",
        category="Semiconductors",
        unit_cost=15.5,
        currency="USD",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    shipment = SimpleNamespace(
        id="sh_1",
        org_id="org_test",
        tracking_number="TRK-987654",
        carrier_id="c_1",
        product_id="pr_1",
        route_id=None,
        mode="OCEAN",
        current_lat=20.0,
        current_lng=-140.0,
        status="IN_TRANSIT",
        delay_minutes=45.0,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )

    builder = DigitalTwinBuilder(organization_id="org_test")
    snapshot = builder.build_from_entities(
        carriers=[carrier], products=[prod], shipments=[shipment]
    )

    # 3 nodes: Carrier, Product, Shipment
    assert snapshot.node_count == 3
    # 2 edges: Carrier -> Shipment (CARRIES), Shipment -> Product (FLOW)
    assert snapshot.edge_count == 2

    edge_types = {e.edge_type for e in snapshot.edges.values()}
    assert TwinEdgeType.CARRIES in edge_types
    assert TwinEdgeType.FLOW in edge_types


def test_builder_inventory_linkage():
    wh = SimpleNamespace(
        id="wh_1",
        org_id="org_test",
        name="Main Depot",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    prod = SimpleNamespace(
        id="pr_1",
        org_id="org_test",
        sku="SKU-BAT-100",
        name="Lithium Battery Pack",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    inv = SimpleNamespace(
        id="inv_1",
        org_id="org_test",
        facility_id="wh_1",
        product_id="pr_1",
        quantity_on_hand=3500.0,
        safety_stock=500.0,
        reorder_point=1000.0,
        days_of_supply=35.0,
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )

    builder = DigitalTwinBuilder(organization_id="org_test")
    snapshot = builder.build_from_entities(warehouses=[wh], products=[prod], inventories=[inv])

    assert snapshot.node_count == 2
    assert snapshot.edge_count == 1
    edge = list(snapshot.edges.values())[0]
    assert edge.edge_type == TwinEdgeType.LOCATED_AT
    assert edge.current_flow == 3500.0
    assert edge.properties["safety_stock"] == 500.0


def test_builder_annotates_incidents_without_fabricating_edges():
    fac = SimpleNamespace(
        id="fac_10",
        org_id="org_test",
        name="Coastal Plant",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    incident = SimpleNamespace(
        id="inc_99",
        org_id="org_test",
        title="Typhoon Disruption Alert",
        severity="HIGH",
        status="INVESTIGATING",
        affected_assets=["fac_10"],
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )

    builder = DigitalTwinBuilder(organization_id="org_test")
    snapshot = builder.build_from_entities(factories=[fac], incidents=[incident])

    assert snapshot.node_count == 1
    assert snapshot.edge_count == 0  # No fabricated edges
    node = list(snapshot.nodes.values())[0]
    assert "active_incidents" in node.properties
    assert len(node.properties["active_incidents"]) == 1
    assert node.properties["active_incidents"][0]["title"] == "Typhoon Disruption Alert"


def test_builder_filters_cross_tenant_entities():
    sup_a = SimpleNamespace(
        id="sup_a",
        org_id="org_alpha",
        name="Alpha Supplier",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    sup_b = SimpleNamespace(
        id="sup_b",
        org_id="org_beta",  # Different tenant!
        name="Beta Supplier",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )

    builder = DigitalTwinBuilder(organization_id="org_alpha")
    snapshot = builder.build_from_entities(suppliers=[sup_a, sup_b])

    assert snapshot.node_count == 1
    assert list(snapshot.nodes.values())[0].label == "Alpha Supplier"


def test_builder_idempotency_and_determinism():
    sup = SimpleNamespace(
        id="s1",
        org_id="org1",
        name="Supplier 1",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )
    site = SimpleNamespace(
        id="site1",
        org_id="org1",
        supplier_id="s1",
        name="Site 1",
        created_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
    )

    builder = DigitalTwinBuilder(organization_id="org1")
    snapshot1 = builder.build_from_entities(suppliers=[sup], supplier_sites=[site])
    snapshot2 = builder.build_from_entities(suppliers=[sup], supplier_sites=[site])

    assert snapshot1.node_count == snapshot2.node_count
    assert snapshot1.edge_count == snapshot2.edge_count
    assert set(snapshot1.nodes.keys()) == set(snapshot2.nodes.keys())
    assert set(snapshot1.edges.keys()) == set(snapshot2.edges.keys())
    assert snapshot1.source_fingerprint == snapshot2.source_fingerprint
    assert snapshot1.twin_fingerprint == snapshot2.twin_fingerprint
