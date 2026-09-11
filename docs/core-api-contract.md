# RiskWise 2.0 Core API Contract & Resource Design

**Document Version:** 2.0.0  
**Status:** DESIGNED / APPROVED FOR IMPLEMENTATION  
**Phase:** Phase 4 — Core APIs (Step 1 — Core API Contract & Resource Design)  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Executive Summary & Design Principles

The RiskWise 2.0 Core API Contract provides a strictly typed, multi-tenant, role-governed REST API designed to power real-time supply chain risk intelligence, predictive tracking, multi-agent autonomous investigations, digital twin graphs, and human-in-the-loop governance.

### Architectural Separation of Concerns
1. **HTTP Layer (`api/app/api/`):** FastAPI routers validate HTTP payloads, headers, query parameters, cookies, and enforce dependency injection (`AuthenticatedContext`, `require_role`).
2. **Contract / Schema Layer (`api/app/schemas/`):** Pydantic v2 schemas define strict request and response boundaries. Database models are **never** exposed directly over the wire. Server-controlled fields (`id`, `org_id`, `created_at`, `updated_at`) are strictly forbidden in client write requests (`extra = "forbid"`).
3. **Service Layer (`api/app/services/`):** Encapsulates business validation, workflow orchestration, audit logging, transaction boundaries, and state machines.
4. **Data Access Layer (`api/app/repositories/`):** Executes scoped queries against SQLAlchemy 2.0 sessions, applying mandatory tenant isolation predicates (`org_id == context.organization_id`).
5. **Database Layer (`api/app/models/`):** 34 authoritative PostgreSQL tables established in Phase 2.

---

## 2. API Base Path & Conventions

### Base Path
All business endpoints are mounted under the versioned prefix:
```
/api/v1
```

### URL Naming Conventions
- Resources use kebab-case plural nouns (e.g., `/api/v1/supplier-sites`, `/api/v1/shipment-events`, `/api/v1/twin-nodes`).
- Nested child entities may be accessed directly with filtering or via parent sub-paths:
  - Direct collection with parent filter: `GET /api/v1/shipment-events?shipment_id={id}`
  - Nested sub-resource: `GET /api/v1/shipments/{id}/events`
- RPC / State machine transitions use verb suffixes on specific resource identifiers:
  - `POST /api/v1/recommendations/{id}/approve`
  - `POST /api/v1/actions/{id}/execute`
  - `POST /api/v1/scenarios/{id}/simulate`

### Public Endpoints (No Authentication Required)
- `GET /` — API metadata and version
- `GET /health` — Application liveness check
- `GET /api/v1/health` — API v1 liveness check
- `GET /api/v1/health/db` — RDS PostgreSQL readiness probe
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc documentation
- `GET /openapi.json` — OpenAPI 3.1 specification schema
- `GET /api/v1/auth/google` — Google OAuth 2.0 initiation endpoint
- `GET /api/v1/auth/google/callback` — Google OAuth 2.0 callback and session creation

---

## 3. Authentication Architecture

All core business endpoints require an active, validated RiskWise application session established during the Phase 3 Google OAuth 2.0 authentication flow.

### Session Cookie Transmission
- **Cookie Name:** `riskwise_session`
- **Security Flags:**
  - `HttpOnly`: True (prevents JavaScript access and XSS theft)
  - `Secure`: True in production environments (HTTPS only)
  - `SameSite`: `Lax` (protects against CSRF attacks while allowing top-level navigation)
  - `Max-Age`: 604,800 seconds (7 days)

### Dependency Gatekeeper
FastAPI dependency injection enforces session validation via `get_authenticated_context`:
```python
@router.get("/api/v1/suppliers", response_model=SupplierListResponse)
def list_suppliers(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    params: PaginationParams = Depends(),
    db: Session = Depends(get_db),
):
    ...
```

`AuthenticatedContext` yields:
- `context.user`: Active SQLAlchemy `User` record
- `context.organization`: Active SQLAlchemy `Organization` record
- `context.user_id`: Authenticated user UUID string
- `context.organization_id`: Tenant UUID string boundary
- `context.role`: Assigned RBAC role string (`Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin`)

---

## 4. Authorization & RBAC Matrix

Role-based access control is enforced via the `require_role(*allowed_roles)` dependency decorator. The RiskWise domain defines 5 hierarchical user roles:

| Role | Scope & Permissions | Example Capabilities |
| :--- | :--- | :--- |
| **Viewer** | Read-only access to operational assets and intelligence | View suppliers, shipments, telemetry, digital twin, risks, incidents, and notification list. Cannot create or modify records. |
| **Analyst** | Read-write access to risk assessments, scenarios, simulations, and recommendations | All Viewer capabilities + create/update risks, launch what-if scenarios, trigger simulations, run optimization runs, and create mitigation proposals. |
| **OpsManager** | Operational management of supply chain entities | All Analyst capabilities + update supplier operational status, edit facility/warehouse capacities, manage carrier records, update shipments, log inventory movements. |
| **RiskManager** | Strategic governance, approval sign-off, action execution | All OpsManager capabilities + formal human-in-the-loop approval/rejection of mitigation recommendations, triggering operational actions, overriding risk assessments. |
| **Admin** | Tenant organization administration | All RiskManager capabilities + user invite/management, role updates, tenant settings updates, document indexing/deletion, compliance audit trail review. |

---

## 5. Multi-Tenancy & Data Isolation

Multi-tenancy is enforced at the database repository layer through mandatory organization scoping.

### Core Tenancy Principles
1. **Never Trust Client Organization Headers or Body Fields:** The client request body and query parameters are **never** permitted to specify `org_id`. Any `org_id` supplied in request payloads is rejected with `422 Unprocessable Entity` (`extra = "forbid"`).
2. **Strict Context Injection:** The tenant boundary is unconditionally determined by `context.organization_id` derived from the verified server-side session.
3. **Repository Predicates:** Every query against tenant-scoped tables must explicitly include `.filter(Model.org_id == context.organization_id)`.
4. **Cross-Tenant Information Masking:** If a user requests a specific resource ID (`GET /api/v1/suppliers/{id}`) that exists in another tenant's organization, the API returns `404 Not Found` (never `403 Forbidden`). This prevents ID enumeration attacks and competitor asset discovery.

### Scoping Classifications
- **Tenant-Owned Entities (23 Tables):** `users`, `suppliers`, `supplier_sites`, `factories`, `warehouses`, `carriers`, `products`, `routes`, `shipments`, `inventory`, `inventory_movements`, `risks`, `risk_assessments`, `incidents`, `twin_nodes`, `twin_edges`, `scenarios`, `optimization_runs`, `recommendations`, `actions`, `audit_logs`, `notifications`, `documents`.
- **Hierarchically Scoped Child Entities (7 Tables):** Scoped through foreign key join to parent tenant record:
  - `shipment_events` -> `shipment.org_id`
  - `risk_factors` -> `risk.org_id`
  - `simulations` -> `scenario.org_id`
  - `approvals` -> `recommendation.org_id`
  - `verification_results` -> `action.org_id`
  - `agent_tasks` -> `agent_run.org_id`
  - `agent_tool_calls` -> `agent_task.agent_run.org_id`
  - `document_chunks` -> `document.org_id`
- **Global Reference Entities (1 Table):** `ports` (UN/LOCODE shared transit hub catalog; read-only to all authenticated tenants).
- **Tenant Root (1 Table):** `organizations` (restricted to the tenant's own profile).

---

## 6. Standardized Error Contract

All error responses adhere to a consistent JSON envelope to ensure predictability for API clients:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "The requested supplier could not be found.",
    "details": {
      "resource_id": "sup_9b2e84c1"
    }
  }
}
```

### HTTP Status Code Matrix

| Status Code | Error Code | Description | Example Trigger |
| :--- | :--- | :--- | :--- |
| **400 Bad Request** | `BAD_REQUEST` / `INVALID_PARAMETER` | Malformed request or illegal query parameters | Invalid sort column `sort=non_existent_column` |
| **401 Unauthorized** | `UNAUTHORIZED` / `SESSION_EXPIRED` | Missing, invalid, or expired session cookie | Accessing business API without `riskwise_session` |
| **403 Forbidden** | `FORBIDDEN` / `INSUFFICIENT_PERMISSIONS` | Authenticated user lacks required role | `Viewer` attempting to execute `POST /api/v1/actions` |
| **404 Not Found** | `RESOURCE_NOT_FOUND` | Resource does not exist or belongs to another tenant | Querying unknown shipment ID or cross-tenant ID |
| **409 Conflict** | `CONFLICT` / `STATE_CONFLICT` | Operation conflicts with current resource state | Approving a recommendation that is already `APPROVED` |
| **422 Unprocessable Entity** | `VALIDATION_ERROR` | Schema validation failed | Submitting negative inventory quantity or invalid coordinates |
| **429 Too Many Requests** | `RATE_LIMITED` | Rate limit quota exceeded | AI agent task triggering excessive external tool queries |
| **500 Internal Server Error** | `INTERNAL_ERROR` | Unexpected server condition | Database connection timeout or unhandled exception |

### Information Sanitization Policy
- **No Stack Traces:** Stack traces and internal Python exception traces are never returned in HTTP responses.
- **No Raw SQL Leaks:** PostgreSQL syntax errors, constraint names, or table internals are intercepted and transformed into clean domain errors.
- **Zero Secret Exposure:** Credentials, OAuth secrets, database passwords, and internal infrastructure IPs are stripped before serialization.

---

## 7. Pagination, Filtering, Sorting & Search

### Standard Pagination Strategy
All collection endpoints implement uniform 1-indexed pagination via query parameters:
- `page`: Integer $\ge 1$ (default: `1`)
- `limit`: Integer between `1` and `100` (default: `20`, maximum: `100`)

#### Response Envelope:
```json
{
  "items": [ ... ],
  "pagination": {
    "total": 142,
    "page": 1,
    "limit": 20,
    "pages": 8
  }
}
```

### Filtering Standards
- Filtering is performed using exact matching or enum matching via query parameters:
  - `GET /api/v1/shipments?status=IN_TRANSIT&mode=OCEAN`
  - `GET /api/v1/risks?severity=HIGH&trend=INCREASING`
  - `GET /api/v1/suppliers?tier=CRITICAL&country=TW`
- Date range filtering is supported on timestamp columns using `_after` and `_before`:
  - `GET /api/v1/shipments?eta_after=2026-09-01T00:00:00Z&eta_before=2026-09-30T23:59:59Z`

### Sorting Standards
- Sorting is controlled via the `sort` query parameter:
  - Ascending: `sort=created_at` or `sort=+created_at`
  - Descending: `sort=-created_at`
- Each resource implements an explicit **Sort Allowlist**. Requests specifying columns outside the allowlist receive a `400 Bad Request` with `INVALID_SORT_FIELD`.

### Free-Text Search
- Resource endpoints support a `search` parameter that applies case-insensitive `ILIKE` pattern matching across primary descriptive attributes (e.g., `name`, `code`, `tracking_number`, `sku`, `title`).

---

## 8. State Transitions, Concurrency & Soft-Delete Strategy

### Soft-Delete vs Hard-Delete Policy
Inspection of the Phase 2 database schema confirms that operational entities do **not** possess `deleted_at` or `is_deleted` columns.
- **Network & Logistics Entities (`suppliers`, `shipments`, `inventory`):** Hard deletion is **disabled**. Resources participate in business lifecycle status transitions (e.g., `status = CANCELLED`, `status = OFFLINE`). DELETE endpoints are not exposed.
- **Scenarios, Digital Twin & Knowledge Entities (`scenarios`, `twin_nodes`, `twin_edges`, `documents`):** Hard deletion is permitted with cascade cleanup to child tables. Restricted to `Admin` and `RiskManager` roles.
- **Telemetry & Ledgers (`shipment_events`, `inventory_movements`, `audit_logs`, `verification_results`):** Strictly **immutable** append-only records. `UPDATE` and `DELETE` return `405 Method Not Allowed`.

### Concurrency Controls
1. **Inventory Reconciliation:** Stock level adjustments use atomic database expressions (`quantity_on_hand = quantity_on_hand + delta`) within explicit transaction blocks to eliminate race conditions.
2. **Recommendation Approvals:** State transition from `PENDING` to `APPROVED` or `REJECTED` evaluates current state under database row lock (`SELECT FOR UPDATE`) to prevent duplicate human sign-offs.
3. **Action Execution:** Actions implement idempotency checks using unique action IDs and status state machine verification (`PENDING` $\rightarrow$ `EXECUTING` $\rightarrow$ `COMPLETED`).

---

## 9. Comprehensive Resource Catalog

### 9.1 Organizations (`organizations`)
- **Purpose:** Multi-tenant organization profile and configuration boundary.
- **Scope:** Tenant Root.
- **Authentication:** Required (`riskwise_session`).
- **Roles:** Read: `Viewer`+, Update: `Admin`.
- **Create:** Managed during tenant provisioning / SSO sign-up.
- **Read:** `GET /api/v1/organizations/me` (returns current tenant profile).
- **List:** N/A (single-tenant isolation).
- **Update:** `PATCH /api/v1/organizations/me` (`name`, `slug`, `settings_json`).
- **Delete:** Unsupported via public API.
- **Filters:** None.
- **Sort:** None.
- **Notes:** Tenant can only view and update its own organization settings.

### 9.2 Users (`users`)
- **Purpose:** Team members, assigned RBAC roles, and activity status.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `Admin`.
- **Create:** `POST /api/v1/users` (invite user with initial role).
- **Read:** `GET /api/v1/users/{id}` (or `GET /api/v1/auth/me`).
- **List:** `GET /api/v1/users` (paginated team directory).
- **Update:** `PATCH /api/v1/users/{id}` (`full_name`, `role`, `is_active`).
- **Delete:** Unsupported; deactivation via `is_active = false`.
- **Filters:** `role`, `is_active`.
- **Sort:** `created_at`, `last_active_at`, `email`.
- **Notes:** Users cannot elevate their own roles.

### 9.3 Suppliers (`suppliers`)
- **Purpose:** Tier-1/Tier-2/Tier-3 component and material suppliers.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/suppliers`.
- **Read:** `GET /api/v1/suppliers/{id}`.
- **List:** `GET /api/v1/suppliers`.
- **Update:** `PATCH /api/v1/suppliers/{id}`.
- **Delete:** Unsupported; status managed via operational metadata.
- **Filters:** `tier`, `criticality`, `country`, `search`.
- **Sort:** `created_at`, `name`, `reliability_score`, `financial_exposure`.
- **Notes:** Reliability score ranges from 0 to 100.

### 9.4 Supplier Sites (`supplier_sites`)
- **Purpose:** Physical manufacturing and distribution facilities operated by suppliers.
- **Scope:** Organization-scoped (`org_id`), linked to `supplier_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/supplier-sites`.
- **Read:** `GET /api/v1/supplier-sites/{id}`.
- **List:** `GET /api/v1/supplier-sites`.
- **Update:** `PATCH /api/v1/supplier-sites/{id}`.
- **Delete:** Unsupported; status transition to `OFFLINE`.
- **Filters:** `supplier_id`, `status`, `country`, `site_type`.
- **Sort:** `created_at`, `name`, `capacity`.
- **Notes:** Coordinates validated within lat $[-90, 90]$ and lng $[-180, 180]$.

### 9.5 Factories (`factories`)
- **Purpose:** Internal or contract manufacturing production plants.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/factories`.
- **Read:** `GET /api/v1/factories/{id}`.
- **List:** `GET /api/v1/factories`.
- **Update:** `PATCH /api/v1/factories/{id}`.
- **Delete:** Unsupported; status transition to `MAINTENANCE` or `OFFLINE`.
- **Filters:** `status`, `country`, `search`.
- **Sort:** `created_at`, `name`, `utilization`.
- **Notes:** Utilization tracked as percentage (0–100%).

### 9.6 Warehouses (`warehouses`)
- **Purpose:** Storage, inventory hubs, and regional distribution centers.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/warehouses`.
- **Read:** `GET /api/v1/warehouses/{id}`.
- **List:** `GET /api/v1/warehouses`.
- **Update:** `PATCH /api/v1/warehouses/{id}`.
- **Delete:** Unsupported; status transition to `OFFLINE`.
- **Filters:** `status`, `country`, `search`.
- **Sort:** `created_at`, `name`, `total_capacity`, `current_occupancy`.
- **Notes:** `current_occupancy` cannot exceed `total_capacity`.

### 9.7 Ports (`ports`)
- **Purpose:** Global maritime, aviation, and inland trade choke point reference data.
- **Scope:** Global reference catalog (no `org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+.
- **Create:** Read-only reference data (managed by platform operations).
- **Read:** `GET /api/v1/ports/{id}`.
- **List:** `GET /api/v1/ports`.
- **Update:** Read-only to tenants.
- **Delete:** Read-only to tenants.
- **Filters:** `port_type`, `country`, `search`.
- **Sort:** `name`, `congestion_score`, `average_wait_hours`.
- **Notes:** Identified by UN/LOCODE standard where available.

### 9.8 Carriers (`carriers`)
- **Purpose:** Logistics freight providers, shipping lines, and airlines.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/carriers`.
- **Read:** `GET /api/v1/carriers/{id}`.
- **List:** `GET /api/v1/carriers`.
- **Update:** `PATCH /api/v1/carriers/{id}`.
- **Delete:** Unsupported.
- **Filters:** `mode`, `search`.
- **Sort:** `created_at`, `name`, `on_time_reliability`.
- **Notes:** On-time reliability scored 0–100%.

### 9.9 Products (`products`)
- **Purpose:** Finished goods and bill-of-materials components.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/products`.
- **Read:** `GET /api/v1/products/{id}`.
- **List:** `GET /api/v1/products`.
- **Update:** `PATCH /api/v1/products/{id}`.
- **Delete:** Unsupported.
- **Filters:** `category`, `currency`, `search`.
- **Sort:** `created_at`, `sku`, `name`, `unit_cost`.
- **Notes:** SKU is unique per organization.

### 9.10 Routes (`routes`)
- **Purpose:** Defined transport corridors between facilities with lead-time baselines.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/routes`.
- **Read:** `GET /api/v1/routes/{id}`.
- **List:** `GET /api/v1/routes`.
- **Update:** `PATCH /api/v1/routes/{id}`.
- **Delete:** Supported for unused routes (`Admin` / `OpsManager`).
- **Filters:** `mode`, `origin_facility_id`, `destination_facility_id`.
- **Sort:** `created_at`, `name`, `distance_km`, `risk_score`.
- **Notes:** Waypoints serialized in `waypoints_json`.

### 9.11 Shipments (`shipments`)
- **Purpose:** Real-time consignment tracking across global trade lanes.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/shipments`.
- **Read:** `GET /api/v1/shipments/{id}`.
- **List:** `GET /api/v1/shipments`.
- **Update:** `PATCH /api/v1/shipments/{id}` (status, ETA, route, carrier).
- **Delete:** Unsupported; lifecycle managed via status (`CANCELLED`, `DELIVERED`).
- **Filters:** `status`, `mode`, `carrier_id`, `product_id`, `data_provenance`, `search`.
- **Sort:** `created_at`, `tracking_number`, `eta`, `delay_minutes`.
- **Notes:** Data provenance indicates `REAL`, `SYNTHETIC`, or `ESTIMATED`.

### 9.12 Shipment Events (`shipment_events`)
- **Purpose:** Telemetry milestones, AIS vessel pings, and waypoint event stream.
- **Scope:** Child entity scoped via parent `shipment_id` (`shipment.org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `OpsManager`+ / Ingestion Service.
- **Create:** `POST /api/v1/shipment-events`.
- **Read:** `GET /api/v1/shipment-events/{id}`.
- **List:** `GET /api/v1/shipment-events?shipment_id={id}`.
- **Update:** Immutable (405 Method Not Allowed).
- **Delete:** Immutable (405 Method Not Allowed).
- **Filters:** `shipment_id`, `event_type`, `source_type`.
- **Sort:** `timestamp`, `created_at`.
- **Notes:** Append-only event store.

### 9.13 Inventory (`inventory`)
- **Purpose:** Facility-level stock levels, reorder points, and days-of-supply.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `OpsManager`+.
- **Create:** `POST /api/v1/inventory`.
- **Read:** `GET /api/v1/inventory/{id}`.
- **List:** `GET /api/v1/inventory`.
- **Update:** `PATCH /api/v1/inventory/{id}` (reconciliation adjustments).
- **Delete:** Unsupported.
- **Filters:** `product_id`, `facility_id`.
- **Sort:** `created_at`, `quantity_on_hand`, `days_of_supply`.
- **Notes:** Atomic transactional updates prevent concurrent drift.

### 9.14 Inventory Movements (`inventory_movements`)
- **Purpose:** Audit ledger of stock receipts, transfers, and consumption.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `OpsManager`+.
- **Create:** `POST /api/v1/inventory-movements`.
- **Read:** `GET /api/v1/inventory-movements/{id}`.
- **List:** `GET /api/v1/inventory-movements`.
- **Update:** Immutable (405 Method Not Allowed).
- **Delete:** Immutable (405 Method Not Allowed).
- **Filters:** `product_id`, `movement_type`.
- **Sort:** `timestamp`, `quantity`.
- **Notes:** Append-only transaction ledger.

### 9.15 Risks (`risks`)
- **Purpose:** Identified geopolitical, climatic, supplier, or lane risk entities.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `Analyst`+.
- **Create:** `POST /api/v1/risks`.
- **Read:** `GET /api/v1/risks/{id}`.
- **List:** `GET /api/v1/risks`.
- **Update:** `PATCH /api/v1/risks/{id}`.
- **Delete:** Unsupported; archived via trend/severity status.
- **Filters:** `severity`, `trend`, `risk_type`, `search`.
- **Sort:** `detected_at`, `risk_score`, `impact`, `probability`.
- **Notes:** Risk scores computed on 0–100 scale.

### 9.16 Risk Factors (`risk_factors`)
- **Purpose:** Causal drivers contributing to a composite risk score.
- **Scope:** Child entity scoped via parent `risk_id` (`risk.org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `Analyst`+.
- **Create:** `POST /api/v1/risk-factors`.
- **Read:** `GET /api/v1/risk-factors/{id}`.
- **List:** `GET /api/v1/risk-factors?risk_id={id}`.
- **Update:** `PATCH /api/v1/risk-factors/{id}`.
- **Delete:** Supported for obsolete factors (`Analyst`+).
- **Filters:** `risk_id`, `category`.
- **Sort:** `created_at`, `score`, `weight`.
- **Notes:** Evidence captured in `evidence_json`.

### 9.17 Risk Assessments (`risk_assessments`)
- **Purpose:** Evaluation run analyzing a risk by AI agents or human analysts.
- **Scope:** Organization-scoped (`org_id`), linked to `risk_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `Analyst`+ / AI pipeline.
- **Create:** `POST /api/v1/risk-assessments`.
- **Read:** `GET /api/v1/risk-assessments/{id}`.
- **List:** `GET /api/v1/risk-assessments`.
- **Update:** Immutable evaluation record.
- **Delete:** Unsupported.
- **Filters:** `risk_id`, `assessor_type`.
- **Sort:** `created_at`, `score`, `confidence`.
- **Notes:** Findings recorded in structured JSON format.

### 9.18 Incidents (`incidents`)
- **Purpose:** Realized disruptions actively investigated or mitigated.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update: `Analyst`+.
- **Create:** `POST /api/v1/incidents`.
- **Read:** `GET /api/v1/incidents/{id}`.
- **List:** `GET /api/v1/incidents`.
- **Update:** `PATCH /api/v1/incidents/{id}` (status, severity, resolution).
- **Delete:** Unsupported; resolved through lifecycle (`RESOLVED`, `CLOSED`).
- **Filters:** `status`, `severity`, `risk_id`, `search`.
- **Sort:** `detected_at`, `severity`, `title`.
- **Notes:** Affected asset IDs tracked in `affected_assets` array.

### 9.19 Digital Twin Nodes (`twin_nodes`)
- **Purpose:** Graph vertices representing network nodes in digital twin topology.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update/Delete: `OpsManager`+.
- **Create:** `POST /api/v1/twin-nodes`.
- **Read:** `GET /api/v1/twin-nodes/{id}`.
- **List:** `GET /api/v1/twin-nodes`.
- **Update:** `PATCH /api/v1/twin-nodes/{id}`.
- **Delete:** `DELETE /api/v1/twin-nodes/{id}` (cascades incident edge cleanup).
- **Filters:** `node_type`, `search`.
- **Sort:** `label`, `health_score`.
- **Notes:** Links to physical entity via `entity_id`.

### 9.20 Digital Twin Edges (`twin_edges`)
- **Purpose:** Graph connections representing flow, transport, or dependencies.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update/Delete: `OpsManager`+.
- **Create:** `POST /api/v1/twin-edges`.
- **Read:** `GET /api/v1/twin-edges/{id}`.
- **List:** `GET /api/v1/twin-edges`.
- **Update:** `PATCH /api/v1/twin-edges/{id}`.
- **Delete:** `DELETE /api/v1/twin-edges/{id}`.
- **Filters:** `edge_type`, `from_node_id`, `to_node_id`.
- **Sort:** `flow_capacity`, `risk_score`.
- **Notes:** Validates that both endpoints belong to the tenant's digital twin.

### 9.21 Scenarios (`scenarios`)
- **Purpose:** What-if simulation hypotheses (e.g. port closure, supplier outage).
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Update/Delete: `Analyst`+.
- **Create:** `POST /api/v1/scenarios`.
- **Read:** `GET /api/v1/scenarios/{id}`.
- **List:** `GET /api/v1/scenarios`.
- **Update:** `PATCH /api/v1/scenarios/{id}`.
- **Delete:** `DELETE /api/v1/scenarios/{id}` (cascades simulations).
- **Filters:** `created_by_user_id`, `search`.
- **Sort:** `created_at`, `name`.
- **Notes:** Input parameters defined in `variables_json`.

### 9.22 Simulations (`simulations`)
- **Purpose:** Execution run and projected impact metrics of a scenario.
- **Scope:** Child entity scoped via parent `scenario_id` (`scenario.org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `Analyst`+.
- **Create:** `POST /api/v1/simulations` (or `POST /api/v1/scenarios/{id}/simulate`).
- **Read:** `GET /api/v1/simulations/{id}`.
- **List:** `GET /api/v1/simulations?scenario_id={id}`.
- **Update:** Unsupported (immutable execution run).
- **Delete:** Unsupported.
- **Filters:** `scenario_id`, `mode`, `status`.
- **Sort:** `executed_at`.
- **Notes:** Outputs include baseline metrics, projected metrics, and confidence intervals.

### 9.23 Optimization Runs (`optimization_runs`)
- **Purpose:** Prescriptive solver runs generating optimal mitigation plans.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `Analyst`+.
- **Create:** `POST /api/v1/optimization-runs`.
- **Read:** `GET /api/v1/optimization-runs/{id}`.
- **List:** `GET /api/v1/optimization-runs`.
- **Update:** Unsupported (immutable solver output).
- **Delete:** Unsupported.
- **Filters:** `objective`.
- **Sort:** `created_at`, `cost_savings_estimate`, `delay_reduction_days`.
- **Notes:** Recommended action sequence stored in `recommended_plan`.

### 9.24 Recommendations (`recommendations`)
- **Purpose:** Mitigation proposals generated by agents or analysts for active incidents.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `Analyst`+.
- **Create:** `POST /api/v1/recommendations`.
- **Read:** `GET /api/v1/recommendations/{id}`.
- **List:** `GET /api/v1/recommendations`.
- **Update:** `PATCH /api/v1/recommendations/{id}` (prior to approval).
- **Delete:** Unsupported.
- **Filters:** `incident_id`, `status`.
- **Sort:** `created_at`, `confidence`, `estimated_cost`.
- **Notes:** Status transitions: `PENDING` $\rightarrow$ `APPROVED` | `REJECTED` $\rightarrow$ `EXECUTED`.

### 9.25 Approvals (`approvals`)
- **Purpose:** Human-in-the-loop formal governance sign-off on recommendations.
- **Scope:** Child entity scoped via parent `recommendation_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `RiskManager`+.
- **Create:** `POST /api/v1/approvals` (or `POST /api/v1/recommendations/{id}/approve`).
- **Read:** `GET /api/v1/approvals/{id}`.
- **List:** `GET /api/v1/approvals?recommendation_id={id}`.
- **Update:** Immutable (405 Method Not Allowed).
- **Delete:** Immutable (405 Method Not Allowed).
- **Filters:** `recommendation_id`, `decision`, `decided_by_user_id`.
- **Sort:** `decided_at`.
- **Notes:** Automatically updates parent recommendation status and emits audit log.

### 9.26 Actions (`actions`)
- **Purpose:** Executed operational mitigation altering shipments, routes, or orders.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Execute: `RiskManager`+.
- **Create:** `POST /api/v1/actions`.
- **Read:** `GET /api/v1/actions/{id}`.
- **List:** `GET /api/v1/actions`.
- **Update:** Execution updates handled by internal executor service.
- **Delete:** Unsupported.
- **Filters:** `status`, `action_type`, `target_entity_type`.
- **Sort:** `executed_at`, `status`.
- **Notes:** Triggers operational workflow with full payload audit.

### 9.27 Verification Results (`verification_results`)
- **Purpose:** Post-action observational check comparing risk metrics before and after.
- **Scope:** Child entity scoped via parent `action_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+.
- **Create:** Automated observation service.
- **Read:** `GET /api/v1/verification-results/{id}`.
- **List:** `GET /api/v1/verification-results?action_id={id}`.
- **Update:** Immutable.
- **Delete:** Immutable.
- **Filters:** `action_id`, `verified`.
- **Sort:** `verified_at`.
- **Notes:** Verifies mitigation efficacy in the live network.

### 9.28 Audit Logs (`audit_logs`)
- **Purpose:** Immutable compliance trail of security, configuration, and data mutations.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Admin` (and `RiskManager` for compliance audits).
- **Create:** Automated system middleware and service hooks.
- **Read:** `GET /api/v1/audit-logs/{id}`.
- **List:** `GET /api/v1/audit-logs`.
- **Update:** Strictly prohibited (405 Method Not Allowed).
- **Delete:** Strictly prohibited (405 Method Not Allowed).
- **Filters:** `actor_type`, `action`, `resource_type`, `status`.
- **Sort:** `timestamp`.
- **Notes:** Captures `before_json` and `after_json` diffs with request correlation ID.

### 9.29 Notifications (`notifications`)
- **Purpose:** User and team alerts regarding risks, disruptions, and approvals.
- **Scope:** Organization-scoped (`org_id`), filtered by `user_id`.
- **Authentication:** Required.
- **Roles:** Read/List/Update: `Viewer`+ (own notifications).
- **Create:** Automated alert engine.
- **Read:** `GET /api/v1/notifications/{id}`.
- **List:** `GET /api/v1/notifications`.
- **Update:** `PATCH /api/v1/notifications/{id}` (mark as read: `is_read = true`).
- **Delete:** Unsupported.
- **Filters:** `category`, `severity`, `is_read`.
- **Sort:** `created_at`, `severity`.
- **Notes:** Supports batch mark-as-read: `POST /api/v1/notifications/mark-all-read`.

### 9.30 Agent Runs (`agent_runs`)
- **Purpose:** Autonomous multi-agent incident investigation pipeline executions.
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create: `Analyst`+.
- **Create:** `POST /api/v1/agent-runs`.
- **Read:** `GET /api/v1/agent-runs/{id}`.
- **List:** `GET /api/v1/agent-runs`.
- **Update:** Pipeline state managed by orchestrator.
- **Delete:** Unsupported.
- **Filters:** `incident_id`, `workflow_name`, `current_stage`, `status`.
- **Sort:** `started_at`, `confidence`.
- **Notes:** Tracks multi-agent lifecycle across stages.

### 9.31 Agent Tasks (`agent_tasks`)
- **Purpose:** Specific execution task performed by a specialized sub-agent.
- **Scope:** Child entity scoped via parent `agent_run_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+.
- **Create:** Agent orchestration service.
- **Read:** `GET /api/v1/agent-tasks/{id}`.
- **List:** `GET /api/v1/agent-tasks?agent_run_id={id}`.
- **Update:** Agent orchestration service.
- **Delete:** Unsupported.
- **Filters:** `agent_run_id`, `status`, `agent_name`.
- **Sort:** `started_at`, `duration_ms`.
- **Notes:** Contains sub-agent findings in `findings_json`.

### 9.32 Agent Tool Calls (`agent_tool_calls`)
- **Purpose:** Audit record of external tools invoked during an agent task.
- **Scope:** Scoped via parent `agent_task_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+.
- **Create:** Agent tool execution runner.
- **Read:** `GET /api/v1/agent-tool-calls/{id}`.
- **List:** `GET /api/v1/agent-tool-calls?agent_task_id={id}`.
- **Update:** Immutable audit record.
- **Delete:** Unsupported.
- **Filters:** `agent_task_id`, `status`, `tool_name`.
- **Sort:** `executed_at`, `duration_ms`.
- **Notes:** Records inputs, outputs, execution duration, and tool status.

### 9.33 Documents (`documents`)
- **Purpose:** Ingested enterprise documents (SOPs, contracts, intelligence feeds).
- **Scope:** Organization-scoped (`org_id`).
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+, Create/Delete: `Admin`+.
- **Create:** `POST /api/v1/documents`.
- **Read:** `GET /api/v1/documents/{id}`.
- **List:** `GET /api/v1/documents`.
- **Update:** Metadata updates only (`Admin`+).
- **Delete:** `DELETE /api/v1/documents/{id}` (cascades text chunk deletion).
- **Filters:** `status`, `file_type`, `search`.
- **Sort:** `created_at`, `title`.
- **Notes:** References S3 bucket storage via `s3_uri`.

### 9.34 Document Chunks (`document_chunks`)
- **Purpose:** Text chunks and vector embeddings used for semantic RAG search.
- **Scope:** Child entity scoped via parent `document_id`.
- **Authentication:** Required.
- **Roles:** Read/List: `Viewer`+.
- **Create:** Ingestion embedding worker.
- **Read:** `GET /api/v1/document-chunks/{id}`.
- **List:** `GET /api/v1/document-chunks?document_id={id}`.
- **Update:** Ingestion embedding worker.
- **Delete:** Controlled via parent Document deletion.
- **Filters:** `document_id`.
- **Sort:** `chunk_index`.
- **Notes:** Embeddings stored for similarity search.

---

## 10. Production Endpoint Matrix

The following matrix represents the formal production API contract designed for Phase 4. All business endpoints have their Pydantic request and response schemas verified and ready for implementation.

| Resource | Method | Endpoint | Auth | Scope | Allowed Roles | Contract Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Auth** | `GET` | `/api/v1/auth/google` | Public | System | Public | **ACTIVE (Phase 3)** |
| **Auth** | `GET` | `/api/v1/auth/google/callback` | Public | System | Public | **ACTIVE (Phase 3)** |
| **Auth** | `GET` | `/api/v1/auth/me` | Cookie | Tenant | All Authenticated | **ACTIVE (Phase 3)** |
| **Auth** | `POST` | `/api/v1/auth/logout` | Cookie | Session | All Authenticated | **ACTIVE (Phase 3)** |
| **Health** | `GET` | `/api/v1/health` | Public | System | Public | **ACTIVE** |
| **Health** | `GET` | `/api/v1/health/db` | Public | System | Public | **ACTIVE** |
| **Organization**| `GET` | `/api/v1/organizations/me` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Organization**| `PATCH`| `/api/v1/organizations/me` | Cookie | Tenant | `Admin` | Designed |
| **Users** | `GET` | `/api/v1/users` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Users** | `POST` | `/api/v1/users` | Cookie | Tenant | `Admin` | Designed |
| **Users** | `GET` | `/api/v1/users/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Users** | `PATCH`| `/api/v1/users/{id}` | Cookie | Tenant | `Admin` | Designed |
| **Suppliers** | `GET` | `/api/v1/suppliers` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Suppliers** | `POST` | `/api/v1/suppliers` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Suppliers** | `GET` | `/api/v1/suppliers/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Suppliers** | `PATCH`| `/api/v1/suppliers/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Supplier Sites**| `GET`| `/api/v1/supplier-sites` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Supplier Sites**| `POST`| `/api/v1/supplier-sites` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Supplier Sites**| `GET`| `/api/v1/supplier-sites/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Supplier Sites**| `PATCH`| `/api/v1/supplier-sites/{id}`| Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Factories** | `GET` | `/api/v1/factories` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Factories** | `POST` | `/api/v1/factories` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Factories** | `GET` | `/api/v1/factories/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Factories** | `PATCH`| `/api/v1/factories/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Warehouses** | `GET` | `/api/v1/warehouses` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Warehouses** | `POST` | `/api/v1/warehouses` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Warehouses** | `GET` | `/api/v1/warehouses/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Warehouses** | `PATCH`| `/api/v1/warehouses/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Ports** | `GET` | `/api/v1/ports` | Cookie | Global | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Ports** | `GET` | `/api/v1/ports/{id}` | Cookie | Global | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Carriers** | `GET` | `/api/v1/carriers` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Carriers** | `POST` | `/api/v1/carriers` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Carriers** | `GET` | `/api/v1/carriers/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Carriers** | `PATCH`| `/api/v1/carriers/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Products** | `GET` | `/api/v1/products` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Products** | `POST` | `/api/v1/products` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Products** | `GET` | `/api/v1/products/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Products** | `PATCH`| `/api/v1/products/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Routes** | `GET` | `/api/v1/routes` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Routes** | `POST` | `/api/v1/routes` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Routes** | `GET` | `/api/v1/routes/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Routes** | `PATCH`| `/api/v1/routes/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipments** | `GET` | `/api/v1/shipments` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipments** | `POST` | `/api/v1/shipments` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipments** | `GET` | `/api/v1/shipments/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipments** | `PATCH`| `/api/v1/shipments/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipment Events**| `GET`| `/api/v1/shipment-events` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipment Events**| `POST`| `/api/v1/shipment-events` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Shipment Events**| `GET`| `/api/v1/shipment-events/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory** | `GET` | `/api/v1/inventory` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory** | `POST` | `/api/v1/inventory` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory** | `GET` | `/api/v1/inventory/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory** | `PATCH`| `/api/v1/inventory/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory Movements**| `GET`| `/api/v1/inventory-movements`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory Movements**| `POST`| `/api/v1/inventory-movements`| Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Inventory Movements**| `GET`| `/api/v1/inventory-movements/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Risks** | `GET` | `/api/v1/risks` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Risks** | `POST` | `/api/v1/risks` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Risks** | `GET` | `/api/v1/risks/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Risks** | `PATCH`| `/api/v1/risks/{id}` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Risk Factors**| `GET` | `/api/v1/risk-factors` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Risk Factors**| `POST`| `/api/v1/risk-factors` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Risk Factors**| `GET` | `/api/v1/risk-factors/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Risk Assessments**| `GET`| `/api/v1/risk-assessments`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Risk Assessments**| `POST`| `/api/v1/risk-assessments`| Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Risk Assessments**| `GET`| `/api/v1/risk-assessments/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Incidents** | `GET` | `/api/v1/incidents` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Incidents** | `POST` | `/api/v1/incidents` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Incidents** | `GET` | `/api/v1/incidents/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Incidents** | `PATCH`| `/api/v1/incidents/{id}` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Twin Nodes** | `GET` | `/api/v1/twin-nodes` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Nodes** | `POST` | `/api/v1/twin-nodes` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Nodes** | `GET` | `/api/v1/twin-nodes/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Nodes** | `PATCH`| `/api/v1/twin-nodes/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Nodes** | `DELETE`| `/api/v1/twin-nodes/{id}`| Cookie | Tenant | `RiskManager`, `Admin` | Designed |
| **Twin Edges** | `GET` | `/api/v1/twin-edges` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Edges** | `POST` | `/api/v1/twin-edges` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Edges** | `GET` | `/api/v1/twin-edges/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Edges** | `PATCH`| `/api/v1/twin-edges/{id}` | Cookie | Tenant | `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Twin Edges** | `DELETE`| `/api/v1/twin-edges/{id}`| Cookie | Tenant | `RiskManager`, `Admin` | Designed |
| **Scenarios** | `GET` | `/api/v1/scenarios` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Scenarios** | `POST` | `/api/v1/scenarios` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Scenarios** | `GET` | `/api/v1/scenarios/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Scenarios** | `PATCH`| `/api/v1/scenarios/{id}` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Scenarios** | `DELETE`| `/api/v1/scenarios/{id}` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Simulations** | `GET` | `/api/v1/simulations` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Simulations** | `POST` | `/api/v1/simulations` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Simulations** | `GET` | `/api/v1/simulations/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Optimization**| `GET` | `/api/v1/optimization-runs`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Optimization**| `POST`| `/api/v1/optimization-runs`| Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Optimization**| `GET` | `/api/v1/optimization-runs/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Recommendations**| `GET`| `/api/v1/recommendations`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Recommendations**| `POST`| `/api/v1/recommendations`| Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Recommendations**| `GET`| `/api/v1/recommendations/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Recommendations**| `PATCH`| `/api/v1/recommendations/{id}`| Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Approvals** | `GET` | `/api/v1/approvals` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Approvals** | `POST` | `/api/v1/approvals` | Cookie | Tenant | `RiskManager`, `Admin` | Designed |
| **Approvals** | `GET` | `/api/v1/approvals/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Actions** | `GET` | `/api/v1/actions` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Actions** | `POST` | `/api/v1/actions` | Cookie | Tenant | `RiskManager`, `Admin` | Designed |
| **Actions** | `GET` | `/api/v1/actions/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Verification**| `GET` | `/api/v1/verification-results`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Verification**| `GET` | `/api/v1/verification-results/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Audit Logs** | `GET` | `/api/v1/audit-logs` | Cookie | Tenant | `Admin`, `RiskManager` | Designed |
| **Audit Logs** | `GET` | `/api/v1/audit-logs/{id}`| Cookie | Tenant | `Admin`, `RiskManager` | Designed |
| **Notifications**| `GET`| `/api/v1/notifications` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Notifications**| `GET`| `/api/v1/notifications/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Notifications**| `PATCH`| `/api/v1/notifications/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Agent Runs** | `GET` | `/api/v1/agent-runs` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Agent Runs** | `POST` | `/api/v1/agent-runs` | Cookie | Tenant | `Analyst`, `RiskManager`, `Admin` | Designed |
| **Agent Runs** | `GET` | `/api/v1/agent-runs/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Agent Tasks**| `GET` | `/api/v1/agent-tasks` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Agent Tasks**| `GET` | `/api/v1/agent-tasks/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Agent Tool Calls**| `GET`| `/api/v1/agent-tool-calls`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Agent Tool Calls**| `GET`| `/api/v1/agent-tool-calls/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Documents** | `GET` | `/api/v1/documents` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Documents** | `POST` | `/api/v1/documents` | Cookie | Tenant | `Admin` | Designed |
| **Documents** | `GET` | `/api/v1/documents/{id}` | Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Documents** | `DELETE`| `/api/v1/documents/{id}` | Cookie | Tenant | `Admin` | Designed |
| **Document Chunks**| `GET`| `/api/v1/document-chunks`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |
| **Document Chunks**| `GET`| `/api/v1/document-chunks/{id}`| Cookie | Tenant | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | Designed |

---

## 11. Security, Auditability & Compliance Summary

### Zero Trust Data Ingress
- Client requests are strictly validated using Pydantic models with `extra = "forbid"`.
- All writes are sanitized to prevent injection attacks and illegal attribute mutation.

### Immutable Audit Trail
Every write operation across supply chain assets, governance decisions, and user permissions emits a record to `audit_logs` containing:
- `actor_type` (`USER`, `AGENT`, `SYSTEM`)
- `actor_id` (User ID or Agent ID)
- `action` (e.g., `SUPPLIER_CREATE`, `RECOMMENDATION_APPROVE`, `ACTION_EXECUTE`)
- `resource_type` and `resource_id`
- `before_json` and `after_json` state diffs
- Request correlation ID for distributed tracing
