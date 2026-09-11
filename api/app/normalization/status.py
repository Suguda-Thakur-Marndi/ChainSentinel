"""Controlled status normalization and vocabulary mapping for Phase 6.

Maps disparate provider and domain statuses into canonical SignalStatus enums
while preserving the original unmapped status string in metadata.
"""

from __future__ import annotations

from typing import Optional

from app.normalization.contract import SignalStatus


class StatusNormalizer:
    """Deterministic status vocabulary normalizer."""

    _DELAY_SYNONYMS = {
        "delayed",
        "late",
        "behind schedule",
        "running late",
        "estimated delay",
        "delay",
        "postponed",
        "minor delay",
        "major delay",
    }

    _CANCEL_SYNONYMS = {
        "cancelled",
        "canceled",
        "void",
        "service cancelled",
        "service canceled",
        "abandoned",
        "aborted",
        "trip cancelled",
        "flight cancelled",
    }

    _ACTIVE_SYNONYMS = {
        "on_time",
        "on time",
        "on schedule",
        "active",
        "in_transit",
        "in transit",
        "moving",
        "operational",
        "normal",
        "en_route",
        "en route",
        "underway",
        "sailing",
        "airborne",
        "running",
        "planned",
    }

    _DISRUPTED_SYNONYMS = {
        "disrupted",
        "disruption",
        "incident",
        "accident",
        "congestion",
        "congested",
        "hazard",
        "alert",
        "warning",
        "severe",
        "closed",
        "closure",
        "blocked",
        "roadblock",
        "strike",
        "halted",
        "breakdown",
        "critical",
        "exception",
    }

    _RESOLVED_SYNONYMS = {
        "resolved",
        "delivered",
        "completed",
        "arrived",
        "cleared",
        "docked",
        "landed",
        "finished",
        "all clear",
    }

    @classmethod
    def normalize_status(cls, raw_status: Optional[str]) -> SignalStatus:
        """Map raw provider/canonical status text to SignalStatus."""
        if not raw_status or not raw_status.strip():
            return SignalStatus.ACTIVE

        clean = raw_status.strip().lower()

        # Direct checks
        if clean in cls._DELAY_SYNONYMS or "delay" in clean:
            return SignalStatus.DELAYED
        if clean in cls._CANCEL_SYNONYMS or "cancel" in clean:
            return SignalStatus.CANCELLED
        if clean in cls._DISRUPTED_SYNONYMS or "disrupt" in clean or "closed" in clean or "closure" in clean or "hazard" in clean:
            return SignalStatus.DISRUPTED
        if clean in cls._RESOLVED_SYNONYMS or "deliver" in clean or "arrived" in clean:
            return SignalStatus.RESOLVED
        if clean in cls._ACTIVE_SYNONYMS or "transit" in clean or "normal" in clean:
            return SignalStatus.ACTIVE

        # Default fallback
        return SignalStatus.UNKNOWN
