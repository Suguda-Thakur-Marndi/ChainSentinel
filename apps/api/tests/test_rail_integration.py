"""Comprehensive unit test suite for RiskWise 2.0 Phase 5 Step 7: Rail Data Integration.

All tests are 100% self-contained and execute against mocked HTTP endpoints (zero live network calls).

Covers all 45+ requirements:
 1. RailAdapter initialization
 2. Provider capability inspection
 3. Configuration loading and validation
 4. Feed URL resolution (defaults)
 5. Feed URL resolution (custom operator)
 6. Feed URL resolution (custom override)
 7. API key resolution (direct secret)
 8. API key resolution (environment fallback)
 9. Unauthenticated feed support
10. Feed successfully fetched
11. Protobuf parsing (TripUpdate)
12. Protobuf parsing (VehiclePosition)
13. Protobuf parsing (Alert)
14. Invalid protobuf handling
15. Empty feed handling
16. Feed timestamp parsing
17. Entity ID preservation
18. TripUpdate arrival and departure delays
19. TripUpdate cancellation
20. TripUpdate significant delay
21. TripUpdate moderate and minor delay
22. VehiclePosition coordinates validation
23. VehiclePosition invalid latitude
24. VehiclePosition invalid longitude
25. VehiclePosition missing coordinates
26. Route, trip, vehicle, and stop IDs mapping
27. Missing optional fields
28. Deleted entity skipped
29. Alert effect mapping (NO_SERVICE)
30. Alert effect mapping (SIGNIFICANT_DELAYS)
31. Alert effect mapping (REDUCED_SERVICE)
32. Alert effect mapping (STOP_MOVED)
33. Alert effect mapping (ADDITIONAL_SERVICE)
34. Deterministic idempotency fingerprinting
35. Consecutive vehicle positions preservation
36. Duplicate event suppression
37. Entity correlation (no false shipment correlation)
38. Entity correlation (explicit shipment preserved)
39. ShipmentEventBridge behavior
40. Source metadata and source_type
41. Passenger vs freight limitation notice
42. Raw and canonical separation
43. Retry behavior (transient 5xx)
44. HTTP 429 rate limit handling
45. HTTP 401/403 authentication error handling
46. Timeout handling
47. Connection error handling
48. Health check (HEALTHY)
49. Health check (UNCONFIGURED)
50. Health check (invalid protobuf)
51. Health check (auth rejected)
52. Health check (rate limited)
53. Health check (server error)
54. Health check (timeout)
55. Logging and credential redaction
56. Registry integration
57. Polling job creation helper
58. Tenant/org isolation
59. Full pipeline integration (IngestionService -> Adapter -> Normalizer -> Storage)
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from google.transit import gtfs_realtime_pb2
import httpx
import pytest

from app.integrations import (
    AuthMode,
    BaseEventNormalizer,
    CanonicalEventType,
    CanonicalExternalEvent,
    CoordinateValidator,
    DEFAULT_TFNSW_ALERTS_URL,
    DEFAULT_TFNSW_BASE_URL,
    DEFAULT_TFNSW_TRIP_UPDATES_URL,
    DEFAULT_TFNSW_VEHICLE_POSITIONS_URL,
    DELAY_MAJOR_THRESHOLD_SECONDS,
    DELAY_MEDIUM_THRESHOLD_SECONDS,
    DELAY_MINOR_THRESHOLD_SECONDS,
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
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderType,
    RailAdapter,
    RailFeedConfig,
    RailFeedType,
    RailNormalizer,
    RateLimitConfig,
    RawEvent,
    RetryConfig,
    ScheduledIngestionJob,
    SecretResolver,
    ShipmentEventBridge,
    TimestampNormalizer,
    create_rail_polling_job,
    default_provider_registry,
)


# =====================================================================
# Protobuf Feed Builders for Tests
# =====================================================================

def build_trip_update_protobuf(
    entity_id: str = "ent_tu_1",
    trip_id: str = "TRIP_101",
    route_id: str = "T1",
    vehicle_id: str = "V_9001",
    delay_seconds: int = 950,
    stop_id: str = "STATION_CENTRAL",
    sched_rel: int = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.SCHEDULED,
    header_timestamp: int = 1725800000,
    entity_timestamp: Optional[int] = 1725800000,
    is_deleted: bool = False,
) -> bytes:
    """Build a GTFS-Realtime binary protobuf FeedMessage containing a TripUpdate."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = header_timestamp

    entity = feed.entity.add()
    entity.id = entity_id
    entity.is_deleted = is_deleted

    tu = entity.trip_update
    tu.trip.trip_id = trip_id
    tu.trip.route_id = route_id
    tu.trip.schedule_relationship = sched_rel
    tu.trip.start_time = "08:30:00"
    tu.trip.start_date = "20260908"

    if vehicle_id:
        tu.vehicle.id = vehicle_id

    if entity_timestamp is not None:
        tu.timestamp = entity_timestamp

    stu = tu.stop_time_update.add()
    stu.stop_sequence = 1
    stu.stop_id = stop_id
    stu.arrival.delay = delay_seconds
    stu.departure.delay = delay_seconds

    return feed.SerializeToString()


def build_vehicle_position_protobuf(
    entity_id: str = "ent_vp_1",
    vehicle_id: str = "V_7002",
    trip_id: str = "TRIP_202",
    route_id: str = "T2",
    latitude: float = -33.8688,
    longitude: float = 151.2093,
    bearing: float = 180.0,
    speed_mps: float = 22.5,
    stop_id: str = "STATION_WYNYARD",
    current_status: int = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.IN_TRANSIT_TO,
    header_timestamp: int = 1725800000,
    entity_timestamp: Optional[int] = 1725800005,
    is_deleted: bool = False,
) -> bytes:
    """Build a GTFS-Realtime binary protobuf FeedMessage containing a VehiclePosition."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = header_timestamp

    entity = feed.entity.add()
    entity.id = entity_id
    entity.is_deleted = is_deleted

    vp = entity.vehicle
    if trip_id or route_id:
        if trip_id:
            vp.trip.trip_id = trip_id
        if route_id:
            vp.trip.route_id = route_id

    if vehicle_id:
        vp.vehicle.id = vehicle_id
        vp.vehicle.label = f"Waratah-{vehicle_id}"

    vp.position.latitude = latitude
    vp.position.longitude = longitude
    vp.position.bearing = bearing
    vp.position.speed = speed_mps

    vp.current_status = current_status
    if stop_id:
        vp.stop_id = stop_id
    vp.current_stop_sequence = 3

    if entity_timestamp is not None:
        vp.timestamp = entity_timestamp

    return feed.SerializeToString()


def build_alert_protobuf(
    entity_id: str = "ent_al_1",
    cause: int = gtfs_realtime_pb2.Alert.Cause.TECHNICAL_PROBLEM,
    effect: int = gtfs_realtime_pb2.Alert.Effect.SIGNIFICANT_DELAYS,
    header_text: str = "Signals failure at Central",
    desc_text: str = "Major delays expected across T1, T2 and T9 lines due to signal equipment failure.",
    route_id: str = "T1",
    stop_id: str = "STATION_CENTRAL",
    header_timestamp: int = 1725800000,
    start_ts: int = 1725799000,
    end_ts: int = 1725805000,
    is_deleted: bool = False,
) -> bytes:
    """Build a GTFS-Realtime binary protobuf FeedMessage containing a Service Alert."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = header_timestamp

    entity = feed.entity.add()
    entity.id = entity_id
    entity.is_deleted = is_deleted

    al = entity.alert
    al.cause = cause
    al.effect = effect

    h_trans = al.header_text.translation.add()
    h_trans.text = header_text
    h_trans.language = "en"

    d_trans = al.description_text.translation.add()
    d_trans.text = desc_text
    d_trans.language = "en"

    ap = al.active_period.add()
    ap.start = start_ts
    ap.end = end_ts

    ie = al.informed_entity.add()
    if route_id:
        ie.route_id = route_id
    if stop_id:
        ie.stop_id = stop_id

    return feed.SerializeToString()


def build_empty_protobuf_feed(header_timestamp: int = 1725800000) -> bytes:
    """Build a GTFS-Realtime FeedMessage with 0 entities."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = header_timestamp
    return feed.SerializeToString()


def make_mock_rail_client(
    feed_bytes: Optional[bytes] = None,
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
    custom_handler: Optional[Callable[[httpx.Request], httpx.Response]] = None,
) -> httpx.Client:
    """Create an isolated in-memory HTTP client with mock transport returning protobuf."""
    default_payload = feed_bytes if feed_bytes is not None else build_trip_update_protobuf()

    def default_handler(request: httpx.Request) -> httpx.Response:
        if custom_handler is not None:
            return custom_handler(request)

        resp_headers = dict(headers or {})
        if "Content-Type" not in resp_headers:
            resp_headers["Content-Type"] = "application/x-google-protobuf"

        return httpx.Response(
            status_code=status_code,
            content=default_payload,
            headers=resp_headers,
            request=request,
        )

    transport = httpx.MockTransport(default_handler)
    return httpx.Client(transport=transport)


# =====================================================================
# Unit Tests (59 Focused Test Cases)
# =====================================================================

def test_rail_adapter_initialization() -> None:
    """1. Test RailAdapter default initialization, capabilities, and provider metadata."""
    adapter = RailAdapter()
    assert adapter.provider_name == "rail"
    assert adapter.provider_type == ProviderType.RAIL
    assert adapter.capabilities.supports_polling is True
    assert adapter.capabilities.supports_batch is True
    assert adapter.capabilities.supports_health_check is True
    assert adapter.capabilities.supports_webhook is False
    assert adapter.capabilities.supports_streaming is False
    assert adapter.config.auth_mode == AuthMode.API_KEY_HEADER
    assert adapter.config.base_url == DEFAULT_TFNSW_TRIP_UPDATES_URL
    adapter.close()


def test_rail_adapter_capabilities() -> None:
    """2. Test RailAdapter capabilities enumeration."""
    adapter = RailAdapter()
    caps = adapter.capabilities
    assert "train" in caps.supported_entities
    assert "station" in caps.supported_entities
    assert "gtfs_realtime" in caps.supported_modalities
    assert caps.max_batch_size == 1000
    adapter.close()


def test_rail_configuration_validation() -> None:
    """3. Test custom ProviderConfig loading and validation."""
    custom_config = ProviderConfig(
        provider_name="rail",
        provider_type=ProviderType.RAIL,
        base_url="https://custom.rail.feed.gov.au/v2/gtfs",
        auth_mode=AuthMode.NONE,
        rate_limit=RateLimitConfig(requests_per_minute=120),
        retry=RetryConfig(max_retries=5, initial_delay_seconds=1.0),
        extra_settings={"operator": "nswtrains"},
    )
    adapter = RailAdapter(config=custom_config)
    assert adapter.config.rate_limit.requests_per_minute == 120
    assert adapter.config.retry.max_retries == 5
    assert adapter.config.extra_settings["operator"] == "nswtrains"
    adapter.close()


def test_rail_feed_url_resolution_defaults() -> None:
    """4. Test default TfNSW feed URL resolution for all supported feed types."""
    adapter = RailAdapter()
    tu_url = adapter.get_feed_url(RailFeedType.TRIP_UPDATES, operator="sydneytrains")
    vp_url = adapter.get_feed_url(RailFeedType.VEHICLE_POSITIONS, operator="sydneytrains")
    al_url = adapter.get_feed_url(RailFeedType.ALERTS, operator="sydneytrains")

    assert tu_url == "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains"
    assert vp_url == "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/sydneytrains"
    assert al_url == "https://api.transport.nsw.gov.au/v2/gtfs/alerts/sydneytrains"
    adapter.close()


def test_rail_feed_url_resolution_custom_operator() -> None:
    """5. Test feed URL resolution for NSW Trains regional operator."""
    adapter = RailAdapter()
    tu_url = adapter.get_feed_url(RailFeedType.TRIP_UPDATES, operator="nswtrains")
    vp_url = adapter.get_feed_url(RailFeedType.VEHICLE_POSITIONS, operator="nswtrains")
    al_url = adapter.get_feed_url(RailFeedType.ALERTS, operator="nswtrains")

    assert tu_url == "https://api.transport.nsw.gov.au/v2/gtfs/realtime/nswtrains"
    assert vp_url == "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/nswtrains"
    assert al_url == "https://api.transport.nsw.gov.au/v2/gtfs/alerts/nswtrains"
    adapter.close()


def test_rail_feed_url_resolution_custom_override() -> None:
    """6. Test custom URL override via extra_settings."""
    cfg = ProviderConfig(
        provider_name="rail",
        provider_type=ProviderType.RAIL,
        extra_settings={
            "trip_updates_url": "https://mirror.transport.gov/tu",
            "endpoint_url": "https://mirror.transport.gov/general",
        },
    )
    adapter = RailAdapter(config=cfg)
    assert adapter.get_feed_url(RailFeedType.TRIP_UPDATES) == "https://mirror.transport.gov/tu"
    assert adapter.get_feed_url(RailFeedType.ALERTS) == "https://mirror.transport.gov/general"
    adapter.close()


def test_rail_api_key_resolution_direct_secret() -> None:
    """7. Test API key resolution when directly supplied as secret parameter."""
    adapter = RailAdapter(secret="direct_tfnsw_key_abc123")
    assert adapter.resolve_api_key() == "direct_tfnsw_key_abc123"
    adapter.close()


def test_rail_api_key_resolution_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """8. Test API key resolution from environment variables (TFNSW_API_KEY)."""
    monkeypatch.setenv("TFNSW_API_KEY", "env_tfnsw_secret_987")
    adapter = RailAdapter()
    assert adapter.resolve_api_key() == "env_tfnsw_secret_987"
    adapter.close()


def test_rail_unauthenticated_feed_support() -> None:
    """9. Test unauthenticated feed support when no key is configured."""
    resolver = SecretResolver()
    adapter = RailAdapter(secret=None, secret_resolver=resolver)
    assert adapter.resolve_api_key() is None

    # When fetching, no Authorization header is sent
    captured_headers: Dict[str, str] = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(
            status_code=200,
            content=build_trip_update_protobuf(),
            headers={"Content-Type": "application/x-google-protobuf"},
            request=request,
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(capture_handler))
    adapter._external_client = mock_client

    batch = adapter.fetch(feed_type=RailFeedType.TRIP_UPDATES)
    assert "authorization" not in captured_headers
    assert len(batch.events) == 1
    adapter.close()


def test_rail_feed_successfully_fetched() -> None:
    """10. Test successful GTFS-Realtime feed fetch returning an IngestionBatch."""
    pb_data = build_trip_update_protobuf(entity_id="test_entity_1")
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch(feed_type=RailFeedType.TRIP_UPDATES)
    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "rail"
    assert len(batch.events) == 1
    assert batch.events[0].provider_name == "rail"
    assert batch.events[0].provider_type == ProviderType.RAIL
    assert batch.source_metadata["feed_type"] == "trip_updates"
    adapter.close()


def test_rail_protobuf_parsing_trip_updates() -> None:
    """11. Test detailed TripUpdate protobuf deserialization."""
    pb_data = build_trip_update_protobuf(
        entity_id="tu_42",
        trip_id="TRIP_EAST_42",
        route_id="T4",
        vehicle_id="V_WARATAH_42",
        delay_seconds=480,
        stop_id="STATION_BONDI",
    )
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch(feed_type=RailFeedType.TRIP_UPDATES)
    raw_payload = batch.events[0].raw_payload
    assert raw_payload["entity_type"] == "TripUpdate"
    assert raw_payload["entity_id"] == "tu_42"
    assert raw_payload["trip_id"] == "TRIP_EAST_42"
    assert raw_payload["route_id"] == "T4"
    assert raw_payload["vehicle_id"] == "V_WARATAH_42"
    assert raw_payload["delay_seconds"] == 480
    assert raw_payload["stop_id"] == "STATION_BONDI"
    assert len(raw_payload["stop_time_updates"]) == 1
    adapter.close()


def test_rail_protobuf_parsing_vehicle_positions() -> None:
    """12. Test detailed VehiclePosition protobuf deserialization."""
    pb_data = build_vehicle_position_protobuf(
        entity_id="vp_88",
        vehicle_id="V_MILLENNIUM_88",
        trip_id="TRIP_NORTH_88",
        route_id="T1",
        latitude=-33.7961,
        longitude=151.1780,
        bearing=315.0,
        speed_mps=18.2,
        stop_id="STATION_CHATSWOOD",
    )
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch(feed_type=RailFeedType.VEHICLE_POSITIONS)
    raw_payload = batch.events[0].raw_payload
    assert raw_payload["entity_type"] == "VehiclePosition"
    assert raw_payload["entity_id"] == "vp_88"
    assert raw_payload["vehicle_id"] == "V_MILLENNIUM_88"
    assert raw_payload["latitude"] == pytest.approx(-33.7961, rel=1e-4)
    assert raw_payload["longitude"] == pytest.approx(151.1780, rel=1e-4)
    assert raw_payload["bearing"] == pytest.approx(315.0, rel=1e-4)
    assert raw_payload["speed_mps"] == pytest.approx(18.2, rel=1e-4)
    assert raw_payload["stop_id"] == "STATION_CHATSWOOD"
    assert raw_payload["current_status"] == "IN_TRANSIT_TO"
    adapter.close()


def test_rail_protobuf_parsing_alerts() -> None:
    """13. Test detailed Alert protobuf deserialization."""
    pb_data = build_alert_protobuf(
        entity_id="al_99",
        cause=gtfs_realtime_pb2.Alert.Cause.WEATHER,
        effect=gtfs_realtime_pb2.Alert.Effect.NO_SERVICE,
        header_text="Severe flooding on South Coast Line",
        desc_text="All train services between Wollongong and Kiama are suspended due to severe weather.",
        route_id="SCO",
        stop_id="STATION_WOLLONGONG",
    )
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch(feed_type=RailFeedType.ALERTS)
    raw_payload = batch.events[0].raw_payload
    assert raw_payload["entity_type"] == "Alert"
    assert raw_payload["entity_id"] == "al_99"
    assert raw_payload["cause"] == "WEATHER"
    assert raw_payload["effect"] == "NO_SERVICE"
    assert raw_payload["header_text"] == "Severe flooding on South Coast Line"
    assert "All train services" in raw_payload["description_text"]
    assert raw_payload["route_id"] == "SCO"
    assert raw_payload["stop_id"] == "STATION_WOLLONGONG"
    adapter.close()


def test_rail_invalid_protobuf_handling() -> None:
    """14. Test handling of malformed or invalid binary protobuf payload."""
    malformed_bytes = b"NOT_A_VALID_PROTOBUF_BINARY_STRING_12345"
    client = make_mock_rail_client(feed_bytes=malformed_bytes)
    adapter = RailAdapter(http_client=client)

    # In google-protobuf, parsing garbage can either raise DecodeError or result in garbled fields.
    # If bytes violate protobuf wire format, DecodeError -> ProviderResponseError.
    # We test invalid varint wire type bytes:
    invalid_wire = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x01])
    client_invalid = make_mock_rail_client(feed_bytes=invalid_wire)
    adapter_invalid = RailAdapter(http_client=client_invalid)

    with pytest.raises(ProviderResponseError) as exc_info:
        adapter_invalid.fetch()
    assert "decode GTFS-Realtime" in str(exc_info.value)
    adapter.close()
    adapter_invalid.close()


def test_rail_empty_feed_handling() -> None:
    """15. Test handling of a valid GTFS-Realtime feed with 0 entities."""
    empty_pb = build_empty_protobuf_feed(header_timestamp=1725800000)
    client = make_mock_rail_client(feed_bytes=empty_pb)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch()
    assert isinstance(batch, IngestionBatch)
    assert len(batch.events) == 0
    assert batch.source_metadata["header_timestamp"] == 1725800000
    adapter.close()


def test_rail_feed_timestamp_parsing() -> None:
    """16. Test extraction and propagation of GTFS-Realtime feed header timestamp."""
    pb_data = build_trip_update_protobuf(header_timestamp=1725812345)
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch()
    assert batch.source_metadata["header_timestamp"] == 1725812345
    assert batch.events[0].raw_payload["feed_header_timestamp"] == 1725812345
    adapter.close()


def test_rail_entity_id_preservation() -> None:
    """17. Test preservation of provider entity ID in raw event and provider_event_id."""
    pb_data = build_trip_update_protobuf(entity_id="entity_sydney_999")
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch()
    event = batch.events[0]
    assert event.raw_payload["entity_id"] == "entity_sydney_999"
    assert "entity_sydney_999" in event.provider_event_id
    adapter.close()


def test_rail_trip_update_arrival_and_departure_delays() -> None:
    """18. Test arrival and departure delay extraction from stop_time_update."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add()
    entity.id = "tu_stops"
    tu = entity.trip_update
    tu.trip.trip_id = "T_DELAY_1"

    # Stop 1: 120s delay
    s1 = tu.stop_time_update.add()
    s1.stop_sequence = 1
    s1.stop_id = "STOP_A"
    s1.arrival.delay = 120
    s1.departure.delay = 140

    # Stop 2: 360s delay
    s2 = tu.stop_time_update.add()
    s2.stop_sequence = 2
    s2.stop_id = "STOP_B"
    s2.arrival.delay = 360
    s2.departure.delay = 360

    client = make_mock_rail_client(feed_bytes=feed.SerializeToString())
    adapter = RailAdapter(http_client=client)

    batch = adapter.fetch()
    p = batch.events[0].raw_payload
    assert p["delay_seconds"] == 120  # primary stop delay
    assert p["max_delay_seconds"] == 360  # max stop delay
    assert len(p["stop_time_updates"]) == 2
    adapter.close()


def test_rail_trip_update_cancellation() -> None:
    """19. Test TripUpdate cancellation normalization (schedule_relationship = CANCELED)."""
    pb_data = build_trip_update_protobuf(
        sched_rel=gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.CANCELED
    )
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)
    batch = adapter.fetch()

    normalizer = RailNormalizer()
    canonical = normalizer.normalize(batch.events[0])

    assert canonical.event_type == CanonicalEventType.RAIL_DISRUPTION
    assert canonical.severity == EventSeverity.CRITICAL
    assert canonical.status == "CANCELED"
    adapter.close()


def test_rail_trip_update_significant_delay() -> None:
    """20. Test conservative delay classification: major delay >= 1800s (CRITICAL) and >= 900s (HIGH)."""
    normalizer = RailNormalizer()

    # Major delay >= 1800 seconds (30 minutes) -> CRITICAL
    pb_major = build_trip_update_protobuf(delay_seconds=2000)
    adapter_major = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_major))
    batch_major = adapter_major.fetch()
    c_major = normalizer.normalize(batch_major.events[0])
    assert c_major.event_type == CanonicalEventType.RAIL_DISRUPTION
    assert c_major.severity == EventSeverity.CRITICAL
    assert c_major.delay_minutes == round(2000 / 60.0, 1)

    # Significant delay >= 900 seconds (15 minutes) -> HIGH
    pb_sig = build_trip_update_protobuf(delay_seconds=1200)
    adapter_sig = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_sig))
    batch_sig = adapter_sig.fetch()
    c_sig = normalizer.normalize(batch_sig.events[0])
    assert c_sig.event_type == CanonicalEventType.TRAIN_DELAY
    assert c_sig.severity == EventSeverity.HIGH
    assert c_sig.delay_minutes == 20.0

    adapter_major.close()
    adapter_sig.close()


def test_rail_trip_update_moderate_and_minor_delay() -> None:
    """21. Test moderate delay >= 300s (MEDIUM), minor delay > 60s (LOW), on-time <= 60s (INFO)."""
    normalizer = RailNormalizer()

    # Moderate delay >= 300s (5 minutes) -> MEDIUM
    pb_mod = build_trip_update_protobuf(delay_seconds=420)
    adapter_mod = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_mod))
    c_mod = normalizer.normalize(adapter_mod.fetch().events[0])
    assert c_mod.event_type == CanonicalEventType.TRAIN_DELAY
    assert c_mod.severity == EventSeverity.MEDIUM

    # Minor delay > 60s -> LOW
    pb_min = build_trip_update_protobuf(delay_seconds=180)
    adapter_min = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_min))
    c_min = normalizer.normalize(adapter_min.fetch().events[0])
    assert c_min.event_type == CanonicalEventType.TRAIN_DELAY
    assert c_min.severity == EventSeverity.LOW

    # On time <= 60s -> INFO
    pb_ontime = build_trip_update_protobuf(delay_seconds=30)
    adapter_ontime = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_ontime))
    c_ontime = normalizer.normalize(adapter_ontime.fetch().events[0])
    assert c_ontime.event_type == CanonicalEventType.TRAIN_DELAY
    assert c_ontime.severity == EventSeverity.INFO
    assert c_ontime.status == "ON_TIME"

    adapter_mod.close()
    adapter_min.close()
    adapter_ontime.close()


def test_rail_vehicle_position_coordinates_validation() -> None:
    """22. Test valid vehicle position coordinates normalization into EventLocation."""
    pb_data = build_vehicle_position_protobuf(
        latitude=-33.8688,
        longitude=151.2093,
        vehicle_id="V_55",
        route_id="T3",
    )
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)
    batch = adapter.fetch(feed_type=RailFeedType.VEHICLE_POSITIONS)

    normalizer = RailNormalizer()
    canonical = normalizer.normalize(batch.events[0])

    assert canonical.event_type == CanonicalEventType.LOCATION_UPDATE
    assert canonical.location is not None
    assert canonical.location.latitude == pytest.approx(-33.8688, rel=1e-4)
    assert canonical.location.longitude == pytest.approx(151.2093, rel=1e-4)
    assert canonical.location.country_code == "AU"
    assert "Train V_55" in canonical.location.location_name
    assert canonical.quality == EventQuality.VALID
    adapter.close()


def test_rail_vehicle_position_invalid_latitude() -> None:
    """23. Test handling of invalid latitude (> 90.0) resulting in PARTIAL quality."""
    pb_data = build_vehicle_position_protobuf(latitude=99.9, longitude=151.2)
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)
    batch = adapter.fetch(feed_type=RailFeedType.VEHICLE_POSITIONS)

    normalizer = RailNormalizer()
    canonical = normalizer.normalize(batch.events[0])

    assert canonical.quality == EventQuality.PARTIAL
    assert canonical.location is None
    assert any("Coordinate validation" in err for err in canonical.validation_errors)
    adapter.close()


def test_rail_vehicle_position_invalid_longitude() -> None:
    """24. Test handling of invalid longitude (> 180.0) resulting in PARTIAL quality."""
    pb_data = build_vehicle_position_protobuf(latitude=-33.8, longitude=195.0)
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=client)
    batch = adapter.fetch(feed_type=RailFeedType.VEHICLE_POSITIONS)

    normalizer = RailNormalizer()
    canonical = normalizer.normalize(batch.events[0])

    assert canonical.quality == EventQuality.PARTIAL
    assert canonical.location is None
    assert len(canonical.validation_errors) > 0
    adapter.close()


def test_rail_vehicle_position_missing_coordinates() -> None:
    """25. Test vehicle position without coordinates creates PARTIAL quality event."""
    raw_event = RawEvent(
        provider_name="rail",
        provider_type=ProviderType.RAIL,
        provider_event_id="rail:test:missing_coords",
        fingerprint="fp_missing_coords",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "entity_type": "VehiclePosition",
            "entity_id": "vp_no_coords",
            "latitude": None,
            "longitude": None,
            "current_status": "STOPPED_AT",
        },
    )
    normalizer = RailNormalizer()
    canonical = normalizer.normalize(raw_event)
    assert canonical.quality == EventQuality.PARTIAL
    assert canonical.location is None


def test_rail_route_and_trip_and_vehicle_and_stop_ids() -> None:
    """26. Test route_id, trip_id, vehicle_id, and stop_id preservation in EntityCorrelation."""
    pb_data = build_trip_update_protobuf(
        trip_id="TRIP_WEST_77",
        route_id="BMT",
        vehicle_id="V_OSCAR_77",
        stop_id="STATION_PENRITH",
    )
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch()

    normalizer = RailNormalizer()
    canonical = normalizer.normalize(batch.events[0])

    assert canonical.correlation.route_id == "BMT"
    assert canonical.correlation.custom_identifiers["trip_id"] == "TRIP_WEST_77"
    assert canonical.correlation.custom_identifiers["vehicle_id"] == "V_OSCAR_77"
    assert canonical.correlation.custom_identifiers["stop_id"] == "STATION_PENRITH"
    adapter.close()


def test_rail_missing_optional_fields() -> None:
    """27. Test entity without vehicle ID or stop ID parses safely."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add()
    entity.id = "tu_minimal"
    tu = entity.trip_update
    tu.trip.trip_id = "TRIP_MINIMAL"
    # No vehicle ID, no stop time updates

    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=feed.SerializeToString()))
    batch = adapter.fetch()
    assert len(batch.events) == 1
    raw = batch.events[0].raw_payload
    assert raw["vehicle_id"] is None
    assert raw["stop_id"] is None

    normalizer = RailNormalizer()
    canonical = normalizer.normalize(batch.events[0])
    assert canonical.correlation.route_id is None
    assert canonical.correlation.custom_identifiers["trip_id"] == "TRIP_MINIMAL"
    adapter.close()


def test_rail_deleted_entity_skipped() -> None:
    """28. Test that entities marked is_deleted = True are ignored during ingestion."""
    pb_data = build_trip_update_protobuf(entity_id="deleted_entity_1", is_deleted=True)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch()
    assert len(batch.events) == 0
    adapter.close()


def test_rail_alert_effect_mapping_no_service() -> None:
    """29. Test Alert NO_SERVICE maps to RAIL_DISRUPTION + CRITICAL."""
    pb_data = build_alert_protobuf(effect=gtfs_realtime_pb2.Alert.Effect.NO_SERVICE)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(feed_type=RailFeedType.ALERTS)

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.event_type == CanonicalEventType.RAIL_DISRUPTION
    assert canonical.severity == EventSeverity.CRITICAL
    adapter.close()


def test_rail_alert_effect_mapping_significant_delays() -> None:
    """30. Test Alert SIGNIFICANT_DELAYS maps to TRAIN_DELAY + HIGH."""
    pb_data = build_alert_protobuf(effect=gtfs_realtime_pb2.Alert.Effect.SIGNIFICANT_DELAYS)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(feed_type=RailFeedType.ALERTS)

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.event_type == CanonicalEventType.TRAIN_DELAY
    assert canonical.severity == EventSeverity.HIGH
    adapter.close()


def test_rail_alert_effect_mapping_reduced_service() -> None:
    """31. Test Alert REDUCED_SERVICE maps to RAIL_DISRUPTION + MEDIUM."""
    pb_data = build_alert_protobuf(effect=gtfs_realtime_pb2.Alert.Effect.REDUCED_SERVICE)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(feed_type=RailFeedType.ALERTS)

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.event_type == CanonicalEventType.RAIL_DISRUPTION
    assert canonical.severity == EventSeverity.MEDIUM
    adapter.close()


def test_rail_alert_effect_mapping_stop_moved() -> None:
    """32. Test Alert STOP_MOVED maps to RAIL_DISRUPTION + LOW."""
    pb_data = build_alert_protobuf(effect=gtfs_realtime_pb2.Alert.Effect.STOP_MOVED)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(feed_type=RailFeedType.ALERTS)

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.event_type == CanonicalEventType.RAIL_DISRUPTION
    assert canonical.severity == EventSeverity.LOW
    adapter.close()


def test_rail_alert_effect_mapping_additional_service() -> None:
    """33. Test Alert ADDITIONAL_SERVICE maps to CUSTOM + INFO."""
    pb_data = build_alert_protobuf(effect=gtfs_realtime_pb2.Alert.Effect.ADDITIONAL_SERVICE)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(feed_type=RailFeedType.ALERTS)

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.event_type == CanonicalEventType.CUSTOM
    assert canonical.severity == EventSeverity.INFO
    adapter.close()


def test_rail_deterministic_idempotency_fingerprinting() -> None:
    """34. Test deterministic SHA-256 fingerprinting for duplicate detection."""
    payload_1 = {
        "entity_type": "VehiclePosition",
        "entity_id": "vp_1",
        "trip_id": "T1",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "timestamp": 1725800000,
        "current_status": "IN_TRANSIT_TO",
    }
    payload_2 = dict(payload_1)

    fp1 = RailAdapter.compute_fingerprint(payload_1)
    fp2 = RailAdapter.compute_fingerprint(payload_2)

    assert fp1 == fp2
    assert len(fp1) == 64


def test_rail_consecutive_vehicle_positions_preserved() -> None:
    """35. Test that legitimate consecutive position updates produce distinct fingerprints."""
    pos1 = {
        "entity_type": "VehiclePosition",
        "entity_id": "vp_1",
        "trip_id": "T1",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "timestamp": 1725800000,
    }
    # 10 seconds later, moved slightly
    pos2 = {
        "entity_type": "VehiclePosition",
        "entity_id": "vp_1",
        "trip_id": "T1",
        "latitude": -33.8710,
        "longitude": 151.2095,
        "timestamp": 1725800010,
    }

    fp1 = RailAdapter.compute_fingerprint(pos1)
    fp2 = RailAdapter.compute_fingerprint(pos2)
    assert fp1 != fp2


def test_rail_duplicate_event_suppression() -> None:
    """36. Test that IdempotencyEngine correctly suppresses duplicate fingerprints."""
    engine = IdempotencyEngine()
    payload = {
        "entity_type": "TripUpdate",
        "entity_id": "tu_idem",
        "trip_id": "T_IDEM",
        "delay_seconds": 120,
        "timestamp": 1725800000,
    }
    fp = RailAdapter.compute_fingerprint(payload)

    # First observation should be accepted
    is_new, _ = engine.check_and_record(fp)
    assert is_new is True
    # Second identical observation should be rejected as duplicate
    is_new2, _ = engine.check_and_record(fp)
    assert is_new2 is False


def test_rail_entity_correlation_no_false_shipment() -> None:
    """37. Test strict passenger rail isolation: shipment_id must be None by default."""
    pb_data = build_trip_update_protobuf(vehicle_id="V_9999", route_id="CCN")
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch()

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.correlation.shipment_id is None
    assert canonical.correlation.carrier_id is None
    assert canonical.correlation.route_id == "CCN"
    adapter.close()


def test_rail_entity_correlation_explicit_shipment_preserved() -> None:
    """38. Test that if shipment_id is explicitly injected into raw event, it is preserved."""
    raw_event = RawEvent(
        provider_name="rail",
        provider_type=ProviderType.RAIL,
        provider_event_id="rail:test:explicit_shipment",
        fingerprint="fp_shipment_1",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "entity_type": "TripUpdate",
            "entity_id": "tu_ship",
            "trip_id": "T_FREIGHT_INTERMODAL",
            "shipment_id": "SHP-RAIL-AU-001",
            "carrier_id": "PACIFIC_NATIONAL",
            "delay_seconds": 600,
        },
    )
    canonical = RailNormalizer().normalize(raw_event)
    assert canonical.correlation.shipment_id == "SHP-RAIL-AU-001"
    assert canonical.correlation.carrier_id == "PACIFIC_NATIONAL"


def test_rail_shipment_event_bridge_behavior() -> None:
    """39. Test ShipmentEventBridge behavior with and without correlated shipment_id."""
    normalizer = RailNormalizer()

    # Default rail event: no shipment correlation -> cannot persist to ShipmentEvent
    pb_data = build_trip_update_protobuf()
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    canonical_default = normalizer.normalize(adapter.fetch().events[0])

    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical_default) is False
    with pytest.raises(ValueError) as exc_info:
        ShipmentEventBridge.to_shipment_event_dict(canonical_default)
    assert "cannot be persisted" in str(exc_info.value)

    # Correlated rail event: can persist to ShipmentEvent
    correlated_event = CanonicalExternalEvent(
        provider="rail",
        source_event_id="rail:corr:1",
        event_type=CanonicalEventType.TRAIN_DELAY,
        event_timestamp=datetime.now(timezone.utc),
        correlation=EntityCorrelation(shipment_id="SHP-AU-RAIL-99"),
        severity=EventSeverity.HIGH,
        delay_minutes=25.0,
    )
    assert ShipmentEventBridge.can_persist_to_shipment_event(correlated_event) is True
    persisted_dict = ShipmentEventBridge.to_shipment_event_dict(correlated_event)
    assert persisted_dict["shipment_id"] == "SHP-AU-RAIL-99"
    adapter.close()


def test_rail_source_metadata_and_source_type() -> None:
    """40. Test that batch metadata and canonical events have REAL source_type."""
    pb_data = build_vehicle_position_protobuf()
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(feed_type=RailFeedType.VEHICLE_POSITIONS)

    assert batch.source_metadata["operator"] == "sydneytrains"
    assert batch.source_metadata["feed_type"] == "vehicle_positions"

    canonical = RailNormalizer().normalize(batch.events[0])
    assert canonical.source_type == EventSourceType.REAL
    adapter.close()


def test_rail_passenger_vs_freight_limitation_notice() -> None:
    """41. Test explicit passenger rail notice in normalized attributes."""
    pb_data = build_trip_update_protobuf()
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch()

    canonical = RailNormalizer().normalize(batch.events[0])
    attrs = canonical.normalized_attributes
    assert "passenger_rail_notice" in attrs
    assert "not a commercial freight shipment" in attrs["passenger_rail_notice"]
    assert attrs["mode"] == "RAIL"
    adapter.close()


def test_rail_raw_canonical_separation() -> None:
    """42. Test that raw protobuf fields are stored in raw_payload and not in canonical root."""
    pb_data = build_trip_update_protobuf(delay_seconds=300)
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch()
    raw = batch.events[0]

    canonical = RailNormalizer().normalize(raw)
    # Raw payload has full GTFS-RT dictionary
    assert "stop_time_updates" in raw.raw_payload
    # Canonical external event uses strict canonical fields
    assert not hasattr(canonical, "stop_time_updates")
    assert canonical.raw_event_id is not None or canonical.payload_fingerprint == raw.fingerprint
    adapter.close()


def test_rail_retry_behavior_transient_5xx() -> None:
    """43. Test retry policy handles transient HTTP 5xx errors."""
    attempts = 0

    def fail_twice_then_succeed(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(status_code=503, content=b"Gateway Unavailable", request=request)
        return httpx.Response(
            status_code=200,
            content=build_trip_update_protobuf(),
            headers={"Content-Type": "application/x-google-protobuf"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(fail_twice_then_succeed))
    cfg = ProviderConfig(
        provider_name="rail",
        provider_type=ProviderType.RAIL,
        retry=RetryConfig(max_retries=3, initial_delay_seconds=0.01),
    )
    adapter = RailAdapter(config=cfg, http_client=client)
    batch = adapter.fetch()

    assert attempts == 3
    assert len(batch.events) == 1
    adapter.close()


def test_rail_http_429_rate_limit_error() -> None:
    """44. Test HTTP 429 response raises ProviderRateLimitError with Retry-After header."""
    client = make_mock_rail_client(
        status_code=429,
        feed_bytes=b"Quota Exceeded",
        headers={"Retry-After": "45"},
    )
    adapter = RailAdapter(http_client=client)

    with pytest.raises(ProviderRateLimitError) as exc_info:
        adapter.fetch()
    assert exc_info.value.retry_after_seconds == 45.0
    adapter.close()


def test_rail_http_401_403_authentication_error() -> None:
    """45. Test HTTP 401/403 responses raise ProviderAuthenticationError."""
    for status in (401, 403):
        client = make_mock_rail_client(status_code=status, feed_bytes=b"Forbidden")
        adapter = RailAdapter(http_client=client)
        with pytest.raises(ProviderAuthenticationError) as exc_info:
            adapter.fetch()
        assert exc_info.value.status_code == status
        adapter.close()


def test_rail_timeout_handling() -> None:
    """46. Test client timeout raises ProviderTimeoutError."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out after 15s")

    client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    adapter = RailAdapter(http_client=client)

    with pytest.raises(ProviderTimeoutError) as exc_info:
        adapter.fetch()
    assert "timeout" in str(exc_info.value).lower()
    adapter.close()


def test_rail_connection_error_handling() -> None:
    """47. Test client network failure raises ProviderConnectionError."""
    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to resolve api.transport.nsw.gov.au")

    client = httpx.Client(transport=httpx.MockTransport(error_handler))
    cfg = ProviderConfig(
        provider_name="rail",
        provider_type=ProviderType.RAIL,
        retry=RetryConfig(max_retries=1, initial_delay_seconds=0.01),
    )
    adapter = RailAdapter(config=cfg, http_client=client)

    with pytest.raises(ProviderConnectionError) as exc_info:
        adapter.fetch()
    assert "network failure" in str(exc_info.value).lower()
    adapter.close()


def test_rail_health_check_healthy() -> None:
    """48. Test diagnostic health check returns HEALTHY on 200 with valid protobuf."""
    pb_data = build_alert_protobuf()
    client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.HEALTHY
    assert health.details["configured"] is True
    assert health.details["entity_count"] == 1
    adapter.close()


def test_rail_health_check_unconfigured() -> None:
    """49. Test diagnostic health check returns UNCONFIGURED when API key is missing."""
    resolver = SecretResolver()
    adapter = RailAdapter(secret=None, secret_resolver=resolver)
    health = adapter.health_check()

    assert health.status == ProviderHealthStatus.UNCONFIGURED
    assert health.details["error_category"] == "CONFIGURATION"
    adapter.close()


def test_rail_health_check_invalid_protobuf() -> None:
    """50. Test diagnostic health check returns UNHEALTHY when 200 body is invalid protobuf."""
    invalid_wire = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x01])
    client = make_mock_rail_client(feed_bytes=invalid_wire)
    adapter = RailAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.UNHEALTHY
    assert health.details["error_category"] == "RESPONSE"
    adapter.close()


def test_rail_health_check_auth_rejected() -> None:
    """51. Test diagnostic health check returns UNHEALTHY when probe receives 401/403."""
    client = make_mock_rail_client(status_code=401, feed_bytes=b"Unauthorized")
    adapter = RailAdapter(secret="bad_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.UNHEALTHY
    assert health.details["error_category"] == "AUTHENTICATION"
    adapter.close()


def test_rail_health_check_rate_limited() -> None:
    """52. Test diagnostic health check returns DEGRADED when probe receives 429."""
    client = make_mock_rail_client(status_code=429, feed_bytes=b"Too Many Requests")
    adapter = RailAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.DEGRADED
    assert health.details["error_category"] == "RATE_LIMIT"
    adapter.close()


def test_rail_health_check_server_error() -> None:
    """53. Test diagnostic health check returns UNHEALTHY when probe receives 500/503."""
    client = make_mock_rail_client(status_code=503, feed_bytes=b"Service Unavailable")
    adapter = RailAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.UNHEALTHY
    assert health.details["error_category"] == "UPSTREAM"
    adapter.close()


def test_rail_health_check_timeout() -> None:
    """54. Test diagnostic health check returns DEGRADED when probe times out."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Probe timeout")

    client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    adapter = RailAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.DEGRADED
    assert health.details["error_category"] == "TIMEOUT"
    adapter.close()


def test_rail_logging_and_credential_redaction() -> None:
    """55. Test secret redaction ensures API key is never exposed in logs or payloads."""
    secret = "secret_tfnsw_token_123456"
    sanitized = SecretResolver.sanitize_payload({
        "tfnsw_api_key": secret,
        "api_key": secret,
        "tfnsw_token": secret,
    })
    assert sanitized["tfnsw_api_key"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["tfnsw_token"] == "[REDACTED]"


def test_rail_registry_integration() -> None:
    """56. Test RailAdapter discovery and instantiation through default_provider_registry."""
    assert default_provider_registry.is_registered("rail")
    adapter_cls = default_provider_registry.get_adapter_cls("rail")
    assert adapter_cls is RailAdapter

    inst = default_provider_registry.create_adapter("rail")
    assert isinstance(inst, RailAdapter)


def test_rail_polling_job_creation() -> None:
    """57. Test create_rail_polling_job helper produces valid ScheduledIngestionJob."""
    job = create_rail_polling_job(
        job_id="rail_sydney_poll_job",
        cron_or_interval="interval:30",
        feed_type=RailFeedType.TRIP_UPDATES,
        operator="sydneytrains",
        organization_id="org_sydney_logistics",
    )
    assert isinstance(job, ScheduledIngestionJob)
    assert job.job_id == "rail_sydney_poll_job"
    assert job.provider_name == "rail"
    assert job.parameters["feed_type"] == "trip_updates"
    assert job.parameters["operator"] == "sydneytrains"
    assert job.organization_id == "org_sydney_logistics"


def test_rail_tenant_org_isolation() -> None:
    """58. Test tenant/org ID propagation in raw events and deterministic fingerprinting."""
    pb_data = build_trip_update_protobuf()
    adapter = RailAdapter(http_client=make_mock_rail_client(feed_bytes=pb_data))
    batch = adapter.fetch(org_id="org_enterprise_99")

    event = batch.events[0]
    assert event.org_id == "org_enterprise_99"

    canonical = RailNormalizer().normalize(event)
    assert canonical.org_id == "org_enterprise_99"
    adapter.close()


def test_rail_full_pipeline_integration() -> None:
    """59. Test end-to-end flow: IngestionService -> Adapter -> RawStorage -> Normalizer -> CanonicalStorage."""
    raw_storage = InMemoryRawEventStorage()
    canonical_storage = InMemoryCanonicalEventStorage()

    pb_data = build_trip_update_protobuf(
        entity_id="pipeline_tu_1",
        trip_id="T_SYD_CENTRAL",
        delay_seconds=450,
    )
    mock_client = make_mock_rail_client(feed_bytes=pb_data)
    adapter = RailAdapter(http_client=mock_client)

    # 1. Ingestion Step
    batch = adapter.fetch(feed_type=RailFeedType.TRIP_UPDATES)
    assert len(batch.events) == 1
    raw_event = batch.events[0]
    raw_storage.store_batch(batch)

    stored_raw = raw_storage.get_event(raw_event.id)
    assert stored_raw is not None

    # 2. Normalization Step
    normalizer = RailNormalizer()
    assert normalizer.can_normalize(stored_raw) is True

    canonical_event = normalizer.normalize(stored_raw)
    assert canonical_event.event_type == CanonicalEventType.TRAIN_DELAY
    assert canonical_event.severity == EventSeverity.MEDIUM

    # 3. Canonical Storage Step
    canonical_id = canonical_storage.store(canonical_event)
    assert canonical_id == canonical_event.event_id

    retrieved = canonical_storage.get_event(canonical_id)
    assert retrieved is not None
    assert retrieved.provider == "rail"
    assert retrieved.correlation.custom_identifiers["trip_id"] == "T_SYD_CENTRAL"

    adapter.close()
