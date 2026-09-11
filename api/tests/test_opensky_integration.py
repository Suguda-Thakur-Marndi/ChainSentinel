"""Comprehensive unit test suite for RiskWise 2.0 Phase 5 Step 6: Air / OpenSky Integration.

All tests are 100% self-contained and execute against mocked HTTP endpoints (zero live network calls).

Covers all 57 checklist requirements:
 1. adapter initialization
 2. provider capability inspection
 3. configuration loading
 4. missing client ID
 5. missing client secret
 6. OAuth token request
 7. OAuth token parsing
 8. token caching
 9. token expiration
10. token refresh
11. authentication failure
12. successful /states/all request
13. bounding-box request
14. ICAO24 filtering
15. invalid latitude
16. invalid longitude
17. invalid bounding box
18. timestamp normalization
19. time_position normalization
20. last_contact normalization
21. ICAO24 mapping
22. callsign mapping
23. origin-country mapping
24. longitude mapping
25. latitude mapping
26. barometric altitude mapping
27. geometric altitude mapping
28. velocity mapping
29. true-track mapping
30. vertical-rate mapping
31. on-ground mapping
32. squawk mapping
33. position-source mapping
34. category mapping
35. nullable fields
36. malformed provider response
37. HTTP 401 recovery
38. HTTP 403 handling
39. HTTP 429 handling
40. Retry-After handling
41. transient 5xx retry
42. deterministic idempotency
43. duplicate observation handling
44. consecutive observation preservation
45. canonical event generation
46. EventQuality behavior
47. entity correlation
48. unresolved shipment correlation
49. valid shipment correlation
50. ShipmentEventBridge behavior
51. raw payload preservation
52. secret redaction
53. health check
54. scheduler integration
55. observability metadata
56. tenant/org isolation
57. unsupported field handling
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app.integrations import (
    AuthMode,
    BaseEventNormalizer,
    CanonicalEventType,
    CanonicalExternalEvent,
    CoordinateValidator,
    DEFAULT_OPENSKY_BASE_URL,
    DEFAULT_OPENSKY_TOKEN_URL,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
    IdempotencyEngine,
    InMemoryCanonicalEventStorage,
    InMemoryIngestionScheduler,
    InMemoryRawEventStorage,
    IngestionBatch,
    IngestionService,
    NormalizationPipeline,
    OpenSkyAdapter,
    OpenSkyBoundingBox,
    OpenSkyNormalizer,
    OpenSkyOAuthTokenManager,
    OpenSkyStateVector,
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
    ProviderValidationError,
    RateLimitConfig,
    RawEvent,
    RetryConfig,
    ScheduledIngestionJob,
    SecretResolver,
    ShipmentEventBridge,
    TimestampNormalizer,
    create_opensky_polling_job,
    default_provider_registry,
)


# =====================================================================
# Mock Data & Transport Builders
# =====================================================================

SAMPLE_TOKEN_RESPONSE = {
    "access_token": "mock_opensky_jwt_token_xyz123",
    "expires_in": 1800,
    "refresh_expires_in": 0,
    "token_type": "Bearer",
    "not-before-policy": 0,
    "scope": "email profile",
}

# Real-world OpenSky state array representation
# [0: icao24, 1: callsign, 2: origin_country, 3: time_position, 4: last_contact,
#  5: lon, 6: lat, 7: baro_alt, 8: on_ground, 9: velocity, 10: true_track,
#  11: vertical_rate, 12: sensors, 13: geo_alt, 14: squawk, 15: spi,
#  16: position_source, 17: category]
SAMPLE_STATE_LUFTHANSA = [
    "3c6444",        # 0: icao24
    "DLH123  ",      # 1: callsign (with trailing whitespace)
    "Germany",       # 2: origin_country
    1725800000,      # 3: time_position
    1725800005,      # 4: last_contact
    8.5678,          # 5: longitude
    50.0379,         # 6: latitude
    3200.4,          # 7: baro_altitude (meters)
    False,           # 8: on_ground
    180.5,           # 9: velocity (m/s)
    245.0,           # 10: true_track (degrees)
    -5.2,            # 11: vertical_rate (m/s)
    None,            # 12: sensors
    3310.0,          # 13: geo_altitude (meters)
    "1000",          # 14: squawk
    False,           # 15: spi
    0,               # 16: position_source (0=ADS-B)
    4,               # 17: category (Large)
]

SAMPLE_STATE_GROUND = [
    "400a0c",
    "BAW456  ",
    "United Kingdom",
    1725800010,
    1725800012,
    -0.4614,
    51.4700,
    25.0,
    True,            # on_ground = True
    5.0,
    90.0,
    0.0,
    None,
    26.0,
    "7000",
    False,
    0,
    5,
]

SAMPLE_STATE_EMERGENCY = [
    "a808c1",
    "AAL789  ",
    "United States",
    1725800020,
    1725800022,
    -73.7781,
    40.6413,
    1500.0,
    False,
    140.0,
    180.0,
    -8.5,
    None,
    1550.0,
    "7700",          # Squawk 7700 = General Emergency
    True,
    0,
    4,
]

SAMPLE_STATE_RADIO_FAIL = [
    "4b1812",
    "SWR321  ",
    "Switzerland",
    1725800030,
    1725800032,
    8.5417,
    47.4582,
    2500.0,
    False,
    160.0,
    45.0,
    2.0,
    None,
    2550.0,
    "7600",          # Squawk 7600 = Radio Failure
    False,
    0,
    3,
]

SAMPLE_STATE_HIJACK = [
    "710245",
    "THY999  ",
    "Turkey",
    1725800040,
    1725800042,
    28.8146,
    40.9769,
    4000.0,
    False,
    200.0,
    270.0,
    0.0,
    None,
    4100.0,
    "7500",          # Squawk 7500 = Unlawful Interference
    False,
    0,
    4,
]

SAMPLE_STATE_NULLABLE = [
    "3c6499",
    None,            # callsign null
    "Germany",
    None,            # time_position null
    1725800008,
    None,            # longitude null
    None,            # latitude null
    None,            # baro_alt null
    False,
    None,            # velocity null
    None,            # true_track null
    None,            # vertical_rate null
    None,
    None,            # geo_alt null
    None,            # squawk null
    False,
    0,
    None,
]


def make_mock_opensky_client(
    token_status: int = 200,
    token_data: Optional[Dict[str, Any]] = None,
    states_status: int = 200,
    states_data: Optional[Dict[str, Any]] = None,
    states_headers: Optional[Dict[str, str]] = None,
    custom_handler: Optional[Callable[[httpx.Request], httpx.Response]] = None,
) -> httpx.Client:
    """Create an isolated in-memory HTTP client with mock transport."""
    resolved_token_data = token_data if token_data is not None else SAMPLE_TOKEN_RESPONSE
    resolved_states_data = (
        states_data
        if states_data is not None
        else {"time": 1725800000, "states": [SAMPLE_STATE_LUFTHANSA]}
    )

    def default_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        # Route 1: OAuth2 token endpoint
        if "protocol/openid-connect/token" in url_str:
            if token_status != 200:
                return httpx.Response(
                    status_code=token_status,
                    content=b'{"error": "invalid_client", "error_description": "Bad credentials"}',
                    headers={"Content-Type": "application/json"},
                    request=request,
                )
            return httpx.Response(
                status_code=200,
                content=json.dumps(resolved_token_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                request=request,
            )

        # Route 2: States endpoint
        if "states/all" in url_str:
            resp_headers = dict(states_headers or {})
            if "Content-Type" not in resp_headers:
                resp_headers["Content-Type"] = "application/json"

            content = (
                json.dumps(resolved_states_data).encode("utf-8")
                if resolved_states_data is not None
                else b""
            )
            return httpx.Response(
                status_code=states_status,
                content=content,
                headers=resp_headers,
                request=request,
            )

        # Fallback 404
        return httpx.Response(status_code=404, content=b"Not Found", request=request)

    handler = custom_handler or default_handler
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


# =====================================================================
# Tests
# =====================================================================

def test_01_adapter_initialization():
    """1. Test adapter initialization, provider name, and type."""
    adapter = OpenSkyAdapter(client_id="test_id", secret="test_secret")
    assert adapter.provider_name == "opensky"
    assert adapter.provider_type == ProviderType.AIR
    assert adapter.capabilities.supports_polling is True


def test_02_provider_capability_inspection():
    """2. Test provider capability inspection."""
    adapter = OpenSkyAdapter(client_id="test_id", secret="test_secret")
    caps = adapter.capabilities
    assert caps.supports_polling is True
    assert caps.supports_webhook is False
    assert caps.supports_batch is True
    assert caps.supports_health_check is True
    assert "air" in caps.supported_modalities
    assert "adsb" in caps.supported_modalities
    assert "state_vector" in caps.supported_modalities
    assert "aircraft" in caps.supported_entities


def test_03_configuration_loading():
    """3. Test configuration loading and default settings."""
    adapter = OpenSkyAdapter(client_id="test_id", secret="test_secret")
    assert adapter.config.provider_name == "opensky"
    assert adapter.config.auth_mode == AuthMode.OAUTH2
    assert adapter.config.rate_limit.requests_per_minute == 60
    assert adapter.config.retry.max_retries == 3


def test_04_missing_client_id(monkeypatch):
    """4. Test missing client ID raises ProviderConfigurationError."""
    monkeypatch.delenv("OPENSKY_CLIENT_ID", raising=False)
    cfg = ProviderConfig(
        provider_name="opensky",
        provider_type=ProviderType.AIR,
        extra_settings={"client_id_ref": "env:OPENSKY_CLIENT_ID"},
    )
    adapter = OpenSkyAdapter(config=cfg, secret="valid_secret")
    with pytest.raises(ProviderConfigurationError) as exc_info:
        adapter.resolve_client_id()
    assert "Missing OpenSky client ID" in str(exc_info.value)


def test_05_missing_client_secret(monkeypatch):
    """5. Test missing client secret raises ProviderConfigurationError."""
    monkeypatch.delenv("OPENSKY_CLIENT_SECRET", raising=False)
    cfg = ProviderConfig(
        provider_name="opensky",
        provider_type=ProviderType.AIR,
        secret_ref="env:OPENSKY_CLIENT_SECRET",
    )
    adapter = OpenSkyAdapter(config=cfg, client_id="valid_client_id")
    with pytest.raises(ProviderConfigurationError) as exc_info:
        adapter.resolve_client_secret()
    assert "Missing OpenSky client secret" in str(exc_info.value)


def test_06_oauth_token_request():
    """6. Test OAuth token request formats form-urlencoded body correctly."""
    captured_request: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["method"] = request.method
        captured_request["body"] = request.read().decode("utf-8")
        captured_request["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(
            status_code=200,
            content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token_mgr = OpenSkyOAuthTokenManager(
        client_id="my_client_id",
        client_secret="my_client_secret",
        http_client=client,
    )
    token = token_mgr.get_token()

    assert token == "mock_opensky_jwt_token_xyz123"
    assert captured_request["method"] == "POST"
    assert "grant_type=client_credentials" in captured_request["body"]
    assert "client_id=my_client_id" in captured_request["body"]
    assert "client_secret=my_client_secret" in captured_request["body"]
    assert "application/x-www-form-urlencoded" in captured_request["content_type"]


def test_07_oauth_token_parsing():
    """7. Test OAuth token parsing extracts token and expiration correctly."""
    client = make_mock_opensky_client(
        token_data={"access_token": "token_abc_789", "expires_in": 1200, "token_type": "Bearer"}
    )
    token_mgr = OpenSkyOAuthTokenManager(
        client_id="cid", client_secret="csec", http_client=client
    )
    token = token_mgr.get_token()
    assert token == "token_abc_789"
    assert token_mgr.is_token_valid() is True


def test_08_token_caching():
    """8. Test token caching avoids redundant network requests."""
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            status_code=200,
            content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token_mgr = OpenSkyOAuthTokenManager(
        client_id="cid", client_secret="csec", http_client=client
    )
    # First call acquires token
    t1 = token_mgr.get_token()
    # Second call should use cached token
    t2 = token_mgr.get_token()

    assert t1 == t2
    assert request_count == 1


def test_09_token_expiration():
    """9. Test token expiration behavior."""
    client = make_mock_opensky_client()
    token_mgr = OpenSkyOAuthTokenManager(
        client_id="cid",
        client_secret="csec",
        http_client=client,
        refresh_margin_seconds=10.0,
    )
    token_mgr.get_token()
    assert token_mgr.is_token_valid() is True

    # Artificially set _expires_at in the past
    token_mgr._expires_at = time.monotonic() - 5.0
    assert token_mgr.is_token_valid() is False


def test_10_token_refresh():
    """10. Test token refresh when expired or forced."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            status_code=200,
            content=json.dumps({
                "access_token": f"token_v{call_count}",
                "expires_in": 1800,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token_mgr = OpenSkyOAuthTokenManager(
        client_id="cid", client_secret="csec", http_client=client
    )
    t1 = token_mgr.get_token()
    assert t1 == "token_v1"

    # Force refresh
    t2 = token_mgr.get_token(force_refresh=True)
    assert t2 == "token_v2"
    assert call_count == 2


def test_11_authentication_failure():
    """11. Test authentication failure raises ProviderAuthenticationError."""
    client = make_mock_opensky_client(token_status=401)
    token_mgr = OpenSkyOAuthTokenManager(
        client_id="bad_id", client_secret="bad_secret", http_client=client
    )
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        token_mgr.get_token()
    assert exc_info.value.status_code == 401


def test_12_successful_states_all_request():
    """12. Test successful /states/all request ingestion."""
    client = make_mock_opensky_client(
        states_data={"time": 1725800000, "states": [SAMPLE_STATE_LUFTHANSA, SAMPLE_STATE_GROUND]}
    )
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    batch = adapter.fetch()

    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "opensky"
    assert len(batch.events) == 2
    assert batch.events[0].raw_payload["icao24"] == "3c6444"
    assert batch.events[1].raw_payload["icao24"] == "400a0c"


def test_13_bounding_box_request():
    """13. Test bounding box filter generates lamin, lomin, lamax, lomax query params."""
    captured_params: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "protocol/openid-connect/token" in url_str:
            return httpx.Response(status_code=200, content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"), request=request)
        if "states/all" in url_str:
            captured_params.update(dict(request.url.params))
            return httpx.Response(status_code=200, content=b'{"time": 1725800000, "states": []}', request=request)
        return httpx.Response(status_code=404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    bbox = OpenSkyBoundingBox(
        min_latitude=45.0,
        min_longitude=5.0,
        max_latitude=55.0,
        max_longitude=15.0,
    )
    adapter.fetch(bounding_box=bbox)

    assert float(captured_params["lamin"]) == 45.0
    assert float(captured_params["lomin"]) == 5.0
    assert float(captured_params["lamax"]) == 55.0
    assert float(captured_params["lomax"]) == 15.0


def test_14_icao24_filtering():
    """14. Test ICAO24 filtering with single and multiple aircraft transponders."""
    captured_icaos: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "protocol/openid-connect/token" in url_str:
            return httpx.Response(status_code=200, content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"), request=request)
        if "states/all" in url_str:
            captured_icaos.extend(request.url.params.get_list("icao24"))
            return httpx.Response(status_code=200, content=b'{"time": 1725800000, "states": []}', request=request)
        return httpx.Response(status_code=404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    adapter.fetch(icao24=["3c6444", "400a0c"])

    assert captured_icaos == ["3c6444", "400a0c"]


def test_15_invalid_latitude():
    """15. Test invalid latitude rejected before HTTP call."""
    with pytest.raises(Exception):
        OpenSkyBoundingBox(min_latitude=95.0, min_longitude=0.0, max_latitude=50.0, max_longitude=10.0)


def test_16_invalid_longitude():
    """16. Test invalid longitude rejected before HTTP call."""
    with pytest.raises(Exception):
        OpenSkyBoundingBox(min_latitude=40.0, min_longitude=-190.0, max_latitude=50.0, max_longitude=10.0)


def test_17_invalid_bounding_box():
    """17. Test min_latitude > max_latitude rejected with ProviderValidationError."""
    with pytest.raises(ProviderValidationError) as exc_info:
        OpenSkyBoundingBox(min_latitude=55.0, min_longitude=0.0, max_latitude=45.0, max_longitude=10.0)
    assert "min_latitude" in str(exc_info.value)


def test_18_timestamp_normalization():
    """18. Test timestamp normalization to timezone-aware UTC datetime."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "time_position": 1725800000, "last_contact": 1725800005},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.event_timestamp.tzinfo is not None
    assert canonical.event_timestamp == datetime.fromtimestamp(1725800000, tz=timezone.utc)


def test_19_time_position_normalization():
    """19. Test time_position normalization sets observed_at in UTC."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.observed_at == datetime.fromtimestamp(1725800000, tz=timezone.utc)


def test_20_last_contact_normalization():
    """20. Test last_contact normalization when time_position is None."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "time_position": None, "last_contact": 1725800010},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.event_timestamp == datetime.fromtimestamp(1725800010, tz=timezone.utc)
    assert canonical.observed_at is None


def test_21_icao24_mapping():
    """21. Test ICAO24 mapping into correlation and normalized attributes."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.correlation.custom_identifiers["icao24"] == "3c6444"
    assert canonical.normalized_attributes["icao24"] == "3c6444"


def test_22_callsign_mapping():
    """22. Test callsign stripped of whitespace and mapped."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "callsign": "DLH123  ", "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.correlation.custom_identifiers["callsign"] == "DLH123"
    assert canonical.normalized_attributes["callsign"] == "DLH123"


def test_23_origin_country_mapping():
    """23. Test origin country mapping."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "origin_country": "Germany", "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["origin_country"] == "Germany"
    assert canonical.correlation.custom_identifiers["origin_country"] == "Germany"


def test_24_longitude_mapping():
    """24. Test longitude mapping into EventLocation."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "longitude": 8.5678, "latitude": 50.0379, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.longitude == 8.5678


def test_25_latitude_mapping():
    """25. Test latitude mapping into EventLocation."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "longitude": 8.5678, "latitude": 50.0379, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.latitude == 50.0379


def test_26_barometric_altitude_mapping():
    """26. Test barometric altitude mapping in meters."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "baro_altitude": 3200.4, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["baro_altitude_meters"] == 3200.4


def test_27_geometric_altitude_mapping():
    """27. Test geometric altitude mapping in meters."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "geo_altitude": 3310.0, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["geo_altitude_meters"] == 3310.0


def test_28_velocity_mapping():
    """28. Test velocity mapping in m/s ground speed."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "velocity": 180.5, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["velocity_mps"] == 180.5


def test_29_true_track_mapping():
    """29. Test true track mapping in degrees clockwise from north."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "true_track": 245.0, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["true_track_degrees"] == 245.0


def test_30_vertical_rate_mapping():
    """30. Test vertical rate mapping in m/s."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "vertical_rate": -5.2, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["vertical_rate_mps"] == -5.2


def test_31_on_ground_mapping():
    """31. Test on_ground mapping sets status to ON_GROUND or AIRBORNE."""
    normalizer = OpenSkyNormalizer()
    raw_ground = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "on_ground": True, "time_position": 1725800000},
    )
    raw_air = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "on_ground": False, "time_position": 1725800000},
    )
    assert normalizer.normalize(raw_ground).status == "ON_GROUND"
    assert normalizer.normalize(raw_air).status == "AIRBORNE"


def test_32_squawk_mapping():
    """32. Test squawk code mapping and emergency elevation (7700, 7600, 7500)."""
    normalizer = OpenSkyNormalizer()

    # Normal squawk -> INFO
    raw_norm = RawEvent(provider_name="opensky", raw_payload={"icao24": "3c6444", "squawk": "1000", "time_position": 1725800000})
    norm_event = normalizer.normalize(raw_norm)
    assert norm_event.severity == EventSeverity.INFO

    # 7700 General Emergency -> CRITICAL
    raw_7700 = RawEvent(provider_name="opensky", raw_payload={"icao24": "3c6444", "squawk": "7700", "time_position": 1725800000})
    event_7700 = normalizer.normalize(raw_7700)
    assert event_7700.severity == EventSeverity.CRITICAL
    assert event_7700.status == "EMERGENCY"

    # 7600 Radio Failure -> HIGH
    raw_7600 = RawEvent(provider_name="opensky", raw_payload={"icao24": "3c6444", "squawk": "7600", "time_position": 1725800000})
    event_7600 = normalizer.normalize(raw_7600)
    assert event_7600.severity == EventSeverity.HIGH
    assert event_7600.status == "RADIO_FAILURE"

    # 7500 Hijacking -> CRITICAL
    raw_7500 = RawEvent(provider_name="opensky", raw_payload={"icao24": "3c6444", "squawk": "7500", "time_position": 1725800000})
    event_7500 = normalizer.normalize(raw_7500)
    assert event_7500.severity == EventSeverity.CRITICAL
    assert event_7500.status == "UNLAWFUL_INTERFERENCE"


def test_33_position_source_mapping():
    """33. Test position source code mapping."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "position_source": 0, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["position_source"] == 0


def test_34_category_mapping():
    """34. Test emitter category mapping."""
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "category": 4, "time_position": 1725800000},
    )
    canonical = normalizer.normalize(raw)
    assert canonical.normalized_attributes["category"] == 4


def test_35_nullable_fields():
    """35. Test nullable fields handling without fabricating dummy values."""
    vector = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_NULLABLE)
    assert vector.callsign is None
    assert vector.longitude is None
    assert vector.latitude is None
    assert vector.baro_altitude is None
    assert vector.velocity is None

    payload = vector.to_raw_payload()
    normalizer = OpenSkyNormalizer()
    raw = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical = normalizer.normalize(raw)

    assert canonical.location is None
    assert canonical.normalized_attributes["velocity_mps"] is None
    assert canonical.quality == EventQuality.PARTIAL


def test_36_malformed_provider_response():
    """36. Test malformed provider response raises ProviderResponseError."""
    client = make_mock_opensky_client(states_data=None)
    # Send non-JSON body
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "protocol/openid-connect/token" in url_str:
            return httpx.Response(status_code=200, content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"), request=request)
        if "states/all" in url_str:
            return httpx.Response(status_code=200, content=b"invalid non json string", request=request)
        return httpx.Response(status_code=404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    with pytest.raises(ProviderResponseError):
        adapter.fetch()


def test_37_http_401_recovery():
    """37. Test HTTP 401 triggers token invalidation, refresh, and successful retry."""
    states_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal states_attempts
        url_str = str(request.url)
        if "protocol/openid-connect/token" in url_str:
            return httpx.Response(status_code=200, content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"), request=request)
        if "states/all" in url_str:
            states_attempts += 1
            if states_attempts == 1:
                return httpx.Response(status_code=401, content=b'{"error": "Unauthorized"}', request=request)
            return httpx.Response(
                status_code=200,
                content=json.dumps({"time": 1725800000, "states": [SAMPLE_STATE_LUFTHANSA]}).encode("utf-8"),
                request=request,
            )
        return httpx.Response(status_code=404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    batch = adapter.fetch()

    assert len(batch.events) == 1
    assert states_attempts == 2


def test_38_http_403_handling():
    """38. Test HTTP 403 Forbidden raises ProviderAuthenticationError."""
    client = make_mock_opensky_client(states_status=403)
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    with pytest.raises(ProviderAuthenticationError) as exc_info:
        adapter.fetch()
    assert exc_info.value.status_code == 403


def test_39_http_429_handling():
    """39. Test HTTP 429 Too Many Requests raises ProviderRateLimitError."""
    client = make_mock_opensky_client(states_status=429)
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    with pytest.raises(ProviderRateLimitError):
        adapter.fetch()


def test_40_retry_after_handling():
    """40. Test Retry-After header parsing on HTTP 429."""
    client = make_mock_opensky_client(
        states_status=429,
        states_headers={"Retry-After": "30"},
    )
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    with pytest.raises(ProviderRateLimitError) as exc_info:
        adapter.fetch()
    assert exc_info.value.retry_after_seconds == 30.0


def test_41_transient_5xx_retry():
    """41. Test transient 500 error is retried by RetryPolicy and succeeds."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        url_str = str(request.url)
        if "protocol/openid-connect/token" in url_str:
            return httpx.Response(status_code=200, content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"), request=request)
        if "states/all" in url_str:
            attempts += 1
            if attempts == 1:
                return httpx.Response(status_code=503, content=b"Service Unavailable", request=request)
            return httpx.Response(
                status_code=200,
                content=json.dumps({"time": 1725800000, "states": [SAMPLE_STATE_LUFTHANSA]}).encode("utf-8"),
                request=request,
            )
        return httpx.Response(status_code=404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = ProviderConfig(
        provider_name="opensky",
        provider_type=ProviderType.AIR,
        retry=RetryConfig(max_retries=2, initial_delay_seconds=0.01),
    )
    adapter = OpenSkyAdapter(config=cfg, client_id="cid", secret="csec", http_client=client)
    batch = adapter.fetch()

    assert len(batch.events) == 1
    assert attempts == 2


def test_42_deterministic_idempotency():
    """42. Test deterministic idempotency generates identical SHA-256 fingerprint."""
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    fp1 = OpenSkyAdapter.compute_fingerprint(payload, org_id="org_123")
    fp2 = OpenSkyAdapter.compute_fingerprint(payload, org_id="org_123")
    assert fp1 == fp2
    assert len(fp1) == 64


def test_43_duplicate_observation_handling():
    """43. Test IdempotencyEngine detects duplicate observation fingerprint."""
    engine = IdempotencyEngine()
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    fp = OpenSkyAdapter.compute_fingerprint(payload, org_id="org_test")
    event = RawEvent(
        provider_name="opensky",
        provider_event_id=f"opensky:3c6444:{payload['time_position']}",
        fingerprint=fp,
        org_id="org_test",
    )

    unique1, recorded_fp = engine.check_and_record(event, organization_id="org_test")
    assert unique1 is True
    assert engine.is_duplicate(recorded_fp) is True

    unique2, _ = engine.check_and_record(event, organization_id="org_test")
    assert unique2 is False


def test_44_consecutive_observation_preservation():
    """44. Test consecutive observations with different timestamps produce different fingerprints."""
    payload1 = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    # Consecutive observation 10 seconds later
    updated_state = list(SAMPLE_STATE_LUFTHANSA)
    updated_state[3] = 1725800010  # new time_position
    updated_state[5] = 8.6000      # moved lon
    updated_state[6] = 50.0500     # moved lat
    payload2 = OpenSkyStateVector.from_raw_array(updated_state).to_raw_payload()

    fp1 = OpenSkyAdapter.compute_fingerprint(payload1)
    fp2 = OpenSkyAdapter.compute_fingerprint(payload2)

    assert fp1 != fp2


def test_45_canonical_event_generation():
    """45. Test canonical event generation conforms to CanonicalEventType.LOCATION_UPDATE."""
    normalizer = OpenSkyNormalizer()
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    raw = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical = normalizer.normalize(raw)

    assert isinstance(canonical, CanonicalExternalEvent)
    assert canonical.event_type == CanonicalEventType.LOCATION_UPDATE
    assert canonical.provider == "opensky"
    assert canonical.source_type == EventSourceType.REAL


def test_46_event_quality_behavior():
    """46. Test EventQuality behavior (VALID vs PARTIAL vs INVALID)."""
    normalizer = OpenSkyNormalizer()

    # Valid: icao24 + coords + timestamp
    raw_valid = RawEvent(
        provider_name="opensky",
        raw_payload=OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload(),
    )
    assert normalizer.normalize(raw_valid).quality == EventQuality.VALID

    # Partial: missing coords
    raw_partial = RawEvent(
        provider_name="opensky",
        raw_payload={"icao24": "3c6444", "time_position": 1725800000},
    )
    assert normalizer.normalize(raw_partial).quality == EventQuality.PARTIAL


def test_47_entity_correlation():
    """47. Test entity correlation preserves aircraft identity."""
    normalizer = OpenSkyNormalizer()
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    raw = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical = normalizer.normalize(raw)

    assert canonical.correlation.custom_identifiers["icao24"] == "3c6444"
    assert canonical.correlation.custom_identifiers["callsign"] == "DLH123"
    assert canonical.correlation.custom_identifiers["origin_country"] == "Germany"


def test_48_unresolved_shipment_correlation():
    """48. Test pure aircraft observation keeps shipment_id unresolved (None)."""
    normalizer = OpenSkyNormalizer()
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    raw = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical = normalizer.normalize(raw)

    assert canonical.correlation.shipment_id is None
    assert canonical.is_correlated is True  # True because custom_identifiers has icao24
    assert canonical.shipment_id is None


def test_49_valid_shipment_correlation():
    """49. Test explicit downstream shipment correlation binding."""
    normalizer = OpenSkyNormalizer()
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()
    payload["shipment_id"] = "shp_air_cargo_001"
    raw = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical = normalizer.normalize(raw)

    assert canonical.correlation.shipment_id == "shp_air_cargo_001"
    assert canonical.shipment_id == "shp_air_cargo_001"


def test_50_shipment_event_bridge_behavior():
    """50. Test ShipmentEventBridge rejects uncorrelated aircraft and accepts correlated."""
    normalizer = OpenSkyNormalizer()
    payload = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA).to_raw_payload()

    # Case A: Uncorrelated aircraft
    raw_uncorrelated = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical_uncorrelated = normalizer.normalize(raw_uncorrelated)
    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical_uncorrelated) is False
    with pytest.raises(ValueError):
        ShipmentEventBridge.to_shipment_event_dict(canonical_uncorrelated)

    # Case B: Correlated aircraft
    payload_corr = dict(payload)
    payload_corr["shipment_id"] = "shp_express_air_999"
    raw_corr = RawEvent(provider_name="opensky", raw_payload=payload_corr)
    canonical_corr = normalizer.normalize(raw_corr)
    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical_corr) is True

    shipment_dict = ShipmentEventBridge.to_shipment_event_dict(canonical_corr)
    assert shipment_dict["shipment_id"] == "shp_express_air_999"
    assert shipment_dict["mode"] == "AIR"
    assert shipment_dict["latitude"] == 50.0379
    assert shipment_dict["longitude"] == 8.5678


def test_51_raw_payload_preservation():
    """51. Test raw payload preservation inside RawEvent envelope."""
    vector = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA)
    payload = vector.to_raw_payload(response_time=1725800000)
    raw = RawEvent(provider_name="opensky", raw_payload=payload)

    assert raw.raw_payload["icao24"] == "3c6444"
    assert raw.raw_payload["callsign"] == "DLH123"
    assert raw.raw_payload["baro_altitude"] == 3200.4
    assert raw.raw_payload["response_time"] == 1725800000


def test_52_secret_redaction():
    """52. Test that secrets and tokens never appear in payload or string representations."""
    client_secret = "super_confidential_secret_key_123"
    access_token = "confidential_bearer_token_abc"
    adapter = OpenSkyAdapter(client_id="cid", secret=client_secret)

    # Verify adapter string representation does not leak secret
    assert client_secret not in str(adapter)

    # Verify SecretResolver sanitization strips credential fields
    dirty_payload = {
        "icao24": "3c6444",
        "client_secret": client_secret,
        "access_token": access_token,
        "Authorization": f"Bearer {access_token}",
    }
    sanitized = SecretResolver.sanitize_payload(dirty_payload)
    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["icao24"] == "3c6444"


def test_53_health_check():
    """53. Test provider health check outcomes across all 4 operational states."""
    # State 1: UNCONFIGURED (missing credentials)
    unconfigured_adapter = OpenSkyAdapter(client_id="", secret="")
    h1 = unconfigured_adapter.health_check()
    assert h1.status == ProviderHealthStatus.UNCONFIGURED

    # State 2: HEALTHY (successful token + probe)
    healthy_client = make_mock_opensky_client()
    healthy_adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=healthy_client)
    h2 = healthy_adapter.health_check()
    assert h2.status == ProviderHealthStatus.HEALTHY
    assert "connectivity probe succeeded" in h2.message

    # State 3: DEGRADED (probe timeout)
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "protocol/openid-connect/token" in url_str:
            return httpx.Response(status_code=200, content=json.dumps(SAMPLE_TOKEN_RESPONSE).encode("utf-8"), request=request)
        raise httpx.ReadTimeout("Timeout probe")

    timeout_client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    timeout_adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=timeout_client)
    h3 = timeout_adapter.health_check()
    assert h3.status == ProviderHealthStatus.DEGRADED

    # State 4: UNHEALTHY (auth rejection)
    unauth_client = make_mock_opensky_client(token_status=401)
    unauth_adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=unauth_client)
    h4 = unauth_adapter.health_check()
    assert h4.status == ProviderHealthStatus.UNHEALTHY


def test_54_scheduler_integration():
    """54. Test scheduler integration with create_opensky_polling_job."""
    scheduler = InMemoryIngestionScheduler()
    bbox = OpenSkyBoundingBox(min_latitude=40.0, min_longitude=-10.0, max_latitude=60.0, max_longitude=20.0)
    job = create_opensky_polling_job(
        job_id="job_opensky_europe",
        cron_or_interval="interval:120",
        bounding_box=bbox,
        icao24=["3c6444"],
    )
    scheduler.register_job(job)

    retrieved = scheduler.get_job("job_opensky_europe")
    assert retrieved is not None
    assert retrieved.provider_name == "opensky"
    assert retrieved.cron_or_interval == "interval:120"
    assert "bounding_box" in retrieved.parameters
    assert retrieved.parameters["icao24"] == ["3c6444"]


def test_55_observability_metadata():
    """55. Test observability metadata is populated on IngestionBatch."""
    client = make_mock_opensky_client(
        states_data={"time": 1725800000, "states": [SAMPLE_STATE_LUFTHANSA]}
    )
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    batch = adapter.fetch()

    assert "response_time" in batch.source_metadata
    assert batch.source_metadata["count"] == 1
    assert "endpoint" in batch.source_metadata


def test_56_tenant_org_isolation():
    """56. Test multi-tenant isolation propagating org_id."""
    client = make_mock_opensky_client(
        states_data={"time": 1725800000, "states": [SAMPLE_STATE_LUFTHANSA]}
    )
    adapter = OpenSkyAdapter(client_id="cid", secret="csec", http_client=client)
    batch = adapter.fetch(org_id="org_riskwise_air_01")

    assert batch.events[0].org_id == "org_riskwise_air_01"

    normalizer = OpenSkyNormalizer()
    canonical = normalizer.normalize(batch.events[0])
    assert canonical.org_id == "org_riskwise_air_01"


def test_57_unsupported_field_handling():
    """57. Test that commercial flight data not provided by OpenSky is explicitly unsupported/excluded."""
    vector = OpenSkyStateVector.from_raw_array(SAMPLE_STATE_LUFTHANSA)
    payload = vector.to_raw_payload()

    # OpenSky ADS-B does not provide commercial schedules, delays, cargo, bookings
    assert "passenger_count" not in payload
    assert "cargo_manifest" not in payload
    assert "airline_delay_reason" not in payload
    assert "scheduled_departure_time" not in payload

    normalizer = OpenSkyNormalizer()
    raw = RawEvent(provider_name="opensky", raw_payload=payload)
    canonical = normalizer.normalize(raw)

    # Canonical mapping does not fabricate delay_minutes or eta
    assert canonical.delay_minutes is None
    assert canonical.eta is None
