"""SQLAlchemy models for the supply chain Digital Twin topology graph (Nodes and Edges)."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class TwinNode(Base):
    """Entity node in the supply chain digital twin graph."""
    __tablename__ = "twin_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class TwinEdge(Base):
    """Directional flow, transport, or dependency connection between twin nodes."""
    __tablename__ = "twin_edges"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    from_node_id: Mapped[str] = mapped_column(String(64), ForeignKey("twin_nodes.id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String(64), ForeignKey("twin_nodes.id"), nullable=False)
    edge_type: Mapped[str] = mapped_column(String(50), default="FLOW")
    flow_capacity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_flow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    from_node: Mapped["TwinNode"] = relationship("TwinNode", foreign_keys=[from_node_id])
    to_node: Mapped["TwinNode"] = relationship("TwinNode", foreign_keys=[to_node_id])
