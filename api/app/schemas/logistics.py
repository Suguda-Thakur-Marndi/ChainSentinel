"""Pydantic schemas for logistics, tracking, telemetry, and inventory management."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    EXCEPTION = "EXCEPTION"


class DataProvenance(str, Enum):
    REAL = "REAL"
    SYNTHETIC = "SYNTHETIC"
    ESTIMATED = "ESTIMATED"


class InventoryMovementType(str, Enum):
    RECEIPT = "RECEIPT"
    SHIPMENT = "SHIPMENT"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER = "TRANSFER"


# Shipment
class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracking_number: str = Field(..., min_length=1, max_length=100)
    route_id: Optional[str] = Field(None, max_length=64)
    product_id: Optional[str] = Field(None, max_length=64)
    carrier_id: Optional[str] = Field(None, max_length=64)
    origin: Optional[str] = Field(None, max_length=255)
    destination: Optional[str] = Field(None, max_length=255)
    status: ShipmentStatus = ShipmentStatus.IN_TRANSIT
    mode: str = Field(default="OCEAN", max_length=50)
    current_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    current_lng: Optional[float] = Field(None, ge=-180.0, le=180.0)
    eta: Optional[datetime] = None
    eta_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    delay_minutes: Optional[float] = None
    data_provenance: DataProvenance = DataProvenance.REAL
    risk_id: Optional[str] = Field(None, max_length=64)


class ShipmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: Optional[str] = Field(None, max_length=64)
    carrier_id: Optional[str] = Field(None, max_length=64)
    origin: Optional[str] = Field(None, max_length=255)
    destination: Optional[str] = Field(None, max_length=255)
    status: Optional[ShipmentStatus] = None
    mode: Optional[str] = Field(None, max_length=50)
    current_lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    current_lng: Optional[float] = Field(None, ge=-180.0, le=180.0)
    eta: Optional[datetime] = None
    eta_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    delay_minutes: Optional[float] = None
    risk_id: Optional[str] = Field(None, max_length=64)


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    tracking_number: str
    route_id: Optional[str] = None
    product_id: Optional[str] = None
    carrier_id: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    status: str
    mode: str
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    eta: Optional[datetime] = None
    eta_confidence: Optional[float] = None
    delay_minutes: Optional[float] = None
    data_provenance: str
    risk_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class ShipmentListResponse(PaginatedResponse[ShipmentResponse]):
    pass


# ShipmentEvent (Append-only Telemetry)
class ShipmentEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: str = Field(..., max_length=64)
    mode: Optional[str] = Field(None, max_length=50)
    event_type: Optional[str] = Field(None, max_length=100)
    timestamp: Optional[datetime] = None
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    status: Optional[str] = Field(None, max_length=50)
    eta: Optional[datetime] = None
    delay_minutes: Optional[float] = None
    source: str = Field(default="REAL", max_length=50)
    source_type: Optional[str] = Field(None, max_length=50)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    raw_event_id: Optional[str] = Field(None, max_length=100)
    metadata_json: Optional[dict[str, Any]] = None


class ShipmentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_id: str
    mode: Optional[str] = None
    event_type: Optional[str] = None
    timestamp: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: Optional[str] = None
    eta: Optional[datetime] = None
    delay_minutes: Optional[float] = None
    source: str
    source_type: Optional[str] = None
    confidence: Optional[float] = None
    raw_event_id: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime


class ShipmentEventListResponse(PaginatedResponse[ShipmentEventResponse]):
    pass


# Inventory
class InventoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., max_length=64)
    facility_id: Optional[str] = Field(None, max_length=64)
    quantity_on_hand: float = Field(..., ge=0.0)
    safety_stock: Optional[float] = Field(None, ge=0.0)
    reorder_point: Optional[float] = Field(None, ge=0.0)
    days_of_supply: Optional[float] = Field(None, ge=0.0)


class InventoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity_on_hand: Optional[float] = Field(None, ge=0.0)
    safety_stock: Optional[float] = Field(None, ge=0.0)
    reorder_point: Optional[float] = Field(None, ge=0.0)
    days_of_supply: Optional[float] = Field(None, ge=0.0)


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    product_id: str
    facility_id: Optional[str] = None
    quantity_on_hand: float
    safety_stock: Optional[float] = None
    reorder_point: Optional[float] = None
    days_of_supply: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class InventoryListResponse(PaginatedResponse[InventoryResponse]):
    pass


# InventoryMovement (Append-only Ledger)
class InventoryMovementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(..., max_length=64)
    movement_type: Optional[InventoryMovementType] = None
    quantity: float = Field(...)
    from_location: Optional[str] = Field(None, max_length=255)
    to_location: Optional[str] = Field(None, max_length=255)
    reference_id: Optional[str] = Field(None, max_length=100)


class InventoryMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    product_id: str
    movement_type: Optional[str] = None
    quantity: float
    from_location: Optional[str] = None
    to_location: Optional[str] = None
    timestamp: datetime
    reference_id: Optional[str] = None


class InventoryMovementListResponse(PaginatedResponse[InventoryMovementResponse]):
    pass
