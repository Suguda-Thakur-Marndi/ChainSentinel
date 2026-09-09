"""Evidence representation and provenance lineage tracking for RiskWise Risk Engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.canonical import EventSourceType
from app.normalization.contract import NormalizedRiskSignal
from app.risk_engine.errors import RiskEngineInputError


def generate_deterministic_evidence_id(
    organization_id: Optional[str],
    signal_id: str,
    provider: Optional[str] = None,
) -> str:
    """Generate a reproducible UUIDv5 evidence identifier based on tenant, signal ID, and optional provider."""
    org = organization_id or "global"
    prov = f":{provider}" if provider else ""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{org}:evidence:{signal_id}{prov}"))


class RiskEvidence(BaseModel):
    """Traceable evidence unit linking a RiskFactor back to its NormalizedRiskSignal lineage."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    evidence_id: str = Field(..., min_length=1, description="Deterministic unique evidence identifier.")
    normalized_signal_id: str = Field(..., min_length=1, description="Lineage link to NormalizedRiskSignal.signal_id.")
    source: str = Field(..., min_length=1, description="Primary external source name.")
    provider: str = Field(..., min_length=1, description="Ingestion provider name.")
    source_type: EventSourceType = Field(default=EventSourceType.REAL, description="Nature of observation (REAL, ESTIMATED, SIMULATED).")
    event_time: datetime = Field(..., description="Timestamp when the real-world condition occurred.")
    relevance: float = Field(default=1.0, ge=0.0, le=1.0, description="Semantic relevance weight of this evidence to the factor.")
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

    @classmethod
    def from_normalized_signal(
        cls,
        signal: Any,
        organization_id: Optional[str] = None,
        relevance: float = 1.0,
    ) -> RiskEvidence:
        """Construct a strongly typed RiskEvidence from a Phase 6 NormalizedRiskSignal.

        Strict Boundary: Rejects raw payloads or canonical events.
        """
        if not isinstance(signal, NormalizedRiskSignal):
            raise RiskEngineInputError(
                f"Expected NormalizedRiskSignal, got {type(signal).__name__}. "
                "Risk Engine boundary rejects unnormalized inputs."
            )

        org_id = organization_id or signal.organization_id
        ev_id = generate_deterministic_evidence_id(org_id, signal.signal_id, signal.provider)

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

        return cls(
            evidence_id=ev_id,
            normalized_signal_id=signal.signal_id,
            source=signal.source,
            provider=signal.provider,
            source_type=signal.source_type,
            event_time=signal.event_time,
            relevance=relevance,
            provenance=provenance_data,
            supporting_sources=corroborating,
            confidence=signal.confidence,
            metadata=meta,
        )
