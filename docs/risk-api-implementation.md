# RiskWise 2.0 — Risk API Implementation Report

**Document Version:** 1.0.0  
**Status:** IMPLEMENTED & VALIDATED  
**Phase:** Phase 4 — Core APIs (Step 6 — Risk APIs)  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Executive Summary & Scope Boundaries

In Phase 4 Step 6, the production CRUD and API governance layer for the **Risk domain** was implemented strictly covering the four core resources approved in `docs/core-api-contract.md`:

1. **`risks`** (`Risk` model, `risks` table) — Organization-scoped geopolitical, climatic, supplier, or lane risk entities.
2. **`risk_factors`** (`RiskFactor` model, `risk_factors` table) — Causal drivers contributing to composite risk scores, scoped hierarchically through parent `risk.org_id`.
3. **`risk_assessments`** (`RiskAssessment` model, `risk_assessments` table) — Organization-scoped, immutable evaluation snapshots analyzing risks.
4. **`incidents`** (`Incident` model, `incidents` table) — Organization-scoped realized disruptions actively managed through defined lifecycle states.

### Strict Governance Boundary
> [!IMPORTANT]
> **CRUD & Governance Only:** This implementation provides strictly the state management, tenant isolation, RBAC governance, validation, and audit layer. The future **Risk Engine**, automated ML predictive scoring, external signal ingestion (TomTom, AISStream, OpenSky, live weather), simulation, optimization, and AI agents (LangGraph/Bedrock) are **NOT** implemented in this phase and belong to future roadmap milestones.

### Database & Schema Integrity
- **Zero Database DDL / Schema Modifications:** Utilized the existing Phase 2 PostgreSQL schema without altering table definitions or adding constraints.
- **Zero Database Migrations:** No Alembic migrations generated or applied.

---

## 2. Production Endpoints Matrix

| Resource | HTTP Method | Path | Auth | Scope | Roles | Description / Invariants |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Risks** | `GET` | `/api/v1/risks` | Cookie | Tenant | `Viewer`+ | List risks with pagination, search, filter, and sort |
| **Risks** | `POST` | `/api/v1/risks` | Cookie | Tenant | `Analyst`+ | Create new risk entity within tenant partition |
| **Risks** | `GET` | `/api/v1/risks/{id}` | Cookie | Tenant | `Viewer`+ | Retrieve single risk with 404 masking |
| **Risks** | `PATCH` | `/api/v1/risks/{id}` | Cookie | Tenant | `Analyst`+ | Update risk attributes with audit logging |
| **Risks** | `GET` | `/api/v1/risks/{id}/factors` | Cookie | Tenant | `Viewer`+ | List causal factors linked to parent risk |
| **Risks** | `GET` | `/api/v1/risks/{id}/assessments` | Cookie | Tenant | `Viewer`+ | List evaluation assessments linked to parent risk |
| **Risk Factors** | `GET` | `/api/v1/risk-factors` | Cookie | Tenant | `Viewer`+ | List risk factors with pagination, filter, sort, search |
| **Risk Factors** | `POST` | `/api/v1/risk-factors` | Cookie | Tenant | `Analyst`+ | Create causal factor validating parent risk ownership |
| **Risk Factors** | `GET` | `/api/v1/risk-factors/{id}` | Cookie | Tenant | `Viewer`+ | Retrieve single risk factor with 404 masking |
| **Risk Factors** | `PATCH` | `/api/v1/risk-factors/{id}` | Cookie | Tenant | `Analyst`+ | Update risk factor attributes with audit logging |
| **Risk Factors** | `DELETE` | `/api/v1/risk-factors/{id}` | Cookie | Tenant | `Analyst`+ | Delete obsolete risk factor with audit logging |
| **Risk Assessments** | `GET` | `/api/v1/risk-assessments` | Cookie | Tenant | `Viewer`+ | List evaluation snapshots with pagination, filter, sort |
| **Risk Assessments** | `POST` | `/api/v1/risk-assessments` | Cookie | Tenant | `Analyst`+ | Record immutable risk assessment evaluation snapshot |
| **Risk Assessments** | `GET` | `/api/v1/risk-assessments/{id}` | Cookie | Tenant | `Viewer`+ | Retrieve single assessment record with 404 masking |
| **Incidents** | `GET` | `/api/v1/incidents` | Cookie | Tenant | `Viewer`+ | List disruption incidents with pagination, filter, sort |
| **Incidents** | `POST` | `/api/v1/incidents` | Cookie | Tenant | `Analyst`+ | Record new incident with optional risk reference verification |
| **Incidents** | `GET` | `/api/v1/incidents/{id}` | Cookie | Tenant | `Viewer`+ | Retrieve single incident record with 404 masking |
| **Incidents** | `PATCH` | `/api/v1/incidents/{id}` | Cookie | Tenant | `Analyst`+ | Update incident details and manage lifecycle transitions |

---

## 3. Authentication & RBAC Governance

### Authentication
All risk endpoints require an active application session established via Phase 3 Google OAuth. The session ID is transmitted via the secure `riskwise_session` HTTP-only cookie and validated by `SessionService`.
- **Unauthenticated Requests:** Return `401 Unauthorized`.

### Role-Based Access Control (RBAC)
Authorization is enforced via `require_role(*allowed_roles)`:
- **`Viewer`:** Read-only access to all risk collections and single entities (`GET`).
- **`Analyst` / `OpsManager` / `RiskManager` / `Admin`:** Mutation privileges (`POST`, `PATCH`, `DELETE`).
- **Forbidden Mutations:** If a `Viewer` attempts any write operation (`POST /api/v1/risks`, `PATCH /api/v1/risks/{id}`, `DELETE /api/v1/risk-factors/{id}`, etc.), the request is rejected with `403 Forbidden` (`FORBIDDEN_MUTATION`).

---

## 4. Multi-Tenant Isolation & Relationship Validation

### Tenant Isolation Strategy
- **Zero Client-Side Tenancy:** Request bodies and query parameters are forbidden from supplying server-controlled tenancy fields like `org_id` (`extra = "forbid"` returns `422 Unprocessable Entity`).
- **Hierarchical Isolation for Child Entities:**
  - `RiskFactor` records are linked to `Risk` via `risk_id`. Data access joins `risks` on `risks.id == risk_factors.risk_id` and filters by `risks.org_id == context.organization_id`.
- **404 Masking:** To prevent competitor existence discovery and enumeration, requests targeting records belonging to other organizations return `404 Not Found` with code `RESOURCE_NOT_FOUND`.
- **Cross-Tenant Relationship Protection:**
  - When creating a `RiskFactor`, the parent `risk_id` is verified to belong to the authenticated organization.
  - When creating a `RiskAssessment`, the target `risk_id` must belong to the authenticated organization.
  - When creating or updating an `Incident` with a `risk_id`, the referenced risk must belong to the authenticated organization.
  - Cross-tenant references fail safely with `404 Not Found` (masked).

---

## 5. Domain Invariants & Business Rules

1. **Risk Invariants:**
   - `probability` must be within $[0.0, 1.0]$.
   - `impact` must be within $[0.0, 100.0]$.
   - `risk_score` must be within $[0.0, 100.0]$.
   - `confidence` must be within $[0.0, 1.0]$.
   - `severity` must adhere to `RiskSeverity` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
   - `trend` must adhere to `RiskTrend` (`INCREASING`, `DECREASING`, `STABLE`, `VOLATILE`).
   - Hard `DELETE` on `/api/v1/risks/{id}` is unsupported and returns `405 Method Not Allowed`.
2. **Risk Factor Invariants:**
   - `weight` must be $\ge 0.0$.
   - `score` must be within $[0.0, 100.0]$.
   - Deletion of obsolete factors is supported (`DELETE /api/v1/risk-factors/{id}`).
3. **Risk Assessment Immutability:**
   - Assessments represent historical audit evaluation snapshots.
   - `PATCH` and `DELETE` on `/api/v1/risk-assessments/{id}` are not registered and return `405 Method Not Allowed`.
   - Domain service methods `update_assessment()` and `delete_assessment()` explicitly raise `ImmutableResourceError`.
4. **Incident Lifecycle Invariants:**
   - `status` must adhere to `IncidentStatus` (`DETECTED`, `INVESTIGATING`, `MITIGATING`, `RESOLVED`, `CLOSED`).
   - Transitioning an incident to `RESOLVED` or `CLOSED` automatically sets `resolved_at` to the current UTC timestamp if not explicitly provided.
   - Hard `DELETE` on `/api/v1/incidents/{id}` is unsupported and returns `405 Method Not Allowed`.

---

## 6. Safe Query Filtering, Sorting & Search (Allowlists)

All queries are protected by repository allowlists against SQL injection and data leakage:

### Allowlist Definitions:
- **Risks:**
  - Search: `["title", "location", "risk_type", "source"]` (SQL wildcards `%` and `_` safely escaped)
  - Sort: `detected_at`, `risk_score`, `impact`, `probability`, `title`, `severity`, `confidence`, `updated_at`
  - Filter: `severity`, `trend`, `risk_type`, `source`, `detected_at_after`, `detected_at_before`
- **Risk Factors:**
  - Search: `["name", "category"]`
  - Sort: `created_at`, `score`, `weight`, `name`
  - Filter: `risk_id`, `category`
- **Risk Assessments:**
  - Search: `["methodology", "assessor_type", "assessor_id"]`
  - Sort: `created_at`, `score`, `confidence`
  - Filter: `risk_id`, `assessor_type`, `created_at_after`, `created_at_before`
- **Incidents:**
  - Search: `["title", "location", "source"]`
  - Sort: `detected_at`, `severity`, `title`, `updated_at`, `resolved_at`
  - Filter: `status`, `severity`, `risk_id`, `detected_at_after`, `detected_at_before`

Passing any unapproved query field returns `400 Bad Request` with `INVALID_FILTER_FIELD` or `INVALID_SORT_FIELD`.

---

## 7. Audit Trail Strategy

All state-changing operations emit immutable audit records using the centralized `AuditService.log_event`:
- **`Risk` Operations:** `CREATE`, `UPDATE` logged with actor ID and before/after payloads.
- **`RiskFactor` Operations:** `CREATE`, `UPDATE`, `DELETE` logged with factor identifiers.
- **`RiskAssessment` Operations:** `CREATE` logged with evaluation parameters.
- **`Incident` Operations:** `CREATE`, `UPDATE` logged with lifecycle transition diffs.
- **Scrubbing & Serialization:** `sanitize_payload` automatically sanitizes sensitive credentials and serializes date/time objects into ISO 8601 strings.

---

## 8. Test Coverage & Validation Metrics

A dedicated test suite in `api/tests/test_risk_api.py` verifies all 26 contract criteria:

```
api/tests/test_risk_api.py::test_1_authentication_required PASSED
api/tests/test_risk_api.py::test_2_rbac_enforcement PASSED
api/tests/test_risk_api.py::test_3_tenant_isolation PASSED
api/tests/test_risk_api.py::test_4_cross_tenant_parent_reference_rejection PASSED
api/tests/test_risk_api.py::test_5_risk_factor_creation PASSED
api/tests/test_risk_api.py::test_6_risk_factor_retrieval PASSED
api/tests/test_risk_api.py::test_7_risk_factor_listing PASSED
api/tests/test_risk_api.py::test_8_risk_factor_filtering PASSED
api/tests/test_risk_api.py::test_9_risk_factor_sorting PASSED
api/tests/test_risk_api.py::test_10_risk_factor_search_and_wildcard_escaping PASSED
api/tests/test_risk_api.py::test_11_risk_crud PASSED
api/tests/test_risk_api.py::test_12_risk_forbidden_hard_delete PASSED
api/tests/test_risk_api.py::test_13_risk_numeric_bounds_validation PASSED
api/tests/test_risk_api.py::test_14_risk_assessment_creation PASSED
api/tests/test_risk_api.py::test_15_risk_assessment_retrieval PASSED
api/tests/test_risk_api.py::test_16_assessment_immutability_rules PASSED
api/tests/test_risk_api.py::test_17_incident_creation PASSED
api/tests/test_risk_api.py::test_18_incident_retrieval PASSED
api/tests/test_risk_api.py::test_19_incident_listing PASSED
api/tests/test_risk_api.py::test_20_incident_update PASSED
api/tests/test_risk_api.py::test_21_incident_lifecycle_auto_resolution PASSED
api/tests/test_risk_api.py::test_22_server_controlled_field_protection PASSED
api/tests/test_risk_api.py::test_23_standardized_error_envelopes PASSED
api/tests/test_risk_api.py::test_24_audit_logging_behavior PASSED
api/tests/test_risk_api.py::test_25_openapi_route_registration_and_uniqueness PASSED
api/tests/test_risk_api.py::test_26_risk_factor_deletion PASSED
```

### Full Regression Suite Results
Running the complete test suite across all Phase 1-4 modules:
- **Total Tests:** 238 tests.
- **Results:** 237 passed, 1 skipped (live RDS network probe skip guard).
- **New Failures:** 0.

### OpenAPI Specification Validation
- **Total Endpoints Registered:** 45 paths.
- **Total HTTP Operations:** 73 operations.
- **Operation ID Uniqueness:** 100% unique (0 duplicates across entire specification).
