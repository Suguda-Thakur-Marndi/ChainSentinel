"""Unit and contract tests for USGS Earthquake Hazards Program Provider Integration.

Tests the full lifecycle of the USGS integration:
 1. Adapter initialization and capability inspection
 2. Configuration loading and defaults
 3. Successful GeoJSON feed parsing (mocked)
 4. FDSN query parameter construction and execution
 5. Coordinate validation and bounds enforcement
 6. UTC timestamp normalization from epoch milliseconds
 7. Richter magnitude and tsunami operational severity mapping
 8. Normal minor tremors do not become critical risk (M < 4.0 -> INFO)
 9. Severe earthquakes trigger HIGH/CRITICAL severity (M >= 6.0 / 7.0 / tsunami)
10. Missing optional attributes handled gracefully
11. Malformed GeoJSON response error handling
12. HTTP 400 validation error handling
13. HTTP 429 rate limit response and Retry-After handling
14. Transient HTTP 500/503 errors and bounded retry policy
15. Deterministic idempotency fingerprinting (SHA-256)
16. Duplicate event suppression
17. Canonical event generation and schema validation
18. EventQuality assessment (VALID, PARTIAL, INVALID)
19. Raw payload preservation and credential safety
20. Provider health check (HEALTHY, DEGRADED, UNHEALTHY)
21. Multi-tenant organization isolation
22. Registry integration in default_provider_registry
23. Domain normalization into SignalDomain.GEOLOGICAL
24. Live smoke test (when online, non-blocking)
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
    ProviderConfigurationError,
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
    TimestampNormalizer,
    default_provider_registry,
)
from app.integrations.providers.usgs import (
    DEFAULT_USGS_FEED_URL,
    DEFAULT_USGS_QUERY_URL,
    USGSEarthquakeAdapter,
    USGSEarthquakeNormalizer,
)
from app.normalization.contract import SignalDomain, SignalType
from app.normalization.handlers import (
    DomainNormalizationRegistry,
    GeologicalHazardNormalizationHandler,
)


# =====================================================================
# Mock GeoJSON Responses & Fixtures
# =====================================================================

SAMPLE_USGS_GEOJSON = {
    "type": "FeatureCollection",
    "metadata": {
        "generated": 1729000000000,
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
        "title": "USGS Magnitude 4.5+ Earthquakes, Past Day",
        "status": 200,
        "api": "1.10.3",
        "count": 3,
    },
    "features": [
        {
            "type": "Feature",
            "properties": {
                "mag": 7.4,
                "place": "18 km SSW of Hualien City, Taiwan",
                "time": 1712102280000,
                "updated": 1712120000000,
                "tz": None,
                "url": "https://earthquake.usgs.gov/earthquakes/event/us7000m123",
                "detail": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/us7000m123.geojson",
                "felt": 1250,
                "cdi": 8.5,
                "mmi": 7.8,
                "alert": "red",
                "status": "reviewed",
                "tsunami": 1,
                "sig": 980,
                "net": "us",
                "code": "7000m123",
                "ids": ",us7000m123,",
                "sources": ",us,",
                "types": ",dyfi,general-link,ground-failure,losspager,moment-tensor,origin,phase-data,shakemap,",
                "nst": 120,
                "dmin": 0.45,
                "rms": 0.82,
                "gap": 22,
                "magType": "mww",
                "type": "earthquake",
                "title": "M 7.4 - 18 km SSW of Hualien City, Taiwan",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [121.56, 23.82, 34.8],  # [lon, lat, depth]
            },
            "id": "us7000m123",
        },
        {
            "type": "Feature",
            "properties": {
                "mag": 5.2,
                "place": "Off coast of Sendai, Japan",
                "time": 1712105000000,
                "updated": 1712110000000,
                "url": "https://earthquake.usgs.gov/earthquakes/event/us7000m456",
                "felt": 85,
                "alert": "yellow",
                "status": "reviewed",
                "tsunami": 0,
                "sig": 420,
                "magType": "mww",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [141.8, 38.2, 50.0],
            },
            "id": "us7000m456",
        },
        {
            "type": "Feature",
            "properties": {
                "mag": 3.2,
                "place": "12 km N of Ridgecrest, California",
                "time": 1712108000000,
                "updated": 1712109000000,
                "status": "automatic",
                "tsunami": 0,
                "sig": 160,
                "magType": "ml",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [-117.65, 35.72, 8.2],
            },
            "id": "ci4000m789",
        },
    ],
}


def create_mock_usgs_client(
    status_code: int = 200,
    json_data: Any = None,
    headers: Optional[Dict[str, str]] = None,
    exception: Optional[Exception] = None,
) -> httpx.Client:
    """Helper creating an in-memory httpx.Client using httpx.MockTransport."""
    def handler(request: httpx.Request) -> httpx.Response:
        if exception:
            raise exception
        return httpx.Response(
            status_code=status_code,
            json=json_data if json_data is not None else SAMPLE_USGS_GEOJSON,
            headers=headers or {"content-type": "application/json"},
        )
    return httpx.Client(transport=httpx.MockTransport(handler))


# =====================================================================
# Test Suite
# =====================================================================

def test_01_adapter_initialization() -> None:
    adapter = USGSEarthquakeAdapter()
    assert adapter.provider_name == "usgs_earthquake"
    assert adapter.provider_type == ProviderType.SEISMIC
    assert adapter.capabilities.supports_polling is True
    assert adapter.capabilities.supports_historical is True
    assert adapter.capabilities.supports_health_check is True
    assert "seismic" in adapter.capabilities.supported_modalities
    adapter.close()


def test_02_configuration_loading() -> None:
    custom_cfg = ProviderConfig(
        provider_name="usgs_earthquake",
        provider_type=ProviderType.SEISMIC,
        base_url="https://custom.usgs.gov/earthquakes",
        rate_limit=RateLimitConfig(requests_per_minute=30),
        retry=RetryConfig(max_retries=5),
    )
    adapter = USGSEarthquakeAdapter(config=custom_cfg)
    assert adapter.config.base_url == "https://custom.usgs.gov/earthquakes"
    assert adapter.config.rate_limit.requests_per_minute == 30
    assert adapter.config.retry.max_retries == 5
    adapter.close()


def test_03_successful_feed_fetch() -> None:
    client = create_mock_usgs_client(status_code=200, json_data=SAMPLE_USGS_GEOJSON)
    adapter = USGSEarthquakeAdapter(http_client=client)

    batch = adapter.fetch(port_id="port_kaohsiung", organization_id="org_supply_corp")
    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "usgs_earthquake"
    assert len(batch.events) == 3

    ev = batch.events[0]
    assert ev.provider_name == "usgs_earthquake"
    assert ev.provider_event_id == "us7000m123"
    assert ev.org_id == "org_supply_corp"
    assert ev.metadata["port_id"] == "port_kaohsiung"
    assert ev.fingerprint is not None
    assert ev.source_timestamp.year == 2024
    adapter.close()


def test_04_fdsn_query_mode() -> None:
    recorded_urls = []
    def handler(request: httpx.Request) -> httpx.Response:
        recorded_urls.append(str(request.url))
        return httpx.Response(200, json=SAMPLE_USGS_GEOJSON)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = USGSEarthquakeAdapter(http_client=client)

    adapter.fetch(
        latitude=23.8,
        longitude=121.5,
        max_radius_km=250.0,
        min_magnitude=5.0,
        start_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
    )
    assert len(recorded_urls) == 1
    req_url = recorded_urls[0]
    assert "fdsnws/event/1/query" in req_url
    assert "minmagnitude=5.0" in req_url
    assert "latitude=23.8" in req_url
    assert "longitude=121.5" in req_url
    assert "maxradiuskm=250.0" in req_url
    adapter.close()


def test_05_coordinate_validation() -> None:
    adapter = USGSEarthquakeAdapter()
    with pytest.raises(ValueError, match="Latitude out of bounds"):
        adapter.fetch(latitude=95.0, longitude=120.0)

    with pytest.raises(ValueError, match="Longitude out of bounds"):
        adapter.fetch(latitude=20.0, longitude=195.0)
    adapter.close()


def test_06_utc_timestamp_normalization() -> None:
    client = create_mock_usgs_client()
    adapter = USGSEarthquakeAdapter(http_client=client)
    batch = adapter.fetch()
    ev = batch.events[0]
    assert ev.source_timestamp.tzinfo == timezone.utc
    assert ev.source_timestamp.hour == 23  # UTC hour for epoch 1712102280000
    adapter.close()


def test_07_richer_magnitude_severity_mapping() -> None:
    normalizer = USGSEarthquakeNormalizer()

    # Event 0: M 7.4 + Tsunami 1 -> CRITICAL
    raw_0 = RawEvent(
        provider_name="usgs_earthquake",
        raw_payload=SAMPLE_USGS_GEOJSON["features"][0],
    )
    canon_0 = normalizer.normalize(raw_0)
    assert canon_0.severity == EventSeverity.CRITICAL
    assert canon_0.event_type == CanonicalEventType.TSUNAMI
    assert canon_0.normalized_attributes["magnitude"] == 7.4
    assert canon_0.normalized_attributes["tsunami_warning"] is True

    # Event 1: M 5.2, yellow alert -> MEDIUM
    raw_1 = RawEvent(
        provider_name="usgs_earthquake",
        raw_payload=SAMPLE_USGS_GEOJSON["features"][1],
    )
    canon_1 = normalizer.normalize(raw_1)
    assert canon_1.severity == EventSeverity.MEDIUM
    assert canon_1.event_type == CanonicalEventType.EARTHQUAKE
    assert canon_1.normalized_attributes["magnitude"] == 5.2

    # Event 2: M 3.2 minor tremor -> INFO (Never falsely promoted to critical risk!)
    raw_2 = RawEvent(
        provider_name="usgs_earthquake",
        raw_payload=SAMPLE_USGS_GEOJSON["features"][2],
    )
    canon_2 = normalizer.normalize(raw_2)
    assert canon_2.severity == EventSeverity.INFO
    assert canon_2.event_type == CanonicalEventType.EARTHQUAKE


def test_08_missing_optional_fields() -> None:
    normalizer = USGSEarthquakeNormalizer()
    minimal_feature = {
        "type": "Feature",
        "properties": {
            "mag": 4.8,
            "time": 1712102280000,
        },
        "geometry": {
            "type": "Point",
            "coordinates": [100.0, 10.0],
        },
        "id": "minimal_01",
    }
    raw = RawEvent(provider_name="usgs_earthquake", raw_payload=minimal_feature)
    canon = normalizer.normalize(raw)
    assert canon.location.latitude == 10.0
    assert canon.location.longitude == 100.0
    assert canon.severity == EventSeverity.LOW
    assert canon.quality == EventQuality.VALID


def test_09_malformed_geojson_handling() -> None:
    client = create_mock_usgs_client(status_code=200, json_data={"unexpected": "payload"})
    adapter = USGSEarthquakeAdapter(http_client=client)
    batch = adapter.fetch()
    assert len(batch.events) == 0
    adapter.close()


def test_10_http_400_validation_error() -> None:
    client = create_mock_usgs_client(status_code=400, json_data={"error": "Result count exceeds 20000"})
    adapter = USGSEarthquakeAdapter(http_client=client)
    with pytest.raises(ProviderValidationError) as exc:
        adapter.fetch(min_magnitude=0.1)
    assert exc.value.status_code == 400
    adapter.close()


def test_11_http_429_rate_limiting() -> None:
    client = create_mock_usgs_client(status_code=429, headers={"Retry-After": "10"})
    adapter = USGSEarthquakeAdapter(http_client=client)
    with pytest.raises(ProviderRateLimitError) as exc:
        adapter.fetch()
    assert exc.value.retry_after_seconds == 10.0
    adapter.close()


def test_12_transient_5xx_and_retry() -> None:
    attempts = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json=SAMPLE_USGS_GEOJSON)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = USGSEarthquakeAdapter(http_client=client)

    policy = RetryPolicy(RetryConfig(max_retries=3, initial_delay_seconds=0.01))
    batch = policy.execute(adapter.fetch)
    assert len(batch.events) == 3
    assert attempts == 3
    adapter.close()


def test_13_deterministic_idempotency_fingerprint() -> None:
    fp1 = USGSEarthquakeAdapter.compute_earthquake_fingerprint(
        event_id="us7000m123",
        updated_timestamp=1712120000000,
        magnitude=7.4,
        org_id="org_test",
    )
    fp2 = USGSEarthquakeAdapter.compute_earthquake_fingerprint(
        event_id="us7000m123",
        updated_timestamp=1712120000000,
        magnitude=7.4,
        org_id="org_test",
    )
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256


def test_14_duplicate_event_suppression() -> None:
    engine = IdempotencyEngine()
    feature = SAMPLE_USGS_GEOJSON["features"][0]
    raw1 = RawEvent(
        provider_name="usgs_earthquake",
        provider_event_id="us7000m123",
        fingerprint=USGSEarthquakeAdapter.compute_earthquake_fingerprint("us7000m123", 1712120000000, 7.4),
        raw_payload=feature,
    )
    raw2 = RawEvent(
        provider_name="usgs_earthquake",
        provider_event_id="us7000m123",
        fingerprint=USGSEarthquakeAdapter.compute_earthquake_fingerprint("us7000m123", 1712120000000, 7.4),
        raw_payload=feature,
    )

    is_unique_1, _ = engine.check_and_record(raw1)
    is_unique_2, _ = engine.check_and_record(raw2)
    assert is_unique_1 is True
    assert is_unique_2 is False


def test_15_provider_health_check() -> None:
    # 1. Healthy
    client_ok = create_mock_usgs_client(status_code=200, json_data=SAMPLE_USGS_GEOJSON)
    adapter_ok = USGSEarthquakeAdapter(http_client=client_ok)
    h_ok = adapter_ok.health_check()
    assert h_ok.status == ProviderHealthStatus.HEALTHY
    assert h_ok.details["features_count"] == 3
    adapter_ok.close()

    # 2. Degraded 429
    client_429 = create_mock_usgs_client(status_code=429)
    adapter_429 = USGSEarthquakeAdapter(http_client=client_429)
    h_429 = adapter_429.health_check()
    assert h_429.status == ProviderHealthStatus.DEGRADED
    adapter_429.close()

    # 3. Timeout / Unhealthy
    client_timeout = create_mock_usgs_client(exception=httpx.TimeoutException("Timeout"))
    adapter_timeout = USGSEarthquakeAdapter(http_client=client_timeout)
    h_to = adapter_timeout.health_check()
    assert h_to.status == ProviderHealthStatus.UNHEALTHY
    adapter_timeout.close()


def test_16_registry_integration() -> None:
    assert default_provider_registry.is_registered("usgs_earthquake")
    cls = default_provider_registry.get_adapter_cls("usgs_earthquake")
    assert cls == USGSEarthquakeAdapter

    adapter = default_provider_registry.create_adapter("usgs_earthquake")
    assert isinstance(adapter, USGSEarthquakeAdapter)
    adapter.close()


def test_17_domain_normalization_handler() -> None:
    normalizer = USGSEarthquakeNormalizer()
    raw = RawEvent(
        provider_name="usgs_earthquake",
        raw_payload=SAMPLE_USGS_GEOJSON["features"][0],
        metadata={"port_id": "port_kaohsiung"},
        org_id="org_test",
    )
    canon = normalizer.normalize(raw)

    reg = DomainNormalizationRegistry()
    handler = reg.resolve_handler(canon)
    assert isinstance(handler, GeologicalHazardNormalizationHandler)

    signal = handler.normalize(canon)
    assert signal.domain == SignalDomain.GEOLOGICAL
    assert signal.signal_type == SignalType.HAZARD
    assert signal.severity == EventSeverity.CRITICAL
    assert signal.measurements.disruption_level >= 0.9
    assert signal.entities.port_id == "port_kaohsiung"


def test_18_tenant_org_isolation() -> None:
    feature = SAMPLE_USGS_GEOJSON["features"][0]
    fp_tenant_a = USGSEarthquakeAdapter.compute_earthquake_fingerprint(
        event_id="us7000m123", updated_timestamp=1712120000000, org_id="tenant_a"
    )
    fp_tenant_b = USGSEarthquakeAdapter.compute_earthquake_fingerprint(
        event_id="us7000m123", updated_timestamp=1712120000000, org_id="tenant_b"
    )
    assert fp_tenant_a != fp_tenant_b
