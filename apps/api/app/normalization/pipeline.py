"""Normalization pipeline and batch orchestrator for Phase 6.

Processes CanonicalExternalEvent instances into NormalizedRiskSignal representations
with deterministic routing, unit standardisation, semantic deduplication,
and multi-source corroboration.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.canonical import (
    CanonicalExternalEvent,
    EventQuality,
    EventSourceType,
)
from app.normalization.contract import (
    CorroboratingEvidence,
    NormalizedRiskSignal,
)
from app.normalization.handlers import DomainNormalizationRegistry

logger = logging.getLogger("riskwise.normalization.pipeline")


class NormalizationStatus(str, Enum):
    """Execution status of a normalization operation."""

    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"


class NormalizationResult(BaseModel):
    """Result of normalizing a single canonical event."""

    model_config = ConfigDict(extra="allow")

    status: NormalizationStatus
    signal: Optional[NormalizedRiskSignal] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        """Return True if normalization produced a usable signal."""
        return self.status in (NormalizationStatus.VALID, NormalizationStatus.PARTIAL) and self.signal is not None


class BatchNormalizationResult(BaseModel):
    """Result of normalizing a batch of canonical events."""

    model_config = ConfigDict(extra="allow")

    total_count: int = 0
    valid_count: int = 0
    partial_count: int = 0
    invalid_count: int = 0
    signals: List[NormalizedRiskSignal] = Field(default_factory=list)
    rejected_signals: List[Dict[str, Any]] = Field(default_factory=list)
    duration_ms: float = 0.0


# Source precedence ranking for source-of-truth conflict resolution
_SOURCE_PRECEDENCE = {
    EventSourceType.REAL: 3,
    EventSourceType.ESTIMATED: 2,
    EventSourceType.SIMULATED: 1,
}


class NormalizationPipeline:
    """Core Phase 6 normalization pipeline orchestrator."""

    def __init__(self, registry: Optional[DomainNormalizationRegistry] = None) -> None:
        self.registry = registry or DomainNormalizationRegistry()

    def normalize_event(self, event: Any) -> NormalizationResult:
        """Normalize a single CanonicalExternalEvent into a NormalizedRiskSignal."""
        start_time = time.perf_counter()
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Type Boundary Verification
        if not isinstance(event, CanonicalExternalEvent):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[
                    f"Invalid event type: expected CanonicalExternalEvent, got {type(event).__name__}. "
                    "Phase 6 normalizer cannot directly consume raw provider payloads."
                ],
                duration_ms=duration_ms,
            )

        # 2. Structural & Quality Validation
        if event.quality == EventQuality.INVALID:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=["Event has EventQuality.INVALID and cannot be converted to an active risk signal."] + event.validation_errors,
                duration_ms=duration_ms,
            )

        # 3. Coordinate Bounds Defense
        if event.latitude is not None and not (-90.0 <= event.latitude <= 90.0):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[f"Invalid latitude: {event.latitude}. Must be between -90.0 and 90.0."],
                duration_ms=duration_ms,
            )

        if event.longitude is not None and not (-180.0 <= event.longitude <= 180.0):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[f"Invalid longitude: {event.longitude}. Must be between -180.0 and 180.0."],
                duration_ms=duration_ms,
            )

        # 4. Domain Handler Resolution & Execution
        try:
            handler = self.registry.resolve_handler(event)
            signal = handler.normalize(event)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error("Error normalizing canonical event '%s': %s", event.event_id, exc)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[f"Domain normalization failed: {str(exc)}"],
                duration_ms=duration_ms,
            )

        # 5. Quality & Status Assessment
        if event.quality == EventQuality.PARTIAL or not signal.entities.has_any_entity:
            status = NormalizationStatus.PARTIAL
            if not signal.entities.has_any_entity:
                warnings.append("Signal has no resolved primary supply-chain entities (stored as unlinked signal).")
        else:
            status = NormalizationStatus.VALID

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return NormalizationResult(
            status=status,
            signal=signal,
            errors=errors,
            warnings=warnings,
            duration_ms=duration_ms,
        )

    def normalize_batch(self, events: List[Any]) -> BatchNormalizationResult:
        """Normalize a batch of canonical events with failure isolation."""
        start_time = time.perf_counter()
        valid_count = 0
        partial_count = 0
        invalid_count = 0
        signals: List[NormalizedRiskSignal] = []
        rejected_signals: List[Dict[str, Any]] = []

        for item in events:
            result = self.normalize_event(item)
            if result.is_success and result.signal is not None:
                if result.status == NormalizationStatus.VALID:
                    valid_count += 1
                else:
                    partial_count += 1
                signals.append(result.signal)
            else:
                invalid_count += 1
                ev_id = getattr(item, "event_id", str(item))
                rejected_signals.append({
                    "event_id": ev_id,
                    "errors": result.errors,
                    "duration_ms": result.duration_ms,
                })

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return BatchNormalizationResult(
            total_count=len(events),
            valid_count=valid_count,
            partial_count=partial_count,
            invalid_count=invalid_count,
            signals=signals,
            rejected_signals=rejected_signals,
            duration_ms=duration_ms,
        )

    def deduplicate_and_corroborate(
        self,
        signals: List[NormalizedRiskSignal],
    ) -> List[NormalizedRiskSignal]:
        """Perform semantic deduplication and multi-source corroboration across signals.

        When two signals share identical semantic fingerprints:
        - Exact duplicates (same source and canonical event ID) are dropped.
        - Corroborating signals (different sources or canonical events) are merged into
          the primary signal's supporting_sources without loss of provenance.
        - Source precedence is respected (REAL > ESTIMATED > SIMULATED).
        """
        deduped: Dict[str, NormalizedRiskSignal] = {}

        for sig in signals:
            fp = sig.fingerprint or sig.generate_fingerprint()

            if fp not in deduped:
                deduped[fp] = sig
            else:
                existing = deduped[fp]

                # Exact duplicate check
                if (
                    existing.source == sig.source
                    and existing.canonical_event_id == sig.canonical_event_id
                    and existing.provider_event_id == sig.provider_event_id
                ):
                    continue

                # Multi-source corroboration
                new_evidence = CorroboratingEvidence(
                    source=sig.source,
                    provider=sig.provider,
                    canonical_event_id=sig.canonical_event_id,
                    provider_event_id=sig.provider_event_id,
                    source_reference=sig.source_reference,
                    confidence=sig.confidence,
                    observed_at=sig.observed_at or sig.event_time,
                    summary=f"Corroborating signal from {sig.source} ({sig.event_type})",
                )

                # Check precedence: if the incoming signal has strictly higher precedence, promote it
                existing_prec = _SOURCE_PRECEDENCE.get(existing.source_type, 0)
                incoming_prec = _SOURCE_PRECEDENCE.get(sig.source_type, 0)

                if incoming_prec > existing_prec:
                    # Demote existing to supporting source and adopt incoming as primary
                    demoted_evidence = CorroboratingEvidence(
                        source=existing.source,
                        provider=existing.provider,
                        canonical_event_id=existing.canonical_event_id,
                        provider_event_id=existing.provider_event_id,
                        source_reference=existing.source_reference,
                        confidence=existing.confidence,
                        observed_at=existing.observed_at or existing.event_time,
                        summary=f"Prior evidence from {existing.source}",
                    )
                    sig.add_corroborating_evidence(demoted_evidence)
                    for prior in existing.supporting_sources:
                        sig.add_corroborating_evidence(prior)
                    deduped[fp] = sig
                else:
                    # Retain existing primary, attach incoming as corroborating evidence
                    existing.add_corroborating_evidence(new_evidence)
                    for prior in sig.supporting_sources:
                        existing.add_corroborating_evidence(prior)

        return list(deduped.values())
