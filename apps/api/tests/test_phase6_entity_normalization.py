"""Phase 6 Step 3: Entity Normalization & Cross-Source Correlation Test Suite.

Comprehensive test coverage for identifier normalization, namespace isolation,
conservative entity correlation, false-positive prevention, cross-source corroboration,
provenance preservation, multi-tenant isolation, determinism, and security.
"""

import uuid
from datetime import datetime, timezone
import pytest

from app.integrations.canonical import (
    CanonicalEventType,
    CanonicalExternalEvent,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.normalization.contract import (
    CorrelationConfidence,
    CorrelationMethod,
    CorrelationStatus,
    EntityReference,
    EntityType,
    NormalizedRiskSignal,
    SignalDomain,
    SignalEntityReferences,
    SignalStatus,
    SignalType,
)
from app.normalization.correlation import CrossSourceCorrelator
from app.normalization.entity_resolver import (
    EntityNormalizer,
    InMemoryEntityLookupProvider,
)
from app.normalization.identifiers import IdentifierNormalizer, NormalizedIdentifier
from app.normalization.pipeline import NormalizationPipeline, NormalizationStatus


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def lookup_provider() -> InMemoryEntityLookupProvider:
    provider = InMemoryEntityLookupProvider()
    # Register Org A entities
    provider.register_shipment(
        org_id="org_alpha",
        shipment_id="shp_alpha_001",
        tracking_number="TRK123456",
        carrier_namespace="FEDEX",
    )
    provider.register_supplier(
        org_id="org_alpha",
        supplier_id="sup_alpha_001",
        code="SUP-ALPHA-01",
        name="Apex Manufacturing",
    )
    provider.register_supplier_site(
        org_id="org_alpha",
        site_id="site_alpha_001",
        supplier_id="sup_alpha_001",
        name="Apex Assembly Plant 1",
    )
    provider.register_factory(
        org_id="org_alpha",
        factory_id="fac_alpha_001",
        name="Internal Gigafactory Alpha",
    )
    provider.register_warehouse(
        org_id="org_alpha",
        warehouse_id="wh_alpha_001",
        code="WH-NORTH-01",
        name="North Logistics Hub",
    )
    provider.register_carrier(
        org_id="org_alpha",
        carrier_id="car_alpha_001",
        code="FEDEX",
        namespace="FEDEX",
        name="Federal Express Alpha",
    )
    provider.register_route(
        org_id="org_alpha",
        route_id="rte_alpha_001",
        name="Transpacific Corridor A",
    )

    # Register Org B entities (Strict tenant boundary)
    provider.register_shipment(
        org_id="org_beta",
        shipment_id="shp_beta_001",
        tracking_number="TRK999999",
        carrier_namespace="FEDEX",
    )
    provider.register_supplier(
        org_id="org_beta",
        supplier_id="sup_beta_001",
        code="SUP-BETA-01",
        name="Beta Components Corp",
    )

    # Register Global Reference Data (Ports, Vessels, Aircraft)
    provider.register_port(
        port_id="port_la_001",
        code="USLAX",
        name="Port of Los Angeles",
        unlocode="USLAX",
    )
    provider.register_port(
        port_id="port_rot_001",
        code="NLRTM",
        name="Port of Rotterdam",
        unlocode="NLRTM",
    )
    provider.register_vessel(
        imo="9123456",
        mmsi="367123456",
        name="Ever Alpha",
        vessel_id="ves_ever_alpha",
    )
    provider.register_vessel(
        imo="9876543",
        mmsi="367987654",
        name="Maersk Pacific",
        vessel_id="ves_maersk_pacific",
    )
    provider.register_aircraft(
        icao24="a1b2c3",
        callsign="FDX101",
        aircraft_id="ac_a1b2c3",
    )
    provider.register_aircraft(
        icao24="c3d4e5",
        callsign="UPS202",
        aircraft_id="ac_c3d4e5",
    )

    return provider


@pytest.fixture
def entity_normalizer(lookup_provider: InMemoryEntityLookupProvider) -> EntityNormalizer:
    return EntityNormalizer(lookup_provider=lookup_provider)


@pytest.fixture
def base_signal() -> NormalizedRiskSignal:
    return NormalizedRiskSignal(
        signal_id=str(uuid.uuid4()),
        organization_id="org_alpha",
        domain=SignalDomain.LOGISTICS,
        signal_type=SignalType.STATUS_UPDATE,
        event_type="SHIPMENT_STATUS",
        status=SignalStatus.ACTIVE,
        severity=EventSeverity.INFO,
        event_time=datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc),
        source="provider_karrio",
        source_type=EventSourceType.REAL,
        provider="Karrio",
        canonical_event_id="can_001",
        entities=SignalEntityReferences(),
    )


# =============================================================================
# Category 1: IDENTIFIERS (Tests 1-4)
# =============================================================================
def test_identifier_whitespace_normalization():
    """1. Test that leading and trailing whitespace is trimmed across all identifier types."""
    res_imo = IdentifierNormalizer.normalize_imo("   9123456   ")
    assert res_imo.normalized_value == "9123456"
    assert res_imo.raw_value == "9123456"
    assert res_imo.is_valid is True

    res_unlocode = IdentifierNormalizer.normalize_unlocode("  uslax  ")
    assert res_unlocode.normalized_value == "USLAX"
    assert res_unlocode.is_valid is True


def test_identifier_case_handling():
    """2. Test case-insensitivity formatting for UN/LOCODE (uppercase) and ICAO24 (lowercase hex)."""
    res_loc = IdentifierNormalizer.normalize_unlocode("nlrtm")
    assert res_loc.normalized_value == "NLRTM"
    assert res_loc.is_valid is True

    res_icao = IdentifierNormalizer.normalize_icao24("A1B2C3")
    assert res_icao.normalized_value == "a1b2c3"
    assert res_icao.is_valid is True


def test_identifier_known_formatting():
    """3. Test stripping of known prefixes such as 'IMO ' while validating exact 7 digits."""
    res_imo_prefix = IdentifierNormalizer.normalize_imo("IMO 9123456")
    assert res_imo_prefix.normalized_value == "9123456"
    assert res_imo_prefix.is_valid is True

    res_imo_dash = IdentifierNormalizer.normalize_imo("IMO-9123456")
    assert res_imo_dash.normalized_value == "9123456"
    assert res_imo_dash.is_valid is True


def test_unknown_identifier_preservation():
    """4. Test that unknown identifiers are trimmed but NEVER arbitrarily stripped of characters."""
    raw_custom = "custom#item-100_XYZ/v2"
    res = IdentifierNormalizer.normalize_generic(f"  {raw_custom}  ", namespace="CUSTOM", identifier_type="ITEM")
    assert res.normalized_value == raw_custom
    assert res.raw_value == raw_custom
    assert res.is_valid is True


# =============================================================================
# Category 2: NAMESPACES (Tests 5-7)
# =============================================================================
def test_namespace_same_id_same_namespace():
    """5. Test that identical values within the same namespace resolve to the same qualified key."""
    id1 = IdentifierNormalizer.normalize_generic("12345", namespace="PROVIDER_A", identifier_type="TRACKING")
    id2 = IdentifierNormalizer.normalize_generic("12345", namespace="PROVIDER_A", identifier_type="TRACKING")
    assert id1.qualified_key == id2.qualified_key
    assert id1.qualified_key == "PROVIDER_A:TRACKING:12345"


def test_namespace_same_id_different_namespace():
    """6. Test that identical values across different namespaces produce distinct qualified keys."""
    id_a = IdentifierNormalizer.normalize_generic("12345", namespace="PROVIDER_A", identifier_type="TRACKING")
    id_b = IdentifierNormalizer.normalize_generic("12345", namespace="PROVIDER_B", identifier_type="TRACKING")
    assert id_a.qualified_key != id_b.qualified_key
    assert id_a.qualified_key == "PROVIDER_A:TRACKING:12345"
    assert id_b.qualified_key == "PROVIDER_B:TRACKING:12345"


def test_namespace_same_value_different_identifier_type():
    """7. Test that identical values with different identifier types (e.g. IMO vs MMSI) never collide."""
    imo = IdentifierNormalizer.normalize_imo("1234567")
    mmsi = IdentifierNormalizer.normalize_mmsi("123456789")
    # Even if strings shared 7 digits
    generic_imo = IdentifierNormalizer.normalize_generic("1234567", namespace="MARITIME", identifier_type="IMO")
    generic_mmsi = IdentifierNormalizer.normalize_generic("1234567", namespace="MARITIME", identifier_type="MMSI")
    assert generic_imo.qualified_key != generic_mmsi.qualified_key
    assert "IMO" in generic_imo.qualified_key
    assert "MMSI" in generic_mmsi.qualified_key


# =============================================================================
# Category 3: SHIPMENTS (Tests 8-12)
# =============================================================================
def test_shipment_exact_internal_id(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """8. Test shipment correlation via exact internal ID matching tenant scope."""
    base_signal.entities.shipment_id = "shp_alpha_001"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.correlation_status == CorrelationStatus.RESOLVED
    assert len(resolved.entities.references) == 1
    ref = resolved.entities.references[0]
    assert ref.entity_type == EntityType.SHIPMENT
    assert ref.internal_id == "shp_alpha_001"
    assert ref.correlation_confidence == CorrelationConfidence.EXACT
    assert ref.correlation_method == CorrelationMethod.INTERNAL_ID


def test_shipment_exact_tracking_id_and_carrier_namespace(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """9. Test shipment correlation via tracking number qualified by carrier namespace."""
    base_signal.normalized_attributes["tracking_number"] = "TRK123456"
    base_signal.normalized_attributes["carrier_code"] = "FEDEX"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.shipment_id == "shp_alpha_001"
    assert resolved.entities.correlation_status == CorrelationStatus.RESOLVED
    ref = resolved.entities.get_references_by_type(EntityType.SHIPMENT)[0]
    assert ref.correlation_confidence == CorrelationConfidence.VERIFIED
    assert ref.correlation_method == CorrelationMethod.VERIFIED_MAPPING


def test_shipment_unresolved_preserved(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """10. Test that an unknown tracking number is marked UNRESOLVED and preserved."""
    base_signal.normalized_attributes["tracking_number"] = "UNKNOWN_TRK_999"
    base_signal.normalized_attributes["carrier_code"] = "FEDEX"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.shipment_id is None
    assert "tracking_number" in resolved.entities.unresolved_identifiers
    assert resolved.entities.unresolved_identifiers["tracking_number"] == "UNKNOWN_TRK_999"
    ref = resolved.entities.get_references_by_type(EntityType.SHIPMENT)[0]
    assert ref.correlation_confidence == CorrelationConfidence.UNRESOLVED
    assert ref.correlation_method == CorrelationMethod.UNRESOLVED


def test_shipment_false_positive_rejection_location_alone(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """11. Test that geographic coordinates alone NEVER establish a shipment correlation."""
    base_signal.latitude = 34.0522
    base_signal.longitude = -118.2437
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.shipment_id is None
    assert resolved.entities.get_references_by_type(EntityType.SHIPMENT) == []
    assert resolved.entities.correlation_status == CorrelationStatus.NONE


def test_shipment_false_positive_rejection_name_or_text_alone(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """12. Test that raw text mentions or descriptive names alone NEVER correlate a shipment."""
    base_signal.normalized_attributes["description"] = "Cargo moving near Apex Assembly Plant 1"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.shipment_id is None
    assert resolved.entities.get_references_by_type(EntityType.SHIPMENT) == []


# =============================================================================
# Category 4: SUPPLIERS (Tests 13-15)
# =============================================================================
def test_supplier_verified_mapping(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """13. Test supplier correlation via verified supplier code within tenant."""
    base_signal.normalized_attributes["supplier_code"] = "SUP-ALPHA-01"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.supplier_id == "sup_alpha_001"
    assert resolved.entities.correlation_status == CorrelationStatus.RESOLVED
    ref = resolved.entities.get_references_by_type(EntityType.SUPPLIER)[0]
    assert ref.correlation_confidence == CorrelationConfidence.VERIFIED
    assert ref.correlation_method == CorrelationMethod.VERIFIED_MAPPING


def test_supplier_unresolved_preserved(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """14. Test that an unknown supplier ID is preserved as unresolved without false correlation."""
    base_signal.entities.supplier_id = "sup_unknown_999"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert "supplier_id" in resolved.entities.unresolved_identifiers
    ref = resolved.entities.get_references_by_type(EntityType.SUPPLIER)[0]
    assert ref.correlation_confidence == CorrelationConfidence.UNRESOLVED


def test_supplier_similar_name_false_positive_rejection(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """15. Test that similar company names (e.g. 'Apex Manufacturing Ltd') do NOT resolve to 'Apex Manufacturing'."""
    base_signal.normalized_attributes["supplier_name"] = "Apex Manufacturing Ltd"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.supplier_id is None
    assert resolved.entities.get_references_by_type(EntityType.SUPPLIER) == []
    assert resolved.entities.unresolved_identifiers.get("supplier_name") == "Apex Manufacturing Ltd"


# =============================================================================
# Category 5: SUPPLIER SITES / FACTORIES (Tests 16-18)
# =============================================================================
def test_supplier_site_exact_mapping(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """16. Test supplier site correlation via internal site ID."""
    base_signal.entities.supplier_site_id = "site_alpha_001"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.SUPPLIER_SITE)[0]
    assert ref.internal_id == "site_alpha_001"
    assert ref.correlation_confidence == CorrelationConfidence.EXACT


def test_factory_exact_mapping(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """17. Test factory plant correlation via internal factory ID."""
    base_signal.entities.factory_id = "fac_alpha_001"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.FACTORY)[0]
    assert ref.internal_id == "fac_alpha_001"
    assert ref.correlation_confidence == CorrelationConfidence.EXACT


def test_site_vs_factory_vs_supplier_distinction(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """18. Test that supplier, supplier site, and factory are kept strictly distinct."""
    base_signal.entities.supplier_id = "sup_alpha_001"
    base_signal.entities.supplier_site_id = "site_alpha_001"
    base_signal.entities.factory_id = "fac_alpha_001"
    resolved = entity_normalizer.normalize_entities(base_signal)

    types = [r.entity_type for r in resolved.entities.references]
    assert EntityType.SUPPLIER in types
    assert EntityType.SUPPLIER_SITE in types
    assert EntityType.FACTORY in types
    assert len(types) == 3


# =============================================================================
# Category 6: WAREHOUSES (Tests 19-20)
# =============================================================================
def test_warehouse_exact_mapping(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """19. Test warehouse correlation via verified warehouse code."""
    base_signal.normalized_attributes["warehouse_code"] = "WH-NORTH-01"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.warehouse_id == "wh_alpha_001"
    ref = resolved.entities.get_references_by_type(EntityType.WAREHOUSE)[0]
    assert ref.correlation_confidence == CorrelationConfidence.VERIFIED


def test_warehouse_geographic_only_false_positive_rejection(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """20. Test that nearby coordinates do NOT falsely correlate to a warehouse without an identifier."""
    base_signal.latitude = 40.7128
    base_signal.longitude = -74.0060
    base_signal.normalized_attributes["location_name"] = "Industrial Park near WH-NORTH-01"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.warehouse_id is None
    assert resolved.entities.get_references_by_type(EntityType.WAREHOUSE) == []


# =============================================================================
# Category 7: PORTS (Tests 21-25)
# =============================================================================
def test_port_internal_id(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """21. Test port correlation via internal port ID."""
    base_signal.entities.port_id = "port_la_001"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.PORT)[0]
    assert ref.internal_id == "port_la_001"
    assert ref.correlation_confidence == CorrelationConfidence.EXACT


def test_port_unlocode(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """22. Test port correlation via verified UN/LOCODE mapping."""
    base_signal.normalized_attributes["unlocode"] = "USLAX"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.port_id == "port_la_001"
    ref = resolved.entities.get_references_by_type(EntityType.PORT)[0]
    assert ref.correlation_confidence == CorrelationConfidence.VERIFIED
    assert ref.correlation_method == CorrelationMethod.VERIFIED_MAPPING


def test_port_provider_mapping(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """23. Test port correlation via port_code in normalized attributes."""
    base_signal.normalized_attributes["port_code"] = "NLRTM"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.port_id == "port_rot_001"


def test_port_nearby_false_positive_rejection(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """24. Test that geographic proximity alone does NOT snap an event to a port."""
    base_signal.latitude = 33.74
    base_signal.longitude = -118.26  # Close to Port of LA
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.port_id is None
    assert resolved.entities.get_references_by_type(EntityType.PORT) == []


def test_port_single_authoritative_path(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """25. Test single authoritative resolution path: internal ID > UN/LOCODE."""
    base_signal.entities.port_id = "port_la_001"
    base_signal.normalized_attributes["unlocode"] = "NLRTM"  # Different UN/LOCODE
    resolved = entity_normalizer.normalize_entities(base_signal)
    # Primary internal port ID takes precedence
    assert resolved.entities.port_id == "port_la_001"


# =============================================================================
# Category 8: VESSELS (Tests 26-30)
# =============================================================================
def test_vessel_imo(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """26. Test vessel resolution via IMO number."""
    base_signal.normalized_attributes["imo"] = "9123456"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.VESSEL)[0]
    assert ref.internal_id == "ves_ever_alpha"
    assert ref.correlation_confidence == CorrelationConfidence.EXACT


def test_vessel_mmsi(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """27. Test vessel resolution via MMSI number."""
    base_signal.entities.vessel_mmsi = "367987654"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.VESSEL)[0]
    assert ref.internal_id == "ves_maersk_pacific"
    assert ref.correlation_confidence == CorrelationConfidence.VERIFIED


def test_vessel_callsign_unregistered(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """28. Test vessel call sign preservation without IMO/MMSI."""
    base_signal.normalized_attributes["callsign"] = "WDC1234"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.unresolved_identifiers.get("vessel_callsign") == "WDC1234"


def test_vessel_name_unregistered(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """29. Test vessel name preservation in unresolved identifiers."""
    base_signal.normalized_attributes["vessel_name"] = "Pacific Voyager"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.unresolved_identifiers.get("vessel_name") == "Pacific Voyager"


def test_vessel_conflicting_identifiers(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """30. Test that conflicting IMO and MMSI flagging is preserved as ambiguous/conflict."""
    base_signal.normalized_attributes["imo"] = "9123456"    # Resolves to Ever Alpha
    base_signal.entities.vessel_mmsi = "367987654"          # Resolves to Maersk Pacific
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.has_conflict is True
    assert resolved.entities.correlation_status == CorrelationStatus.AMBIGUOUS
    ref = resolved.entities.get_references_by_type(EntityType.VESSEL)[0]
    assert ref.is_conflict is True
    assert "Vessel conflict" in ref.conflict_details


# =============================================================================
# Category 9: AIRCRAFT (Tests 31-33)
# =============================================================================
def test_aircraft_icao24(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """31. Test aircraft resolution via ICAO24 hexadecimal address."""
    base_signal.entities.aircraft_icao24 = "a1b2c3"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.AIRCRAFT)[0]
    assert ref.internal_id == "ac_a1b2c3"
    assert ref.correlation_confidence == CorrelationConfidence.EXACT


def test_aircraft_callsign(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """32. Test aircraft callsign resolution marked as WEAK without registered ICAO24."""
    base_signal.entities.flight_number = "UAL999"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.AIRCRAFT)[0]
    assert ref.correlation_confidence == CorrelationConfidence.WEAK
    assert ref.correlation_method == CorrelationMethod.EXTERNAL_REFERENCE


def test_aircraft_conflicting_callsign(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """33. Test aircraft conflict detection when reported callsign conflicts with registered permanent callsign."""
    base_signal.entities.aircraft_icao24 = "a1b2c3"   # Registered with permanent callsign FDX101
    base_signal.entities.flight_number = "UPS999"      # Conflicting active callsign
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.has_conflict is True
    assert resolved.entities.correlation_status == CorrelationStatus.AMBIGUOUS
    ref = resolved.entities.get_references_by_type(EntityType.AIRCRAFT)[0]
    assert ref.is_conflict is True
    assert "Aircraft identity ambiguity" in ref.conflict_details


# =============================================================================
# Category 10: CARRIERS (Tests 34-35)
# =============================================================================
def test_carrier_namespace_collision_prevention(lookup_provider: InMemoryEntityLookupProvider):
    """34. Test that carrier codes in different namespaces do not collide."""
    lookup_provider.register_carrier(org_id="org_alpha", carrier_id="car_1", code="EXP", namespace="PARCEL")
    lookup_provider.register_carrier(org_id="org_alpha", carrier_id="car_2", code="EXP", namespace="FREIGHT")

    c1 = lookup_provider.get_carrier_by_code("org_alpha", "EXP", "PARCEL")
    c2 = lookup_provider.get_carrier_by_code("org_alpha", "EXP", "FREIGHT")
    assert c1["id"] == "car_1"
    assert c2["id"] == "car_2"
    assert c1["id"] != c2["id"]


def test_carrier_verified_mapping(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """35. Test carrier correlation via verified carrier code and namespace."""
    base_signal.normalized_attributes["carrier_code"] = "FEDEX"
    base_signal.normalized_attributes["carrier_namespace"] = "FEDEX"
    resolved = entity_normalizer.normalize_entities(base_signal)
    assert resolved.entities.carrier_id == "car_alpha_001"
    ref = resolved.entities.get_references_by_type(EntityType.CARRIER)[0]
    assert ref.correlation_confidence == CorrelationConfidence.VERIFIED


# =============================================================================
# Category 11: VEHICLE / TRACKING OBJECT (Tests 36-37)
# =============================================================================
def test_vehicle_identifier_normalized(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """36. Test vehicle identifier normalization without false shipment correlation."""
    base_signal.entities.vehicle_id = "TRUCK-99-ALPHA"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.VEHICLE)[0]
    assert ref.external_id == "TRUCK-99-ALPHA"
    assert resolved.entities.shipment_id is None


def test_tracking_object_container(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """37. Test container / tracking object normalization."""
    base_signal.normalized_attributes["container_id"] = "MSCU1234567"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.TRACKING_OBJECT)[0]
    assert ref.external_id == "MSCU1234567"
    assert resolved.entities.unresolved_identifiers.get("tracking_object_id") == "MSCU1234567"


# =============================================================================
# Category 12: MULTI-ENTITY EVENT CORRELATION (Test 38)
# =============================================================================
def test_event_multi_entity_independent_evidence(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """38. Test an event referencing route, port, and carrier simultaneously with independent evidence."""
    base_signal.entities.route_id = "rte_alpha_001"
    base_signal.entities.port_id = "port_la_001"
    base_signal.entities.carrier_id = "car_alpha_001"
    resolved = entity_normalizer.normalize_entities(base_signal)

    assert len(resolved.entities.references) == 3
    types = {r.entity_type for r in resolved.entities.references}
    assert types == {EntityType.ROUTE, EntityType.PORT, EntityType.CARRIER}
    assert resolved.entities.shipment_id is None  # No unwarranted shipment correlation


# =============================================================================
# Category 13: EVENT CORRELATION & CROSS-SOURCE (Tests 39-44)
# =============================================================================
def test_cross_source_exact_duplicate_dropped():
    """39. Test that exact duplicate events from the same source do not inflate evidence count."""
    correlator = CrossSourceCorrelator()
    sig1 = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_tomtom_100",
        provider_event_id="tt_inc_1",
    )
    sig2 = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_tomtom_100",
        provider_event_id="tt_inc_1",
    )

    correlator.correlate_signal(sig1)
    correlator.correlate_signal(sig2)
    corroborated = correlator.get_corroborated_signals()
    assert len(corroborated) == 1
    assert len(corroborated[0].supporting_sources) == 0  # Not inflated


def test_cross_source_corroboration_independent_sources():
    """40. Test that independent sources (TomTom + Tavily news) are merged into supporting sources."""
    correlator = CrossSourceCorrelator()
    sig_tomtom = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 5, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_tomtom_101",
        provider_event_id="tt_closure_1",
    )
    sig_tavily = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 15, 0, tzinfo=timezone.utc),  # Same hour bucket
        latitude=34.05,
        longitude=-118.25,
        source="tavily",
        provider="Tavily",
        canonical_event_id="can_tavily_201",
        provider_event_id="tav_news_7",
    )

    correlator.correlate_signal(sig_tomtom)
    correlator.correlate_signal(sig_tavily)
    corroborated = correlator.get_corroborated_signals()

    assert len(corroborated) == 1
    primary = corroborated[0]
    assert primary.provider == "TomTom"
    assert len(primary.supporting_sources) == 1
    assert primary.supporting_sources[0].provider == "Tavily"
    assert primary.supporting_sources[0].canonical_event_id == "can_tavily_201"


def test_cross_source_source_precedence_promotion():
    """41. Test that a higher-precedence source (REAL) promotes over an existing (ESTIMATED) source."""
    correlator = CrossSourceCorrelator()
    sig_estimated = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        source_type=EventSourceType.ESTIMATED,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="simulator",
        provider="TrafficSim",
        canonical_event_id="can_sim_01",
    )
    sig_real = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        source_type=EventSourceType.REAL,
        event_time=datetime(2026, 9, 8, 10, 10, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_real_01",
    )

    correlator.correlate_signal(sig_estimated)
    correlator.correlate_signal(sig_real)
    corroborated = correlator.get_corroborated_signals()

    assert len(corroborated) == 1
    primary = corroborated[0]
    assert primary.source_type == EventSourceType.REAL
    assert primary.provider == "TomTom"
    assert len(primary.supporting_sources) == 1
    assert primary.supporting_sources[0].provider == "TrafficSim"


def test_cross_source_unrelated_events_kept_separate():
    """42. Test that signals with different event types or different spatial coordinates stay separate."""
    correlator = CrossSourceCorrelator()
    sig_road = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_rd_01",
    )
    sig_weather = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.WEATHER,
        signal_type=SignalType.HAZARD,
        event_type="SEVERE_WEATHER_ALERT",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="openweather",
        provider="OpenWeather",
        canonical_event_id="can_wx_01",
    )

    correlator.correlate_signal(sig_road)
    correlator.correlate_signal(sig_weather)
    corroborated = correlator.get_corroborated_signals()
    assert len(corroborated) == 2


def test_cross_source_conflicting_status_preserved():
    """43. Test that conflicting statuses across sources (ACTIVE vs RESOLVED) are preserved without deletion."""
    correlator = CrossSourceCorrelator()
    sig_active = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_active_01",
    )
    sig_resolved = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.RESOLVED,
        event_time=datetime(2026, 9, 8, 10, 20, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tavily",
        provider="Tavily",
        canonical_event_id="can_resolved_01",
    )

    correlator.correlate_signal(sig_active)
    correlator.correlate_signal(sig_resolved)
    corroborated = correlator.get_corroborated_signals()

    assert len(corroborated) == 1
    primary = corroborated[0]
    assert "status_conflicts" in primary.canonical_attributes
    conflict_list = primary.canonical_attributes["status_conflicts"]
    assert len(conflict_list) >= 1
    assert conflict_list[0]["status_a"] == "ACTIVE"
    assert conflict_list[0]["status_b"] == "RESOLVED"


def test_cross_source_same_timestamp_different_location_kept_separate():
    """44. Test that identical timestamps in distant locations are never merged."""
    correlator = CrossSourceCorrelator()
    sig_la = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_la",
    )
    sig_ny = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=40.71,
        longitude=-74.00,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_ny",
    )

    correlator.correlate_signal(sig_la)
    correlator.correlate_signal(sig_ny)
    assert len(correlator.get_corroborated_signals()) == 2


# =============================================================================
# Category 14: TENANCY & ISOLATION (Tests 45-46)
# =============================================================================
def test_multi_tenant_isolation_entity_lookup(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """45. Test that Organization A CANNOT resolve entities belonging to Organization B."""
    base_signal.organization_id = "org_alpha"
    # Attempt to resolve Org B's shipment
    base_signal.entities.shipment_id = "shp_beta_001"
    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.SHIPMENT)[0]
    assert ref.internal_id is None
    assert ref.correlation_confidence == CorrelationConfidence.UNRESOLVED
    assert "Shipment ID not found within tenant scope" in ref.evidence["reason"]


def test_multi_tenant_isolation_cross_source_correlation():
    """46. Test that events in different organizations never merge even with identical attributes."""
    correlator = CrossSourceCorrelator()
    sig_alpha = NormalizedRiskSignal(
        organization_id="org_alpha",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_a",
    )
    sig_beta = NormalizedRiskSignal(
        organization_id="org_beta",
        domain=SignalDomain.ROAD,
        signal_type=SignalType.DISRUPTION,
        event_type="ROAD_CLOSURE",
        status=SignalStatus.ACTIVE,
        event_time=datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        source="tomtom",
        provider="TomTom",
        canonical_event_id="can_b",
    )

    correlator.correlate_signal(sig_alpha)
    correlator.correlate_signal(sig_beta)
    assert len(correlator.get_corroborated_signals()) == 2


# =============================================================================
# Category 15: DETERMINISM & SECURITY (Tests 47-48)
# =============================================================================
def test_pipeline_determinism(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """47. Test that identical canonical inputs produce strictly identical entity references."""
    base_signal.entities.shipment_id = "shp_alpha_001"
    base_signal.normalized_attributes["unlocode"] = "USLAX"

    sig1 = entity_normalizer.normalize_entities(base_signal.model_copy(deep=True))
    sig2 = entity_normalizer.normalize_entities(base_signal.model_copy(deep=True))

    assert len(sig1.entities.references) == len(sig2.entities.references)
    for r1, r2 in zip(sig1.entities.references, sig2.entities.references):
        assert r1.entity_type == r2.entity_type
        assert r1.internal_id == r2.internal_id
        assert r1.correlation_confidence == r2.correlation_confidence


def test_security_prompt_injection_remains_inert(entity_normalizer: EntityNormalizer, base_signal: NormalizedRiskSignal):
    """48. Test that malicious prompt injection payloads in entity references remain inert data."""
    malicious_text = "'; DROP TABLE shipments; -- <script>alert(1)</script>"
    base_signal.normalized_attributes["tracking_number"] = malicious_text
    base_signal.normalized_attributes["carrier_code"] = "FEDEX"

    resolved = entity_normalizer.normalize_entities(base_signal)
    ref = resolved.entities.get_references_by_type(EntityType.SHIPMENT)[0]
    assert ref.correlation_confidence == CorrelationConfidence.UNRESOLVED
    assert ref.external_id == malicious_text.strip()
    assert resolved.entities.shipment_id is None


# =============================================================================
# Category 16: FULL PIPELINE INTEGRATION (Tests 49-50)
# =============================================================================
def test_pipeline_end_to_end_entity_normalization(lookup_provider: InMemoryEntityLookupProvider):
    """49. Test end-to-end normalization pipeline integrating domain handler, entity resolver, and corroborator."""
    normalizer = EntityNormalizer(lookup_provider=lookup_provider)
    pipeline = NormalizationPipeline(entity_normalizer=normalizer)

    event = CanonicalExternalEvent(
        event_id="can_test_49",
        org_id="org_alpha",
        provider="Karrio",
        source_event_id="ext_49",
        event_type=CanonicalEventType.SHIPMENT_STATUS,
        event_timestamp=datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc),
        latitude=34.05,
        longitude=-118.25,
        correlation=EntityCorrelation(shipment_id="shp_alpha_001"),
        normalized_attributes={"unlocode": "USLAX"},
        source_type=EventSourceType.REAL,
        quality=EventQuality.VALID,
    )

    result = pipeline.normalize_event(event)
    assert result.status == NormalizationStatus.VALID
    assert result.signal is not None
    assert result.signal.entities.shipment_id == "shp_alpha_001"
    assert result.signal.entities.port_id == "port_la_001"
    assert len(result.signal.entities.references) >= 2


def test_pipeline_batch_entity_normalization_with_corroboration(lookup_provider: InMemoryEntityLookupProvider):
    """50. Test batch normalization and deduplication through pipeline with multi-source corroboration."""
    normalizer = EntityNormalizer(lookup_provider=lookup_provider)
    pipeline = NormalizationPipeline(entity_normalizer=normalizer)

    events = [
        CanonicalExternalEvent(
            event_id="can_batch_1",
            org_id="org_alpha",
            provider="TomTom",
            source_event_id="tt_1",
            event_type=CanonicalEventType.ROAD_CLOSURE,
            event_timestamp=datetime(2026, 9, 8, 14, 0, 0, tzinfo=timezone.utc),
            latitude=34.05,
            longitude=-118.25,
            source_type=EventSourceType.REAL,
            quality=EventQuality.VALID,
        ),
        CanonicalExternalEvent(
            event_id="can_batch_2",
            org_id="org_alpha",
            provider="Tavily",
            source_event_id="tav_1",
            event_type=CanonicalEventType.ROAD_CLOSURE,
            event_timestamp=datetime(2026, 9, 8, 14, 10, 0, tzinfo=timezone.utc),
            latitude=34.05,
            longitude=-118.25,
            source_type=EventSourceType.ESTIMATED,
            quality=EventQuality.VALID,
        ),
    ]

    batch_result = pipeline.normalize_batch(events)
    assert batch_result.valid_count + batch_result.partial_count == 2

    # Deduplicate & corroborate
    corroborated = pipeline.deduplicate_and_corroborate(batch_result.signals)
    assert len(corroborated) == 1
    primary = corroborated[0]
    assert primary.provider == "TomTom"
    assert len(primary.supporting_sources) == 1
    assert primary.supporting_sources[0].provider == "Tavily"
