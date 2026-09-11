"""Unit tests for Canonical External Event Model and Normalization Boundary.

Validates all 27 canonical normalization requirements:
1. Canonical event creation
2. Required field validation
3. Timestamp normalization to UTC
4. Malformed timestamp rejection
5. Timezone conversion
6. Latitude range validation (-90 to +90)
7. Longitude range validation (-180 to +180)
8. Optional location handling (non-geographic events allowed)
9. Event taxonomy validation
10. Unknown / extensible event types
11. Source type handling (REAL, SIMULATED, ESTIMATED)
12. Severity handling (INFO, LOW, MEDIUM, HIGH, CRITICAL)
13. Confidence handling (0.0 to 1.0)
14. Known entity correlation
15. Unresolved correlation (event retained without entity link)
16. Provider / source traceability
17. Payload fingerprint preservation
18. Idempotency integration with Step 1 architecture
19. Raw vs Canonical separation (raw payload preserved)
20. VALID quality state evaluation
21. PARTIAL quality state evaluation
22. INVALID quality state evaluation
23. Normalizer interface abstraction
24. Fake provider normalization (weather, AIS, traffic)
25. Sensitive payload sanitization
26. Full serialization / deserialization round-trip
27. Regression compatibility and storage boundary
"""

import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

import pytest
from pydantic import ValidationError

from app.integrations import (
    BaseEventNormalizer,
    CanonicalEventType,
    CanonicalEventStorage,
    CanonicalExternalEvent,
    CoordinateValidator,
    DefaultEventNormalizer,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
    IdempotencyEngine,
    InMemoryCanonicalEventStorage,
    MockAISNormalizer,
    MockTrafficNormalizer,
    MockWeatherNormalizer,
    NormalizationPipeline,
    RawEvent,
    SecretResolver,
    ShipmentEventBridge,
    TimestampNormalizer,
)


# =====================================================================
# 27 Canonical Event Unit Tests
# =====================================================================

def test_01_canonical_event_creation():
    """1. Test successful creation of CanonicalExternalEvent with all core fields."""
    event = CanonicalExternalEvent(
        provider="openweather",
        event_type=CanonicalEventType.WEATHER_ALERT,
        event_timestamp=datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc),
        source_event_id="wx_alert_991",
        severity=EventSeverity.HIGH,
        confidence=0.92,
        location=EventLocation(latitude=1.3521, longitude=103.8198, location_name="Singapore Strait"),
    )
    assert event.provider == "openweather"
    assert event.event_type == CanonicalEventType.WEATHER_ALERT
    assert event.severity == EventSeverity.HIGH
    assert event.confidence == 0.92
    assert event.latitude == 1.3521
    assert event.longitude == 103.8198
    assert event.event_id is not None
    assert event.received_at is not None


def test_02_required_field_validation():
    """2. Test validation failures when mandatory fields are omitted."""
    # Missing provider
    with pytest.raises(ValidationError) as exc_info:
        CanonicalExternalEvent(
            event_type=CanonicalEventType.WEATHER_ALERT,
            event_timestamp=datetime.now(timezone.utc),
        )
    assert "provider" in str(exc_info.value)

    # Missing event_timestamp
    with pytest.raises(ValidationError) as exc_info:
        CanonicalExternalEvent(
            provider="test_provider",
            event_type=CanonicalEventType.WEATHER_ALERT,
        )
    assert "event_timestamp" in str(exc_info.value)


def test_03_timestamp_normalization_to_utc():
    """3. Test normalization of ISO strings, Unix timestamps, and naive datetimes to UTC."""
    # ISO string with UTC 'Z'
    dt1 = TimestampNormalizer.parse_to_utc("2026-09-07T14:30:00Z")
    assert dt1.tzinfo == timezone.utc
    assert dt1.hour == 14 and dt1.minute == 30

    # Unix epoch seconds
    dt2 = TimestampNormalizer.parse_to_utc(1788777000.0)
    assert dt2.tzinfo == timezone.utc

    # Unix epoch milliseconds
    dt3 = TimestampNormalizer.parse_to_utc(1788777000000)
    assert dt3.tzinfo == timezone.utc
    assert dt2 == dt3

    # Naive datetime gets converted to UTC
    naive = datetime(2026, 9, 7, 18, 0, 0)
    dt4 = TimestampNormalizer.parse_to_utc(naive)
    assert dt4.tzinfo == timezone.utc
    assert dt4.hour == 18


def test_04_malformed_timestamp_rejection():
    """4. Test rejection of impossible or unparseable timestamps."""
    with pytest.raises(ValueError):
        TimestampNormalizer.parse_to_utc("not-a-timestamp")

    with pytest.raises(ValueError):
        TimestampNormalizer.parse_to_utc("")

    with pytest.raises(ValueError):
        TimestampNormalizer.parse_to_utc(None)


def test_05_timezone_conversion():
    """5. Test timezone-offset datetime is converted precisely to UTC equivalent."""
    # +05:30 offset
    tz_ist = timezone(timedelta(hours=5, minutes=30))
    dt_ist = datetime(2026, 9, 7, 17, 30, 0, tzinfo=tz_ist)
    dt_utc = TimestampNormalizer.parse_to_utc(dt_ist)

    assert dt_utc.tzinfo == timezone.utc
    assert dt_utc.hour == 12
    assert dt_utc.minute == 0


def test_06_latitude_range_validation():
    """6. Test latitude bounds [-90, +90] are strictly validated."""
    # Valid bounds
    lat, _ = CoordinateValidator.validate(45.0, 0.0)
    assert lat == 45.0
    lat_edge, _ = CoordinateValidator.validate(-90.0, 0.0)
    assert lat_edge == -90.0

    # Invalid latitude > 90
    with pytest.raises(ValueError) as exc1:
        CoordinateValidator.validate(90.1, 0.0)
    assert "Latitude out of bounds" in str(exc1.value)

    # Invalid latitude < -90
    with pytest.raises(ValueError) as exc2:
        CoordinateValidator.validate(-95.0, 0.0)
    assert "Latitude out of bounds" in str(exc2.value)


def test_07_longitude_range_validation():
    """7. Test longitude bounds [-180, +180] are strictly validated."""
    # Valid bounds
    _, lon = CoordinateValidator.validate(0.0, 180.0)
    assert lon == 180.0

    # Invalid longitude > 180
    with pytest.raises(ValueError) as exc1:
        CoordinateValidator.validate(0.0, 180.01)
    assert "Longitude out of bounds" in str(exc1.value)

    # Invalid longitude < -180
    with pytest.raises(ValueError) as exc2:
        CoordinateValidator.validate(0.0, -181.0)
    assert "Longitude out of bounds" in str(exc2.value)


def test_08_optional_location_handling():
    """8. Test events without geographic coordinates (e.g. global news) are supported."""
    event = CanonicalExternalEvent(
        provider="reuters_news",
        event_type=CanonicalEventType.NEWS_EVENT,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        location=None,  # Non-geographic event
        normalized_attributes={"headline": "Global container shipping rates stabilize"},
    )
    assert event.location is None
    assert event.latitude is None
    assert event.longitude is None


def test_09_event_taxonomy_validation():
    """9. Test domain event taxonomy classification."""
    assert CanonicalEventType.SHIPMENT_DELAY.value == "SHIPMENT_DELAY"
    assert CanonicalEventType.PORT_CONGESTION.value == "PORT_CONGESTION"
    assert CanonicalEventType.ROAD_INCIDENT.value == "ROAD_INCIDENT"
    assert CanonicalEventType.WEATHER_ALERT.value == "WEATHER_ALERT"
    assert CanonicalEventType.VESSEL_LOCATION.value == "VESSEL_LOCATION"
    assert CanonicalEventType.FLIGHT_DELAY.value == "FLIGHT_DELAY"
    assert CanonicalEventType.TRAIN_DELAY.value == "TRAIN_DELAY"
    assert CanonicalEventType.PARCEL_STATUS.value == "PARCEL_STATUS"
    assert CanonicalEventType.GEOPOLITICAL_EVENT.value == "GEOPOLITICAL_EVENT"


def test_10_unknown_extensible_event_types():
    """10. Test extensible / custom event types are allowed without failing validation."""
    event = CanonicalExternalEvent(
        provider="custom_telemetry",
        event_type="CUSTOM_WAREHOUSE_ROBOTICS_PING",
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert event.event_type == "CUSTOM_WAREHOUSE_ROBOTICS_PING"


def test_11_source_type_handling():
    """11. Test distinction between REAL, SIMULATED, and ESTIMATED source types."""
    assert EventSourceType.REAL.value == "REAL"
    assert EventSourceType.SIMULATED.value == "SIMULATED"
    assert EventSourceType.ESTIMATED.value == "ESTIMATED"

    sim_event = CanonicalExternalEvent(
        provider="risk_simulator",
        event_type=CanonicalEventType.WEATHER_ALERT,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        source_type=EventSourceType.SIMULATED,
    )
    assert sim_event.source_type == EventSourceType.SIMULATED


def test_12_severity_handling():
    """12. Test event operational severity levels (INFO to CRITICAL)."""
    assert EventSeverity.INFO.value == "INFO"
    assert EventSeverity.LOW.value == "LOW"
    assert EventSeverity.MEDIUM.value == "MEDIUM"
    assert EventSeverity.HIGH.value == "HIGH"
    assert EventSeverity.CRITICAL.value == "CRITICAL"

    crit_event = CanonicalExternalEvent(
        provider="traffic_feed",
        event_type=CanonicalEventType.ROAD_CLOSURE,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        severity=EventSeverity.CRITICAL,
    )
    assert crit_event.severity == EventSeverity.CRITICAL


def test_13_confidence_handling():
    """13. Test confidence scoring bounded between 0.0 and 1.0."""
    valid_event = CanonicalExternalEvent(
        provider="ais_stream",
        event_type=CanonicalEventType.VESSEL_LOCATION,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        confidence=0.88,
    )
    assert valid_event.confidence == 0.88

    # Confidence > 1.0 rejected
    with pytest.raises(ValidationError):
        CanonicalExternalEvent(
            provider="ais_stream",
            event_type=CanonicalEventType.VESSEL_LOCATION,
            event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
            confidence=1.05,
        )

    # Confidence < 0.0 rejected
    with pytest.raises(ValidationError):
        CanonicalExternalEvent(
            provider="ais_stream",
            event_type=CanonicalEventType.VESSEL_LOCATION,
            event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
            confidence=-0.1,
        )


def test_14_known_entity_correlation():
    """14. Test correlation with known RiskWise supply chain entities."""
    correlation = EntityCorrelation(
        shipment_id="shp_sg_syd_001",
        carrier_id="car_maersk_01",
        port_id="prt_singapore",
        route_id="rot_malacca_sydney",
    )
    assert correlation.is_correlated is True

    event = CanonicalExternalEvent(
        provider="carrier_tracking",
        event_type=CanonicalEventType.SHIPMENT_STATUS,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        correlation=correlation,
    )
    assert event.is_correlated is True
    assert event.shipment_id == "shp_sg_syd_001"


def test_15_unresolved_correlation():
    """15. Test that events with unresolved correlations are fully preserved."""
    event = CanonicalExternalEvent(
        provider="ais_coastal_radar",
        event_type=CanonicalEventType.VESSEL_LOCATION,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        correlation=EntityCorrelation(custom_identifiers={"mmsi": "563000111"}),
    )
    # shipment_id is None, but event is retained
    assert event.shipment_id is None
    assert event.correlation.custom_identifiers["mmsi"] == "563000111"


def test_16_provider_source_traceability():
    """16. Test end-to-end source traceability propagation."""
    raw = RawEvent(
        provider_name="openweather",
        provider_event_id="wx_obs_12345",
        raw_payload={"temp_c": 28.0, "lat": 1.3, "lon": 103.8},
        fingerprint="abc_sha256_fp",
        org_id="org_riskwise_prod",
    )
    pipeline = NormalizationPipeline()
    pipeline.register_normalizer(MockWeatherNormalizer())

    canonical = pipeline.normalize(raw)
    assert canonical.provider == "openweather"
    assert canonical.source_event_id == "wx_obs_12345"
    assert canonical.raw_event_id == raw.id
    assert canonical.payload_fingerprint == "abc_sha256_fp"
    assert canonical.org_id == "org_riskwise_prod"


def test_17_payload_fingerprint_preservation():
    """17. Test that payload fingerprint is retained on CanonicalExternalEvent."""
    raw = RawEvent(
        provider_name="sensor_feed",
        raw_payload={"sensor_id": 42},
        fingerprint="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )
    pipeline = NormalizationPipeline()
    canonical = pipeline.normalize(raw)
    assert canonical.payload_fingerprint == raw.fingerprint


def test_18_idempotency_integration():
    """18. Test integration with Step 1 IdempotencyEngine."""
    engine = IdempotencyEngine()
    raw1 = RawEvent(
        provider_name="tomtom",
        provider_event_id="tt_inc_501",
        raw_payload={"delay_minutes": 25.0},
    )
    raw2 = RawEvent(
        provider_name="tomtom",
        provider_event_id="tt_inc_501",
        raw_payload={"delay_minutes": 25.0},
    )

    # Check Step 1 deduplication
    is_unique_1, fp1 = engine.check_and_record(raw1)
    is_unique_2, fp2 = engine.check_and_record(raw2)
    assert is_unique_1 is True
    assert is_unique_2 is False
    assert fp1 == fp2

    # Verify canonical event carries the deduplication fingerprint
    raw1.fingerprint = fp1
    pipeline = NormalizationPipeline()
    canonical = pipeline.normalize(raw1)
    assert canonical.payload_fingerprint == fp1


def test_19_raw_canonical_separation():
    """19. Test raw payload is preserved and not overwritten by normalized properties."""
    original_raw_payload = {"temp_c": 30.0, "raw_extra_vendor_code": "0xDEADBEEF"}
    raw = RawEvent(
        provider_name="mock_weather",
        raw_payload=dict(original_raw_payload),
    )
    pipeline = NormalizationPipeline()
    pipeline.register_normalizer(MockWeatherNormalizer())

    canonical = pipeline.normalize(raw)
    # Raw payload remains untouched in raw event
    assert raw.raw_payload["raw_extra_vendor_code"] == "0xDEADBEEF"
    # Canonical event has structured normalized_attributes
    assert canonical.normalized_attributes["temperature_celsius"] == 30.0


def test_20_valid_quality_state():
    """20. Test VALID quality assignment when core, location, and correlation are populated."""
    pipeline = NormalizationPipeline()
    pipeline.register_normalizer(MockWeatherNormalizer())

    raw = RawEvent(
        provider_name="mock_weather",
        raw_payload={
            "temp_c": 24.0,
            "lat": 1.35,
            "lon": 103.82,
            "route_id": "rot_sg_my_01",
        },
    )
    canonical = pipeline.normalize(raw)
    assert canonical.quality == EventQuality.VALID
    assert len(canonical.validation_errors) == 0


def test_21_partial_quality_state():
    """21. Test PARTIAL quality assignment when location or correlation is missing."""
    pipeline = NormalizationPipeline()
    raw = RawEvent(
        provider_name="generic_provider",
        raw_payload={"headline": "Port workers announce 24hr strike"},
        event_type="NEWS_EVENT",
    )
    canonical = pipeline.normalize(raw)
    # Valid event, but lacks spatial coords and correlation
    assert canonical.quality == EventQuality.PARTIAL
    assert canonical.is_correlated is False


def test_22_invalid_quality_state():
    """22. Test INVALID quality assignment when spatial coordinates are out of bounds."""
    pipeline = NormalizationPipeline()
    raw = RawEvent(
        provider_name="broken_sensor",
        raw_payload={"latitude": 999.0, "longitude": 0.0},
    )
    canonical = pipeline.normalize(raw)
    assert canonical.quality == EventQuality.INVALID
    assert any("out of bounds" in err for err in canonical.validation_errors)


def test_23_normalizer_interface_abstraction():
    """23. Test custom normalizer subclassing BaseEventNormalizer."""
    class CustomCustomsNormalizer(BaseEventNormalizer):
        def can_normalize(self, raw_event: RawEvent) -> bool:
            return raw_event.provider_name == "customs_broker"

        def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
            return CanonicalExternalEvent(
                provider=raw_event.provider_name,
                event_type=CanonicalEventType.SHIPMENT_STATUS,
                event_timestamp=raw_event.ingested_at,
                status="CUSTOMS_CLEARED",
            )

    norm = CustomCustomsNormalizer()
    raw = RawEvent(provider_name="customs_broker")
    assert norm.can_normalize(raw) is True
    canonical = norm.normalize(raw)
    assert canonical.status == "CUSTOMS_CLEARED"


def test_24_fake_provider_normalization():
    """24. Test normalization across mock weather, AIS, and traffic providers."""
    pipeline = NormalizationPipeline()
    pipeline.register_normalizer(MockWeatherNormalizer())
    pipeline.register_normalizer(MockAISNormalizer())
    pipeline.register_normalizer(MockTrafficNormalizer())

    # 1. Weather
    raw_wx = RawEvent(
        provider_name="mock_weather",
        raw_payload={"temp_c": 46.0, "wind_speed_knots": 45.0, "lat": 25.2, "lon": 55.3},
    )
    canon_wx = pipeline.normalize(raw_wx)
    assert canon_wx.event_type == CanonicalEventType.WEATHER_ALERT
    assert canon_wx.severity == EventSeverity.HIGH

    # 2. Ocean AIS
    raw_ais = RawEvent(
        provider_name="mock_ais",
        raw_payload={"mmsi": "123456789", "speed": 14.5, "heading": 90, "lat": 1.2, "lon": 103.7},
    )
    canon_ais = pipeline.normalize(raw_ais)
    assert canon_ais.event_type == CanonicalEventType.VESSEL_LOCATION
    assert canon_ais.normalized_attributes["speed_knots"] == 14.5

    # 3. Traffic
    raw_traffic = RawEvent(
        provider_name="mock_traffic",
        raw_payload={"delay_minutes": 45.0, "road_name": "A1 Motorway", "lat": 51.5, "lon": -0.1},
    )
    canon_traffic = pipeline.normalize(raw_traffic)
    assert canon_traffic.event_type == CanonicalEventType.ROAD_INCIDENT
    assert canon_traffic.severity == EventSeverity.HIGH


def test_25_sensitive_payload_sanitization():
    """25. Test that API credentials in raw payload are sanitized during normalization."""
    raw = RawEvent(
        provider_name="external_api",
        raw_payload={
            "api_key": "AKIA_SECRET_XYZ",
            "auth_token": "bearer secret_token_123",
            "data": {"temp": 25},
        },
    )
    pipeline = NormalizationPipeline()
    canonical = pipeline.normalize(raw)

    # Ensure sensitive fields are redacted in raw payload and normalized attributes
    assert raw.raw_payload["api_key"] == "[REDACTED]"
    assert raw.raw_payload["auth_token"] == "[REDACTED]"
    assert canonical.normalized_attributes["api_key"] == "[REDACTED]"


def test_26_serialization_deserialization_round_trip():
    """26. Test full JSON serialization and deserialization round-trip."""
    event = CanonicalExternalEvent(
        provider="tomtom",
        event_type=CanonicalEventType.ROAD_INCIDENT,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        location=EventLocation(latitude=52.37, longitude=4.89, location_name="Amsterdam"),
        correlation=EntityCorrelation(shipment_id="shp_ams_01"),
        severity=EventSeverity.MEDIUM,
        delay_minutes=18.5,
    )
    json_str = event.model_dump_json()
    parsed_dict = json.loads(json_str)
    assert parsed_dict["provider"] == "tomtom"
    assert parsed_dict["location"]["latitude"] == 52.37

    reconstructed = CanonicalExternalEvent.model_validate_json(json_str)
    assert reconstructed.provider == event.provider
    assert reconstructed.event_type == event.event_type
    assert reconstructed.latitude == event.latitude
    assert reconstructed.shipment_id == event.shipment_id


def test_27_regression_compatibility_and_storage_boundary():
    """27. Test CanonicalEventStorage and ShipmentEventBridge without database migrations."""
    # Test CanonicalEventStorage boundary
    storage: CanonicalEventStorage = InMemoryCanonicalEventStorage()
    event = CanonicalExternalEvent(
        provider="maritime_feed",
        event_type=CanonicalEventType.VESSEL_LOCATION,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        correlation=EntityCorrelation(shipment_id="shp_test_bridge_01"),
        location=EventLocation(latitude=1.2, longitude=103.8),
    )
    event_id = storage.store(event)
    assert event_id == event.event_id
    retrieved = storage.get_event(event_id)
    assert retrieved is not None
    assert retrieved.provider == "maritime_feed"

    # Test ShipmentEventBridge
    assert ShipmentEventBridge.can_persist_to_shipment_event(event) is True
    bridge_dict = ShipmentEventBridge.to_shipment_event_dict(event)
    assert bridge_dict["shipment_id"] == "shp_test_bridge_01"
    assert bridge_dict["latitude"] == 1.2
    assert "metadata_json" in bridge_dict

    # Uncorrelated event bridge rejection
    uncorrelated_event = CanonicalExternalEvent(
        provider="maritime_feed",
        event_type=CanonicalEventType.VESSEL_LOCATION,
        event_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert ShipmentEventBridge.can_persist_to_shipment_event(uncorrelated_event) is False
    with pytest.raises(ValueError):
        ShipmentEventBridge.to_shipment_event_dict(uncorrelated_event)
