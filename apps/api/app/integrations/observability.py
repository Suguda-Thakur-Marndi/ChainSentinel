"""Production-grade reliability and observability infrastructure for external data ingestion.

Provides:
1. Deterministic Failure Classification (FailureCategory & classify_failure)
2. Thread-Safe Ingestion Metrics Collector & Hooks (IngestionMetricsCollector)
3. Ingestion Lifecycle Audit Ledger (IngestionAuditSink & InMemoryIngestionAuditLedger)
4. Structured Ingestion Logging with Strict Redaction (IngestionStructuredLogger)
5. Stale External Data Detection & Quality Verification (StaleDataDetector)
6. Secret & Sensitive Logistics Data Redaction
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, Union

logger = logging.getLogger("riskwise.integrations.observability")


# =====================================================================
# 1. Deterministic Failure Classification
# =====================================================================

from app.integrations.errors import FailureCategory, classify_failure



# =====================================================================
# 2. Secret & Sensitive Data Redaction
# =====================================================================

SENSITIVE_SECRET_PATTERNS = re.compile(
    r"(api[_-]?key|secret|token|password|auth|credential|cookie|private_key|client_secret)",
    re.IGNORECASE,
)

SENSITIVE_PII_PATTERNS = re.compile(
    r"(email|phone|ssn|social_security|credit_card|card_number|cvv|passport|date_of_birth)",
    re.IGNORECASE,
)

# Common sensitive logistics fields that shouldn't appear in ordinary telemetry logs
SENSITIVE_LOGISTICS_PATTERNS = re.compile(
    r"(recipient_name|customer_name|billing_address|delivery_notes|consignee_name|consignee_address)",
    re.IGNORECASE,
)


def mask_sensitive_identifier(val: Any) -> str:
    """Mask sensitive identifiers like tracking numbers or IDs (e.g. TRK***5678)."""
    if not val:
        return "[EMPTY]"
    s = str(val).strip()
    if len(s) <= 4:
        return "****"
    return f"{s[:2]}****{s[-4:]}"


def sanitize_for_logging(data: Any, mask_logistics: bool = True) -> Any:
    """Recursively scrub credentials, tokens, PII, and private customer logistics data.

    Returns a clean, safe representation suitable for structured logs and telemetry.
    """
    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k)
            # 1. Check secrets
            if SENSITIVE_SECRET_PATTERNS.search(k_str):
                sanitized[k_str] = "[REDACTED_SECRET]"
            # 2. Check PII
            elif SENSITIVE_PII_PATTERNS.search(k_str):
                sanitized[k_str] = "[REDACTED_PII]"
            # 3. Check sensitive logistics
            elif mask_logistics and SENSITIVE_LOGISTICS_PATTERNS.search(k_str):
                sanitized[k_str] = "[REDACTED_LOGISTICS_PII]"
            else:
                sanitized[k_str] = sanitize_for_logging(v, mask_logistics=mask_logistics)
        return sanitized
    elif isinstance(data, (list, tuple, set)):
        return [sanitize_for_logging(item, mask_logistics=mask_logistics) for item in data]
    return data


# =====================================================================
# 3. Structured Ingestion Logging
# =====================================================================

@dataclass
class StructuredLogEntry:
    """Representation of an audited structured log entry."""

    timestamp: str
    log_level: str
    provider: str
    operation: str
    status: str
    duration_ms: float
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    organization_id: Optional[str] = None
    retry_count: int = 0
    event_count: int = 0
    normalized_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "log_level": self.log_level,
            "provider": self.provider,
            "operation": self.operation,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "organization_id": self.organization_id,
            "retry_count": self.retry_count,
            "event_count": self.event_count,
            "normalized_count": self.normalized_count,
            "rejected_count": self.rejected_count,
            "duplicate_count": self.duplicate_count,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "details": self.details,
        }


class IngestionStructuredLogger:
    """Structured logger for ingestion pipeline with zero secret leakage and test capture."""

    def __init__(self, logger_name: str = "riskwise.integrations.structured") -> None:
        self.underlying_logger = logging.getLogger(logger_name)
        self._captured_logs: List[StructuredLogEntry] = []
        self._capture_enabled: bool = False
        self._lock = threading.Lock()

    def enable_capture(self) -> None:
        """Enable in-memory log capturing for testing and verification."""
        with self._lock:
            self._capture_enabled = True
            self._captured_logs.clear()

    def disable_capture(self) -> None:
        """Disable in-memory log capturing."""
        with self._lock:
            self._capture_enabled = False

    def get_captured_logs(self) -> List[StructuredLogEntry]:
        """Retrieve copy of captured logs."""
        with self._lock:
            return list(self._captured_logs)

    def clear_captured_logs(self) -> None:
        """Clear captured logs."""
        with self._lock:
            self._captured_logs.clear()

    @contextmanager
    def capture_context(self) -> Generator[List[StructuredLogEntry], None, None]:
        """Context manager capturing logs during the context block."""
        self.enable_capture()
        try:
            yield self._captured_logs
        finally:
            self.disable_capture()

    def log_operation(
        self,
        provider: str,
        operation: str,
        status: str,
        duration_ms: float,
        level: int = logging.INFO,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        retry_count: int = 0,
        event_count: int = 0,
        normalized_count: int = 0,
        rejected_count: int = 0,
        duplicate_count: int = 0,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> StructuredLogEntry:
        """Emit sanitized, structured ingestion log."""
        clean_details = sanitize_for_logging(details or {}, mask_logistics=True)
        # Never store raw provider payloads
        clean_details.pop("raw_payload", None)
        clean_details.pop("raw_events", None)

        level_name = logging.getLevelName(level)
        entry = StructuredLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            log_level=level_name,
            provider=provider,
            operation=operation,
            status=status,
            duration_ms=duration_ms,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            organization_id=organization_id,
            retry_count=retry_count,
            event_count=event_count,
            normalized_count=normalized_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            error_type=error_type,
            error_message=error_message,
            details=clean_details,
        )

        log_msg = (
            f"Ingestion [{provider}:{operation}] status={status} duration={duration_ms:.2f}ms "
            f"events={event_count} norm={normalized_count} rej={rejected_count} dup={duplicate_count} "
            f"retries={retry_count} req_id={request_id} corr_id={correlation_id} trace_id={trace_id} "
            f"org_id={organization_id}"
        )
        if error_type:
            log_msg += f" error={error_type}"

        self.underlying_logger.log(level, log_msg)

        with self._lock:
            if self._capture_enabled:
                self._captured_logs.append(entry)

        return entry


# Default singleton instance
default_structured_logger = IngestionStructuredLogger()


# =====================================================================
# 4. Ingestion Metrics Collector
# =====================================================================

@dataclass
class _DurationSummary:
    """Tracks latency statistics using monotonic time."""

    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0

    def record(self, duration_ms: float) -> None:
        self.count += 1
        self.total_ms += duration_ms
        if duration_ms < self.min_ms:
            self.min_ms = duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms

    @property
    def avg_ms(self) -> float:
        return (self.total_ms / self.count) if self.count > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "total_ms": round(self.total_ms, 2),
            "min_ms": round(self.min_ms, 2) if self.count > 0 else 0.0,
            "max_ms": round(self.max_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
        }


class IngestionMetricsCollector:
    """Thread-safe, provider-agnostic metrics registry for ingestion telemetry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._durations: Dict[str, _DurationSummary] = {}
        self._hooks: List[Callable[[str, Union[int, float], Dict[str, str]], None]] = []

    def add_hook(self, hook: Callable[[str, Union[int, float], Dict[str, str]], None]) -> None:
        """Register an external metrics hook (e.g. for forwarding to custom sinks)."""
        with self._lock:
            self._hooks.append(hook)

    def _notify_hooks(self, name: str, value: Union[int, float], tags: Dict[str, str]) -> None:
        for hook in self._hooks:
            try:
                hook(name, value, tags)
            except Exception as e:
                logger.error("Error in metrics hook: %s", e)

    def increment(
        self,
        metric_name: str,
        value: int = 1,
        provider: Optional[str] = None,
        org_id: Optional[str] = None,
        status: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Increment a counter metric with dimensional tags."""
        tag_parts = [metric_name]
        tags: Dict[str, str] = {}
        if provider:
            tag_parts.append(f"provider={provider.lower()}")
            tags["provider"] = provider.lower()
        if org_id:
            tag_parts.append(f"org={org_id}")
            tags["org_id"] = org_id
        if status:
            tag_parts.append(f"status={status.lower()}")
            tags["status"] = status.lower()
        if reason:
            tag_parts.append(f"reason={reason.lower()}")
            tags["reason"] = reason.lower()

        key = ":".join(tag_parts)

        with self._lock:
            current = self._counters.get(key, 0) + value
            self._counters[key] = current

        self._notify_hooks(metric_name, value, tags)
        return current

    def set_gauge(
        self,
        metric_name: str,
        value: float,
        provider: Optional[str] = None,
    ) -> None:
        """Set a gauge metric value (e.g. provider_health_status)."""
        tag_parts = [metric_name]
        tags: Dict[str, str] = {}
        if provider:
            tag_parts.append(f"provider={provider.lower()}")
            tags["provider"] = provider.lower()

        key = ":".join(tag_parts)

        with self._lock:
            self._gauges[key] = value

        self._notify_hooks(metric_name, value, tags)

    def record_duration(
        self,
        metric_name: str,
        duration_ms: float,
        provider: Optional[str] = None,
    ) -> None:
        """Record monotonic execution latency."""
        tag_parts = [metric_name]
        tags: Dict[str, str] = {}
        if provider:
            tag_parts.append(f"provider={provider.lower()}")
            tags["provider"] = provider.lower()

        key = ":".join(tag_parts)

        with self._lock:
            if key not in self._durations:
                self._durations[key] = _DurationSummary()
            self._durations[key].record(duration_ms)

        self._notify_hooks(metric_name, duration_ms, tags)

    def get_counter(self, metric_name: str, provider: Optional[str] = None) -> int:
        """Get the total count for a metric, optionally filtered by provider."""
        with self._lock:
            total = 0
            for k, val in self._counters.items():
                if k.startswith(metric_name):
                    if provider:
                        if f"provider={provider.lower()}" in k:
                            total += val
                    else:
                        total += val
            return total

    def get_gauge(self, metric_name: str, provider: Optional[str] = None) -> Optional[float]:
        """Get current gauge value."""
        with self._lock:
            for k, val in self._gauges.items():
                if k.startswith(metric_name):
                    if provider and f"provider={provider.lower()}" in k:
                        return val
                    elif not provider:
                        return val
            return None

    def get_duration_stats(self, metric_name: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """Get summary statistics for a duration metric."""
        with self._lock:
            combined = _DurationSummary()
            for k, summary in self._durations.items():
                if k.startswith(metric_name):
                    if not provider or f"provider={provider.lower()}" in k:
                        combined.count += summary.count
                        combined.total_ms += summary.total_ms
                        if summary.min_ms < combined.min_ms:
                            combined.min_ms = summary.min_ms
                        if summary.max_ms > combined.max_ms:
                            combined.max_ms = summary.max_ms
            return combined.to_dict()

    def snapshot(self) -> Dict[str, Any]:
        """Produce complete snapshot of all tracked metrics."""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "durations": {k: v.to_dict() for k, v in self._durations.items()},
            }

    def reset(self) -> None:
        """Reset all metrics (useful for isolated tests)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._durations.clear()


# Default singleton metrics collector
default_metrics_collector = IngestionMetricsCollector()


# =====================================================================
# 5. Ingestion Audit Lifecycle
# =====================================================================

class IngestionAuditAction(str, Enum):
    """Lifecycle events recorded in the immutable ingestion audit trail."""

    INGESTION_STARTED = "INGESTION_STARTED"
    PROVIDER_REQUESTED = "PROVIDER_REQUESTED"
    PROVIDER_SUCCEEDED = "PROVIDER_SUCCEEDED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    RETRY_ATTEMPTED = "RETRY_ATTEMPTED"
    RATE_LIMITED = "RATE_LIMITED"
    EVENT_NORMALIZED = "EVENT_NORMALIZED"
    DUPLICATE_DISCARDED = "DUPLICATE_DISCARDED"
    EVENT_REJECTED = "EVENT_REJECTED"
    INGESTION_COMPLETED = "INGESTION_COMPLETED"


@dataclass
class IngestionAuditEntry:
    """Immutable audit record representing an ingestion lifecycle event."""

    timestamp: datetime
    action: IngestionAuditAction
    provider_name: str
    status: str
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None
    org_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "provider_name": self.provider_name,
            "status": self.status,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "ingestion_run_id": self.ingestion_run_id,
            "org_id": self.org_id,
            "details": self.details,
        }


class InMemoryIngestionAuditLedger:
    """Thread-safe, append-only in-memory ledger for ingestion audit logging."""

    def __init__(self, max_capacity: int = 5000) -> None:
        self._lock = threading.Lock()
        self._max_capacity = max_capacity
        self._records: List[IngestionAuditEntry] = []

    def record_event(
        self,
        action: IngestionAuditAction,
        provider_name: str,
        status: str = "SUCCESS",
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        ingestion_run_id: Optional[str] = None,
        org_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> IngestionAuditEntry:
        """Record an ingestion lifecycle event with automatic secret scrubbing."""
        clean_details = sanitize_for_logging(details or {}, mask_logistics=True)
        # Avoid storing raw payloads in audit records
        clean_details.pop("raw_payload", None)

        entry = IngestionAuditEntry(
            timestamp=datetime.now(timezone.utc),
            action=action,
            provider_name=provider_name,
            status=status,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            ingestion_run_id=ingestion_run_id,
            org_id=org_id,
            details=clean_details,
        )

        with self._lock:
            if len(self._records) >= self._max_capacity:
                self._records.pop(0)
            self._records.append(entry)

        return entry

    def list_events(
        self,
        provider_name: Optional[str] = None,
        action: Optional[IngestionAuditAction] = None,
        org_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[IngestionAuditEntry]:
        """List audit events matching filter criteria."""
        with self._lock:
            matches = list(self._records)

        if provider_name:
            matches = [e for e in matches if e.provider_name.lower() == provider_name.lower()]
        if action:
            matches = [e for e in matches if e.action == action]
        if org_id:
            matches = [e for e in matches if e.org_id == org_id]
        if correlation_id:
            matches = [e for e in matches if e.correlation_id == correlation_id]

        return matches[-limit:]

    def clear(self) -> None:
        """Clear audit ledger (for test isolation)."""
        with self._lock:
            self._records.clear()


# Default singleton audit ledger
default_audit_ledger = InMemoryIngestionAuditLedger()


# =====================================================================
# 6. Stale Data Detection
# =====================================================================

class FreshnessConfig:
    """Configurable provider-specific freshness bounds in seconds."""

    DEFAULT_THRESHOLDS: Dict[str, float] = {
        "openweather": 21600.0,    # 6 hours
        "tomtom": 7200.0,          # 2 hours
        "aisstream": 3600.0,       # 1 hour
        "opensky": 3600.0,         # 1 hour
        "rail": 3600.0,            # 1 hour
        "karrio": 604800.0,        # 7 days
        "tavily": 2592000.0,       # 30 days
    }

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
        default_threshold: float = 86400.0,  # 24 hours default
        allow_stale: bool = True,
    ) -> None:
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if thresholds:
            self.thresholds.update({k.lower(): v for k, v in thresholds.items()})
        self.default_threshold = default_threshold
        self.allow_stale = allow_stale

    def get_max_age(self, provider_name: str) -> float:
        """Get configured max allowed age in seconds for a provider."""
        return self.thresholds.get(provider_name.lower(), self.default_threshold)


class StaleDataDetector:
    """Evaluates timestamp freshness of ingested signals without blindly dropping data."""

    def __init__(self, config: Optional[FreshnessConfig] = None) -> None:
        self.config = config or FreshnessConfig()

    def check_freshness(
        self,
        timestamp: Optional[datetime],
        provider_name: str,
        reference_time: Optional[datetime] = None,
    ) -> Tuple[bool, float]:
        """Check if an event timestamp exceeds the freshness threshold for a provider.

        Returns:
            Tuple[is_stale, age_seconds]:
              - is_stale: True if age > max_age, False otherwise.
              - age_seconds: Monotonically calculated elapsed seconds since timestamp.
        """
        if timestamp is None:
            return False, 0.0

        ref = reference_time or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            ts_utc = timestamp.replace(tzinfo=timezone.utc)
        else:
            ts_utc = timestamp.astimezone(timezone.utc)

        age_seconds = max(0.0, (ref - ts_utc).total_seconds())
        max_age = self.config.get_max_age(provider_name)
        is_stale = age_seconds > max_age
        return is_stale, age_seconds
