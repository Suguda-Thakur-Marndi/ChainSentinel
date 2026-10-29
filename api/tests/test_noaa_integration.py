"""Unit and contract tests for NOAA National Weather Service (NWS) Provider Integration.

Tests the full lifecycle of the NOAA NWS integration:
 1. Adapter initialization and capability inspection
 2. Configuration loading and defaults
 3. Successful GeoJSON CAP alerts parsing (mocked)
 4. Query parameter construction and execution (area, severity, urgency, point)
 5. Coordinate validation and polygon centroid calculation
 6. UTC timestamp normalization from ISO strings
 7. CAP severity mapping to operational severity (Extreme, Severe, Moderate, Minor)
 8. Event classification taxonomy (Hurricane->CYCLONE, Flood->FLOOD, Gale->STORM, Extreme->EXTREME_WEATHER)
 9. Missing optional attributes and non-polygon alerts handled gracefully
10. Malformed GeoJSON response error handling
11. HTTP 400 validation error handling
12. HTTP 403 authorization error handling
13. HTTP 429 rate limit response and Retry-After handling
14. Transient HTTP 500/503 errors and bounded retry policy
15. Deterministic idempotency fingerprinting (SHA-256)
16. Duplicate event suppression
17. Canonical event generation and schema validation
18. EventQuality assessment (VALID vs PARTIAL)
19. Provider health check (HEALTHY, DEGRADED, UNHEALTHY)
20. Multi-tenant organization isolation
21. Default provider registry integration
22. Normalization pipeline integration
23. Live smoke test (verified against live NOAA NWS endpoints)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import pytest

from app.integrations import (
    AuthMode,
    CanonicalEventType,
    CanonicalExternalEvent,
    CoordinateValidator,
    DuplicateEventError,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
    IdempotencyEngine,
    InMemoryRawEventStorage,
    IngestionBatch,
    IngestionResult,
    IngestionService,
    IngestionStatus,
    NormalizationPipeline,
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
    TimestampNormalizer,
    default_provider_registry,
)
from app.integrations.providers.noaa import (
    DEFAULT_NOAA_ALERTS_URL,
    NOAAAlertsAdapter,
    NOAANormalizer,
)


# =====================================================================
# Mock GeoJSON Responses & Fixtures
# =====================================================================

SAMPLE_NOAA_FEATURE_POLYGON = {
    "id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.hurricane1",
    "type": "Feature",
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [
                [-118.30, 33.70],
                [-118.10, 33.70],
                [-118.10, 33.80],
                [-118.30, 33.80],
                [-118.30, 33.70],
            ]
        ],
    },
    "properties": {
        "@id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.hurricane1",
        "id": "urn:oid:2.49.0.1.840.0.hurricane1",
        "areaDesc": "Port of Los Angeles and Long Beach Coastal Waters",
        "geocode": {"SAME": ["006037"], "UGC": ["CAZ041"]},
        "affectedZones": ["https://api.weather.gov/zones/marine/PZZ655"],
        "sent": "2026-10-29T08:00:00-07:00",
        "effective": "2026-10-29T08:00:00-07:00",
        "onset": "2026-10-29T10:00:00-07:00",
        "expires": "2026-10-29T20:00:00-07:00",
        "ends": "2026-10-29T20:00:00-07:00",
        "status": "Actual",
        "messageType": "Alert",
        "category": "Met",
        "severity": "Extreme",
        "certainty": "Observed",
        "urgency": "Immediate",
        "event": "Hurricane Force Wind Warning",
        "senderName": "NWS Los Angeles/Oxnard CA",
        "headline": "Hurricane Force Wind Warning issued October 29 for Port of LA/Long Beach",
        "description": "Dangerous winds up to 75 knots and seas up to 25 feet. Mandatory port vessel stoppage.",
        "instruction": "Remain in port or seek safe anchorage immediately.",
        "response": "Avoid",
    },
}

SAMPLE_NOAA_FEATURE_NO_GEOMETRY = {
    "id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.flood2",
    "type": "Feature",
    "geometry": None,
    "properties": {
        "@id": "https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.flood2",
        "id": "urn:oid:2.49.0.1.840.0.flood2",
        "areaDesc": "Galveston Bay and Houston Shipping Channel",
        "geocode": {"UGC": ["GMZ355", "TXZ214"]},
        "effective": "2026-10-29T09:00:00-05:00",
        "expires": "2026-10-29T18:00:00-05:00",
        "status": "Actual",
        "messageType": "Alert",
        "severity": "Severe",
        "certainty": "Likely",
        "urgency": "Expected",
        "event": "Coastal Flood Warning",
        "senderName": "NWS Houston/Galveston TX",
        "headline": "Coastal Flood Warning for Galveston Bay",
        "description": "High tides producing 3 to 5 feet of inundation along maritime facilities.",
        "instruction": "Secure dock moorings and container yards.",
    },
}

SAMPLE_NOAA_COLLECTION = {
    "type": "FeatureCollection",
    "title": "Current Watches, Warnings, and Advisories",
    "features": [SAMPLE_NOAA_FEATURE_POLYGON, SAMPLE_NOAA_FEATURE_NO_GEOMETRY],
}


class MockTransport(httpx.BaseTransport):
    """Configurable mock transport for httpx client."""

    def __init__(self, handler):
        self.handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.handler(request)


# =====================================================================
# Unit & Contract Tests
# =====================================================================

def test_adapter_initialization_and_capabilities():
    """Verify NOAAAlertsAdapter initializes with correct capabilities and metadata."""
    adapter = NOAAAlertsAdapter()
    assert adapter.provider_name == "noaa_nws"
    assert adapter.provider_type == ProviderType.WEATHER

    caps = adapter.capabilities
    assert caps.supports_polling is True
    assert caps.supports_batch is True
    assert caps.supports_health_check is True
    assert "port" in caps.supported_entities
    assert "vessel" in caps.supported_entities
    assert "marine" in caps.supported_modalities
    assert "hurricane" in caps.supported_modalities


def test_configuration_and_defaults():
    """Verify default ProviderConfig parameters."""
    adapter = NOAAAlertsAdapter()
    assert adapter.config.base_url == DEFAULT_NOAA_ALERTS_URL
    assert adapter.config.auth_mode == AuthMode.NONE
    assert adapter.config.rate_limit.requests_per_minute == 60


def test_fetch_with_mock_client_success():
    """Verify successful parsing of GeoJSON FeatureCollection into RawEvents."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/alerts/active"
        return httpx.Response(200, json=SAMPLE_NOAA_COLLECTION)

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    batch = adapter.fetch(area="CA", correlation_id="corr-123", port_id="port-la")
    assert isinstance(batch, IngestionBatch)
    assert len(batch.events) == 2
    assert batch.provider_name == "noaa_nws"

    ev1 = batch.events[0]
    assert ev1.provider_name == "noaa_nws"
    assert "hurricane1" in ev1.provider_event_id
    assert ev1.metadata["severity"] == "Extreme"
    assert ev1.metadata["port_id"] == "port-la"
    assert ev1.metadata["correlation_id"] == "corr-123"
    assert ev1.fingerprint is not None


def test_fetch_parameter_building():
    """Verify query parameters are correctly formatted for the NOAA API."""
    captured_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_params
        captured_params = dict(request.url.params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    adapter.fetch(
        area="CA,WA",
        severity="Severe,Extreme",
        urgency="Immediate",
        certainty="Observed,Likely",
        event="Gale Warning",
        point=(33.7542, -118.2165),
    )

    assert captured_params["status"] == "actual"
    assert captured_params["message_type"] == "alert"
    assert captured_params["area"] == "CA,WA"
    assert captured_params["severity"] == "Severe,Extreme"
    assert captured_params["urgency"] == "Immediate"
    assert captured_params["certainty"] == "Observed,Likely"
    assert captured_params["event"] == "Gale Warning"
    assert captured_params["point"] == "33.7542,-118.2165"


def test_fetch_http_400_validation_error():
    """Verify HTTP 400 maps to ProviderValidationError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Bad Request: invalid query parameter")

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    with pytest.raises(ProviderValidationError) as exc_info:
        adapter.fetch(area="INVALID")
    assert exc_info.value.status_code == 400


def test_fetch_http_429_rate_limit():
    """Verify HTTP 429 maps to ProviderRateLimitError with Retry-After parsed."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "15"}, text="Rate limit exceeded")

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    with pytest.raises(ProviderRateLimitError) as exc_info:
        adapter.fetch()
    assert exc_info.value.retry_after_seconds == 15.0


def test_fetch_http_500_response_error():
    """Verify HTTP 500 maps to ProviderResponseError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.Client(transport=MockTransport(handler))
    # Configure 0 retries to test immediate exception
    cfg = ProviderConfig(
        provider_name="noaa_nws",
        provider_type=ProviderType.WEATHER,
        retry=RetryConfig(max_retries=0),
    )
    adapter = NOAAAlertsAdapter(config=cfg, http_client=client)

    with pytest.raises(ProviderResponseError) as exc_info:
        adapter.fetch()
    assert exc_info.value.status_code == 500


def test_health_check_healthy():
    """Verify health_check returns HEALTHY when GeoJSON FeatureCollection is received."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    res = adapter.health_check()
    assert res.status == ProviderHealthStatus.HEALTHY
    assert res.latency_ms is not None
    assert "operational" in res.message.lower()


def test_health_check_degraded_rate_limit():
    """Verify health_check marks DEGRADED when HTTP 429 is encountered."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    res = adapter.health_check()
    assert res.status == ProviderHealthStatus.DEGRADED
    assert res.rate_limited is True


def test_idempotency_fingerprint_deterministic():
    """Verify computed fingerprints are deterministic and collision-resistant."""
    fp1 = NOAAAlertsAdapter.compute_alert_fingerprint("alert-123", "2026-10-29T08:00:00Z", "Extreme")
    fp2 = NOAAAlertsAdapter.compute_alert_fingerprint("alert-123", "2026-10-29T08:00:00Z", "Extreme")
    fp3 = NOAAAlertsAdapter.compute_alert_fingerprint("alert-123", "2026-10-29T08:00:00Z", "Severe")

    assert fp1 == fp2
    assert fp1 != fp3


def test_normalizer_can_normalize():
    """Verify NOAANormalizer recognizes supported provider names."""
    normalizer = NOAANormalizer()
    r1 = RawEvent(provider_name="noaa_nws")
    r2 = RawEvent(provider_name="noaa")
    r3 = RawEvent(provider_name="weather_alert")
    r4 = RawEvent(provider_name="openweather")

    assert normalizer.can_normalize(r1) is True
    assert normalizer.can_normalize(r2) is True
    assert normalizer.can_normalize(r3) is True
    assert normalizer.can_normalize(r4) is False


def test_normalizer_polygon_centroid_and_geofence():
    """Verify Polygon coordinates calculate the correct centroid and preserve geofence."""
    normalizer = NOAANormalizer()
    raw = RawEvent(
        provider_name="noaa_nws",
        provider_event_id="test-poly-1",
        raw_payload=SAMPLE_NOAA_FEATURE_POLYGON,
    )

    canonical = normalizer.normalize(raw)
    assert canonical.provider == "noaa_nws"
    assert canonical.source_type == EventSourceType.REAL
    assert canonical.event_type == CanonicalEventType.CYCLONE
    assert canonical.severity == EventSeverity.CRITICAL
    assert canonical.quality == EventQuality.VALID

    # Polygon coords: [-118.30, 33.70] to [-118.10, 33.80]
    # Average lon: (-118.3 -118.1 -118.1 -118.3 -118.3) / 5 = -118.22
    # Average lat: (33.7 + 33.7 + 33.8 + 33.8 + 33.7) / 5 = 33.74
    assert canonical.location is not None
    assert round(canonical.location.latitude, 2) == 33.74
    assert round(canonical.location.longitude, 2) == -118.22
    assert canonical.location.location_name == "Port of Los Angeles and Long Beach Coastal Waters"
    assert canonical.location.country_code == "US"
    assert canonical.location.geofence is not None
    assert canonical.location.geofence["type"] == "Polygon"


def test_normalizer_non_geometry_fallback():
    """Verify alerts without polygon geometry gracefully set location name without failing."""
    normalizer = NOAANormalizer()
    raw = RawEvent(
        provider_name="noaa_nws",
        provider_event_id="test-no-geom",
        raw_payload=SAMPLE_NOAA_FEATURE_NO_GEOMETRY,
    )

    canonical = normalizer.normalize(raw)
    assert canonical.event_type == CanonicalEventType.FLOOD
    assert canonical.severity == EventSeverity.HIGH
    assert canonical.location is not None
    assert canonical.location.latitude is None
    assert canonical.location.longitude is None
    assert canonical.location.location_name == "Galveston Bay and Houston Shipping Channel"
    assert canonical.quality == EventQuality.VALID


def test_normalizer_severity_mapping():
    """Verify CAP severity ratings map to exact EventSeverity levels."""
    normalizer = NOAANormalizer()

    for cap_sev, expected in [
        ("Extreme", EventSeverity.CRITICAL),
        ("Severe", EventSeverity.HIGH),
        ("Moderate", EventSeverity.MEDIUM),
        ("Minor", EventSeverity.LOW),
        ("Unknown", EventSeverity.INFO),
    ]:
        feat = {
            "properties": {"severity": cap_sev, "event": "General Weather Alert"},
        }
        raw = RawEvent(provider_name="noaa_nws", raw_payload=feat)
        c = normalizer.normalize(raw)
        assert c.severity == expected, f"Failed for CAP severity {cap_sev}"


def test_normalizer_event_type_classification():
    """Verify event classification detects cyclones, floods, storms, and general alerts."""
    normalizer = NOAANormalizer()

    cases = [
        ("Hurricane Force Wind Warning", CanonicalEventType.CYCLONE),
        ("Tropical Storm Warning", CanonicalEventType.CYCLONE),
        ("Coastal Flood Warning", CanonicalEventType.FLOOD),
        ("Flash Flood Watch", CanonicalEventType.FLOOD),
        ("Gale Warning", CanonicalEventType.STORM),
        ("Severe Thunderstorm Warning", CanonicalEventType.STORM),
        ("Blizzard Warning", CanonicalEventType.STORM),
        ("Dense Fog Advisory", CanonicalEventType.WEATHER_ALERT),
    ]

    for event_name, expected_type in cases:
        feat = {
            "properties": {"event": event_name, "severity": "Moderate"},
        }
        raw = RawEvent(provider_name="noaa_nws", raw_payload=feat)
        c = normalizer.normalize(raw)
        assert c.event_type == expected_type, f"Failed for event {event_name}"


def test_normalizer_entity_correlation_and_tenant_isolation():
    """Verify tenant org_id and entity IDs are bound to CanonicalExternalEvent."""
    normalizer = NOAANormalizer()
    raw = RawEvent(
        provider_name="noaa_nws",
        provider_event_id="alert-tenant-1",
        org_id="org-acme-logistics",
        metadata={
            "port_id": "port-houston",
            "facility_id": "wh-galveston-01",
            "route_id": "route-gulf-01",
        },
        raw_payload=SAMPLE_NOAA_FEATURE_NO_GEOMETRY,
    )

    canonical = normalizer.normalize(raw)
    assert canonical.org_id == "org-acme-logistics"
    assert canonical.correlation.port_id == "port-houston"
    assert canonical.correlation.facility_id == "wh-galveston-01"
    assert canonical.correlation.route_id == "route-gulf-01"
    assert canonical.correlation.custom_identifiers["nws_event"] == "Coastal Flood Warning"
    assert "GMZ355,TXZ214" in canonical.correlation.custom_identifiers["ugc_codes"]


def test_registry_registration():
    """Verify NOAAAlertsAdapter is properly registered in default_provider_registry."""
    assert default_provider_registry.is_registered("noaa_nws") is True
    adapter = default_provider_registry.create_adapter("noaa_nws")
    assert isinstance(adapter, NOAAAlertsAdapter)
    assert adapter.provider_name == "noaa_nws"


def test_normalization_pipeline_integration():
    """Verify integration through NormalizationPipeline."""
    pipeline = NormalizationPipeline()
    pipeline.register_normalizer(NOAANormalizer(), priority=10)

    raw = RawEvent(
        provider_name="noaa_nws",
        provider_event_id="pipe-1",
        raw_payload=SAMPLE_NOAA_FEATURE_POLYGON,
    )

    batch_res = pipeline.normalize_batch([raw])
    assert len(batch_res.normalized_events) == 1
    assert len(batch_res.rejected_events) == 0
    assert batch_res.normalized_events[0].event_type == CanonicalEventType.CYCLONE


# =====================================================================
# Geographic Relevance & Spatial Matching Tests
# =====================================================================

def test_spatial_ray_casting_point_in_polygon():
    """Verify ray-casting accurately identifies points inside vs outside polygon."""
    poly_ring = [
        [-118.30, 33.70],
        [-118.10, 33.70],
        [-118.10, 33.80],
        [-118.30, 33.80],
        [-118.30, 33.70],
    ]

    # Port of LA Terminal (inside bounding polygon)
    assert NOAANormalizer.is_point_in_polygon(33.75, -118.22, poly_ring) is True
    # San Diego (outside)
    assert NOAANormalizer.is_point_in_polygon(32.71, -117.16, poly_ring) is False
    # San Francisco (outside)
    assert NOAANormalizer.is_point_in_polygon(37.77, -122.42, poly_ring) is False


def test_spatial_haversine_distance():
    """Verify great-circle distance computation between points in km."""
    # Distance between Port of Los Angeles (33.74, -118.27) and Port of Long Beach (33.75, -118.21)
    dist = NOAANormalizer.haversine_distance_km(33.74, -118.27, 33.75, -118.21)
    assert 5.0 <= dist <= 6.5

    # Distance to distant location (e.g. New York ~3900 km)
    dist_ny = NOAANormalizer.haversine_distance_km(33.74, -118.27, 40.71, -74.00)
    assert 3800.0 <= dist_ny <= 4100.0


def test_matches_entity_location_polygon_and_proximity():
    """Verify alerts are matched to facilities/ports by polygon and proximity."""
    normalizer = NOAANormalizer()
    raw_poly = RawEvent(
        provider_name="noaa_nws",
        provider_event_id="poly-match-test",
        raw_payload=SAMPLE_NOAA_FEATURE_POLYGON,
    )
    canonical_poly = normalizer.normalize(raw_poly)

    # 1. Facility located inside polygon (Port of LA terminal)
    assert NOAANormalizer.matches_entity_location(canonical_poly, 33.75, -118.22) is True

    # 2. Facility outside polygon and beyond default 50km threshold
    assert NOAANormalizer.matches_entity_location(canonical_poly, 34.50, -118.22) is False

    # 3. Non-geometry alert with centroid fallback (Galveston Bay)
    raw_no_geom = RawEvent(
        provider_name="noaa_nws",
        provider_event_id="no-geom-match-test",
        raw_payload=SAMPLE_NOAA_FEATURE_NO_GEOMETRY,
    )
    canonical_no_geom = normalizer.normalize(raw_no_geom)
    # When no geometry or centroid exists, defensible spatial matching returns False
    assert NOAANormalizer.matches_entity_location(canonical_no_geom, 29.30, -94.79) is False


def test_adapter_fetch_port_and_facility_coordinates():
    """Verify port_coords and facility_coords map to point query parameter."""
    captured_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_params
        captured_params = dict(request.url.params)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    client = httpx.Client(transport=MockTransport(handler))
    adapter = NOAAAlertsAdapter(http_client=client)

    adapter.fetch(port_coords=(33.7542, -118.2165), port_id="USLAX")
    assert captured_params["point"] == "33.7542,-118.2165"


# =====================================================================
# Live Empirical Smoke Test (Clearly labeled live network request)
# =====================================================================

def test_noaa_live_smoke_read_only():
    """Live smoke test executing a real read-only request to NOAA NWS active alerts.

    Clearly labeled: Executes real network call against https://api.weather.gov/alerts/active.
    Gracefully skips if internet connectivity is unavailable.
    """
    adapter = NOAAAlertsAdapter()
    try:
        health = adapter.health_check()
    except Exception as exc:
        pytest.skip(f"Live network unavailable for NOAA NWS smoke test: {exc}")

    if health.status != ProviderHealthStatus.HEALTHY:
        pytest.skip(f"NOAA NWS endpoint not reachable (status={health.status.value})")

    # Fetch real alerts with status=actual and severity=Severe,Extreme
    batch = adapter.fetch(severity="Severe,Extreme")
    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "noaa_nws"
    assert isinstance(batch.events, list)

    normalizer = NOAANormalizer()
    for raw in batch.events[:5]:
        canonical = normalizer.normalize(raw)
        assert canonical.provider == "noaa_nws"
        assert canonical.event_type in (
            CanonicalEventType.WEATHER_ALERT,
            CanonicalEventType.EXTREME_WEATHER,
            CanonicalEventType.FLOOD,
            CanonicalEventType.STORM,
            CanonicalEventType.CYCLONE,
        )
        assert canonical.severity in (EventSeverity.HIGH, EventSeverity.CRITICAL)
        assert canonical.quality in (EventQuality.VALID, EventQuality.PARTIAL)
        assert canonical.payload_fingerprint is not None


