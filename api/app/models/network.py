"""SQLAlchemy models for supply chain network entities (Suppliers, Facilities, Ports, Routes, Carriers, Products)."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Supplier(Base):
    """Tiered supplier organization profile."""
    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String(50), default="MEDIUM", nullable=True)
    criticality: Mapped[Optional[str]] = mapped_column(String(50), default="MEDIUM", nullable=True)
    reliability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    financial_exposure: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lead_time_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_risk_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    supplier_sites: Mapped[list["SupplierSite"]] = relationship("SupplierSite", back_populates="supplier")


class SupplierSite(Base):
    """Specific manufacturing or storage facility operated by a supplier."""
    __tablename__ = "supplier_sites"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    supplier_id: Mapped[str] = mapped_column(String(64), ForeignKey("suppliers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    site_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    capacity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="OPERATIONAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="supplier_sites")


class Factory(Base):
    """Manufacturing plant or production facility."""
    __tablename__ = "factories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    capacity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    utilization: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="OPERATIONAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class Warehouse(Base):
    """Storage, distribution, or cross-docking facility."""
    __tablename__ = "warehouses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_capacity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_occupancy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="OPERATIONAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class Port(Base):
    """Global sea, air, or inland transit terminal (shared reference data)."""
    __tablename__ = "ports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    port_type: Mapped[str] = mapped_column(String(50), default="SEA")
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    congestion_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_wait_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class Carrier(Base):
    """Freight forwarding and transport service provider."""
    __tablename__ = "carriers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    on_time_reliability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contact_info_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class Product(Base):
    """Product catalog SKU and item definition."""
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    unit_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class Route(Base):
    """Defined shipping corridor between origin and destination nodes."""
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin_facility_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    destination_facility_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(50), default="OCEAN")
    distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    standard_lead_time_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    waypoints_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
