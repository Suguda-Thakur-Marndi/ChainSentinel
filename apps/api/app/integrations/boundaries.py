"""Ingestion boundary abstractions for raw storage, scheduling, and webhooks.

Step 1 establishes the structural boundaries without coupling to specific
external providers, production cron daemons, or webhook routes.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.integrations.base import IngestionBatch, RawEvent

logger = logging.getLogger("riskwise.integrations.boundaries")


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
        limit: int = 100,
    ) -> List[RawEvent]:
        """List stored raw events with optional provider filtering."""
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
        limit: int = 100,
    ) -> List[RawEvent]:
        with self._lock:
            events = list(self._events.values())
        if provider_name:
            events = [e for e in events if e.provider_name == provider_name]
        return events[-limit:]

    def clear(self) -> None:
        """Clear all stored events."""
        with self._lock:
            self._events.clear()


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
    def list_jobs(self, enabled_only: bool = False) -> List[ScheduledIngestionJob]:
        """List registered ingestion jobs."""
        pass

    @abstractmethod
    def unregister_job(self, job_id: str) -> bool:
        """Unregister a scheduled job."""
        pass


class InMemoryIngestionScheduler(IngestionScheduler):
    """In-memory scheduler registry for Step 1 architectural compliance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, ScheduledIngestionJob] = {}

    def register_job(self, job: ScheduledIngestionJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get_job(self, job_id: str) -> Optional[ScheduledIngestionJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self, enabled_only: bool = False) -> List[ScheduledIngestionJob]:
        with self._lock:
            jobs = list(self._jobs.values())
        if enabled_only:
            jobs = [j for j in jobs if j.enabled]
        return jobs

    def unregister_job(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None


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
