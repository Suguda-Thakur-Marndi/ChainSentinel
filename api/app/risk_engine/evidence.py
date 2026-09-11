"""Evidence representation and provenance lineage tracking for RiskWise Risk Engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.canonical import EventQuality, EventSourceType
from app.normalization.contract import NormalizedRiskSignal
from app.risk_engine.errors import RiskEngineInputError, TenantMismatchError


class EvidenceRelevance(str, Enum):
    """Deterministic relevance classification of evidence relative to evaluated risk factors."""

    PRIMARY = "PRIMARY"          # Direct primary observation triggering the factor
    SUPPORTING = "SUPPORTING"    # Contextual or adjacent route/network observation
    CORROBORATING = "CORROBORATING"  # Independent external confirmation of the same condition
    CONTEXTUAL = "CONTEXTUAL"    # Operational background or ambient conditions
    CONFLICTING = "CONFLICTING"  # Contradictory provider observation
    LIMITATION = "LIMITATION"    # Degraded or partial data explaining evaluation uncertainty


def generate_deterministic_evidence_id(
    organization_id: Optional[str],
    signal_id: str,
    provider: Optional[str] = None,
) -> str:
    """Generate a reproducible UUIDv5 evidence identifier based on tenant, signal ID, and optional provider."""
    org = organization_id or "global"
    prov = f":{provider}" if provider else ""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{org}:evidence:{signal_id}{prov}"))


def derive_evidence_relevance(
    signal: NormalizedRiskSignal,
    factor_type: Optional[str] = None,
    is_primary: bool = True,
) -> EvidenceRelevance:
    """Deterministically derive evidence relevance classification without generative models.

    Derivation Rules:
    1. Signals with unresolved conflicts -> CONFLICTING
    2. Signals with INVALID quality -> LIMITATION
    3. Signals with PARTIAL quality and secondary role -> LIMITATION
    4. Direct domain observations evaluated as factor foundation -> PRIMARY
    5. Independent corroborating observations -> CORROBORATING
    6. Contextual observations -> SUPPORTING
    """
    if getattr(signal, "has_conflict", False) or (getattr(signal, "conflicts", None) and len(signal.conflicts) > 0):
        return EvidenceRelevance.CONFLICTING

    if signal.quality == EventQuality.INVALID:
        return EvidenceRelevance.LIMITATION

    if not is_primary:
        if signal.quality == EventQuality.PARTIAL:
            return EvidenceRelevance.LIMITATION
        if len(getattr(signal, "supporting_sources", [])) > 0:
            return EvidenceRelevance.CORROBORATING
        return EvidenceRelevance.SUPPORTING

    return EvidenceRelevance.PRIMARY


class RiskEvidence(BaseModel):
    """Traceable evidence unit linking a RiskFactor back to its NormalizedRiskSignal lineage."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    evidence_id: str = Field(..., min_length=1, description="Deterministic unique evidence identifier.")
    normalized_signal_id: str = Field(..., min_length=1, description="Lineage link to NormalizedRiskSignal.signal_id.")
    organization_id: Optional[str] = Field(default=None, description="Tenant organization identifier.")
    factor_id: Optional[str] = Field(default=None, description="Target factor identifier if linked.")
    source: str = Field(..., min_length=1, description="Primary external source name.")
    provider: str = Field(..., min_length=1, description="Ingestion provider name.")
    source_type: EventSourceType = Field(default=EventSourceType.REAL, description="Nature of observation (REAL, ESTIMATED, SIMULATED).")
    event_time: datetime = Field(..., description="Timestamp when the real-world condition occurred.")
    relevance: Union[EvidenceRelevance, float, str] = Field(
        default=EvidenceRelevance.PRIMARY,
        description="Deterministic evidence relevance classification or semantic weight.",
    )
    fingerprint: Optional[str] = Field(default=None, description="Deterministic semantic fingerprint.")
    quality: Optional[EventQuality] = Field(default=None, description="Signal data quality state (VALID, PARTIAL, INVALID).")
    has_conflict: bool = Field(default=False, description="Whether signal carries unresolved multi-source conflict.")
    conflicts: List[Dict[str, Any]] = Field(default_factory=list, description="Preserved conflict details.")
    location: Optional[Dict[str, Any]] = Field(default=None, description="Geographic location context where applicable.")
    limitations: List[str] = Field(default_factory=list, description="Evidence-level caveats.")
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Complete lineage metadata preserved from Phase 5 and 6.")
    supporting_sources: List[Dict[str, Any]] = Field(default_factory=list, description="Corroborating source evidence traces.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Certainty score of the underlying observation.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Domain attributes and conflict indicators.")

    @field_validator("event_time")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        """Enforce timezone-aware UTC datetime."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @property
    def signal_id(self) -> str:
        """Convenience alias for normalized_signal_id."""
        return self.normalized_signal_id

    @property
    def observed_at(self) -> datetime:
        """Convenience alias for event_time."""
        return self.event_time

    @property
    def location_name(self) -> Optional[str]:
        """Convenience accessor for location name."""
        return self.location.get("location_name") if isinstance(self.location, dict) else None

    @property
    def latitude(self) -> Optional[float]:
        """Convenience accessor for latitude."""
        return self.location.get("latitude") if isinstance(self.location, dict) else None

    @property
    def longitude(self) -> Optional[float]:
        """Convenience accessor for longitude."""
        return self.location.get("longitude") if isinstance(self.location, dict) else None

    @property
    def domain(self) -> SignalDomain:
        """Convenience accessor for signal domain."""
        from app.normalization.contract import SignalDomain
        d = self.metadata.get("domain", "LOGISTICS")
        try:
            return SignalDomain(d)
        except Exception:
            return SignalDomain.LOGISTICS

    @classmethod
    def from_normalized_signal(
        cls,
        signal: Any,
        organization_id: Optional[str] = None,
        relevance: Optional[Union[EvidenceRelevance, float, str]] = None,
        factor_id: Optional[str] = None,
    ) -> RiskEvidence:
        """Construct a strongly typed RiskEvidence from a Phase 6 NormalizedRiskSignal.

        Strict Boundary: Rejects raw payloads or canonical events.
        """
        if not isinstance(signal, NormalizedRiskSignal):
            raise RiskEngineInputError(
                f"Expected NormalizedRiskSignal, got {type(signal).__name__}. "
                "Risk Engine boundary rejects unnormalized inputs."
            )

        org_id = organization_id or signal.organization_id or "global"
        if organization_id and signal.organization_id and organization_id != signal.organization_id:
            raise TenantMismatchError(
                f"Tenant isolation violated in evidence creation: requested '{organization_id}' "
                f"does not match signal organization '{signal.organization_id}'."
            )

        ev_id = generate_deterministic_evidence_id(org_id, signal.signal_id, signal.provider)

        resolved_relevance: Union[EvidenceRelevance, float, str] = (
            relevance if relevance is not None else derive_evidence_relevance(signal, is_primary=True)
        )

        provenance_data = {
            "canonical_event_id": signal.canonical_event_id,
            "raw_event_id": signal.raw_event_id,
            "provider_event_id": signal.provider_event_id,
            "source_reference": signal.source_reference,
            "correlation_id": signal.correlation_id,
            "trace_id": signal.trace_id,
            "ingestion_run_id": signal.ingestion_run_id,
            "fingerprint": signal.fingerprint,
            "supporting_sources_count": len(signal.supporting_sources),
        }

        corroborating = []
        for s in getattr(signal, "supporting_sources", []):
            if hasattr(s, "model_dump"):
                corroborating.append(s.model_dump())
            elif isinstance(s, dict):
                corroborating.append(s)

        meta = {
            "domain": signal.domain.value,
            "signal_type": signal.signal_type.value,
            "event_type": signal.event_type,
            "status": signal.status.value,
            "severity": signal.severity.value,
            "has_conflict": getattr(signal, "has_conflict", False),
            "quality": signal.quality.value,
            "quality_reasons": list(signal.quality_reasons),
        }
        if getattr(signal, "conflicts", None):
            meta["conflicts"] = signal.conflicts

        loc = None
        if any([
            signal.latitude is not None,
            signal.longitude is not None,
            signal.location_name,
            signal.country_code,
            signal.region,
        ]):
            loc = {
                "latitude": signal.latitude,
                "longitude": signal.longitude,
                "location_name": signal.location_name,
                "country_code": signal.country_code,
                "region": signal.region,
            }

        evidence_limitations: List[str] = []
        if signal.source_type == EventSourceType.SIMULATED:
            evidence_limitations.append("Source is SIMULATED: synthetic scenario.")
        elif signal.source_type == EventSourceType.ESTIMATED:
            evidence_limitations.append("Source is ESTIMATED: modeled or inferred observation.")
        if signal.quality == EventQuality.PARTIAL:
            reasons_str = ", ".join(signal.quality_reasons) if signal.quality_reasons else "incomplete data"
            evidence_limitations.append(f"Signal quality is PARTIAL: {reasons_str}.")
        if getattr(signal, "has_conflict", False):
            evidence_limitations.append("Signal subject to unresolved multi-source conflict.")

        return cls(
            evidence_id=ev_id,
            normalized_signal_id=signal.signal_id,
            organization_id=org_id,
            factor_id=factor_id,
            source=signal.source,
            provider=signal.provider,
            source_type=signal.source_type,
            event_time=signal.event_time,
            relevance=resolved_relevance,
            fingerprint=signal.fingerprint,
            quality=signal.quality,
            has_conflict=getattr(signal, "has_conflict", False),
            conflicts=list(getattr(signal, "conflicts", [])),
            location=loc,
            limitations=evidence_limitations,
            provenance=provenance_data,
            supporting_sources=corroborating,
            confidence=signal.confidence,
            metadata=meta,
        )
