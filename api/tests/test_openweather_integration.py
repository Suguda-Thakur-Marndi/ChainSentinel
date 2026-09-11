"""Unit tests for Phase 5 Step 3: OpenWeather Weather Data Integration.

Covers all 34 required test cases using mocked HTTP responses (zero live network calls):
 1. Adapter initialization
 2. Configuration loading
 3. Missing API key / configuration
 4. Successful weather request
 5. Coordinate validation
 6. Invalid latitude
 7. Invalid longitude
 8. UTC timestamp normalization
 9. Temperature mapping
10. Precipitation mapping when present
11. Wind mapping when present
12. Pressure mapping when present
13. Humidity mapping when present
14. Visibility mapping when present
15. Weather condition mapping
16. Missing optional fields
17. Malformed provider response
18. Authentication failure (HTTP 401/403)
19. Rate-limit response (HTTP 429)
20. Transient provider failure (HTTP 502/503)
21. Retry behavior
22. Retry-After behavior
23. Deterministic idempotency
24. Duplicate observation handling
25. Canonical event generation
26. EventQuality behavior (VALID, PARTIAL, INVALID)
27. Normal weather does not become critical risk
28. Alert behavior according to supported API capability
29. Provider health check
30. Raw payload preservation
31. Secret redaction
32. Scheduler integration
33. Observability metadata
34. Tenant/org isolation
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
    InMemoryIngestionScheduler,
    InMemoryRawEventStorage,
    IngestionBatch,
    IngestionMetadata,
    IngestionResult,
    IngestionService,
    IngestionStatus,
    NormalizationPipeline,
    OpenWeatherAdapter,
    OpenWeatherNormalizer,
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
    default_provider_registry,
)


# =====================================================================
# Mock Responses & Mock Transport Helpers
# =====================================================================

SAMPLE_LONDON_WEATHER = {
    "coord": {"lon": -0.1278, "lat": 51.5074},
    "weather": [
        {
            "id": 800,
            "main": "Clear",
            "description": "clear sky",
            "icon": "01d",
        }
    ],
    "base": "stations",
    "main": {
        "temp": 18.5,
        "feels_like": 18.1,
        "temp_min": 17.0,
        "temp_max": 20.0,
        "pressure": 1016,
        "humidity": 55,
    },
    "visibility": 10000,
    "wind": {
        "speed": 3.6,
        "deg": 210,
        "gust": 5.2,
    },
    "clouds": {"all": 10},
    "dt": 1661870592,
    "sys": {
        "country": "GB",
        "sunrise": 1661834187,
        "sunset": 1661882025,
    },
    "id": 2643743,
    "name": "London",
    "cod": 200,
}

SAMPLE_SINGAPORE_RAIN = {
    "coord": {"lon": 103.8198, "lat": 1.3521},
    "weather": [
        {
            "id": 501,
            "main": "Rain",
            "description": "moderate rain",
            "icon": "10d",
        }
    ],
    "main": {
        "temp": 28.0,
        "feels_like": 32.5,
        "temp_min": 26.5,
        "temp_max": 30.0,
        "pressure": 1008,
        "humidity": 85,
    },
    "visibility": 7000,
    "wind": {
        "speed": 6.2,
        "deg": 180,
    },
    "rain": {"1h": 8.5, "3h": 15.0},
    "clouds": {"all": 75},
    "dt": 1661870600,
    "sys": {"country": "SG"},
    "id": 1880252,
    "name": "Singapore",
    "cod": 200,
}

SAMPLE_MIAMI_STORM = {
    "coord": {"lon": -80.1918, "lat": 25.7617},
    "weather": [
        {
            "id": 212,
            "main": "Thunderstorm",
            "description": "heavy thunderstorm",
            "icon": "11d",
        }
    ],
    "main": {
        "temp": 29.0,
        "feels_like": 35.0,
        "pressure": 995,
        "humidity": 90,
    },
    "visibility": 4000,
    "wind": {
        "speed": 22.5,
        "deg": 90,
        "gust": 28.0,
    },
    "rain": {"1h": 35.0},
    "dt": 1661870700,
    "sys": {"country": "US"},
    "id": 4164138,
    "name": "Miami",
    "cod": 200,
}

SAMPLE_ONE_CALL_ALERT = {
    "lat": 35.4676,
    "lon": -97.5164,
    "timezone": "America/Chicago",
    "current": {
        "dt": 1661870800,
        "temp": 24.0,
        "pressure": 980,
        "humidity": 82,
        "wind_speed": 18.0,
        "weather": [{"id": 212, "main": "Thunderstorm", "description": "heavy thunderstorm"}],
    },
    "alerts": [
        {
            "sender_name": "NWS Norman OK",
            "event": "Tornado Warning",
            "start": 1661870800,
            "end": 1661874400,
            "description": "A severe thunderstorm capable of producing a tornado was located over Oklahoma City.",
            "tags": ["Severe thunderstorm", "Tornado"],
        }
    ],
}


def create_mock_client(status_code: int = 200, json_data: Any = None, headers: Optional[Dict[str, str]] = None) -> httpx.Client:
    """Create an httpx client using MockTransport returning specified status and content."""
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps(json_data).encode("utf-8") if json_data is not None else b""
        resp_headers = headers or {}
        if "Content-Type" not in resp_headers:
            resp_headers["Content-Type"] = "application/json"
        return httpx.Response(status_code=status_code, content=content, headers=resp_headers, request=request)

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


# =====================================================================
# 34 Focused Unit Tests
# =====================================================================

def test_01_adapter_initialization():
    """1. Test adapter initialization, capabilities, and provider metadata."""
    adapter = OpenWeatherAdapter(secret="test_key_123")
    assert adapter.provider_name == "openweather"
    assert adapter.provider_type == ProviderType.WEATHER
    assert adapter.capabilities.supports_polling is True
    assert adapter.capabilities.supports_webhook is False
    assert adapter.capabilities.supports_health_check is True
    assert "weather" in adapter.capabilities.supported_modalities
    assert "location" in adapter.capabilities.supported_entities


def test_02_configuration_loading():
    """2. Test configuration loading, defaults, and custom overrides."""
    custom_cfg = ProviderConfig(
        provider_name="openweather",
        provider_type=ProviderType.WEATHER,
        base_url="https://api.openweathermap.org/data/2.5/weather",
        auth_mode=AuthMode.API_KEY_QUERY,
        secret_ref="env:CUSTOM_OPENWEATHER_KEY",
        rate_limit=RateLimitConfig(requests_per_minute=120),
        retry=RetryConfig(max_retries=5, initial_delay_seconds=1.0),
    )
    adapter = OpenWeatherAdapter(config=custom_cfg, secret="test_override")
    assert adapter.config.provider_name == "openweather"
    assert adapter.config.rate_limit.requests_per_minute == 120
    assert adapter.config.retry.max_retries == 5
    assert adapter.resolve_api_key() == "test_override"


def test_03_missing_api_key_configuration(monkeypatch):
    """3. Test that missing API key raises ProviderConfigurationError."""
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    monkeypatch.delenv("EMPTY_KEY_REF", raising=False)
    cfg = ProviderConfig(
        provider_name="openweather",
        provider_type=ProviderType.WEATHER,
        secret_ref="env:EMPTY_KEY_REF",
    )
    adapter = OpenWeatherAdapter(config=cfg, secret=None)
    with pytest.raises(ProviderConfigurationError) as exc_info:
        adapter.resolve_api_key()
    assert "not configured" in str(exc_info.value).lower()


def test_04_successful_weather_request():
    """4. Test successful weather request and IngestionBatch generation."""
    client = create_mock_client(status_code=200, json_data=SAMPLE_LONDON_WEATHER)
    adapter = OpenWeatherAdapter(secret="test_api_key", http_client=client)

    batch = adapter.fetch(latitude=51.5074, longitude=-0.1278)
    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "openweather"
    assert len(batch.events) == 1

    event = batch.events[0]
    assert event.provider_name == "openweather"
    assert event.raw_payload["name"] == "London"
    assert event.source_timestamp.tzinfo is not None
    assert event.fingerprint is not None


def test_05_coordinate_validation():
    """5. Test valid coordinates pass CoordinateValidator."""
    lat, lon = CoordinateValidator.validate(1.3521, 103.8198)
    assert lat == 1.3521
    assert lon == 103.8198


def test_06_invalid_latitude():
    """6. Test invalid latitude (> 90 or < -90) raises ProviderValidationError before request."""
    mock_called = [False]

    def mock_handler(req: httpx.Request) -> httpx.Response:
        mock_called[0] = True
        return httpx.Response(200, json=SAMPLE_LONDON_WEATHER, request=req)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderValidationError) as exc:
        adapter.fetch(latitude=95.0, longitude=-0.1278)
    assert "bounds" in str(exc.value).lower() or "invalid coordinates" in str(exc.value).lower()
    assert mock_called[0] is False, "HTTP request must not be issued for invalid coordinates"


def test_07_invalid_longitude():
    """7. Test invalid longitude (> 180 or < -180) raises ProviderValidationError before request."""
    mock_called = [False]

    def mock_handler(req: httpx.Request) -> httpx.Response:
        mock_called[0] = True
        return httpx.Response(200, json=SAMPLE_LONDON_WEATHER, request=req)

    client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderValidationError) as exc:
        adapter.fetch(latitude=51.5074, longitude=-195.0)
    assert "bounds" in str(exc.value).lower() or "invalid coordinates" in str(exc.value).lower()
    assert mock_called[0] is False, "HTTP request must not be issued for invalid coordinates"


def test_08_utc_timestamp_normalization():
    """8. Test that dt is normalized to timezone-aware UTC datetime."""
    dt_epoch = 1661870592
    normalized = TimestampNormalizer.parse_to_utc(dt_epoch)
    assert normalized.tzinfo == timezone.utc
    assert normalized.year == 2022


def test_09_temperature_mapping():
    """9. Test temperature and feels_like mapping to Celsius in canonical event."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
        source_timestamp=datetime(2022, 8, 30, 14, 43, 12, tzinfo=timezone.utc),
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    attrs = canonical.normalized_attributes
    assert attrs["temperature_celsius"] == 18.5
    assert attrs["feels_like_celsius"] == 18.1
    assert attrs["temp_min_celsius"] == 17.0
    assert attrs["temp_max_celsius"] == 20.0


def test_10_precipitation_mapping_when_present():
    """10. Test precipitation (rain/snow) mapping when present."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_SINGAPORE_RAIN,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    attrs = canonical.normalized_attributes
    assert attrs["rain_1h_mm"] == 8.5
    assert attrs["rain_3h_mm"] == 15.0


def test_11_wind_mapping_when_present():
    """11. Test wind speed, direction, and gust mapping when present."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    attrs = canonical.normalized_attributes
    assert attrs["wind_speed_mps"] == 3.6
    assert attrs["wind_deg"] == 210
    assert attrs["wind_gust_mps"] == 5.2


def test_12_pressure_mapping_when_present():
    """12. Test barometric pressure mapping in hPa."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    assert canonical.normalized_attributes["pressure_hpa"] == 1016


def test_13_humidity_mapping_when_present():
    """13. Test humidity percentage mapping."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    assert canonical.normalized_attributes["humidity_percent"] == 55


def test_14_visibility_mapping_when_present():
    """14. Test visibility mapping in meters."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    assert canonical.normalized_attributes["visibility_meters"] == 10000.0


def test_15_weather_condition_mapping():
    """15. Test weather condition id, main, description, and icon mapping."""
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    attrs = canonical.normalized_attributes
    assert attrs["weather_id"] == 800
    assert attrs["weather_main"] == "Clear"
    assert attrs["weather_description"] == "clear sky"
    assert attrs["weather_icon"] == "01d"


def test_16_missing_optional_fields():
    """16. Test that missing optional fields (rain, snow, gust, visibility) parse cleanly."""
    minimal_payload = {
        "coord": {"lat": 10.0, "lon": 20.0},
        "weather": [{"id": 801, "main": "Clouds"}],
        "main": {"temp": 22.0},
        "dt": 1661870592,
    }
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=minimal_payload,
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    attrs = canonical.normalized_attributes
    assert attrs["temperature_celsius"] == 22.0
    assert "rain_1h_mm" not in attrs
    assert "wind_gust_mps" not in attrs
    assert "visibility_meters" not in attrs


def test_17_malformed_provider_response():
    """17. Test that malformed JSON response raises ProviderResponseError."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"INVALID_JSON{", request=req)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderResponseError) as exc:
        adapter.fetch(latitude=51.5, longitude=-0.1)
    assert "malformed" in str(exc.value).lower()


def test_18_authentication_failure():
    """18. Test that HTTP 401/403 raises non-retriable ProviderAuthenticationError."""
    client = create_mock_client(
        status_code=401,
        json_data={"cod": 401, "message": "Invalid API key."},
    )
    adapter = OpenWeatherAdapter(secret="bad_key", http_client=client)

    with pytest.raises(ProviderAuthenticationError) as exc:
        adapter.fetch(latitude=51.5, longitude=-0.1)
    assert exc.value.status_code == 401
    assert exc.value.retriable is False


def test_19_rate_limit_response():
    """19. Test that HTTP 429 raises retriable ProviderRateLimitError with Retry-After."""
    client = create_mock_client(
        status_code=429,
        json_data={"cod": 429, "message": "Quota exceeded"},
        headers={"Retry-After": "45"},
    )
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderRateLimitError) as exc:
        adapter.fetch(latitude=51.5, longitude=-0.1)
    assert exc.value.retriable is True
    assert exc.value.retry_after == 45.0


def test_20_transient_provider_failure():
    """20. Test that HTTP 502/503 raises retriable ProviderResponseError."""
    client = create_mock_client(status_code=503, json_data={"message": "Service Unavailable"})
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    with pytest.raises(ProviderResponseError) as exc:
        adapter.fetch(latitude=51.5, longitude=-0.1)
    assert exc.value.status_code == 503
    assert exc.value.retriable is True


def test_21_retry_behavior():
    """21. Test that transient failures are retried according to RetryPolicy."""
    calls = [0]

    def flaky_handler(req: httpx.Request) -> httpx.Response:
        calls[0] += 1
        if calls[0] < 3:
            return httpx.Response(502, json={"message": "Bad Gateway"}, request=req)
        return httpx.Response(200, json=SAMPLE_LONDON_WEATHER, request=req)

    client = httpx.Client(transport=httpx.MockTransport(flaky_handler))
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)
    retry_policy = RetryPolicy(config=RetryConfig(max_retries=3, initial_delay_seconds=0.01))

    # Test execution via retry policy
    batch = retry_policy.execute(
        lambda: adapter.fetch(latitude=51.5074, longitude=-0.1278),
        sleep_func=lambda s: None,
    )
    assert calls[0] == 3
    assert len(batch.events) == 1


def test_22_retry_after_behavior():
    """22. Test that RetryPolicy respects Retry-After delay when signaled."""
    cfg = RetryConfig(max_retries=2, initial_delay_seconds=1.0, max_delay_seconds=60.0)
    delay = RetryPolicy.compute_delay(attempt=0, config=cfg, retry_after=15.0)
    assert delay == 15.0


def test_23_deterministic_idempotency():
    """23. Test deterministic SHA-256 fingerprint generation for identical weather observations."""
    fp1 = OpenWeatherAdapter.compute_observation_fingerprint(
        latitude=51.50741,
        longitude=-0.12781,
        observation_timestamp=1661870592,
        weather_id=800,
        org_id="org_default",
    )
    # Slight micro-coordinate variation rounds to same 4-decimal precision
    fp2 = OpenWeatherAdapter.compute_observation_fingerprint(
        latitude=51.50744,
        longitude=-0.12784,
        observation_timestamp=1661870592,
        weather_id=800,
        org_id="org_default",
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_24_duplicate_observation_handling():
    """24. Test that repeated ingestion of identical observation is deduplicated."""
    idempotency = IdempotencyEngine()
    client = create_mock_client(status_code=200, json_data=SAMPLE_LONDON_WEATHER)
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client, idempotency_engine=idempotency)

    batch1 = adapter.fetch(latitude=51.5074, longitude=-0.1278)
    event1 = batch1.events[0]

    # First recording is unique
    is_unique_1, fp1 = idempotency.check_and_record(event1)
    assert is_unique_1 is True

    # Second recording is duplicate
    batch2 = adapter.fetch(latitude=51.5074, longitude=-0.1278)
    event2 = batch2.events[0]
    is_unique_2, fp2 = idempotency.check_and_record(event2)
    assert is_unique_2 is False
    assert fp1 == fp2


def test_25_canonical_event_generation():
    """25. Test full conversion of OpenWeather RawEvent to CanonicalExternalEvent."""
    raw = RawEvent(
        provider_name="openweather",
        provider_event_id="ow_2643743_1661870592",
        raw_payload=SAMPLE_LONDON_WEATHER,
        metadata={"route_id": "route_lon_01"},
    )
    normalizer = OpenWeatherNormalizer()
    canonical = normalizer.normalize(raw)

    assert canonical.provider == "openweather"
    assert canonical.source_event_id == "ow_2643743_1661870592"
    assert canonical.latitude == 51.5074
    assert canonical.longitude == -0.1278
    assert canonical.location.location_name == "London"
    assert canonical.location.country_code == "GB"
    assert canonical.correlation.route_id == "route_lon_01"


def test_26_event_quality_behavior():
    """26. Test EventQuality behavior (VALID, PARTIAL, INVALID)."""
    normalizer = OpenWeatherNormalizer()

    # 1. Valid: has coordinates and entity correlation
    raw_valid = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
        metadata={"shipment_id": "shp_001"},
    )
    canon_valid = normalizer.normalize(raw_valid)
    assert canon_valid.quality == EventQuality.VALID

    # 2. Partial: has valid coordinates but no correlation
    raw_partial = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
        metadata={},
    )
    canon_partial = normalizer.normalize(raw_partial)
    assert canon_partial.quality == EventQuality.PARTIAL

    # 3. Invalid: coordinates out of geographic bounds
    bad_payload = dict(SAMPLE_LONDON_WEATHER)
    bad_payload["coord"] = {"lat": 150.0, "lon": 0.0}
    raw_invalid = RawEvent(
        provider_name="openweather",
        raw_payload=bad_payload,
    )
    canon_invalid = normalizer.normalize(raw_invalid)
    assert canon_invalid.quality == EventQuality.INVALID


def test_27_normal_weather_does_not_become_critical_risk():
    """27. Test that normal ambient weather stays INFO/LOW and never becomes CRITICAL risk."""
    normalizer = OpenWeatherNormalizer()
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    canonical = normalizer.normalize(raw)

    # 18.5°C, clear sky, 3.6 m/s wind -> INFO
    assert canonical.severity == EventSeverity.INFO
    assert canonical.severity not in (EventSeverity.HIGH, EventSeverity.CRITICAL)
    assert canonical.event_type == CanonicalEventType.CUSTOM


def test_28_alert_behavior_according_to_supported_capability():
    """28. Test alert handling for One Call 3.0 alerts and lack of alerts in 2.5."""
    normalizer = OpenWeatherNormalizer()

    # A. One Call 3.0 alert payload
    raw_alert = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_ONE_CALL_ALERT,
    )
    canon_alert = normalizer.normalize(raw_alert)
    assert canon_alert.event_type == CanonicalEventType.WEATHER_ALERT
    assert canon_alert.severity == EventSeverity.CRITICAL
    assert canon_alert.normalized_attributes["alert_event"] == "Tornado Warning"
    assert canon_alert.normalized_attributes["alert_sender"] == "NWS Norman OK"

    # B. Current Weather 2.5 response without alerts does not fabricate alert
    raw_25 = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_LONDON_WEATHER,
    )
    canon_25 = normalizer.normalize(raw_25)
    assert canon_25.event_type != CanonicalEventType.WEATHER_ALERT
    assert "alert_event" not in canon_25.normalized_attributes


def test_29_provider_health_check():
    """29. Test provider health check (HEALTHY, UNCONFIGURED, UNHEALTHY, DEGRADED)."""
    # Healthy
    client_ok = create_mock_client(200, json_data=SAMPLE_LONDON_WEATHER)
    adapter_ok = OpenWeatherAdapter(secret="valid_key", http_client=client_ok)
    res_ok = adapter_ok.health_check()
    assert res_ok.status == ProviderHealthStatus.HEALTHY

    # Unconfigured
    adapter_unconf = OpenWeatherAdapter(
        config=ProviderConfig(provider_name="openweather", provider_type=ProviderType.WEATHER, secret_ref=None),
        secret=None,
    )
    res_unconf = adapter_unconf.health_check()
    assert res_unconf.status == ProviderHealthStatus.UNCONFIGURED

    # Unhealthy (Auth failure)
    client_401 = create_mock_client(401, json_data={"message": "Invalid API key"})
    adapter_401 = OpenWeatherAdapter(secret="bad_key", http_client=client_401)
    res_401 = adapter_401.health_check()
    assert res_401.status == ProviderHealthStatus.UNHEALTHY

    # Degraded (Rate limit)
    client_429 = create_mock_client(429, json_data={"message": "Quota exceeded"})
    adapter_429 = OpenWeatherAdapter(secret="key", http_client=client_429)
    res_429 = adapter_429.health_check()
    assert res_429.status == ProviderHealthStatus.DEGRADED


def test_30_raw_payload_preservation():
    """30. Test that raw provider response is preserved verbatim in RawEvent."""
    client = create_mock_client(200, json_data=SAMPLE_LONDON_WEATHER)
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    batch = adapter.fetch(latitude=51.5074, longitude=-0.1278)
    raw_event = batch.events[0]

    assert raw_event.raw_payload["coord"]["lat"] == 51.5074
    assert raw_event.raw_payload["main"]["temp"] == 18.5
    assert raw_event.raw_payload["dt"] == 1661870592


def test_31_secret_redaction():
    """31. Test that API keys and appid query parameter are never stored in payload or logs."""
    client = create_mock_client(200, json_data=SAMPLE_LONDON_WEATHER)
    adapter = OpenWeatherAdapter(secret="secret_abc_12345", http_client=client)

    batch = adapter.fetch(latitude=51.5074, longitude=-0.1278)
    raw = batch.events[0]

    # Raw payload must not contain appid or secret
    assert "appid" not in raw.raw_payload
    assert "secret_abc_12345" not in json.dumps(raw.raw_payload)

    # Sanitize check on URL
    sanitized_url = adapter._sanitize_url_for_logging("https://api.openweathermap.org/data/2.5/weather?lat=1&lon=2&appid=secret_abc_12345")
    assert "secret_abc_12345" not in sanitized_url
    assert "appid=[REDACTED]" in sanitized_url


def test_32_scheduler_integration():
    """32. Test that OpenWeather polling jobs integrate cleanly with IngestionScheduler."""
    scheduler = InMemoryIngestionScheduler()
    job = ScheduledIngestionJob(
        job_id="ow_poll_singapore",
        provider_name="openweather",
        cron_or_interval="*/15 * * * *",
        enabled=True,
        parameters={"latitude": 1.3521, "longitude": 103.8198},
    )
    scheduler.register_job(job)

    retrieved = scheduler.get_job("ow_poll_singapore")
    assert retrieved is not None
    assert retrieved.parameters["latitude"] == 1.3521
    assert len(scheduler.list_jobs(enabled_only=True)) == 1


def test_33_observability_metadata():
    """33. Test that IngestionService records complete observability and audit metadata."""
    client = create_mock_client(200, json_data=SAMPLE_LONDON_WEATHER)
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client)

    service = IngestionService()
    # Register adapter class with test client
    default_provider_registry.register(
        type("MockOWAdapter", (OpenWeatherAdapter,), {"__init__": lambda self, **kwargs: OpenWeatherAdapter.__init__(self, secret="test_key", http_client=client)}),
        overwrite=True,
    )

    result = service.ingest(
        provider_name="openweather",
        parameters={"latitude": 51.5074, "longitude": -0.1278},
        correlation_id="corr_test_001",
    )

    assert result.status == IngestionStatus.SUCCESS
    meta = result.metadata
    assert meta.provider == "openweather"
    assert meta.correlation_id == "corr_test_001"
    assert meta.items_fetched == 1
    assert meta.items_ingested == 1
    assert meta.duration_ms >= 0.0


def test_34_tenant_org_isolation():
    """34. Test that tenant organization_id is isolated in idempotency and raw storage."""
    idempotency = IdempotencyEngine()
    client = create_mock_client(200, json_data=SAMPLE_LONDON_WEATHER)
    adapter = OpenWeatherAdapter(secret="test_key", http_client=client, idempotency_engine=idempotency)

    # Ingest for Org A
    batch_a = adapter.fetch(latitude=51.5074, longitude=-0.1278, organization_id="org_alpha")
    event_a = batch_a.events[0]
    unique_a, fp_a = idempotency.check_and_record(event_a, organization_id="org_alpha")
    assert unique_a is True

    # Ingest same observation for Org B
    batch_b = adapter.fetch(latitude=51.5074, longitude=-0.1278, organization_id="org_beta")
    event_b = batch_b.events[0]
    unique_b, fp_b = idempotency.check_and_record(event_b, organization_id="org_beta")
    # Must be considered unique because Org B is isolated from Org A
    assert unique_b is True
    assert fp_a != fp_b


def test_35_severe_weather_thunderstorm_mapping():
    """35. Test that severe thunderstorm condition codes map to STORM and HIGH severity."""
    normalizer = OpenWeatherNormalizer()
    raw = RawEvent(
        provider_name="openweather",
        raw_payload=SAMPLE_MIAMI_STORM,
    )
    canonical = normalizer.normalize(raw)

    assert canonical.event_type == CanonicalEventType.STORM
    assert canonical.severity == EventSeverity.HIGH
    assert canonical.normalized_attributes["wind_speed_mps"] == 22.5
    assert canonical.normalized_attributes["rain_1h_mm"] == 35.0
