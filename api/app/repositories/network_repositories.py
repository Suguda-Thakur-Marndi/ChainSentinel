"""Repositories for Network entities: SupplierSite, Factory, Warehouse, Carrier, Product, Route."""
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.network import Carrier, Factory, Product, Route, SupplierSite, Warehouse
from app.repositories.base import BaseRepository

# ==============================================================================
# SUPPLIER SITES
# ==============================================================================
SUPPLIER_SITE_SEARCH_COLUMNS = ["name", "country", "city", "site_type"]

SUPPLIER_SITE_SORT_ALLOWLIST = {
    "name": SupplierSite.name,
    "capacity": SupplierSite.capacity,
    "created_at": SupplierSite.created_at,
    "updated_at": SupplierSite.updated_at,
}

SUPPLIER_SITE_FILTER_ALLOWLIST = {
    "supplier_id": SupplierSite.supplier_id,
    "status": SupplierSite.status,
    "country": SupplierSite.country,
    "site_type": SupplierSite.site_type,
    "created_at_after": SupplierSite.created_at,
    "created_at_before": SupplierSite.created_at,
}


class SupplierSiteRepository(BaseRepository[SupplierSite]):
    """Data access repository for SupplierSite entities."""

    def __init__(self, session: Session):
        super().__init__(SupplierSite, session)

    def list_by_supplier(self, supplier_id: str, org_id: Optional[str] = None) -> list[SupplierSite]:
        """List all sites belonging to a given supplier within tenant scope."""
        stmt = select(SupplierSite).where(SupplierSite.supplier_id == supplier_id)
        if org_id:
            stmt = stmt.where(SupplierSite.org_id == org_id)
        return list(self.session.scalars(stmt).all())


# ==============================================================================
# FACTORIES
# ==============================================================================
FACTORY_SEARCH_COLUMNS = ["name", "code", "country", "city"]

FACTORY_SORT_ALLOWLIST = {
    "name": Factory.name,
    "code": Factory.code,
    "capacity": Factory.capacity,
    "utilization": Factory.utilization,
    "created_at": Factory.created_at,
    "updated_at": Factory.updated_at,
}

FACTORY_FILTER_ALLOWLIST = {
    "status": Factory.status,
    "country": Factory.country,
    "code": Factory.code,
    "created_at_after": Factory.created_at,
    "created_at_before": Factory.created_at,
}


class FactoryRepository(BaseRepository[Factory]):
    """Data access repository for Factory entities."""

    def __init__(self, session: Session):
        super().__init__(Factory, session)

    def get_by_code(self, code: str, org_id: Optional[str] = None) -> Optional[Factory]:
        """Look up a factory by code within tenant scope."""
        stmt = select(Factory).where(Factory.code == code)
        if org_id:
            stmt = stmt.where(Factory.org_id == org_id)
        return self.session.scalars(stmt).first()


# ==============================================================================
# WAREHOUSES
# ==============================================================================
WAREHOUSE_SEARCH_COLUMNS = ["name", "code", "country", "city"]

WAREHOUSE_SORT_ALLOWLIST = {
    "name": Warehouse.name,
    "code": Warehouse.code,
    "total_capacity": Warehouse.total_capacity,
    "current_occupancy": Warehouse.current_occupancy,
    "created_at": Warehouse.created_at,
    "updated_at": Warehouse.updated_at,
}

WAREHOUSE_FILTER_ALLOWLIST = {
    "status": Warehouse.status,
    "country": Warehouse.country,
    "code": Warehouse.code,
    "created_at_after": Warehouse.created_at,
    "created_at_before": Warehouse.created_at,
}


class WarehouseRepository(BaseRepository[Warehouse]):
    """Data access repository for Warehouse entities."""

    def __init__(self, session: Session):
        super().__init__(Warehouse, session)

    def get_by_code(self, code: str, org_id: Optional[str] = None) -> Optional[Warehouse]:
        """Look up a warehouse by code within tenant scope."""
        stmt = select(Warehouse).where(Warehouse.code == code)
        if org_id:
            stmt = stmt.where(Warehouse.org_id == org_id)
        return self.session.scalars(stmt).first()


# ==============================================================================
# CARRIERS
# ==============================================================================
CARRIER_SEARCH_COLUMNS = ["name", "code"]

CARRIER_SORT_ALLOWLIST = {
    "name": Carrier.name,
    "code": Carrier.code,
    "on_time_reliability": Carrier.on_time_reliability,
    "created_at": Carrier.created_at,
    "updated_at": Carrier.updated_at,
}

CARRIER_FILTER_ALLOWLIST = {
    "mode": Carrier.mode,
    "code": Carrier.code,
    "created_at_after": Carrier.created_at,
    "created_at_before": Carrier.created_at,
}


class CarrierRepository(BaseRepository[Carrier]):
    """Data access repository for Carrier entities."""

    def __init__(self, session: Session):
        super().__init__(Carrier, session)

    def get_by_code(self, code: str, org_id: Optional[str] = None) -> Optional[Carrier]:
        """Look up a carrier by code within tenant scope."""
        stmt = select(Carrier).where(Carrier.code == code)
        if org_id:
            stmt = stmt.where(Carrier.org_id == org_id)
        return self.session.scalars(stmt).first()


# ==============================================================================
# PRODUCTS
# ==============================================================================
PRODUCT_SEARCH_COLUMNS = ["sku", "name", "category"]

PRODUCT_SORT_ALLOWLIST = {
    "sku": Product.sku,
    "name": Product.name,
    "category": Product.category,
    "unit_cost": Product.unit_cost,
    "created_at": Product.created_at,
    "updated_at": Product.updated_at,
}

PRODUCT_FILTER_ALLOWLIST = {
    "category": Product.category,
    "currency": Product.currency,
    "sku": Product.sku,
    "created_at_after": Product.created_at,
    "created_at_before": Product.created_at,
}


class ProductRepository(BaseRepository[Product]):
    """Data access repository for Product entities."""

    def __init__(self, session: Session):
        super().__init__(Product, session)

    def get_by_sku(self, sku: str, org_id: Optional[str] = None) -> Optional[Product]:
        """Look up a product by its SKU within tenant scope."""
        stmt = select(Product).where(Product.sku == sku)
        if org_id:
            stmt = stmt.where(Product.org_id == org_id)
        return self.session.scalars(stmt).first()


# ==============================================================================
# ROUTES
# ==============================================================================
ROUTE_SEARCH_COLUMNS = ["name", "mode"]

ROUTE_SORT_ALLOWLIST = {
    "name": Route.name,
    "mode": Route.mode,
    "distance_km": Route.distance_km,
    "standard_lead_time_days": Route.standard_lead_time_days,
    "risk_score": Route.risk_score,
    "created_at": Route.created_at,
    "updated_at": Route.updated_at,
}

ROUTE_FILTER_ALLOWLIST = {
    "mode": Route.mode,
    "origin_facility_id": Route.origin_facility_id,
    "destination_facility_id": Route.destination_facility_id,
    "created_at_after": Route.created_at,
    "created_at_before": Route.created_at,
}


class RouteRepository(BaseRepository[Route]):
    """Data access repository for Route entities."""

    def __init__(self, session: Session):
        super().__init__(Route, session)
