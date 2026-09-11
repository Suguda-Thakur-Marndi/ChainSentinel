# RiskWise 2.0 — Inventory API Implementation Report

**Document Version:** 1.0.0  
**Status:** IMPLEMENTED & VALIDATED  
**Phase:** Phase 4 — Core APIs (Step 5 — Inventory APIs)  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Executive Summary & Scope Boundary

In Phase 4 Step 5, production Inventory APIs were implemented strictly covering the two core inventory resources approved in the Core API Contract (`docs/core-api-contract.md`):

1. **`inventory`** (`Inventory` model, `inventory` table) — Organization-scoped stock balances, safety stock thresholds, reorder points, and days-of-supply tracking.
2. **`inventory_movements`** (`InventoryMovement` model, `inventory_movements` table) — Organization-scoped, append-only immutable audit ledger recording stock receipts, shipments, adjustments, and internal transfers.

### Strict Scope Boundary Adherence
- **Zero Database / DDL Alterations:** Utilized existing PostgreSQL schema created in Phase 2 without adding, altering, or removing columns, constraints, or tables. Zero migrations generated.
- **Zero Out-of-Scope Modules:** No implementation of future Step 6 Risk APIs, Risk Engine, Risk Factors, Risk Assessments, Incidents, Predictions, Scenarios, Simulations, Recommendations, AI Agents, or external sensor feeds.

---

## 2. Production Endpoints Matrix

| Resource | HTTP Method | Path | Auth | Scope | Roles | Description / Invariants |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Inventory** | `GET` | `/api/v1/inventory` | Cookie | Tenant | `Viewer`+ | List inventory records with pagination, search, filter, and sort |
| **Inventory** | `POST` | `/api/v1/inventory` | Cookie | Tenant | `OpsManager`+ | Create facility-level stock record with product & facility tenant verification |
| **Inventory** | `GET` | `/api/v1/inventory/{id}` | Cookie | Tenant | `Viewer`+ | Retrieve individual inventory record with 404 masking |
| **Inventory** | `PATCH` | `/api/v1/inventory/{id}` | Cookie | Tenant | `OpsManager`+ | Update stock levels and thresholds with audit logging |
| **Inventory Movements** | `GET` | `/api/v1/inventory-movements` | Cookie | Tenant | `Viewer`+ | List stock movement ledger entries with pagination, search, filter, sort |
| **Inventory Movements** | `POST` | `/api/v1/inventory-movements` | Cookie | Tenant | `OpsManager`+ | Append immutable ledger record with atomic stock reconciliation |
| **Inventory Movements** | `GET` | `/api/v1/inventory-movements/{id}` | Cookie | Tenant | `Viewer`+ | Retrieve individual ledger entry with 404 masking |

---

## 3. Authentication & RBAC Governance

### Authentication
All inventory endpoints require a validated session established during Phase 3 Google OAuth authentication. The session ID is transmitted via the secure `riskwise_session` HTTP-only cookie and validated against the session cache (`SessionService`).
- **Unauthenticated Requests:** Return `401 Unauthorized` with JSON error envelope.

### Role-Based Access Control (RBAC)
Authorization is enforced through `require_role(*allowed_roles)`:
- **`Viewer` / `Analyst`:** Read-only access (`GET /api/v1/inventory`, `GET /api/v1/inventory-movements`).
- **`OpsManager` / `RiskManager` / `Admin`:** Mutation permissions (`POST`, `PATCH`).
- **Forbidden Mutations:** If a `Viewer` or `Analyst` attempts any mutation (`POST /api/v1/inventory`, `PATCH /api/v1/inventory/{id}`, `POST /api/v1/inventory-movements`), the request is immediately rejected with `403 Forbidden` (`FORBIDDEN_MUTATION`).

---

## 4. Multi-Tenant Isolation & 404 Masking Strategy

### Tenant Boundary Enforcement
- **Zero Client-Side Tenancy:** Request payloads and URL parameters are strictly forbidden from supplying `org_id` (`extra = "forbid"` returns `422 Unprocessable Entity`).
- **Server-Controlled Boundary:** The tenant boundary is unconditionally derived from `context.organization_id`.
- **404 Masking Strategy:** Requests attempting to access or modify records belonging to another tenant return `404 Not Found` with `RESOURCE_NOT_FOUND` to prevent competitor data enumeration.
- **Cross-Tenant Relationship Protection:**
  - `Inventory.product_id` must reference a product belonging to the authenticated tenant.
  - `Inventory.facility_id` must reference a factory or warehouse belonging to the authenticated tenant.
  - `InventoryMovement.product_id` must reference a tenant-owned product.
  - `InventoryMovement.reference_id` when pointing to an inventory record must belong to the authenticated tenant.
  - Cross-tenant references fail safely with `404 Not Found` (masked).

---

## 5. Inventory Invariants & Business Logic

1. **Non-Negative Stock Invariant:**
   - `quantity_on_hand` cannot be negative at creation or update (`Field(..., ge=0.0)` returning `422 Unprocessable Entity` or `ValidationDomainError` with code `INVALID_QUANTITY`).
   - `safety_stock`, `reorder_point`, and `days_of_supply` must be non-negative values.
2. **Lifecycle State Invariants:**
   - Hard `DELETE` is not exposed on `/api/v1/inventory/{id}` and `/api/v1/inventory` (returns `405 Method Not Allowed`).
3. **Movement Quantity Invariant:**
   - Stock movements cannot have `quantity == 0` (raises `400 Bad Request` with `INVALID_QUANTITY`).

---

## 6. Append-Only Ledger & Movement Immutability

1. **Immutable Ledger Design:**
   - `InventoryMovement` models transactional telemetry and audit history of stock receipts, transfers, adjustments, and shipments.
   - Once written, records in `inventory_movements` cannot be updated or deleted.
2. **Endpoint Immutability:**
   - No `PATCH` or `DELETE` endpoints are registered on `/api/v1/inventory-movements` or `/api/v1/inventory-movements/{id}`.
   - HTTP `PATCH` and `DELETE` requests automatically return `405 Method Not Allowed`.
   - Domain service methods `update_movement` and `delete_movement` explicitly raise `ImmutableResourceError`.

---

## 7. Concurrency Control & Atomic Stock Reconciliation

### Pessimistic Row Locking & Atomic Adjustment
To prevent concurrent race conditions, lost updates, and inventory drift:
1. **Row-Level Locking:**
   - `InventoryRepository.get_for_update` executes `SELECT ... FOR UPDATE` via `get_with_for_update` within the active `UnitOfWork` transaction.
2. **Atomic In-Database Adjustment:**
   - `InventoryRepository.adjust_stock` uses `atomic_adjust_numeric` to execute direct atomic SQL updates:
     ```sql
     UPDATE inventory
     SET quantity_on_hand = quantity_on_hand + :delta, updated_at = :now
     WHERE id = :id AND org_id = :org_id AND (quantity_on_hand + :delta >= 0);
     ```
3. **Atomic Movement Reconciliations:**
   - When a stock movement specifies a `reference_id` pointing to an inventory record:
     - `RECEIPT` movements automatically increase stock by `+abs(quantity)`.
     - `SHIPMENT` movements deduct stock by `-abs(quantity)`.
     - Generic adjustments adjust by `quantity`.
   - If the resulting balance would drop below zero, the transaction is rejected and rolled back with `400 Bad Request` (`INSUFFICIENT_INVENTORY`), preventing inventory deficits.

---

## 8. Safe Query Filtering, Sorting & Search

All query parameters are strictly validated against repository allowlists to eliminate SQL injection and unauthorized data leakage.

### Inventory Allowlist Configuration
- **Search Columns:** `["product_id", "facility_id"]` (SQL wildcards `%` and `_` safely escaped).
- **Sort Allowlist:** `quantity_on_hand`, `days_of_supply`, `safety_stock`, `reorder_point`, `created_at`, `updated_at`.
- **Filter Allowlist:** `product_id`, `facility_id`, `created_at_after`, `created_at_before`.

### Inventory Movement Allowlist Configuration
- **Search Columns:** `["reference_id", "from_location", "to_location"]`.
- **Sort Allowlist:** `timestamp`, `quantity`.
- **Filter Allowlist:** `product_id`, `movement_type`, `reference_id`, `timestamp_after`, `timestamp_before`.

Attempting to pass unapproved filter or sort fields returns `400 Bad Request` (`INVALID_FILTER_FIELD` or `INVALID_SORT_FIELD`).

---

## 9. Audit Logging Strategy

State-changing operations are logged using the centralized `AuditService.log_event` inside the active `UnitOfWork` transaction boundary:
- **`Inventory` CREATE:** Emits `AuditLog` record with `action="CREATE"`, `resource_type="Inventory"`, actor UUID, and sanitized entity payload.
- **`Inventory` UPDATE:** Emits `AuditLog` record with `action="UPDATE"`, `resource_type="Inventory"`, diff tracking `before_data` and `after_data`.
- **`InventoryMovement` CREATE:** Emits `AuditLog` record with `action="CREATE"`, `resource_type="InventoryMovement"`, timestamp, actor UUID, and movement details.
- **Credential Scrubbing & Type Safety:** `sanitize_payload` automatically redacts sensitive tokens and serializes `datetime`/`date` objects to ISO 8601 strings.

---

## 10. Comprehensive Test Coverage & Validation Results

A dedicated test suite was built in `api/tests/test_inventory_api.py` covering all 22 required test cases:

```
api/tests/test_inventory_api.py::test_1_authentication_required PASSED
api/tests/test_inventory_api.py::test_2_rbac_enforcement PASSED
api/tests/test_inventory_api.py::test_3_organization_isolation PASSED
api/tests/test_inventory_api.py::test_4_cross_tenant_product_rejection PASSED
api/tests/test_inventory_api.py::test_5_cross_tenant_facility_rejection PASSED
api/tests/test_inventory_api.py::test_6_inventory_creation PASSED
api/tests/test_inventory_api.py::test_7_inventory_retrieval PASSED
api/tests/test_inventory_api.py::test_8_inventory_listing PASSED
api/tests/test_inventory_api.py::test_9_pagination_validation PASSED
api/tests/test_inventory_api.py::test_10_filtering PASSED
api/tests/test_inventory_api.py::test_11_sorting_and_invalid_sort PASSED
api/tests/test_inventory_api.py::test_12_search_and_wildcard_escaping PASSED
api/tests/test_inventory_api.py::test_13_update_behavior PASSED
api/tests/test_inventory_api.py::test_14_server_controlled_field_injection PASSED
api/tests/test_inventory_api.py::test_15_invalid_quantity_handling PASSED
api/tests/test_inventory_api.py::test_16_inventory_movement_creation_and_reconciliation PASSED
api/tests/test_inventory_api.py::test_17_movement_cross_tenant_reference_rejection PASSED
api/tests/test_inventory_api.py::test_18_append_only_and_immutability_rules PASSED
api/tests/test_inventory_api.py::test_19_insufficient_stock_protection PASSED
api/tests/test_inventory_api.py::test_20_audit_logging_behavior PASSED
api/tests/test_inventory_api.py::test_21_standardized_error_envelope PASSED
api/tests/test_inventory_api.py::test_22_openapi_route_registration_and_uniqueness PASSED
```

### Full Regression Suite Results
Running the complete test suite across all Phase 1-4 modules:
- **Total Tests:** 212 tests.
- **Results:** 211 passed, 1 skipped (live RDS network probe skip guard).
- **New Failures:** 0.

### OpenAPI Specification Validation
- **Total Endpoints Registered:** 35.
- **Total HTTP Operations:** 55.
- **Duplicate Operation IDs:** 0 (all operation IDs globally unique).
