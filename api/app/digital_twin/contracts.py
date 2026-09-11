"""Strongly typed Pydantic contracts for RiskWise Digital Twin subsystem.

Enforces:
- Strict validation (extra="forbid")
- Immutability for snapshots (frozen=True)
- Type safety and coordinate/metric range bounding
- Deterministic serialization
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.digital_twin import TwinNodeType, TwinEdgeType


class DigitalTwinProvenance(BaseModel):
    """Authoritative source provenance descriptor for nodes and edges."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_entity_type: str = Field(..., min_length=1, max_length=64)
    source_entity_id: str = Field(..., min_length=1, max_length=64)
    source_system: str = Field(default="INTERNAL_DB", min_length=1, max_length=64)
    source_timestamp: Optional[datetime] = None
    source_reference: Optional[str] = Field(None, max_length=255)
    confidence_score: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TwinNodeContract(BaseModel):
    """Strongly typed representation of an operational twin node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(..., min_length=1, max_length=64, description="Deterministic UUIDv5 ID")
    organization_id: str = Field(..., min_length=1, max_length=64)
    node_type: TwinNodeType
    source_entity_type: str = Field(..., min_length=1, max_length=64)
    source_entity_id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    health_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    status: Optional[str] = Field(None, max_length=64)
    properties: Dict[str, Any] = Field(default_factory=dict)
    source_timestamp: Optional[datetime] = None
    provenance: Optional[DigitalTwinProvenance] = None
    fingerprint: str = Field(..., min_length=64, max_length=64, description="SHA-256 hex digest")

    @property
    def provenance_info(self) -> DigitalTwinProvenance:
        if self.provenance is not None:
            return self.provenance
        return DigitalTwinProvenance(
            source_entity_type=self.source_entity_type,
            source_entity_id=self.source_entity_id,
            source_system="INTERNAL_DB",
            source_timestamp=self.source_timestamp,
            metadata=dict(self.properties),
        )


class TwinEdgeContract(BaseModel):
    """Strongly typed representation of an operational relationship edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(..., min_length=1, max_length=64, description="Deterministic UUIDv5 ID")
    organization_id: str = Field(..., min_length=1, max_length=64)
    from_node_id: str = Field(..., min_length=1, max_length=64)
    to_node_id: str = Field(..., min_length=1, max_length=64)
    edge_type: TwinEdgeType
    status: Optional[str] = Field(None, max_length=64)
    flow_capacity: Optional[float] = Field(None, ge=0.0)
    current_flow: Optional[float] = Field(None, ge=0.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    properties: Dict[str, Any] = Field(default_factory=dict)
    source_reference: Optional[str] = Field(None, max_length=255)
    provenance: Optional[DigitalTwinProvenance] = None
    fingerprint: str = Field(..., min_length=64, max_length=64, description="SHA-256 hex digest")

    @property
    def provenance_info(self) -> DigitalTwinProvenance:
        if self.provenance is not None:
            return self.provenance
        return DigitalTwinProvenance(
            source_entity_type="EDGE",
            source_entity_id=self.edge_id,
            source_system="INTERNAL_DB",
            source_reference=self.source_reference,
            metadata=dict(self.properties),
        )


class DigitalTwinSnapshot(BaseModel):
    """Immutable snapshot of the Digital Twin graph at a specific point in time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    twin_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    version: str = Field(default="1", min_length=1, max_length=32)
    node_count: int = Field(..., ge=0)
    edge_count: int = Field(..., ge=0)
    nodes: Dict[str, TwinNodeContract]
    edges: Dict[str, TwinEdgeContract]
    source_fingerprint: str = Field(..., min_length=64, max_length=64)
    twin_fingerprint: str = Field(..., min_length=64, max_length=64)
    generated_at: datetime
    status: str = Field(default="CURRENT", max_length=32)


class TwinValidationResult(BaseModel):
    """Result of graph structure, reference, and tenant consistency validation."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    node_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)


class TwinSubgraph(BaseModel):
    """Bounded subgraph returned from a query or traversal."""

    model_config = ConfigDict(extra="forbid")

    root_node_id: str
    depth: int = Field(..., ge=0)
    nodes: List[TwinNodeContract]
    edges: List[TwinEdgeContract]
    total_nodes: int = Field(..., ge=0)
    total_edges: int = Field(..., ge=0)


class TwinQuery(BaseModel):
    """Bounded query parameters for graph search, filtering, and traversal."""

    model_config = ConfigDict(extra="forbid")

    node_id: Optional[str] = Field(None, max_length=64)
    node_types: Optional[List[TwinNodeType]] = None
    edge_types: Optional[List[TwinEdgeType]] = None
    max_depth: int = Field(default=3, ge=1, le=10)
    max_nodes: int = Field(default=100, ge=1, le=500)
    max_edges: int = Field(default=200, ge=1, le=1000)


class TwinPathResult(BaseModel):
    """Deterministic path discovery result without optimization or ranking."""

    model_config = ConfigDict(extra="forbid")

    source_node_id: str
    target_node_id: str
    path_found: bool
    node_ids: List[str] = Field(default_factory=list)
    edge_ids: List[str] = Field(default_factory=list)
    hop_count: int = Field(default=0, ge=0)


# Exact Phase 12 Conceptual Specification Aliases
DigitalTwinNode = TwinNodeContract
DigitalTwinEdge = TwinEdgeContract
DigitalTwinQuery = TwinQuery
DigitalTwinPath = TwinPathResult
DigitalTwinResult = TwinValidationResult

