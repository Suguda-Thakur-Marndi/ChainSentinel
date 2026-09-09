"""Normalization pipeline and batch orchestrator for Phase 6 Step 4.

Authoritative end-to-end normalization pipeline that transforms CanonicalExternalEvent
instances into deterministic, validated, provenance-preserving NormalizedRiskSignal representations.
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
    generate_deterministic_signal_id,
)
from app.normalization.correlation import CrossSourceCorrelator
from app.normalization.entity_resolver import EntityNormalizer
from app.normalization.handlers import DomainNormalizationRegistry
from app.normalization.quality import (
    NormalizationQualityReason,
    QualityAssessmentResult,
    SignalQualityValidator,
)

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
    quality_reasons: List[str] = Field(default_factory=list)
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
    duplicate_count: int = 0
    corroborated_count: int = 0
    signals: List[NormalizedRiskSignal] = Field(default_factory=list)
    finalized_signals: List[NormalizedRiskSignal] = Field(default_factory=list)
    valid_signals: List[NormalizedRiskSignal] = Field(default_factory=list)
    partial_signals: List[NormalizedRiskSignal] = Field(default_factory=list)
    rejected_signals: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


# Source precedence ranking for source-of-truth conflict resolution
_SOURCE_PRECEDENCE = {
    EventSourceType.REAL: 3,
    EventSourceType.ESTIMATED: 2,
    EventSourceType.SIMULATED: 1,
}


class NormalizationPipeline:
    """Core authoritative Phase 6 normalization pipeline orchestrator."""

    def __init__(
        self,
        registry: Optional[DomainNormalizationRegistry] = None,
        entity_normalizer: Optional[EntityNormalizer] = None,
        cross_source_correlator: Optional[CrossSourceCorrelator] = None,
    ) -> None:
        self.registry = registry or DomainNormalizationRegistry()
        self.entity_normalizer = entity_normalizer if entity_normalizer is not None else EntityNormalizer()
        self.cross_source_correlator = cross_source_correlator or CrossSourceCorrelator()

    def normalize_event(self, event: Any) -> NormalizationResult:
        """Normalize a single CanonicalExternalEvent into an authoritative NormalizedRiskSignal."""
        start_time = time.perf_counter()
        errors: List[str] = []
        warnings: List[str] = []
        quality_reasons: List[str] = []

        # ---------------------------------------------------------------------
        # 1. Type Boundary Verification
        # ---------------------------------------------------------------------
        if not isinstance(event, CanonicalExternalEvent):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[
                    f"Invalid event type: expected CanonicalExternalEvent, got {type(event).__name__}. "
                    "Phase 6 normalizer cannot directly consume raw provider payloads."
                ],
                quality_reasons=[NormalizationQualityReason.MISSING_REQUIRED_FIELD.value],
                duration_ms=duration_ms,
            )

        # ---------------------------------------------------------------------
        # 2. Structural & Quality Validation (Upstream Phase 5 Model)
        # ---------------------------------------------------------------------
        if event.quality == EventQuality.INVALID:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=["Event has EventQuality.INVALID and cannot be converted to an active risk signal."] + event.validation_errors,
                quality_reasons=[NormalizationQualityReason.MISSING_REQUIRED_FIELD.value],
                duration_ms=duration_ms,
            )

        # ---------------------------------------------------------------------
        # 3. Coordinate Bounds Defense
        # ---------------------------------------------------------------------
        if event.latitude is not None and not (-90.0 <= event.latitude <= 90.0):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[f"Invalid latitude: {event.latitude}. Must be between -90.0 and 90.0."],
                quality_reasons=[NormalizationQualityReason.INVALID_COORDINATE.value],
                duration_ms=duration_ms,
            )

        if event.longitude is not None and not (-180.0 <= event.longitude <= 180.0):
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=[f"Invalid longitude: {event.longitude}. Must be between -180.0 and 180.0."],
                quality_reasons=[NormalizationQualityReason.INVALID_COORDINATE.value],
                duration_ms=duration_ms,
            )

        # ---------------------------------------------------------------------
        # 4. Domain Handler Resolution & Execution
        # ---------------------------------------------------------------------
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
                quality_reasons=[NormalizationQualityReason.UNSUPPORTED_SEMANTIC_VALUE.value],
                duration_ms=duration_ms,
            )

        # ---------------------------------------------------------------------
        # 5. Entity Normalization (Phase 6 Step 3)
        # ---------------------------------------------------------------------
        if self.entity_normalizer is not None:
            try:
                signal = self.entity_normalizer.normalize_entities(signal)
            except Exception as exc:
                logger.warning("Entity normalization error on event '%s': %s", event.event_id, exc)
                warnings.append(f"Entity normalization encountered error: {str(exc)}")
                quality_reasons.append(NormalizationQualityReason.UNRESOLVED_ENTITY.value)

        # ---------------------------------------------------------------------
        # 6. Deterministic Identity Assignment
        # ---------------------------------------------------------------------
        signal.signal_id = generate_deterministic_signal_id(signal.organization_id, signal.canonical_event_id)

        # ---------------------------------------------------------------------
        # 7. Field-Level & Numeric Safety Validation (Step 4 Quality Engine)
        # ---------------------------------------------------------------------
        assessment = SignalQualityValidator.validate_signal(signal)
        if assessment.is_invalid:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            all_errors = sorted(list(set(errors + assessment.errors)))
            all_reasons = sorted(list(set([r.value for r in assessment.reasons] + quality_reasons)))
            return NormalizationResult(
                status=NormalizationStatus.INVALID,
                signal=None,
                errors=all_errors,
                warnings=assessment.warnings,
                quality_reasons=all_reasons,
                duration_ms=duration_ms,
            )

        # ---------------------------------------------------------------------
        # 8. Quality & Status Assessment
        # ---------------------------------------------------------------------
        is_partial = (
            event.quality == EventQuality.PARTIAL
            or assessment.is_partial
            or not signal.entities.has_any_entity
        )

        if is_partial:
            status = NormalizationStatus.PARTIAL
            signal.quality = EventQuality.PARTIAL
            if not signal.entities.has_any_entity:
                warnings.append("Signal has no resolved primary supply-chain entities (stored as unlinked signal).")
                quality_reasons.append(NormalizationQualityReason.UNRESOLVED_ENTITY.value)
        else:
            status = NormalizationStatus.VALID
            signal.quality = EventQuality.VALID

        # Merge warnings and quality reasons
        for r in assessment.reasons:
            if r.value not in quality_reasons:
                quality_reasons.append(r.value)
        warnings = sorted(list(set(warnings + assessment.warnings)))
        quality_reasons = sorted(list(set(quality_reasons + signal.quality_reasons)))
        signal.quality_reasons = quality_reasons
        signal.fingerprint = signal.generate_fingerprint()

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return NormalizationResult(
            status=status,
            signal=signal,
            errors=[],
            warnings=warnings,
            quality_reasons=quality_reasons,
            duration_ms=duration_ms,
        )

    def normalize_batch(self, events: List[Any], correlate: bool = False) -> BatchNormalizationResult:
        """Normalize a batch of canonical events with complete failure isolation."""
        start_time = time.perf_counter()
        valid_count = 0
        partial_count = 0
        invalid_count = 0
        signals: List[NormalizedRiskSignal] = []
        valid_signals: List[NormalizedRiskSignal] = []
        partial_signals: List[NormalizedRiskSignal] = []
        rejected_signals: List[Dict[str, Any]] = []

        for item in events:
            result = self.normalize_event(item)
            if result.is_success and result.signal is not None:
                if result.status == NormalizationStatus.VALID:
                    valid_count += 1
                    valid_signals.append(result.signal)
                else:
                    partial_count += 1
                    partial_signals.append(result.signal)
                signals.append(result.signal)
            else:
                invalid_count += 1
                ev_id = getattr(item, "event_id", str(item))
                rejected_signals.append({
                    "event_id": ev_id,
                    "errors": result.errors,
                    "quality_reasons": result.quality_reasons,
                    "duration_ms": result.duration_ms,
                })

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        duplicate_count = 0
        corroborated_count = 0
        finalized_signals = list(signals)

        if correlate and signals:
            correlator = CrossSourceCorrelator()
            finalized_signals = correlator.correlate_signals(signals)
            duplicate_count = correlator.duplicate_count
            corroborated_count = correlator.corroborated_count

        metrics = {
            "total_received": len(events),
            "valid_signals": valid_count,
            "partial_signals": partial_count,
            "rejected_signals": invalid_count,
            "duplicate_signals": duplicate_count,
            "corroborated_signals": corroborated_count,
            "processing_duration_ms": duration_ms,
        }

        return BatchNormalizationResult(
            total_count=len(events),
            valid_count=valid_count,
            partial_count=partial_count,
            invalid_count=invalid_count,
            duplicate_count=duplicate_count,
            corroborated_count=corroborated_count,
            signals=signals,
            finalized_signals=finalized_signals,
            valid_signals=valid_signals,
            partial_signals=partial_signals,
            rejected_signals=rejected_signals,
            metrics=metrics,
            duration_ms=duration_ms,
        )

    def finalize_batch(self, events: List[Any]) -> BatchNormalizationResult:
        """Authoritative batch normalization, deduplication, conflict resolution, and corroboration."""
        return self.normalize_batch(events, correlate=True)

    def deduplicate_and_corroborate(
        self,
        signals: List[NormalizedRiskSignal],
    ) -> List[NormalizedRiskSignal]:
        """Perform semantic deduplication and multi-source corroboration across signals.

        When two signals share identical semantic fingerprints:
        - Exact duplicates (same source and canonical event ID) are dropped without inflating evidence.
        - Corroborating signals (different sources or canonical events) are merged into
          the primary signal's supporting_sources without loss of provenance.
        - Source precedence is respected (REAL > ESTIMATED > SIMULATED).
        - Disagreements and conflicts are preserved in structured conflict records.
        """
        # Instantiate fresh correlator for deterministic batch isolation
        correlator = CrossSourceCorrelator()
        return correlator.correlate_signals(signals)
