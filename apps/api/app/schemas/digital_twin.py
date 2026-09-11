"""Pydantic schemas for supply chain Digital Twin topology graph (Nodes and Edges)."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class TwinNodeType(str, Enum):
    SUPPLIER = "SUPPLIER"
    SUPPLIER_SITE = "SUPPLIER_SITE"
    FACTORY = "FACTORY"
    WAREHOUSE = "WAREHOUSE"
    PORT = "PORT"
    CARRIER = "CARRIER"
    ROUTE = "ROUTE"
    SHIPMENT = "SHIPMENT"
    PRODUCT = "PRODUCT"
    CUSTOMER = "CUSTOMER"
    CUSTOM = "CUSTOM"


class TwinEdgeType(str, Enum):
    FLOW = "FLOW"
    TRANSPORT = "TRANSPORT"
    DEPENDENCY = "DEPENDENCY"
    LOCATED_AT = "LOCATED_AT"
    OPERATES = "OPERATES"
    CONNECTS = "CONNECTS"
    CARRIES = "CARRIES"
    SUPPLIES = "SUPPLIES"


# TwinNode
class TwinNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: TwinNodeType = TwinNodeType.SUPPLIER
    entity_id: Optional[str] = Field(None, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    health_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    properties_json: dict[str, Any] = Field(default_factory=dict)


class TwinNodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: Optional[TwinNodeType] = None
    entity_id: Optional[str] = Field(None, max_length=64)
    label: Optional[str] = Field(None, min_length=1, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    health_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    properties_json: Optional[dict[str, Any]] = None


class TwinNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    node_type: str
    entity_id: Optional[str] = None
    label: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    health_score: Optional[float] = None
    properties_json: dict[str, Any]
    updated_at: Optional[datetime] = None


class TwinNodeListResponse(PaginatedResponse[TwinNodeResponse]):
    pass


# TwinEdge
class TwinEdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node_id: str = Field(..., max_length=64)
    to_node_id: str = Field(..., max_length=64)
    edge_type: TwinEdgeType = TwinEdgeType.FLOW
    flow_capacity: Optional[float] = Field(None, ge=0.0)
    current_flow: Optional[float] = Field(None, ge=0.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    properties_json: dict[str, Any] = Field(default_factory=dict)


class TwinEdgeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_type: Optional[TwinEdgeType] = None
    flow_capacity: Optional[float] = Field(None, ge=0.0)
    current_flow: Optional[float] = Field(None, ge=0.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    properties_json: Optional[dict[str, Any]] = None


class TwinEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    from_node_id: str
    to_node_id: str
    edge_type: str
    flow_capacity: Optional[float] = None
    current_flow: Optional[float] = None
    risk_score: Optional[float] = None
    properties_json: dict[str, Any]
    updated_at: Optional[datetime] = None


class TwinEdgeListResponse(PaginatedResponse[TwinEdgeResponse]):
    pass
