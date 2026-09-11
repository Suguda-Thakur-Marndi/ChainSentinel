"""Central ingestion service coordinating provider data retrieval,

validation, rate limiting, retries, idempotency deduplication,
raw data boundary buffering, and structured observability.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.integrations.base import (
    IngestionBatch,
    ProviderHealthResult,
    ProviderHealthStatus,
    RawEvent,
)
from app.integrations.boundaries import InMemoryRawEventStorage, RawEventStorage
from app.integrations.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    ProviderCircuitBreaker,
)
from app.integrations.config import ProviderConfig, SecretResolver
from app.integrations.errors import (
    DuplicateEventError,
    FailureCategory,
    IngestionError,
    ProviderDisabledError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
    classify_failure,
)
from app.integrations.idempotency import IdempotencyEngine
from app.integrations.normalizers import (
    NormalizationBatchResult,
    NormalizationPipeline,
)
from app.integrations.observability import (
    IngestionAuditAction,
    IngestionMetricsCollector,
    IngestionStructuredLogger,
    InMemoryIngestionAuditLedger,
    StaleDataDetector,
    default_audit_ledger,
    default_metrics_collector,
    default_structured_logger,
)
from app.integrations.rate_limiter import ProviderRateLimiter
from app.integrations.registry import ProviderRegistry, default_provider_registry
from app.integrations.retry import RetryPolicy

logger = logging.getLogger("riskwise.integrations.service")


class IngestionStatus(str, Enum):
    """Execution status outcomes for ingestion operations."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


@dataclass
class IngestionMetadata:
    """Detailed audit and observability metadata for an ingestion attempt."""

    request_id: str
    correlation_id: str
    ingestion_run_id: str
    provider: str
    duration_ms: float
    retry_count: int
    items_fetched: int
    items_ingested: int
    items_deduplicated: int
    trace_id: Optional[str] = None
    organization_id: Optional[str] = None
    provider_request_duration_ms: float = 0.0
    normalization_duration_ms: float = 0.0
    storage_duration_ms: float = 0.0
    items_rejected: int = 0
    items_stale: int = 0
    failure_category: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_class: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "ingestion_run_id": self.ingestion_run_id,
            "organization_id": self.organization_id,
            "provider": self.provider,
            "duration_ms": round(self.duration_ms, 2),
            "provider_request_duration_ms": round(self.provider_request_duration_ms, 2),
            "normalization_duration_ms": round(self.normalization_duration_ms, 2),
            "storage_duration_ms": round(self.storage_duration_ms, 2),
            "retry_count": self.retry_count,
            "items_fetched": self.items_fetched,
            "items_ingested": self.items_ingested,
            "items_deduplicated": self.items_deduplicated,
            "items_rejected": self.items_rejected,
            "items_stale": self.items_stale,
            "failure_category": self.failure_category,
            "timestamp": self.timestamp.isoformat(),
            "error_class": self.error_class,
            "error_message": self.error_message,
        }


@dataclass
class IngestionResult:
    """Outcome of an ingestion service invocation."""

    status: IngestionStatus
    provider_name: str
    metadata: IngestionMetadata
    events: List[RawEvent] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)


class IngestionService:
    """Central orchestrator for external signal ingestion."""

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        rate_limiter: Optional[ProviderRateLimiter] = None,
        retry_policy: Optional[RetryPolicy] = None,
        idempotency_engine: Optional[IdempotencyEngine] = None,
        storage: Optional[RawEventStorage] = None,
        secret_resolver: Optional[SecretResolver] = None,
        circuit_breaker: Optional[ProviderCircuitBreaker] = None,
        metrics_collector: Optional[IngestionMetricsCollector] = None,
        audit_ledger: Optional[InMemoryIngestionAuditLedger] = None,
        structured_logger: Optional[IngestionStructuredLogger] = None,
        stale_data_detector: Optional[StaleDataDetector] = None,
        normalization_pipeline: Optional[NormalizationPipeline] = None,
    ) -> None:
        self.registry = registry or default_provider_registry
        self.rate_limiter = rate_limiter or ProviderRateLimiter()
        self.retry_policy = retry_policy or RetryPolicy()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self.storage = storage or InMemoryRawEventStorage()
        self.secret_resolver = secret_resolver or SecretResolver()
        self.circuit_breaker = circuit_breaker or ProviderCircuitBreaker()
        self.metrics_collector = metrics_collector or default_metrics_collector
        self.audit_ledger = audit_ledger or default_audit_ledger
        self.structured_logger = structured_logger or default_structured_logger
        self.stale_data_detector = stale_data_detector or StaleDataDetector()
        self.normalization_pipeline = normalization_pipeline or NormalizationPipeline()
        self._last_successful_ingestion: Dict[str, datetime] = {}

    def ingest(
        self,
        provider_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        config: Optional[ProviderConfig] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> IngestionResult:
        """Execute an ingestion cycle for a named provider with production reliability.

        Steps:
        1. Contextual identifiers & tracing setup
        2. Circuit breaker check
        3. Adapter and configuration resolution
        4. Rate limit enforcement
        5. Adapter fetch with bounded exponential retry
        6. Sensitive payload sanitization & stale data inspection
        7. Deterministic idempotency deduplication
        8. Raw event boundary storage
        9. Outcome metadata, metrics recording, and audit logging
        """
        ingestion_run_id = str(uuid.uuid4())
        req_id = request_id or str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())
        trc_id = trace_id or f"trc-{uuid.uuid4().hex[:16]}"
        start_mono = time.perf_counter()

        # Audit: Ingestion Started
        self.audit_ledger.record_event(
            action=IngestionAuditAction.INGESTION_STARTED,
            provider_name=provider_name,
            status="STARTED",
            request_id=req_id,
            correlation_id=corr_id,
            trace_id=trc_id,
            ingestion_run_id=ingestion_run_id,
            org_id=organization_id,
            details={"parameters": parameters or {}},
        )

        self.metrics_collector.increment(
            "ingestion_requests_total",
            provider=provider_name,
            org_id=organization_id,
        )

        try:
            # 1. Circuit Breaker Enforcement
            if not self.circuit_breaker.can_execute(provider_name):
                status_dict = self.circuit_breaker.get_status(provider_name)
                raise CircuitBreakerOpenError(
                    f"Circuit breaker for provider '{provider_name}' is OPEN. "
                    f"Cooldown remaining: {status_dict.get('cooldown_remaining_seconds', 0.0)}s",
                    provider_name=provider_name,
                    cooldown_remaining=status_dict.get("cooldown_remaining_seconds"),
                )

            # 2. Resolve adapter & configuration
            adapter_cls = self.registry.get_adapter_cls(provider_name)
            effective_config = config or self.registry.get_config(provider_name)

            if effective_config is not None and not effective_config.enabled:
                raise ProviderDisabledError(
                    f"Provider '{provider_name}' is disabled by configuration",
                    provider_name=provider_name,
                )

            adapter = adapter_cls(config=effective_config)

            # 3. Rate limit check & acquire
            rl_config = effective_config.rate_limit if effective_config else None
            is_allowed, wait_seconds = self.rate_limiter.check_limit(provider_name, rl_config)
            if not is_allowed:
                self.metrics_collector.increment("provider_rate_limit_total", provider=provider_name)
                self.audit_ledger.record_event(
                    action=IngestionAuditAction.RATE_LIMITED,
                    provider_name=provider_name,
                    status="THROTTLED",
                    request_id=req_id,
                    correlation_id=corr_id,
                    trace_id=trc_id,
                    ingestion_run_id=ingestion_run_id,
                    org_id=organization_id,
                    details={"wait_seconds": wait_seconds},
                )
                raise ProviderRateLimitError(
                    f"Rate limit exceeded for provider '{provider_name}'. Wait {wait_seconds:.1f}s",
                    provider_name=provider_name,
                    retry_after=wait_seconds,
                )

            self.rate_limiter.acquire(provider_name, rl_config)

            # 4. Fetch data via retry policy
            params = parameters or {}
            retries_recorded = [0]
            fetch_start_mono = time.perf_counter()

            # Audit: Provider Requested
            self.audit_ledger.record_event(
                action=IngestionAuditAction.PROVIDER_REQUESTED,
                provider_name=provider_name,
                status="REQUESTED",
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                ingestion_run_id=ingestion_run_id,
                org_id=organization_id,
            )

            def _fetch_attempt() -> IngestionBatch:
                try:
                    return adapter.fetch(**params)
                except ProviderRateLimitError as rle:
                    self.rate_limiter.record_rate_limit(
                        provider_name,
                        retry_after=rle.retry_after,
                    )
                    self.metrics_collector.increment("provider_rate_limit_total", provider=provider_name)
                    raise

            # Configure retry policy with provider specific retry config if present
            retry_pol = self.retry_policy
            if effective_config and effective_config.retry:
                retry_pol = RetryPolicy(config=effective_config.retry)

            def _on_retry(attempt: int, delay: float, exc: Exception) -> None:
                retries_recorded[0] = attempt
                self.metrics_collector.increment("provider_retry_total", provider=provider_name)
                self.audit_ledger.record_event(
                    action=IngestionAuditAction.RETRY_ATTEMPTED,
                    provider_name=provider_name,
                    status="RETRYING",
                    request_id=req_id,
                    correlation_id=corr_id,
                    trace_id=trc_id,
                    ingestion_run_id=ingestion_run_id,
                    org_id=organization_id,
                    details={
                        "attempt": attempt,
                        "delay": round(delay, 2),
                        "error_type": exc.__class__.__name__,
                    },
                )
                logger.warning(
                    "Ingestion retry attempt=%d delay=%.2fs for provider=%s error=%s",
                    attempt,
                    delay,
                    provider_name,
                    exc,
                )

            batch: IngestionBatch = retry_pol.execute(
                _fetch_attempt,
                on_retry=_on_retry,
            )

            provider_req_duration_ms = (time.perf_counter() - fetch_start_mono) * 1000.0
            self.metrics_collector.record_duration(
                "provider_request_duration",
                provider_req_duration_ms,
                provider=provider_name,
            )

            # Record successful provider execution to circuit breaker
            self.circuit_breaker.record_success(provider_name)

            self.audit_ledger.record_event(
                action=IngestionAuditAction.PROVIDER_SUCCEEDED,
                provider_name=provider_name,
                status="SUCCESS",
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                ingestion_run_id=ingestion_run_id,
                org_id=organization_id,
                details={
                    "duration_ms": round(provider_req_duration_ms, 2),
                    "items_fetched": len(batch.events),
                },
            )

            # 5. Process events: sanitization, correlation metadata, freshness & idempotency
            proc_start_mono = time.perf_counter()
            accepted_events: List[RawEvent] = []
            duplicate_ids: List[str] = []
            stale_count = 0

            for raw_event in batch.events:
                # Sanitize raw payload
                raw_event.raw_payload = self.secret_resolver.sanitize_payload(
                    raw_event.raw_payload
                )

                # Set organization scoping
                if organization_id and not raw_event.organization_id:
                    raw_event.organization_id = organization_id

                # Attach correlation identifiers into raw event metadata
                raw_event.metadata["request_id"] = req_id
                raw_event.metadata["correlation_id"] = corr_id
                raw_event.metadata["trace_id"] = trc_id
                raw_event.metadata["ingestion_run_id"] = ingestion_run_id
                if organization_id:
                    raw_event.metadata["organization_id"] = organization_id

                # Evaluate data freshness without blindly dropping
                is_stale, age_sec = self.stale_data_detector.check_freshness(
                    raw_event.source_timestamp,
                    provider_name=provider_name,
                )
                if is_stale:
                    stale_count += 1
                    raw_event.metadata["is_stale"] = True
                    raw_event.metadata["stale_age_seconds"] = round(age_sec, 1)

                # Idempotency check
                is_unique, fingerprint = self.idempotency_engine.check_and_record(
                    raw_event,
                    organization_id=organization_id,
                )

                if is_unique:
                    accepted_events.append(raw_event)
                    self.audit_ledger.record_event(
                        action=IngestionAuditAction.EVENT_NORMALIZED,
                        provider_name=provider_name,
                        status="ACCEPTED",
                        request_id=req_id,
                        correlation_id=corr_id,
                        trace_id=trc_id,
                        ingestion_run_id=ingestion_run_id,
                        org_id=organization_id,
                        details={"event_id": raw_event.id, "fingerprint": fingerprint},
                    )
                else:
                    duplicate_ids.append(fingerprint)
                    self.metrics_collector.increment(
                        "ingestion_duplicates_total",
                        provider=provider_name,
                        org_id=organization_id,
                    )
                    self.audit_ledger.record_event(
                        action=IngestionAuditAction.DUPLICATE_DISCARDED,
                        provider_name=provider_name,
                        status="DUPLICATE",
                        request_id=req_id,
                        correlation_id=corr_id,
                        trace_id=trc_id,
                        ingestion_run_id=ingestion_run_id,
                        org_id=organization_id,
                        details={"fingerprint": fingerprint},
                    )

            proc_duration_ms = (time.perf_counter() - proc_start_mono) * 1000.0

            # 6. Store accepted events at the raw boundary
            storage_start_mono = time.perf_counter()
            if accepted_events:
                storage_batch = IngestionBatch(
                    provider_name=batch.provider_name,
                    events=accepted_events,
                    source_metadata=batch.source_metadata,
                    fetched_at=batch.fetched_at,
                )
                self.storage.store_batch(storage_batch)
            storage_duration_ms = (time.perf_counter() - storage_start_mono) * 1000.0

            total_duration_ms = (time.perf_counter() - start_mono) * 1000.0

            # 7. Determine status
            total_fetched = len(batch.events)
            total_ingested = len(accepted_events)
            total_duplicates = len(duplicate_ids)

            if total_fetched > 0 and total_ingested == 0 and total_duplicates > 0:
                status = IngestionStatus.SKIPPED_DUPLICATE
            elif total_ingested > 0 and total_duplicates > 0:
                status = IngestionStatus.PARTIAL
            else:
                status = IngestionStatus.SUCCESS

            self._last_successful_ingestion[provider_name] = datetime.now(timezone.utc)

            # Record success metrics
            self.metrics_collector.increment(
                "ingestion_success_total",
                provider=provider_name,
                org_id=organization_id,
                status=status.value,
            )
            self.metrics_collector.increment(
                "ingestion_events_received_total",
                value=total_fetched,
                provider=provider_name,
                org_id=organization_id,
            )
            self.metrics_collector.increment(
                "ingestion_events_normalized_total",
                value=total_ingested,
                provider=provider_name,
                org_id=organization_id,
            )

            metadata = IngestionMetadata(
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                ingestion_run_id=ingestion_run_id,
                organization_id=organization_id,
                provider=provider_name,
                duration_ms=total_duration_ms,
                provider_request_duration_ms=provider_req_duration_ms,
                normalization_duration_ms=proc_duration_ms,
                storage_duration_ms=storage_duration_ms,
                retry_count=retries_recorded[0],
                items_fetched=total_fetched,
                items_ingested=total_ingested,
                items_deduplicated=total_duplicates,
                items_rejected=0,
                items_stale=stale_count,
            )

            # Structured logging
            self.structured_logger.log_operation(
                provider=provider_name,
                operation="ingest",
                status=status.value,
                duration_ms=total_duration_ms,
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                organization_id=organization_id,
                retry_count=retries_recorded[0],
                event_count=total_fetched,
                normalized_count=total_ingested,
                rejected_count=0,
                duplicate_count=total_duplicates,
                details={
                    "stale_events": stale_count,
                    "storage_ms": storage_duration_ms,
                },
            )

            # Audit: Ingestion Completed
            self.audit_ledger.record_event(
                action=IngestionAuditAction.INGESTION_COMPLETED,
                provider_name=provider_name,
                status=status.value,
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                ingestion_run_id=ingestion_run_id,
                org_id=organization_id,
                details={
                    "duration_ms": round(total_duration_ms, 2),
                    "items_fetched": total_fetched,
                    "items_ingested": total_ingested,
                    "items_deduplicated": total_duplicates,
                },
            )

            return IngestionResult(
                status=status,
                provider_name=provider_name,
                metadata=metadata,
                events=accepted_events,
                duplicates=duplicate_ids,
                rejected=[],
                errors=[],
            )

        except Exception as exc:
            total_duration_ms = (time.perf_counter() - start_mono) * 1000.0
            error_cls_name = exc.__class__.__name__
            category = classify_failure(exc)

            # Record failure in circuit breaker
            if not isinstance(exc, CircuitBreakerOpenError):
                self.circuit_breaker.record_failure(provider_name, exc)

            self.metrics_collector.increment(
                "ingestion_failure_total",
                provider=provider_name,
                org_id=organization_id,
                reason=category.value,
            )

            if isinstance(exc, IngestionError):
                safe_msg = exc.to_safe_dict().get("message", str(exc))
                error_dict = exc.to_safe_dict()
            else:
                safe_msg = f"Unexpected error during ingestion: {type(exc).__name__}"
                error_dict = {
                    "error_class": error_cls_name,
                    "failure_category": category.value,
                    "provider_name": provider_name,
                    "message": safe_msg,
                }

            metadata = IngestionMetadata(
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                ingestion_run_id=ingestion_run_id,
                organization_id=organization_id,
                provider=provider_name,
                duration_ms=total_duration_ms,
                retry_count=0,
                items_fetched=0,
                items_ingested=0,
                items_deduplicated=0,
                items_rejected=0,
                failure_category=category.value,
                error_class=error_cls_name,
                error_message=safe_msg,
            )

            self.structured_logger.log_operation(
                provider=provider_name,
                operation="ingest",
                status="FAILED",
                duration_ms=total_duration_ms,
                level=logging.ERROR,
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                organization_id=organization_id,
                error_type=error_cls_name,
                error_message=safe_msg,
                details={"failure_category": category.value},
            )

            # Audit: Provider Failed
            self.audit_ledger.record_event(
                action=IngestionAuditAction.PROVIDER_FAILED,
                provider_name=provider_name,
                status="FAILED",
                request_id=req_id,
                correlation_id=corr_id,
                trace_id=trc_id,
                ingestion_run_id=ingestion_run_id,
                org_id=organization_id,
                details={
                    "error_type": error_cls_name,
                    "failure_category": category.value,
                    "message": safe_msg,
                },
            )

            if raise_on_error:
                raise

            return IngestionResult(
                status=IngestionStatus.FAILED,
                provider_name=provider_name,
                metadata=metadata,
                events=[],
                duplicates=[],
                rejected=[],
                errors=[error_dict],
            )

    def check_health(
        self,
        provider_name: str,
        config: Optional[ProviderConfig] = None,
    ) -> ProviderHealthResult:
        """Evaluate operational health for a provider considering connectivity, auth, rate-limit, and circuit breaker."""
        start = time.perf_counter()
        cb_status = self.circuit_breaker.get_status(provider_name)
        cb_state = cb_status.get("state", "CLOSED")

        # 1. Unregistered check
        if not self.registry.is_registered(provider_name):
            res = ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                message=f"Provider '{provider_name}' is not registered",
                latency_ms=0.0,
                circuit_state=cb_state,
                failure_category=FailureCategory.PROVIDER_UNAVAILABLE.value,
            )
            self.metrics_collector.set_gauge("provider_health_status", 0.0, provider=provider_name)
            return res

        effective_config = config or self.registry.get_config(provider_name)

        # 2. Disabled check
        if effective_config is not None and not effective_config.enabled:
            res = ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNAVAILABLE,
                message="Provider is disabled in configuration",
                latency_ms=0.0,
                circuit_state=cb_state,
                failure_category=FailureCategory.PROVIDER_UNAVAILABLE.value,
            )
            self.metrics_collector.set_gauge("provider_health_status", 0.0, provider=provider_name)
            return res

        # 3. Circuit Breaker OPEN check
        if cb_state == CircuitState.OPEN.value:
            cooldown_rem = cb_status.get("cooldown_remaining_seconds", 0.0)
            res = ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNAVAILABLE,
                message=f"Circuit breaker is OPEN (cooldown remaining: {cooldown_rem:.1f}s)",
                latency_ms=0.0,
                circuit_state=cb_state,
                consecutive_failures=cb_status.get("consecutive_failures", 0),
                failure_category=FailureCategory.CIRCUIT_OPEN.value,
            )
            self.metrics_collector.set_gauge("provider_health_status", 0.0, provider=provider_name)
            return res

        # 4. Rate limit cooldown check
        rl_status = self.rate_limiter.get_provider_status(provider_name)
        if rl_status.get("is_cooling_down"):
            cooldown_rem = rl_status.get("cooldown_remaining_seconds", 0.0)
            res = ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.DEGRADED,
                message=f"Provider is currently rate-limited (cooldown: {cooldown_rem:.1f}s)",
                latency_ms=0.0,
                circuit_state=cb_state,
                rate_limited=True,
                failure_category=FailureCategory.RATE_LIMITED.value,
            )
            self.metrics_collector.set_gauge("provider_health_status", 0.5, provider=provider_name)
            return res

        # 5. Execute adapter probe
        adapter = self.registry.create_adapter(provider_name, config=effective_config)
        try:
            result = adapter.health_check()
            latency_ms = (time.perf_counter() - start) * 1000.0
            result.latency_ms = latency_ms
            result.circuit_state = cb_state
            result.consecutive_failures = cb_status.get("consecutive_failures", 0)

            # If circuit breaker was in HALF_OPEN, probe outcome dictates recovery
            if cb_state == CircuitState.HALF_OPEN.value:
                if result.status == ProviderHealthStatus.HEALTHY:
                    self.circuit_breaker.record_success(provider_name)
                    result.circuit_state = CircuitState.CLOSED.value
                else:
                    self.circuit_breaker.record_failure(provider_name)
                    result.circuit_state = CircuitState.OPEN.value
                    result.status = ProviderHealthStatus.UNAVAILABLE

            if result.status == ProviderHealthStatus.HEALTHY:
                result.last_successful_check = datetime.now(timezone.utc)
                self.metrics_collector.set_gauge("provider_health_status", 1.0, provider=provider_name)
            elif result.status == ProviderHealthStatus.DEGRADED:
                self.metrics_collector.set_gauge("provider_health_status", 0.5, provider=provider_name)
            else:
                self.metrics_collector.set_gauge("provider_health_status", 0.0, provider=provider_name)

            return result
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            cat = classify_failure(exc)
            # Record failure in circuit breaker
            self.circuit_breaker.record_failure(provider_name, exc)
            self.metrics_collector.set_gauge("provider_health_status", 0.0, provider=provider_name)

            return ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNAVAILABLE,
                message=f"Health check exception: {exc.__class__.__name__}: {str(exc)}",
                latency_ms=latency_ms,
                circuit_state=self.circuit_breaker.get_state(provider_name).value,
                consecutive_failures=cb_status.get("consecutive_failures", 0) + 1,
                failure_category=cat.value,
            )

    def get_last_successful_ingestion(self, provider_name: str) -> Optional[datetime]:
        """Return the timestamp of the last successful ingestion for a provider."""
        return self._last_successful_ingestion.get(provider_name)
