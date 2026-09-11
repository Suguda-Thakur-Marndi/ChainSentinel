"""Comprehensive unit test suite for RiskWise 2.0 Phase 5 Step 8: Tracking / Logistics Integration (Karrio).

All tests are 100% self-contained and execute against mocked HTTP endpoints (zero live network calls).

Covers all 48+ requirements:
 1. KarrioAdapter initialization
 2. Provider capability inspection
 3. Custom configuration validation
 4. Direct secret resolution
 5. Environment variable secret resolution (KARRIO_API_KEY)
 6. Unauthenticated feed support
 7. URL resolution for tracker queries and lists
 8. Successful single tracker fetch
 9. Multi-event tracking history
10. Root summary event when events array is empty
11. Tracking number and carrier name preservation
12. Status mapping: delivered
13. Status mapping: in_transit
14. Status mapping: out_for_delivery
15. Status mapping: picked_up
16. Status mapping: ready_for_pickup
17. Status mapping: pending / created
18. Status mapping: delivery_delayed / delayed
19. Status mapping: delivery_failed
20. Status mapping: on_hold / exception
21. Status mapping: cancelled
22. Status mapping: unknown
23. Incident reason: carrier damaged & lost parcel (CRITICAL)
24. Incident reason: customs & weather delay (HIGH)
25. Incident reason: consignee issues (MEDIUM)
26. Timestamp normalization (ISO 8601)
27. Timestamp normalization (epoch)
28. Timestamp normalization (date + time)
29. Malformed timestamp fallback
30. ETA extraction (estimated_delivery)
31. Missing ETA handling
32. Calculated delay minutes from baseline ETA
33. Location with valid coordinates (lat/lon)
34. Location with invalid coordinates (PARTIAL quality)
35. Location text-only (no coordinates)
36. Explicit shipment correlation (request parameter)
37. Explicit shipment correlation (tracker metadata)
38. Unresolved shipment correlation (shipment_id = None)
39. False correlation prevention (carrier/tracking ID is not shipment ID)
40. ShipmentEventBridge behavior (with and without shipment_id)
41. Batch listing query (/v1/trackers)
42. Deterministic idempotency fingerprinting
43. Consecutive tracking events preservation (distinct fingerprints)
44. Duplicate event suppression via IdempotencyEngine
45. Retry behavior on transient HTTP 5xx
46. HTTP 429 rate limit with Retry-After header
47. HTTP 401/403 authentication error handling
48. HTTP 404 tracker not found handling
49. Client timeout handling
50. Connection error handling
51. Malformed JSON response handling
52. Diagnostic health check: HEALTHY
53. Diagnostic health check: UNCONFIGURED
54. Diagnostic health check: UNHEALTHY (auth failure)
55. Diagnostic health check: DEGRADED (rate limit)
56. Diagnostic health check: UNHEALTHY (server error)
57. Diagnostic health check: DEGRADED (timeout)
58. Secret redaction in logs and payloads
59. Registry integration (default_provider_registry)
60. Polling job creation helper (create_karrio_polling_job)
61. Webhook signature verification (HMAC-SHA256)
62. Webhook signature rejection (invalid HMAC)
63. Webhook payload parsing (wrapped data object)
64. Tenant/org isolation in raw and canonical events
65. Full multi-tier pipeline integration
"""
from __future__ import annotations

import hashlib
import hmac
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
    DEFAULT_KARRIO_BASE_URL,
    DEFAULT_KARRIO_TRACKERS_ENDPOINT,
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
    KarrioAdapter,
    KarrioIncidentReason,
    KarrioNormalizer,
    KarrioTracker,
    KarrioTrackingEvent,
    KarrioTrackingStatus,
    KarrioWebhookReceiver,
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
    ProviderValidationError,
    RateLimitConfig,
    RawEvent,
    RetryConfig,
    ScheduledIngestionJob,
    SecretResolver,
    ShipmentEventBridge,
    TimestampNormalizer,
    create_karrio_polling_job,
    default_provider_registry,
)


# =====================================================================
# Sample Karrio Mock Payloads
# =====================================================================

SAMPLE_TRACKER_FEDEX = {
    "id": "trk_fedex_123456",
    "carrier_name": "fedex",
    "carrier_id": "fedex_account_us",
    "tracking_number": "123456789012",
    "status": "in_transit",
    "delivered": False,
    "estimated_delivery": "2026-09-12T17:00:00Z",
    "actual_delivery": None,
    "events": [
        {
            "date": "2026-09-08",
            "time": "08:15",
            "description": "Picked up by FedEx",
            "location": "AUSTIN, TX, US",
            "code": "PU",
            "status": "picked_up",
            "timestamp": 1725783300,
            "latitude": 30.2672,
            "longitude": -97.7431,
        },
        {
            "date": "2026-09-08",
            "time": "14:30",
            "description": "Departed FedEx Sort Facility",
            "location": "MEMPHIS, TN, US",
            "code": "DP",
            "status": "in_transit",
            "timestamp": 1725805800,
            "latitude": 35.0424,
            "longitude": -89.9767,
        },
    ],
    "messages": [],
    "metadata": {
        "shipment_id": "SHP-US-WEST-901",
    },
    "info": {
        "carrier_tracking_link": "https://www.fedex.com/fedextrack/?trknbr=123456789012",
        "shipment_service": "fedex_priority_overnight",
    },
}

SAMPLE_TRACKER_DELIVERED = {
    "id": "trk_auspost_888",
    "carrier_name": "auspost",
    "carrier_id": "auspost_sydney",
    "tracking_number": "AP987654321AU",
    "status": "delivered",
    "delivered": True,
    "estimated_delivery": "2026-09-08T12:00:00Z",
    "actual_delivery": "2026-09-08T11:45:00Z",
    "events": [
        {
            "date": "2026-09-08",
            "time": "11:45",
            "description": "Delivered to recipient mailbox",
            "location": "SYDNEY, NSW, AU",
            "code": "DEL",
            "status": "delivered",
            "timestamp": 1725795900,
            "latitude": -33.8688,
            "longitude": 151.2093,
        }
    ],
    "metadata": {},
}

SAMPLE_TRACKER_EXCEPTION = {
    "id": "trk_dhl_exc",
    "carrier_name": "dhl",
    "carrier_id": "dhl_express_global",
    "tracking_number": "DHL8877665544",
    "status": "on_hold",
    "delivered": False,
    "estimated_delivery": "2026-09-15T18:00:00Z",
    "events": [
        {
            "date": "2026-09-08",
            "time": "16:00",
            "description": "Shipment held in customs for inspection",
            "location": "LOS ANGELES, CA, US",
            "code": "HOLD_CUSTOMS",
            "status": "on_hold",
            "reason": "customs_delay",
            "timestamp": 1725811200,
            "latitude": 33.9425,
            "longitude": -118.4081,
        }
    ],
    "metadata": {},
}


def make_mock_karrio_client(
    response_data: Optional[Any] = None,
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
    custom_handler: Optional[Callable[[httpx.Request], httpx.Response]] = None,
) -> httpx.Client:
    """Create an isolated in-memory HTTP client with mock transport returning Karrio JSON."""
    default_data = response_data if response_data is not None else SAMPLE_TRACKER_FEDEX

    def default_handler(request: httpx.Request) -> httpx.Response:
        if custom_handler is not None:
            return custom_handler(request)

        resp_headers = dict(headers or {})
        if "Content-Type" not in resp_headers:
            resp_headers["Content-Type"] = "application/json"

        body = json.dumps(default_data).encode("utf-8") if default_data is not None else b""
        return httpx.Response(
            status_code=status_code,
            content=body,
            headers=resp_headers,
            request=request,
        )

    transport = httpx.MockTransport(default_handler)
    return httpx.Client(transport=transport)


# =====================================================================
# Unit Tests (65 Comprehensive Test Cases)
# =====================================================================

def test_karrio_adapter_initialization() -> None:
    """1. Test KarrioAdapter initialization, capabilities, and provider metadata."""
    adapter = KarrioAdapter()
    assert adapter.provider_name == "karrio"
    assert adapter.provider_type == ProviderType.LOGISTICS_TRACKING
    assert adapter.capabilities.supports_polling is True
    assert adapter.capabilities.supports_webhook is True
    assert adapter.capabilities.supports_batch is True
    assert adapter.capabilities.supports_health_check is True
    assert adapter.capabilities.supports_streaming is False
    assert adapter.config.auth_mode == AuthMode.API_KEY_HEADER
    assert adapter.config.base_url == DEFAULT_KARRIO_BASE_URL
    adapter.close()


def test_karrio_adapter_capabilities() -> None:
    """2. Test KarrioAdapter capabilities inspection."""
    adapter = KarrioAdapter()
    caps = adapter.capabilities
    assert "tracker" in caps.supported_entities
    assert "tracking_number" in caps.supported_entities
    assert "parcel" in caps.supported_entities
    assert "freight" in caps.supported_modalities
    assert caps.max_batch_size == 500
    adapter.close()


def test_karrio_configuration_validation() -> None:
    """3. Test custom ProviderConfig loading and validation."""
    custom_config = ProviderConfig(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        base_url="https://karrio.internal.logistics.net:5002",
        auth_mode=AuthMode.API_KEY_HEADER,
        secret_ref="env:CUSTOM_KARRIO_TOKEN",
        rate_limit=RateLimitConfig(requests_per_minute=240),
        retry=RetryConfig(max_retries=5, initial_delay_seconds=0.2),
    )
    adapter = KarrioAdapter(config=custom_config)
    assert adapter.config.base_url == "https://karrio.internal.logistics.net:5002"
    assert adapter.config.rate_limit.requests_per_minute == 240
    assert adapter.config.retry.max_retries == 5
    adapter.close()


def test_karrio_api_key_resolution_direct_secret() -> None:
    """4. Test API key resolution when directly supplied as secret parameter."""
    adapter = KarrioAdapter(secret="direct_karrio_token_xyz99")
    assert adapter.resolve_api_key() == "direct_karrio_token_xyz99"
    adapter.close()


def test_karrio_api_key_resolution_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Test API key resolution from environment variable KARRIO_API_KEY."""
    monkeypatch.setenv("KARRIO_API_KEY", "env_karrio_token_8877")
    adapter = KarrioAdapter()
    assert adapter.resolve_api_key() == "env_karrio_token_8877"
    adapter.close()


def test_karrio_unauthenticated_feed_support() -> None:
    """6. Test unauthenticated request when Karrio instance has no auth token required."""
    resolver = SecretResolver()
    adapter = KarrioAdapter(secret=None, secret_resolver=resolver)
    assert adapter.resolve_api_key() is None

    captured_headers: Dict[str, str] = {}

    def capture_handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(
            status_code=200,
            content=json.dumps(SAMPLE_TRACKER_DELIVERED).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(capture_handler))
    adapter._external_client = mock_client

    batch = adapter.fetch(carrier_name="auspost", tracking_number="AP987654321AU")
    assert "authorization" not in captured_headers
    assert len(batch.events) == 1
    adapter.close()


def test_karrio_url_builders() -> None:
    """7. Test URL resolution for individual tracker and list endpoints."""
    adapter = KarrioAdapter()
    tracker_url = adapter.get_tracker_url("fedex", "123456789012")
    list_url = adapter.get_trackers_url()

    assert tracker_url == "http://localhost:5002/v1/trackers/fedex/123456789012"
    assert list_url == "http://localhost:5002/v1/trackers"
    adapter.close()


def test_karrio_successful_tracking_request() -> None:
    """8. Test successful single tracker fetch returning an IngestionBatch."""
    client = make_mock_rail_client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert isinstance(batch, IngestionBatch)
    assert batch.provider_name == "karrio"
    assert batch.source_metadata["carrier_name"] == "fedex"
    assert batch.source_metadata["tracking_number"] == "123456789012"
    assert batch.source_metadata["status"] == "in_transit"
    adapter.close()


def test_karrio_multiple_tracking_events() -> None:
    """9. Test that multiple events in a tracker produce corresponding RawEvent milestones."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert len(batch.events) == 2

    e0 = batch.events[0]
    assert e0.raw_payload["code"] == "PU"
    assert e0.raw_payload["status"] == "picked_up"
    assert e0.raw_payload["event_index"] == 0

    e1 = batch.events[1]
    assert e1.raw_payload["code"] == "DP"
    assert e1.raw_payload["status"] == "in_transit"
    assert e1.raw_payload["event_index"] == 1
    adapter.close()


def test_karrio_root_tracker_summary_event() -> None:
    """10. Test tracker with empty events array produces a single summary RawEvent."""
    empty_events_tracker = {
        "id": "trk_empty_events",
        "carrier_name": "ups",
        "tracking_number": "1Z9999999999999999",
        "status": "pending",
        "delivered": False,
        "events": [],
    }
    client = make_mock_karrio_client(response_data=empty_events_tracker)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="ups", tracking_number="1Z9999999999999999")
    assert len(batch.events) == 1
    assert batch.events[0].raw_payload["status"] == "pending"
    assert batch.events[0].raw_payload["event_index"] == 0
    adapter.close()


def test_karrio_tracking_number_and_carrier_preservation() -> None:
    """11. Test original tracking number and carrier name are preserved."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_DELIVERED)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="auspost", tracking_number="AP987654321AU")
    raw = batch.events[0]
    assert raw.raw_payload["tracking_number"] == "AP987654321AU"
    assert raw.raw_payload["carrier_name"] == "auspost"

    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.correlation.custom_identifiers["tracking_number"] == "AP987654321AU"
    assert canonical.correlation.custom_identifiers["carrier_name"] == "auspost"
    adapter.close()


def test_karrio_status_mapping_delivered() -> None:
    """12. Test status mapping: delivered -> SHIPMENT_STATUS + INFO + DELIVERED."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:deliv",
        fingerprint="fp_deliv",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "delivered", "tracking_number": "T1", "carrier_name": "fedex"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.INFO
    assert canonical.status == "DELIVERED"


def test_karrio_status_mapping_in_transit() -> None:
    """13. Test status mapping: in_transit -> SHIPMENT_STATUS + INFO + IN_TRANSIT."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:transit",
        fingerprint="fp_transit",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "in_transit", "tracking_number": "T2", "carrier_name": "ups"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.INFO
    assert canonical.status == "IN_TRANSIT"


def test_karrio_status_mapping_out_for_delivery() -> None:
    """14. Test status mapping: out_for_delivery -> SHIPMENT_STATUS + LOW + OUT_FOR_DELIVERY."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:ofd",
        fingerprint="fp_ofd",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "out_for_delivery", "tracking_number": "T3", "carrier_name": "dhl"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.LOW
    assert canonical.status == "OUT_FOR_DELIVERY"


def test_karrio_status_mapping_picked_up() -> None:
    """15. Test status mapping: picked_up -> SHIPMENT_STATUS + INFO + PICKED_UP."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:pu",
        fingerprint="fp_pu",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "picked_up", "tracking_number": "T4", "carrier_name": "fedex"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.INFO
    assert canonical.status == "PICKED_UP"


def test_karrio_status_mapping_ready_for_pickup() -> None:
    """16. Test status mapping: ready_for_pickup -> SHIPMENT_STATUS + INFO + READY_FOR_PICKUP."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:rfp",
        fingerprint="fp_rfp",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "ready_for_pickup", "tracking_number": "T5", "carrier_name": "auspost"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.INFO
    assert canonical.status == "READY_FOR_PICKUP"


def test_karrio_status_mapping_pending() -> None:
    """17. Test status mapping: pending / created -> SHIPMENT_STATUS + INFO + PENDING."""
    for s in ("pending", "created", "label_printed"):
        raw = RawEvent(
            provider_name="karrio",
            provider_type=ProviderType.LOGISTICS_TRACKING,
            provider_event_id=f"karrio:test:{s}",
            fingerprint=f"fp_{s}",
            source_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            raw_payload={"status": s, "tracking_number": "T6", "carrier_name": "ups"},
        )
        canonical = KarrioNormalizer().normalize(raw)
        assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
        assert canonical.severity == EventSeverity.INFO
        assert canonical.status == "PENDING"


def test_karrio_status_mapping_delivery_delayed() -> None:
    """18. Test status mapping: delivery_delayed -> SHIPMENT_DELAY + MEDIUM / HIGH."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:delayed",
        fingerprint="fp_delayed",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "delivery_delayed", "description": "Weather delay on route", "tracking_number": "T7", "carrier_name": "fedex"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_DELAY
    assert canonical.severity == EventSeverity.MEDIUM
    assert canonical.status == "DELAYED"


def test_karrio_status_mapping_delivery_failed() -> None:
    """19. Test status mapping: delivery_failed -> SHIPMENT_STATUS + HIGH + DELIVERY_FAILED."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:failed",
        fingerprint="fp_failed",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "delivery_failed", "tracking_number": "T8", "carrier_name": "dhl"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.HIGH
    assert canonical.status == "DELIVERY_FAILED"


def test_karrio_status_mapping_on_hold_exception() -> None:
    """20. Test status mapping: on_hold / exception -> SHIPMENT_DELAY + HIGH + ON_HOLD."""
    for s in ("on_hold", "exception", "customs_hold"):
        raw = RawEvent(
            provider_name="karrio",
            provider_type=ProviderType.LOGISTICS_TRACKING,
            provider_event_id=f"karrio:test:{s}",
            fingerprint=f"fp_{s}",
            source_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            raw_payload={"status": s, "tracking_number": "T9", "carrier_name": "fedex"},
        )
        canonical = KarrioNormalizer().normalize(raw)
        assert canonical.event_type == CanonicalEventType.SHIPMENT_DELAY
        assert canonical.severity == EventSeverity.HIGH
        assert canonical.status == "ON_HOLD"


def test_karrio_status_mapping_cancelled() -> None:
    """21. Test status mapping: cancelled -> SHIPMENT_STATUS + CRITICAL + CANCELLED."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:cancelled",
        fingerprint="fp_cancelled",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "cancelled", "tracking_number": "T10", "carrier_name": "ups"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical.severity == EventSeverity.CRITICAL
    assert canonical.status == "CANCELLED"


def test_karrio_status_mapping_unknown() -> None:
    """22. Test status mapping: unknown status -> CUSTOM + INFO."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:unk",
        fingerprint="fp_unk",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "some_arbitrary_unmapped_status", "tracking_number": "T11", "carrier_name": "custom_carrier"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.event_type == CanonicalEventType.CUSTOM
    assert canonical.severity == EventSeverity.INFO


def test_karrio_incident_reason_damaged_and_lost() -> None:
    """23. Test incident reason: carrier_damaged_parcel and carrier_parcel_lost -> CRITICAL."""
    for r in ("carrier_damaged_parcel", "carrier_parcel_lost"):
        raw = RawEvent(
            provider_name="karrio",
            provider_type=ProviderType.LOGISTICS_TRACKING,
            provider_event_id=f"karrio:test:{r}",
            fingerprint=f"fp_{r}",
            source_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            raw_payload={"status": "exception", "reason": r, "tracking_number": "T12", "carrier_name": "dhl"},
        )
        canonical = KarrioNormalizer().normalize(raw)
        assert canonical.severity == EventSeverity.CRITICAL
        assert r.upper() in canonical.status


def test_karrio_incident_reason_customs_and_weather() -> None:
    """24. Test incident reason: customs_delay and weather_delay -> HIGH + SHIPMENT_DELAY."""
    for r in ("customs_delay", "weather_delay", "carrier_sorting_error"):
        raw = RawEvent(
            provider_name="karrio",
            provider_type=ProviderType.LOGISTICS_TRACKING,
            provider_event_id=f"karrio:test:{r}",
            fingerprint=f"fp_{r}",
            source_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            raw_payload={"status": "delivery_delayed", "reason": r, "tracking_number": "T13", "carrier_name": "fedex"},
        )
        canonical = KarrioNormalizer().normalize(raw)
        assert canonical.event_type == CanonicalEventType.SHIPMENT_DELAY
        assert canonical.severity == EventSeverity.HIGH


def test_karrio_incident_reason_consignee_issues() -> None:
    """25. Test incident reason: consignee_refused and consignee_business_closed -> MEDIUM."""
    for r in ("consignee_refused", "consignee_business_closed", "consignee_not_available"):
        raw = RawEvent(
            provider_name="karrio",
            provider_type=ProviderType.LOGISTICS_TRACKING,
            provider_event_id=f"karrio:test:{r}",
            fingerprint=f"fp_{r}",
            source_timestamp=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            raw_payload={"status": "delivery_failed", "reason": r, "tracking_number": "T14", "carrier_name": "ups"},
        )
        canonical = KarrioNormalizer().normalize(raw)
        assert canonical.severity == EventSeverity.MEDIUM


def test_karrio_timestamp_normalization_iso() -> None:
    """26. Test timestamp normalization from ISO 8601 string."""
    ts_iso = "2026-09-08T14:30:00Z"
    dt = TimestampNormalizer.parse_to_utc(ts_iso)
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 8
    assert dt.hour == 14
    assert dt.tzinfo == timezone.utc


def test_karrio_timestamp_normalization_epoch() -> None:
    """27. Test timestamp normalization from epoch integer."""
    dt = TimestampNormalizer.parse_to_utc(1725805800)
    assert dt.tzinfo == timezone.utc


def test_karrio_timestamp_normalization_date_and_time() -> None:
    """28. Test timestamp normalization combining date and time fields."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    canonical = KarrioNormalizer().normalize(batch.events[0])
    assert canonical.event_timestamp.hour == 8
    assert canonical.event_timestamp.minute == 15
    adapter.close()


def test_karrio_malformed_timestamp_fallback() -> None:
    """29. Test that malformed timestamp falls back without throwing unhandled exceptions."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:bad_ts",
        fingerprint="fp_bad_ts",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "in_transit", "estimated_delivery": "NOT_A_VALID_DATE", "tracking_number": "T15", "carrier_name": "ups"},
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.eta is None
    assert any("ETA normalization" in err for err in canonical.validation_errors)
    assert canonical.quality == EventQuality.PARTIAL


def test_karrio_eta_extraction() -> None:
    """30. Test estimated delivery date (ETA) extraction and normalization."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    canonical = KarrioNormalizer().normalize(batch.events[0])

    assert canonical.eta is not None
    assert canonical.eta.year == 2026
    assert canonical.eta.month == 9
    assert canonical.eta.day == 12
    adapter.close()


def test_karrio_missing_eta() -> None:
    """31. Test handling of tracker with no estimated delivery date."""
    data = dict(SAMPLE_TRACKER_DELIVERED)
    data["estimated_delivery"] = None
    client = make_mock_karrio_client(response_data=data)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="auspost", tracking_number="AP987654321AU")
    canonical = KarrioNormalizer().normalize(batch.events[0])
    assert canonical.eta is None
    adapter.close()


def test_karrio_calculated_delay_from_baseline_eta() -> None:
    """32. Test delay calculation when scheduled_eta baseline is provided."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:sched",
        fingerprint="fp_sched",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "status": "in_transit",
            "scheduled_eta": "2026-09-12T12:00:00Z",
            "estimated_delivery": "2026-09-12T15:30:00Z",  # 3.5 hours = 210 minutes delay
            "tracking_number": "T16",
            "carrier_name": "fedex",
        },
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.delay_minutes == 210.0


def test_karrio_location_with_valid_coordinates() -> None:
    """33. Test tracking milestone with valid coordinates produces EventLocation."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    canonical = KarrioNormalizer().normalize(batch.events[0])

    assert canonical.location is not None
    assert canonical.location.latitude == pytest.approx(30.2672, rel=1e-4)
    assert canonical.location.longitude == pytest.approx(-97.7431, rel=1e-4)
    assert "AUSTIN" in canonical.location.location_name
    assert canonical.quality == EventQuality.VALID
    adapter.close()


def test_karrio_location_with_invalid_coordinates() -> None:
    """34. Test invalid coordinates degrade event quality to PARTIAL."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:bad_coords",
        fingerprint="fp_bad_coords",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "status": "in_transit",
            "latitude": 105.0,  # Invalid latitude > 90
            "longitude": -89.0,
            "tracking_number": "T17",
            "carrier_name": "ups",
        },
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.quality == EventQuality.PARTIAL
    assert canonical.location is None
    assert any("Coordinate validation" in err for err in canonical.validation_errors)


def test_karrio_location_text_only() -> None:
    """35. Test text-only location produces EventLocation without fabricating coordinates."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:text_loc",
        fingerprint="fp_text_loc",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "status": "in_transit",
            "location": "MEMPHIS HUB, TN, US",
            "latitude": None,
            "longitude": None,
            "tracking_number": "T18",
            "carrier_name": "fedex",
        },
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.location is not None
    assert canonical.location.latitude is None
    assert canonical.location.longitude is None
    assert canonical.location.location_name == "MEMPHIS HUB, TN, US"


def test_karrio_shipment_correlation_explicit_param() -> None:
    """36. Test explicit shipment correlation passed via fetch parameter."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_DELIVERED)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(
        carrier_name="auspost",
        tracking_number="AP987654321AU",
        shipment_id="SHP-EXPLICIT-AU-001",
    )
    raw = batch.events[0]
    canonical = KarrioNormalizer().normalize(raw)

    assert canonical.correlation.shipment_id == "SHP-EXPLICIT-AU-001"
    adapter.close()


def test_karrio_shipment_correlation_metadata() -> None:
    """37. Test explicit shipment correlation extracted from tracker metadata."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    raw = batch.events[0]
    canonical = KarrioNormalizer().normalize(raw)

    assert canonical.correlation.shipment_id == "SHP-US-WEST-901"
    adapter.close()


def test_karrio_shipment_correlation_unresolved_default() -> None:
    """38. Test unmapped tracker leaves shipment_id as None."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_EXCEPTION)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(carrier_name="dhl", tracking_number="DHL8877665544")
    canonical = KarrioNormalizer().normalize(batch.events[0])

    assert canonical.correlation.shipment_id is None
    adapter.close()


def test_karrio_false_shipment_correlation_prevention() -> None:
    """39. Test that carrier_id or tracking_number is never falsely assigned as shipment_id."""
    raw = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:no_false",
        fingerprint="fp_no_false",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "status": "in_transit",
            "carrier_id": "carrier_fedex_us",
            "tracking_number": "123456789012",
            "carrier_name": "fedex",
        },
    )
    canonical = KarrioNormalizer().normalize(raw)
    assert canonical.correlation.shipment_id is None
    assert canonical.correlation.carrier_id == "carrier_fedex_us"
    assert canonical.correlation.custom_identifiers["tracking_number"] == "123456789012"


def test_karrio_shipment_event_bridge_behavior() -> None:
    """40. Test ShipmentEventBridge behavior with and without correlated shipment_id."""
    normalizer = KarrioNormalizer()

    # Case A: Uncorrelated event -> cannot persist
    raw_uncorr = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:bridge_uncorr",
        fingerprint="fp_bridge_uncorr",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={"status": "in_transit", "tracking_number": "T19", "carrier_name": "fedex"},
    )
    canonical_uncorr = normalizer.normalize(raw_uncorr)
    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical_uncorr) is False

    with pytest.raises(ValueError) as exc_info:
        ShipmentEventBridge.to_shipment_event_dict(canonical_uncorr)
    assert "missing required shipment_id correlation" in str(exc_info.value)

    # Case B: Correlated event -> can persist to ShipmentEvent dictionary
    raw_corr = RawEvent(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        provider_event_id="karrio:test:bridge_corr",
        fingerprint="fp_bridge_corr",
        source_timestamp=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
        raw_payload={
            "status": "in_transit",
            "shipment_id": "SHP-CORR-999",
            "tracking_number": "T20",
            "carrier_name": "fedex",
            "latitude": 35.042,
            "longitude": -89.976,
        },
    )
    canonical_corr = normalizer.normalize(raw_corr)
    assert ShipmentEventBridge.can_persist_to_shipment_event(canonical_corr) is True

    persisted_dict = ShipmentEventBridge.to_shipment_event_dict(canonical_corr)
    assert persisted_dict["shipment_id"] == "SHP-CORR-999"
    assert persisted_dict["status"] == "IN_TRANSIT"
    assert persisted_dict["latitude"] == pytest.approx(35.042, rel=1e-4)


def test_karrio_batch_listing_query() -> None:
    """41. Test fetch_batch queries GET /v1/trackers and returns multiple trackers."""
    batch_data = {
        "count": 2,
        "results": [SAMPLE_TRACKER_FEDEX, SAMPLE_TRACKER_DELIVERED],
    }
    client = make_mock_karrio_client(response_data=batch_data)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch_batch(carrier_name="fedex")
    assert len(batch.events) == 2
    assert batch.events[0].raw_payload["tracking_number"] == "123456789012"
    assert batch.events[1].raw_payload["tracking_number"] == "AP987654321AU"
    adapter.close()


def test_karrio_deterministic_idempotency_fingerprinting() -> None:
    """42. Test deterministic SHA-256 fingerprinting produces identical keys for identical state."""
    p1 = {
        "carrier_name": "fedex",
        "tracking_number": "123456789012",
        "code": "DP",
        "status": "in_transit",
        "date": "2026-09-08",
        "time": "14:30",
        "latitude": 35.042,
        "longitude": -89.976,
    }
    p2 = dict(p1)

    fp1 = KarrioAdapter.compute_fingerprint(p1)
    fp2 = KarrioAdapter.compute_fingerprint(p2)

    assert fp1 == fp2
    assert len(fp1) == 64


def test_karrio_consecutive_tracking_events_preserved() -> None:
    """43. Test that consecutive events for the same tracking number yield distinct fingerprints."""
    p1 = {
        "carrier_name": "fedex",
        "tracking_number": "123456789012",
        "code": "AR",
        "status": "in_transit",
        "date": "2026-09-08",
        "time": "12:00",
        "event_index": 0,
    }
    p2 = {
        "carrier_name": "fedex",
        "tracking_number": "123456789012",
        "code": "DP",
        "status": "in_transit",
        "date": "2026-09-08",
        "time": "14:30",
        "event_index": 1,
    }

    fp1 = KarrioAdapter.compute_fingerprint(p1)
    fp2 = KarrioAdapter.compute_fingerprint(p2)
    assert fp1 != fp2


def test_karrio_duplicate_event_suppression() -> None:
    """44. Test that IdempotencyEngine suppresses duplicate tracking milestones."""
    engine = IdempotencyEngine()
    payload = {
        "carrier_name": "dhl",
        "tracking_number": "DHL1234",
        "code": "PU",
        "status": "picked_up",
        "date": "2026-09-08",
        "time": "09:00",
    }
    fp = KarrioAdapter.compute_fingerprint(payload)

    is_new, _ = engine.check_and_record(fp)
    assert is_new is True

    is_new2, _ = engine.check_and_record(fp)
    assert is_new2 is False


def test_karrio_retry_behavior_transient_5xx() -> None:
    """45. Test bounded exponential retry policy handles transient HTTP 500/502/503."""
    attempts = 0

    def fail_twice_then_succeed(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(status_code=503, content=b'{"error": "Temporary Outage"}', request=request)
        return httpx.Response(
            status_code=200,
            content=json.dumps(SAMPLE_TRACKER_DELIVERED).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(fail_twice_then_succeed))
    cfg = ProviderConfig(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        retry=RetryConfig(max_retries=3, initial_delay_seconds=0.01),
    )
    adapter = KarrioAdapter(config=cfg, http_client=client)
    batch = adapter.fetch(carrier_name="auspost", tracking_number="AP987654321AU")

    assert attempts == 3
    assert len(batch.events) == 1
    adapter.close()


def test_karrio_http_429_rate_limit_error() -> None:
    """46. Test HTTP 429 response raises ProviderRateLimitError with Retry-After."""
    client = make_mock_karrio_client(
        status_code=429,
        response_data={"error": "Too Many Requests"},
        headers={"Retry-After": "30"},
    )
    adapter = KarrioAdapter(http_client=client)

    with pytest.raises(ProviderRateLimitError) as exc_info:
        adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert exc_info.value.retry_after_seconds == 30.0
    adapter.close()


def test_karrio_http_401_403_auth_error() -> None:
    """47. Test HTTP 401/403 responses raise ProviderAuthenticationError."""
    for status in (401, 403):
        client = make_mock_karrio_client(status_code=status, response_data={"error": "Invalid API token"})
        adapter = KarrioAdapter(http_client=client)
        with pytest.raises(ProviderAuthenticationError) as exc_info:
            adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
        assert exc_info.value.status_code == status
        adapter.close()


def test_karrio_http_404_not_found() -> None:
    """48. Test HTTP 404 response raises ProviderResponseError indicating tracker not found."""
    client = make_mock_karrio_client(status_code=404, response_data={"error": "Tracker not found"})
    adapter = KarrioAdapter(http_client=client)

    with pytest.raises(ProviderResponseError) as exc_info:
        adapter.fetch(carrier_name="fedex", tracking_number="NON_EXISTENT_TRACKING")
    assert exc_info.value.status_code == 404
    assert "not found" in str(exc_info.value).lower()
    adapter.close()


def test_karrio_timeout_handling() -> None:
    """49. Test request timeout raises ProviderTimeoutError."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Karrio server connection timed out")

    client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    adapter = KarrioAdapter(http_client=client)

    with pytest.raises(ProviderTimeoutError) as exc_info:
        adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert "timeout" in str(exc_info.value).lower()
    adapter.close()


def test_karrio_connection_error_handling() -> None:
    """50. Test client network failure raises ProviderConnectionError."""
    def error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to connect to Karrio port 5002")

    client = httpx.Client(transport=httpx.MockTransport(error_handler))
    cfg = ProviderConfig(
        provider_name="karrio",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        retry=RetryConfig(max_retries=1, initial_delay_seconds=0.01),
    )
    adapter = KarrioAdapter(config=cfg, http_client=client)

    with pytest.raises(ProviderConnectionError) as exc_info:
        adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert "network failure" in str(exc_info.value).lower()
    adapter.close()


def test_karrio_malformed_json_response() -> None:
    """51. Test non-JSON response raises ProviderResponseError."""
    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=b"INVALID_HTML_RESPONSE", headers={"Content-Type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(malformed_handler))
    adapter = KarrioAdapter(http_client=client)

    with pytest.raises(ProviderResponseError) as exc_info:
        adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert "valid json" in str(exc_info.value).lower()
    adapter.close()


def test_karrio_health_check_healthy() -> None:
    """52. Test diagnostic health check returns HEALTHY on 200 with valid JSON list."""
    client = make_mock_karrio_client(response_data={"results": [SAMPLE_TRACKER_FEDEX]})
    adapter = KarrioAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.HEALTHY
    assert health.details["configured"] is True
    adapter.close()


def test_karrio_health_check_unconfigured() -> None:
    """53. Test diagnostic health check returns UNCONFIGURED when API token is missing."""
    resolver = SecretResolver()
    adapter = KarrioAdapter(secret=None, secret_resolver=resolver)
    health = adapter.health_check()

    assert health.status == ProviderHealthStatus.UNCONFIGURED
    assert health.details["error_category"] == "CONFIGURATION"
    adapter.close()


def test_karrio_health_check_unhealthy_auth() -> None:
    """54. Test diagnostic health check returns UNHEALTHY when probe receives 401/403."""
    client = make_mock_karrio_client(status_code=401, response_data={"error": "Unauthorized"})
    adapter = KarrioAdapter(secret="bad_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.UNHEALTHY
    assert health.details["error_category"] == "AUTHENTICATION"
    adapter.close()


def test_karrio_health_check_degraded_rate_limit() -> None:
    """55. Test diagnostic health check returns DEGRADED when probe receives 429."""
    client = make_mock_karrio_client(status_code=429, response_data={"error": "Too Many Requests"})
    adapter = KarrioAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.DEGRADED
    assert health.details["error_category"] == "RATE_LIMIT"
    adapter.close()


def test_karrio_health_check_server_error() -> None:
    """56. Test diagnostic health check returns UNHEALTHY when probe receives 500/503."""
    client = make_mock_karrio_client(status_code=503, response_data={"error": "Unavailable"})
    adapter = KarrioAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.UNHEALTHY
    assert health.details["error_category"] == "UPSTREAM"
    adapter.close()


def test_karrio_health_check_timeout() -> None:
    """57. Test diagnostic health check returns DEGRADED when probe times out."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Health probe timeout")

    client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
    adapter = KarrioAdapter(secret="valid_key", http_client=client)

    health = adapter.health_check()
    assert health.status == ProviderHealthStatus.DEGRADED
    assert health.details["error_category"] == "TIMEOUT"
    adapter.close()


def test_karrio_logging_and_credential_redaction() -> None:
    """58. Test secret redaction ensures Karrio API key is never exposed in logs or payloads."""
    secret = "secret_karrio_token_999888"
    sanitized = SecretResolver.sanitize_payload({
        "karrio_api_key": secret,
        "api_key": secret,
        "token": secret,
    })
    assert sanitized["karrio_api_key"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"


def test_karrio_registry_integration() -> None:
    """59. Test KarrioAdapter discovery and instantiation through default_provider_registry."""
    assert default_provider_registry.is_registered("karrio")
    adapter_cls = default_provider_registry.get_adapter_cls("karrio")
    assert adapter_cls is KarrioAdapter

    inst = default_provider_registry.create_adapter("karrio")
    assert isinstance(inst, KarrioAdapter)


def test_karrio_polling_job_creation() -> None:
    """60. Test create_karrio_polling_job helper produces valid ScheduledIngestionJob."""
    job = create_karrio_polling_job(
        job_id="karrio_fedex_poll_1",
        carrier_name="fedex",
        tracking_number="123456789012",
        cron_or_interval="interval:15",
        shipment_id="SHP-US-001",
        organization_id="org_enterprise_logistics",
    )
    assert isinstance(job, ScheduledIngestionJob)
    assert job.job_id == "karrio_fedex_poll_1"
    assert job.provider_name == "karrio"
    assert job.parameters["carrier_name"] == "fedex"
    assert job.parameters["tracking_number"] == "123456789012"
    assert job.parameters["shipment_id"] == "SHP-US-001"
    assert job.organization_id == "org_enterprise_logistics"


def test_karrio_webhook_signature_verification() -> None:
    """61. Test KarrioWebhookReceiver verifies HMAC-SHA256 signature and shared secret."""
    receiver = KarrioWebhookReceiver()
    secret = "webhook_secret_key_123"
    body = b'{"event": "tracker_updated", "data": {"tracking_number": "123", "carrier_name": "fedex"}}'

    # Compute valid HMAC-SHA256
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert receiver.verify_signature(body, sig, secret) is True

    # Direct token match
    assert receiver.verify_signature(body, secret, secret) is True


def test_karrio_webhook_signature_rejection() -> None:
    """62. Test KarrioWebhookReceiver rejects invalid signatures."""
    receiver = KarrioWebhookReceiver()
    secret = "webhook_secret_key_123"
    body = b'{"event": "tracker_updated"}'

    assert receiver.verify_signature(body, "invalid_sig_abc", secret) is False
    assert receiver.verify_signature(body, "", secret) is False
    assert receiver.verify_signature(body, "sig", "") is False


def test_karrio_webhook_payload_parsing() -> None:
    """63. Test KarrioWebhookReceiver parses wrapped {"event": "...", "data": {...}} payload."""
    receiver = KarrioWebhookReceiver()
    wrapped_payload = {
        "event": "tracker_updated",
        "data": {
            "id": "trk_webhook_1",
            "carrier_name": "dhl",
            "tracking_number": "DHL999",
            "status": "delivered",
        },
    }
    raw_body = json.dumps(wrapped_payload).encode("utf-8")
    parsed = receiver.parse_payload(raw_body, headers={})

    assert parsed["tracking_number"] == "DHL999"
    assert parsed["status"] == "delivered"
    assert parsed["webhook_event"] == "tracker_updated"


def test_karrio_tenant_org_isolation() -> None:
    """64. Test tenant/org ID propagation in raw events and deterministic fingerprinting."""
    client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_DELIVERED)
    adapter = KarrioAdapter(http_client=client)

    batch = adapter.fetch(
        carrier_name="auspost",
        tracking_number="AP987654321AU",
        org_id="org_apac_logistics",
    )
    event = batch.events[0]
    assert event.org_id == "org_apac_logistics"

    canonical = KarrioNormalizer().normalize(event)
    assert canonical.org_id == "org_apac_logistics"
    adapter.close()


def test_karrio_full_pipeline_integration() -> None:
    """65. Test end-to-end flow: IngestionService -> Adapter -> RawStorage -> Normalizer -> CanonicalStorage."""
    raw_storage = InMemoryRawEventStorage()
    canonical_storage = InMemoryCanonicalEventStorage()

    mock_client = make_mock_karrio_client(response_data=SAMPLE_TRACKER_FEDEX)
    adapter = KarrioAdapter(http_client=mock_client)

    # 1. Ingestion Step
    batch = adapter.fetch(carrier_name="fedex", tracking_number="123456789012")
    assert len(batch.events) == 2
    raw_event = batch.events[0]
    raw_storage.store_batch(batch)

    stored_raw = raw_storage.get_event(raw_event.id)
    assert stored_raw is not None

    # 2. Normalization Step
    normalizer = KarrioNormalizer()
    assert normalizer.can_normalize(stored_raw) is True

    canonical_event = normalizer.normalize(stored_raw)
    assert canonical_event.event_type == CanonicalEventType.SHIPMENT_STATUS
    assert canonical_event.severity == EventSeverity.INFO
    assert canonical_event.status == "PICKED_UP"
    assert canonical_event.correlation.shipment_id == "SHP-US-WEST-901"

    # 3. Canonical Storage Step
    canonical_id = canonical_storage.store(canonical_event)
    assert canonical_id == canonical_event.event_id

    retrieved = canonical_storage.get_event(canonical_id)
    assert retrieved is not None
    assert retrieved.provider == "karrio"
    assert retrieved.correlation.custom_identifiers["tracking_number"] == "123456789012"

    adapter.close()
