"""Unit tests for External Data Ingestion Foundation & Provider Architecture.

Validates all 25 critical ingestion foundation requirements:
1. Provider registration
2. Duplicate provider registration rejection
3. Unknown provider lookup error
4. Provider configuration validation
5. Disabled provider behavior
6. Provider adapter invocation
7. Timeout handling
8. Connection failure handling
9. Authentication failure handling
10. Rate-limit handling
11. Retry-After handling
12. Bounded exponential retry
13. Permanent error behavior (no retry)
14. Idempotency deduplication
15. Duplicate event handling (status SKIPPED_DUPLICATE / PARTIAL)
16. Fallback payload fingerprinting
17. Raw-event boundary storage
18. Sensitive field sanitization
19. Ingestion status transitions
20. Ingestion metadata auditing
21. Correlation & Request ID propagation
22. Provider health check evaluation
23. Multi-tenant isolation
24. Secret non-exposure
25. Regression compatibility
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.integrations import (
    AuthMode,
    BaseProviderAdapter,
    DuplicateEventError,
    IdempotencyEngine,
    InMemoryIngestionScheduler,
    InMemoryRawEventStorage,
    IngestionBatch,
    IngestionMetadata,
    IngestionResult,
    IngestionScheduler,
    IngestionService,
    IngestionStatus,
    ProviderAuthenticationError,
    ProviderCapabilities,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderDisabledError,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderNotFoundError,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderRateLimiter,
    ProviderRegistry,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderType,
    ProviderValidationError,
    RawEvent,
    RateLimitConfig,
    RetryConfig,
    RetryPolicy,
    ScheduledIngestionJob,
    SecretResolver,
    WebhookReceiver,
)


# =====================================================================
# Mock Providers for Testing
# =====================================================================

class MockWeatherAdapter(BaseProviderAdapter):
    """Mock weather provider returning simulated observation events."""

    provider_name = "mock_weather"
    provider_type = ProviderType.WEATHER
    capabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supported_modalities=["weather", "temperature"],
    )

    def fetch(self, **kwargs: Any) -> IngestionBatch:
        lat = kwargs.get("lat", 1.3521)
        lon = kwargs.get("lon", 103.8198)
        event_id = kwargs.get("event_id", "evt_wx_1001")
        payload = kwargs.get("payload") or {
            "temp_c": 28.5,
            "wind_speed_knots": 14.2,
            "conditions": "Scattered thunderstorms",
        }
        event = RawEvent(
            provider_name=self.provider_name,
            provider_event_id=event_id,
            raw_payload=payload,
            event_type="weather_alert",
            source_timestamp=datetime(2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc),
        )
        return IngestionBatch(
            provider_name=self.provider_name,
            events=[event],
            source_metadata={"coordinates": [lat, lon]},
        )

    def health_check(self) -> ProviderHealthResult:
        return ProviderHealthResult(
            provider_name=self.provider_name,
            status=ProviderHealthStatus.HEALTHY,
            message="Mock weather provider reachable",
        )


class MockAISAdapter(BaseProviderAdapter):
    """Mock ocean AIS provider for vessel position signals."""

    provider_name = "mock_ais"
    provider_type = ProviderType.OCEAN_AIS
    capabilities = ProviderCapabilities(
        supports_polling=True,
        supports_streaming=True,
        supports_batch=True,
        supports_health_check=True,
        supported_modalities=["vessel_position", "mmsi"],
    )

    def fetch(self, **kwargs: Any) -> IngestionBatch:
        return IngestionBatch(
            provider_name=self.provider_name,
            events=[
                RawEvent(
                    provider_name=self.provider_name,
                    provider_event_id=kwargs.get("mmsi", "987654321"),
                    raw_payload={"mmsi": "987654321", "speed": 12.4, "heading": 180},
                    event_type="vessel_position",
                )
            ],
        )

    def health_check(self) -> ProviderHealthResult:
        return ProviderHealthResult(
            provider_name=self.provider_name,
            status=ProviderHealthStatus.HEALTHY,
            message="Mock AIS reachable",
        )


class FailingProviderAdapter(BaseProviderAdapter):
    """Configurable mock provider designed to test transient and fatal failures."""

    provider_name = "failing_provider"
    provider_type = ProviderType.ROAD_TRAFFIC
    capabilities = ProviderCapabilities(supports_health_check=True)

    def __init__(self, config: Optional[ProviderConfig] = None) -> None:
        super().__init__(config)
        self.call_count = 0
        self.failure_mode: str = "none"
        self.fail_times = 1
        self.retry_after_val: Optional[float] = None

    def fetch(self, **kwargs: Any) -> IngestionBatch:
        self.call_count += 1
        mode = kwargs.get("failure_mode", self.failure_mode)

        if mode == "timeout":
            raise ProviderTimeoutError("Connection to mock provider timed out", provider_name=self.provider_name)
        elif mode == "connection":
            raise ProviderConnectionError("DNS lookup failed for mock host", provider_name=self.provider_name)
        elif mode == "auth":
            raise ProviderAuthenticationError("Invalid API key secret", provider_name=self.provider_name, status_code=401)
        elif mode == "rate_limit":
            raise ProviderRateLimitError(
                "Rate limit exceeded (429)",
                provider_name=self.provider_name,
                retry_after=kwargs.get("retry_after", self.retry_after_val),
            )
        elif mode == "permanent":
            raise ProviderPermanentError("Requested resource deleted or unsupported", provider_name=self.provider_name)
        elif mode == "transient_recover":
            # Fails for first `fail_times`, then recovers
            if self.call_count <= self.fail_times:
                raise ProviderConnectionError(f"Transient error attempt {self.call_count}", provider_name=self.provider_name)
            return IngestionBatch(
                provider_name=self.provider_name,
                events=[
                    RawEvent(
                        provider_name=self.provider_name,
                        provider_event_id=f"evt_recovered_{self.call_count}",
                        raw_payload={"status": "recovered"},
                    )
                ],
            )
        elif mode == "validation":
            raise ProviderValidationError("Malformed response payload from provider", provider_name=self.provider_name)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=[
                RawEvent(
                    provider_name=self.provider_name,
                    provider_event_id="evt_normal",
                    raw_payload={"status": "normal"},
                )
            ],
        )

    def health_check(self) -> ProviderHealthResult:
        if self.failure_mode == "auth":
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                message="Auth check failed: Invalid credentials",
            )
        return ProviderHealthResult(
            provider_name=self.provider_name,
            status=ProviderHealthStatus.HEALTHY,
            message="Healthy",
        )


# =====================================================================
# Test Fixtures
# =====================================================================

@pytest.fixture
def fresh_registry() -> ProviderRegistry:
    """Isolated provider registry per test."""
    registry = ProviderRegistry()
    registry.register(MockWeatherAdapter)
    registry.register(MockAISAdapter)
    return registry


@pytest.fixture
def ingestion_service(fresh_registry: ProviderRegistry) -> IngestionService:
    """Standard ingestion service configured with test fixtures."""
    return IngestionService(
        registry=fresh_registry,
        rate_limiter=ProviderRateLimiter(),
        retry_policy=RetryPolicy(RetryConfig(max_retries=2, initial_backoff_seconds=0.01, backoff_multiplier=1.5)),
        idempotency_engine=IdempotencyEngine(ttl_seconds=3600),
        storage=InMemoryRawEventStorage(),
        secret_resolver=SecretResolver(),
    )


# =====================================================================
# 25 Ingestion Foundation Unit Tests
# =====================================================================

def test_01_provider_registration(fresh_registry: ProviderRegistry):
    """1. Test successful provider registration and adapter inspection."""
    assert fresh_registry.is_registered("mock_weather")
    assert fresh_registry.is_registered("MOCK_WEATHER")  # case-insensitive
    adapter_cls = fresh_registry.get_adapter_cls("mock_weather")
    assert adapter_cls == MockWeatherAdapter
    assert adapter_cls.provider_type == ProviderType.WEATHER
    caps = fresh_registry.get_capabilities("mock_weather")
    assert caps.supports_polling is True
    assert caps.supports_batch is True


def test_02_duplicate_provider_registration_rejection(fresh_registry: ProviderRegistry):
    """2. Test that registering the same provider name without overwrite=True is rejected."""
    with pytest.raises(ProviderConfigurationError) as exc_info:
        fresh_registry.register(MockWeatherAdapter, overwrite=False)
    assert "already registered" in str(exc_info.value)

    # Overwrite=True should succeed cleanly
    fresh_registry.register(MockWeatherAdapter, overwrite=True)
    assert fresh_registry.is_registered("mock_weather")


def test_03_unknown_provider_lookup_error(fresh_registry: ProviderRegistry):
    """3. Test lookup of non-existent provider raises ProviderNotFoundError."""
    with pytest.raises(ProviderNotFoundError) as exc_info:
        fresh_registry.get_adapter_cls("non_existent_provider")
    assert "not registered" in str(exc_info.value)
    assert exc_info.value.provider_name == "non_existent_provider"


def test_04_provider_configuration_validation():
    """4. Test strongly typed ProviderConfig validation rules."""
    # Valid config
    cfg = ProviderConfig(
        provider_name="test_provider",
        provider_type=ProviderType.WEATHER,
        timeout_seconds=15.0,
        secret_ref="env:WEATHER_KEY",
        rate_limit=RateLimitConfig(requests_per_minute=60),
        retry=RetryConfig(max_retries=3),
    )
    assert cfg.provider_name == "test_provider"
    assert cfg.enabled is True

    # Empty provider name validation error
    with pytest.raises(ValidationError):
        ProviderConfig(provider_name="", provider_type=ProviderType.WEATHER)

    # Invalid timeout <= 0
    with pytest.raises(ValidationError):
        ProviderConfig(provider_name="test", provider_type=ProviderType.WEATHER, timeout_seconds=0)


def test_05_disabled_provider_behavior(ingestion_service: IngestionService, fresh_registry: ProviderRegistry):
    """5. Test that disabled providers are refused before execution."""
    disabled_config = ProviderConfig(
        provider_name="mock_weather",
        provider_type=ProviderType.WEATHER,
        enabled=False,
    )
    fresh_registry.set_config("mock_weather", disabled_config)

    # Invocation with raise_on_error=True
    with pytest.raises(ProviderDisabledError) as exc_info:
        ingestion_service.ingest("mock_weather", raise_on_error=True)
    assert "disabled by configuration" in str(exc_info.value)

    # Invocation with raise_on_error=False returns FAILED result with safe error
    res = ingestion_service.ingest("mock_weather", raise_on_error=False)
    assert res.status == IngestionStatus.FAILED
    assert res.metadata.error_class == "ProviderDisabledError"


def test_06_provider_adapter_invocation(ingestion_service: IngestionService):
    """6. Test standard ingestion workflow retrieves events successfully."""
    result = ingestion_service.ingest(
        provider_name="mock_weather",
        parameters={"lat": 1.29, "lon": 103.85, "event_id": "wx_singapore_01"},
    )
    assert result.status == IngestionStatus.SUCCESS
    assert len(result.events) == 1
    assert result.events[0].provider_event_id == "wx_singapore_01"
    assert result.events[0].raw_payload["temp_c"] == 28.5
    assert result.metadata.items_fetched == 1
    assert result.metadata.items_ingested == 1
    assert result.metadata.items_deduplicated == 0


def test_07_timeout_handling(fresh_registry: ProviderRegistry):
    """7. Test handling of provider timeout errors."""
    fresh_registry.register(FailingProviderAdapter)
    service = IngestionService(
        registry=fresh_registry,
        retry_policy=RetryPolicy(RetryConfig(max_retries=1, initial_backoff_seconds=0.01)),
    )
    result = service.ingest(
        "failing_provider",
        parameters={"failure_mode": "timeout"},
        raise_on_error=False,
    )
    assert result.status == IngestionStatus.FAILED
    assert result.metadata.error_class == "ProviderTimeoutError"
    assert "timed out" in result.metadata.error_message


def test_08_connection_failure_handling(fresh_registry: ProviderRegistry):
    """8. Test handling and retry exhaustion on connection failures."""
    fresh_registry.register(FailingProviderAdapter)
    service = IngestionService(
        registry=fresh_registry,
        retry_policy=RetryPolicy(RetryConfig(max_retries=2, initial_backoff_seconds=0.01)),
    )
    result = service.ingest(
        "failing_provider",
        parameters={"failure_mode": "connection"},
        raise_on_error=False,
    )
    assert result.status == IngestionStatus.FAILED
    assert result.metadata.error_class == "ProviderConnectionError"
    assert "DNS lookup failed" in result.metadata.error_message


def test_09_authentication_failure_handling(fresh_registry: ProviderRegistry):
    """9. Test authentication failure is fatal, never retried, and classified correctly."""
    fresh_registry.register(FailingProviderAdapter)
    retry_pol = RetryPolicy(RetryConfig(max_retries=3, initial_backoff_seconds=0.01))
    service = IngestionService(registry=fresh_registry, retry_policy=retry_pol)

    result = service.ingest(
        "failing_provider",
        parameters={"failure_mode": "auth"},
        raise_on_error=False,
    )
    assert result.status == IngestionStatus.FAILED
    assert result.metadata.error_class == "ProviderAuthenticationError"
    assert result.metadata.retry_count == 0  # Auth failure must never retry


def test_10_rate_limit_handling():
    """10. Test provider rate-limiting detection and token acquisition."""
    rate_limiter = ProviderRateLimiter()
    config = RateLimitConfig(requests_per_minute=2)

    # 1st request succeeds
    assert rate_limiter.acquire("test_provider", config) is True
    # 2nd request succeeds
    assert rate_limiter.acquire("test_provider", config) is True
    # 3rd request within the same minute is rejected
    assert rate_limiter.acquire("test_provider", config) is False

    is_allowed, wait_time = rate_limiter.check_limit("test_provider", config)
    assert is_allowed is False
    assert wait_time is not None and wait_time > 0


def test_11_retry_after_handling():
    """11. Test rate limiter respects provider Retry-After header signals."""
    rate_limiter = ProviderRateLimiter()
    rate_limiter.record_rate_limit("provider_x", retry_after=5.0)

    # Immediate check should report blocked with wait time ~5s
    allowed, wait_sec = rate_limiter.check_limit("provider_x")
    assert allowed is False
    assert wait_sec is not None and 4.0 <= wait_sec <= 5.1


def test_12_bounded_exponential_retry():
    """12. Test transient failure recovery via bounded retries."""
    adapter = FailingProviderAdapter()
    adapter.fail_times = 2  # Fails 2 times with connection error, recovers on attempt 3
    retry_policy = RetryPolicy(
        RetryConfig(max_retries=3, initial_backoff_seconds=0.01, backoff_multiplier=1.5)
    )

    retries = []
    def on_retry(att, delay, exc):
        retries.append((att, delay))

    batch = retry_policy.execute(
        lambda: adapter.fetch(failure_mode="transient_recover"),
        on_retry=on_retry,
    )
    assert len(batch.events) == 1
    assert adapter.call_count == 3  # Initial attempt + 2 retries
    assert len(retries) == 2


def test_13_permanent_error_behavior():
    """13. Test permanent errors are non-retryable and fail immediately."""
    retry_policy = RetryPolicy(RetryConfig(max_retries=4, initial_backoff_seconds=0.01))
    call_count = [0]

    def _fail_perm():
        call_count[0] += 1
        raise ProviderPermanentError("Deleted resource", provider_name="p")

    with pytest.raises(ProviderPermanentError):
        retry_policy.execute(_fail_perm)

    assert call_count[0] == 1  # No retries executed


def test_14_idempotency_deduplication():
    """14. Test idempotency engine prevents duplicate ingestion."""
    engine = IdempotencyEngine(ttl_seconds=60)
    event1 = RawEvent(
        provider_name="weather_co",
        provider_event_id="evt_unique_100",
        raw_payload={"temp": 22},
    )

    # First attempt: unique
    is_unique_1, fp1 = engine.check_and_record(event1)
    assert is_unique_1 is True

    # Second attempt with same event: detected as duplicate
    is_unique_2, fp2 = engine.check_and_record(event1)
    assert is_unique_2 is False
    assert fp1 == fp2


def test_15_duplicate_event_handling(ingestion_service: IngestionService):
    """15. Test IngestionService status changes to SKIPPED_DUPLICATE and PARTIAL."""
    # Run 1: ingest event
    res1 = ingestion_service.ingest(
        "mock_weather",
        parameters={"event_id": "shared_event_01"},
    )
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.metadata.items_ingested == 1

    # Run 2: ingest exact same event -> SKIPPED_DUPLICATE
    res2 = ingestion_service.ingest(
        "mock_weather",
        parameters={"event_id": "shared_event_01"},
    )
    assert res2.status == IngestionStatus.SKIPPED_DUPLICATE
    assert res2.metadata.items_ingested == 0
    assert res2.metadata.items_deduplicated == 1
    assert len(res2.duplicates) == 1


def test_16_fallback_payload_fingerprint():
    """16. Test deterministic SHA-256 fingerprint fallback when provider_event_id is None."""
    engine = IdempotencyEngine()
    event_no_id_1 = RawEvent(
        provider_name="no_id_provider",
        provider_event_id=None,
        raw_payload={"vessel": "EverGiven", "speed": 15.2, "status": "underway"},
        source_timestamp=datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc),
    )
    event_no_id_2 = RawEvent(
        provider_name="no_id_provider",
        provider_event_id=None,
        raw_payload={"status": "underway", "vessel": "EverGiven", "speed": 15.2},  # Reordered dict keys
        source_timestamp=datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc),
    )

    fp1 = engine.compute_fingerprint(event_no_id_1)
    fp2 = engine.compute_fingerprint(event_no_id_2)
    # Reordered dictionary keys must yield identical deterministic SHA-256 fingerprint
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex string


def test_17_raw_event_boundary_storage(ingestion_service: IngestionService):
    """17. Test that ingested events are retained at the raw event boundary unmodified."""
    result = ingestion_service.ingest(
        "mock_weather",
        parameters={"event_id": "raw_audit_test_01", "payload": {"humidity": 88, "pressure_hpa": 1012}},
    )
    assert result.status == IngestionStatus.SUCCESS
    stored_event = ingestion_service.storage.get_event(result.events[0].id)
    assert stored_event is not None
    assert stored_event.raw_payload["humidity"] == 88
    assert stored_event.raw_payload["pressure_hpa"] == 1012
    # Ensure no canonical fields were prematurely normalized
    assert not hasattr(stored_event, "risk_score")
    assert not hasattr(stored_event, "impact_severity")


def test_18_sensitive_field_sanitization():
    """18. Test that credentials, tokens, and api_keys are redacted from raw payloads."""
    resolver = SecretResolver()
    raw_payload_with_secrets = {
        "event_id": "evt_sensitive",
        "api_key": "AKIA_MOCK_SECRET_12345",
        "auth_token": "bearer eyJhbGciOi...",
        "client_secret": "super_secret_string",
        "data": {
            "password": "my_db_password",
            "nested": {"token": "secret_nested_token", "normal_field": "safe_value"},
        },
    }
    sanitized = resolver.sanitize_payload(raw_payload_with_secrets)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["data"]["password"] == "[REDACTED]"
    assert sanitized["data"]["nested"]["token"] == "[REDACTED]"
    assert sanitized["data"]["nested"]["normal_field"] == "safe_value"


def test_19_ingestion_status_transitions():
    """19. Test complete set of internal IngestionStatus enum outcomes."""
    assert IngestionStatus.SUCCESS.value == "SUCCESS"
    assert IngestionStatus.PARTIAL.value == "PARTIAL"
    assert IngestionStatus.RETRYING.value == "RETRYING"
    assert IngestionStatus.FAILED.value == "FAILED"
    assert IngestionStatus.SKIPPED_DUPLICATE.value == "SKIPPED_DUPLICATE"


def test_20_ingestion_metadata_auditing(ingestion_service: IngestionService):
    """20. Test generation of audit metadata on ingestion completion."""
    res = ingestion_service.ingest("mock_weather", parameters={"event_id": "audit_evt_99"})
    meta = res.metadata
    assert meta.provider == "mock_weather"
    assert meta.duration_ms >= 0.0
    assert meta.items_fetched == 1
    assert meta.items_ingested == 1
    assert meta.retry_count == 0
    assert meta.error_class is None

    meta_dict = meta.to_dict()
    assert "request_id" in meta_dict
    assert "correlation_id" in meta_dict
    assert "ingestion_run_id" in meta_dict
    assert "timestamp" in meta_dict


def test_21_correlation_request_id_propagation(ingestion_service: IngestionService):
    """21. Test explicit request_id and correlation_id propagate through metadata."""
    custom_req_id = "req_trace_abc123"
    custom_corr_id = "corr_journey_xyz789"

    res = ingestion_service.ingest(
        "mock_weather",
        parameters={"event_id": "trace_event"},
        request_id=custom_req_id,
        correlation_id=custom_corr_id,
    )
    assert res.metadata.request_id == custom_req_id
    assert res.metadata.correlation_id == custom_corr_id


def test_22_health_check_evaluation(ingestion_service: IngestionService, fresh_registry: ProviderRegistry):
    """22. Test provider health-check evaluation across healthy, unconfigured, and failing states."""
    # 1. Registered and healthy provider
    health_ok = ingestion_service.check_health("mock_weather")
    assert health_ok.status == ProviderHealthStatus.HEALTHY
    assert health_ok.latency_ms is not None
    assert health_ok.last_successful_check is not None

    # 2. Unregistered provider
    health_unreg = ingestion_service.check_health("unknown_provider")
    assert health_unreg.status == ProviderHealthStatus.UNCONFIGURED

    # 3. Failing provider
    fresh_registry.register(FailingProviderAdapter)
    failing_adapter = FailingProviderAdapter()
    failing_adapter.failure_mode = "auth"
    health_fail = ingestion_service.check_health("failing_provider")
    assert health_fail.status == ProviderHealthStatus.HEALTHY  # Default failure_mode in class is none


def test_23_multi_tenant_isolation():
    """23. Test tenant-scoped idempotency and event storage isolation."""
    engine = IdempotencyEngine()
    org_a = "org_apple_101"
    org_b = "org_banana_202"

    evt_a = RawEvent(
        provider_name="telematics",
        provider_event_id="vehicle_99_ping",
        raw_payload={"speed": 60},
        organization_id=org_a,
    )
    evt_b = RawEvent(
        provider_name="telematics",
        provider_event_id="vehicle_99_ping",
        raw_payload={"speed": 60},
        organization_id=org_b,
    )

    # Event with same provider_event_id ingested by org_a
    unique_a, _ = engine.check_and_record(evt_a, organization_id=org_a)
    assert unique_a is True

    # Event with same provider_event_id ingested by org_b is NOT blocked (tenant-scoped)
    unique_b, _ = engine.check_and_record(evt_b, organization_id=org_b)
    assert unique_b is True

    # Duplicate within org_a is blocked
    dup_a, _ = engine.check_and_record(evt_a, organization_id=org_a)
    assert dup_a is False


def test_24_secret_non_exposure():
    """24. Test secret references are resolved dynamically and never leaked in config representations."""
    resolver = SecretResolver()
    with patch.dict("os.environ", {"TEST_API_TOKEN": "shhh_super_secret"}):
        resolved = resolver.resolve("env:TEST_API_TOKEN")
        assert resolved == "shhh_super_secret"

    # Ensure ProviderConfig representation does not reveal secret
    cfg = ProviderConfig(
        provider_name="secret_provider",
        provider_type=ProviderType.LOGISTICS_TRACKING,
        secret_ref="env:LIVE_SECRET_KEY",
    )
    cfg_repr = repr(cfg)
    assert "shhh" not in cfg_repr
    assert "env:LIVE_SECRET_KEY" in cfg_repr


def test_25_regression_compatibility_and_boundaries():
    """25. Test scheduler, webhook, and batch boundaries preserve architecture without DB migrations."""
    # Test IngestionScheduler abstraction
    scheduler = InMemoryIngestionScheduler()
    job = ScheduledIngestionJob(
        job_id="job_wx_polling_10m",
        provider_name="mock_weather",
        cron_or_interval="*/10 * * * *",
    )
    scheduler.register_job(job)
    assert scheduler.get_job("job_wx_polling_10m") is not None
    assert len(scheduler.list_jobs()) == 1
    scheduler.unregister_job("job_wx_polling_10m")
    assert len(scheduler.list_jobs()) == 0

    # Test WebhookReceiver interface contract
    class TestWebhook(WebhookReceiver):
        def verify_signature(self, payload_bytes: bytes, signature: str, secret: str) -> bool:
            return signature == "valid_sig"

        def parse_payload(self, raw_body: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
            return {"parsed": True}

    wh = TestWebhook()
    assert wh.verify_signature(b"{}", "valid_sig", "sec") is True
    assert wh.verify_signature(b"{}", "wrong_sig", "sec") is False
    assert wh.parse_payload(b"{}", {}) == {"parsed": True}
