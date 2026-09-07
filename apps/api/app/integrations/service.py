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
from app.integrations.config import ProviderConfig, SecretResolver
from app.integrations.errors import (
    DuplicateEventError,
    IngestionError,
    ProviderDisabledError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
)
from app.integrations.idempotency import IdempotencyEngine
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_class: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "ingestion_run_id": self.ingestion_run_id,
            "provider": self.provider,
            "duration_ms": round(self.duration_ms, 2),
            "retry_count": self.retry_count,
            "items_fetched": self.items_fetched,
            "items_ingested": self.items_ingested,
            "items_deduplicated": self.items_deduplicated,
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
    ) -> None:
        self.registry = registry or default_provider_registry
        self.rate_limiter = rate_limiter or ProviderRateLimiter()
        self.retry_policy = retry_policy or RetryPolicy()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self.storage = storage or InMemoryRawEventStorage()
        self.secret_resolver = secret_resolver or SecretResolver()
        self._last_successful_ingestion: Dict[str, datetime] = {}

    def ingest(
        self,
        provider_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        config: Optional[ProviderConfig] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> IngestionResult:
        """Execute an ingestion cycle for a named provider.

        Steps:
        1. Contextual identifiers & tracing setup
        2. Adapter and configuration resolution
        3. Rate limit enforcement
        4. Adapter fetch with bounded exponential retry
        5. Sensitive payload sanitization
        6. Deterministic idempotency deduplication
        7. Raw event boundary storage
        8. Audit logging & outcome metadata generation
        """
        ingestion_run_id = str(uuid.uuid4())
        req_id = request_id or str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())
        start_time = time.perf_counter()

        logger.info(
            "Starting ingestion run %s for provider=%s req_id=%s corr_id=%s org_id=%s",
            ingestion_run_id,
            provider_name,
            req_id,
            corr_id,
            organization_id,
        )

        try:
            # 1. Resolve adapter & config
            adapter_cls = self.registry.get_adapter_cls(provider_name)
            effective_config = config or self.registry.get_config(provider_name)

            if effective_config is not None and not effective_config.enabled:
                raise ProviderDisabledError(
                    f"Provider '{provider_name}' is disabled by configuration",
                    provider_name=provider_name,
                )

            adapter = adapter_cls(config=effective_config)

            # 2. Rate limit check & acquire
            rl_config = effective_config.rate_limit if effective_config else None
            is_allowed, wait_seconds = self.rate_limiter.check_limit(provider_name, rl_config)
            if not is_allowed:
                raise ProviderRateLimitError(
                    f"Rate limit exceeded for provider '{provider_name}'. Wait {wait_seconds:.1f}s",
                    provider_name=provider_name,
                    retry_after=wait_seconds,
                )

            self.rate_limiter.acquire(provider_name, rl_config)

            # 3. Fetch data via retry policy
            params = parameters or {}
            retries_recorded = [0]

            def _fetch_attempt() -> IngestionBatch:
                try:
                    return adapter.fetch(**params)
                except ProviderRateLimitError as rle:
                    self.rate_limiter.record_rate_limit(
                        provider_name,
                        retry_after=rle.retry_after,
                    )
                    raise

            # Configure retry policy with provider specific retry config if present
            retry_pol = self.retry_policy
            if effective_config and effective_config.retry:
                retry_pol = RetryPolicy(config=effective_config.retry)

            # Track retries count
            def _on_retry(attempt: int, delay: float, exc: Exception) -> None:
                retries_recorded[0] = attempt
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

            # 4. Process events: sanitization + idempotency deduplication
            accepted_events: List[RawEvent] = []
            duplicate_ids: List[str] = []

            for raw_event in batch.events:
                # Sanitize raw payload to prevent credential persistence
                raw_event.raw_payload = self.secret_resolver.sanitize_payload(
                    raw_event.raw_payload
                )

                # Set organization if scoped
                if organization_id and not raw_event.organization_id:
                    raw_event.organization_id = organization_id

                # Idempotency check
                is_unique, fingerprint = self.idempotency_engine.check_and_record(
                    raw_event,
                    organization_id=organization_id,
                )

                if is_unique:
                    accepted_events.append(raw_event)
                else:
                    duplicate_ids.append(fingerprint)

            # 5. Store accepted events at the raw boundary
            if accepted_events:
                storage_batch = IngestionBatch(
                    provider_name=batch.provider_name,
                    events=accepted_events,
                    source_metadata=batch.source_metadata,
                    fetched_at=batch.fetched_at,
                )
                self.storage.store_batch(storage_batch)

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # 6. Determine status
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

            metadata = IngestionMetadata(
                request_id=req_id,
                correlation_id=corr_id,
                ingestion_run_id=ingestion_run_id,
                provider=provider_name,
                duration_ms=duration_ms,
                retry_count=retries_recorded[0],
                items_fetched=total_fetched,
                items_ingested=total_ingested,
                items_deduplicated=total_duplicates,
            )

            logger.info(
                "Ingestion completed for provider=%s status=%s fetched=%d ingested=%d dupes=%d in %.2fms",
                provider_name,
                status.value,
                total_fetched,
                total_ingested,
                total_duplicates,
                duration_ms,
            )

            return IngestionResult(
                status=status,
                provider_name=provider_name,
                metadata=metadata,
                events=accepted_events,
                duplicates=duplicate_ids,
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_cls_name = exc.__class__.__name__

            if isinstance(exc, IngestionError):
                safe_msg = exc.to_safe_dict().get("message", str(exc))
                error_dict = exc.to_safe_dict()
            else:
                safe_msg = f"Unexpected error during ingestion: {type(exc).__name__}"
                error_dict = {
                    "error_class": "ProviderResponseError",
                    "provider_name": provider_name,
                    "message": safe_msg,
                }

            metadata = IngestionMetadata(
                request_id=req_id,
                correlation_id=corr_id,
                ingestion_run_id=ingestion_run_id,
                provider=provider_name,
                duration_ms=duration_ms,
                retry_count=0,
                items_fetched=0,
                items_ingested=0,
                items_deduplicated=0,
                error_class=error_cls_name,
                error_message=safe_msg,
            )

            logger.error(
                "Ingestion failed for provider=%s error=%s msg=%s in %.2fms",
                provider_name,
                error_cls_name,
                safe_msg,
                duration_ms,
            )

            if raise_on_error:
                raise

            return IngestionResult(
                status=IngestionStatus.FAILED,
                provider_name=provider_name,
                metadata=metadata,
                events=[],
                duplicates=[],
                errors=[error_dict],
            )

    def check_health(
        self,
        provider_name: str,
        config: Optional[ProviderConfig] = None,
    ) -> ProviderHealthResult:
        """Evaluate operational health for a provider."""
        start = time.perf_counter()

        if not self.registry.is_registered(provider_name):
            return ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                message=f"Provider '{provider_name}' is not registered",
                latency_ms=0.0,
            )

        effective_config = config or self.registry.get_config(provider_name)
        if effective_config is not None and not effective_config.enabled:
            return ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                message="Provider is disabled in configuration",
                latency_ms=0.0,
            )

        adapter = self.registry.create_adapter(provider_name, config=effective_config)
        try:
            result = adapter.health_check()
            latency_ms = (time.perf_counter() - start) * 1000.0
            result.latency_ms = latency_ms
            if result.status == ProviderHealthStatus.HEALTHY:
                result.last_successful_check = datetime.now(timezone.utc)
            return result
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                message=f"Health check exception: {exc.__class__.__name__}",
                latency_ms=latency_ms,
            )

    def get_last_successful_ingestion(self, provider_name: str) -> Optional[datetime]:
        """Return the timestamp of the last successful ingestion for a provider."""
        return self._last_successful_ingestion.get(provider_name)
