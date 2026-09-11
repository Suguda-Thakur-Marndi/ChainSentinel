# RiskWise 2.0 Core API Service Layer & Repository Foundations

**Document Version:** 2.0.0  
**Phase:** Phase 4 — Core APIs (Step 2 — Service Layer & Repository Foundations)  
**Status:** IMPLEMENTED & VALIDATED  
**Authoritative Backend:** FastAPI (`api`), SQLAlchemy 2.0, PostgreSQL 16 (RDS `ap-southeast-2`), Redis/Valkey Session Cache  

---

## 1. Architecture

RiskWise 2.0 follows an enterprise, layered clean architecture designed to decouple HTTP transport and protocol validation from business logic and database persistence:

```
┌────────────────────────────────────────────────────────┐
│                   FastAPI Routers                      │
│     (Route Definitions, Request/Response Schema DTOs)  │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│           Authentication & Context Resolution          │
│    (Session Cookie -> AuthenticatedContext, RBAC)      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                    Service Layer                       │
│ (BaseService, Business Rules, State Machines, Auditing)│
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│               Unit of Work (Transaction)               │
│     (Atomic Commit / Rollback, Coordinated Repos)      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Repository Layer                     │
│  (BaseRepository, PortRepo, AuditLogRepo, Safe Queries)│
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                     SQLAlchemy                         │
│       (Declarative ORM Models, Prepared Statements)    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                 PostgreSQL 16 (RDS)                    │
│      (34 Authoritative Tables, Foreign Keys, Indexes)  │
└────────────────────────────────────────────────────────┘
```

### Core Principles
1. **Separation of Concerns:** Routers parse HTTP requests; Services enforce business validation and state rules; Repositories execute database queries; Models map database tables.
2. **Never Scatter Commits:** Business operations spanning multiple writes are executed atomically inside a Unit of Work transaction boundary.
3. **Strict Tenancy Isolation:** The client never dictates tenant boundaries. The server extracts `context.organization_id` from the authenticated session.
4. **Authoritative Database:** The existing PostgreSQL schema from Phase 2 is immutable and authoritative.

---

## 2. Repository Pattern

The repository layer abstracts data access for SQLAlchemy 2.0 entities. It provides standard CRUD methods without coupling callers to raw SQL queries or session details:

### Location: `api/app/repositories/base.py`

```python
class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], session: Session):
        self.model = model
        self.session = session

    def get(self, id: str, org_id: Optional[str] = None) -> Optional[ModelType]: ...
    def get_or_404(self, id: str, org_id: Optional[str] = None) -> ModelType: ...
    def list(self, org_id: Optional[str] = None, page: int = 1, limit: int = 20, ...) -> list[ModelType]: ...
    def count(self, org_id: Optional[str] = None, filters: Optional[dict] = None, ...) -> int: ...
    def create(self, entity: ModelType, auto_commit: bool = True) -> ModelType: ...
    def update(self, entity: ModelType, auto_commit: bool = True) -> ModelType: ...
    def delete(self, id: str, org_id: Optional[str] = None, auto_commit: bool = True) -> bool: ...
    def exists(self, id: str, org_id: Optional[str] = None) -> bool: ...
    def find_one(self, org_id: Optional[str] = None, **criteria: Any) -> Optional[ModelType]: ...
```

### Auto-Commit vs Transaction Mode
- `auto_commit=True`: Commits immediately on individual writes (preserves backwards-compatibility for existing tests and standalone repository operations).
- `auto_commit=False`: Performs `session.flush()`, deferring the final commit to the service or Unit of Work transaction boundary.

---

## 3. Service Pattern

The service layer contains business workflows, lifecycle rules, cross-table coordination, and authorization checks. Routers must never execute raw database operations directly.

### Location: `api/app/services/base.py`

```python
class BaseService(Generic[ModelType]):
    def __init__(
        self,
        model: Type[ModelType],
        uow: UnitOfWork,
        context: Optional[AuthenticatedContext] = None,
    ):
        self.model = model
        self.uow = uow
        self.context = context
        self.scope = get_resource_scope(model)

    def get_by_id(self, id: str) -> ModelType: ...
    def list_paginated(self, params: PaginationParams, ...) -> PaginatedResponse[Any]: ...
    def create(self, schema_in: BaseModel | dict[str, Any], auto_commit: bool = True) -> ModelType: ...
    def update(self, id: str, schema_in: BaseModel | dict[str, Any], auto_commit: bool = True) -> ModelType: ...
    def delete(self, id: str, auto_commit: bool = True) -> bool: ...
```

### Lifecycle Rules Enforced by BaseService:
1. **Immutable Ledgers (`shipment_events`, `inventory_movements`, `audit_logs`, `verification_results`):**
   - Mutation (`update`) and deletion (`delete`) raise `ImmutableResourceError` (HTTP 405).
2. **Operational Entities (`suppliers`, `shipments`, `inventory`):**
   - Hard deletion (`delete`) raises `LifecycleStateError` (HTTP 409). Clients must execute status transitions (e.g., `status = 'INACTIVE'`).
3. **Ephemeral Entities (`scenarios`, `twin_nodes`, `documents`):**
   - Hard deletion is permitted with tenant boundary verification.

---

## 4. Unit of Work

The Unit of Work pattern coordinates database transactions and repositories across an atomic business workflow.

### Location: `api/app/db/unit_of_work.py`

```python
class UnitOfWork:
    def __init__(self, session: Session):
        self.session = session
        ...

    @property
    def suppliers(self) -> SupplierRepository: ...
    @property
    def shipments(self) -> ShipmentRepository: ...
    @property
    def ports(self) -> PortRepository: ...
    @property
    def audit_logs(self) -> AuditLogRepository: ...
    def repository(self, model: Type[T]) -> BaseRepository[T]: ...

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def flush(self) -> None: ...
```

### Context Manager Usage
```python
with uow:
    supplier = uow.suppliers.create(supplier_entity, auto_commit=False)
    uow.audit_logs.append_log(
        org_id=context.organization_id,
        actor_id=context.user_id,
        action="CREATE",
        resource_type="Supplier",
        resource_id=supplier.id,
        auto_commit=False,
    )
    uow.commit()
```
If an exception occurs within the `with uow:` block, `__exit__` automatically rolls back the entire transaction.

---

## 5. Transaction Boundaries

1. **Atomic Multi-Writes:** A business operation that modifies more than one table (or writes an audit event alongside an operational change) must be committed once at the service boundary.
2. **No Scattered Commits:** Individual repository helper methods called during a composite transaction use `auto_commit=False` (`flush()` only).
3. **Rollback on Error:** Any exception (SQLAlchemy error, domain validation failure) triggers a full session rollback before the error is converted into an HTTP error response.

---

## 6. Dependency Injection

FastAPI dependency injection is utilized end-to-end to ensure clean lifecycle management and testability:

```python
@router.get("/api/v1/suppliers/{id}", response_model=SupplierResponse)
def get_supplier(
    id: str,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    uow: UnitOfWork = Depends(get_uow),
):
    service = SupplierService(uow=uow, context=context)
    return service.get_by_id(id)
```

- `get_db`: Yields SQLAlchemy `Session`.
- `get_uow`: Yields `UnitOfWork` bound to the active request `Session`.
- `get_authenticated_context`: Resolves `User`, `Organization`, and role from the session cookie.
- `require_role(*roles)`: Enforces RBAC permissions before route execution.

---

## 7. Tenant Isolation

RiskWise 2.0 enforces strict multi-tenant boundary isolation at the data access layer:

### Implementation Principles
1. **Never Trust Client Inputs:** Query parameters, headers, or body fields containing `org_id` are never trusted. Client request schemas forbid `org_id` (`extra = 'forbid'`).
2. **Server-Derived Context:** The organization boundary is extracted from `context.organization_id` provided by `get_authenticated_context`.
3. **Query Filtering:** For all tenant-owned models, repository queries apply:
   ```python
   stmt = stmt.where(model.org_id == context.organization_id)
   ```
4. **Cross-Tenant Masking (404 vs 403):** If an authenticated user queries a resource ID that exists in another tenant's database partition, the API returns `404 Not Found` (never `403 Forbidden`). This eliminates ID enumeration attacks.

---

## 8. Global Resources

RiskWise contains shared reference catalogs that must **not** be partitioned by tenant.

### Classification Table:
| Scope | Table Count | Example Tables | Isolation Policy |
| :--- | :--- | :--- | :--- |
| **GLOBAL** | 1 | `ports` | Shared reference data; read-only to all authenticated tenants; never filtered by `org_id`. |
| **SYSTEM** | 1 | `organizations` | System root entity; restricted to tenant's own profile or system administrators. |
| **TENANT** | 24 | `suppliers`, `shipments`, `risks`, `inventory` | Strictly scoped via `model.org_id == context.organization_id`. |
| **CHILD** | 8 | `shipment_events`, `approvals`, `simulations` | Hierarchically scoped through foreign key relationship to parent tenant record. |

In `api/app/repositories/query_utils.py`, `apply_tenant_isolation` inspects `get_resource_scope(model)`. If the scope is `GLOBAL`, tenant filtering is safely skipped.

---

## 9. Pagination

Collections implement the Phase 4 Step 1 standard:
- Query Parameters: `page` (default `1`, min `1`), `limit` (default `20`, min `1`, max `100`).
- Slicing: `stmt.offset((page - 1) * limit).limit(limit)`.
- Metadata Calculation:
  - `total`: Total matching records.
  - `pages`: `(total + limit - 1) // limit if total > 0 else 0`.
- Response Envelope:
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

---

## 10. Safe Filtering

Filtering utilizes explicit allowlists mapping query parameters to SQLAlchemy model columns.

### Location: `api/app/repositories/query_utils.py`

- **Exact Equality:** `status="IN_TRANSIT"` -> `stmt.where(Model.status == "IN_TRANSIT")`
- **Timestamp Ranges:**
  - `created_at_after="2026-08-01T00:00:00Z"` -> `stmt.where(Model.created_at >= parsed_date)`
  - `created_at_before="2026-08-31T23:59:59Z"` -> `stmt.where(Model.created_at <= parsed_date)`
- **Allowlist Enforcement:** Unapproved filter fields raise `InvalidFilterFieldError` (HTTP 400).

---

## 11. Safe Sorting

Sorting prevents SQL injection by mapping client sort expressions to approved model columns.

### Conventions:
- Ascending: `sort="name"` or `sort="+name"`
- Descending: `sort="-created_at"`
- Validation: Sort keys are validated against `sort_allowlist`. Unknown sort fields raise `InvalidSortFieldError` (HTTP 400) with error code `INVALID_SORT_FIELD`.

---

## 12. Safe Search

Search executes safe, case-insensitive substring pattern matching across approved textual attributes (e.g. `name`, `code`, `tracking_number`).

### Wildcard Escaping:
Special SQL LIKE wildcard characters (`%`, `_`, `\`) are escaped via `escape_like_wildcards`:
```python
escaped = re.sub(r"([%_\\])", r"\\\1", term)
col.ilike(f"%{escaped}%", escape="\\")
```
This ensures client searches for literal terms like `"100%"` do not trigger arbitrary wildcard matching.

---

## 13. Standardized Error Handling

All domain exceptions inherit from `AppError` and produce the standardized error payload:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Supplier not found",
    "details": {
      "resource_type": "Supplier",
      "resource_id": "sup_9b2e84c1"
    }
  }
}
```

### Exception Hierarchy:
| Exception | HTTP Status | Error Code | Description |
| :--- | :--- | :--- | :--- |
| `NotFoundError` | 404 | `RESOURCE_NOT_FOUND` | Record missing or cross-tenant masked |
| `ConflictError` | 409 | `CONFLICT` | State conflict or duplicate key |
| `ValidationDomainError` | 400 | `VALIDATION_ERROR` | Business rule validation failure |
| `InvalidSortFieldError` | 400 | `INVALID_SORT_FIELD` | Requested sort column not allowed |
| `InvalidFilterFieldError`| 400 | `INVALID_FILTER_FIELD`| Requested filter column not allowed |
| `AuthorizationError` | 403 | `FORBIDDEN` | Insufficient role or inactive account |
| `AuthenticationError` | 401 | `UNAUTHORIZED` | Invalid or missing session |
| `ImmutableResourceError`| 405 | `IMMUTABLE_RESOURCE` | Attempted write/delete on ledger |
| `LifecycleStateError` | 409 | `INVALID_STATE_TRANSITION` | Attempted illegal status transition |
| `DatabaseError` | 500 | `DATABASE_ERROR` | Sanitized database error |

---

## 14. Concurrency Controls

Foundations for concurrency management are established in `api/app/services/concurrency.py`:

1. **Pessimistic Row Locking:**
   ```python
   entity = get_with_for_update(session, Recommendation, recommendation_id, org_id)
   ```
   Locks the database row using `SELECT ... FOR UPDATE`, ensuring serial execution during critical state changes (e.g., recommendation approval).
2. **Atomic In-Database Numeric Adjustments:**
   ```python
   atomic_adjust_numeric(session, Warehouse, warehouse_id, "current_occupancy", delta=50.0)
   ```
   Uses `UPDATE warehouse SET current_occupancy = current_occupancy + delta` to eliminate read-modify-write race conditions.
3. **State Transition Validation:**
   ```python
   validate_state_transition(current_status, target_status, allowed_transitions_dict)
   ```

---

## 15. Audit Hooks

Audit logging is centralized in `api/app/services/audit_service.py`.

### Security & Sanitization:
The audit logger recursively scrubs credentials and secrets before writing to the database:
- Scrubbed patterns: `password`, `secret`, `token`, `api_key`, `credentials`, `authorization`, `cookie`.
- Replaced with: `"[REDACTED]"`.
- Persisted to: `audit_logs` table via the current Unit of Work transaction.

---

## 16. Testing Strategy

1. **Isolation & Safety:** Foundation unit tests run against in-memory SQLite (`StaticPool`). Destructive tests are never executed against live RDS.
2. **20 Foundation Verification Points:**
   - Repository: Get, List, Count, Create, Update
   - Tenant isolation & cross-tenant masking
   - Global resource handling
   - Pagination, Filtering, Sorting, Search with escaping
   - Unit of Work atomic commit & rollback
   - Service validation, state conflicts, immutable resource protection, operational deletion rules
   - Authorization integration & secret scrubbing in audit logs
3. **Full Regression Validation:** 134 automated tests (133 passed, 1 skipped) verify 100% test integrity and zero regressions against Phase 1, Phase 2, and Phase 3 baselines.
