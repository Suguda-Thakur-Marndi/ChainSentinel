"""Normalized risk signal contract and internal data models for Phase 6.

Establishes the strongly typed, domain-neutral representation of risk signals
derived from Phase 5 CanonicalExternalEvent objects.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.canonical import (
    CanonicalEventType,
    CanonicalExternalEvent,
    EventQuality,
    EventSeverity,
    EventSourceType,
)


def _generate_signal_id() -> str:
    return str(uuid.uuid4())


class SignalDomain(str, Enum):
    """Top-level domain classification for normalized risk signals."""

    WEATHER = "WEATHER"
    ROAD = "ROAD"
    OCEAN = "OCEAN"
    AIR = "AIR"
    RAIL = "RAIL"
    LOGISTICS = "LOGISTICS"
    INTELLIGENCE = "INTELLIGENCE"
    GENERAL = "GENERAL"


class SignalType(str, Enum):
    """Functional classification of the risk signal nature."""

    DELAY = "DELAY"
    DISRUPTION = "DISRUPTION"
    CONGESTION = "CONGESTION"
    HAZARD = "HAZARD"
    STATUS_UPDATE = "STATUS_UPDATE"
    ANOMALY = "ANOMALY"
    INCIDENT = "INCIDENT"
    CUSTOM = "CUSTOM"


class SignalStatus(str, Enum):
    """Normalized operational status of the condition or entity."""

    NORMAL = "NORMAL"
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    DISRUPTED = "DISRUPTED"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"
    RESOLVED = "RESOLVED"
    COMPLETED = "COMPLETED"
    UNKNOWN = "UNKNOWN"


class CorrelationStatus(str, Enum):
    """Resolution status of entity references within the signal."""

    NONE = "NONE"
    PARTIAL = "PARTIAL"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


class EntityType(str, Enum):
    """Supported supply chain network and asset entity types."""

    SHIPMENT = "SHIPMENT"
    SUPPLIER = "SUPPLIER"
    SUPPLIER_SITE = "SUPPLIER_SITE"
    FACTORY = "FACTORY"
    WAREHOUSE = "WAREHOUSE"
    PORT = "PORT"
    ROUTE = "ROUTE"
    CARRIER = "CARRIER"
    VESSEL = "VESSEL"
    AIRCRAFT = "AIRCRAFT"
    VEHICLE = "VEHICLE"
    TRACKING_OBJECT = "TRACKING_OBJECT"


class CorrelationConfidence(str, Enum):
    """Evidence confidence level establishing the entity correlation."""

    EXACT = "EXACT"          # Direct match on primary internal ID or verified unambiguous mapping
    VERIFIED = "VERIFIED"    # Verified provider mapping or registered master tracking lookup
    STRONG = "STRONG"        # Strong unambiguous external identifier (e.g. valid IMO, unique ICAO24)
    WEAK = "WEAK"            # Partial or secondary indicator (e.g. callsign without ICAO24)
    UNRESOLVED = "UNRESOLVED"  # External reference present but unverified against internal entities


class CorrelationMethod(str, Enum):
    """Methodology used to resolve the entity association."""

    INTERNAL_ID = "INTERNAL_ID"
    VERIFIED_MAPPING = "VERIFIED_MAPPING"
    PROVIDER_REFERENCE = "PROVIDER_REFERENCE"
    EXACT_IDENTIFIER = "EXACT_IDENTIFIER"
    NAMESPACE_IDENTIFIER = "NAMESPACE_IDENTIFIER"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"
    UNRESOLVED = "UNRESOLVED"


class EntityReference(BaseModel):
    """Strongly typed, namespace-aware entity association record."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    entity_type: EntityType
    internal_id: Optional[str] = None
    external_id: Optional[str] = None
    identifier_namespace: Optional[str] = None
    identifier_type: Optional[str] = None
    correlation_confidence: CorrelationConfidence = CorrelationConfidence.UNRESOLVED
    correlation_method: CorrelationMethod = CorrelationMethod.UNRESOLVED
    evidence: Optional[Dict[str, Any]] = None
    raw_identifier: Optional[str] = None
    is_conflict: bool = False
    conflict_details: Optional[str] = None


class SignalEntityReferences(BaseModel):
    """Normalized internal supply-chain entity references."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    shipment_id: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_site_id: Optional[str] = None
    factory_id: Optional[str] = None
    warehouse_id: Optional[str] = None
    port_id: Optional[str] = None
    route_id: Optional[str] = None
    carrier_id: Optional[str] = None

    # Transit asset identifiers (for future asset graph resolution)
    vehicle_id: Optional[str] = None
    vessel_mmsi: Optional[str] = None
    aircraft_icao24: Optional[str] = None
    flight_number: Optional[str] = None
    trip_id: Optional[str] = None

    # Unresolved external identifiers preserved for graph matching
    unresolved_identifiers: Dict[str, str] = Field(default_factory=dict)

    correlation_status: CorrelationStatus = CorrelationStatus.NONE

    # Detailed typed entity references and conflict tracking (Phase 6 Step 3)
    references: List[EntityReference] = Field(default_factory=list)
    has_conflict: bool = False
    conflict_reason: Optional[str] = None

    @property
    def has_any_entity(self) -> bool:
        """Return True if at least one primary domain entity ID is populated."""
        return any([
            self.shipment_id,
            self.supplier_id,
            self.supplier_site_id,
            self.factory_id,
            self.warehouse_id,
            self.port_id,
            self.route_id,
            self.carrier_id,
        ])

    def add_reference(self, ref: EntityReference) -> None:
        """Add an entity reference and mirror primary internal ID if applicable."""
        self.references.append(ref)
        if ref.is_conflict:
            self.has_conflict = True
            self.conflict_reason = ref.conflict_details or "Conflicting entity identifier detected"
            self.correlation_status = CorrelationStatus.AMBIGUOUS

        # Mirror internal_id into convenience field if verified/exact and not conflicting
        if ref.internal_id and not ref.is_conflict:
            if ref.entity_type == EntityType.SHIPMENT and not self.shipment_id:
                self.shipment_id = ref.internal_id
            elif ref.entity_type == EntityType.SUPPLIER and not self.supplier_id:
                self.supplier_id = ref.internal_id
            elif ref.entity_type == EntityType.SUPPLIER_SITE and not self.supplier_site_id:
                self.supplier_site_id = ref.internal_id
            elif ref.entity_type == EntityType.FACTORY and not self.factory_id:
                self.factory_id = ref.internal_id
            elif ref.entity_type == EntityType.WAREHOUSE and not self.warehouse_id:
                self.warehouse_id = ref.internal_id
            elif ref.entity_type == EntityType.PORT and not self.port_id:
                self.port_id = ref.internal_id
            elif ref.entity_type == EntityType.ROUTE and not self.route_id:
                self.route_id = ref.internal_id
            elif ref.entity_type == EntityType.CARRIER and not self.carrier_id:
                self.carrier_id = ref.internal_id

    def get_references_by_type(self, entity_type: EntityType) -> List[EntityReference]:
        """Retrieve all entity references matching a specific entity type."""
        return [r for r in self.references if r.entity_type == entity_type]

    def get_primary_reference(self) -> Optional[EntityReference]:
        """Retrieve the highest confidence entity reference."""
        if not self.references:
            return None
        order = {
            CorrelationConfidence.EXACT: 5,
            CorrelationConfidence.VERIFIED: 4,
            CorrelationConfidence.STRONG: 3,
            CorrelationConfidence.WEAK: 2,
            CorrelationConfidence.UNRESOLVED: 1,
        }
        return max(self.references, key=lambda r: order.get(r.correlation_confidence, 0))



class CorroboratingEvidence(BaseModel):
    """Reference to an external source or canonical event supporting this signal."""

    model_config = ConfigDict(extra="allow")

    source: str
    provider: str
    canonical_event_id: Optional[str] = None
    provider_event_id: Optional[str] = None
    source_reference: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    observed_at: Optional[datetime] = None
    summary: Optional[str] = None

    @field_validator("observed_at")
    @classmethod
    def ensure_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class OperationalValues(BaseModel):
    """Normalized measurement and telemetry indicators with deterministic units."""

    model_config = ConfigDict(extra="allow")

    delay_minutes: Optional[float] = None
    eta: Optional[datetime] = None
    distance_km: Optional[float] = Field(None, ge=0.0)
    speed_kmh: Optional[float] = Field(None, ge=0.0)
    temperature_celsius: Optional[float] = None
    weight_kg: Optional[float] = Field(None, ge=0.0)
    volume_m3: Optional[float] = Field(None, ge=0.0)
    monetary_amount: Optional[float] = Field(None, ge=0.0)
    currency_code: Optional[str] = Field(None, max_length=3)
    disruption_level: Optional[float] = Field(None, ge=0.0, le=1.0)
    operational_status: Optional[str] = None

    @field_validator("eta")
    @classmethod
    def ensure_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class NormalizedRiskSignal(BaseModel):
    """Provider-independent internal normalized risk signal contract.

    This represents the output of Phase 6 semantic normalization, downstream
    from Phase 5 CanonicalExternalEvent and upstream of future Risk Evaluation.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # 1. Identity & Tenancy
    signal_id: str = Field(default_factory=_generate_signal_id)
    organization_id: Optional[str] = None

    # 2. Classification
    domain: SignalDomain = SignalDomain.GENERAL
    signal_type: SignalType = SignalType.STATUS_UPDATE
    event_type: str = Field(..., min_length=1)
    status: SignalStatus = SignalStatus.ACTIVE
    severity: EventSeverity = EventSeverity.INFO
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    quality: EventQuality = EventQuality.VALID

    # 3. Temporal Semantics (All timezone-aware UTC)
    event_time: datetime = Field(..., description="Timestamp when the underlying real-world event occurred.")
    observed_at: Optional[datetime] = Field(None, description="Timestamp when the external source observed the condition.")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when RiskWise received the canonical event.",
    )
    effective_from: Optional[datetime] = Field(None, description="Start of validity interval.")
    effective_to: Optional[datetime] = Field(None, description="End of validity interval.")

    # 4. Location Context
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    location_name: Optional[str] = None
    country_code: Optional[str] = Field(None, max_length=3)
    region: Optional[str] = None
    precision_meters: Optional[float] = Field(None, ge=0.0)

    # 5. Entity Correlation
    entities: SignalEntityReferences = Field(default_factory=SignalEntityReferences)

    # 6. Provenance & Lineage
    source: str = Field(..., min_length=1)
    source_type: EventSourceType = EventSourceType.REAL
    provider: str = Field(..., min_length=1)
    canonical_event_id: str = Field(..., min_length=1)
    raw_event_id: Optional[str] = None
    provider_event_id: Optional[str] = None
    source_reference: Optional[str] = None
    supporting_sources: List[CorroboratingEvidence] = Field(default_factory=list)

    # Distributed Tracing
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None

    # 7. Operational Measurements (Normalized Units)
    measurements: OperationalValues = Field(default_factory=OperationalValues)

    # 8. Attributes & Semantic Fingerprinting
    normalized_attributes: Dict[str, Any] = Field(default_factory=dict)
    canonical_attributes: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: Optional[str] = None

    @field_validator("event_time", "observed_at", "received_at", "effective_from", "effective_to")
    @classmethod
    def ensure_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Ensure all timestamps are timezone-aware UTC."""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def compute_fingerprint_if_missing(self) -> NormalizedRiskSignal:
        """Compute deterministic semantic fingerprint if not explicitly provided."""
        if not self.fingerprint:
            self.fingerprint = self.generate_fingerprint()
        return self

    def generate_fingerprint(self) -> str:
        """Generate a deterministic SHA-256 semantic fingerprint."""
        lat_bucket = f"{self.latitude:.2f}" if self.latitude is not None else "none"
        lon_bucket = f"{self.longitude:.2f}" if self.longitude is not None else "none"
        time_bucket = self.event_time.strftime("%Y-%m-%d-%H") if self.event_time else "none"
        primary_entity = (
            self.entities.shipment_id
            or self.entities.supplier_id
            or self.entities.port_id
            or self.entities.route_id
            or self.entities.vessel_mmsi
            or self.entities.aircraft_icao24
            or self.entities.trip_id
            or "none"
        )
        token_str = (
            f"{self.domain.value}|{self.signal_type.value}|{self.event_type}|"
            f"{lat_bucket}|{lon_bucket}|{time_bucket}|{primary_entity}"
        )
        return hashlib.sha256(token_str.encode("utf-8")).hexdigest()

    def add_corroborating_evidence(self, evidence: CorroboratingEvidence) -> None:
        """Add supporting evidence from another source without losing provenance."""
        # Avoid duplicate evidence from identical source & canonical event
        for existing in self.supporting_sources:
            if (
                existing.source == evidence.source
                and existing.canonical_event_id == evidence.canonical_event_id
                and existing.provider_event_id == evidence.provider_event_id
            ):
                return
        self.supporting_sources.append(evidence)
