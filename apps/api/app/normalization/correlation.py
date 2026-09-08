"""Cross-Source Event Correlation and Deduplication Engine for Phase 6 Step 3.

Provides deterministic event fingerprinting, $O(1)$ in-memory indexing, source precedence hierarchy,
conflict preservation, and multi-tenant isolation for multi-source risk signal corroboration.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.integrations.canonical import EventSeverity, EventSourceType
from app.normalization.contract import (
    CorroboratingEvidence,
    NormalizedRiskSignal,
    SignalStatus,
)

logger = logging.getLogger("riskwise.normalization.correlation")


# Source precedence weights: REAL (3) > ESTIMATED (2) > SIMULATED (1)
_PRECEDENCE_WEIGHTS = {
    EventSourceType.REAL: 3,
    EventSourceType.ESTIMATED: 2,
    EventSourceType.SIMULATED: 1,
}


def _get_precedence(source_type: EventSourceType) -> int:
    return _PRECEDENCE_WEIGHTS.get(source_type, 1)


class CrossSourceCorrelator:
    """Deterministic, high-performance cross-source risk signal correlator."""

    def __init__(self) -> None:
        # Index: Dict[correlation_key, NormalizedRiskSignal]
        self._index: Dict[str, NormalizedRiskSignal] = {}
        # Track seen provider event IDs to identify exact duplicates: Set[Tuple[org_id, provider, source_event_id/canonical_id]]
        self._seen_event_ids: Set[Tuple[str, str, str]] = set()

    def generate_correlation_key(self, signal: NormalizedRiskSignal) -> str:
        """Compute a deterministic SHA-256 event correlation key.

        Components:
        - organization_id (strictly isolates multi-tenant events)
        - domain
        - signal_type
        - event_type
        - primary_entity_key (exact internal ID or strong asset ID)
        - spatial_bucket (0.01 deg ~= 1.1 km precision)
        - temporal_bucket (1-hour UTC bucket)
        - incident_reference (optional external incident/alert ID)
        """
        org_id = signal.organization_id or "global"
        domain = signal.domain.value
        sig_type = signal.signal_type.value
        ev_type = signal.event_type.strip().upper()

        # Extract primary entity key
        e = signal.entities
        entity_key = (
            e.shipment_id
            or e.supplier_id
            or e.port_id
            or e.route_id
            or e.vessel_mmsi
            or e.aircraft_icao24
            or e.vehicle_id
            or "unlinked"
        )

        # Spatial bucket (~1.1 km)
        lat_bucket = f"{signal.latitude:.2f}" if signal.latitude is not None else "none"
        lon_bucket = f"{signal.longitude:.2f}" if signal.longitude is not None else "none"

        # Temporal bucket (1-hour window)
        time_bucket = signal.event_time.strftime("%Y-%m-%d-%H") if signal.event_time else "none"

        # Incident / alert reference ID if shared across feeds
        attrs = signal.normalized_attributes
        incident_ref = (
            attrs.get("incident_id")
            or attrs.get("alert_id")
            or attrs.get("closure_id")
            or "none"
        )

        token_str = (
            f"{org_id}|{domain}|{sig_type}|{ev_type}|{entity_key}|"
            f"{lat_bucket}|{lon_bucket}|{time_bucket}|{incident_ref}"
        )
        return hashlib.sha256(token_str.encode("utf-8")).hexdigest()

    def correlate_signal(self, signal: NormalizedRiskSignal) -> NormalizedRiskSignal:
        """Process an incoming signal against the corroboration index.

        - If EXACT DUPLICATE: Returns existing signal without inflating evidence.
        - If CORROBORATING EVIDENCE: Merges secondary source into primary signal with zero provenance loss.
        - If NEW EVENT: Registers signal in index.
        """
        key = self.generate_correlation_key(signal)
        org_id = signal.organization_id or "global"
        dedup_id = signal.provider_event_id or signal.canonical_event_id
        dedup_tuple = (org_id, signal.provider, dedup_id)

        # 1. Exact Duplicate Detection
        if dedup_tuple in self._seen_event_ids:
            logger.debug("Exact duplicate detected for %s; skipping evidence inflation", dedup_tuple)
            return self._index.get(key, signal)

        self._seen_event_ids.add(dedup_tuple)

        # 2. Check for existing correlated physical event
        existing = self._index.get(key)
        if existing is None:
            # First observation of this incident
            signal.fingerprint = key
            self._index[key] = signal
            return signal

        # 3. Corroborating Event from Independent Source
        existing_precedence = _get_precedence(existing.source_type)
        incoming_precedence = _get_precedence(signal.source_type)

        # Check for status conflict
        has_status_conflict = existing.status != signal.status
        if has_status_conflict:
            conflict_record = {
                "source_a": existing.source,
                "status_a": existing.status.value,
                "source_b": signal.source,
                "status_b": signal.status.value,
                "timestamp_a": existing.event_time.isoformat(),
                "timestamp_b": signal.event_time.isoformat(),
            }
            existing.canonical_attributes.setdefault("status_conflicts", []).append(conflict_record)
            signal.canonical_attributes.setdefault("status_conflicts", []).append(conflict_record)

        if incoming_precedence > existing_precedence:
            # Incoming signal has higher precedence (e.g. REAL vs ESTIMATED):
            # Promote incoming signal to primary; demote existing to supporting evidence
            demoted_evidence = CorroboratingEvidence(
                source=existing.source,
                provider=existing.provider,
                canonical_event_id=existing.canonical_event_id,
                provider_event_id=existing.provider_event_id,
                source_reference=existing.source_reference,
                confidence=existing.confidence,
                observed_at=existing.observed_at or existing.event_time,
                summary=f"Demoted primary (precedence {existing_precedence} < {incoming_precedence})",
            )
            signal.add_corroborating_evidence(demoted_evidence)
            # Copy over existing supporting evidence
            for ev in existing.supporting_sources:
                signal.add_corroborating_evidence(ev)

            signal.fingerprint = key
            self._index[key] = signal
            return signal
        else:
            # Existing signal has higher or equal precedence:
            # Append incoming signal as corroborating evidence to existing signal
            incoming_evidence = CorroboratingEvidence(
                source=signal.source,
                provider=signal.provider,
                canonical_event_id=signal.canonical_event_id,
                provider_event_id=signal.provider_event_id,
                source_reference=signal.source_reference,
                confidence=signal.confidence,
                observed_at=signal.observed_at or signal.event_time,
                summary=f"Corroborating observation from {signal.provider}",
            )
            existing.add_corroborating_evidence(incoming_evidence)
            # Merge any supporting sources incoming signal might have
            for ev in signal.supporting_sources:
                existing.add_corroborating_evidence(ev)

            return existing

    def correlate_signals(self, signals: List[NormalizedRiskSignal]) -> List[NormalizedRiskSignal]:
        """Correlate a batch of normalized signals and return deduplicated, corroborated list."""
        for s in signals:
            self.correlate_signal(s)
        return list(self._index.values())

    def get_corroborated_signals(self) -> List[NormalizedRiskSignal]:
        """Retrieve all currently indexed corroborated signals."""
        return list(self._index.values())

    def clear(self) -> None:
        """Reset the correlation index and seen event tracker."""
        self._index.clear()
        self._seen_event_ids.clear()
