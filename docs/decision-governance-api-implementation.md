# RiskWise 2.0 — Decision & Governance API Implementation

**Document Version:** 1.0.0  
**Status:** COMPLETED & VALIDATED  
**Phase:** Phase 4 — Core APIs (Step 7 — Decision & Governance APIs)  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Architectural Scope & Purpose

This step implements the authoritative **Decision & Governance APIs** (Phase 4 Step 7) for RiskWise 2.0, covering:
1. `recommendations` (Mitigation proposals generated for active disruption incidents)
2. `approvals` (Human-in-the-loop formal governance sign-offs on recommendations)
3. `actions` (Operational mitigation execution records altering shipments, routes, or orders)
4. `verification_results` (Post-action observational verification comparing risk before and after mitigation)
5. `notifications` (User alerts and broadcast notifications)
6. `audit_logs` (Immutable compliance audit trail query interface)

> [!IMPORTANT]
> **Foundation Rule:** This step provides the production API, repository, service, and governance foundation for future agentic decision, action, and verification workflows. It does **NOT** implement the Decision Agent, Action Agent, Verification Agent, LangGraph, Claude/Bedrock, OR-Tools, optimization solvers, simulation engine, or external logistics integrations (TMS/WMS/ERP).

---

## 2. Resource & Endpoint Inventory

The Step 7 implementation delivers **23 production endpoints** under `/api/v1`, each with globally unique OpenAPI operation IDs, strict Pydantic v2 schemas (`extra = "forbid"`), and RBAC gates:

| Domain Resource | HTTP Method | Route | Scope | RBAC Minimum Role | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Recommendations** | `GET` | `/api/v1/recommendations` | Tenant | `Viewer`+ | Paginated list with filtering, sorting, and substring search |
| **Recommendations** | `POST` | `/api/v1/recommendations` | Tenant | `Analyst`+ | Record new mitigation recommendation proposal |
| **Recommendations** | `GET` | `/api/v1/recommendations/{id}` | Tenant | `Viewer`+ | Single recommendation retrieval with 404 masking |
| **Recommendations** | `PATCH`| `/api/v1/recommendations/{id}` | Tenant | `Analyst`+ | Update proposal prior to formal decision |
| **Recommendations** | `POST` | `/api/v1/recommendations/{id}/approve` | Tenant | `RiskManager`+ | Convenience RPC endpoint for formal approval sign-off |
| **Approvals** | `GET` | `/api/v1/approvals` | Child | `Viewer`+ | Paginated list scoped via parent recommendation |
| **Approvals** | `POST` | `/api/v1/approvals` | Child | `RiskManager`+ | Record formal human-in-the-loop sign-off |
| **Approvals** | `GET` | `/api/v1/approvals/{id}` | Child | `Viewer`+ | Single approval retrieval verifying tenant parent |
| **Actions** | `GET` | `/api/v1/actions` | Tenant | `Viewer`+ | Paginated list of operational mitigation execution records |
| **Actions** | `POST` | `/api/v1/actions` | Tenant | `RiskManager`+ | Create operational mitigation action record |
| **Actions** | `GET` | `/api/v1/actions/{id}` | Tenant | `Viewer`+ | Single action retrieval with 404 masking |
| **Actions** | `PATCH`| `/api/v1/actions/{id}` | Tenant | `RiskManager`+ | Update status or execution result payload |
| **Actions** | `POST` | `/api/v1/actions/{id}/execute` | Tenant | `RiskManager`+ | Trigger state machine execution progression |
| **Verification Results** | `GET` | `/api/v1/verification-results` | Child | `Viewer`+ | Paginated list scoped via parent action |
| **Verification Results** | `POST` | `/api/v1/verification-results` | Child | `RiskManager`+ | Record immutable post-action verification outcome |
| **Verification Results** | `GET` | `/api/v1/verification-results/{id}`| Child | `Viewer`+ | Single verification result retrieval verifying tenant parent |
| **Audit Logs** | `GET` | `/api/v1/audit-logs` | Tenant | `RiskManager`+ | Paginated compliance audit log list |
| **Audit Logs** | `GET` | `/api/v1/audit-logs/{id}` | Tenant | `RiskManager`+ | Single audit log record retrieval |
| **Notifications** | `GET` | `/api/v1/notifications` | Tenant/User | `Viewer`+ | List alerts for authenticated user or tenant broadcast |
| **Notifications** | `POST` | `/api/v1/notifications` | Tenant/User | `Admin` | Record alert or notification entry |
| **Notifications** | `GET` | `/api/v1/notifications/{id}` | Tenant/User | `Viewer`+ | Single alert retrieval scoped to user or broadcast |
| **Notifications** | `PATCH`| `/api/v1/notifications/{id}` | Tenant/User | `Viewer`+ | Update read status (`is_read = true`) |
| **Notifications** | `POST` | `/api/v1/notifications/mark-all-read` | Tenant/User | `Viewer`+ | Batch mark all notifications for current user as read |

---

## 3. Data Access & Repository Architecture

All 5 new repositories inherit from `BaseRepository[T]` and are registered with `UnitOfWork`:

1. **`RecommendationRepository` (`api/app/repositories/governance_repositories.py`)**:
   - Explicit SEARCH allowlist: `title`, `rationale`
   - Explicit SORT allowlist: `created_at`, `confidence`, `estimated_cost`, `title`, `status`
   - Explicit FILTER allowlist: `incident_id`, `status`
   - Concurrency locking helper: `get_for_update(id, org_id)` (`SELECT ... FOR UPDATE`)

2. **`ApprovalRepository` (`api/app/repositories/governance_repositories.py`)**:
   - Child entity scoped hierarchically through `recommendation.org_id`
   - Explicit SEARCH allowlist: `decision`, `comments`
   - Explicit SORT allowlist: `decided_at`, `decision`
   - Explicit FILTER allowlist: `recommendation_id`, `decision`, `decided_by_user_id`
   - Scoped lookup helpers: `get_approval_in_org(id, org_id)`, `list_approvals_for_org(...)`
   - Immutability guards: `update()` and `delete()` raise `ImmutableResourceError`

3. **`ActionRepository` (`api/app/repositories/governance_repositories.py`)**:
   - Explicit SEARCH allowlist: `action_type`, `target_entity_type`, `target_entity_id`
   - Explicit SORT allowlist: `executed_at`, `status`, `action_type`
   - Explicit FILTER allowlist: `status`, `action_type`, `target_entity_type`, `recommendation_id`
   - Concurrency locking helper: `get_for_update(id, org_id)`

4. **`VerificationResultRepository` (`api/app/repositories/governance_repositories.py`)**:
   - Child entity scoped hierarchically through `action.org_id`
   - Explicit SEARCH allowlist: `observation_summary`
   - Explicit SORT allowlist: `verified_at`, `verified`, `risk_score_after`
   - Explicit FILTER allowlist: `action_id`, `verified`
   - Scoped lookup helpers: `get_result_in_org(id, org_id)`, `get_by_action_id_in_org(action_id, org_id)`, `list_results_for_org(...)`
   - Immutability guards: `update()` and `delete()` raise `ImmutableResourceError`

5. **`NotificationRepository` (`api/app/repositories/governance_repositories.py`)**:
   - Explicit SEARCH allowlist: `title`, `summary`, `category`
   - Explicit SORT allowlist: `created_at`, `severity`, `category`
   - Explicit FILTER allowlist: `category`, `severity`, `is_read`, `user_id`
   - User/Broadcast scoping: `list_for_user(org_id, user_id, ...)` matches `user_id == context.user_id` or `user_id IS NULL`
   - Atomic batch update: `mark_all_read_for_user(org_id, user_id)`

6. **`AuditLogRepository` (`api/app/repositories/audit_log.py`)**:
   - Immutable append-only audit trail query repository with filtering by `actor_type`, `action`, `resource_type`, `status`, and sorting by `timestamp`.

---

## 4. Service Layer & Business Invariants

The services encapsulate all state transitions, relationship checks, and audit emission:

### Recommendation Service (`RecommendationService`)
- **Parent Validation:** If `incident_id` is supplied, verifies that the incident exists in the same organization. Cross-tenant or non-existent IDs raise `NotFoundError(404)`.
- **Lifecycle Enforcing:** Recommendations in finalized states (`APPROVED`, `REJECTED`, `EXECUTED`) reject arbitrary updates with `LifecycleStateError(409)`.
- **Deletion Protection:** Hard DELETE is unsupported (`405 Method Not Allowed`).

### Approval Service (`ApprovalService`)
- **Row-Level Concurrency Lock:** Acquires an exclusive `SELECT ... FOR UPDATE` row lock on the target recommendation to guarantee that two concurrent requests cannot produce dual decisions.
- **State Transition Guard:** Only `PENDING` recommendations can be decided. Attempting to approve or reject an already decided recommendation raises `LifecycleStateError(409)`.
- **Atomic Transition:**
  - `APPROVE` $\rightarrow$ `recommendation.status = "APPROVED"`
  - `REJECT` $\rightarrow$ `recommendation.status = "REJECTED"`
  - `REQUEST_MODIFICATION` $\rightarrow$ `recommendation.status = "PENDING"`
- **Strict Immutability:** Approvals are immutable historical sign-offs; PATCH/DELETE return `405 Method Not Allowed`.

### Action Service (`ActionService`)
- **Prerequisite Validation:** If an action is linked to a recommendation (`recommendation_id`), the recommendation must exist in the tenant and be in `APPROVED` status. Linking an action to a `PENDING` or `REJECTED` recommendation raises `LifecycleStateError(409)`.
- **Execution Transitions:**
  - `PENDING` $\rightarrow$ `EXECUTING` $\rightarrow$ `COMPLETED` or `FAILED`
  - When an action reaches `COMPLETED`, if it is linked to a recommendation, the recommendation's status is atomically updated to `EXECUTED`.
  - Terminal states `COMPLETED` and `FAILED` cannot transition further (`LifecycleStateError(409)`).

### Verification Result Service (`VerificationResultService`)
- **Action Validation:** Verifies that parent `action_id` exists within the authenticated tenant.
- **Single Verification Rule:** 1:1 relationship between `Action` and `VerificationResult`. Duplicate attempts return `ConflictError(409)`.
- **Strict Immutability:** Verification results are observational records; PATCH/DELETE return `405 Method Not Allowed`.

### Notification Service (`NotificationService`)
- **User & Broadcast Scoping:** Users can only list and update alerts addressed to them or marked as tenant-wide broadcasts (`user_id IS NULL`).
- **Batch Mark-All-Read:** Atomic SQL update efficiently marks all unread notifications for the user as read.

### Audit Log Query Service (`AuditLogQueryService`)
- Read-only interface restricted to `RiskManager` and `Admin`.
- Mutations across recommendations, approvals, actions, verification results, and notifications automatically emit entries to `audit_logs` with sanitized payloads.

---

## 5. RBAC Permission Matrix

| Role | Recommendations | Approvals | Actions | Verification Results | Notifications | Audit Logs |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Viewer** | Read-only (`GET`) | Read-only (`GET`) | Read-only (`GET`) | Read-only (`GET`) | Read / Mark Read (`GET`, `PATCH`, `POST /mark-all-read`) | Denied (`403`) |
| **Analyst** | Read + Write (`GET`, `POST`, `PATCH`) | Read-only (`GET`) | Read-only (`GET`) | Read-only (`GET`) | Read / Mark Read | Denied (`403`) |
| **OpsManager** | Read-only (`GET`) | Read-only (`GET`) | Read-only (`GET`) | Read-only (`GET`) | Read / Mark Read | Denied (`403`) |
| **RiskManager** | Read + Write + Approve | Full (`GET`, `POST`) | Full (`GET`, `POST`, `PATCH`, `POST /execute`) | Full (`GET`, `POST`) | Read / Mark Read | Read-only (`GET`) |
| **Admin** | Full | Full | Full | Full | Full (`POST` alerts) | Read-only (`GET`) |

---

## 6. Verification & Test Results

A comprehensive, dedicated test suite was implemented in `api/tests/test_decision_governance_api.py`.

### Test Suite Execution
```bash
api/.venv/Scripts/python.exe -m pytest api/tests/test_decision_governance_api.py -v
```
**Results:** **30 passed in 7.70s (100% pass rate)**

### Full Regression Test Suite
```bash
api/.venv/Scripts/python.exe -m pytest api/tests -q
```
**Results:** **267 passed, 1 skipped (live RDS network probe guard) in 42.54s**  
- **0 regressions**
- **0 duplicate routes**
- **0 duplicate operation IDs** (96 globally unique operations verified across 60 endpoints)
- **0 database schema modifications / 0 new migrations**
