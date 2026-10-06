"""Background telemetry ingestion worker.

Periodically reads fresh telemetry objects from active providers (AISStream,
OpenSky, OpenWeather, TomTom), normalizes events, deduplicates, and persists
them to the `signals` table (and `shipment_events` when linked to shipments).

Provides graceful degradation for unconfigured or disabled providers.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from app.core.config import settings
from app.db.session import SessionLocal
from app.db.unit_of_work import UnitOfWork
from app.services.tracking import get_tracking_aggregator
from app.services.tracking.models import LiveMapObject, ProviderHealthStatus

logger = logging.getLogger("riskwise.integrations.worker")


class TelemetryIngestionWorker:
    """Scheduled background worker persisting real external telemetry into database signals."""

    def __init__(self, poll_interval_seconds: Optional[int] = None) -> None:
        self.poll_interval = poll_interval_seconds or getattr(settings, "TELEMETRY_POLL_INTERVAL_SECONDS", 60)
        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._last_run_timestamp: Optional[datetime] = None
        self._total_signals_ingested = 0

    def start(self) -> None:
        """Start the background ingestion loop if not already running."""
        if self._is_running:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._run_loop(), name="telemetry_ingestion_worker")
        logger.info(
            "[TelemetryWorker] Started background ingestion worker (interval=%ds)",
            self.poll_interval,
        )

    async def stop(self) -> None:
        """Gracefully stop the background ingestion worker."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[TelemetryWorker] Background ingestion worker stopped.")

    async def _run_loop(self) -> None:
        """Continuous ingestion loop with error containment."""
        # Wait initial 5 seconds for provider warm-up
        await asyncio.sleep(5)
        while self._is_running:
            cycle_start = time.perf_counter()
            try:
                await self.ingest_cycle()
            except Exception as e:
                logger.error("[TelemetryWorker] Unexpected error during ingestion cycle: %s", e, exc_info=True)

            elapsed = time.perf_counter() - cycle_start
            sleep_duration = max(1.0, self.poll_interval - elapsed)
            try:
                await asyncio.sleep(sleep_duration)
            except asyncio.CancelledError:
                break

    async def ingest_cycle(self) -> Dict[str, Any]:
        """Execute a single telemetry ingestion and persistence pass."""
        aggregator = get_tracking_aggregator()
        self._last_run_timestamp = datetime.now(timezone.utc)
        cycle_start = time.perf_counter()

        # 1. Inspect provider health to skip unconfigured cleanly
        health_resp = await aggregator.get_providers_health()
        for p in health_resp.providers:
            if p.status == ProviderHealthStatus.UNCONFIGURED:
                logger.debug("[TelemetryWorker] Provider %s is UNCONFIGURED. Skipping cleanly.", p.name)
            elif p.status in (ProviderHealthStatus.ERROR, ProviderHealthStatus.UNAVAILABLE):
                logger.warning(
                    "[TelemetryWorker] Provider %s is DEGRADED/ERROR: %s. Core platform unaffected.",
                    p.name,
                    p.reason or "No additional details",
                )

        # 2. Retrieve current normalized telemetry frames
        live_data = await aggregator.get_objects()
        raw_objects = live_data.items
        records_received = len(raw_objects)

        if not raw_objects:
            duration = time.perf_counter() - cycle_start
            return {
                "status": "IDLE",
                "records_received": 0,
                "records_persisted": 0,
                "records_skipped": 0,
                "duration_seconds": round(duration, 3),
            }

        records_persisted = 0
        records_skipped = 0
        errors = 0

        # Map object types to Risk Signal domains
        domain_map = {
            "vessel": "OCEAN",
            "aircraft": "AIR",
            "weather": "WEATHER",
            "traffic": "ROAD",
            "truck": "ROAD",
            "train": "RAIL",
            "shipment": "LOGISTICS",
            "incident": "GENERAL",
            "port": "OCEAN",
        }

        # 3. Persist valid objects into signals and correlate shipments
        with SessionLocal() as session:
            uow = UnitOfWork(session=session)
            for obj in raw_objects:
                try:
                    # Validate coordinate bounds
                    if not (-90.0 <= obj.latitude <= 90.0 and -180.0 <= obj.longitude <= 180.0):
                        records_skipped += 1
                        continue
                    if abs(obj.latitude) < 1e-6 and abs(obj.longitude) < 1e-6:
                        records_skipped += 1
                        continue

                    # Parse timestamp safely
                    try:
                        detected_at = datetime.fromisoformat(obj.timestamp)
                    except Exception:
                        detected_at = datetime.now(timezone.utc)

                    domain = domain_map.get(obj.type.lower(), "GENERAL")
                    signal_type = "HAZARD" if obj.type == "weather" else "STATUS_UPDATE"
                    severity = "HIGH" if obj.type == "incident" else "LOW"
                    if obj.type == "weather" and "alert" in obj.name.lower():
                        severity = "MEDIUM"

                    sig_id = f"sig_{obj.source}_{obj.id}"
                    sig_dict = {
                        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, sig_id)),
                        "signal_id": sig_id,
                        "org_id": None,
                        "domain": domain,
                        "signal_type": signal_type,
                        "status": obj.status or "ACTIVE",
                        "severity": severity,
                        "confidence": 1.0,
                        "source": obj.source,
                        "provider": obj.source,
                        "canonical_event_id": obj.identifier or obj.id,
                        "latitude": obj.latitude,
                        "longitude": obj.longitude,
                        "location_name": f"{obj.latitude:.3f},{obj.longitude:.3f}",
                        "title": obj.name or f"{obj.type.upper()} {obj.id}",
                        "summary": f"Telemetry frame from {obj.source}: {obj.name} (type={obj.type})",
                        "entity_type": obj.type.upper(),
                        "entity_id": obj.identifier or obj.id,
                        "delay_minutes": float(obj.metadata.get("delay_minutes", 0.0) or 0.0),
                        "payload_json": obj.metadata,
                        "detected_at": detected_at,
                    }

                    _, is_new = uow.signals.upsert_signal(sig_dict, auto_commit=False)
                    if is_new:
                        records_persisted += 1
                    else:
                        records_skipped += 1

                except Exception as row_err:
                    errors += 1
                    logger.debug("[TelemetryWorker] Error processing object %s: %s", obj.id, row_err)

            try:
                session.commit()
            except Exception as commit_err:
                session.rollback()
                logger.error("[TelemetryWorker] Database commit failed: %s", commit_err)
                errors += 1

        duration = time.perf_counter() - cycle_start
        self._total_signals_ingested += records_persisted

        logger.info(
            "[TelemetryWorker] Ingestion cycle complete: duration=%.2fs, received=%d, persisted=%d, skipped=%d, errors=%d",
            duration,
            records_received,
            records_persisted,
            records_skipped,
            errors,
        )

        return {
            "status": "SUCCESS",
            "records_received": records_received,
            "records_persisted": records_persisted,
            "records_skipped": records_skipped,
            "errors": errors,
            "duration_seconds": round(duration, 3),
            "timestamp": self._last_run_timestamp.isoformat(),
        }


_worker_instance: Optional[TelemetryIngestionWorker] = None


def get_telemetry_worker() -> TelemetryIngestionWorker:
    """Return singleton instance of TelemetryIngestionWorker."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = TelemetryIngestionWorker()
    return _worker_instance
