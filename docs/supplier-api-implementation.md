# RiskWise 2.0 Supplier API Implementation

**Document Version:** 2.0.0  
**Status:** IMPLEMENTED & VALIDATED  
**Phase:** Phase 4 — Core APIs (Step 3 — Supplier APIs)  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Executive Summary

The **Supplier API** is the primary operational entry point for managing tier-1, tier-2, and tier-3 component, material, and assembly providers in RiskWise 2.0. Built strictly upon the service and repository foundations of Step 2, it delivers:
- Multi-tenant data partitioning via authenticated server context (`context.organization_id`).
- Five-tier role-based access control (RBAC).
- Atomic transaction coordination via `UnitOfWork`.
- Automated, secret-scrubbed audit logging via `AuditService`.
- Standardized error envelopes with 404 cross-tenant information masking.
- Safe allowlisted filtering, sorting, and wildcard-escaped search.

---

## 2. Endpoints & Route Summary

All endpoints are mounted under the prefix `/api/v1/suppliers`:

| Method | Path | Summary | Allowed Roles | Success Status |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/suppliers` | List suppliers (paginated, filtered, sorted, searched) | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | `200 OK` |
| `POST` | `/api/v1/suppliers` | Create a new supplier in the tenant partition | `OpsManager`, `RiskManager`, `Admin` | `201 Created` |
| `GET` | `/api/v1/suppliers/{id}` | Retrieve individual supplier by ID | `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin` | `200 OK` |
| `PATCH` | `/api/v1/suppliers/{id}` | Update existing supplier details | `OpsManager`, `RiskManager`, `Admin` | `200 OK` |
| `DELETE`| `/api/v1/suppliers/{id}` | **Not Supported** (operational lifecycle management) | — | `405 Method Not Allowed` |

---

## 3. Authentication & Authorization (RBAC)

### 3.1 Authentication
All Supplier endpoints require a valid RiskWise application session cookie (`riskwise_session`) established via the Phase 3 Google OAuth 2.0 workflow.
- Missing, expired, or invalid sessions unconditionally return `401 Unauthorized`.
- Inactive user accounts immediately revoke the session and return `401 Unauthorized`.

### 3.2 Authorization (RBAC)
Role checks are enforced at the router layer using the `require_role(*allowed_roles)` dependency factory:
- **Read Access (`Viewer`+):** Users with `Viewer`, `Analyst`, `OpsManager`, `RiskManager`, or `Admin` roles may list and retrieve suppliers.
- **Write Access (`OpsManager`+):** Creating (`POST`) or modifying (`PATCH`) suppliers requires `OpsManager`, `RiskManager`, or `Admin`. Attempted mutations by `Viewer` or `Analyst` users return `403 Forbidden` (`INSUFFICIENT_PERMISSIONS`).

---

## 4. Multi-Tenancy & Data Isolation

1. **Server-Owned Tenant Context:** The client is strictly prohibited from supplying `org_id`. Any `org_id` in the request body is rejected with `422 Unprocessable Entity` (`model_config = ConfigDict(extra="forbid")`).
2. **Context Derivation:** The tenant partition is unconditionally derived from `context.organization_id` inside `AuthenticatedContext`.
3. **Database Scoping:** All queries executed by `SupplierRepository` apply `Supplier.org_id == context.organization_id`.
4. **Cross-Tenant Masking (404 vs 403):** If a user attempts to read or update a supplier ID belonging to another tenant, the API returns `404 Not Found` (never 403). This prevents competitor ID enumeration and unauthorized data discovery.

---

## 5. Request & Response Schemas

### 5.1 Create Supplier Request (`POST /api/v1/suppliers`)
```json
{
  "name": "Apex Microelectronics Ltd",
  "code": "SUP-APEX-001",
  "country": "TW",
  "tier": "CRITICAL",
  "criticality": "HIGH",
  "reliability_score": 94.5,
  "financial_exposure": 1500000.0,
  "lead_time_days": 45.0,
  "metadata_json": {
    "certifications": ["ISO-9001", "IATF-16949"],
    "primary_contact": "supply@apex.tw"
  }
}
```
*Note: `id`, `org_id`, `created_at`, and `updated_at` are server-managed and forbidden in client payloads.*

### 5.2 Supplier Response (`SupplierResponse`)
```json
{
  "id": "sup_6f8b2d10-3c4a-4e89-a29b-8d147814b7e1",
  "org_id": "org_alpha_01",
  "name": "Apex Microelectronics Ltd",
  "code": "SUP-APEX-001",
  "country": "TW",
  "tier": "CRITICAL",
  "criticality": "HIGH",
  "reliability_score": 94.5,
  "financial_exposure": 1500000.0,
  "lead_time_days": 45.0,
  "current_risk_id": null,
  "metadata_json": {
    "certifications": ["ISO-9001", "IATF-16949"],
    "primary_contact": "supply@apex.tw"
  },
  "created_at": "2026-09-07T13:30:00Z",
  "updated_at": null
}
```

### 5.3 Supplier List Response (`SupplierListResponse`)
```json
{
  "items": [
    {
      "id": "sup_6f8b2d10-3c4a-4e89-a29b-8d147814b7e1",
      "org_id": "org_alpha_01",
      "name": "Apex Microelectronics Ltd",
      "code": "SUP-APEX-001",
      "country": "TW",
      "tier": "CRITICAL",
      "criticality": "HIGH",
      "reliability_score": 94.5,
      "financial_exposure": 1500000.0,
      "lead_time_days": 45.0,
      "current_risk_id": null,
      "metadata_json": {},
      "created_at": "2026-09-07T13:30:00Z",
      "updated_at": null
    }
  ],
  "pagination": {
    "total": 1,
    "page": 1,
    "limit": 20,
    "pages": 1
  }
}
```

---

## 6. Safe Querying: Pagination, Filtering, Sorting & Search

### 6.1 Pagination
- `page`: Integer $\ge 1$ (default: `1`).
- `limit`: Integer between `1` and `100` (default: `20`, maximum: `100`).
- Illegal values (e.g., `page=0` or `limit=101`) return `422 Unprocessable Entity`.

### 6.2 Filtering
Filtering is restricted to an explicit allowlist:
- `tier`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
- `criticality`: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
- `country`: String (e.g., `TW`, `US`, `DE`)
- `created_at_after`: ISO-8601 timestamp (`created_at >= val`)
- `created_at_before`: ISO-8601 timestamp (`created_at <= val`)
- **Unapproved Filter Fields:** Any unexpected query parameter returns `400 Bad Request` with code `INVALID_FILTER_FIELD`.

### 6.3 Sorting
Sorting is restricted to approved model columns:
- Allowlist: `name`, `code`, `country`, `tier`, `criticality`, `reliability_score`, `financial_exposure`, `lead_time_days`, `created_at`, `updated_at`.
- Syntax: `sort=name` (ascending) or `sort=-reliability_score` (descending).
- **Unapproved Sort Fields:** Requesting an unapproved field returns `400 Bad Request` with code `INVALID_SORT_FIELD`.

### 6.4 Search
Case-insensitive substring search is performed across `name`, `code`, and `country`. Special SQL LIKE wildcards (`%`, `_`, `\`) are safely escaped before execution to prevent wildcard pattern injection.

---

## 7. Business Validation & Conflict Handling

1. **Unique Code Check:** Supplier `code` must be unique within an organization. Attempting to create or update a supplier with a duplicate code returns `409 Conflict`:
   ```json
   {
     "error": {
       "code": "SUPPLIER_CODE_EXISTS",
       "message": "Supplier with code 'SUP-APEX-001' already exists in this organization",
       "details": {
         "code": "SUP-APEX-001"
       }
     }
   }
   ```
2. **Reliability Score Range:** Validated within $[0.0, 100.0]$. Out-of-bounds values return `422 Unprocessable Entity`.
3. **Financial Exposure:** Validated $\ge 0.0$. Negative values return `422 Unprocessable Entity`.

---

## 8. Lifecycle & Deletion Policy

In compliance with the Phase 4 Core API contract, **hard deletion of operational suppliers is strictly disabled**:
- `DELETE /api/v1/suppliers/{id}` is not registered on the router and returns `405 Method Not Allowed`.
- Programmatic invocations of `service.delete(id)` raise `LifecycleStateError` (HTTP 409) instructing the caller to manage supplier lifecycle state via operational metadata.

---

## 9. Transactions & Audit Logging

### 9.1 Atomic Transaction Boundary
All mutations (`create_supplier`, `update_supplier`) operate inside a `with self.uow:` context:
1. Model created or modified via `SupplierRepository` (`auto_commit=False`).
2. Audit log entry recorded via `AuditService.log_event` (`auto_commit=False`).
3. Transaction committed atomically via `self.uow.commit()`.
4. Any failure triggers an immediate `self.uow.rollback()`, ensuring zero partial state persistence.

### 9.2 Audit Log Trails
Mutations emit an immutable record into the `audit_logs` table:
- `actor_id`: Authenticated user UUID.
- `org_id`: Tenant UUID.
- `action`: `CREATE` or `UPDATE`.
- `resource_type`: `Supplier`.
- `resource_id`: Supplier UUID.
- `before_json`: Prior state snapshot (for updates).
- `after_json`: New state snapshot with recursive credential/secret scrubbing (`[REDACTED]`).

---

## 10. Automated Test Coverage

The Supplier API implementation is validated by **21 security, multi-tenancy, and domain tests** in `api/tests/test_supplier_api.py`:

| # | Test Name | Assertion / Scenario |
| :--- | :--- | :--- |
| 1 | `test_1_unauthenticated_get_returns_401` | Missing session cookie returns `401 Unauthorized`. |
| 2 | `test_2_unauthenticated_post_returns_401` | Unauthenticated POST returns `401 Unauthorized`. |
| 3 | `test_3_viewer_get_allowed` | `Viewer` role can read supplier collection and individual record (`200 OK`). |
| 4 | `test_4_unauthorized_post_returns_403` | `Viewer` and `Analyst` roles receive `403 Forbidden` on creation attempts. |
| 5 | `test_5_authorized_post_success` | `OpsManager`, `RiskManager`, and `Admin` successfully create suppliers (`201 Created`). |
| 6 | `test_6_cross_tenant_get_returns_404` | Reading another tenant's supplier returns `404 Not Found` (masked). |
| 7 | `test_7_cross_tenant_patch_returns_404` | Updating another tenant's supplier returns `404 Not Found` (masked). |
| 8 | `test_8_client_supplied_org_id_rejected` | Body containing `org_id` returns `422 Unprocessable Entity`. |
| 9 | `test_9_client_supplied_server_controlled_id_rejected` | Body containing `id` or `created_at` returns `422 Unprocessable Entity`. |
| 10 | `test_10_invalid_sort_returns_400` | Unapproved sort field returns `400 Bad Request` (`INVALID_SORT_FIELD`). |
| 11 | `test_11_invalid_filter_returns_400` | Unapproved filter field returns `400 Bad Request` (`INVALID_FILTER_FIELD`). |
| 12 | `test_12_invalid_pagination_returns_422` | `page=0` or `limit=101` returns `422 Unprocessable Entity`. |
| 13 | `test_13_search_safely_escapes_wildcards` | Searching `%` escapes wildcards and matches exact literal string. |
| 14 | `test_14_missing_supplier_returns_404` | Unknown supplier ID returns `404 Not Found` (`RESOURCE_NOT_FOUND`). |
| 15 | `test_15_valid_update_success` | Valid `PATCH` modifies fields and updates timestamp (`200 OK`). |
| 16 | `test_16_invalid_update_validation_error` | Out-of-bounds `reliability_score` returns `422 Unprocessable Entity`. |
| 17 | `test_17_duplicate_code_conflict_returns_409` | Duplicate `code` within tenant returns `409 Conflict` (`SUPPLIER_CODE_EXISTS`). |
| 18 | `test_18_hard_delete_not_exposed` | `DELETE /api/v1/suppliers/{id}` returns `405 Method Not Allowed`. |
| 19 | `test_19_audit_record_generated_for_mutation` | Creation and update persist immutable records to `audit_logs`. |
| 20 | `test_20_transaction_rollback_works_after_failed_mutation` | Uniqueness conflict leaves database clean without partial writes. |
| 21 | `test_21_openapi_schema_contains_supplier_endpoints` | OpenAPI spec contains all 4 endpoints, correct methods, and zero duplicates. |

### Overall Suite Regression Status:
- Total Tests: **155**
- Passed: **154**
- Skipped: **1** (live RDS destructive safety guard)
- Failed: **0**
- Regressions: **None**
