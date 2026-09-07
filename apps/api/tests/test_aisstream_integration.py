"""Unit tests for Phase 5 Step 5: Ocean / AIS Data Integration (AISStream).

Covers at least 44 focused unit tests using mocked WebSocket transport (zero live network calls):
 1. Adapter initialization
 2. Capability inspection
 3. Configuration loading
 4. Missing API key handling
 5. Custom configuration overrides
 6. WebSocket endpoint configuration
 7. Subscription construction
 8. Bounding-box subscription
 9. Vessel/MMSI filtering when supported
10. Successful connection
11. Authentication handling
12. Message reception
13. Malformed message handling
14. Missing required message fields
15. MMSI mapping
16. Latitude mapping
17. Longitude mapping
18. Timestamp normalization
19. Heading mapping
20. Course-over-ground mapping
21. Speed-over-ground mapping
22. Vessel identity mapping
23. Navigational status mapping
24. Coordinate validation
25. Invalid latitude rejection
26. Invalid longitude rejection
27. Canonical event generation
28. EventQuality behavior
29. Unresolved shipment correlation
30. Valid shipment correlation
31. ShipmentEventBridge behavior
32. Deterministic idempotency
33. Duplicate message handling
34. Legitimate consecutive positions are not incorrectly deduplicated
35. Raw payload preservation
36. Secret redaction
37. Transient disconnect handling
38. Reconnect/backoff behavior
39. Authentication failure is not endlessly retried
40. Provider health check
41. Observability metadata
42. Tenant/org isolation
43. Graceful shutdown
44. Unsupported message handling
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

from app.integrations import (
    AISStreamAdapter,
    AISStreamNormalizer,
    AISStreamSubscription,
    AISWebSocketTransport,
    MockAISWebSocketTransport,
    AuthMode,
    BaseEventNormalizer,
    CanonicalEventType,
    CanonicalExternalEvent,
    CoordinateValidator,
    DEFAULT_AISSTREAM_URL,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
    IdempotencyEngine,
    InMemoryCanonicalEventStorage,
    InMemoryRawEventStorage,
    IngestionBatch,
    IngestionService,
    NormalizationPipeline,
    ProviderAuthenticationError,
    ProviderCapabilities,
    ProviderConfig,
    ProviderConnectionError,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderType,
    ProviderValidationError,
    RateLimitConfig,
    RawEvent,
    RetryConfig,
    RetryPolicy,
    SecretResolver,
    ShipmentEventBridge,
    TimestampNormalizer,
    default_provider_registry,
)


# =====================================================================
# Fixtures & Sample Payloads
# =====================================================================

@pytest.fixture
def sample_position_report() -> dict[str, Any]:
    """Verified AISStream PositionReport payload."""
    return {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": 244710000,
            "ShipName": "ROTTERDAM STAR",
            "latitude": 51.9244,
            "longitude": 4.4777,
            "time_utc": "2026-09-08 00:15:30.000000 +0000 UTC",
        },
        "Message": {
            "PositionReport": {
                "Cog": 182.5,
                "Sog": 12.8,
                "TrueHeading": 180,
                "NavigationalStatus": 0,  # Under way using engine
                "Latitude": 51.9244,
                "Longitude": 4.4777,
                "Timestamp": 30,
                "UserID": 244710000,
                "RateOfTurn": 0,
            }
        },
    }


@pytest.fixture
def sample_static_data() -> dict[str, Any]:
    """Verified AISStream ShipStaticData payload."""
    return {
        "MessageType": "ShipStaticData",
        "MetaData": {
            "MMSI": 244710000,
            "ShipName": "ROTTERDAM STAR",
            "latitude": 51.9244,
            "longitude": 4.4777,
            "time_utc": "2026-09-08 00:15:30.000000 +0000 UTC",
        },
        "Message": {
            "ShipStaticData": {
                "ImoNumber": 9321483,
                "CallSign": "PD3841",
                "Name": "ROTTERDAM STAR",
                "Type": 70,  # Cargo ship
                "Destination": "ANTWERP",
                "Dimension": {"A": 120, "B": 280, "C": 20, "D": 22},
                "Draught": 14.5,
                "Eta": {"Month": 9, "Day": 10, "Hour": 18, "Minute": 0},
            }
        },
    }


@pytest.fixture
def sample_subscription() -> AISStreamSubscription:
    """Valid AISStream subscription with bounding boxes and filters."""
    return AISStreamSubscription(
        bounding_boxes=[[[51.0, 3.0], [53.0, 5.0]]],
        filters_ship_mmsi=["244710000"],
        filter_message_types=["PositionReport", "ShipStaticData"],
    )


@pytest.fixture
def mock_transport() -> MockAISWebSocketTransport:
    return MockAISWebSocketTransport()


@pytest.fixture
def adapter(mock_transport: MockAISWebSocketTransport) -> AISStreamAdapter:
    return AISStreamAdapter(
        secret="test-aisstream-api-key",
        transport=mock_transport,
    )


@pytest.fixture
def normalizer() -> AISStreamNormalizer:
    return AISStreamNormalizer()


# =====================================================================
# Unit Tests (1 to 44)
# =====================================================================

def test_01_adapter_initialization(adapter: AISStreamAdapter) -> None:
    """1. Verify adapter attributes, provider name, and provider type."""
    assert adapter.provider_name == "aisstream"
    assert adapter.provider_type == ProviderType.OCEAN_AIS
    assert adapter.capabilities is not None
    assert adapter.config is not None


def test_02_capability_inspection(adapter: AISStreamAdapter) -> None:
    """2. Verify declared streaming capabilities without fake polling/webhooks."""
    caps = adapter.capabilities
    assert caps.supports_streaming is True
    assert caps.supports_polling is False
    assert caps.supports_webhook is False
    assert caps.supports_batch is True
    assert caps.supports_health_check is True
    assert "ocean" in caps.supported_modalities
    assert "vessel" in caps.supported_entities


def test_03_configuration_loading(adapter: AISStreamAdapter) -> None:
    """3. Verify default configuration parameters."""
    cfg = adapter.config
    assert cfg.provider_name == "aisstream"
    assert cfg.provider_type == ProviderType.OCEAN_AIS
    assert cfg.base_url == DEFAULT_AISSTREAM_URL
    assert cfg.rate_limit.requests_per_minute == 120


def test_04_missing_api_key() -> None:
    """4. Verify missing API key raises ProviderAuthenticationError."""
    resolver = SecretResolver()
    adapter = AISStreamAdapter(secret=None, secret_resolver=resolver)
    adapter.config.secret_ref = "env:NONEXISTENT_KEY_12345"

    with pytest.raises(ProviderAuthenticationError) as exc_info:
        adapter._resolve_api_key()
    assert "missing" in str(exc_info.value).lower() or "not be resolved" in str(exc_info.value).lower()



def test_05_custom_configuration() -> None:
    """5. Verify custom configuration overrides base URL, rate limits, and timeouts."""
    custom_cfg = ProviderConfig(
        provider_name="aisstream",
        provider_type=ProviderType.OCEAN_AIS,
        base_url="wss://custom.stream.aisstream.io/v1",
        timeout_seconds=25.0,
        rate_limit=RateLimitConfig(requests_per_minute=300),
        retry=RetryConfig(max_retries=5, initial_delay_seconds=1.0),
    )
    adapter = AISStreamAdapter(config=custom_cfg, secret="custom-key")
    assert adapter.config.base_url == "wss://custom.stream.aisstream.io/v1"
    assert adapter.config.timeout_seconds == 25.0
    assert adapter.config.rate_limit.requests_per_minute == 300
    assert adapter.config.retry.max_retries == 5


def test_06_websocket_endpoint_configuration(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """6. Verify connection uses verified WebSocket endpoint."""
    adapter.connect()
    assert mock_transport.is_connected is True
    assert mock_transport._url == DEFAULT_AISSTREAM_URL


def test_07_subscription_construction(sample_subscription: AISStreamSubscription) -> None:
    """7. Verify subscription serialization matches verified AISStream JSON spec."""
    payload = sample_subscription.to_subscription_payload(api_key="secret-key-xyz")
    assert payload["APIKey"] == "secret-key-xyz"
    assert "BoundingBoxes" in payload
    assert payload["BoundingBoxes"] == [[[51.0, 3.0], [53.0, 5.0]]]
    assert payload["FiltersShipMMSI"] == ["244710000"]
    assert payload["FilterMessageTypes"] == ["PositionReport", "ShipStaticData"]


def test_08_bounding_box_subscription() -> None:
    """8. Verify bounding-box subscription accepts multi-point geographic bounds."""
    sub = AISStreamSubscription(
        bounding_boxes=[
            [[28.0, 32.0], [31.5, 33.5]],  # Suez Canal
            [[1.0, 103.0], [1.5, 104.5]],  # Malacca Strait
        ]
    )
    payload = sub.to_subscription_payload("my-key")
    assert len(payload["BoundingBoxes"]) == 2


def test_09_vessel_mmsi_filtering() -> None:
    """9. Verify MMSI filter constraints (max 200 items, non-empty)."""
    sub = AISStreamSubscription(
        bounding_boxes=[[[10.0, 20.0], [11.0, 21.0]]],
        filters_ship_mmsi=["123456789", "987654321"],
    )
    payload = sub.to_subscription_payload("test-key")
    assert payload["FiltersShipMMSI"] == ["123456789", "987654321"]

    # Reject more than 200 MMSIs
    with pytest.raises(ValueError) as exc:
        AISStreamSubscription(
            bounding_boxes=[[[10.0, 20.0], [11.0, 21.0]]],
            filters_ship_mmsi=[str(i) for i in range(205)],
        )
    assert "200 MMSI" in str(exc.value)


def test_10_successful_connection(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """10. Verify successful connection lifecycle."""
    assert not mock_transport.is_connected
    adapter.connect()
    assert mock_transport.is_connected
    adapter.close()
    assert not mock_transport.is_connected


def test_11_authentication_handling(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport, sample_subscription: AISStreamSubscription) -> None:
    """11. Verify authentication key is dispatched inside initial subscription frame."""
    adapter.subscribe(sample_subscription)
    assert len(mock_transport.sent_messages) == 1
    sent_frame = json.loads(mock_transport.sent_messages[0])
    assert sent_frame["APIKey"] == "test-aisstream-api-key"


def test_12_message_reception(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport, sample_position_report: dict[str, Any]) -> None:
    """12. Verify message reception wraps frame into RawEvent."""
    adapter.connect()
    mock_transport.queue_message(sample_position_report)

    raw_event = adapter.receive_raw_message()
    assert isinstance(raw_event, RawEvent)
    assert raw_event.provider_name == "aisstream"
    assert raw_event.provider_type == ProviderType.OCEAN_AIS
    assert raw_event.metadata["message_type"] == "PositionReport"
    assert raw_event.metadata["mmsi"] == "244710000"


def test_13_malformed_message(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """13. Verify malformed (non-JSON) frame raises ProviderValidationError."""
    adapter.connect()
    mock_transport.queue_message("NOT_VALID_JSON{")

    with pytest.raises(ProviderValidationError) as exc:
        adapter.receive_raw_message()
    assert "Malformed JSON" in str(exc.value)


def test_14_missing_required_message_fields(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """14. Verify missing envelope fields (e.g. no MetaData) raises ProviderValidationError."""
    adapter.connect()
    mock_transport.queue_message({"MessageType": "PositionReport"})  # Missing MetaData & Message

    with pytest.raises(ProviderValidationError) as exc:
        adapter.receive_raw_message()
    assert "Missing required" in str(exc.value)


def test_15_mmsi_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """15. Verify MMSI mapped to canonical correlation custom identifiers."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.correlation.custom_identifiers.get("mmsi") == "244710000"


def test_16_latitude_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """16. Verify latitude correctly extracted and mapped to EventLocation."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.location is not None
    assert canonical.location.latitude == 51.9244


def test_17_longitude_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """17. Verify longitude correctly extracted and mapped to EventLocation."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.location is not None
    assert canonical.location.longitude == 4.4777


def test_18_timestamp_normalization(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """18. Verify AIS timestamp string normalized to timezone-aware UTC datetime."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.event_timestamp.tzinfo == timezone.utc
    assert canonical.event_timestamp.year == 2026
    assert canonical.event_timestamp.month == 9
    assert canonical.event_timestamp.day == 8


def test_19_heading_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """19. Verify TrueHeading mapped to normalized_attributes."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes.get("heading_degrees") == 180


def test_20_course_over_ground_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """20. Verify Course Over Ground (Cog) mapped to normalized_attributes."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes.get("course_over_ground") == 182.5


def test_21_speed_over_ground_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """21. Verify Speed Over Ground (Sog) mapped to speed_over_ground_knots."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes.get("speed_over_ground_knots") == 12.8


def test_22_vessel_identity_mapping(normalizer: AISStreamNormalizer, sample_static_data: dict[str, Any]) -> None:
    """22. Verify static vessel identity (Name, CallSign, ImoNumber) mapped to correlation."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_static_data)
    canonical = normalizer.normalize(raw)
    idents = canonical.correlation.custom_identifiers
    assert idents.get("mmsi") == "244710000"
    assert idents.get("imo") == "9321483"
    assert idents.get("call_sign") == "PD3841"
    assert idents.get("vessel_name") == "ROTTERDAM STAR"


def test_23_navigational_status_mapping(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """23. Verify navigational status maps normal underway to INFO, aground/distress to CRITICAL."""
    # Underway
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.event_type == CanonicalEventType.VESSEL_LOCATION
    assert canonical.severity == EventSeverity.INFO
    assert canonical.status == "UNDERWAY"

    # Aground (Status 6)
    sample_position_report["Message"]["PositionReport"]["NavigationalStatus"] = 6
    raw_aground = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical_aground = normalizer.normalize(raw_aground)
    assert canonical_aground.event_type == CanonicalEventType.MARITIME_INCIDENT
    assert canonical_aground.severity == EventSeverity.CRITICAL
    assert canonical_aground.status == "AGROUND"

    # Distress (Status 14)
    sample_position_report["Message"]["PositionReport"]["NavigationalStatus"] = 14
    raw_distress = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical_distress = normalizer.normalize(raw_distress)
    assert canonical_distress.event_type == CanonicalEventType.MARITIME_INCIDENT
    assert canonical_distress.severity == EventSeverity.CRITICAL
    assert canonical_distress.status == "DISTRESS"

    # Not under command (Status 2)
    sample_position_report["Message"]["PositionReport"]["NavigationalStatus"] = 2
    raw_nuc = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical_nuc = normalizer.normalize(raw_nuc)
    assert canonical_nuc.event_type == CanonicalEventType.MARITIME_INCIDENT
    assert canonical_nuc.severity == EventSeverity.HIGH
    assert canonical_nuc.status == "NOT_UNDER_COMMAND"


def test_24_coordinate_validation() -> None:
    """24. Verify CoordinateValidator ensures coordinates are within WGS84 limits."""
    lat, lon = CoordinateValidator.validate(45.0, -75.0)
    assert lat == 45.0
    assert lon == -75.0


def test_25_invalid_latitude() -> None:
    """25. Verify out-of-range latitude (>90 or <-90) is rejected."""
    with pytest.raises(ValueError):
        CoordinateValidator.validate(91.5, 0.0)

    with pytest.raises(ValueError):
        AISStreamSubscription(bounding_boxes=[[[95.0, 10.0], [96.0, 12.0]]])


def test_26_invalid_longitude() -> None:
    """26. Verify out-of-range longitude (>180 or <-180) is rejected."""
    with pytest.raises(ValueError):
        CoordinateValidator.validate(0.0, 185.0)

    with pytest.raises(ValueError):
        AISStreamSubscription(bounding_boxes=[[[10.0, 185.0], [12.0, 186.0]]])


def test_27_canonical_event_generation(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """27. Verify canonical event generation produces a fully populated model."""
    raw = RawEvent(
        provider_name="aisstream",
        provider_event_id="aisstream:244710000:PositionReport",
        raw_payload=sample_position_report,
        org_id="tenant-alpha",
    )
    canonical = normalizer.normalize(raw)
    assert canonical.provider == "aisstream"
    assert canonical.source_event_id == "aisstream:244710000:PositionReport"
    assert canonical.event_type == CanonicalEventType.VESSEL_LOCATION
    assert canonical.org_id == "tenant-alpha"
    assert canonical.quality == EventQuality.VALID


def test_28_event_quality_behavior(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """28. Verify EventQuality marks complete message VALID, missing location PARTIAL."""
    # Valid
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    assert normalizer.normalize(raw).quality == EventQuality.VALID

    # Missing coordinates -> PARTIAL
    sample_position_report["MetaData"]["latitude"] = None
    sample_position_report["Message"]["PositionReport"]["Latitude"] = None
    raw_partial = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    assert normalizer.normalize(raw_partial).quality == EventQuality.PARTIAL


def test_29_unresolved_shipment_correlation(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """29. Verify raw observation without shipment link leaves correlation.shipment_id unresolved."""
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.correlation.shipment_id is None
    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical) is False


def test_30_valid_shipment_correlation(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """30. Verify when shipment link is explicitly correlated, correlation.shipment_id is set."""
    sample_position_report["shipment_id"] = "SHP-2026-999"
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)
    assert canonical.correlation.shipment_id == "SHP-2026-999"
    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical) is True


def test_31_shipment_event_bridge_behavior(normalizer: AISStreamNormalizer, sample_position_report: dict[str, Any]) -> None:
    """31. Verify ShipmentEventBridge converts correlated canonical event into DB dictionary."""
    sample_position_report["shipment_id"] = "SHP-2026-888"
    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report)
    canonical = normalizer.normalize(raw)

    bridge_dict = ShipmentEventBridge.to_shipment_event_dict(canonical)
    assert bridge_dict["shipment_id"] == "SHP-2026-888"
    assert bridge_dict["mode"] == "OCEAN"
    assert bridge_dict["latitude"] == 51.9244
    assert bridge_dict["longitude"] == 4.4777
    assert bridge_dict["status"] == "UNDERWAY"


def test_32_deterministic_idempotency(sample_position_report: dict[str, Any]) -> None:
    """32. Verify identical messages produce identical deterministic SHA-256 fingerprints."""
    fp1 = AISStreamAdapter.compute_fingerprint(sample_position_report, org_id="tenant-1")
    fp2 = AISStreamAdapter.compute_fingerprint(sample_position_report, org_id="tenant-1")
    assert fp1 == fp2
    assert len(fp1) == 64


def test_33_duplicate_message_handling(sample_position_report: dict[str, Any]) -> None:
    """33. Verify IdempotencyEngine recognizes duplicate event by fingerprint."""
    engine = IdempotencyEngine()
    fp = AISStreamAdapter.compute_fingerprint(sample_position_report, org_id="tenant-1")
    event = RawEvent(
        provider_name="aisstream",
        provider_event_id="aisstream:244710000:PositionReport",
        fingerprint=fp,
        org_id="tenant-1",
    )

    unique1, _ = engine.check_and_record(event, organization_id="tenant-1")
    assert unique1 is True

    unique2, _ = engine.check_and_record(event, organization_id="tenant-1")
    assert unique2 is False



def test_34_legitimate_consecutive_positions_not_deduplicated(sample_position_report: dict[str, Any]) -> None:
    """34. Verify consecutive vessel positions differing in timestamp or location are NOT deduplicated."""
    fp1 = AISStreamAdapter.compute_fingerprint(sample_position_report, org_id="tenant-1")

    # Second report 10 seconds later, 100 meters forward
    report_2 = json.loads(json.dumps(sample_position_report))
    report_2["MetaData"]["time_utc"] = "2026-09-08 00:15:40.000000 +0000 UTC"
    report_2["MetaData"]["latitude"] = 51.9255
    report_2["Message"]["PositionReport"]["Latitude"] = 51.9255
    fp2 = AISStreamAdapter.compute_fingerprint(report_2, org_id="tenant-1")

    assert fp1 != fp2, "Legitimate consecutive positions must have distinct fingerprints."


def test_35_raw_payload_preservation(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport, sample_position_report: dict[str, Any]) -> None:
    """35. Verify complete provider message payload is preserved uncorrupted in RawEvent."""
    adapter.connect()
    mock_transport.queue_message(sample_position_report)
    raw = adapter.receive_raw_message()

    assert raw.raw_payload["MessageType"] == "PositionReport"
    assert raw.raw_payload["MetaData"]["ShipName"] == "ROTTERDAM STAR"
    assert raw.raw_payload["Message"]["PositionReport"]["Sog"] == 12.8


def test_36_secret_redaction(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport, sample_position_report: dict[str, Any]) -> None:
    """36. Verify API keys or credentials injected into frames are redacted from RawEvent."""
    sample_position_report["APIKey"] = "SUPER_SECRET_TOKEN_DO_NOT_LOG"
    adapter.connect()
    mock_transport.queue_message(sample_position_report)
    raw = adapter.receive_raw_message()

    assert raw.raw_payload["APIKey"] == "[REDACTED]"
    assert "SUPER_SECRET_TOKEN_DO_NOT_LOG" not in json.dumps(raw.raw_payload)


def test_37_transient_disconnect(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """37. Verify connection reset raises ProviderConnectionError."""
    adapter.connect()
    mock_transport.simulate_connection_error = True

    with pytest.raises(ProviderConnectionError):
        adapter.receive_raw_message()


def test_38_reconnect_backoff(mock_transport: MockAISWebSocketTransport) -> None:
    """38. Verify reconnect with bounded backoff policy."""
    policy = RetryPolicy(RetryConfig(max_retries=3, initial_delay_seconds=0.01))
    attempts = 0

    def mock_reconnect() -> bool:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderConnectionError("Temporary drop")
        return True

    res = policy.execute(mock_reconnect)
    assert res is True
    assert attempts == 3


def test_39_auth_failure_not_endlessly_retried(mock_transport: MockAISWebSocketTransport) -> None:
    """39. Verify authentication failure is not endlessly retried."""
    policy = RetryPolicy(RetryConfig(max_retries=5, initial_delay_seconds=0.01))
    call_count = 0

    def fail_auth() -> None:
        nonlocal call_count
        call_count += 1
        raise ProviderAuthenticationError("Invalid API key")

    with pytest.raises(ProviderAuthenticationError):
        policy.execute(fail_auth)

    assert call_count == 1, "Authentication errors must NOT be retried."


def test_40_provider_health_check(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """40. Verify health check reports HEALTHY, UNCONFIGURED, or UNHEALTHY without exposing secrets."""
    # 1. Healthy
    res = adapter.health_check()
    assert res.status == ProviderHealthStatus.HEALTHY
    assert res.provider_name == "aisstream"
    assert "secret" not in json.dumps(res.details).lower()

    # 2. Unconfigured
    unconf_adapter = AISStreamAdapter(secret=None, secret_resolver=SecretResolver())
    unconf_adapter.config.secret_ref = "env:MISSING_KEY_XYZ"
    res_unconf = unconf_adapter.health_check()
    assert res_unconf.status == ProviderHealthStatus.UNCONFIGURED


    # 3. Connection drop / Unhealthy
    mock_transport.simulate_connection_error = True
    res_unhealthy = adapter.health_check()
    assert res_unhealthy.status == ProviderHealthStatus.UNHEALTHY


def test_41_observability_metadata(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport, sample_position_report: dict[str, Any]) -> None:
    """41. Verify observability metadata captured in RawEvent and IngestionBatch."""
    adapter.connect()
    mock_transport.queue_message(sample_position_report)
    batch = adapter.receive_batch(max_messages=1)

    assert batch.metadata["received_count"] == 1
    assert "duration_ms" in batch.metadata
    assert batch.source_metadata["endpoint"] == DEFAULT_AISSTREAM_URL
    assert batch.events[0].metadata["source_protocol"] == "websocket"


def test_42_tenant_org_isolation(sample_position_report: dict[str, Any]) -> None:
    """42. Verify tenant isolation in raw events, canonical events, and idempotency fingerprints."""
    fp_a = AISStreamAdapter.compute_fingerprint(sample_position_report, org_id="tenant-a")
    fp_b = AISStreamAdapter.compute_fingerprint(sample_position_report, org_id="tenant-b")
    assert fp_a != fp_b, "Events from different tenants must yield distinct fingerprints."

    raw = RawEvent(provider_name="aisstream", raw_payload=sample_position_report, org_id="tenant-a")
    canonical = AISStreamNormalizer().normalize(raw)
    assert canonical.org_id == "tenant-a"


def test_43_graceful_shutdown(adapter: AISStreamAdapter, mock_transport: MockAISWebSocketTransport) -> None:
    """43. Verify graceful shutdown releases transport and resets subscription status."""
    adapter.connect()
    assert mock_transport.is_connected is True
    adapter.close()
    assert mock_transport.is_connected is False
    assert adapter._is_subscribed is False


def test_44_unsupported_message_handling(normalizer: AISStreamNormalizer) -> None:
    """44. Verify unsupported AIS message type is parsed as CUSTOM without failure."""
    unsupported_payload = {
        "MessageType": "StandardSearchAndRescueAircraftReport",
        "MetaData": {
            "MMSI": 111222333,
            "ShipName": "RESCUE HELO 01",
            "latitude": 52.1,
            "longitude": 4.2,
            "time_utc": "2026-09-08 00:00:00.000000 +0000 UTC",
        },
        "Message": {
            "StandardSearchAndRescueAircraftReport": {
                "Altitude": 150,
                "Sog": 110.0,
            }
        },
    }
    raw = RawEvent(provider_name="aisstream", raw_payload=unsupported_payload)
    canonical = normalizer.normalize(raw)

    assert canonical.event_type == CanonicalEventType.CUSTOM
    assert canonical.normalized_attributes.get("event_classification") == "AIS_STANDARDSEARCHANDRESCUEAIRCRAFTREPORT"
    assert canonical.quality == EventQuality.VALID
    assert canonical.severity == EventSeverity.INFO
