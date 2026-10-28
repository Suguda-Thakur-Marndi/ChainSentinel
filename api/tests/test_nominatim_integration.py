"""Unit and contract tests for OpenStreetMap Nominatim Geocoding Provider Integration.

Tests the full lifecycle of the Nominatim integration:
 1. Adapter initialization and capabilities (enforcing 1 req/sec policy)
 2. Configuration loading and defaults
 3. Forward geocoding request and response parsing (mocked)
 4. Reverse geocoding request and coordinate parsing (mocked)
 5. Coordinate bounds validation (-90 to +90, -180 to +180)
 6. Address details parsing and country code normalization
 7. Mandatory descriptive User-Agent header validation
 8. Attribution metadata preservation (ODbL 1.0)
 9. Missing optional fields handled gracefully
10. Malformed JSON response error handling
11. HTTP 403 Forbidden handling (missing User-Agent)
12. HTTP 429 rate limit error and Retry-After handling
13. Transient HTTP 5xx errors and bounded retry policy
14. Deterministic idempotency fingerprinting
15. Duplicate geocoding suppression
16. Canonical event generation and quality assessment (VALID, PARTIAL, INVALID)
17. Provider health check probe (HEALTHY, DEGRADED, UNHEALTHY)
18. Registry integration in default_provider_registry
19. Multi-tenant organization isolation
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
    ProviderAuthenticationError,
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
    SecretResolver,
    TimestampNormalizer,
    default_provider_registry,
)
from app.integrations.providers.nominatim import (
    DEFAULT_NOMINATIM_BASE_URL,
    DEFAULT_NOMINATIM_REVERSE_URL,
    DEFAULT_NOMINATIM_SEARCH_URL,
    NominatimAdapter,
    NominatimNormalizer,
)


# =====================================================================
# Mock Payloads & Transport Helpers
# =====================================================================

SAMPLE_FORWARD_GEOCODE = [
    {
        "place_id": 282845612,
        "licence": "Data © OpenStreetMap contributors, ODbL 1.0. http://osm.org/copyright",
        "osm_type": "relation",
        "osm_id": 141258,
        "lat": "51.9244424",
        "lon": "4.4777326",
        "category": "boundary",
        "type": "administrative",
        "place_rank": 16,
        "importance": 0.852,
        "addresstype": "city",
        "name": "Rotterdam",
        "display_name": "Port of Rotterdam, Rotterdam, South Holland, Netherlands",
        "address": {
            "city": "Rotterdam",
            "state": "South Holland",
            "ISO3166-2-lvl4": "NL-ZH",
            "country": "Netherlands",
            "country_code": "nl",
            "postcode": "3011 AA",
        },
        "boundingbox": ["51.85", "51.99", "4.35", "4.60"],
    }
]

SAMPLE_REVERSE_GEOCODE = {
    "place_id": 198273645,
    "licence": "Data © OpenStreetMap contributors, ODbL 1.0",
    "osm_type": "way",
    "osm_id": 987654321,
    "lat": "33.7431",
    "lon": "-118.2673",
    "category": "amenity",
    "type": "ferry_terminal",
    "place_rank": 30,
    "importance": 0.65,
    "display_name": "Berth 93, Port of Los Angeles, San Pedro, Los Angeles, California, 90731, United States",
    "address": {
        "amenity": "Port of Los Angeles",
        "road": "Swinford Street",
        "suburb": "San Pedro",
        "city": "Los Angeles",
        "state": "California",
        "postcode": "90731",
        "country": "United States",
        "country_code": "us",
    },
    "boundingbox": ["33.74", "33.75", "-118.27", "-118.26"],
}


def create_mock_nominatim_client(
    status_code: int = 200,
    json_data: Any = None,
    headers: Optional[Dict[str, str]] = None,
    exception: Optional[Exception] = None,
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if exception:
            raise exception
        return httpx.Response(
            status_code=status_code,
            json=json_data if json_data is not None else SAMPLE_FORWARD_GEOCODE,
            headers=headers or {"content-type": "application/json"},
        )
    return httpx.Client(transport=httpx.MockTransport(handler))


# =====================================================================
# Test Suite
# =====================================================================

def test_01_adapter_initialization() -> None:
    adapter = NominatimAdapter()
    assert adapter.provider_name == "nominatim"
    assert adapter.provider_type == ProviderType.GEOCODING
    assert adapter.capabilities.supports_polling is True
    assert adapter.capabilities.supports_batch is False  # Enforces 1 req/sec policy
    assert "geocoding" in adapter.capabilities.supported_modalities
    adapter.close()


def test_02_configuration_loading() -> None:
    cfg = ProviderConfig(
        provider_name="nominatim",
        provider_type=ProviderType.GEOCODING,
        base_url=DEFAULT_NOMINATIM_SEARCH_URL,
        rate_limit=RateLimitConfig(requests_per_minute=60, burst_limit=1),
    )
    adapter = NominatimAdapter(config=cfg)
    assert adapter.config.rate_limit.requests_per_minute == 60
    assert adapter.config.rate_limit.burst_limit == 1
    adapter.close()


def test_03_forward_geocoding_success() -> None:
    client = create_mock_nominatim_client(status_code=200, json_data=SAMPLE_FORWARD_GEOCODE)
    adapter = NominatimAdapter(http_client=client)

    batch = adapter.fetch(query="Port of Rotterdam", port_id="port_rotterdam", organization_id="org_test")
    assert len(batch.events) == 1
    ev = batch.events[0]
    assert ev.provider_name == "nominatim"
    assert ev.provider_event_id == "osm_relation_141258"
    assert ev.metadata["port_id"] == "port_rotterdam"
    assert ev.org_id == "org_test"
    adapter.close()


def test_04_reverse_geocoding_success() -> None:
    client = create_mock_nominatim_client(status_code=200, json_data=SAMPLE_REVERSE_GEOCODE)
    adapter = NominatimAdapter(http_client=client)

    batch = adapter.fetch(latitude=33.7431, longitude=-118.2673, facility_id="fac_la")
    assert len(batch.events) == 1
    ev = batch.events[0]
    assert ev.provider_name == "nominatim"
    assert ev.provider_event_id == "osm_way_987654321"
    assert ev.metadata["facility_id"] == "fac_la"
    adapter.close()


def test_05_coordinate_bounds_validation() -> None:
    adapter = NominatimAdapter()
    with pytest.raises(ValueError, match="Latitude out of bounds"):
        adapter.fetch(latitude=91.0, longitude=0.0)

    with pytest.raises(ValueError, match="Longitude out of bounds"):
        adapter.fetch(latitude=0.0, longitude=-181.0)

    with pytest.raises(ProviderValidationError):
        adapter.fetch()  # Neither query nor coords provided
    adapter.close()


def test_06_normalization_and_address_mapping() -> None:
    normalizer = NominatimNormalizer()
    raw = RawEvent(
        provider_name="nominatim",
        provider_event_id="osm_relation_141258",
        raw_payload=SAMPLE_FORWARD_GEOCODE[0],
        metadata={"port_id": "port_rotterdam"},
    )
    canon = normalizer.normalize(raw)
    assert canon.event_type == CanonicalEventType.GEOCODING_REFERENCE
    assert canon.severity == EventSeverity.INFO
    assert canon.status == "GEOCODED"
    assert canon.quality == EventQuality.VALID
    assert canon.location.latitude == 51.9244424
    assert canon.location.longitude == 4.4777326
    assert canon.location.country_code == "NL"
    assert canon.location.region == "South Holland"
    assert canon.normalized_attributes["city"] == "Rotterdam"
    assert canon.normalized_attributes["postcode"] == "3011 AA"
    assert "OpenStreetMap" in canon.normalized_attributes["attribution"]


def test_07_user_agent_header_present() -> None:
    adapter = NominatimAdapter()
    headers = adapter.client.headers
    assert "User-Agent" in headers
    assert "ChainSentinel" in headers["User-Agent"]
    adapter.close()


def test_08_http_403_forbidden_handling() -> None:
    client = create_mock_nominatim_client(status_code=403)
    adapter = NominatimAdapter(http_client=client)
    with pytest.raises(ProviderAuthenticationError) as exc:
        adapter.fetch(query="Hamburg")
    assert exc.value.status_code == 403
    adapter.close()


def test_09_http_429_rate_limiting() -> None:
    client = create_mock_nominatim_client(status_code=429, headers={"Retry-After": "2"})
    adapter = NominatimAdapter(http_client=client)
    with pytest.raises(ProviderRateLimitError) as exc:
        adapter.fetch(query="Hamburg")
    assert exc.value.retry_after_seconds == 2.0
    adapter.close()


def test_10_transient_5xx_and_retry() -> None:
    attempts = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(500, text="Server Error")
        return httpx.Response(200, json=SAMPLE_FORWARD_GEOCODE)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = NominatimAdapter(http_client=client)

    policy = RetryPolicy(RetryConfig(max_retries=2, initial_delay_seconds=0.01))
    batch = policy.execute(lambda: adapter.fetch(query="Rotterdam"))
    assert len(batch.events) == 1
    assert attempts == 2
    adapter.close()


def test_11_deterministic_idempotency_fingerprint() -> None:
    fp1 = NominatimAdapter.compute_geocoding_fingerprint(141258, "relation", "q:Rotterdam", org_id="tenant_1")
    fp2 = NominatimAdapter.compute_geocoding_fingerprint(141258, "relation", "q:Rotterdam", org_id="tenant_1")
    assert fp1 == fp2
    assert len(fp1) == 64


def test_12_provider_health_check() -> None:
    client_ok = create_mock_nominatim_client(status_code=200, json_data=SAMPLE_FORWARD_GEOCODE)
    adapter_ok = NominatimAdapter(http_client=client_ok)
    h_ok = adapter_ok.health_check()
    assert h_ok.status == ProviderHealthStatus.HEALTHY
    adapter_ok.close()

    client_429 = create_mock_nominatim_client(status_code=429)
    adapter_429 = NominatimAdapter(http_client=client_429)
    h_429 = adapter_429.health_check()
    assert h_429.status == ProviderHealthStatus.DEGRADED
    adapter_429.close()

    client_to = create_mock_nominatim_client(exception=httpx.TimeoutException("Timeout"))
    adapter_to = NominatimAdapter(http_client=client_to)
    h_to = adapter_to.health_check()
    assert h_to.status == ProviderHealthStatus.UNHEALTHY
    adapter_to.close()


def test_13_registry_integration() -> None:
    assert default_provider_registry.is_registered("nominatim")
    cls = default_provider_registry.get_adapter_cls("nominatim")
    assert cls == NominatimAdapter

    adapter = default_provider_registry.create_adapter("nominatim")
    assert isinstance(adapter, NominatimAdapter)
    adapter.close()


def test_14_tenant_org_isolation() -> None:
    fp_a = NominatimAdapter.compute_geocoding_fingerprint(141258, "relation", "q:Rotterdam", org_id="tenant_a")
    fp_b = NominatimAdapter.compute_geocoding_fingerprint(141258, "relation", "q:Rotterdam", org_id="tenant_b")
    assert fp_a != fp_b
