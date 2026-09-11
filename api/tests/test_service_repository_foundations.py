"""Comprehensive tests for RiskWise 2.0 Service Layer & Repository Foundations (Phase 4 Step 2).

Tests:
 1. Repository get
 2. Repository list
 3. Repository count
 4. Repository create
 5. Repository update
 6. Tenant isolation
 7. Global resource handling (Port)
 8. Pagination calculation & metadata
 9. Filtering allowlist & date range (_after/_before)
10. Sorting allowlist & order direction (+/-)
11. Search across approved text columns & wildcard escaping
12. Not-found behavior (cross-tenant masking with 404)
13. Transaction commit (UnitOfWork atomic multi-write)
14. Transaction rollback (UnitOfWork exception recovery)
15. Service validation & business rules
16. Conflict handling
17. Immutable resource protection (ShipmentEvent, AuditLog)
18. Operational lifecycle / deletion rules
19. Authorization integration (AuthenticatedContext)
20. Error mapping & security sanitization
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.context import AuthenticatedContext
from app.core.errors import (
    AuthorizationError,
    ConflictError,
    ImmutableResourceError,
    InvalidFilterFieldError,
    InvalidSortFieldError,
    LifecycleStateError,
    NotFoundError,
    ValidationDomainError,
)
from app.db.base import Base
from app.db.unit_of_work import UnitOfWork
from app.models.governance import AuditLog
from app.models.logistics import Shipment, ShipmentEvent
from app.models.network import Port, Supplier
from app.models.tenancy import Organization, User
from app.repositories.audit_log import AuditLogRepository
from app.repositories.base import BaseRepository
from app.repositories.port import PortRepository
from app.repositories.query_utils import (
    ResourceScope,
    apply_filters,
    apply_pagination,
    apply_search,
    apply_sorting,
    apply_tenant_isolation,
    escape_like_wildcards,
    get_resource_scope,
)
from app.repositories.shipment import ShipmentRepository
from app.repositories.supplier import SupplierRepository
from app.schemas.common import PaginationParams
from app.schemas.session import SessionData
from app.services.audit_service import AuditService, sanitize_payload
from app.services.base import BaseService
from app.services.concurrency import (
    atomic_adjust_numeric,
    get_with_for_update,
    validate_state_transition,
)


@pytest.fixture(scope="function")
def db_session():
    """Isolated in-memory SQLite database session for unit tests (zero RDS interaction)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def uow(db_session: Session):
    """Unit of Work fixture bound to test session."""
    return UnitOfWork(db_session)


@pytest.fixture(scope="function")
def tenant_context_a():
    """Mock AuthenticatedContext for Organization A."""
    user = User(
        id="usr_test_a_01",
        email="analyst.a@riskwise.test",
        full_name="Analyst Org A",
        role="Analyst",
        org_id="org_alpha_101",
        is_active=True,
    )
    session_data = SessionData(
        session_id="sess_test_a",
        user_id=user.id,
        email=user.email,
        role=user.role,
        organization_id=user.org_id,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    return AuthenticatedContext(user=user, session_data=session_data)


@pytest.fixture(scope="function")
def tenant_context_b():
    """Mock AuthenticatedContext for Organization B."""
    user = User(
        id="usr_test_b_01",
        email="analyst.b@riskwise.test",
        full_name="Analyst Org B",
        role="Analyst",
        org_id="org_beta_202",
        is_active=True,
    )
    session_data = SessionData(
        session_id="sess_test_b",
        user_id=user.id,
        email=user.email,
        role=user.role,
        organization_id=user.org_id,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc),
    )
    return AuthenticatedContext(user=user, session_data=session_data)


# ==============================================================================
# 1. REPOSITORY GET
# ==============================================================================
def test_1_repository_get(db_session: Session):
    """1. Test repository get retrieves entity by ID within tenant scope."""
    repo = BaseRepository(Supplier, db_session)
    supplier = Supplier(
        id="sup_get_01",
        org_id="org_alpha_101",
        name="Get Test Supplier",
        code="GET-01",
    )
    repo.create(supplier)

    found = repo.get("sup_get_01", org_id="org_alpha_101")
    assert found is not None
    assert found.id == "sup_get_01"
    assert found.name == "Get Test Supplier"

    not_found = repo.get("sup_non_existent", org_id="org_alpha_101")
    assert not_found is None


# ==============================================================================
# 2. REPOSITORY LIST
# ==============================================================================
def test_2_repository_list(db_session: Session):
    """2. Test repository list applies pagination and ordering."""
    repo = BaseRepository(Supplier, db_session)
    for i in range(5):
        repo.create(
            Supplier(
                id=f"sup_list_{i}",
                org_id="org_alpha_101",
                name=f"Supplier {i}",
                code=f"SUP-{i:03d}",
            )
        )

    results = repo.list(org_id="org_alpha_101", page=1, limit=3)
    assert len(results) == 3

    results_page_2 = repo.list(org_id="org_alpha_101", page=2, limit=3)
    assert len(results_page_2) == 2


# ==============================================================================
# 3. REPOSITORY COUNT
# ==============================================================================
def test_3_repository_count(db_session: Session):
    """3. Test repository count reflects total matching entities within tenant."""
    repo = BaseRepository(Supplier, db_session)
    for i in range(4):
        repo.create(Supplier(id=f"sup_count_a_{i}", org_id="org_alpha_101", name=f"Org A {i}"))
    repo.create(Supplier(id="sup_count_b_01", org_id="org_beta_202", name="Org B 01"))

    assert repo.count(org_id="org_alpha_101") == 4
    assert repo.count(org_id="org_beta_202") == 1


# ==============================================================================
# 4. REPOSITORY CREATE
# ==============================================================================
def test_4_repository_create(db_session: Session):
    """4. Test repository create successfully persists entity with session commit."""
    repo = BaseRepository(Supplier, db_session)
    supplier = Supplier(
        id="sup_create_01",
        org_id="org_alpha_101",
        name="Newly Created Supplier",
        code="NEW-01",
        tier="CRITICAL",
    )
    created = repo.create(supplier)
    assert created.id == "sup_create_01"
    assert created.tier == "CRITICAL"

    persisted = repo.get("sup_create_01")
    assert persisted is not None
    assert persisted.name == "Newly Created Supplier"


# ==============================================================================
# 5. REPOSITORY UPDATE
# ==============================================================================
def test_5_repository_update(db_session: Session):
    """5. Test repository update modifies entity attributes reliably."""
    repo = BaseRepository(Supplier, db_session)
    supplier = Supplier(
        id="sup_update_01",
        org_id="org_alpha_101",
        name="Pre-Update Supplier",
        reliability_score=80.0,
    )
    repo.create(supplier)

    supplier.reliability_score = 95.5
    supplier.name = "Post-Update Supplier"
    updated = repo.update(supplier)

    assert updated.reliability_score == 95.5
    assert updated.name == "Post-Update Supplier"

    re_retrieved = repo.get("sup_update_01")
    assert re_retrieved.reliability_score == 95.5


# ==============================================================================
# 6. TENANT ISOLATION
# ==============================================================================
def test_6_tenant_isolation(db_session: Session):
    """6. Test tenant isolation ensures queries never return cross-tenant data."""
    repo = BaseRepository(Supplier, db_session)
    repo.create(Supplier(id="sup_tenant_a", org_id="org_alpha_101", name="Alpha Supplier"))
    repo.create(Supplier(id="sup_tenant_b", org_id="org_beta_202", name="Beta Supplier"))

    # Org A should only see Org A
    org_a_items = repo.list(org_id="org_alpha_101")
    assert len(org_a_items) == 1
    assert org_a_items[0].id == "sup_tenant_a"

    # Org B querying Org A record by ID returns None (not found)
    cross_tenant_get = repo.get("sup_tenant_a", org_id="org_beta_202")
    assert cross_tenant_get is None

    # Missing org_id for tenant-scoped query raises AuthorizationError
    with pytest.raises(AuthorizationError) as exc_info:
        apply_tenant_isolation(None, Supplier, org_id=None)
    assert "Tenant organization context is required" in str(exc_info.value)


# ==============================================================================
# 7. GLOBAL RESOURCE HANDLING (PORT)
# ==============================================================================
def test_7_global_resource_handling(db_session: Session):
    """7. Test global resource Port is accessible without org_id and scope is GLOBAL."""
    assert get_resource_scope(Port) == ResourceScope.GLOBAL
    assert get_resource_scope(Supplier) == ResourceScope.TENANT

    port_repo = PortRepository(db_session)
    port_repo.create(
        Port(
            id="port_sin_01",
            code="SGSIN",
            name="Port of Singapore",
            country="Singapore",
            port_type="SEA",
            congestion_score=35.0,
        )
    )

    # Port can be queried without org_id
    port = port_repo.get("port_sin_01")
    assert port is not None
    assert port.name == "Port of Singapore"

    # Listing ports does not filter by org_id
    ports = port_repo.list_ports()
    assert len(ports) == 1
    assert ports[0].code == "SGSIN"


# ==============================================================================
# 8. PAGINATION
# ==============================================================================
def test_8_pagination_calculation_and_metadata(uow: UnitOfWork, tenant_context_a: AuthenticatedContext):
    """8. Test BaseService pagination calculations (total, page, limit, pages)."""
    service = BaseService(Supplier, uow, tenant_context_a)
    for i in range(25):
        service.create({"id": f"sup_p_{i:02d}", "name": f"Supplier {i:02d}"})

    params = PaginationParams(page=2, limit=10)
    response = service.list_paginated(params)

    assert response.pagination.total == 25
    assert response.pagination.page == 2
    assert response.pagination.limit == 10
    assert response.pagination.pages == 3
    assert len(response.items) == 10


# ==============================================================================
# 9. FILTERING ALLOWLIST & DATE RANGE
# ==============================================================================
def test_9_filtering_allowlist_and_dates(db_session: Session):
    """9. Test safe filtering, date ranges (_after, _before), and rejection of invalid fields."""
    repo = BaseRepository(Supplier, db_session)
    allowlist = {
        "country": Supplier.country,
        "tier": Supplier.tier,
        "created_at_after": Supplier.created_at,
        "created_at_before": Supplier.created_at,
    }

    t1 = datetime(2026, 8, 1, 10, 0, 0)
    t2 = datetime(2026, 8, 15, 10, 0, 0)
    t3 = datetime(2026, 9, 1, 10, 0, 0)

    repo.create(Supplier(id="s1", org_id="org_alpha_101", name="S1", country="TW", tier="CRITICAL", created_at=t1))
    repo.create(Supplier(id="s2", org_id="org_alpha_101", name="S2", country="TW", tier="MEDIUM", created_at=t2))
    repo.create(Supplier(id="s3", org_id="org_alpha_101", name="S3", country="US", tier="CRITICAL", created_at=t3))

    # Exact filter
    tw_critical = repo.list(org_id="org_alpha_101", filters={"country": "TW", "tier": "CRITICAL"}, filter_allowlist=allowlist)
    assert len(tw_critical) == 1
    assert tw_critical[0].id == "s1"

    # Date range filter
    date_filtered = repo.list(
        org_id="org_alpha_101",
        filters={"created_at_after": "2026-08-10T00:00:00Z"},
        filter_allowlist=allowlist,
    )
    assert len(date_filtered) == 2

    # Reject unapproved filter field
    with pytest.raises(InvalidFilterFieldError) as exc_info:
        repo.list(org_id="org_alpha_101", filters={"malicious_column": "x"}, filter_allowlist=allowlist)
    assert exc_info.value.code == "INVALID_FILTER_FIELD"


# ==============================================================================
# 10. SORTING ALLOWLIST
# ==============================================================================
def test_10_sorting_allowlist(db_session: Session):
    """10. Test safe sorting allowlist (+/- syntax) and rejection of invalid sort fields."""
    repo = BaseRepository(Supplier, db_session)
    sort_allowlist = {
        "name": Supplier.name,
        "reliability_score": Supplier.reliability_score,
        "created_at": Supplier.created_at,
    }

    repo.create(Supplier(id="s_a", org_id="org_alpha_101", name="Alpha Corp", reliability_score=85.0))
    repo.create(Supplier(id="s_b", org_id="org_alpha_101", name="Beta Corp", reliability_score=95.0))

    # Ascending sort
    asc_res = repo.list(org_id="org_alpha_101", sort_param="name", sort_allowlist=sort_allowlist)
    assert asc_res[0].name == "Alpha Corp"

    # Descending sort
    desc_res = repo.list(org_id="org_alpha_101", sort_param="-reliability_score", sort_allowlist=sort_allowlist)
    assert desc_res[0].reliability_score == 95.0

    # Reject invalid sort field
    with pytest.raises(InvalidSortFieldError) as exc_info:
        repo.list(org_id="org_alpha_101", sort_param="password_hash", sort_allowlist=sort_allowlist)
    assert exc_info.value.code == "INVALID_SORT_FIELD"


# ==============================================================================
# 11. SEARCH & WILDCARD ESCAPING
# ==============================================================================
def test_11_search_and_wildcard_escaping(db_session: Session):
    """11. Test substring search and escaping of SQL wildcard symbols (%, _)."""
    repo = BaseRepository(Supplier, db_session)
    search_cols = ["name", "code"]

    repo.create(Supplier(id="s1", org_id="org_alpha_101", name="Global Logistics 100%", code="GL-01"))
    repo.create(Supplier(id="s2", org_id="org_alpha_101", name="Global Logistics Ordinary", code="GL-02"))

    # Wildcard escaping check
    assert escape_like_wildcards("100%_pure") == "100\\%\\_pure"

    # Searching exact literal 100% should only match s1, not s2
    res = repo.list(org_id="org_alpha_101", search="100%", search_columns=search_cols)
    assert len(res) == 1
    assert res[0].id == "s1"


# ==============================================================================
# 12. NOT-FOUND BEHAVIOR (CROSS-TENANT MASKING)
# ==============================================================================
def test_12_not_found_behavior(uow: UnitOfWork, tenant_context_a: AuthenticatedContext, tenant_context_b: AuthenticatedContext):
    """12. Test that cross-tenant access returns 404 (RESOURCE_NOT_FOUND), never leaking existence."""
    service_a = BaseService(Supplier, uow, tenant_context_a)
    service_b = BaseService(Supplier, uow, tenant_context_b)

    service_a.create({"id": "sup_secret_a", "name": "Secret Supplier A"})

    # Non-existent ID returns 404
    with pytest.raises(NotFoundError) as exc_info:
        service_a.get_by_id("non_existent_id")
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "RESOURCE_NOT_FOUND"

    # Cross-tenant ID returns 404 (does NOT return 403, preventing ID discovery)
    with pytest.raises(NotFoundError) as exc_info_cross:
        service_b.get_by_id("sup_secret_a")
    assert exc_info_cross.value.status_code == 404
    assert exc_info_cross.value.code == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 13. TRANSACTION COMMIT (UNIT OF WORK)
# ==============================================================================
def test_13_transaction_commit_unit_of_work(uow: UnitOfWork):
    """13. Test Unit of Work atomic multi-write commit."""
    with uow:
        s = Supplier(id="sup_uow_01", org_id="org_alpha_101", name="UoW Supplier")
        uow.suppliers.create(s, auto_commit=False)

        log = AuditLog(
            id="log_uow_01",
            org_id="org_alpha_101",
            actor_id="user_1",
            action="CREATE",
            resource_type="Supplier",
            resource_id="sup_uow_01",
        )
        uow.audit_logs.create(log, auto_commit=False)
        uow.commit()

    # Verify both writes were committed
    assert uow.suppliers.get("sup_uow_01") is not None
    assert uow.audit_logs.get("log_uow_01") is not None


# ==============================================================================
# 14. TRANSACTION ROLLBACK (UNIT OF WORK)
# ==============================================================================
def test_14_transaction_rollback_unit_of_work(uow: UnitOfWork):
    """14. Test Unit of Work rolls back all writes when an exception is raised."""
    try:
        with uow:
            s = Supplier(id="sup_rollback_01", org_id="org_alpha_101", name="Rollback Supplier")
            uow.suppliers.create(s, auto_commit=False)
            # Simulate unexpected failure before commit
            raise RuntimeError("Simulated failure in multi-write workflow")
    except RuntimeError:
        pass

    # Verify supplier was not persisted
    assert uow.suppliers.get("sup_rollback_01") is None


# ==============================================================================
# 15. SERVICE VALIDATION
# ==============================================================================
def test_15_service_validation():
    """15. Test domain business state machine validation."""
    allowed = {
        "PENDING": ["IN_REVIEW", "CANCELLED"],
        "IN_REVIEW": ["APPROVED", "REJECTED"],
        "APPROVED": ["EXECUTED"],
    }

    # Valid transition succeeds
    validate_state_transition("PENDING", "IN_REVIEW", allowed)

    # Invalid transition raises LifecycleStateError
    with pytest.raises(LifecycleStateError) as exc_info:
        validate_state_transition("PENDING", "EXECUTED", allowed)
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"


# ==============================================================================
# 16. CONFLICT HANDLING
# ==============================================================================
def test_16_conflict_handling():
    """16. Test ConflictError exception properties."""
    conflict = ConflictError(
        message="Recommendation is already approved",
        code="RECOMMENDATION_ALREADY_APPROVED",
        details={"recommendation_id": "rec_123"},
    )
    assert conflict.status_code == 409
    assert conflict.code == "RECOMMENDATION_ALREADY_APPROVED"
    assert conflict.details["recommendation_id"] == "rec_123"


# ==============================================================================
# 17. IMMUTABLE RESOURCE PROTECTION
# ==============================================================================
def test_17_immutable_resource_protection(uow: UnitOfWork, tenant_context_a: AuthenticatedContext):
    """17. Test that immutable ledger entities forbid update and deletion."""
    service = BaseService(AuditLog, uow, tenant_context_a)

    # Creating ledger entry is allowed
    log = service.create(
        {
            "id": "log_immut_01",
            "actor_id": "usr_01",
            "action": "LOGIN",
            "resource_type": "Session",
        }
    )
    assert log.id == "log_immut_01"

    # Updating ledger entry is forbidden
    with pytest.raises(ImmutableResourceError) as exc_update:
        service.update("log_immut_01", {"action": "LOGOUT"})
    assert exc_update.value.code == "IMMUTABLE_RESOURCE"

    # Deleting ledger entry is forbidden
    with pytest.raises(ImmutableResourceError) as exc_del:
        service.delete("log_immut_01")
    assert exc_del.value.code == "IMMUTABLE_RESOURCE"


# ==============================================================================
# 18. OPERATIONAL LIFECYCLE / DELETION RULES
# ==============================================================================
def test_18_operational_lifecycle_deletion_rules(uow: UnitOfWork, tenant_context_a: AuthenticatedContext):
    """18. Test operational entities (suppliers, shipments) forbid hard delete."""
    supplier_service = BaseService(Supplier, uow, tenant_context_a)
    supplier_service.create({"id": "sup_no_delete", "name": "Active Supplier"})

    # Hard deletion of operational supplier is forbidden
    with pytest.raises(LifecycleStateError) as exc_info:
        supplier_service.delete("sup_no_delete")
    assert exc_info.value.code == "INVALID_STATE_TRANSITION"
    assert "operational entity and cannot be hard deleted" in str(exc_info.value)


# ==============================================================================
# 19. AUTHORIZATION INTEGRATION
# ==============================================================================
def test_19_authorization_integration(uow: UnitOfWork, tenant_context_a: AuthenticatedContext):
    """19. Test BaseService injects tenant_id and isolates created records."""
    service = BaseService(Supplier, uow, tenant_context_a)

    # Client tries to pass a different org_id in body
    created = service.create({"id": "sup_auth_01", "name": "Secure Supplier", "org_id": "org_spoofed_999"})

    # Service must overwrite or enforce the authenticated tenant boundary
    assert created.org_id == "org_alpha_101"
    assert created.org_id != "org_spoofed_999"


# ==============================================================================
# 20. ERROR MAPPING & SECURITY SANITIZATION
# ==============================================================================
def test_20_error_mapping_and_secret_scrubbing(uow: UnitOfWork):
    """20. Test secret scrubbing in audit logs and atomic concurrency arithmetic."""
    # 1. Test secret scrubbing
    raw_payload = {
        "user_email": "user@example.com",
        "api_key": "sk-live-secret-12345",
        "password": "super-secret-password",
        "nested": {
            "session_token": "token_abc",
            "safe_metric": 42,
        },
    }
    sanitized = sanitize_payload(raw_payload)
    assert sanitized["user_email"] == "user@example.com"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["session_token"] == "[REDACTED]"
    assert sanitized["nested"]["safe_metric"] == 42

    # 2. Test audit event emission
    entry = AuditService.log_event(
        uow=uow,
        org_id="org_alpha_101",
        actor_id="user_1",
        action="UPDATE_CONFIG",
        resource_type="Organization",
        resource_id="org_alpha_101",
        before_data=raw_payload,
        auto_commit=True,
    )
    assert entry.before_json["password"] == "[REDACTED]"

    # 3. Test atomic numeric adjustment (concurrency helper)
    supplier = Supplier(id="sup_conc_01", org_id="org_alpha_101", name="Conc Supplier", reliability_score=50.0)
    uow.suppliers.create(supplier)

    affected = atomic_adjust_numeric(
        session=uow.session,
        model=Supplier,
        id="sup_conc_01",
        field_name="reliability_score",
        delta=15.5,
        org_id="org_alpha_101",
    )
    assert affected == 1
    uow.session.expire_all()
    assert uow.suppliers.get("sup_conc_01").reliability_score == 65.5
