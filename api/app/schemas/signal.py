"""Pydantic schemas for Normalized Risk Signals (Phase 6 / Ingestion / Telemetry)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


class SignalResponse(BaseModel):
    """Normalized telemetry risk signal item."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    signal_id: str
    org_id: Optional[str] = None
    domain: str = "GENERAL"
    signal_type: str = "STATUS_UPDATE"
    status: str = "ACTIVE"
    severity: str = "LOW"
    confidence: float = 1.0
    source: str
    provider: str
    canonical_event_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    title: str
    summary: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    delay_minutes: Optional[float] = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime
    created_at: datetime


class SignalCreate(BaseModel):
    """Schema for creating or ingesting a normalized risk signal."""
    signal_id: Optional[str] = None
    domain: str = "GENERAL"
    signal_type: str = "STATUS_UPDATE"
    status: str = "ACTIVE"
    severity: str = "LOW"
    confidence: float = 1.0
    source: str
    provider: str
    canonical_event_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    title: str
    summary: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    delay_minutes: Optional[float] = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    detected_at: Optional[datetime] = None


class SignalListResponse(PaginatedResponse[SignalResponse]):
    """Paginated collection of normalized signals."""
    pass

