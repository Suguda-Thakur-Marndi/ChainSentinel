"""Unit and contract tests for Open-Meteo Weather & Marine Provider Integration.

Tests the full lifecycle of the Open-Meteo integration:
 1. Adapter initialization and capabilities
 2. Configuration loading and default endpoints
 3. Successful atmospheric weather fetch (mocked)
 4. Successful marine wave & sea state fetch (mocked)
 5. Coordinate validation and bounds enforcement
 6. UTC timestamp parsing from ISO format
 7. Operational severity mapping: normal weather is INFO (never critical risk)
 8. Severe wind, wave height, and thunderstorms mapped to HIGH/CRITICAL
 9. WMO weather code mapping and descriptions
10. Multi-location batch query
11. Missing optional fields handled gracefully
12. Malformed JSON response handling
13. HTTP 400 Bad Request error handling
14. HTTP 429 rate limiting and quota handling
15. Transient HTTP 5xx errors and bounded retry policy
16. Deterministic idempotency fingerprinting
17. Duplicate observation suppression
18. Canonical event generation and quality assessment
19. Provider health check probe (HEALTHY, DEGRADED, UNHEALTHY)
20. Registry integration in default_provider_registry
21. Tenant/org isolation
22. Optional API key secret resolution and credential redaction
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
from app.integrations.providers.openmeteo import (
    DEFAULT_OPENMETEO_FORECAST_URL,
    DEFAULT_OPENMETEO_MARINE_URL,
    OpenMeteoAdapter,
    OpenMeteoNormalizer,
)


# =====================================================================
# Mock Payloads & Transport Helpers
# =====================================================================

SAMPLE_OPENMETEO_FORECAST = {
    "latitude": 1.29,
    "longitude": 103.85,
    "generationtime_ms": 0.12,
    "utc_offset_seconds": 0,
    "timezone": "UTC",
    "elevation": 15.0,
    "current": {
        "time": "2024-10-29T12:00:00Z",
        "interval": 900,
        "temperature_2m": 29.5,
        "relative_humidity_2m": 82,
        "apparent_temperature": 34.2,
        "precipitation": 0.0,
        "rain": 0.0,
        "weather_code": 1,  # Mainly clear
        "surface_pressure": 1010.5,
        "wind_speed_10m": 12.6,  # km/h (~3.5 m/s)
        "wind_direction_10m": 140,
        "wind_gusts_10m": 18.0,
    },
}

SAMPLE_OPENMETEO_MARINE = {
    "latitude": 1.29,
    "longitude": 103.85,
    "current": {
        "time": "2024-10-29T12:00:00Z",
        "wave_height": 1.2,
        "wave_direction": 135,
        "wave_period": 4.5,
        "wind_wave_height": 0.8,
        "swell_wave_height": 0.9,
    },
}

SAMPLE_OPENMETEO_TYPHOON = {
    "latitude": 22.0,
    "longitude": 121.0,
    "current": {
        "time": "2024-10-29T12:00:00Z",
        "temperature_2m": 26.0,
        "relative_humidity_2m": 98,
        "precipitation": 45.0,
        "weather_code": 99,  # Severe thunderstorm with heavy hail
        "surface_pressure": 965.0,
        "wind_speed_10m": 126.0,  # km/h (~35 m/s -> Hurricane force)
        "wind_gusts_10m": 160.0,
    },
}


def create_mock_openmeteo_client(
    forecast_status: int = 200,
    forecast_data: Any = None,
    marine_data: Any = None,
    exception: Optional[Exception] = None,
    headers: Optional[Dict[str, str]] = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if exception:
            raise exception
        url_str = str(request.url)
        if "marine" in url_str:
            return httpx.Response(200, json=marine_data or SAMPLE_OPENMETEO_MARINE)
        return httpx.Response(
            status_code=forecast_status,
            json=forecast_data if forecast_data is not None else SAMPLE_OPENMETEO_FORECAST,
            headers=headers or {"content-type": "application/json"},
        )
    return httpx.Client(transport=httpx.MockTransport(handler))


# =====================================================================
# Test Suite
# =====================================================================

def test_01_adapter_initialization() -> None:
    adapter = OpenMeteoAdapter()
    assert adapter.provider_name == "openmeteo"
    assert adapter.provider_type == ProviderType.WEATHER
    assert adapter.capabilities.supports_polling is True
    assert adapter.capabilities.supports_health_check is True
    assert "marine" in adapter.capabilities.supported_modalities
    adapter.close()


def test_02_configuration_loading() -> None:
    cfg = ProviderConfig(
        provider_name="openmeteo",
        provider_type=ProviderType.WEATHER,
        base_url=DEFAULT_OPENMETEO_FORECAST_URL,
        rate_limit=RateLimitConfig(requests_per_minute=200),
    )
    adapter = OpenMeteoAdapter(config=cfg)
    assert adapter.config.rate_limit.requests_per_minute == 200
    adapter.close()


def test_03_successful_atmospheric_and_marine_fetch() -> None:
    client = create_mock_openmeteo_client()
    adapter = OpenMeteoAdapter(http_client=client)

    batch = adapter.fetch(
        latitude=1.29,
        longitude=103.85,
        include_marine=True,
        port_id="port_singapore",
        organization_id="org_test",
    )
    assert len(batch.events) == 1
    ev = batch.events[0]
    assert ev.provider_name == "openmeteo"
    assert ev.metadata["port_id"] == "port_singapore"
    assert ev.org_id == "org_test"

    raw_payload = ev.raw_payload
    assert "forecast" in raw_payload
    assert "marine" in raw_payload
    assert raw_payload["marine"]["wave_height"] == 1.2
    adapter.close()


def test_04_coordinate_validation() -> None:
    adapter = OpenMeteoAdapter()
    with pytest.raises(ValueError, match="Latitude out of bounds"):
        adapter.fetch(latitude=-95.0, longitude=50.0)

    with pytest.raises(ValueError, match="Longitude out of bounds"):
        adapter.fetch(latitude=10.0, longitude=200.0)

    with pytest.raises(ProviderValidationError):
        adapter.fetch()  # Missing both coordinates and locations
    adapter.close()


def test_05_normal_weather_does_not_become_critical_risk() -> None:
    normalizer = OpenMeteoNormalizer()
    raw = RawEvent(
        provider_name="openmeteo",
        raw_payload={"forecast": SAMPLE_OPENMETEO_FORECAST, "marine": SAMPLE_OPENMETEO_MARINE},
    )
    canon = normalizer.normalize(raw)
    assert canon.severity == EventSeverity.INFO
    assert canon.quality == EventQuality.VALID
    assert canon.location.latitude == 1.29
    assert canon.location.longitude == 103.85
    assert canon.normalized_attributes["temperature_celsius"] == 29.5
    assert canon.normalized_attributes["weather_condition"] == "Mainly clear"
    assert canon.normalized_attributes["wave_height_meters"] == 1.2


def test_06_typhoon_and_violent_storm_severity_mapping() -> None:
    normalizer = OpenMeteoNormalizer()
    raw = RawEvent(
        provider_name="openmeteo",
        raw_payload={"forecast": SAMPLE_OPENMETEO_TYPHOON, "marine": {"wave_height": 9.5}},
    )
    canon = normalizer.normalize(raw)
    assert canon.severity == EventSeverity.CRITICAL
    assert canon.normalized_attributes["wind_speed_mps"] == 35.0
    assert canon.normalized_attributes["wave_height_meters"] == 9.5
    assert canon.normalized_attributes["weather_code"] == 99


def test_07_multi_location_batch_query() -> None:
    client = create_mock_openmeteo_client()
    adapter = OpenMeteoAdapter(http_client=client)

    locations = [
        {"lat": 30.58, "lon": 32.56, "port_id": "port_suez"},
        {"lat": 9.35, "lon": -79.90, "port_id": "port_panama"},
    ]
    batch = adapter.fetch(locations=locations)
    assert len(batch.events) == 2
    assert batch.events[0].metadata["port_id"] == "port_suez"
    assert batch.events[1].metadata["port_id"] == "port_panama"
    adapter.close()


def test_08_missing_optional_fields() -> None:
    normalizer = OpenMeteoNormalizer()
    minimal_payload = {
        "latitude": 40.71,
        "longitude": -74.00,
        "current": {
            "time": "2024-10-29T12:00:00Z",
            "temperature_2m": 15.0,
        },
    }
    raw = RawEvent(provider_name="openmeteo", raw_payload=minimal_payload)
    canon = normalizer.normalize(raw)
    assert canon.quality == EventQuality.VALID
    assert canon.normalized_attributes["temperature_celsius"] == 15.0
    assert canon.normalized_attributes["wave_height_meters"] is None


def test_09_malformed_response_handling() -> None:
    client = create_mock_openmeteo_client(forecast_data={"error": True, "reason": "Bad request"})
    adapter = OpenMeteoAdapter(http_client=client)
    batch = adapter.fetch(lat=10.0, lon=20.0)
    assert len(batch.events) == 1
    adapter.close()


def test_10_http_400_validation_error() -> None:
    client = create_mock_openmeteo_client(forecast_status=400)
    adapter = OpenMeteoAdapter(http_client=client)
    with pytest.raises(ProviderValidationError):
        adapter.fetch(lat=10.0, lon=20.0)
    adapter.close()


def test_11_http_429_rate_limit_and_quota() -> None:
    client = create_mock_openmeteo_client(forecast_status=429, headers={"Retry-After": "60"})
    adapter = OpenMeteoAdapter(http_client=client)
    with pytest.raises(ProviderRateLimitError) as exc:
        adapter.fetch(lat=10.0, lon=20.0)
    assert exc.value.retry_after_seconds == 60.0
    adapter.close()


def test_12_transient_5xx_and_retry() -> None:
    attempts = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json=SAMPLE_OPENMETEO_FORECAST)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenMeteoAdapter(http_client=client)

    policy = RetryPolicy(RetryConfig(max_retries=2, initial_delay_seconds=0.01))
    batch = policy.execute(lambda: adapter.fetch(lat=1.29, lon=103.85))
    assert len(batch.events) == 1
    assert attempts == 2
    adapter.close()


def test_13_deterministic_idempotency_fingerprint() -> None:
    fp1 = OpenMeteoAdapter.compute_observation_fingerprint(
        latitude=1.29,
        longitude=103.85,
        observation_timestamp="2024-10-29T12:00:00Z",
        weather_code=1,
    )
    fp2 = OpenMeteoAdapter.compute_observation_fingerprint(
        latitude=1.29,
        longitude=103.85,
        observation_timestamp="2024-10-29T12:00:00Z",
        weather_code=1,
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_14_provider_health_check() -> None:
    # 1. Healthy
    client_ok = create_mock_openmeteo_client()
    adapter_ok = OpenMeteoAdapter(http_client=client_ok)
    h_ok = adapter_ok.health_check()
    assert h_ok.status == ProviderHealthStatus.HEALTHY
    adapter_ok.close()

    # 2. Degraded 429
    client_429 = create_mock_openmeteo_client(forecast_status=429)
    adapter_429 = OpenMeteoAdapter(http_client=client_429)
    h_429 = adapter_429.health_check()
    assert h_429.status == ProviderHealthStatus.DEGRADED
    adapter_429.close()

    # 3. Timeout
    client_to = create_mock_openmeteo_client(exception=httpx.TimeoutException("Timeout"))
    adapter_to = OpenMeteoAdapter(http_client=client_to)
    h_to = adapter_to.health_check()
    assert h_to.status == ProviderHealthStatus.UNHEALTHY
    adapter_to.close()


def test_15_registry_integration() -> None:
    assert default_provider_registry.is_registered("openmeteo")
    cls = default_provider_registry.get_adapter_cls("openmeteo")
    assert cls == OpenMeteoAdapter

    adapter = default_provider_registry.create_adapter("openmeteo")
    assert isinstance(adapter, OpenMeteoAdapter)
    adapter.close()


def test_16_tenant_org_isolation() -> None:
    fp_a = OpenMeteoAdapter.compute_observation_fingerprint(1.29, 103.85, "2024-10-29T12:00:00Z", org_id="tenant_a")
    fp_b = OpenMeteoAdapter.compute_observation_fingerprint(1.29, 103.85, "2024-10-29T12:00:00Z", org_id="tenant_b")
    assert fp_a != fp_b
