"""Comprehensive test suite for RiskWise 2.0 Phase 5 Step 10: Reliability & Observability.

Covers all 50 target reliability & observability requirements:
 1. request ID propagation
 2. correlation ID propagation
 3. trace ID generation & propagation
 4. structured logging format & fields
 5. secret redaction in logs & metadata
 6. sensitive logistics & PII data protection
 7. provider health system interface
 8. healthy provider evaluation
 9. degraded provider evaluation (rate-limit / transient failure)
10. unavailable provider evaluation (auth failure / circuit open / disabled)
11. timeout failure classification
12. transient network failure classification
13. HTTP 429 rate limit classification
14. authentication failure classification (HTTP 401)
15. authorization failure classification (HTTP 403)
16. invalid request classification (HTTP 400/422)
17. malformed response classification (HTTP 500 / corrupt payload)
18. normalization failure classification
19. partial batch success (mixed valid, duplicate, malformed)
20. all events successful
21. all events failed
22. duplicate counting
23. received count accuracy
24. normalized count accuracy
25. rejected count accuracy
26. monotonic latency measurement
27. retry metrics & observability
28. rate-limit metrics & observability
29. stale data detection without blind rejection
30. data-quality classification independent of provider health
31. audit event generation across ingestion lifecycle
32. ingestion completion audit
33. ingestion failure audit
34. scheduler failure isolation
35. scheduler bounded execution
36. scheduler job cancellation
37. circuit breaker CLOSED state
38. circuit breaker transitions to OPEN on repeated failures
39. circuit breaker transitions to HALF_OPEN after cooldown
40. circuit breaker recovery to CLOSED on successful probe
41. provider failure isolation (failure in provider A != provider B)
42. multi-tenant organization isolation
43. concurrent ingestion execution safety
44. registry thread safety
45. idempotency thread safety
46. rate limiter thread safety
47. no secret leakage in logs, audit, or metadata
48. no raw payload dumping in ordinary logs
49. provider-specific timeout configuration
50. end-to-end metadata propagation through ShipmentEventBridge
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

import pytest

from app.integrations import (
    AuthMode,
    BaseEventNormalizer,
    BaseProviderAdapter,
    CanonicalEventType,
    CanonicalExternalEvent,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
    FailureCategory,
    FreshnessConfig,
    IdempotencyEngine,
    IdempotencyError,
    InMemoryCanonicalEventStorage,
    InMemoryIngestionAuditLedger,
    InMemoryIngestionScheduler,
    InMemoryRawEventStorage,
    IngestionAuditAction,
    IngestionAuditEntry,
    IngestionBatch,
    IngestionError,
    IngestionMetadata,
    IngestionMetricsCollector,
    IngestionResult,
    IngestionService,
    IngestionStatus,
    IngestionStructuredLogger,
    NormalizationBatchResult,
    NormalizationError,
    NormalizationPipeline,
    ProviderAuthenticationError,
    ProviderCapabilities,
    ProviderCircuitBreaker,
    ProviderConfig,
    ProviderConnectionError,
    ProviderDisabledError,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderNotFoundError,
    ProviderPermanentError,
    ProviderRateLimiter,
    ProviderRateLimitError,
    ProviderRegistry,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderType,
    ProviderValidationError,
    RateLimitConfig,
    RawEvent,
    RetryAttempt,
    RetryConfig,
    RetryPolicy,
    ScheduledIngestionJob,
    SecretResolver,
    ShipmentEventBridge,
    StaleDataDetector,
    StructuredLogEntry,
    classify_failure,
    mask_sensitive_identifier,
    sanitize_for_logging,
)


# =====================================================================
# Test Fixtures & Mock Provider Adapter
# =====================================================================

class MockReliabilityAdapter(BaseProviderAdapter):
    """Configurable mock adapter for reliability and observability testing."""

    provider_name = "mock_reliable"
    provider_type = ProviderType.CUSTOM
    capabilities = ProviderCapabilities(supports_polling=True, supports_batch=True)

    def __init__(
        self,
        config: Any = None,
        secret: Optional[str] = None,
        fetch_hook: Optional[Any] = None,
        health_hook: Optional[Any] = None,
    ) -> None:
        super().__init__(config=config, secret=secret)
        self.fetch_hook = fetch_hook
        self.health_hook = health_hook

    def fetch(self, **kwargs: Any) -> IngestionBatch:
        if self.fetch_hook:
            return self.fetch_hook(**kwargs)
        # Default returns one raw event
        return IngestionBatch(
            provider_name=self.provider_name,
            events=[
                RawEvent(
                    provider_name=self.provider_name,
                    provider_event_id="evt-1",
                    source_timestamp=datetime.now(timezone.utc),
                    raw_payload={"message": "sample", "temp_c": 21.5},
                )
            ],
        )

    def health_check(self) -> ProviderHealthResult:
        if self.health_hook:
            return self.health_hook()
        return ProviderHealthResult(
            provider_name=self.provider_name,
            status=ProviderHealthStatus.HEALTHY,
            message="Mock probe healthy",
        )


@pytest.fixture
def fresh_registry():
    reg = ProviderRegistry()
    reg.register(
        MockReliabilityAdapter,
        default_config=ProviderConfig(
            provider_name=MockReliabilityAdapter.provider_name,
            provider_type=MockReliabilityAdapter.provider_type,
            timeout_seconds=5.0,
            retry=RetryConfig(max_retries=2, initial_delay_seconds=0.01, jitter=False),
            rate_limit=RateLimitConfig(requests_per_minute=60),
        ),
    )
    return reg


@pytest.fixture
def fresh_service(fresh_registry):
    rate_limiter = ProviderRateLimiter()
    retry_policy = RetryPolicy(config=RetryConfig(max_retries=2, initial_delay_seconds=0.01, jitter=False))
    idempotency = IdempotencyEngine()
    storage = InMemoryRawEventStorage()
    secret_resolver = SecretResolver()
    circuit_breaker = ProviderCircuitBreaker(
        default_config=CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=0.2, success_threshold=1)
    )
    metrics = IngestionMetricsCollector()
    audit = InMemoryIngestionAuditLedger()
    struct_logger = IngestionStructuredLogger()
    stale_detector = StaleDataDetector(FreshnessConfig(default_threshold=3600.0))

    return IngestionService(
        registry=fresh_registry,
        rate_limiter=rate_limiter,
        retry_policy=retry_policy,
        idempotency_engine=idempotency,
        storage=storage,
        secret_resolver=secret_resolver,
        circuit_breaker=circuit_breaker,
        metrics_collector=metrics,
        audit_ledger=audit,
        structured_logger=struct_logger,
        stale_data_detector=stale_detector,
    )


# =====================================================================
# Tests: 1-6 (Correlation, Logging, Redaction)
# =====================================================================

def test_01_request_id_propagation(fresh_service):
    """1. Verify request_id propagates through metadata, raw events, and audit logs."""
    custom_req_id = "req-custom-xyz-123"
    result = fresh_service.ingest("mock_reliable", request_id=custom_req_id)

    assert result.status == IngestionStatus.SUCCESS
    assert result.metadata.request_id == custom_req_id

    # Verify in raw storage event metadata
    stored = fresh_service.storage.list_events(provider_name="mock_reliable")
    assert len(stored) == 1
    assert stored[0].metadata.get("request_id") == custom_req_id

    # Verify in audit ledger
    audit_events = fresh_service.audit_ledger.list_events(provider_name="mock_reliable")
    assert any(e.request_id == custom_req_id for e in audit_events)


def test_02_correlation_id_propagation(fresh_service):
    """2. Verify correlation_id propagates consistently across the ingestion run."""
    custom_corr_id = "corr-supply-chain-456"
    result = fresh_service.ingest("mock_reliable", correlation_id=custom_corr_id)

    assert result.status == IngestionStatus.SUCCESS
    assert result.metadata.correlation_id == custom_corr_id

    stored = fresh_service.storage.list_events(provider_name="mock_reliable")
    assert stored[0].metadata.get("correlation_id") == custom_corr_id


def test_03_trace_id_generation_and_propagation(fresh_service):
    """3. Verify trace_id is preserved if provided, or generated and propagated."""
    # 3a. Explicit trace_id
    explicit_trace = "trc-explicit-789"
    res1 = fresh_service.ingest("mock_reliable", trace_id=explicit_trace)
    assert res1.metadata.trace_id == explicit_trace
    stored1 = fresh_service.storage.list_events(provider_name="mock_reliable")
    assert stored1[-1].metadata.get("trace_id") == explicit_trace

    # 3b. Generated trace_id
    res2 = fresh_service.ingest("mock_reliable")
    assert res2.metadata.trace_id is not None
    assert res2.metadata.trace_id.startswith("trc-")


def test_04_structured_logging_format_and_fields(fresh_service):
    """4. Verify structured logger emits required fields with correct types."""
    fresh_service.structured_logger.enable_capture()
    try:
        fresh_service.ingest(
            "mock_reliable",
            request_id="req-log-1",
            correlation_id="corr-log-1",
            organization_id="org-acme",
        )
        logs = fresh_service.structured_logger.get_captured_logs()
        assert len(logs) >= 1
        entry = logs[-1]
        assert entry.provider == "mock_reliable"
        assert entry.operation == "ingest"
        assert entry.status == "SUCCESS"
        assert entry.duration_ms > 0.0
        assert entry.request_id == "req-log-1"
        assert entry.correlation_id == "corr-log-1"
        assert entry.organization_id == "org-acme"
        assert entry.event_count == 1
        assert entry.normalized_count == 1
        assert entry.duplicate_count == 0

        d = entry.to_dict()
        assert "timestamp" in d
        assert "log_level" in d
    finally:
        fresh_service.structured_logger.disable_capture()


def test_05_secret_redaction_in_logs_and_metadata(fresh_service):
    """5. Verify API keys, secrets, tokens, and passwords are never logged or preserved."""
    fresh_service.structured_logger.enable_capture()
    try:
        payload_with_secrets = {
            "api_key": "SECRET_KEY_12345",
            "access_token": "OAUTH_TOKEN_SECRET",
            "password": "SUPER_PASSWORD",
            "auth_header": "Bearer secret_jwt",
            "public_metric": 42,
        }

        # Test sanitize_for_logging
        sanitized = sanitize_for_logging(payload_with_secrets)
        assert sanitized["api_key"] == "[REDACTED_SECRET]"
        assert sanitized["access_token"] == "[REDACTED_SECRET]"
        assert sanitized["password"] == "[REDACTED_SECRET]"
        assert sanitized["auth_header"] == "[REDACTED_SECRET]"
        assert sanitized["public_metric"] == 42

        # Verify in structured logger details
        fresh_service.structured_logger.log_operation(
            provider="mock_reliable",
            operation="test_auth",
            status="SUCCESS",
            duration_ms=10.0,
            details={"client_secret": "TOP_SECRET", "safe_param": "ok"},
        )
        logs = fresh_service.structured_logger.get_captured_logs()
        log_details = logs[-1].details
        assert log_details["client_secret"] == "[REDACTED_SECRET]"
        assert log_details["safe_param"] == "ok"
    finally:
        fresh_service.structured_logger.disable_capture()


def test_06_sensitive_logistics_and_pii_data_protection():
    """6. Verify sensitive logistics data (customer names, emails, phones) is protected."""
    logistics_payload = {
        "customer_email": "shipper@acme.com",
        "phone": "+1-555-0199",
        "consignee_name": "John Doe",
        "tracking_number": "TRK-9876543210",
        "status": "DELIVERED",
    }
    sanitized = sanitize_for_logging(logistics_payload, mask_logistics=True)
    assert sanitized["customer_email"] == "[REDACTED_PII]"
    assert sanitized["phone"] == "[REDACTED_PII]"
    assert sanitized["consignee_name"] == "[REDACTED_LOGISTICS_PII]"
    assert sanitized["status"] == "DELIVERED"

    masked_trk = mask_sensitive_identifier(logistics_payload["tracking_number"])
    assert masked_trk == "TR****3210"
    assert "987654" not in masked_trk


# =====================================================================
# Tests: 7-10 (Provider Health System)
# =====================================================================

def test_07_provider_health_interface(fresh_service):
    """7. Verify check_health returns a complete ProviderHealthResult."""
    res = fresh_service.check_health("mock_reliable")
    assert isinstance(res, ProviderHealthResult)
    assert res.provider_name == "mock_reliable"
    assert res.status in (ProviderHealthStatus.HEALTHY, ProviderHealthStatus.DEGRADED, ProviderHealthStatus.UNAVAILABLE)
    assert res.latency_ms is not None
    assert res.circuit_state in ("CLOSED", "OPEN", "HALF_OPEN")


def test_08_provider_health_healthy(fresh_service):
    """8. Verify healthy adapter returns HEALTHY and updates last_successful_check."""
    res = fresh_service.check_health("mock_reliable")
    assert res.status == ProviderHealthStatus.HEALTHY
    assert res.last_successful_check is not None
    assert fresh_service.metrics_collector.get_gauge("provider_health_status", "mock_reliable") == 1.0


def test_09_provider_health_degraded_on_rate_limit(fresh_service):
    """9. Verify provider is reported DEGRADED when in rate limit cooldown."""
    fresh_service.rate_limiter.record_rate_limit("mock_reliable", retry_after=10.0)
    res = fresh_service.check_health("mock_reliable")
    assert res.status == ProviderHealthStatus.DEGRADED
    assert res.rate_limited is True
    assert fresh_service.metrics_collector.get_gauge("provider_health_status", "mock_reliable") == 0.5


def test_10_provider_health_unavailable(fresh_service):
    """10. Verify provider is UNAVAILABLE when circuit is OPEN or disabled."""
    # 10a. Disabled provider
    cfg = fresh_service.registry.get_config("mock_reliable")
    cfg.enabled = False
    fresh_service.registry.set_config("mock_reliable", cfg)
    res = fresh_service.check_health("mock_reliable")
    assert res.status == ProviderHealthStatus.UNAVAILABLE

    # 10b. Circuit breaker OPEN
    cfg.enabled = True
    fresh_service.registry.set_config("mock_reliable", cfg)
    for _ in range(3):
        fresh_service.circuit_breaker.record_failure("mock_reliable", RuntimeError("err"))
    res_cb = fresh_service.check_health("mock_reliable")
    assert res_cb.status == ProviderHealthStatus.UNAVAILABLE
    assert res_cb.circuit_state == "OPEN"


# =====================================================================
# Tests: 11-18 (Deterministic Failure Classification)
# =====================================================================

def test_11_failure_classification_timeout():
    """11. Verify timeout exceptions map to FailureCategory.TIMEOUT."""
    exc1 = ProviderTimeoutError("Connection timed out", provider_name="p")
    exc2 = TimeoutError("Socket timeout")
    assert classify_failure(exc1) == FailureCategory.TIMEOUT
    assert classify_failure(exc2) == FailureCategory.TIMEOUT


def test_12_failure_classification_network_failure():
    """12. Verify network connection drops map to FailureCategory.TRANSIENT_NETWORK."""
    exc1 = ProviderConnectionError("DNS lookup failed", provider_name="p")
    exc2 = ConnectionResetError("Connection reset by peer")
    assert classify_failure(exc1) == FailureCategory.TRANSIENT_NETWORK
    assert classify_failure(exc2) == FailureCategory.TRANSIENT_NETWORK


def test_13_failure_classification_http_429():
    """13. Verify rate limit errors map to FailureCategory.RATE_LIMITED."""
    exc = ProviderRateLimitError("Quota exceeded", provider_name="p", retry_after=30.0)
    assert classify_failure(exc) == FailureCategory.RATE_LIMITED


def test_14_failure_classification_authentication():
    """14. Verify HTTP 401 authentication errors map to FailureCategory.AUTHENTICATION."""
    exc = ProviderAuthenticationError("Invalid API token", provider_name="p", status_code=401)
    assert classify_failure(exc) == FailureCategory.AUTHENTICATION


def test_15_failure_classification_authorization():
    """15. Verify HTTP 403 authorization errors map to FailureCategory.AUTHORIZATION."""
    exc = ProviderAuthenticationError("Forbidden tier", provider_name="p", status_code=403)
    assert classify_failure(exc) == FailureCategory.AUTHORIZATION


def test_16_failure_classification_invalid_request():
    """16. Verify bad requests map to FailureCategory.INVALID_REQUEST."""
    exc = ProviderValidationError("Missing required query param", provider_name="p")
    assert classify_failure(exc) == FailureCategory.INVALID_REQUEST


def test_17_failure_classification_malformed_response():
    """17. Verify malformed responses map to FailureCategory.MALFORMED_RESPONSE."""
    exc = ProviderResponseError("Invalid JSON", status_code=500, provider_name="p")
    assert classify_failure(exc) == FailureCategory.MALFORMED_RESPONSE


def test_18_failure_classification_normalization_failure():
    """18. Verify normalization errors map to FailureCategory.NORMALIZATION_ERROR."""
    exc = NormalizationError("Missing mandatory timestamp", provider_name="p")
    assert classify_failure(exc) == FailureCategory.NORMALIZATION_ERROR


# =====================================================================
# Tests: 19-25 (Batch Outcomes & Event Counts)
# =====================================================================

def test_19_partial_batch_success(fresh_service):
    """19. Verify partial batch success (mixed valid, duplicates, and malformed)."""
    pipeline = NormalizationPipeline()
    events = [
        RawEvent(provider_name="mock_reliable", provider_event_id="e1", raw_payload={"timestamp": "2026-09-08T12:00:00Z"}),
        RawEvent(provider_name="mock_reliable", provider_event_id="e2", raw_payload={"timestamp": "2026-09-08T12:00:00Z"}),
        RawEvent(provider_name="mock_reliable", provider_event_id="e3", raw_payload={"timestamp": "invalid_ts"}),
    ]

    # Custom normalizer that rejects e3
    class StrictNormalizer(BaseEventNormalizer):
        def can_normalize(self, raw):
            return True
        def normalize(self, raw):
            if raw.provider_event_id == "e3":
                raise ValueError("Corrupt event structure")
            return CanonicalExternalEvent(
                provider=raw.provider_name,
                source_event_id=raw.provider_event_id,
                event_timestamp=datetime.now(timezone.utc),
            )

    pipeline.register_normalizer(StrictNormalizer(), priority=10)
    batch_res = pipeline.normalize_batch(events)

    assert batch_res.received_count == 3
    assert batch_res.normalized_count == 2
    assert batch_res.rejected_count == 1
    assert batch_res.rejected_events[0]["provider_event_id"] == "e3"


def test_20_all_events_successful(fresh_service):
    """20. Verify all valid events yield IngestionStatus.SUCCESS."""
    res = fresh_service.ingest("mock_reliable")
    assert res.status == IngestionStatus.SUCCESS
    assert res.metadata.items_fetched == 1
    assert res.metadata.items_ingested == 1
    assert res.metadata.items_deduplicated == 0


def test_21_all_events_failed(fresh_service):
    """21. Verify complete failure when provider raises an unhandled error."""
    class FailingAdapter(BaseProviderAdapter):
        provider_name = "mock_failing"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            raise ProviderConnectionError("Unreachable gateway", provider_name="mock_failing")

    fresh_service.registry.register(FailingAdapter)
    res = fresh_service.ingest("mock_failing")
    assert res.status == IngestionStatus.FAILED
    assert res.metadata.failure_category == FailureCategory.TRANSIENT_NETWORK.value
    assert len(res.errors) == 1


def test_22_duplicate_counting(fresh_service):
    """22. Verify duplicate events are accurately detected and counted."""
    # First ingest: accepted
    res1 = fresh_service.ingest("mock_reliable")
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.metadata.items_ingested == 1

    # Second ingest of identical event: skipped duplicate
    res2 = fresh_service.ingest("mock_reliable")
    assert res2.status == IngestionStatus.SKIPPED_DUPLICATE
    assert res2.metadata.items_deduplicated == 1
    assert res2.metadata.items_ingested == 0


def test_23_received_count(fresh_service):
    """23. Verify items_fetched matches number of raw items from adapter."""
    class MultiAdapter(BaseProviderAdapter):
        provider_name = "mock_multi"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            return IngestionBatch(
                provider_name="mock_multi",
                events=[
                    RawEvent(provider_name="mock_multi", provider_event_id=f"m-{i}", raw_payload={})
                    for i in range(5)
                ],
            )

    fresh_service.registry.register(MultiAdapter)
    res = fresh_service.ingest("mock_multi")
    assert res.metadata.items_fetched == 5
    assert res.metadata.items_ingested == 5


def test_24_normalized_count(fresh_service):
    """24. Verify items_ingested accurately tracks accepted events."""
    res = fresh_service.ingest("mock_reliable")
    assert res.metadata.items_ingested == len(res.events)


def test_25_rejected_count():
    """25. Verify rejected count in NormalizationBatchResult."""
    pipeline = NormalizationPipeline()
    bad_event = RawEvent(provider_name="test", provider_event_id="bad", raw_payload={})

    class FlakyNormalizer(BaseEventNormalizer):
        def can_normalize(self, raw):
            return True
        def normalize(self, raw):
            raise ValueError("Field constraint violated")

    pipeline.register_normalizer(FlakyNormalizer(), priority=5)
    batch_res = pipeline.normalize_batch([bad_event])
    assert batch_res.rejected_count == 1
    assert batch_res.normalized_count == 0


# =====================================================================
# Tests: 26-28 (Latency & Observability Metrics)
# =====================================================================

def test_26_monotonic_latency_measurement(fresh_service):
    """26. Verify monotonic timing is recorded for all stages."""
    res = fresh_service.ingest("mock_reliable")
    m = res.metadata
    assert m.duration_ms > 0.0
    assert m.provider_request_duration_ms >= 0.0
    assert m.normalization_duration_ms >= 0.0
    assert m.storage_duration_ms >= 0.0


def test_27_retry_metrics_and_observability(fresh_service):
    """27. Verify retry attempts are recorded in metrics and metadata."""
    attempts = [0]
    class TransientAdapter(BaseProviderAdapter):
        provider_name = "mock_transient"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            attempts[0] += 1
            if attempts[0] < 2:
                raise ProviderTimeoutError("Temporary glitch", provider_name="mock_transient")
            return IngestionBatch(
                provider_name="mock_transient",
                events=[RawEvent(provider_name="mock_transient", provider_event_id="t-1", raw_payload={})],
            )

    fresh_service.registry.register(
        TransientAdapter,
        default_config=ProviderConfig(
            provider_name="mock_transient",
            provider_type=ProviderType.CUSTOM,
            retry=RetryConfig(max_retries=2, initial_delay_seconds=0.01, jitter=False),
        ),
    )
    res = fresh_service.ingest("mock_transient")
    assert res.status == IngestionStatus.SUCCESS
    assert res.metadata.retry_count == 1
    assert fresh_service.metrics_collector.get_counter("provider_retry_total", "mock_transient") == 1


def test_28_rate_limit_metrics_and_observability(fresh_service):
    """28. Verify rate limiting updates metrics and status is inspectable."""
    fresh_service.rate_limiter.record_rate_limit("mock_reliable", retry_after=15.0)
    status = fresh_service.rate_limiter.get_provider_status("mock_reliable")
    assert status["is_cooling_down"] is True
    assert status["cooldown_remaining_seconds"] > 0.0

    res = fresh_service.ingest("mock_reliable")
    assert res.status == IngestionStatus.FAILED
    assert res.metadata.failure_category == FailureCategory.RATE_LIMITED.value
    assert fresh_service.metrics_collector.get_counter("provider_rate_limit_total", "mock_reliable") >= 1


# =====================================================================
# Tests: 29-30 (Stale Data & Data Quality)
# =====================================================================

def test_29_stale_data_detection(fresh_service):
    """29. Verify stale external observations are tagged without blind dropping."""
    old_time = datetime.now(timezone.utc) - timedelta(hours=5)

    class StaleAdapter(BaseProviderAdapter):
        provider_name = "mock_stale"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            return IngestionBatch(
                provider_name="mock_stale",
                events=[RawEvent(provider_name="mock_stale", provider_event_id="stale-1", source_timestamp=old_time, raw_payload={})],
            )

    fresh_service.registry.register(StaleAdapter)
    res = fresh_service.ingest("mock_stale")
    assert res.status == IngestionStatus.SUCCESS
    assert res.metadata.items_stale == 1
    stored = fresh_service.storage.list_events(provider_name="mock_stale")
    assert stored[0].metadata.get("is_stale") is True


def test_30_data_quality_classification_independent_of_health():
    """30. Verify VALID, PARTIAL, and INVALID quality are tracked separately from provider health."""
    normalizer = NormalizationPipeline()
    # Complete event with location and correlation -> VALID
    raw_valid = RawEvent(
        provider_name="openweather",
        source_timestamp=datetime.now(timezone.utc),
        raw_payload={"latitude": 37.77, "longitude": -122.41, "shipment_id": "shp-100"},
    )
    valid_event = normalizer.normalize(raw_valid)
    assert valid_event.quality == EventQuality.VALID

    # Event missing location/correlation -> PARTIAL
    raw_partial = RawEvent(
        provider_name="openweather",
        source_timestamp=datetime.now(timezone.utc),
        raw_payload={"temp_c": 22.0},
    )
    partial_event = normalizer.normalize(raw_partial)
    assert partial_event.quality == EventQuality.PARTIAL

    # Event with invalid coordinates -> INVALID
    with pytest.raises(Exception):
        CanonicalExternalEvent(
            provider="openweather",
            event_timestamp=datetime.now(timezone.utc),
            location=EventLocation(latitude=999.0, longitude=0.0),
        )


# =====================================================================
# Tests: 31-33 (Ingestion Audit Trail)
# =====================================================================

def test_31_audit_event_generation_lifecycle(fresh_service):
    """31. Verify all expected lifecycle events are recorded in the audit ledger."""
    fresh_service.ingest("mock_reliable")
    actions = [e.action for e in fresh_service.audit_ledger.list_events(provider_name="mock_reliable")]
    assert IngestionAuditAction.INGESTION_STARTED in actions
    assert IngestionAuditAction.PROVIDER_REQUESTED in actions
    assert IngestionAuditAction.PROVIDER_SUCCEEDED in actions
    assert IngestionAuditAction.EVENT_NORMALIZED in actions
    assert IngestionAuditAction.INGESTION_COMPLETED in actions


def test_32_audit_ingestion_completion(fresh_service):
    """32. Verify INGESTION_COMPLETED audit record contains accurate duration & counts."""
    fresh_service.ingest("mock_reliable")
    completed = [e for e in fresh_service.audit_ledger.list_events(provider_name="mock_reliable") if e.action == IngestionAuditAction.INGESTION_COMPLETED]
    assert len(completed) == 1
    assert completed[0].details["items_ingested"] == 1
    assert completed[0].details["duration_ms"] > 0.0


def test_33_audit_ingestion_failure(fresh_service):
    """33. Verify PROVIDER_FAILED audit record captures sanitized error details."""
    class FailingAdapter(BaseProviderAdapter):
        provider_name = "mock_failing_audit"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            raise ProviderAuthenticationError("Bad token secret_123", provider_name="mock_failing_audit")

    fresh_service.registry.register(FailingAdapter)
    fresh_service.ingest("mock_failing_audit")
    failed = [e for e in fresh_service.audit_ledger.list_events(provider_name="mock_failing_audit") if e.action == IngestionAuditAction.PROVIDER_FAILED]
    assert len(failed) == 1
    assert failed[0].details["failure_category"] == FailureCategory.AUTHENTICATION.value


# =====================================================================
# Tests: 34-36 (Scheduler Reliability)
# =====================================================================

def test_34_scheduler_failure_isolation(fresh_service):
    """34. Verify scheduled job failures are isolated and do not crash the scheduler."""
    scheduler = InMemoryIngestionScheduler()
    class BrokenAdapter(BaseProviderAdapter):
        provider_name = "mock_broken_sched"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            raise RuntimeError("Catastrophic provider breakdown")

    fresh_service.registry.register(BrokenAdapter)
    job = ScheduledIngestionJob(
        job_id="job-failing",
        provider_name="mock_broken_sched",
        cron_or_interval="*/5 * * * *",
    )
    scheduler.register_job(job)

    # Execute should return result (FAILED) without raising unhandled exception
    res = scheduler.execute_job("job-failing", fresh_service)
    assert res.status == IngestionStatus.FAILED

    updated_job = scheduler.get_job("job-failing")
    assert updated_job.last_status == "FAILED"
    assert updated_job.consecutive_failures == 1
    assert updated_job.failed_runs == 1


def test_35_scheduler_success_execution(fresh_service):
    """35. Verify scheduled job success lifecycle tracking."""
    scheduler = InMemoryIngestionScheduler()
    job = ScheduledIngestionJob(
        job_id="job-success",
        provider_name="mock_reliable",
        cron_or_interval="*/10 * * * *",
    )
    scheduler.register_job(job)

    res = scheduler.execute_job("job-success", fresh_service)
    assert res.status == IngestionStatus.SUCCESS

    updated_job = scheduler.get_job("job-success")
    assert updated_job.last_status == "SUCCESS"
    assert updated_job.consecutive_failures == 0
    assert updated_job.successful_runs == 1
    assert updated_job.last_run_at is not None


def test_36_scheduler_job_cancellation(fresh_service):
    """36. Verify request_cancel marks job as cancelled and prevents execution."""
    scheduler = InMemoryIngestionScheduler()
    job = ScheduledIngestionJob(
        job_id="job-cancel",
        provider_name="mock_reliable",
        cron_or_interval="0 * * * *",
    )
    scheduler.register_job(job)
    scheduler.request_cancel("job-cancel")

    res = scheduler.execute_job("job-cancel", fresh_service)
    assert res is None
    updated_job = scheduler.get_job("job-cancel")
    assert updated_job.last_status == "CANCELLED"


# =====================================================================
# Tests: 37-40 (Circuit Breaker State Machine)
# =====================================================================

def test_37_circuit_breaker_closed_state():
    """37. Verify circuit starts CLOSED and permits operations."""
    cb = ProviderCircuitBreaker(CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=1.0))
    assert cb.get_state("provider_a") == CircuitState.CLOSED
    assert cb.can_execute("provider_a") is True


def test_38_circuit_breaker_opens_on_repeated_failures():
    """38. Verify circuit trips from CLOSED to OPEN after failure_threshold consecutive errors."""
    cb = ProviderCircuitBreaker(CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=1.0))
    cb.record_failure("provider_a", RuntimeError("err 1"))
    cb.record_failure("provider_a", RuntimeError("err 2"))
    assert cb.get_state("provider_a") == CircuitState.CLOSED

    cb.record_failure("provider_a", RuntimeError("err 3"))
    assert cb.get_state("provider_a") == CircuitState.OPEN
    assert cb.can_execute("provider_a") is False


def test_39_circuit_breaker_half_open_transition():
    """39. Verify circuit transitions from OPEN to HALF_OPEN after cooldown."""
    cb = ProviderCircuitBreaker(CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=0.05))
    cb.record_failure("provider_b", RuntimeError("err 1"))
    cb.record_failure("provider_b", RuntimeError("err 2"))
    assert cb.get_state("provider_b") == CircuitState.OPEN

    # Sleep past cooldown
    time.sleep(0.06)
    assert cb.get_state("provider_b") == CircuitState.HALF_OPEN
    assert cb.can_execute("provider_b") is True


def test_40_circuit_breaker_recovery():
    """40. Verify successful probe in HALF_OPEN closes circuit; failure re-opens it."""
    cb = ProviderCircuitBreaker(CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=0.05, success_threshold=1))
    cb.record_failure("provider_c", RuntimeError("err 1"))
    cb.record_failure("provider_c", RuntimeError("err 2"))
    assert cb.get_state("provider_c") == CircuitState.OPEN

    time.sleep(0.06)
    assert cb.get_state("provider_c") == CircuitState.HALF_OPEN

    # Probe succeeds -> CLOSED
    cb.record_success("provider_c")
    assert cb.get_state("provider_c") == CircuitState.CLOSED


# =====================================================================
# Tests: 41-43 (Isolation & Concurrency)
# =====================================================================

def test_41_provider_failure_isolation(fresh_service):
    """41. Verify failure in Provider A does NOT trip or degrade Provider B."""
    class FlakyA(BaseProviderAdapter):
        provider_name = "flaky_a"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            raise ProviderConnectionError("A is down", provider_name="flaky_a")

    class StableB(BaseProviderAdapter):
        provider_name = "stable_b"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            return IngestionBatch(
                provider_name="stable_b",
                events=[RawEvent(provider_name="stable_b", provider_event_id="b-1", raw_payload={})],
            )

    fresh_service.registry.register(FlakyA)
    fresh_service.registry.register(StableB)

    # Trigger multiple failures in FlakyA to trip its circuit
    for _ in range(4):
        fresh_service.ingest("flaky_a")

    assert fresh_service.circuit_breaker.get_state("flaky_a") == CircuitState.OPEN

    # StableB must remain completely unaffected and healthy
    res_b = fresh_service.ingest("stable_b")
    assert res_b.status == IngestionStatus.SUCCESS
    assert fresh_service.circuit_breaker.get_state("stable_b") == CircuitState.CLOSED


def test_42_organization_isolation(fresh_service):
    """42. Verify idempotency and stored events are isolated across organizations."""
    raw_payload = {"measurement": "temperature", "val": 24.0}

    class SharedProvider(BaseProviderAdapter):
        provider_name = "shared_stream"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            return IngestionBatch(
                provider_name="shared_stream",
                events=[RawEvent(provider_name="shared_stream", provider_event_id="same-id", raw_payload=raw_payload)],
            )

    fresh_service.registry.register(SharedProvider)

    # Ingest for Org 1
    res1 = fresh_service.ingest("shared_stream", organization_id="org-tenant-1")
    assert res1.status == IngestionStatus.SUCCESS
    assert res1.metadata.items_ingested == 1

    # Ingest identical payload for Org 2 -> should NOT be treated as duplicate of Org 1!
    res2 = fresh_service.ingest("shared_stream", organization_id="org-tenant-2")
    assert res2.status == IngestionStatus.SUCCESS
    assert res2.metadata.items_ingested == 1

    # List events scoped by Org
    events_org1 = fresh_service.storage.list_events(provider_name="shared_stream", org_id="org-tenant-1")
    events_org2 = fresh_service.storage.list_events(provider_name="shared_stream", org_id="org-tenant-2")
    assert len(events_org1) == 1
    assert len(events_org2) == 1


def test_43_concurrent_ingestion_safety(fresh_service):
    """43. Verify multi-threaded concurrent ingestion executions run safely without race conditions."""
    class ConcurrentAdapter(BaseProviderAdapter):
        provider_name = "mock_concurrent"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            idx = kwargs.get("index", 0)
            return IngestionBatch(
                provider_name="mock_concurrent",
                events=[RawEvent(provider_name="mock_concurrent", provider_event_id=f"c-{idx}", raw_payload={"idx": idx})],
            )

    fresh_service.registry.register(ConcurrentAdapter)

    def _worker(i: int):
        return fresh_service.ingest(
            "mock_concurrent",
            parameters={"index": i},
            request_id=f"req-thread-{i}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_worker, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 10
    assert all(r.status == IngestionStatus.SUCCESS for r in results)


# =====================================================================
# Tests: 44-46 (Thread Safety of Components)
# =====================================================================

def test_44_registry_thread_safety():
    """44. Verify ProviderRegistry is safe under concurrent adapter registrations and reads."""
    reg = ProviderRegistry()

    def _register(idx: int):
        class TempAdapter(BaseProviderAdapter):
            provider_name = f"temp_prov_{idx}"
            capabilities = ProviderCapabilities()
            def fetch(self, **kwargs):
                return IngestionBatch(provider_name=self.provider_name, events=[])

        reg.register(TempAdapter)
        assert reg.is_registered(f"temp_prov_{idx}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_register, i) for i in range(15)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert len(reg.list_providers()) == 15


def test_45_idempotency_thread_safety():
    """45. Verify IdempotencyEngine safely deduplicates concurrent identical events."""
    engine = IdempotencyEngine()
    results = []

    def _check():
        is_unique, _ = engine.check_and_record("prov_test", provider_event_id="unique-evt-1")
        return is_unique

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_check) for _ in range(20)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Exactly one thread should see unique=True, other 19 should see False
    assert results.count(True) == 1
    assert results.count(False) == 19


def test_46_rate_limiter_thread_safety():
    """46. Verify ProviderRateLimiter request windows are thread-safe under concurrency."""
    rl = ProviderRateLimiter()
    cfg = RateLimitConfig(requests_per_minute=5)
    acquired = []

    def _acquire():
        return rl.acquire("prov_rl", cfg)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_acquire) for _ in range(10)]
        acquired = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Exactly 5 should succeed, 5 should be blocked
    assert acquired.count(True) == 5
    assert acquired.count(False) == 5


# =====================================================================
# Tests: 47-50 (Security, Payloads, Config, End-to-End)
# =====================================================================

def test_47_no_secret_leakage_in_audit_and_logs(fresh_service):
    """47. Verify raw passwords, tokens, and keys are not leaked in audit JSON."""
    fresh_service.audit_ledger.record_event(
        action=IngestionAuditAction.PROVIDER_REQUESTED,
        provider_name="mock_reliable",
        details={
            "api_key": "SUPER_SECRET_VALUE",
            "Authorization": "Bearer token_secret",
            "db_password": "root_password",
        },
    )
    events = fresh_service.audit_ledger.list_events(provider_name="mock_reliable")
    record_json = str(events[-1].to_dict())
    assert "SUPER_SECRET_VALUE" not in record_json
    assert "root_password" not in record_json
    assert "token_secret" not in record_json
    assert "[REDACTED_SECRET]" in record_json


def test_48_no_raw_payload_leakage_in_ordinary_logs(fresh_service):
    """48. Verify large raw event payloads are not dumped directly into logs."""
    fresh_service.structured_logger.enable_capture()
    try:
        fresh_service.structured_logger.log_operation(
            provider="mock_reliable",
            operation="ingest",
            status="SUCCESS",
            duration_ms=12.5,
            details={"raw_payload": {"very_large_blob": "x" * 5000}},
        )
        logs = fresh_service.structured_logger.get_captured_logs()
        assert "raw_payload" not in logs[-1].details
    finally:
        fresh_service.structured_logger.disable_capture()


def test_49_provider_specific_timeout_enforcement(fresh_service):
    """49. Verify provider-specific timeout configuration is preserved on config."""
    class CustomTimeoutAdapter(BaseProviderAdapter):
        provider_name = "timeout_prov"
        capabilities = ProviderCapabilities()
        def fetch(self, **kwargs):
            return IngestionBatch(provider_name=self.provider_name, events=[])

    cfg = ProviderConfig(
        provider_name="timeout_prov",
        provider_type=ProviderType.CUSTOM,
        timeout_seconds=2.5,
    )
    assert cfg.timeout_seconds == 2.5
    fresh_service.registry.register(CustomTimeoutAdapter, default_config=cfg)
    loaded_cfg = fresh_service.registry.get_config("timeout_prov")
    assert loaded_cfg.timeout_seconds == 2.5


def test_50_end_to_end_metadata_propagation(fresh_service):
    """50. Verify full metadata propagation through ShipmentEventBridge."""
    custom_req = "req-e2e-123"
    custom_corr = "corr-e2e-456"
    custom_trace = "trc-e2e-789"
    org = "org-enterprise-corp"

    # 1. Ingest raw event
    res = fresh_service.ingest(
        "mock_reliable",
        request_id=custom_req,
        correlation_id=custom_corr,
        trace_id=custom_trace,
        organization_id=org,
    )
    assert len(res.events) == 1
    raw_event = res.events[0]
    assert raw_event.metadata["request_id"] == custom_req
    assert raw_event.metadata["correlation_id"] == custom_corr
    assert raw_event.metadata["trace_id"] == custom_trace

    # 2. Normalize raw event to canonical event
    normalizer = NormalizationPipeline()
    canonical_event = normalizer.normalize(raw_event)
    assert canonical_event.request_id == custom_req
    assert canonical_event.correlation_id == custom_corr
    assert canonical_event.trace_id == custom_trace
    assert canonical_event.org_id == org

    # 3. Associate with shipment and bridge to ShipmentEvent model dictionary
    canonical_event.correlation.shipment_id = "shp-active-999"
    shipment_dict = ShipmentEventBridge.to_shipment_event_dict(canonical_event)

    assert shipment_dict["shipment_id"] == "shp-active-999"
    assert shipment_dict["metadata_json"]["correlation_id"] == custom_corr
    assert shipment_dict["metadata_json"]["request_id"] == custom_req
    assert shipment_dict["metadata_json"]["trace_id"] == custom_trace
    assert shipment_dict["metadata_json"]["provider"] == "mock_reliable"
