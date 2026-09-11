"""Normalization quality validation, safety checks, and structured reasons for Phase 6 Step 4.

Provides rigorous semantic, temporal, numerical, entity, and provenance validation
for NormalizedRiskSignal instances before downstream consumption by Phase 7 Risk Engine.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.canonical import (
    EventQuality,
    EventSeverity,
    EventSourceType,
)

logger = logging.getLogger("riskwise.normalization.quality")


class NormalizationQualityReason(str, Enum):
    """Structured, provider-independent quality and rejection reasons for normalized signals."""

    # Measurement & Unit Issues
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    NUMERIC_OUT_OF_BOUNDS = "NUMERIC_OUT_OF_BOUNDS"
    UNSUPPORTED_SEMANTIC_VALUE = "UNSUPPORTED_SEMANTIC_VALUE"

    # Spatial / Coordinate Issues
    INVALID_COORDINATE = "INVALID_COORDINATE"
    INCOMPLETE_COORDINATES = "INCOMPLETE_COORDINATES"

    # Temporal Issues
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    TEMPORAL_INCONSISTENCY = "TEMPORAL_INCONSISTENCY"

    # Completeness & Provenance Issues
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INCOMPLETE_PROVENANCE = "INCOMPLETE_PROVENANCE"

    # Entity & Correlation Issues
    UNRESOLVED_ENTITY = "UNRESOLVED_ENTITY"
    CONFLICTING_IDENTIFIERS = "CONFLICTING_IDENTIFIERS"
    NAMESPACE_MISMATCH = "NAMESPACE_MISMATCH"
    TENANT_MISMATCH = "TENANT_MISMATCH"

    # Cross-Source & Conflict Issues
    CONFLICTING_SOURCE_VALUES = "CONFLICTING_SOURCE_VALUES"
    DISPUTED_STATUS = "DISPUTED_STATUS"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"

    # Security & Integrity
    SUSPICIOUS_PAYLOAD = "SUSPICIOUS_PAYLOAD"


class QualityAssessmentResult(BaseModel):
    """Encapsulates the structured outcome of signal quality validation."""

    model_config = ConfigDict(extra="allow")

    quality: EventQuality
    reasons: List[NormalizationQualityReason] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.quality == EventQuality.VALID

    @property
    def is_partial(self) -> bool:
        return self.quality == EventQuality.PARTIAL

    @property
    def is_invalid(self) -> bool:
        return self.quality == EventQuality.INVALID


class SignalQualityValidator:
    """Authoritative semantic and safety validator for NormalizedRiskSignal instances.

    Evaluates:
    1. Identity & Tenancy
    2. Classification completeness
    3. Numeric safety (NaN, Inf, overflow, physical non-negativity)
    4. Temporal consistency (UTC, latency vs. impossible future, interval bounds)
    5. Spatial coordinates (WGS84 bounds, complete coordinate pairs)
    6. Entity consistency & conflict tracking
    7. Provenance completeness
    """

    # Maximum allowable clock skew (in seconds) for real-time events without scheduled flag
    MAX_CLOCK_SKEW_SECONDS = 300.0  # 5 minutes

    # Numerical upper bound to prevent float overflow / absurdity
    MAX_NUMERIC_LIMIT = 1e14

    @classmethod
    def validate_signal(cls, signal: Any) -> QualityAssessmentResult:
        """Perform end-to-end quality and safety validation on a normalized risk signal."""
        errors: List[str] = []
        warnings: List[str] = []
        reasons_set: Set[NormalizationQualityReason] = set()

        # ---------------------------------------------------------------------
        # 1. Type & Identity Validation
        # ---------------------------------------------------------------------
        if signal is None:
            return QualityAssessmentResult(
                quality=EventQuality.INVALID,
                reasons=[NormalizationQualityReason.MISSING_REQUIRED_FIELD],
                errors=["Signal object is None."],
            )

        signal_id = getattr(signal, "signal_id", None)
        if not signal_id or not str(signal_id).strip():
            errors.append("Signal missing required 'signal_id'.")
            reasons_set.add(NormalizationQualityReason.MISSING_REQUIRED_FIELD)

        canonical_event_id = getattr(signal, "canonical_event_id", None)
        if not canonical_event_id or not str(canonical_event_id).strip():
            errors.append("Signal missing required 'canonical_event_id' provenance.")
            reasons_set.add(NormalizationQualityReason.INCOMPLETE_PROVENANCE)

        # ---------------------------------------------------------------------
        # 2. Classification Validation
        # ---------------------------------------------------------------------
        event_type = getattr(signal, "event_type", None)
        if not event_type or not str(event_type).strip():
            errors.append("Signal missing required 'event_type'.")
            reasons_set.add(NormalizationQualityReason.MISSING_REQUIRED_FIELD)

        confidence = getattr(signal, "confidence", None)
        if confidence is not None:
            if math.isnan(confidence) or math.isinf(confidence):
                errors.append(f"Confidence value is invalid (NaN or Inf): {confidence}")
                reasons_set.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)
            elif not (0.0 <= confidence <= 1.0):
                errors.append(f"Confidence out of bounds [0.0, 1.0]: {confidence}")
                reasons_set.add(NormalizationQualityReason.NUMERIC_OUT_OF_BOUNDS)

        # ---------------------------------------------------------------------
        # 3. Numeric Safety Checks (Measurements & Coordinates)
        # ---------------------------------------------------------------------
        measurements = getattr(signal, "measurements", None)
        if measurements is not None:
            cls._validate_measurements(measurements, errors, warnings, reasons_set)

        # ---------------------------------------------------------------------
        # 4. Temporal Consistency Validation
        # ---------------------------------------------------------------------
        cls._validate_temporal_semantics(signal, errors, warnings, reasons_set)

        # ---------------------------------------------------------------------
        # 5. Spatial Coordinate Validation
        # ---------------------------------------------------------------------
        cls._validate_spatial_coordinates(signal, errors, warnings, reasons_set)

        # ---------------------------------------------------------------------
        # 6. Entity Consistency & Conflict Validation
        # ---------------------------------------------------------------------
        cls._validate_entities(signal, errors, warnings, reasons_set)

        # ---------------------------------------------------------------------
        # 7. Provenance Completeness Validation
        # ---------------------------------------------------------------------
        cls._validate_provenance(signal, errors, warnings, reasons_set)

        # ---------------------------------------------------------------------
        # 8. Cross-Source Disagreement & Conflict Tracking
        # ---------------------------------------------------------------------
        if getattr(signal, "has_conflict", False):
            warnings.append("Signal has registered semantic or entity conflicts.")
            reasons_set.add(NormalizationQualityReason.CONFLICTING_SOURCE_VALUES)

        # ---------------------------------------------------------------------
        # Determine Final Quality State
        # ---------------------------------------------------------------------
        sorted_reasons = sorted(list(reasons_set), key=lambda r: r.value)

        if errors:
            return QualityAssessmentResult(
                quality=EventQuality.INVALID,
                reasons=sorted_reasons,
                errors=sorted(errors),
                warnings=sorted(warnings),
            )

        if warnings or reasons_set:
            return QualityAssessmentResult(
                quality=EventQuality.PARTIAL,
                reasons=sorted_reasons,
                errors=[],
                warnings=sorted(warnings),
            )

        return QualityAssessmentResult(
            quality=EventQuality.VALID,
            reasons=[],
            errors=[],
            warnings=[],
        )

    # =========================================================================
    # Internal Validation Helpers
    # =========================================================================

    @classmethod
    def _validate_measurements(
        cls,
        m: Any,
        errors: List[str],
        warnings: List[str],
        reasons: Set[NormalizationQualityReason],
    ) -> None:
        """Validate physical telemetry values to prevent NaN, Inf, and impossible negatives."""
        # Non-negative metrics: (field_name, human_label)
        non_negative_fields = [
            ("distance_km", "Distance"),
            ("speed_kmh", "Speed"),
            ("weight_kg", "Weight"),
            ("volume_m3", "Volume"),
            ("monetary_amount", "Monetary amount"),
        ]

        for field_name, label in non_negative_fields:
            val = getattr(m, field_name, None)
            if val is None:
                continue

            # Check NaN / Inf
            if math.isnan(val) or math.isinf(val):
                errors.append(f"{label} has invalid numeric value (NaN or Inf): {val}")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)
                continue

            # Check overflow limit
            if abs(val) > cls.MAX_NUMERIC_LIMIT:
                errors.append(f"{label} exceeds physical numeric limit: {val}")
                reasons.add(NormalizationQualityReason.NUMERIC_OUT_OF_BOUNDS)
                continue

            # Physical non-negativity: never silently clamp, flag error
            if val < 0.0:
                errors.append(f"{label} cannot be negative (got {val}). Clamping is strictly prohibited.")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)

        # Delay minutes: delay NaN/Inf or overflow
        delay = getattr(m, "delay_minutes", None)
        if delay is not None:
            if math.isnan(delay) or math.isinf(delay):
                errors.append(f"Delay minutes has invalid numeric value: {delay}")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)
            elif abs(delay) > cls.MAX_NUMERIC_LIMIT:
                errors.append(f"Delay minutes exceeds numeric limits: {delay}")
                reasons.add(NormalizationQualityReason.NUMERIC_OUT_OF_BOUNDS)

        # Temperature: check NaN/Inf and absolute physical bounds
        temp = getattr(m, "temperature_celsius", None)
        if temp is not None:
            if math.isnan(temp) or math.isinf(temp):
                errors.append(f"Temperature has invalid numeric value: {temp}")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)
            elif temp < -273.15:
                # Below absolute zero is physically impossible
                errors.append(f"Temperature is below absolute zero (-273.15°C): {temp}")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)

        # Disruption level: bounded [0.0, 1.0]
        disruption = getattr(m, "disruption_level", None)
        if disruption is not None:
            if math.isnan(disruption) or math.isinf(disruption):
                errors.append(f"Disruption level has invalid numeric value: {disruption}")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)
            elif not (0.0 <= disruption <= 1.0):
                errors.append(f"Disruption level must be between 0.0 and 1.0, got {disruption}")
                reasons.add(NormalizationQualityReason.NUMERIC_OUT_OF_BOUNDS)

    @classmethod
    def _validate_temporal_semantics(
        cls,
        signal: Any,
        errors: List[str],
        warnings: List[str],
        reasons: Set[NormalizationQualityReason],
    ) -> None:
        """Validate timestamp consistency, UTC compliance, and interval logic."""
        event_time = getattr(signal, "event_time", None)
        received_at = getattr(signal, "received_at", None)
        observed_at = getattr(signal, "observed_at", None)
        eff_from = getattr(signal, "effective_from", None)
        eff_to = getattr(signal, "effective_to", None)

        if event_time is None:
            errors.append("Signal missing mandatory 'event_time'.")
            reasons.add(NormalizationQualityReason.MISSING_REQUIRED_FIELD)
            return

        # Ensure UTC timezone awareness
        for ts, name in [(event_time, "event_time"), (received_at, "received_at"), (observed_at, "observed_at")]:
            if ts is not None and ts.tzinfo is None:
                errors.append(f"Timestamp '{name}' is not timezone-aware UTC.")
                reasons.add(NormalizationQualityReason.INVALID_TIMESTAMP)

        # Effective interval validation: effective_from <= effective_to
        if eff_from is not None and eff_to is not None:
            if eff_from > eff_to:
                errors.append(
                    f"Temporal interval invalid: effective_from ({eff_from.isoformat()}) "
                    f"is strictly after effective_to ({eff_to.isoformat()})."
                )
                reasons.add(NormalizationQualityReason.TEMPORAL_INCONSISTENCY)

        # Ingestion Latency vs Clock Skew:
        # Legitimate delayed ingestion: event_time < received_at (normal and expected).
        # Impossible future timestamp: received_at < event_time - skew threshold
        if event_time is not None and received_at is not None:
            time_diff = (event_time - received_at).total_seconds()
            # If event_time is substantially in the future without an active/scheduled effective window
            if time_diff > cls.MAX_CLOCK_SKEW_SECONDS:
                # Check if signal is an advisory or scheduled future validity window
                is_scheduled = (
                    eff_from is not None
                    or getattr(signal, "signal_type", None) == "STATUS_UPDATE"
                    or (getattr(signal, "normalized_attributes", None) or {}).get("is_forecast", False)
                )
                if not is_scheduled:
                    errors.append(
                        f"Temporal anomaly: event_time ({event_time.isoformat()}) is {time_diff:.1f}s "
                        f"in the future relative to received_at ({received_at.isoformat()}) without scheduled context."
                    )
                    reasons.add(NormalizationQualityReason.TEMPORAL_INCONSISTENCY)

    @classmethod
    def _validate_spatial_coordinates(
        cls,
        signal: Any,
        errors: List[str],
        warnings: List[str],
        reasons: Set[NormalizationQualityReason],
    ) -> None:
        """Validate WGS84 geographic coordinate bounds and coordinate semantics."""
        lat = getattr(signal, "latitude", None)
        lon = getattr(signal, "longitude", None)

        if lat is not None and lon is None:
            warnings.append("Incomplete spatial coordinates: latitude provided without longitude.")
            reasons.add(NormalizationQualityReason.INCOMPLETE_COORDINATES)
        elif lon is not None and lat is None:
            warnings.append("Incomplete spatial coordinates: longitude provided without latitude.")
            reasons.add(NormalizationQualityReason.INCOMPLETE_COORDINATES)

        if lat is not None:
            if math.isnan(lat) or math.isinf(lat):
                errors.append(f"Latitude is invalid (NaN or Inf): {lat}")
                reasons.add(NormalizationQualityReason.INVALID_COORDINATE)
            elif not (-90.0 <= lat <= 90.0):
                errors.append(f"Latitude out of bounds [-90.0, 90.0]: {lat}")
                reasons.add(NormalizationQualityReason.INVALID_COORDINATE)

        if lon is not None:
            if math.isnan(lon) or math.isinf(lon):
                errors.append(f"Longitude is invalid (NaN or Inf): {lon}")
                reasons.add(NormalizationQualityReason.INVALID_COORDINATE)
            elif not (-180.0 <= lon <= 180.0):
                errors.append(f"Longitude out of bounds [-180.0, 180.0]: {lon}")
                reasons.add(NormalizationQualityReason.INVALID_COORDINATE)

        prec = getattr(signal, "precision_meters", None)
        if prec is not None:
            if math.isnan(prec) or math.isinf(prec) or prec < 0.0:
                errors.append(f"Precision meters cannot be negative or NaN: {prec}")
                reasons.add(NormalizationQualityReason.INVALID_NUMERIC_VALUE)

    @classmethod
    def _validate_entities(
        cls,
        signal: Any,
        errors: List[str],
        warnings: List[str],
        reasons: Set[NormalizationQualityReason],
    ) -> None:
        """Validate entity references, namespace formatting, and conflict markers."""
        entities = getattr(signal, "entities", None)
        if entities is None:
            warnings.append("Signal has no entity reference structure.")
            reasons.add(NormalizationQualityReason.UNRESOLVED_ENTITY)
            return

        org_id = getattr(signal, "organization_id", None)

        # Check entity references
        refs = getattr(entities, "references", []) or []
        for ref in refs:
            # Namespace existence
            if getattr(ref, "external_id", None) and not getattr(ref, "identifier_namespace", None):
                warnings.append(f"Entity reference for {ref.entity_type} missing identifier namespace.")
                reasons.add(NormalizationQualityReason.NAMESPACE_MISMATCH)

            # Conflict checking
            if getattr(ref, "is_conflict", False):
                warnings.append(f"Entity conflict detected on {ref.entity_type}: {ref.conflict_details}")
                reasons.add(NormalizationQualityReason.CONFLICTING_IDENTIFIERS)

            # Identifier type consistency (e.g. IMO vs MMSI)
            raw_id = getattr(ref, "raw_identifier", None)
            id_type = getattr(ref, "identifier_type", None)
            if id_type == "IMO" and raw_id:
                clean_digits = raw_id.upper().replace("IMO", "").replace("-", "").strip()
                if len(clean_digits) != 7 or not clean_digits.isdigit():
                    errors.append(f"IMO identifier malformed: '{raw_id}' does not conform to 7-digit IMO specification.")
                    reasons.add(NormalizationQualityReason.CONFLICTING_IDENTIFIERS)
            elif id_type == "MMSI" and raw_id:
                clean_digits = raw_id.replace("-", "").strip()
                if len(clean_digits) != 9 or not clean_digits.isdigit():
                    errors.append(f"MMSI identifier malformed: '{raw_id}' does not conform to 9-digit MMSI specification.")
                    reasons.add(NormalizationQualityReason.CONFLICTING_IDENTIFIERS)
            elif id_type == "ICAO24" and raw_id:
                clean_hex = raw_id.strip()
                if len(clean_hex) != 6 or not all(c in "0123456789abcdefABCDEF" for c in clean_hex):
                    errors.append(f"ICAO24 identifier malformed: '{raw_id}' does not conform to 6-hex-digit specification.")
                    reasons.add(NormalizationQualityReason.CONFLICTING_IDENTIFIERS)

        # Check for unlinked / unresolved entity status
        has_primary = getattr(entities, "has_any_entity", False)
        if not has_primary:
            warnings.append("Signal has no resolved primary supply-chain entities (unlinked signal).")
            reasons.add(NormalizationQualityReason.UNRESOLVED_ENTITY)

        # Check for registered conflict on entity container
        if getattr(entities, "has_conflict", False):
            warnings.append(f"Entity container indicates unresolved conflict: {entities.conflict_reason}")
            reasons.add(NormalizationQualityReason.CONFLICTING_IDENTIFIERS)

    @classmethod
    def _validate_provenance(
        cls,
        signal: Any,
        errors: List[str],
        warnings: List[str],
        reasons: Set[NormalizationQualityReason],
    ) -> None:
        """Validate completeness of mandatory provenance and traceability markers."""
        source = getattr(signal, "source", None)
        provider = getattr(signal, "provider", None)
        source_type = getattr(signal, "source_type", None)

        if not source or not str(source).strip():
            errors.append("Mandatory provenance field 'source' is empty.")
            reasons.add(NormalizationQualityReason.INCOMPLETE_PROVENANCE)

        if not provider or not str(provider).strip():
            errors.append("Mandatory provenance field 'provider' is empty.")
            reasons.add(NormalizationQualityReason.INCOMPLETE_PROVENANCE)

        if source_type is None:
            errors.append("Mandatory provenance field 'source_type' is empty.")
            reasons.add(NormalizationQualityReason.INCOMPLETE_PROVENANCE)
