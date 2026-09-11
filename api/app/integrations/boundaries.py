"""Ingestion boundary abstractions for raw storage, canonical storage, scheduling, and webhooks.

Step 1 established raw storage, scheduling, and webhook boundaries.
Step 2 establishes the canonical event storage boundary and bridges.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.integrations.base import IngestionBatch, RawEvent
from app.integrations.canonical import CanonicalExternalEvent

logger = logging.getLogger("riskwise.integrations.boundaries")


# =====================================================================
# Raw Event Storage Boundary
# =====================================================================

class RawEventStorage(ABC):
    """Abstract storage boundary for raw external events prior to normalization."""

    @abstractmethod
    def store_batch(self, batch: IngestionBatch) -> int:
        """Store a batch of raw events preserving provider payloads.

        Returns the number of stored events.
        """
        pass

    @abstractmethod
    def get_event(self, event_id: str) -> Optional[RawEvent]:
        """Retrieve a raw event by its internal identifier."""
        pass

    @abstractmethod
    def list_events(
        self,
        provider_name: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawEvent]:
        """List stored raw events with optional provider and organization filtering."""
        pass


class InMemoryRawEventStorage(RawEventStorage):
    """Thread-safe in-memory raw event storage used for ingestion buffering and testing."""

    def __init__(self, max_capacity: int = 10000) -> None:
        self._lock = threading.Lock()
        self._max_capacity = max_capacity
        self._events: Dict[str, RawEvent] = {}

    def store_batch(self, batch: IngestionBatch) -> int:
        stored_count = 0
        with self._lock:
            for event in batch.events:
                # Evict oldest if at capacity
                if len(self._events) >= self._max_capacity:
                    oldest_id = next(iter(self._events))
                    del self._events[oldest_id]
                self._events[event.id] = event
                stored_count += 1
        return stored_count

    def get_event(self, event_id: str) -> Optional[RawEvent]:
        with self._lock:
            return self._events.get(event_id)

    def list_events(
        self,
        provider_name: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[RawEvent]:
        with self._lock:
            events = list(self._events.values())
        if provider_name:
            events = [e for e in events if e.provider_name == provider_name]
        if org_id:
            events = [e for e in events if getattr(e, "org_id", None) == org_id]
        return events[-limit:]

    def clear(self) -> None:
        """Clear all stored events."""
        with self._lock:
            self._events.clear()


# =====================================================================
# Canonical Event Storage Boundary
# =====================================================================

class CanonicalEventStorage(ABC):
    """Abstract storage boundary for normalized CanonicalExternalEvent objects."""

    @abstractmethod
    def store(self, event: CanonicalExternalEvent) -> str:
        """Store a canonical event, returning its event_id."""
        pass

    @abstractmethod
    def store_batch(self, events: List[CanonicalExternalEvent]) -> int:
        """Store multiple canonical events, returning count stored."""
        pass

    @abstractmethod
    def get_event(self, event_id: str) -> Optional[CanonicalExternalEvent]:
        """Retrieve a canonical event by event_id."""
        pass

    @abstractmethod
    def list_events(
        self,
        provider: Optional[str] = None,
        event_type: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalExternalEvent]:
        """List canonical events with optional filtering."""
        pass


class InMemoryCanonicalEventStorage(CanonicalEventStorage):
    """Thread-safe in-memory store for normalized canonical events."""

    def __init__(self, max_capacity: int = 10000) -> None:
        self._lock = threading.Lock()
        self._max_capacity = max_capacity
        self._events: Dict[str, CanonicalExternalEvent] = {}

    def store(self, event: CanonicalExternalEvent) -> str:
        with self._lock:
            if len(self._events) >= self._max_capacity:
                oldest_id = next(iter(self._events))
                del self._events[oldest_id]
            self._events[event.event_id] = event
            return event.event_id

    def store_batch(self, events: List[CanonicalExternalEvent]) -> int:
        stored = 0
        with self._lock:
            for ev in events:
                if len(self._events) >= self._max_capacity:
                    oldest_id = next(iter(self._events))
                    del self._events[oldest_id]
                self._events[ev.event_id] = ev
                stored += 1
        return stored

    def get_event(self, event_id: str) -> Optional[CanonicalExternalEvent]:
        with self._lock:
            return self._events.get(event_id)

    def list_events(
        self,
        provider: Optional[str] = None,
        event_type: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalExternalEvent]:
        with self._lock:
            items = list(self._events.values())

        if provider:
            items = [e for e in items if e.provider.lower() == provider.lower()]
        if event_type:
            items = [e for e in items if str(e.event_type).upper() == event_type.upper()]
        if org_id:
            items = [e for e in items if e.org_id == org_id]

        return items[-limit:]

    def clear(self) -> None:
        """Clear all stored canonical events."""
        with self._lock:
            self._events.clear()


class ShipmentEventBridge:
    """Bridge mapping correlated CanonicalExternalEvent models to ShipmentEvent persistence dictionaries."""

    @classmethod
    def can_persist_to_shipment_event(cls, event: CanonicalExternalEvent) -> bool:
        """Check if an event satisfies the non-null shipment_id constraint of ShipmentEvent."""
        return bool(event.correlation and event.correlation.shipment_id)

    @classmethod
    def to_shipment_event_dict(cls, event: CanonicalExternalEvent) -> Dict[str, Any]:
        """Convert a canonical event into field values suitable for ShipmentEvent model creation.

        Raises:
            ValueError: If event has no correlated shipment_id.
        """
        if not cls.can_persist_to_shipment_event(event):
            raise ValueError(
                f"Canonical event '{event.event_id}' cannot be persisted to ShipmentEvent: "
                "missing required shipment_id correlation."
            )

        return {
            "shipment_id": event.correlation.shipment_id,
            "mode": getattr(event, "normalized_attributes", {}).get("mode", "OCEAN"),
            "event_type": str(event.event_type),
            "timestamp": event.event_timestamp,
            "latitude": event.latitude,
            "longitude": event.longitude,
            "status": event.status or "IN_TRANSIT",
            "eta": event.eta,
            "delay_minutes": event.delay_minutes,
            "source": str(event.source_type.value),
            "source_type": str(event.source_type.value),
            "confidence": event.confidence,
            "raw_event_id": event.raw_event_id,
            "metadata_json": {
                "provider": event.provider,
                "source_event_id": event.source_event_id,
                "payload_fingerprint": event.payload_fingerprint,
                "correlation_id": event.correlation_id,
                "request_id": getattr(event, "request_id", None),
                "trace_id": getattr(event, "trace_id", None),
                "ingestion_run_id": event.ingestion_run_id,
                "quality": event.quality.value,
                "normalized_attributes": event.normalized_attributes,
            },
        }


# =====================================================================
# Scheduling Boundary
# =====================================================================

@dataclass
class ScheduledIngestionJob:
    """Descriptor for a scheduled provider polling task."""

    job_id: str
    provider_name: str
    cron_or_interval: str
    enabled: bool = True
    parameters: Dict[str, Any] = field(default_factory=dict)
    organization_id: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    timeout_seconds: Optional[float] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    is_running: bool = False
    cancel_requested: bool = False
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0


class IngestionScheduler(ABC):
    """Abstract scheduling boundary for periodic ingestion (EventBridge / SQS / Celery-free workers)."""

    @abstractmethod
    def register_job(self, job: ScheduledIngestionJob) -> None:
        """Register a scheduled ingestion job."""
        pass

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[ScheduledIngestionJob]:
        """Get a scheduled job by its identifier."""
        pass

    @abstractmethod
    def list_jobs(self, enabled_only: bool = False, org_id: Optional[str] = None) -> List[ScheduledIngestionJob]:
        """List registered ingestion jobs."""
        pass

    @abstractmethod
    def unregister_job(self, job_id: str) -> bool:
        """Unregister a scheduled job."""
        pass

    @abstractmethod
    def request_cancel(self, job_id: str) -> bool:
        """Signal cancellation for a running or pending job."""
        pass

    @abstractmethod
    def execute_job(self, job_id: str, ingestion_service: Any) -> Any:
        """Execute a scheduled job with bounded execution and failure isolation."""
        pass


class InMemoryIngestionScheduler(IngestionScheduler):
    """In-memory scheduler registry with failure-isolated, bounded execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, ScheduledIngestionJob] = {}

    def register_job(self, job: ScheduledIngestionJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get_job(self, job_id: str) -> Optional[ScheduledIngestionJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, enabled_only: bool = False, org_id: Optional[str] = None) -> List[ScheduledIngestionJob]:
        with self._lock:
            jobs = list(self._jobs.values())
        if enabled_only:
            jobs = [j for j in jobs if j.enabled]
        if org_id:
            jobs = [j for j in jobs if j.organization_id == org_id]
        return jobs

    def unregister_job(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.cancel_requested = True
                return True
            return False

    def execute_job(self, job_id: str, ingestion_service: Any) -> Any:
        """Execute a job synchronously with bounded execution, failure isolation, and lifecycle tracking."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError(f"Job '{job_id}' not found in scheduler.")
            if not job.enabled:
                raise ValueError(f"Job '{job_id}' is disabled.")
            if job.cancel_requested:
                job.cancel_requested = False
                job.last_status = "CANCELLED"
                return None
            job.is_running = True
            job.total_runs += 1
            job.last_run_at = datetime.now(timezone.utc)

        try:
            # Execute through ingestion service with isolated error handling
            result = ingestion_service.ingest(
                provider_name=job.provider_name,
                parameters=job.parameters,
                organization_id=job.organization_id,
                raise_on_error=False,
            )
            with self._lock:
                raw_st = getattr(result, "status", "")
                st_str = (raw_st.value if hasattr(raw_st, "value") else str(raw_st)).upper()
                if st_str in ("SUCCESS", "PARTIAL", "SKIPPED_DUPLICATE"):
                    job.last_status = "SUCCESS"
                    job.consecutive_failures = 0
                    job.successful_runs += 1
                    job.last_error = None
                else:
                    job.last_status = "FAILED"
                    job.consecutive_failures += 1
                    job.failed_runs += 1
                    errors = getattr(result, "errors", [])
                    job.last_error = str(errors[0]) if errors else "Ingestion returned FAILED status"
            return result
        except Exception as exc:
            with self._lock:
                job.last_status = "FAILED"
                job.consecutive_failures += 1
                job.failed_runs += 1
                job.last_error = str(exc)
            logger.error("Isolated failure during scheduled job '%s' execution: %s", job_id, exc)
            return None
        finally:
            with self._lock:
                job.is_running = False


# =====================================================================
# Webhook Boundary
# =====================================================================

class WebhookReceiver(ABC):
    """Abstract webhook receiver boundary for push-based external providers."""

    @abstractmethod
    def verify_signature(
        self,
        payload_bytes: bytes,
        signature: str,
        secret: str,
    ) -> bool:
        """Verify webhook payload authenticity against signature header."""
        pass

    @abstractmethod
    def parse_payload(
        self,
        raw_body: bytes,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """Parse raw webhook bytes and headers into an event dictionary."""
        pass
