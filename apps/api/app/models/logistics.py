"""SQLAlchemy models for logistics, freight tracking, telemetry, and inventory management."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Shipment(Base):
    """Consignment shipment tracking in transit across the network."""
    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    tracking_number: Mapped[str] = mapped_column(String(100), nullable=False)
    route_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("routes.id"), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("products.id"), nullable=True)
    carrier_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("carriers.id"), nullable=True)
    origin: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="IN_TRANSIT")
    mode: Mapped[str] = mapped_column(String(50), default="OCEAN")
    current_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eta: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    eta_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delay_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    data_provenance: Mapped[str] = mapped_column(String(50), default="REAL")
    risk_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    events: Mapped[list["ShipmentEvent"]] = relationship(
        "ShipmentEvent", back_populates="shipment", cascade="all, delete-orphan"
    )


class ShipmentEvent(Base):
    """Telemetry milestone event emitted during shipment transit."""
    __tablename__ = "shipment_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    shipment_id: Mapped[str] = mapped_column(String(64), ForeignKey("shipments.id"), nullable=False)
    mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    eta: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delay_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(50), default="REAL")
    source_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_event_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="events")


class Inventory(Base):
    """Stock levels per product and facility."""
    __tablename__ = "inventory"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), nullable=False)
    facility_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    quantity_on_hand: Mapped[float] = mapped_column(Float, nullable=False)
    safety_stock: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reorder_point: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    days_of_supply: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class InventoryMovement(Base):
    """Inventory receipts, transfers, or consumption records."""
    __tablename__ = "inventory_movements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    product_id: Mapped[str] = mapped_column(String(64), ForeignKey("products.id"), nullable=False)
    movement_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    from_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    to_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
