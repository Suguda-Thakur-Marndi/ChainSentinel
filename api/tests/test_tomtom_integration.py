"""Unit tests for Phase 5 Step 4: TomTom Road / Traffic Data Integration.

Covers at least 40 focused unit tests using mocked HTTP responses (zero live network calls):
 1. Adapter initialization
 2. Provider capability inspection
 3. Configuration loading
 4. Missing API key handling
 5. Custom configuration overrides
 6. Successful traffic-flow request
 7. Successful traffic-incident request
 8. Coordinate validation
 9. Invalid latitude rejection
10. Invalid longitude rejection
11. UTC timestamp normalization
12. Traffic speed mapping
13. Free-flow speed mapping
14. Congestion-related mapping (ratio, travel time)
15. Road segment identity (frc)
16. Incident ID mapping
17. Incident type mapping (ROAD_INCIDENT, TRAFFIC_CONGESTION, ROAD_CLOSURE)
18. Incident severity mapping (magnitudeOfDelay -> EventSeverity)
19. Incident location mapping (GeoJSON [lon, lat] -> EventLocation(lat, lon))
20. Incident description mapping
21. Incident time mapping (startTime, endTime)
22. Closure mapping when supported (iconCategory 8 or roadClosure)
23. Missing optional fields robustness
24. Malformed provider response handling
25. Authentication failure (HTTP 401/403)
26. Rate limiting (HTTP 429 with Retry-After)
27. Transient 5xx failure (HTTP 502/503)
28. Bounded retry behavior via RetryPolicy
29. Retry-After delay handling
30. Deterministic idempotency fingerprinting
31. Duplicate observation deduplication
32. Canonical event generation
33. Raw payload preservation in RawEvent
34. Secret redaction from payload, URLs, and errors
35. Provider health check (HEALTHY, UNCONFIGURED, UNHEALTHY, DEGRADED)
36. Scheduler integration (ScheduledIngestionJob with InMemoryIngestionScheduler)
37. Observability metadata tracking
38. Tenant/org isolation
39. Normal traffic does not become critical risk
40. Severe incident severity mapping
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
import pytest

from app.integrations import (
    AuthMode,
    BaseEventNormalizer,
    CanonicalEventType,
    CanonicalExternalEvent,
    CoordinateValidator,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
    IdempotencyEngine,
    InMemoryIngestionScheduler,
    InMemoryRawEventStorage,
    IngestionBatch,
    IngestionMetadata,
    IngestionResult,
    IngestionService,
    IngestionStatus,
    NormalizationPipeline,
    ProviderAuthenticationError,
    ProviderCapabilities,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderType,
    ProviderValidationError,
    RateLimitConfig,
    RawEvent,
    RetryConfig,
    RetryPolicy,
    ScheduledIngestionJob,
    SecretResolver,
    TimestampNormalizer,
    TomTomAdapter,
    TomTomNormalizer,
    default_provider_registry,
)


# =====================================================================
# Mock Payloads & Client Helpers
# =====================================================================

SAMPLE_FLOW_DATA = {
    "flowSegmentData": {
        "frc": "FRC0",
        "currentSpeed": 85,
        "freeFlowSpeed": 110,
        "currentTravelTime": 142,
        "freeFlowTravelTime": 110,
        "confidence": 0.95,
        "roadClosure": False,
        "coordinates": {
            "coordinate": [
                {"latitude": 52.3731, "longitude": 4.8922},
                {"latitude": 52.3735, "longitude": 4.8928},
            ]
        },
    }
}

SAMPLE_NORMAL_FLOW = {
    "flowSegmentData": {
        "frc": "FRC0",
        "currentSpeed": 110,
        "freeFlowSpeed": 110,
        "currentTravelTime": 100,
        "freeFlowTravelTime": 100,
        "confidence": 0.98,
        "roadClosure": False,
    }
}

SAMPLE_HEAVY_CONGESTION_FLOW = {
    "flowSegmentData": {
        "frc": "FRC1",
        "currentSpeed": 20,
        "freeFlowSpeed": 100,
        "currentTravelTime": 900,
        "freeFlowTravelTime": 180,
        "confidence": 0.90,
        "roadClosure": False,
    }
}

SAMPLE_INCIDENTS_DATA = {
    "incidents": [
        {
            "type": "Feature",
            "id": "tt_inc_001",
            "geometry": {
                "type": "Point",
                "coordinates": [4.8922, 52.3731],
            },
            "properties": {
                "id": "tt_inc_001",
                "iconCategory": 1,  # Accident
                "magnitudeOfDelay": 2,  # Moderate
                "delay": 720,  # 12 minutes
                "length": 1200,
                "startTime": "2026-09-08T08:00:00Z",
                "endTime": "2026-09-08T10:00:00Z",
                "from": "Junction 3",
                "to": "Junction 4",
                "roadNumbers": ["A10"],
                "roadName": "Ring A10",
                "events": [
                    {
                        "code": 101,
                        "description": "accident involving multiple vehicles",
                        "iconCategory": 1,
                    }
                ],
            },
        },
        {
            "type": "Feature",
            "id": "tt_inc_002",
            "geometry": {
                "type": "Point",
                "coordinates": [4.9100, 52.3800],
            },
            "properties": {
                "id": "tt_inc_002",
                "iconCategory": 8,  # Road Closed
                "magnitudeOfDelay": 4,  # Indefinite
                "delay": 4200,  # 70 minutes
                "length": 3500,
                "startTime": "2026-09-08T07:30:00Z",
                "endTime": "2026-09-08T15:00:00Z",
                "from": "Exit 12",
                "to": "Exit 14",
                "roadNumbers": ["A2"],
                "roadName": "A2 Motorway",
                "events": [
                    {
                        "code": 401,
                        "description": "road closed due to emergency bridge repairs",
                        "iconCategory": 8,
                    }
                ],
            },
        },
    ]
}


def create_mock_client(
    status_code: int = 200,
    json_data: Any = None,
    headers: Optional[Dict[str, str]] = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(json_data).encode("utf-8") if json_data is not None else b""
        resp_headers = dict(headers or {})
        if "Content-Type" not in resp_headers:
            resp_headers["Content-Type"] = "application/json"
        return httpx.Response(status_code=status_code, content=content, headers=resp_headers, request=request)

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


# =====================================================================
# 40 Focused Unit Tests
# =====================================================================

def test_01_adapter_initialization():
    """1. Test adapter initialization, provider name, and type."""
    adapter = TomTomAdapter(secret="test_key_tomtom")
    assert adapter.provider_name == "tomtom"
    assert adapter.provider_type == ProviderType.ROAD_TRAFFIC


def test_02_provider_capability_inspection():
    """2. Test declared provider capabilities for TomTom."""
    adapter = TomTomAdapter(secret="test_key_tomtom")
    caps = adapter.capabilities
    assert caps.supports_polling is True
    assert caps.supports_webhook is False
    assert caps.supports_batch is True
    assert caps.supports_health_check is True
    assert "traffic" in caps.supported_modalities
    assert "road_traffic" in caps.supported_modalities
    assert "route" in caps.supported_entities


def test_03_configuration_loading():
    """3. Test configuration defaults and model validation."""
    adapter = TomTomAdapter()
    assert adapter.config.provider_name == "tomtom"
    assert adapter.config.rate_limit.requests_per_minute == 60
    assert adapter.config.retry.max_retries == 3


def test_04_missing_api_key(monkeypatch):
    """4. Test missing API key raises ProviderConfigurationError."""
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    cfg = ProviderConfig(
        provider_name="tomtom",
        provider_type=ProviderType.ROAD_TRAFFIC,
        secret_ref="env:NON_EXISTENT_KEY",
    )
    adapter = TomTomAdapter(config=cfg, secret=None)
    with pytest.raises(ProviderConfigurationError) as exc:
        adapter.resolve_api_key()
    assert "not configured" in str(exc.value).lower()


def test_05_custom_configuration():
    """5. Test custom configuration overrides."""
    custom_cfg = ProviderConfig(
        provider_name="tomtom",
        provider_type=ProviderType.ROAD_TRAFFIC,
        base_url="https://custom.tomtom.api",
        rate_limit=RateLimitConfig(requests_per_minute=120),
        retry=RetryConfig(max_retries=5, initial_delay_seconds=1.5),
    )
    adapter = TomTomAdapter(config=custom_cfg, secret="override_key")
    assert adapter.config.base_url == "https://custom.tomtom.api"
    assert adapter.config.rate_limit.requests_per_minute == 120
    assert adapter.resolve_api_key() == "override_key"


def test_06_successful_traffic_flow_request():
    """6. Test successful traffic flow segment data fetch."""
    client = create_mock_client(200, json_data=SAMPLE_FLOW_DATA)
    adapter = TomTomAdapter(secret="test_key", http_client=client)

    batch = adapter.fetch(latitude=52.3731, longitude=4.8922)
    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "tomtom"
    assert len(batch.events) == 1

    event = batch.events[0]
    assert event.provider_name == "tomtom"
    assert event.raw_payload["flowSegmentData"]["currentSpeed"] == 85
    assert event.metadata["operation"] == "flowSegmentData"


def test_07_successful_traffic_incident_request():
    """7. Test successful traffic incident details fetch using bounding box."""
    client = create_mock_client(200, json_data=SAMPLE_INCIDENTS_DATA)
    adapter = TomTomAdapter(secret="test_key", http_client=client)

    bbox = (4.8, 52.3, 5.0, 52.4)
    batch = adapter.fetch_incidents(bbox=bbox)
    assert isinstance(batch, IngestionBatch)
    assert len(batch.events) == 2
    assert batch.events[0].provider_event_id == "tt_inc_001"
    assert batch.events[1].provider_event_id == "tt_inc_002"


def test_08_coordinate_validation():
    """8. Test valid coordinates pass CoordinateValidator."""
    lat, lon = CoordinateValidator.validate(52.3731, 4.8922)
    assert lat == 52.3731
    assert lon == 4.8922


def test_09_invalid_latitude():
    """9. Test invalid latitude raises ProviderValidationError before network request."""
    mock_called = [False]

    def handler(req: httpx.Request) -> httpx.Response:
        mock_called[0] = True
        return httpx.Response(200, json=SAMPLE_FLOW_DATA, request=req)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TomTomAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderValidationError):
        adapter.fetch(latitude=95.0, longitude=4.8922)
    assert mock_called[0] is False, "HTTP call must not be issued for invalid coordinates"


def test_10_invalid_longitude():
    """10. Test invalid longitude raises ProviderValidationError before network request."""
    mock_called = [False]

    def handler(req: httpx.Request) -> httpx.Response:
        mock_called[0] = True
        return httpx.Response(200, json=SAMPLE_FLOW_DATA, request=req)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TomTomAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderValidationError):
        adapter.fetch(latitude=52.3731, longitude=-190.0)
    assert mock_called[0] is False, "HTTP call must not be issued for invalid coordinates"


def test_11_utc_timestamp_normalization():
    """11. Test that ISO incident timestamps are normalized to timezone-aware UTC."""
    ts_iso = "2026-09-08T08:00:00Z"
    dt = TimestampNormalizer.parse_to_utc(ts_iso)
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 8


def test_12_traffic_speed_mapping():
    """12. Test traffic current speed mapping in km/h."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_FLOW_DATA,
        metadata={"requested_lat": 52.3731, "requested_lon": 4.8922},
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.normalized_attributes["current_speed_kmh"] == 85.0


def test_13_free_flow_speed_mapping():
    """13. Test free-flow speed mapping in km/h."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_FLOW_DATA,
        metadata={"requested_lat": 52.3731, "requested_lon": 4.8922},
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.normalized_attributes["free_flow_speed_kmh"] == 110.0


def test_14_congestion_related_mapping():
    """14. Test congestion ratio, travel time, and delay minutes calculation."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_FLOW_DATA,
        metadata={"requested_lat": 52.3731, "requested_lon": 4.8922},
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    attrs = canon.normalized_attributes
    assert attrs["current_travel_time_sec"] == 142.0
    assert attrs["free_flow_travel_time_sec"] == 110.0
    assert attrs["congestion_ratio"] == 0.77
    assert attrs["delay_minutes"] == 0.5


def test_15_road_segment_identity():
    """15. Test Functional Road Class (frc) mapping."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_FLOW_DATA,
        metadata={"requested_lat": 52.3731, "requested_lon": 4.8922},
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.normalized_attributes["road_category"] == "FRC0"


def test_16_incident_id_mapping():
    """16. Test provider incident ID propagation into canonical event."""
    raw = RawEvent(
        provider_name="tomtom",
        provider_event_id="tt_inc_001",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.source_event_id == "tt_inc_001"
    assert canon.normalized_attributes["incident_id"] == "tt_inc_001"


def test_17_incident_type_mapping():
    """17. Test incident type mapping (iconCategory 1 -> ROAD_INCIDENT)."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.event_type == CanonicalEventType.ROAD_INCIDENT


def test_18_incident_severity_mapping():
    """18. Test incident severity mapping from magnitudeOfDelay."""
    raw_moderate = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],  # magnitude 2
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw_moderate)
    assert canon.severity == EventSeverity.MEDIUM


def test_19_incident_location_mapping():
    """19. Test incident GeoJSON coordinates [lon, lat] mapped to EventLocation(lat, lon)."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.latitude == 52.3731
    assert canon.longitude == 4.8922
    assert canon.location.location_name == "Ring A10"


def test_20_incident_description_mapping():
    """20. Test incident description and road numbers mapping."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert "accident involving multiple vehicles" in canon.normalized_attributes["description"]
    assert "A10" in canon.normalized_attributes["road_numbers"]


def test_21_incident_time_mapping():
    """21. Test incident startTime mapping to event_timestamp."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.event_timestamp == datetime(2026, 9, 8, 8, 0, 0, tzinfo=timezone.utc)


def test_22_closure_mapping_when_supported():
    """22. Test road closure mapping (iconCategory 8) to ROAD_CLOSURE and CRITICAL severity."""
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][1],  # Closed road
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.event_type == CanonicalEventType.ROAD_CLOSURE
    assert canon.severity == EventSeverity.CRITICAL
    assert canon.normalized_attributes["is_closed"] is True


def test_23_missing_optional_fields():
    """23. Test robustness when optional flow or incident fields are missing."""
    sparse_flow = {
        "flowSegmentData": {
            "currentSpeed": 60,
            "freeFlowSpeed": 60,
        }
    }
    raw = RawEvent(provider_name="tomtom", raw_payload=sparse_flow)
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)
    assert canon.normalized_attributes["current_speed_kmh"] == 60.0
    assert "road_category" not in canon.normalized_attributes


def test_24_malformed_provider_response():
    """24. Test that malformed JSON response raises ProviderResponseError."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"MALFORMED_JSON_RESP", request=req)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TomTomAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderResponseError):
        adapter.fetch(latitude=52.3731, longitude=4.8922)


def test_25_authentication_failure():
    """25. Test HTTP 401/403 raises non-retriable ProviderAuthenticationError."""
    client = create_mock_client(401, json_data={"error": "Invalid developer key"})
    adapter = TomTomAdapter(secret="bad_key", http_client=client)

    with pytest.raises(ProviderAuthenticationError) as exc:
        adapter.fetch(latitude=52.3731, longitude=4.8922)
    assert exc.value.status_code == 401
    assert exc.value.retriable is False


def test_26_rate_limiting_429():
    """26. Test HTTP 429 raises retriable ProviderRateLimitError with Retry-After."""
    client = create_mock_client(429, json_data={"error": "Rate limit reached"}, headers={"Retry-After": "30"})
    adapter = TomTomAdapter(secret="key", http_client=client)

    with pytest.raises(ProviderRateLimitError) as exc:
        adapter.fetch(latitude=52.3731, longitude=4.8922)
    assert exc.value.retriable is True
    assert exc.value.retry_after == 30.0


def test_27_transient_5xx_failure():
    """27. Test HTTP 503 raises retriable ProviderResponseError."""
    client = create_mock_client(503, json_data={"error": "Service Unavailable"})
    adapter = TomTomAdapter(secret="key", http_client=client)

    with pytest.raises(ProviderResponseError) as exc:
        adapter.fetch(latitude=52.3731, longitude=4.8922)
    assert exc.value.retriable is True


def test_28_retry_behavior():
    """28. Test bounded exponential retry handles transient failures."""
    calls = [0]

    def handler(req: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] < 3:
            return httpx.Response(502, json={"error": "Bad Gateway"}, request=req)
        return httpx.Response(200, json=SAMPLE_FLOW_DATA, request=req)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = TomTomAdapter(secret="test_key", http_client=client)
    policy = RetryPolicy(RetryConfig(max_retries=3, initial_delay_seconds=0.01))

    batch = policy.execute(lambda: adapter.fetch(latitude=52.3731, longitude=4.8922), sleep_func=lambda s: None)
    assert calls[0] == 3
    assert len(batch.events) == 1


def test_29_retry_after_handling():
    """29. Test RetryPolicy delay computation respects Retry-After."""
    cfg = RetryConfig(max_retries=2, initial_delay_seconds=1.0, max_delay_seconds=60.0)
    delay = RetryPolicy.compute_delay(attempt=0, config=cfg, retry_after=25.0)
    assert delay == 25.0


def test_30_deterministic_idempotency():
    """30. Test deterministic SHA-256 fingerprint generation for incidents and flow."""
    # Incident fingerprint based on stable provider ID
    fp_inc1 = TomTomAdapter.compute_incident_fingerprint("tt_inc_001", org_id="org_1")
    fp_inc2 = TomTomAdapter.compute_incident_fingerprint("tt_inc_001", org_id="org_1")
    assert fp_inc1 == fp_inc2
    assert len(fp_inc1) == 64

    # Flow fingerprint based on micro-coordinates and timestamp
    fp_flow1 = TomTomAdapter.compute_flow_fingerprint(52.37311, 4.89221, 1700000000, frc="FRC0")
    fp_flow2 = TomTomAdapter.compute_flow_fingerprint(52.37314, 4.89224, 1700000000, frc="FRC0")
    assert fp_flow1 == fp_flow2


def test_31_duplicate_observation_handling():
    """31. Test that repeated ingestion of identical incident is deduplicated."""
    idempotency = IdempotencyEngine()
    client = create_mock_client(200, json_data=SAMPLE_INCIDENTS_DATA)
    adapter = TomTomAdapter(secret="key", http_client=client, idempotency_engine=idempotency)

    batch = adapter.fetch_incidents(bbox=(4.8, 52.3, 5.0, 52.4))
    ev1 = batch.events[0]

    unique1, _ = idempotency.check_and_record(ev1)
    assert unique1 is True

    unique2, _ = idempotency.check_and_record(ev1)
    assert unique2 is False


def test_32_canonical_event_generation():
    """32. Test end-to-end CanonicalExternalEvent generation from TomTom RawEvent."""
    raw = RawEvent(
        provider_name="tomtom",
        provider_event_id="tt_inc_001",
        raw_payload=SAMPLE_INCIDENTS_DATA["incidents"][0],
        metadata={"route_id": "rt_ams_01", "shipment_id": "shp_888"},
    )
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)

    assert canon.provider == "tomtom"
    assert canon.event_type == CanonicalEventType.ROAD_INCIDENT
    assert canon.latitude == 52.3731
    assert canon.longitude == 4.8922
    assert canon.correlation.shipment_id == "shp_888"
    assert canon.quality == EventQuality.VALID


def test_33_raw_payload_preservation():
    """33. Test raw provider response is preserved intact in RawEvent."""
    client = create_mock_client(200, json_data=SAMPLE_FLOW_DATA)
    adapter = TomTomAdapter(secret="key", http_client=client)

    batch = adapter.fetch(latitude=52.3731, longitude=4.8922)
    raw = batch.events[0]
    assert raw.raw_payload["flowSegmentData"]["currentSpeed"] == 85
    assert raw.raw_payload["flowSegmentData"]["freeFlowSpeed"] == 110


def test_34_secret_redaction():
    """34. Test that TomTom API key is not stored in payload or logs."""
    client = create_mock_client(200, json_data=SAMPLE_FLOW_DATA)
    adapter = TomTomAdapter(secret="super_secret_tomtom_key_999", http_client=client)

    batch = adapter.fetch(latitude=52.3731, longitude=4.8922)
    raw = batch.events[0]
    assert "super_secret_tomtom_key_999" not in json.dumps(raw.raw_payload)

    sanitized_url = adapter._sanitize_url_for_logging("https://api.tomtom.com/traffic/services/4?key=super_secret_tomtom_key_999")
    assert "super_secret_tomtom_key_999" not in sanitized_url
    assert "key=[REDACTED]" in sanitized_url


def test_35_provider_health_check():
    """35. Test provider health check states (HEALTHY, UNCONFIGURED, UNHEALTHY, DEGRADED)."""
    # Healthy
    client_ok = create_mock_client(200, json_data=SAMPLE_FLOW_DATA)
    adapter_ok = TomTomAdapter(secret="valid_key", http_client=client_ok)
    assert adapter_ok.health_check().status == ProviderHealthStatus.HEALTHY

    # Unconfigured
    adapter_unconf = TomTomAdapter(
        config=ProviderConfig(provider_name="tomtom", provider_type=ProviderType.ROAD_TRAFFIC, secret_ref=None),
        secret=None,
    )
    assert adapter_unconf.health_check().status == ProviderHealthStatus.UNCONFIGURED

    # Unhealthy (401)
    client_401 = create_mock_client(401, json_data={"error": "Unauthorized"})
    adapter_401 = TomTomAdapter(secret="bad_key", http_client=client_401)
    assert adapter_401.health_check().status == ProviderHealthStatus.UNHEALTHY

    # Degraded (429)
    client_429 = create_mock_client(429, json_data={"error": "Rate limit"})
    adapter_429 = TomTomAdapter(secret="key", http_client=client_429)
    assert adapter_429.health_check().status == ProviderHealthStatus.DEGRADED


def test_36_scheduler_integration():
    """36. Test TomTom polling job registration with IngestionScheduler."""
    scheduler = InMemoryIngestionScheduler()
    job = ScheduledIngestionJob(
        job_id="tt_poll_amsterdam_flow",
        provider_name="tomtom",
        cron_or_interval="*/10 * * * *",
        enabled=True,
        parameters={"latitude": 52.3731, "longitude": 4.8922},
    )
    scheduler.register_job(job)
    retrieved = scheduler.get_job("tt_poll_amsterdam_flow")
    assert retrieved is not None
    assert retrieved.parameters["latitude"] == 52.3731


def test_37_observability_metadata():
    """37. Test IngestionService records complete metadata during TomTom ingestion."""
    client = create_mock_client(200, json_data=SAMPLE_FLOW_DATA)
    service = IngestionService()
    default_provider_registry.register(
        type("MockTTAdapter", (TomTomAdapter,), {"__init__": lambda self, **kwargs: TomTomAdapter.__init__(self, secret="test_key", http_client=client)}),
        overwrite=True,
    )

    result = service.ingest(
        provider_name="tomtom",
        parameters={"latitude": 52.3731, "longitude": 4.8922},
        correlation_id="corr_traffic_99",
    )

    assert result.status == IngestionStatus.SUCCESS
    assert result.metadata.provider == "tomtom"
    assert result.metadata.correlation_id == "corr_traffic_99"
    assert result.metadata.items_fetched == 1
    assert result.metadata.items_ingested == 1


def test_38_tenant_org_isolation():
    """38. Test multi-tenant isolation in idempotency fingerprinting."""
    idempotency = IdempotencyEngine()
    client = create_mock_client(200, json_data=SAMPLE_FLOW_DATA)
    adapter = TomTomAdapter(secret="key", http_client=client, idempotency_engine=idempotency)

    batch_a = adapter.fetch(latitude=52.3731, longitude=4.8922, organization_id="org_alpha")
    ev_a = batch_a.events[0]
    unique_a, fp_a = idempotency.check_and_record(ev_a, organization_id="org_alpha")
    assert unique_a is True

    batch_b = adapter.fetch(latitude=52.3731, longitude=4.8922, organization_id="org_beta")
    ev_b = batch_b.events[0]
    unique_b, fp_b = idempotency.check_and_record(ev_b, organization_id="org_beta")
    assert unique_b is True
    assert fp_a != fp_b


def test_39_normal_traffic_does_not_become_critical_risk():
    """39. Test that normal uncongested flow remains INFO/LOW and never becomes CRITICAL risk."""
    normalizer = TomTomNormalizer()
    raw = RawEvent(
        provider_name="tomtom",
        raw_payload=SAMPLE_NORMAL_FLOW,
        metadata={"requested_lat": 52.3731, "requested_lon": 4.8922},
    )
    canon = normalizer.normalize(raw)

    assert canon.severity in (EventSeverity.INFO, EventSeverity.LOW)
    assert canon.severity not in (EventSeverity.HIGH, EventSeverity.CRITICAL)
    assert canon.event_type == CanonicalEventType.CUSTOM


def test_40_severe_incident_severity_mapping():
    """40. Test that severe incident with heavy delay receives CRITICAL severity."""
    severe_incident = {
        "type": "Feature",
        "id": "tt_inc_severe",
        "geometry": {"type": "Point", "coordinates": [4.8922, 52.3731]},
        "properties": {
            "id": "tt_inc_severe",
            "iconCategory": 1,
            "magnitudeOfDelay": 4,  # Indefinite / major
            "delay": 5400,  # 90 minutes
            "roadName": "A1 Motorway",
            "events": [{"description": "severe pileup, multiple lanes blocked"}],
        },
    }
    raw = RawEvent(provider_name="tomtom", raw_payload=severe_incident)
    normalizer = TomTomNormalizer()
    canon = normalizer.normalize(raw)

    assert canon.event_type == CanonicalEventType.ROAD_INCIDENT
    assert canon.severity == EventSeverity.CRITICAL
    assert canon.delay_minutes == 90.0
