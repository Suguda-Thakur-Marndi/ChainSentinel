"""Domain services for Logistics & Network entities:
SupplierSite, Factory, Warehouse, Port, Carrier, Product, Route, Shipment, ShipmentEvent.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel
from app.core.context import AuthenticatedContext
from app.core.errors import (
    ConflictError,
    ImmutableResourceError,
    LifecycleStateError,
    NotFoundError,
    ValidationDomainError,
)
from app.db.unit_of_work import UnitOfWork
from app.models.logistics import Shipment, ShipmentEvent
from app.models.network import Carrier, Factory, Port, Product, Route, SupplierSite, Warehouse
from app.repositories.network_repositories import (
    CARRIER_FILTER_ALLOWLIST,
    CARRIER_SEARCH_COLUMNS,
    CARRIER_SORT_ALLOWLIST,
    FACTORY_FILTER_ALLOWLIST,
    FACTORY_SEARCH_COLUMNS,
    FACTORY_SORT_ALLOWLIST,
    PRODUCT_FILTER_ALLOWLIST,
    PRODUCT_SEARCH_COLUMNS,
    PRODUCT_SORT_ALLOWLIST,
    ROUTE_FILTER_ALLOWLIST,
    ROUTE_SEARCH_COLUMNS,
    ROUTE_SORT_ALLOWLIST,
    SUPPLIER_SITE_FILTER_ALLOWLIST,
    SUPPLIER_SITE_SEARCH_COLUMNS,
    SUPPLIER_SITE_SORT_ALLOWLIST,
    WAREHOUSE_FILTER_ALLOWLIST,
    WAREHOUSE_SEARCH_COLUMNS,
    WAREHOUSE_SORT_ALLOWLIST,
)
from app.repositories.port import (
    PORT_FILTER_ALLOWLIST,
    PORT_SEARCH_COLUMNS,
    PORT_SORT_ALLOWLIST,
)
from app.repositories.shipment import (
    EVENT_FILTER_ALLOWLIST,
    EVENT_SEARCH_COLUMNS,
    EVENT_SORT_ALLOWLIST,
    SHIPMENT_FILTER_ALLOWLIST,
    SHIPMENT_SEARCH_COLUMNS,
    SHIPMENT_SORT_ALLOWLIST,
)
from app.schemas.common import PaginatedResponse, PaginationMeta, PaginationParams
from app.schemas.logistics import (
    ShipmentCreate,
    ShipmentEventCreate,
    ShipmentEventListResponse,
    ShipmentEventResponse,
    ShipmentListResponse,
    ShipmentResponse,
    ShipmentUpdate,
)
from app.schemas.network import (
    CarrierCreate,
    CarrierListResponse,
    CarrierResponse,
    CarrierUpdate,
    FactoryCreate,
    FactoryListResponse,
    FactoryResponse,
    FactoryUpdate,
    PortListResponse,
    PortResponse,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
    RouteCreate,
    RouteListResponse,
    RouteResponse,
    RouteUpdate,
    SupplierSiteCreate,
    SupplierSiteListResponse,
    SupplierSiteResponse,
    SupplierSiteUpdate,
    WarehouseCreate,
    WarehouseListResponse,
    WarehouseResponse,
    WarehouseUpdate,
)
from app.services.audit_service import AuditService
from app.services.base import BaseService


def _clean_payload(data: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Extract dict and convert Enum attributes to raw string values."""
    payload = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)
    for k, v in payload.items():
        if hasattr(v, "value"):
            payload[k] = v.value
    return payload


# ==============================================================================
# 1. SUPPLIER SITE SERVICE
# ==============================================================================
class SupplierSiteService(BaseService[SupplierSite]):
    """Domain service managing SupplierSite lifecycle, validations, and audit."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(SupplierSite, uow, context)

    def create_site(self, data: SupplierSiteCreate) -> SupplierSiteResponse:
        """Create a new SupplierSite enforcing parent supplier ownership."""
        org_id = self._enforce_tenant_scope()

        # Validate parent supplier exists and belongs to this organization
        supplier = self.uow.suppliers.get(data.supplier_id, org_id=org_id)
        if not supplier:
            raise NotFoundError(
                message=f"Parent Supplier with ID '{data.supplier_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Supplier", "resource_id": data.supplier_id},
            )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            site = SupplierSite(**payload)
            self.uow.supplier_sites.create(site, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="SupplierSite",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=site.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return SupplierSiteResponse.model_validate(site)

    def get_site(self, site_id: str) -> SupplierSiteResponse:
        """Retrieve a single supplier site with tenant isolation and 404 masking."""
        site = self.get_by_id(site_id)
        return SupplierSiteResponse.model_validate(site)

    def list_sites(
        self,
        params: PaginationParams,
        supplier_id: Optional[str] = None,
        status: Optional[str] = None,
        country: Optional[str] = None,
        site_type: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> SupplierSiteListResponse:
        """List supplier sites with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if supplier_id:
            filters["supplier_id"] = supplier_id
        if status:
            filters["status"] = status
        if country:
            filters["country"] = country
        if site_type:
            filters["site_type"] = site_type

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=SUPPLIER_SITE_FILTER_ALLOWLIST,
            sort_allowlist=SUPPLIER_SITE_SORT_ALLOWLIST,
            search_columns=SUPPLIER_SITE_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [SupplierSiteResponse.model_validate(item) for item in paginated.items]
        return SupplierSiteListResponse(items=items, pagination=paginated.pagination)

    def update_site(self, site_id: str, data: SupplierSiteUpdate) -> SupplierSiteResponse:
        """Update an existing supplier site with audit logging."""
        site = self.get_by_id(site_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "supplier_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        before_data = {
            "name": site.name,
            "country": site.country,
            "city": site.city,
            "site_type": site.site_type,
            "capacity": site.capacity,
            "status": site.status,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(site, k, v)
            site.updated_at = datetime.now(timezone.utc)
            self.uow.supplier_sites.update(site, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="SupplierSite",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=site.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return SupplierSiteResponse.model_validate(site)


# ==============================================================================
# 2. FACTORY SERVICE
# ==============================================================================
class FactoryService(BaseService[Factory]):
    """Domain service managing Factory lifecycle, validations, and audit."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Factory, uow, context)

    def create_factory(self, data: FactoryCreate) -> FactoryResponse:
        """Create a new Factory within the tenant boundary."""
        org_id = self._enforce_tenant_scope()

        if data.code:
            existing = self.uow.factories.get_by_code(data.code, org_id=org_id)
            if existing:
                raise ConflictError(
                    message=f"Factory with code '{data.code}' already exists in this organization",
                    code="FACTORY_CODE_EXISTS",
                    details={"code": data.code},
                )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            factory = Factory(**payload)
            self.uow.factories.create(factory, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Factory",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=factory.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return FactoryResponse.model_validate(factory)

    def get_factory(self, factory_id: str) -> FactoryResponse:
        """Retrieve an individual factory by ID enforcing tenant isolation."""
        factory = self.get_by_id(factory_id)
        return FactoryResponse.model_validate(factory)

    def list_factories(
        self,
        params: PaginationParams,
        status: Optional[str] = None,
        country: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> FactoryListResponse:
        """List factories with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if country:
            filters["country"] = country

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=FACTORY_FILTER_ALLOWLIST,
            sort_allowlist=FACTORY_SORT_ALLOWLIST,
            search_columns=FACTORY_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [FactoryResponse.model_validate(item) for item in paginated.items]
        return FactoryListResponse(items=items, pagination=paginated.pagination)

    def update_factory(self, factory_id: str, data: FactoryUpdate) -> FactoryResponse:
        """Update an existing factory with business validations and audit logging."""
        factory = self.get_by_id(factory_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        new_code = update_dict.get("code")
        if new_code and new_code != factory.code:
            existing = self.uow.factories.get_by_code(new_code, org_id=org_id)
            if existing and existing.id != factory.id:
                raise ConflictError(
                    message=f"Factory with code '{new_code}' already exists in this organization",
                    code="FACTORY_CODE_EXISTS",
                    details={"code": new_code},
                )

        before_data = {
            "name": factory.name,
            "code": factory.code,
            "country": factory.country,
            "city": factory.city,
            "capacity": factory.capacity,
            "utilization": factory.utilization,
            "status": factory.status,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(factory, k, v)
            factory.updated_at = datetime.now(timezone.utc)
            self.uow.factories.update(factory, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Factory",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=factory.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return FactoryResponse.model_validate(factory)


# ==============================================================================
# 3. WAREHOUSE SERVICE
# ==============================================================================
class WarehouseService(BaseService[Warehouse]):
    """Domain service managing Warehouse lifecycle, capacity rules, and audit."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Warehouse, uow, context)

    def create_warehouse(self, data: WarehouseCreate) -> WarehouseResponse:
        """Create a new Warehouse with capacity validation."""
        org_id = self._enforce_tenant_scope()

        if data.code:
            existing = self.uow.warehouses.get_by_code(data.code, org_id=org_id)
            if existing:
                raise ConflictError(
                    message=f"Warehouse with code '{data.code}' already exists in this organization",
                    code="WAREHOUSE_CODE_EXISTS",
                    details={"code": data.code},
                )

        # Validate current_occupancy <= total_capacity if both provided
        if data.total_capacity is not None and data.current_occupancy is not None:
            if data.current_occupancy > data.total_capacity:
                raise ValidationDomainError(
                    message="Warehouse current occupancy cannot exceed total capacity",
                    code="OCCUPANCY_EXCEEDS_CAPACITY",
                    details={
                        "current_occupancy": data.current_occupancy,
                        "total_capacity": data.total_capacity,
                    },
                )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            warehouse = Warehouse(**payload)
            self.uow.warehouses.create(warehouse, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Warehouse",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=warehouse.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return WarehouseResponse.model_validate(warehouse)

    def get_warehouse(self, warehouse_id: str) -> WarehouseResponse:
        """Retrieve a warehouse by ID enforcing tenant isolation."""
        warehouse = self.get_by_id(warehouse_id)
        return WarehouseResponse.model_validate(warehouse)

    def list_warehouses(
        self,
        params: PaginationParams,
        status: Optional[str] = None,
        country: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> WarehouseListResponse:
        """List warehouses with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if country:
            filters["country"] = country

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=WAREHOUSE_FILTER_ALLOWLIST,
            sort_allowlist=WAREHOUSE_SORT_ALLOWLIST,
            search_columns=WAREHOUSE_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [WarehouseResponse.model_validate(item) for item in paginated.items]
        return WarehouseListResponse(items=items, pagination=paginated.pagination)

    def update_warehouse(self, warehouse_id: str, data: WarehouseUpdate) -> WarehouseResponse:
        """Update an existing warehouse with capacity validation and audit logging."""
        warehouse = self.get_by_id(warehouse_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        new_code = update_dict.get("code")
        if new_code and new_code != warehouse.code:
            existing = self.uow.warehouses.get_by_code(new_code, org_id=org_id)
            if existing and existing.id != warehouse.id:
                raise ConflictError(
                    message=f"Warehouse with code '{new_code}' already exists in this organization",
                    code="WAREHOUSE_CODE_EXISTS",
                    details={"code": new_code},
                )

        effective_capacity = update_dict.get("total_capacity", warehouse.total_capacity)
        effective_occupancy = update_dict.get("current_occupancy", warehouse.current_occupancy)
        if effective_capacity is not None and effective_occupancy is not None:
            if effective_occupancy > effective_capacity:
                raise ValidationDomainError(
                    message="Warehouse current occupancy cannot exceed total capacity",
                    code="OCCUPANCY_EXCEEDS_CAPACITY",
                    details={
                        "current_occupancy": effective_occupancy,
                        "total_capacity": effective_capacity,
                    },
                )

        before_data = {
            "name": warehouse.name,
            "code": warehouse.code,
            "country": warehouse.country,
            "city": warehouse.city,
            "total_capacity": warehouse.total_capacity,
            "current_occupancy": warehouse.current_occupancy,
            "status": warehouse.status,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(warehouse, k, v)
            warehouse.updated_at = datetime.now(timezone.utc)
            self.uow.warehouses.update(warehouse, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Warehouse",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=warehouse.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return WarehouseResponse.model_validate(warehouse)


# ==============================================================================
# 4. PORT SERVICE (GLOBAL REFERENCE)
# ==============================================================================
class PortService:
    """Service managing global Port reference data operations (read-only to tenants)."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        self.uow = uow
        self.context = context

    def get_port(self, port_id: str) -> PortResponse:
        """Retrieve a global port reference by ID."""
        port = self.uow.ports.get(port_id)
        if not port:
            raise NotFoundError(
                message=f"Port with ID '{port_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Port", "resource_id": port_id},
            )
        return PortResponse.model_validate(port)

    def list_ports(
        self,
        params: PaginationParams,
        country: Optional[str] = None,
        port_type: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> PortListResponse:
        """List global ports with pagination, filtering, search, and sorting."""
        filters: dict[str, Any] = {}
        if country:
            filters["country"] = country
        if port_type:
            filters["port_type"] = port_type

        total = self.uow.ports.count(
            org_id=None,
            filters=filters,
            search=search,
            filter_allowlist=PORT_FILTER_ALLOWLIST,
            search_columns=PORT_SEARCH_COLUMNS,
        )

        items = self.uow.ports.list(
            org_id=None,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=PORT_FILTER_ALLOWLIST,
            sort_allowlist=PORT_SORT_ALLOWLIST,
            search_columns=PORT_SEARCH_COLUMNS,
            default_sort_field="name",
            default_sort_desc=False,
        )

        pages = (total + params.limit - 1) // params.limit if total > 0 else 0
        validated_items = [PortResponse.model_validate(item) for item in items]
        return PortListResponse(
            items=validated_items,
            pagination=PaginationMeta(total=total, page=params.page, limit=params.limit, pages=pages),
        )


# ==============================================================================
# 5. CARRIER SERVICE
# ==============================================================================
class CarrierService(BaseService[Carrier]):
    """Domain service managing Carrier lifecycle, validations, and audit."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Carrier, uow, context)

    def create_carrier(self, data: CarrierCreate) -> CarrierResponse:
        """Create a new Carrier within tenant boundary."""
        org_id = self._enforce_tenant_scope()

        if data.code:
            existing = self.uow.carriers.get_by_code(data.code, org_id=org_id)
            if existing:
                raise ConflictError(
                    message=f"Carrier with code '{data.code}' already exists in this organization",
                    code="CARRIER_CODE_EXISTS",
                    details={"code": data.code},
                )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            carrier = Carrier(**payload)
            self.uow.carriers.create(carrier, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Carrier",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=carrier.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return CarrierResponse.model_validate(carrier)

    def get_carrier(self, carrier_id: str) -> CarrierResponse:
        """Retrieve a carrier by ID enforcing tenant isolation."""
        carrier = self.get_by_id(carrier_id)
        return CarrierResponse.model_validate(carrier)

    def list_carriers(
        self,
        params: PaginationParams,
        mode: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> CarrierListResponse:
        """List carriers with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if mode:
            filters["mode"] = mode

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=CARRIER_FILTER_ALLOWLIST,
            sort_allowlist=CARRIER_SORT_ALLOWLIST,
            search_columns=CARRIER_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [CarrierResponse.model_validate(item) for item in paginated.items]
        return CarrierListResponse(items=items, pagination=paginated.pagination)

    def update_carrier(self, carrier_id: str, data: CarrierUpdate) -> CarrierResponse:
        """Update an existing carrier with audit logging."""
        carrier = self.get_by_id(carrier_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        new_code = update_dict.get("code")
        if new_code and new_code != carrier.code:
            existing = self.uow.carriers.get_by_code(new_code, org_id=org_id)
            if existing and existing.id != carrier.id:
                raise ConflictError(
                    message=f"Carrier with code '{new_code}' already exists in this organization",
                    code="CARRIER_CODE_EXISTS",
                    details={"code": new_code},
                )

        before_data = {
            "name": carrier.name,
            "code": carrier.code,
            "mode": carrier.mode,
            "on_time_reliability": carrier.on_time_reliability,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(carrier, k, v)
            carrier.updated_at = datetime.now(timezone.utc)
            self.uow.carriers.update(carrier, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Carrier",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=carrier.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return CarrierResponse.model_validate(carrier)


# ==============================================================================
# 6. PRODUCT SERVICE
# ==============================================================================
class ProductService(BaseService[Product]):
    """Domain service managing Product lifecycle and tenant-unique SKU enforcement."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Product, uow, context)

    def create_product(self, data: ProductCreate) -> ProductResponse:
        """Create a new Product enforcing unique SKU per tenant."""
        org_id = self._enforce_tenant_scope()

        existing = self.uow.products.get_by_sku(data.sku, org_id=org_id)
        if existing:
            raise ConflictError(
                message=f"Product with SKU '{data.sku}' already exists in this organization",
                code="PRODUCT_SKU_EXISTS",
                details={"sku": data.sku},
            )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            product = Product(**payload)
            self.uow.products.create(product, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Product",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=product.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return ProductResponse.model_validate(product)

    def get_product(self, product_id: str) -> ProductResponse:
        """Retrieve a product by ID enforcing tenant isolation."""
        product = self.get_by_id(product_id)
        return ProductResponse.model_validate(product)

    def list_products(
        self,
        params: PaginationParams,
        category: Optional[str] = None,
        currency: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> ProductListResponse:
        """List products with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if category:
            filters["category"] = category
        if currency:
            filters["currency"] = currency

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=PRODUCT_FILTER_ALLOWLIST,
            sort_allowlist=PRODUCT_SORT_ALLOWLIST,
            search_columns=PRODUCT_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [ProductResponse.model_validate(item) for item in paginated.items]
        return ProductListResponse(items=items, pagination=paginated.pagination)

    def update_product(self, product_id: str, data: ProductUpdate) -> ProductResponse:
        """Update an existing product enforcing SKU uniqueness upon change."""
        product = self.get_by_id(product_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        new_sku = update_dict.get("sku")
        if new_sku and new_sku != product.sku:
            existing = self.uow.products.get_by_sku(new_sku, org_id=org_id)
            if existing and existing.id != product.id:
                raise ConflictError(
                    message=f"Product with SKU '{new_sku}' already exists in this organization",
                    code="PRODUCT_SKU_EXISTS",
                    details={"sku": new_sku},
                )

        before_data = {
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "unit_cost": product.unit_cost,
            "currency": product.currency,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(product, k, v)
            product.updated_at = datetime.now(timezone.utc)
            self.uow.products.update(product, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Product",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=product.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return ProductResponse.model_validate(product)


# ==============================================================================
# 7. ROUTE SERVICE
# ==============================================================================
class RouteService(BaseService[Route]):
    """Domain service managing shipping Route definitions and corridors."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Route, uow, context)

    def create_route(self, data: RouteCreate) -> RouteResponse:
        """Create a new Route within tenant boundary."""
        org_id = self._enforce_tenant_scope()
        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            route = Route(**payload)
            self.uow.routes.create(route, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Route",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=route.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return RouteResponse.model_validate(route)

    def get_route(self, route_id: str) -> RouteResponse:
        """Retrieve an individual route by ID enforcing tenant isolation."""
        route = self.get_by_id(route_id)
        return RouteResponse.model_validate(route)

    def list_routes(
        self,
        params: PaginationParams,
        mode: Optional[str] = None,
        origin_facility_id: Optional[str] = None,
        destination_facility_id: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> RouteListResponse:
        """List routes with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if mode:
            filters["mode"] = mode
        if origin_facility_id:
            filters["origin_facility_id"] = origin_facility_id
        if destination_facility_id:
            filters["destination_facility_id"] = destination_facility_id

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=ROUTE_FILTER_ALLOWLIST,
            sort_allowlist=ROUTE_SORT_ALLOWLIST,
            search_columns=ROUTE_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [RouteResponse.model_validate(item) for item in paginated.items]
        return RouteListResponse(items=items, pagination=paginated.pagination)

    def update_route(self, route_id: str, data: RouteUpdate) -> RouteResponse:
        """Update an existing route with audit logging."""
        route = self.get_by_id(route_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        before_data = {
            "name": route.name,
            "origin_facility_id": route.origin_facility_id,
            "destination_facility_id": route.destination_facility_id,
            "mode": route.mode,
            "distance_km": route.distance_km,
            "standard_lead_time_days": route.standard_lead_time_days,
            "risk_score": route.risk_score,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(route, k, v)
            route.updated_at = datetime.now(timezone.utc)
            self.uow.routes.update(route, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Route",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=route.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return RouteResponse.model_validate(route)


# ==============================================================================
# 8. SHIPMENT SERVICE
# ==============================================================================
TERMINAL_SHIPMENT_STATUSES = {"DELIVERED", "CANCELLED"}


class ShipmentService(BaseService[Shipment]):
    """Domain service managing Shipment lifecycle, tenant relationship checks, and audit."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        super().__init__(Shipment, uow, context)

    def _validate_referenced_resources(
        self,
        org_id: str,
        carrier_id: Optional[str] = None,
        product_id: Optional[str] = None,
        route_id: Optional[str] = None,
    ) -> None:
        """Validate that referenced resources belong to the authenticated organization."""
        if carrier_id:
            carrier = self.uow.carriers.get(carrier_id, org_id=org_id)
            if not carrier:
                raise NotFoundError(
                    message=f"Referenced Carrier with ID '{carrier_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Carrier", "resource_id": carrier_id},
                )

        if product_id:
            product = self.uow.products.get(product_id, org_id=org_id)
            if not product:
                raise NotFoundError(
                    message=f"Referenced Product with ID '{product_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Product", "resource_id": product_id},
                )

        if route_id:
            route = self.uow.routes.get(route_id, org_id=org_id)
            if not route:
                raise NotFoundError(
                    message=f"Referenced Route with ID '{route_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Route", "resource_id": route_id},
                )

    def create_shipment(self, data: ShipmentCreate) -> ShipmentResponse:
        """Create a new Shipment validating tracking uniqueness and tenant-owned relationships."""
        org_id = self._enforce_tenant_scope()

        # Check tracking number uniqueness
        existing = self.uow.shipments.get_by_tracking_number(data.tracking_number, org_id=org_id)
        if existing:
            raise ConflictError(
                message=f"Shipment with tracking number '{data.tracking_number}' already exists in this organization",
                code="TRACKING_NUMBER_EXISTS",
                details={"tracking_number": data.tracking_number},
            )

        # Validate referenced resources belong to current tenant
        self._validate_referenced_resources(
            org_id=org_id,
            carrier_id=data.carrier_id,
            product_id=data.product_id,
            route_id=data.route_id,
        )

        payload = _clean_payload(data)
        payload["org_id"] = org_id

        with self.uow:
            shipment = Shipment(**payload)
            self.uow.shipments.create(shipment, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="Shipment",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=shipment.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return ShipmentResponse.model_validate(shipment)

    def get_shipment(self, shipment_id: str) -> ShipmentResponse:
        """Retrieve a shipment by ID enforcing tenant isolation."""
        shipment = self.get_by_id(shipment_id)
        return ShipmentResponse.model_validate(shipment)

    def list_shipments(
        self,
        params: PaginationParams,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        carrier_id: Optional[str] = None,
        product_id: Optional[str] = None,
        data_provenance: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> ShipmentListResponse:
        """List shipments with tenant isolation, safe filters, sorting, and search."""
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if mode:
            filters["mode"] = mode
        if carrier_id:
            filters["carrier_id"] = carrier_id
        if product_id:
            filters["product_id"] = product_id
        if data_provenance:
            filters["data_provenance"] = data_provenance

        paginated = self.list_paginated(
            params=params,
            filters=filters,
            sort_param=sort_param,
            search=search,
            filter_allowlist=SHIPMENT_FILTER_ALLOWLIST,
            sort_allowlist=SHIPMENT_SORT_ALLOWLIST,
            search_columns=SHIPMENT_SEARCH_COLUMNS,
            default_sort_field="created_at",
            default_sort_desc=True,
        )
        items = [ShipmentResponse.model_validate(item) for item in paginated.items]
        return ShipmentListResponse(items=items, pagination=paginated.pagination)

    def update_shipment(self, shipment_id: str, data: ShipmentUpdate) -> ShipmentResponse:
        """Update an existing shipment enforcing legal status transitions and audit logging."""
        shipment = self.get_by_id(shipment_id)
        org_id = self._enforce_tenant_scope()

        update_dict = _clean_payload(data)
        for forbidden in ("id", "org_id", "tracking_number", "created_at", "updated_at"):
            update_dict.pop(forbidden, None)

        # Validate referenced resources if modified
        self._validate_referenced_resources(
            org_id=org_id,
            carrier_id=update_dict.get("carrier_id"),
            product_id=update_dict.get("product_id"),
            route_id=update_dict.get("route_id"),
        )

        # Status transition validation
        new_status = update_dict.get("status")
        if new_status and new_status != shipment.status:
            if shipment.status in TERMINAL_SHIPMENT_STATUSES and new_status not in TERMINAL_SHIPMENT_STATUSES:
                raise LifecycleStateError(
                    message=f"Cannot transition shipment from terminal state '{shipment.status}' to '{new_status}'",
                    code="ILLEGAL_STATUS_TRANSITION",
                    details={"current_status": shipment.status, "target_status": new_status},
                )

        before_data = {
            "status": shipment.status,
            "mode": shipment.mode,
            "carrier_id": shipment.carrier_id,
            "route_id": shipment.route_id,
            "current_lat": shipment.current_lat,
            "current_lng": shipment.current_lng,
            "eta": shipment.eta.isoformat() if shipment.eta else None,
            "delay_minutes": shipment.delay_minutes,
        }

        with self.uow:
            for k, v in update_dict.items():
                setattr(shipment, k, v)
            shipment.updated_at = datetime.now(timezone.utc)
            self.uow.shipments.update(shipment, auto_commit=False)

            AuditService.log_event(
                uow=self.uow,
                action="UPDATE",
                resource_type="Shipment",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=shipment.id,
                before_data=before_data,
                after_data=update_dict,
                auto_commit=False,
            )
            self.uow.commit()

        return ShipmentResponse.model_validate(shipment)


# ==============================================================================
# 9. SHIPMENT EVENT SERVICE (APPEND-ONLY TELEMETRY)
# ==============================================================================
class ShipmentEventService:
    """Domain service managing ShipmentEvent append-only telemetry records."""

    def __init__(self, uow: UnitOfWork, context: AuthenticatedContext):
        self.uow = uow
        self.context = context

    def _enforce_tenant_scope(self) -> str:
        """Derive authoritative tenant organization ID."""
        if not self.context or not self.context.organization_id:
            raise NotFoundError(message="Tenant context required", code="ORGANIZATION_CONTEXT_REQUIRED")
        return self.context.organization_id

    def create_event(self, data: ShipmentEventCreate) -> ShipmentEventResponse:
        """Append an immutable telemetry event ensuring parent shipment belongs to tenant."""
        org_id = self._enforce_tenant_scope()

        # Validate parent shipment exists and belongs to current tenant
        shipment = self.uow.shipments.get(data.shipment_id, org_id=org_id)
        if not shipment:
            raise NotFoundError(
                message=f"Shipment with ID '{data.shipment_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "Shipment", "resource_id": data.shipment_id},
            )

        payload = _clean_payload(data)

        with self.uow:
            event = self.uow.shipment_events.add_event(
                shipment_id=data.shipment_id,
                event_type=payload.get("event_type"),
                mode=payload.get("mode"),
                timestamp=payload.get("timestamp"),
                status=payload.get("status"),
                delay_minutes=payload.get("delay_minutes"),
                latitude=payload.get("latitude"),
                longitude=payload.get("longitude"),
                eta=payload.get("eta"),
                source=payload.get("source", "REAL"),
                source_type=payload.get("source_type"),
                confidence=payload.get("confidence"),
                raw_event_id=payload.get("raw_event_id"),
                metadata_json=payload.get("metadata_json"),
                auto_commit=False,
            )

            AuditService.log_event(
                uow=self.uow,
                action="CREATE",
                resource_type="ShipmentEvent",
                org_id=org_id,
                actor_id=self.context.user_id if self.context else None,
                resource_id=event.id,
                after_data=payload,
                auto_commit=False,
            )
            self.uow.commit()

        return ShipmentEventResponse.model_validate(event)

    def get_event(self, event_id: str) -> ShipmentEventResponse:
        """Retrieve a single shipment event verifying parent shipment ownership."""
        org_id = self._enforce_tenant_scope()
        event = self.uow.shipment_events.get_event_in_org(event_id, org_id=org_id)
        if not event:
            raise NotFoundError(
                message=f"ShipmentEvent with ID '{event_id}' not found",
                code="RESOURCE_NOT_FOUND",
                details={"resource_type": "ShipmentEvent", "resource_id": event_id},
            )
        return ShipmentEventResponse.model_validate(event)

    def list_events(
        self,
        params: PaginationParams,
        shipment_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source_type: Optional[str] = None,
        search: Optional[str] = None,
        sort_param: Optional[str] = None,
    ) -> ShipmentEventListResponse:
        """List shipment events scoped to current tenant via parent shipments."""
        org_id = self._enforce_tenant_scope()

        # If a specific shipment_id is queried, verify tenant ownership
        if shipment_id:
            shipment = self.uow.shipments.get(shipment_id, org_id=org_id)
            if not shipment:
                raise NotFoundError(
                    message=f"Shipment with ID '{shipment_id}' not found",
                    code="RESOURCE_NOT_FOUND",
                    details={"resource_type": "Shipment", "resource_id": shipment_id},
                )

        filters: dict[str, Any] = {}
        if event_type:
            filters["event_type"] = event_type
        if source_type:
            filters["source_type"] = source_type

        items, total = self.uow.shipment_events.list_events_for_org(
            org_id=org_id,
            shipment_id=shipment_id,
            page=params.page,
            limit=params.limit,
            filters=filters,
            sort_param=sort_param,
            search=search,
        )

        pages = (total + params.limit - 1) // params.limit if total > 0 else 0
        validated_items = [ShipmentEventResponse.model_validate(e) for e in items]
        return ShipmentEventListResponse(
            items=validated_items,
            pagination=PaginationMeta(total=total, page=params.page, limit=params.limit, pages=pages),
        )

    def update_event(self, event_id: str, data: Any) -> None:
        """Attempting to update an immutable shipment event raises 405/ImmutableResourceError."""
        raise ImmutableResourceError(
            message="ShipmentEvent is an immutable append-only telemetry record and cannot be modified."
        )

    def delete_event(self, event_id: str) -> None:
        """Attempting to delete an immutable shipment event raises 405/ImmutableResourceError."""
        raise ImmutableResourceError(
            message="ShipmentEvent is an immutable append-only telemetry record and cannot be deleted."
        )
