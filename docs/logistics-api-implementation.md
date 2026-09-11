# RiskWise 2.0 — Logistics API Implementation Report

**Document Version:** 1.0.0  
**Status:** IMPLEMENTED & VALIDATED  
**Phase:** Phase 4 — Core APIs (Step 4 — Logistics APIs)  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Resource Scope & Architecture

In Phase 4 Step 4, production Logistics APIs were implemented strictly covering the 9 logistics and network resources approved in the Core API Contract (`docs/core-api-contract.md`):

1. **`supplier-sites`** (`SupplierSite` model, `supplier_sites` table) — Tenant-scoped. Physical manufacturing and storage sites operated by tiered suppliers.
2. **`factories`** (`Factory` model, `factories` table) — Tenant-scoped. Internal and contract manufacturing production facilities.
3. **`warehouses`** (`Warehouse` model, `warehouses` table) — Tenant-scoped. Regional storage, distribution, and cross-docking facilities.
4. **`ports`** (`Port` model, `ports` table) — Global reference catalog. UN/LOCODE sea, air, and inland transit choke points.
5. **`carriers`** (`Carrier` model, `carriers` table) — Tenant-scoped. Freight forwarders, shipping lines, and logistics service providers.
6. **`products`** (`Product` model, `products` table) — Tenant-scoped. Catalog SKUs, bill-of-materials items, and unit economics.
7. **`routes`** (`Route` model, `routes` table) — Tenant-scoped. Defined shipping corridors between network facilities.
8. **`shipments`** (`Shipment` model, `shipments` table) — Tenant-scoped. Real-time active freight tracking consignments.
9. **`shipment-events`** (`ShipmentEvent` model, `shipment_events` table) — Child-scoped (via `Shipment.org_id`). Append-only telemetry milestones and AIS event stream.

---

## 2. Production Endpoints Matrix

| Resource | HTTP Method | Path | Auth | Scope | Roles | Operation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Supplier Sites** | `GET` | `/api/v1/supplier-sites` | Cookie | Tenant | `Viewer`+ | List supplier sites with pagination, search, filter, sort |
| **Supplier Sites** | `POST` | `/api/v1/supplier-sites` | Cookie | Tenant | `OpsManager`+ | Create supplier site under tenant's supplier |
| **Supplier Sites** | `GET` | `/api/v1/supplier-sites/{id}` | Cookie | Tenant | `Viewer`+ | Get single supplier site with 404 masking |
| **Supplier Sites** | `PATCH` | `/api/v1/supplier-sites/{id}` | Cookie | Tenant | `OpsManager`+ | Update supplier site attributes |
| **Factories** | `GET` | `/api/v1/factories` | Cookie | Tenant | `Viewer`+ | List factories with pagination, search, filter, sort |
| **Factories** | `POST` | `/api/v1/factories` | Cookie | Tenant | `OpsManager`+ | Create factory with optional unique code |
| **Factories** | `GET` | `/api/v1/factories/{id}` | Cookie | Tenant | `Viewer`+ | Get single factory with 404 masking |
| **Factories** | `PATCH` | `/api/v1/factories/{id}` | Cookie | Tenant | `OpsManager`+ | Update factory details |
| **Warehouses** | `GET` | `/api/v1/warehouses` | Cookie | Tenant | `Viewer`+ | List warehouses with pagination, search, filter, sort |
| **Warehouses** | `POST` | `/api/v1/warehouses` | Cookie | Tenant | `OpsManager`+ | Create warehouse with capacity validation |
| **Warehouses** | `GET` | `/api/v1/warehouses/{id}` | Cookie | Tenant | `Viewer`+ | Get single warehouse with 404 masking |
| **Warehouses** | `PATCH` | `/api/v1/warehouses/{id}` | Cookie | Tenant | `OpsManager`+ | Update warehouse with capacity validation |
| **Ports** | `GET` | `/api/v1/ports` | Cookie | Global | `Viewer`+ | List global reference ports (no org filtering) |
| **Ports** | `GET` | `/api/v1/ports/{id}` | Cookie | Global | `Viewer`+ | Get single global reference port |
| **Carriers** | `GET` | `/api/v1/carriers` | Cookie | Tenant | `Viewer`+ | List carriers with pagination, search, filter, sort |
| **Carriers** | `POST` | `/api/v1/carriers` | Cookie | Tenant | `OpsManager`+ | Create carrier within tenant boundary |
| **Carriers** | `GET` | `/api/v1/carriers/{id}` | Cookie | Tenant | `Viewer`+ | Get single carrier with 404 masking |
| **Carriers** | `PATCH` | `/api/v1/carriers/{id}` | Cookie | Tenant | `OpsManager`+ | Update carrier attributes |
| **Products** | `GET` | `/api/v1/products` | Cookie | Tenant | `Viewer`+ | List products with pagination, search, filter, sort |
| **Products** | `POST` | `/api/v1/products` | Cookie | Tenant | `OpsManager`+ | Create product with unique tenant SKU |
| **Products** | `GET` | `/api/v1/products/{id}` | Cookie | Tenant | `Viewer`+ | Get single product with 404 masking |
| **Products** | `PATCH` | `/api/v1/products/{id}` | Cookie | Tenant | `OpsManager`+ | Update product details |
| **Routes** | `GET` | `/api/v1/routes` | Cookie | Tenant | `Viewer`+ | List routes with pagination, search, filter, sort |
| **Routes** | `POST` | `/api/v1/routes` | Cookie | Tenant | `OpsManager`+ | Create shipping route corridor |
| **Routes** | `GET` | `/api/v1/routes/{id}` | Cookie | Tenant | `Viewer`+ | Get single route with 404 masking |
| **Routes** | `PATCH` | `/api/v1/routes/{id}` | Cookie | Tenant | `OpsManager`+ | Update route details |
| **Shipments** | `GET` | `/api/v1/shipments` | Cookie | Tenant | `Viewer`+ | List shipments with pagination, search, filter, sort |
| **Shipments** | `POST` | `/api/v1/shipments` | Cookie | Tenant | `OpsManager`+ | Create shipment with relationship validation |
| **Shipments** | `GET` | `/api/v1/shipments/{id}` | Cookie | Tenant | `Viewer`+ | Get single shipment with 404 masking |
| **Shipments** | `PATCH` | `/api/v1/shipments/{id}` | Cookie | Tenant | `OpsManager`+ | Update shipment status and operational metrics |
| **Shipments** | `GET` | `/api/v1/shipments/{id}/events` | Cookie | Tenant | `Viewer`+ | List all telemetry events for a shipment |
| **Shipment Events** | `GET` | `/api/v1/shipment-events` | Cookie | Tenant | `Viewer`+ | List telemetry events for tenant shipments |
| **Shipment Events** | `POST` | `/api/v1/shipment-events` | Cookie | Tenant | `OpsManager`+ | Append immutable telemetry event to shipment |
| **Shipment Events** | `GET` | `/api/v1/shipment-events/{id}` | Cookie | Tenant | `Viewer`+ | Get single telemetry event with 404 masking |

---

## 3. Authentication & RBAC Governance

### Authentication
All logistics endpoints require a valid session established during Phase 3 Google OAuth authentication. The session ID is transmitted via the secure `riskwise_session` HTTP-only cookie and validated against the session cache.
- **Unauthenticated Requests:** Return `401 Unauthorized`.

### Role-Based Access Control (RBAC)
Authorization is enforced via `require_role(*allowed_roles)`:
- **`Viewer` / `Analyst`:** Read-only access (`GET`).
- **`OpsManager` / `RiskManager` / `Admin`:** Operational mutations (`POST`, `PATCH`).
- **Forbidden Mutations:** Returning `403 Forbidden` if an unauthorized role (e.g. `Viewer`) attempts a write operation.

---

## 4. Multi-Tenant Isolation & 404 Masking Strategy

### Tenant Boundary Enforcement
- **Zero Client-Side Tenancy:** Request payloads and URL parameters are strictly forbidden from specifying `org_id` (`extra = "forbid"` returns `422 Unprocessable Entity`).
- **Server-Controlled Boundary:** The tenant boundary is unconditionally derived from `context.organization_id`.
- **404 Masking:** To prevent competitor discovery and ID enumeration attacks, any request for an entity belonging to another tenant returns `404 Not Found` (never `403 Forbidden`).
- **Cross-Tenant Relationship Protection:**
  - `SupplierSite.supplier_id` must reference a supplier owned by the authenticated tenant.
  - `Shipment` references (`carrier_id`, `product_id`, `route_id`) must belong to the authenticated tenant.
  - `ShipmentEvent.shipment_id` must belong to a shipment owned by the authenticated tenant.
  - Referencing a cross-tenant resource raises `NotFoundError` (404 masked).

---

## 5. Domain Resource Details

### Supplier Sites (`supplier_sites`)
- Validates parent `supplier_id` ownership within the tenant.
- Validates coordinates: latitude $[-90.0, 90.0]$, longitude $[-180.0, 180.0]$.
- Supported site statuses: `OPERATIONAL`, `DISRUPTED`, `OFFLINE`, `MAINTENANCE`.

### Factories (`factories`)
- Tracks production capacity and percentage utilization ($[0.0, 100.0]$).
- Enforces unique factory `code` within the tenant (raises `409 Conflict` `FACTORY_CODE_EXISTS`).

### Warehouses (`warehouses`)
- Validates capacity: `current_occupancy` cannot exceed `total_capacity`. Raises `400 Bad Request` with `OCCUPANCY_EXCEEDS_CAPACITY`.
- Enforces unique warehouse `code` within the tenant (`409 Conflict` `WAREHOUSE_CODE_EXISTS`).

### Ports (`ports`)
- Classified as `GLOBAL` reference data in `app/repositories/query_utils.py`.
- Shared catalog of UN/LOCODE sea, air, and inland terminals.
- No `org_id` column in PostgreSQL schema; tenant filtering is intentionally bypassed for ports.
- Read-only (`GET` only). Normal tenants cannot mutate global reference data (`POST`/`PATCH`/`DELETE` return `405 Method Not Allowed`).

### Carriers (`carriers`)
- Tracks transport mode (`OCEAN`, `AIR`, `ROAD`, `RAIL`) and `on_time_reliability` ($[0.0, 100.0]$).
- Enforces unique carrier `code` within the tenant (`409 Conflict` `CARRIER_CODE_EXISTS`).

### Products (`products`)
- Enforces unique `sku` within the tenant organization. Duplicate SKU on creation or update returns `409 Conflict` `PRODUCT_SKU_EXISTS`.
- Unit cost and ISO currency code tracking.

### Routes (`routes`)
- Defined transport corridors with `distance_km`, `standard_lead_time_days`, and `risk_score` ($[0.0, 100.0]$).
- Waypoints stored as JSON structure.
- **Polymorphic Reference Note:** `origin_facility_id` and `destination_facility_id` are polymorphic string identifiers in PostgreSQL Phase 2 without direct foreign key constraints (allowing references across factories, warehouses, ports, or supplier sites).

### Shipments (`shipments`)
- Mandatory unique `tracking_number` per tenant (`409 Conflict` `TRACKING_NUMBER_EXISTS`).
- Validates that referenced `carrier_id`, `product_id`, and `route_id` exist and belong to the authenticated organization.
- **Status State Machine:** Terminal states (`DELIVERED`, `CANCELLED`) cannot transition backwards to active operational states (`PLANNED`, `IN_TRANSIT`). Illegal transitions raise `LifecycleStateError` (`409 Conflict` `ILLEGAL_STATUS_TRANSITION`).
- Sub-resource `GET /api/v1/shipments/{id}/events` retrieves chronological milestone telemetry for that shipment.

### Shipment Events (`shipment_events`)
- Telemetry milestones (departure, arrival, customs checkpoint, delay notification).
- **Append-Only Telemetry:** Records are strictly immutable. No `PATCH` or `DELETE` endpoints are exposed (`405 Method Not Allowed`).
- Derived tenancy: Authorization is enforced through the parent `Shipment.org_id`. Attempting to log an event against another tenant's shipment returns `404 Not Found` (masked).

---

## 6. Query Infrastructure: Search, Filter, Sort & Pagination

### Search
- Search is executed via safe `ILIKE` substring matching.
- Special SQL wildcards (`%`, `_`, `\`) are safely escaped before statement generation to prevent table-scan resource exhaustion or information leakage.

### Filtering
- Strict allowlist filtering per resource. Any client-supplied query parameter not recognized or not in the allowlist raises `400 Bad Request` with `INVALID_FILTER_FIELD`.
- Date range filtering supported on timestamp columns with `_after` and `_before` suffixes.

### Sorting
- Strict sort allowlist per resource.
- Syntax: `sort=field` (ascending) or `sort=-field` (descending).
- Unknown sort columns receive `400 Bad Request` with `INVALID_SORT_FIELD`.

### Pagination
- Uniform 1-indexed pagination (`page >= 1`, `1 <= limit <= 100`).
- Enclosed in `PaginatedResponse[T]` containing items list and pagination metadata (`total`, `page`, `limit`, `pages`).

---

## 7. Transactions, Concurrency & Audit Logging

### Unit of Work Pattern
All multi-step operations execute within atomic transactions via `UnitOfWork`:
```python
with self.uow:
    self.uow.shipments.create(shipment, auto_commit=False)
    AuditService.log_event(..., auto_commit=False)
    self.uow.commit()
```
Exceptions during execution trigger an automatic rollback, preventing partial or dirty state commits.

### Audit Trail
Every mutating operation (`CREATE`, `UPDATE`) records an immutable event in `audit_logs`:
- Actor ID (`context.user_id`)
- Action verb (`CREATE`, `UPDATE`)
- Resource type and Resource ID
- Tenant organization ID
- Before and after state JSON diffs
- Sensitive secrets or session tokens are never logged.

---

## 8. Automated Test Coverage & Verification

### Test Suite Summary
- **Baseline Test Suite:** 155 tests (154 passed, 1 skipped)
- **New Logistics API Tests:** 35 comprehensive tests in `api/tests/test_logistics_api.py`
- **Total Test Suite:** 190 tests
- **Results:**
  - **189 Passed**
  - **1 Skipped** (live RDS guard)
  - **0 Failed**

### Key Test Categories Verified
1. **Authentication:** Unauthenticated calls to all 9 logistics endpoints return 401.
2. **Authorization:** Viewer role attempting mutation returns 403; OpsManager/Admin succeeds.
3. **Tenant Isolation:** Cross-tenant GET returns 404 masked; cross-tenant PATCH returns 404 masked.
4. **Relationship Validation:** Cross-tenant relationship references (shipment carrier, supplier site parent) return 404 masked.
5. **Input Validation:** Enum validation (422), forbidden extra fields (422), pagination limits (422).
6. **Security Guards:** Client-supplied `org_id` and server-controlled fields (`id`, `created_at`) rejected with 422.
7. **Query Safety:** Invalid sort fields return 400 (`INVALID_SORT_FIELD`); invalid filter fields return 400 (`INVALID_FILTER_FIELD`); SQL wildcards (`%`, `_`) safely escaped.
8. **Lifecycle & Immutability:** Operational resources and append-only telemetry reject `DELETE` with 405 Method Not Allowed; shipment events reject `PATCH` with 405; invalid shipment status transitions from terminal state rejected with 409.
9. **Transactions & Audit:** Failed mutations roll back cleanly with zero dirty records; successful mutations emit structured audit logs.
10. **OpenAPI Specification:** Generated schema contains zero duplicate operation IDs across all 48 operations.

---

## 9. Schema Discoveries & Limitations

1. **Polymorphic Route Facilities:**
   - In `routes`, `origin_facility_id` and `destination_facility_id` are plain string columns without database foreign key constraints. This supports multi-modal network topology connecting ports, supplier sites, factories, or warehouses without schema rigidness. Service layer validates format and basic existence where possible.
2. **Shipment Events Tenant Ownership:**
   - In `shipment_events`, there is no `org_id` column. Tenant scoping is strictly enforced hierarchically via `shipments.org_id`.
3. **Ports Reference Catalog:**
   - In `ports`, there is no `org_id` column. Classified as `GLOBAL` reference data accessible read-only across all tenants.
