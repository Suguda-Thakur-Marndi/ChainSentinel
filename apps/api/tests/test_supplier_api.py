"""Production Supplier API security, multi-tenancy, and domain tests (Phase 4 Step 3).

Tests:
 1. Unauthenticated GET → 401.
 2. Unauthenticated POST → 401.
 3. Viewer GET → allowed (200 OK).
 4. Unauthorized POST (Viewer/Analyst) → 403 Forbidden.
 5. Authorized POST (OpsManager/RiskManager/Admin) → 201 Created.
 6. Cross-tenant GET → 404 Not Found (masked).
 7. Cross-tenant PATCH → 404 Not Found (masked).
 8. Client-supplied org_id in body → 422 Unprocessable Entity.
 9. Client-supplied server-controlled ID in body → 422 Unprocessable Entity.
10. Invalid sort field → 400 Bad Request (INVALID_SORT_FIELD).
11. Invalid filter field → 400 Bad Request (INVALID_FILTER_FIELD).
12. Invalid pagination (page=0, limit=101) → 422 Unprocessable Entity.
13. Search safely escapes SQL wildcards (%, _).
14. Missing supplier ID → 404 Not Found (RESOURCE_NOT_FOUND).
15. Valid update (PATCH) → 200 OK with updated attributes.
16. Invalid update validation error (e.g. reliability_score > 100) → 422.
17. Duplicate code conflict within tenant → 409 Conflict (SUPPLIER_CODE_EXISTS).
18. Hard DELETE not exposed → 405 Method Not Allowed.
19. Audit record generated for mutations (CREATE, UPDATE).
20. Transaction rollback works on failed mutation.
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.governance import AuditLog
from app.models.network import Supplier
from app.models.tenancy import Organization, User
from app.services.session_service import MemorySessionStore, SessionService, get_session_service


# ==============================================================================
# FIXTURES
# ==============================================================================
@pytest.fixture(scope="function")
def test_db():
    """Isolated in-memory SQLite database session fixture."""
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
        engine.dispose()


@pytest.fixture(scope="function")
def session_service():
    """Isolated in-memory session service."""
    return SessionService(store=MemorySessionStore())


@pytest.fixture(scope="function")
def client(test_db: Session, session_service: SessionService):
    """FastAPI TestClient with overridden database and session service dependencies."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    def override_session_service():
        return session_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = override_session_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def seed_users(test_db: Session, session_service: SessionService):
    """Seed test organizations, users, and active sessions across roles."""
    # Organizations
    org_a = Organization(id="org_alpha_01", name="Alpha Logistics Inc", slug="alpha-logistics", is_active=True)
    org_b = Organization(id="org_beta_02", name="Beta Global Ltd", slug="beta-global", is_active=True)
    test_db.add_all([org_a, org_b])
    test_db.commit()

    # Users for Org A
    viewer_a = User(id="usr_view_a", org_id="org_alpha_01", email="viewer@alpha.test", full_name="Viewer A", role="Viewer", is_active=True)
    analyst_a = User(id="usr_analyst_a", org_id="org_alpha_01", email="analyst@alpha.test", full_name="Analyst A", role="Analyst", is_active=True)
    ops_a = User(id="usr_ops_a", org_id="org_alpha_01", email="ops@alpha.test", full_name="OpsManager A", role="OpsManager", is_active=True)
    risk_a = User(id="usr_risk_a", org_id="org_alpha_01", email="risk@alpha.test", full_name="RiskManager A", role="RiskManager", is_active=True)
    admin_a = User(id="usr_admin_a", org_id="org_alpha_01", email="admin@alpha.test", full_name="Admin A", role="Admin", is_active=True)

    # User for Org B
    ops_b = User(id="usr_ops_b", org_id="org_beta_02", email="ops@beta.test", full_name="OpsManager B", role="OpsManager", is_active=True)

    test_db.add_all([viewer_a, analyst_a, ops_a, risk_a, admin_a, ops_b])
    test_db.commit()

    # Create active sessions
    def make_cookie(user: User) -> str:
        s = session_service.create_session(
            user_id=user.id,
            role=user.role,
            organization_id=user.org_id,
            ttl_seconds=3600,
        )
        return s.session_id

    return {
        "org_a": org_a,
        "org_b": org_b,
        "viewer_cookie": make_cookie(viewer_a),
        "analyst_cookie": make_cookie(analyst_a),
        "ops_a_cookie": make_cookie(ops_a),
        "risk_a_cookie": make_cookie(risk_a),
        "admin_a_cookie": make_cookie(admin_a),
        "ops_b_cookie": make_cookie(ops_b),
    }


# ==============================================================================
# 1. UNAUTHENTICATED GET → 401
# ==============================================================================
def test_1_unauthenticated_get_returns_401(client: TestClient):
    """1. Test unauthenticated request to list suppliers returns 401."""
    response = client.get("/api/v1/suppliers")
    assert response.status_code == 401
    assert "detail" in response.json() or "error" in response.json()


# ==============================================================================
# 2. UNAUTHENTICATED POST → 401
# ==============================================================================
def test_2_unauthenticated_post_returns_401(client: TestClient):
    """2. Test unauthenticated request to create supplier returns 401."""
    response = client.post("/api/v1/suppliers", json={"name": "Acme Chips"})
    assert response.status_code == 401


# ==============================================================================
# 3. VIEWER GET → ALLOWED (200 OK)
# ==============================================================================
def test_3_viewer_get_allowed(client: TestClient, seed_users: dict, test_db: Session):
    """3. Test Viewer role can read supplier collection and individual supplier."""
    # Seed a supplier in Org A
    supplier = Supplier(id="sup_seed_01", org_id="org_alpha_01", name="Apex Silicon", code="APX-01")
    test_db.add(supplier)
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["viewer_cookie"])

    # List
    list_resp = client.get("/api/v1/suppliers")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["name"] == "Apex Silicon"

    # Get by ID
    get_resp = client.get("/api/v1/suppliers/sup_seed_01")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == "sup_seed_01"


# ==============================================================================
# 4. UNAUTHORIZED POST (VIEWER/ANALYST) → 403
# ==============================================================================
def test_4_unauthorized_post_returns_403(client: TestClient, seed_users: dict):
    """4. Test Viewer and Analyst roles are forbidden from creating suppliers (403)."""
    payload = {"name": "Unauthorized Supplier", "code": "NO-AUTH"}

    # Viewer
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["viewer_cookie"])
    resp_viewer = client.post("/api/v1/suppliers", json=payload)
    assert resp_viewer.status_code == 403

    # Analyst
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["analyst_cookie"])
    resp_analyst = client.post("/api/v1/suppliers", json=payload)
    assert resp_analyst.status_code == 403


# ==============================================================================
# 5. AUTHORIZED POST (OPS/RISK/ADMIN) → 201
# ==============================================================================
def test_5_authorized_post_success(client: TestClient, seed_users: dict):
    """5. Test OpsManager, RiskManager, and Admin can create suppliers (201 Created)."""
    # OpsManager
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    resp_ops = client.post(
        "/api/v1/suppliers",
        json={
            "name": "Taiwan Micro Optics",
            "code": "TMO-001",
            "country": "TW",
            "tier": "CRITICAL",
            "criticality": "HIGH",
            "reliability_score": 94.5,
        },
    )
    assert resp_ops.status_code == 201
    created_ops = resp_ops.json()
    assert created_ops["id"] is not None
    assert created_ops["org_id"] == "org_alpha_01"
    assert created_ops["name"] == "Taiwan Micro Optics"
    assert created_ops["tier"] == "CRITICAL"

    # RiskManager
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["risk_a_cookie"])
    resp_risk = client.post(
        "/api/v1/suppliers",
        json={"name": "Kyoto Sensors Inc", "code": "KSI-002"},
    )
    assert resp_risk.status_code == 201

    # Admin
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["admin_a_cookie"])
    resp_admin = client.post(
        "/api/v1/suppliers",
        json={"name": "Munich Semiconductor AG", "code": "MSA-003"},
    )
    assert resp_admin.status_code == 201


# ==============================================================================
# 6. CROSS-TENANT GET → 404 NOT FOUND (MASKED)
# ==============================================================================
def test_6_cross_tenant_get_returns_404(client: TestClient, seed_users: dict, test_db: Session):
    """6. Test querying a supplier belonging to another tenant returns 404 (not 403)."""
    # Create supplier in Org A
    sup_a = Supplier(id="sup_org_a_secret", org_id="org_alpha_01", name="Alpha Confidential Supplier")
    test_db.add(sup_a)
    test_db.commit()

    # User in Org B queries Org A supplier
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_b_cookie"])
    response = client.get("/api/v1/suppliers/sup_org_a_secret")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 7. CROSS-TENANT PATCH → 404 NOT FOUND (MASKED)
# ==============================================================================
def test_7_cross_tenant_patch_returns_404(client: TestClient, seed_users: dict, test_db: Session):
    """7. Test updating a supplier belonging to another tenant returns 404."""
    sup_a = Supplier(id="sup_org_a_target", org_id="org_alpha_01", name="Original Name")
    test_db.add(sup_a)
    test_db.commit()

    # User in Org B attempts update on Org A supplier
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_b_cookie"])
    response = client.patch(
        "/api/v1/suppliers/sup_org_a_target",
        json={"name": "Maliciously Hijacked Name"},
    )
    assert response.status_code == 404

    # Verify original name remains unchanged in DB
    re_retrieved = test_db.get(Supplier, "sup_org_a_target")
    assert re_retrieved.name == "Original Name"


# ==============================================================================
# 8. CLIENT-SUPPLIED ORG_ID IN BODY → 422
# ==============================================================================
def test_8_client_supplied_org_id_rejected(client: TestClient, seed_users: dict):
    """8. Test passing org_id in request body is rejected with 422 (extra = forbid)."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.post(
        "/api/v1/suppliers",
        json={"name": "Spoofed Org Supplier", "org_id": "org_spoofed_999"},
    )
    assert response.status_code == 422


# ==============================================================================
# 9. CLIENT-SUPPLIED ID IN BODY → 422
# ==============================================================================
def test_9_client_supplied_server_controlled_id_rejected(client: TestClient, seed_users: dict):
    """9. Test passing server-managed ID or created_at in request body is rejected with 422."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    resp_id = client.post(
        "/api/v1/suppliers",
        json={"name": "Fixed ID Supplier", "id": "sup_custom_id_123"},
    )
    assert resp_id.status_code == 422

    resp_time = client.post(
        "/api/v1/suppliers",
        json={"name": "Spoofed Time Supplier", "created_at": "2020-01-01T00:00:00Z"},
    )
    assert resp_time.status_code == 422


# ==============================================================================
# 10. INVALID SORT FIELD → 400
# ==============================================================================
def test_10_invalid_sort_returns_400(client: TestClient, seed_users: dict):
    """10. Test requesting an unapproved sort column returns 400 INVALID_SORT_FIELD."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.get("/api/v1/suppliers?sort=password_hash")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_SORT_FIELD"


# ==============================================================================
# 11. INVALID FILTER FIELD → 400
# ==============================================================================
def test_11_invalid_filter_returns_400(client: TestClient, seed_users: dict):
    """11. Test requesting an unapproved filter parameter returns 400 INVALID_FILTER_FIELD."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.get("/api/v1/suppliers?unsupported_col=danger")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_FILTER_FIELD"


# ==============================================================================
# 12. INVALID PAGINATION → 422
# ==============================================================================
def test_12_invalid_pagination_returns_422(client: TestClient, seed_users: dict):
    """12. Test invalid pagination bounds (page < 1 or limit > 100) return 422."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])

    resp_zero_page = client.get("/api/v1/suppliers?page=0")
    assert resp_zero_page.status_code == 422

    resp_large_limit = client.get("/api/v1/suppliers?limit=101")
    assert resp_large_limit.status_code == 422


# ==============================================================================
# 13. SEARCH SAFELY ESCAPES WILDCARDS
# ==============================================================================
def test_13_search_safely_escapes_wildcards(client: TestClient, seed_users: dict, test_db: Session):
    """13. Test searching for % and _ safely escapes wildcards and matches literal string."""
    test_db.add(Supplier(id="sup_pct_1", org_id="org_alpha_01", name="Chipset 100% Guaranteed", code="CHIP-100"))
    test_db.add(Supplier(id="sup_pct_2", org_id="org_alpha_01", name="Chipset Standard", code="CHIP-STD"))
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.get("/api/v1/suppliers?search=100%")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "sup_pct_1"


# ==============================================================================
# 14. MISSING SUPPLIER ID → 404
# ==============================================================================
def test_14_missing_supplier_returns_404(client: TestClient, seed_users: dict):
    """14. Test querying a non-existent supplier ID returns 404 RESOURCE_NOT_FOUND."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.get("/api/v1/suppliers/sup_does_not_exist_xyz")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 15. VALID UPDATE (PATCH) → 200 OK
# ==============================================================================
def test_15_valid_update_success(client: TestClient, seed_users: dict, test_db: Session):
    """15. Test valid PATCH update modifies fields and returns updated SupplierResponse."""
    supplier = Supplier(
        id="sup_patch_01",
        org_id="org_alpha_01",
        name="Old Supplier Name",
        reliability_score=75.0,
        tier="MEDIUM",
    )
    test_db.add(supplier)
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.patch(
        "/api/v1/suppliers/sup_patch_01",
        json={
            "name": "Updated Supplier Name",
            "reliability_score": 92.0,
            "tier": "CRITICAL",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Supplier Name"
    assert data["reliability_score"] == 92.0
    assert data["tier"] == "CRITICAL"
    assert data["updated_at"] is not None


# ==============================================================================
# 16. INVALID UPDATE VALIDATION ERROR → 422
# ==============================================================================
def test_16_invalid_update_validation_error(client: TestClient, seed_users: dict, test_db: Session):
    """16. Test PATCH with invalid value (e.g. reliability_score > 100) returns 422."""
    supplier = Supplier(id="sup_patch_inv", org_id="org_alpha_01", name="Test Supplier")
    test_db.add(supplier)
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.patch(
        "/api/v1/suppliers/sup_patch_inv",
        json={"reliability_score": 150.0},  # Schema limits to <= 100.0
    )
    assert response.status_code == 422


# ==============================================================================
# 17. DUPLICATE CODE CONFLICT WITHIN TENANT → 409
# ==============================================================================
def test_17_duplicate_code_conflict_returns_409(client: TestClient, seed_users: dict, test_db: Session):
    """17. Test attempting to create a supplier with a duplicate code in the same org returns 409."""
    supplier = Supplier(id="sup_dup_01", org_id="org_alpha_01", name="Existing Supplier", code="DUP-CODE-01")
    test_db.add(supplier)
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.post(
        "/api/v1/suppliers",
        json={"name": "New Conflicting Supplier", "code": "DUP-CODE-01"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "SUPPLIER_CODE_EXISTS"


# ==============================================================================
# 18. HARD DELETE NOT EXPOSED → 405 METHOD NOT ALLOWED
# ==============================================================================
def test_18_hard_delete_not_exposed(client: TestClient, seed_users: dict, test_db: Session):
    """18. Test that DELETE /api/v1/suppliers/{id} is not exposed and returns 405."""
    supplier = Supplier(id="sup_del_target", org_id="org_alpha_01", name="Delete Target")
    test_db.add(supplier)
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["admin_a_cookie"])
    response = client.delete("/api/v1/suppliers/sup_del_target")
    assert response.status_code == 405


# ==============================================================================
# 19. AUDIT RECORD GENERATED FOR MUTATION
# ==============================================================================
def test_19_audit_record_generated_for_mutation(client: TestClient, seed_users: dict, test_db: Session):
    """19. Test that creating and updating suppliers generates corresponding immutable audit entries."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])

    # 1. Create supplier
    create_resp = client.post(
        "/api/v1/suppliers",
        json={"name": "Audited Supplier", "code": "AUDIT-01"},
    )
    assert create_resp.status_code == 201
    supplier_id = create_resp.json()["id"]

    # Verify audit entry for CREATE
    stmt_create = select(AuditLog).where(
        AuditLog.resource_id == supplier_id,
        AuditLog.action == "CREATE",
    )
    create_log = test_db.scalars(stmt_create).first()
    assert create_log is not None
    assert create_log.org_id == "org_alpha_01"
    assert create_log.resource_type == "Supplier"

    # 2. Update supplier
    patch_resp = client.patch(
        f"/api/v1/suppliers/{supplier_id}",
        json={"name": "Audited Supplier Renamed"},
    )
    assert patch_resp.status_code == 200

    # Verify audit entry for UPDATE
    stmt_update = select(AuditLog).where(
        AuditLog.resource_id == supplier_id,
        AuditLog.action == "UPDATE",
    )
    update_log = test_db.scalars(stmt_update).first()
    assert update_log is not None
    assert update_log.before_json["name"] == "Audited Supplier"
    assert update_log.after_json["name"] == "Audited Supplier Renamed"


# ==============================================================================
# 20. TRANSACTION ROLLBACK ON FAILED MUTATION
# ==============================================================================
def test_20_transaction_rollback_works_after_failed_mutation(client: TestClient, seed_users: dict, test_db: Session):
    """20. Test that if a conflict occurs during creation, no partial record or dirty state is persisted."""
    test_db.add(Supplier(id="sup_initial", org_id="org_alpha_01", name="Initial", code="UNIQUE-99"))
    test_db.commit()

    client.cookies.set(settings.SESSION_COOKIE_NAME, seed_users["ops_a_cookie"])
    response = client.post(
        "/api/v1/suppliers",
        json={"name": "Should Fail", "code": "UNIQUE-99"},
    )
    assert response.status_code == 409

    # Verify count is still 1
    total = test_db.query(Supplier).filter(Supplier.org_id == "org_alpha_01").count()
    assert total == 1


# ==============================================================================
# 21. OPENAPI SPECIFICATION VERIFICATION
# ==============================================================================
def test_21_openapi_schema_contains_supplier_endpoints(client: TestClient):
    """21. Verify OpenAPI specification registers all 4 Supplier endpoints without duplicates."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    paths = spec.get("paths", {})

    # Verify endpoints exist
    assert "/api/v1/suppliers" in paths
    assert "/api/v1/suppliers/{id}" in paths

    # Verify methods
    assert "get" in paths["/api/v1/suppliers"]
    assert "post" in paths["/api/v1/suppliers"]
    assert "get" in paths["/api/v1/suppliers/{id}"]
    assert "patch" in paths["/api/v1/suppliers/{id}"]

    # Verify delete is NOT in paths
    assert "delete" not in paths["/api/v1/suppliers"]
    assert "delete" not in paths["/api/v1/suppliers/{id}"]

    # Verify no duplicate operation IDs
    operation_ids = []
    for path, methods in paths.items():
        for method, operation in methods.items():
            if isinstance(operation, dict) and "operationId" in operation:
                operation_ids.append(operation["operationId"])
    assert len(operation_ids) == len(set(operation_ids))

    # Verify schemas
    schemas = spec.get("components", {}).get("schemas", {})
    assert "SupplierCreate" in schemas
    assert "SupplierUpdate" in schemas
    assert "SupplierResponse" in schemas
    assert "SupplierListResponse" in schemas
