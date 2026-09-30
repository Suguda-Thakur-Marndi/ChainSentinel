"""Normalized live geospatial data models for RiskWise 2.0 / ChainSentinel.

Adheres strictly to the single canonical LiveMapObject representation:
- Explicit coordinates with WGS84 validation (-90 <= lat <= 90, -180 <= lon <= 180).
- Transparent provenance metadata (source, source_timestamp, last_seen).
- Zero fake/synthetic coordinates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MapObjectType(str, Enum):
    VESSEL = "vessel"
    AIRCRAFT = "aircraft"
    TRUCK = "truck"
    TRAIN = "train"
    SHIPMENT = "shipment"
    PORT = "port"
    AIRPORT = "airport"
    WAREHOUSE = "warehouse"
    FACTORY = "factory"
    SUPPLIER = "supplier"
    ROUTE = "route"
    INCIDENT = "incident"
    RISK = "risk"
    WEATHER = "weather"
    TRANSIT = "transit"


class ProviderHealthStatus(str, Enum):
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    UNCONFIGURED = "unconfigured"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class ProviderHealth(BaseModel):
    """Runtime telemetry provider health representation."""
    model_config = ConfigDict(extra="ignore")

    name: str
    purpose: str = "telemetry"
    status: ProviderHealthStatus = ProviderHealthStatus.UNCONFIGURED
    last_success: Optional[str] = None
    last_error: Optional[str] = None
    latency_ms: Optional[float] = None
    objects: int = 0
    reason: Optional[str] = None


class LiveMapObject(BaseModel):
    """Canonical normalized geospatial object representation for the RiskWise live map.

    Strict validation:
    - -90.0 <= latitude <= 90.0
    - -180.0 <= longitude <= 180.0
    - Rejects (0.0, 0.0) unless explicitly flagged in metadata.
    """
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Unique deterministic identifier for the map entity")
    type: str = Field(..., description="Entity category: vessel, aircraft, shipment, weather, incident, etc.")
    source: str = Field(..., description="Telemetry source: aisstream, opensky, project44, openweather, etc.")
    latitude: float = Field(..., description="WGS84 latitude (-90.0 to 90.0)")
    longitude: float = Field(..., description="WGS84 longitude (-180.0 to 180.0)")
    heading: Optional[float] = Field(None, description="Heading in degrees (0-360) or null if unknown")
    speed: Optional[float] = Field(None, description="Speed over ground in knots or km/h, or null if unknown")
    status: Optional[str] = Field(None, description="Operational state or null")
    name: str = Field(..., description="Human-readable label or entity name")
    identifier: Optional[str] = Field(None, description="Domain identifier (e.g. MMSI, ICAO24, tracking number)")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp of original telemetry observation")
    last_seen: str = Field(..., description="ISO-8601 UTC timestamp of latest receipt by RiskWise platform")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Source-specific telemetry attributes")

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if v is None or not (-90.0 <= v <= 90.0):
            raise ValueError(f"Latitude {v} out of WGS84 range [-90.0, 90.0]")
        return round(float(v), 6)

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if v is None or not (-180.0 <= v <= 180.0):
            raise ValueError(f"Longitude {v} out of WGS84 range [-180.0, 180.0]")
        return round(float(v), 6)

    @model_validator(mode="after")
    def validate_non_zero_island(self) -> "LiveMapObject":
        # Disallow exact (0.0, 0.0) null island unless explicitly marked as legitimate in metadata
        if abs(self.latitude) < 1e-6 and abs(self.longitude) < 1e-6:
            if not self.metadata.get("allow_null_island", False):
                raise ValueError("Coordinates (0,0) rejected as ungrounded placeholder/null island")
        return self


class LiveMapResponse(BaseModel):
    """Response payload for GET /api/v1/map/objects."""
    items: List[LiveMapObject] = Field(default_factory=list)
    sources: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    total_count: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProvidersHealthResponse(BaseModel):
    """Response payload for GET /api/v1/map/providers/health."""
    providers: List[ProviderHealth] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
