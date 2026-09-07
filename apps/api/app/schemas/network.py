"""Pydantic schemas for supply chain network resources (Suppliers, Sites, Facilities, Ports, Carriers, Products, Routes)."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class CriticalityTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FacilityStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DISRUPTED = "DISRUPTED"
    OFFLINE = "OFFLINE"
    MAINTENANCE = "MAINTENANCE"


class PortType(str, Enum):
    SEA = "SEA"
    AIR = "AIR"
    INLAND = "INLAND"


class TransportMode(str, Enum):
    OCEAN = "OCEAN"
    AIR = "AIR"
    ROAD = "ROAD"
    RAIL = "RAIL"


# Supplier
class SupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    tier: Optional[CriticalityTier] = CriticalityTier.MEDIUM
    criticality: Optional[CriticalityTier] = CriticalityTier.MEDIUM
    reliability_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    financial_exposure: Optional[float] = Field(None, ge=0.0)
    lead_time_days: Optional[float] = Field(None, ge=0.0)
    current_risk_id: Optional[str] = Field(None, max_length=64)
    metadata_json: Optional[dict[str, Any]] = None


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    tier: Optional[CriticalityTier] = None
    criticality: Optional[CriticalityTier] = None
    reliability_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    financial_exposure: Optional[float] = Field(None, ge=0.0)
    lead_time_days: Optional[float] = Field(None, ge=0.0)
    current_risk_id: Optional[str] = Field(None, max_length=64)
    metadata_json: Optional[dict[str, Any]] = None


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    name: str
    code: Optional[str] = None
    country: Optional[str] = None
    tier: Optional[str] = None
    criticality: Optional[str] = None
    reliability_score: Optional[float] = None
    financial_exposure: Optional[float] = None
    lead_time_days: Optional[float] = None
    current_risk_id: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class SupplierListResponse(PaginatedResponse[SupplierResponse]):
    pass


# SupplierSite
class SupplierSiteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    site_type: Optional[str] = Field(None, max_length=100)
    capacity: Optional[float] = Field(None, ge=0.0)
    status: FacilityStatus = FacilityStatus.OPERATIONAL


class SupplierSiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    site_type: Optional[str] = Field(None, max_length=100)
    capacity: Optional[float] = Field(None, ge=0.0)
    status: Optional[FacilityStatus] = None


class SupplierSiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    supplier_id: str
    name: str
    country: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    site_type: Optional[str] = None
    capacity: Optional[float] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class SupplierSiteListResponse(PaginatedResponse[SupplierSiteResponse]):
    pass


# Factory
class FactoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    capacity: Optional[float] = Field(None, ge=0.0)
    utilization: Optional[float] = Field(None, ge=0.0, le=100.0)
    status: FacilityStatus = FacilityStatus.OPERATIONAL


class FactoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    capacity: Optional[float] = Field(None, ge=0.0)
    utilization: Optional[float] = Field(None, ge=0.0, le=100.0)
    status: Optional[FacilityStatus] = None


class FactoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    name: str
    code: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    capacity: Optional[float] = None
    utilization: Optional[float] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class FactoryListResponse(PaginatedResponse[FactoryResponse]):
    pass


# Warehouse
class WarehouseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    total_capacity: Optional[float] = Field(None, ge=0.0)
    current_occupancy: Optional[float] = Field(None, ge=0.0)
    status: FacilityStatus = FacilityStatus.OPERATIONAL


class WarehouseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    city: Optional[str] = Field(None, max_length=100)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    total_capacity: Optional[float] = Field(None, ge=0.0)
    current_occupancy: Optional[float] = Field(None, ge=0.0)
    status: Optional[FacilityStatus] = None


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    name: str
    code: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    total_capacity: Optional[float] = None
    current_occupancy: Optional[float] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class WarehouseListResponse(PaginatedResponse[WarehouseResponse]):
    pass


# Port (Global Reference Entity)
class PortResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: Optional[str] = None
    name: str
    country: Optional[str] = None
    port_type: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    congestion_score: Optional[float] = None
    average_wait_hours: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class PortListResponse(PaginatedResponse[PortResponse]):
    pass


# Carrier
class CarrierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    mode: Optional[TransportMode] = None
    on_time_reliability: Optional[float] = Field(None, ge=0.0, le=100.0)
    contact_info_json: Optional[dict[str, Any]] = None


class CarrierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    mode: Optional[TransportMode] = None
    on_time_reliability: Optional[float] = Field(None, ge=0.0, le=100.0)
    contact_info_json: Optional[dict[str, Any]] = None


class CarrierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    name: str
    code: Optional[str] = None
    mode: Optional[str] = None
    on_time_reliability: Optional[float] = None
    contact_info_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class CarrierListResponse(PaginatedResponse[CarrierResponse]):
    pass


# Product
class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    unit_cost: Optional[float] = Field(None, ge=0.0)
    currency: str = Field(default="USD", max_length=10)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    unit_cost: Optional[float] = Field(None, ge=0.0)
    currency: Optional[str] = Field(None, max_length=10)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    sku: str
    name: str
    category: Optional[str] = None
    unit_cost: Optional[float] = None
    currency: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProductListResponse(PaginatedResponse[ProductResponse]):
    pass


# Route
class RouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    origin_facility_id: Optional[str] = Field(None, max_length=64)
    destination_facility_id: Optional[str] = Field(None, max_length=64)
    mode: TransportMode = TransportMode.OCEAN
    distance_km: Optional[float] = Field(None, ge=0.0)
    standard_lead_time_days: Optional[float] = Field(None, ge=0.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    waypoints_json: Optional[dict[str, Any]] = None


class RouteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    origin_facility_id: Optional[str] = Field(None, max_length=64)
    destination_facility_id: Optional[str] = Field(None, max_length=64)
    mode: Optional[TransportMode] = None
    distance_km: Optional[float] = Field(None, ge=0.0)
    standard_lead_time_days: Optional[float] = Field(None, ge=0.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    waypoints_json: Optional[dict[str, Any]] = None


class RouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    name: str
    origin_facility_id: Optional[str] = None
    destination_facility_id: Optional[str] = None
    mode: str
    distance_km: Optional[float] = None
    standard_lead_time_days: Optional[float] = None
    risk_score: Optional[float] = None
    waypoints_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class RouteListResponse(PaginatedResponse[RouteResponse]):
    pass
