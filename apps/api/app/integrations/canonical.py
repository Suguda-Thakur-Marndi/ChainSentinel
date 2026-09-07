"""Canonical external event models and provider-independent taxonomy.

Establishes the strongly typed, normalized data contract that unifies
weather, road traffic, ocean AIS, air, rail, logistics, and intelligence
signals across external providers without coupling downstream engines
to provider-specific schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _generate_canonical_id() -> str:
    return str(uuid.uuid4())


class CanonicalEventType(str, Enum):
    """Provider-independent classification taxonomy for external supply-chain signals."""

    # Transport / Milestone
    SHIPMENT_STATUS = "SHIPMENT_STATUS"
    SHIPMENT_DELAY = "SHIPMENT_DELAY"
    ETA_CHANGE = "ETA_CHANGE"
    LOCATION_UPDATE = "LOCATION_UPDATE"

    # Maritime / Port
    PORT_CONGESTION = "PORT_CONGESTION"
    PORT_CLOSURE = "PORT_CLOSURE"
    PORT_DELAY = "PORT_DELAY"

    # Road / Traffic
    ROAD_INCIDENT = "ROAD_INCIDENT"
    ROAD_CLOSURE = "ROAD_CLOSURE"
    TRAFFIC_CONGESTION = "TRAFFIC_CONGESTION"

    # Weather / Climate
    WEATHER_ALERT = "WEATHER_ALERT"
    STORM = "STORM"
    FLOOD = "FLOOD"
    CYCLONE = "CYCLONE"
    EXTREME_WEATHER = "EXTREME_WEATHER"

    # Ocean / AIS
    VESSEL_LOCATION = "VESSEL_LOCATION"
    VESSEL_DELAY = "VESSEL_DELAY"
    MARITIME_INCIDENT = "MARITIME_INCIDENT"

    # Air Freight
    FLIGHT_DELAY = "FLIGHT_DELAY"
    FLIGHT_CANCELLATION = "FLIGHT_CANCELLATION"
    AIRPORT_DISRUPTION = "AIRPORT_DISRUPTION"

    # Rail
    TRAIN_DELAY = "TRAIN_DELAY"
    RAIL_DISRUPTION = "RAIL_DISRUPTION"

    # Logistics / Parcel
    PARCEL_STATUS = "PARCEL_STATUS"
    DELIVERY_DELAY = "DELIVERY_DELAY"

    # External Intelligence
    NEWS_EVENT = "NEWS_EVENT"
    GEOPOLITICAL_EVENT = "GEOPOLITICAL_EVENT"

    # Extensible Fallback
    CUSTOM = "CUSTOM"


class EventSourceType(str, Enum):
    """Origin nature of external signals distinguishing observation from inference."""

    REAL = "REAL"
    SIMULATED = "SIMULATED"
    ESTIMATED = "ESTIMATED"


class EventSeverity(str, Enum):
    """Operational severity of an external event (distinguished from composite risk score)."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventQuality(str, Enum):
    """Data completeness and validation state of a canonical event."""

    VALID = "VALID"          # Identity, timestamp, and core attributes fully populated
    PARTIAL = "PARTIAL"      # Usable event, but optional coordinates or correlation unresolved
    INVALID = "INVALID"      # Critical structural defects (e.g. malformed timestamp or invalid coords)


class EventLocation(BaseModel):
    """Geographic position and spatial context of an event."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    location_name: Optional[str] = None
    country_code: Optional[str] = Field(None, max_length=3)
    region: Optional[str] = None
    precision_meters: Optional[float] = Field(None, ge=0.0)

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < -90.0 or v > 90.0):
            raise ValueError(f"Latitude must be between -90.0 and 90.0, got {v}")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < -180.0 or v > 180.0):
            raise ValueError(f"Longitude must be between -180.0 and 180.0, got {v}")
        return v


class EntityCorrelation(BaseModel):
    """Association between an external signal and internal RiskWise graph entities."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    shipment_id: Optional[str] = None
    carrier_id: Optional[str] = None
    port_id: Optional[str] = None
    route_id: Optional[str] = None
    supplier_id: Optional[str] = None
    facility_id: Optional[str] = None
    custom_identifiers: Dict[str, str] = Field(default_factory=dict)

    @property
    def is_correlated(self) -> bool:
        """Return True if at least one internal entity identifier is bound."""
        return any([
            self.shipment_id,
            self.carrier_id,
            self.port_id,
            self.route_id,
            self.supplier_id,
            self.facility_id,
            bool(self.custom_identifiers),
        ])


class CanonicalExternalEvent(BaseModel):
    """Provider-agnostic canonical representation of an external supply-chain signal."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # 1. Identity
    event_id: str = Field(default_factory=_generate_canonical_id)
    provider: str = Field(..., min_length=1, max_length=100)
    source_event_id: Optional[str] = None
    event_type: Union[CanonicalEventType, str] = CanonicalEventType.CUSTOM

    # 2. Timing (All stored in timezone-aware UTC)
    event_timestamp: datetime
    observed_at: Optional[datetime] = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # 3. Location
    location: Optional[EventLocation] = None

    # 4. Entity Correlation
    correlation: EntityCorrelation = Field(default_factory=EntityCorrelation)

    # 5. Operational Impact & Telemetry
    status: Optional[str] = None
    severity: EventSeverity = EventSeverity.INFO
    delay_minutes: Optional[float] = None
    eta: Optional[datetime] = None

    # 6. Source Semantics & Confidence
    source_type: EventSourceType = EventSourceType.REAL
    source_url: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    raw_event_id: Optional[str] = None

    # 7. Payload
    normalized_attributes: Dict[str, Any] = Field(default_factory=dict)
    provider_metadata: Dict[str, Any] = Field(default_factory=dict)

    # 8. Traceability & Multi-Tenancy
    ingestion_run_id: Optional[str] = None
    correlation_id: Optional[str] = None
    payload_fingerprint: Optional[str] = None
    org_id: Optional[str] = None

    # 9. Quality Assessment
    quality: EventQuality = EventQuality.VALID
    validation_errors: List[str] = Field(default_factory=list)

    @field_validator("event_timestamp", "observed_at", "received_at", "eta")
    @classmethod
    def ensure_utc(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Ensure all timestamps are normalized to timezone-aware UTC."""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="before")
    @classmethod
    def handle_aliases_and_flattened_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Alias provider_name -> provider
            if "provider_name" in data and "provider" not in data:
                data["provider"] = data.pop("provider_name")

            # Extract flattened lat/lon into EventLocation if location object is not explicitly provided
            if "location" not in data or data["location"] is None:
                lat = data.pop("latitude", None)
                lon = data.pop("longitude", None)
                loc_name = data.pop("location_name", None)
                country = data.pop("country_code", None)
                if lat is not None or lon is not None or loc_name is not None or country is not None:
                    data["location"] = {
                        "latitude": lat,
                        "longitude": lon,
                        "location_name": loc_name,
                        "country_code": country,
                    }

            # Extract flattened correlation keys into EntityCorrelation if correlation is not explicitly given
            if "correlation" not in data or data["correlation"] is None:
                corr_data = {}
                for key in ["shipment_id", "carrier_id", "port_id", "route_id", "supplier_id", "facility_id"]:
                    if key in data:
                        corr_data[key] = data.pop(key)
                if corr_data:
                    data["correlation"] = corr_data

        return data

    @property
    def latitude(self) -> Optional[float]:
        return self.location.latitude if self.location else None

    @property
    def longitude(self) -> Optional[float]:
        return self.location.longitude if self.location else None

    @property
    def location_name(self) -> Optional[str]:
        return self.location.location_name if self.location else None

    @property
    def shipment_id(self) -> Optional[str]:
        return self.correlation.shipment_id

    @property
    def is_correlated(self) -> bool:
        return self.correlation.is_correlated
