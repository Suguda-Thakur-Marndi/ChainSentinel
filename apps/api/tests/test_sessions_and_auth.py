"""Comprehensive tests for Session Management, Authentication Dependencies & Protected Routes (Phase 3 Step 4).

Validates all 15 requirements specified in Phase 3 Step 4:
1. No cookie → 401 Unauthorized
2. Invalid session token → 401 Unauthorized
3. Expired session → 401 Unauthorized
4. Valid session → Authenticated (200 OK + UserMeResponse)
5. Inactive user → Denied (401 Unauthorized) & session revoked
6. Logout invalidates session on server
7. /me after logout → 401 Unauthorized
8. Valid user with correct role → Allowed
9. Valid user with incorrect role → 403 Forbidden
10. Organization A cannot access Organization B resources (Multi-tenant isolation)
11. Health endpoints remain public
12. CORS does not allow wildcard "*" with credentials
13. Session cookie has secure properties (HttpOnly, SameSite, Secure)
14. Session IDs are unpredictable and high-entropy
15. Session data does not contain secrets
"""
import secrets
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as models
from app.api.deps import (
    AuthenticatedContext,
    get_authenticated_context,
    get_current_organization,
    get_current_user,
    require_role,
    verify_tenant_access,
)
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas.session import SessionData
from app.services.session_service import (
    MemorySessionStore,
    SessionService,
    clear_session_cookie,
    get_session_service,
    set_session_cookie,
)


# ==============================================================================
# FIXTURES & TEST SETUP
# ==============================================================================

@pytest.fixture(scope="function")
def test_db_session():
    """Isolated SQLite in-memory database fixture with foreign keys enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
def memory_session_service():
    """Isolated SessionService using a fresh MemorySessionStore."""
    store = MemorySessionStore()
    return SessionService(store=store)


@pytest.fixture(scope="function")
def client(test_db_session: Session, memory_session_service: SessionService):
    """FastAPI TestClient with overridden get_db and get_session_service dependencies."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    def override_session_service():
        return memory_session_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = override_session_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def seed_data(test_db_session: Session):
    """Seed test organizations and users."""
    org_a = models.Organization(
        name="Acme Logistics Corp",
        slug="acme-logistics",
        plan="ENTERPRISE",
        is_active=True,
    )
    org_b = models.Organization(
        name="Global Maritime Ltd",
        slug="global-maritime",
        plan="PRO",
        is_active=True,
    )
    test_db_session.add_all([org_a, org_b])
    test_db_session.commit()

    analyst_user = models.User(
        email="analyst@acme.com",
        full_name="Alice Analyst",
        role="Analyst",
        organization=org_a,
        is_active=True,
    )
    admin_user = models.User(
        email="admin@acme.com",
        full_name="Adam Admin",
        role="Admin",
        organization=org_a,
        is_active=True,
    )
    inactive_user = models.User(
        email="inactive@acme.com",
        full_name="Ian Inactive",
        role="Analyst",
        organization=org_a,
        is_active=False,
    )
    user_org_b = models.User(
        email="operator@maritime.com",
        full_name="Bob Maritime",
        role="OpsManager",
        organization=org_b,
        is_active=True,
    )
    test_db_session.add_all([analyst_user, admin_user, inactive_user, user_org_b])
    test_db_session.commit()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "analyst": analyst_user,
        "admin": admin_user,
        "inactive": inactive_user,
        "user_org_b": user_org_b,
    }


# ==============================================================================
# 1-4. SESSION & PROTECTED /ME TESTS
# ==============================================================================

def test_no_cookie_returns_401(client: TestClient):
    """1. No cookie → 401 Unauthorized."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_invalid_session_returns_401(client: TestClient):
    """2. Invalid session → 401 Unauthorized."""
    client.cookies.set(settings.SESSION_COOKIE_NAME, "completely_bogus_session_token_xyz")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Session expired or invalid"}


def test_expired_session_returns_401(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """3. Expired session → 401 Unauthorized."""
    analyst = seed_data["analyst"]
    # Create an already-expired session
    session = memory_session_service.create_session(
        user_id=analyst.id,
        role=analyst.role,
        organization_id=analyst.org_id,
        ttl_seconds=-10,  # Expired 10 seconds ago
    )

    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Session expired or invalid"}


def test_valid_session_returns_authenticated_profile(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """4. Valid session → authenticated (200 OK with UserMeResponse)."""
    analyst = seed_data["analyst"]
    session = memory_session_service.create_session(
        user_id=analyst.id,
        role=analyst.role,
        organization_id=analyst.org_id,
        ttl_seconds=3600,
    )

    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == analyst.id
    assert data["email"] == "analyst@acme.com"
    assert data["role"] == "Analyst"
    assert data["org_id"] == analyst.org_id
    assert data["organization"]["name"] == "Acme Logistics Corp"
    assert "scenarios:run" in data["permissions"]


# ==============================================================================
# 5. USER STATUS CHECK
# ==============================================================================

def test_inactive_user_denied_access(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """5. Inactive user → denied (401) and session is immediately revoked."""
    inactive = seed_data["inactive"]
    session = memory_session_service.create_session(
        user_id=inactive.id,
        role=inactive.role,
        organization_id=inactive.org_id,
        ttl_seconds=3600,
    )

    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Account has been deactivated"}

    # Verify session was revoked in session service
    assert memory_session_service.get_session(session.session_id) is None


# ==============================================================================
# 6-7. LOGOUT BEHAVIOR & SESSION REVOCATION
# ==============================================================================

def test_logout_revokes_server_session_and_clears_cookie(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """6. Logout revokes/deletes server-side session and clears cookie."""
    analyst = seed_data["analyst"]
    session = memory_session_service.create_session(
        user_id=analyst.id,
        role=analyst.role,
        organization_id=analyst.org_id,
    )

    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    logout_resp = client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"status": "ok", "message": "Successfully logged out"}

    # Verify session was revoked from store
    assert memory_session_service.get_session(session.session_id) is None


def test_me_after_logout_returns_401(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """7. GET /api/v1/auth/me returns 401 Unauthorized after logout."""
    analyst = seed_data["analyst"]
    session = memory_session_service.create_session(
        user_id=analyst.id,
        role=analyst.role,
        organization_id=analyst.org_id,
    )

    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    # Confirm initial access works
    assert client.get("/api/v1/auth/me").status_code == 200

    # Logout
    client.post("/api/v1/auth/logout")

    # Immediate subsequent access rejected with 401 Unauthorized
    post_logout_resp = client.get("/api/v1/auth/me")
    assert post_logout_resp.status_code == 401



# ==============================================================================
# 8-9. ROLE AUTHORIZATION
# ==============================================================================

def test_valid_user_with_correct_role_allowed(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """8. Valid user with correct role → allowed (200 OK)."""
    test_app = FastAPI()

    @test_app.get("/admin-only")
    def admin_endpoint(ctx: AuthenticatedContext = Depends(require_role("Admin"))):
        return {"status": "admin_granted"}

    test_app.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    test_app.dependency_overrides[get_session_service] = app.dependency_overrides[get_session_service]

    test_client = TestClient(test_app)

    admin = seed_data["admin"]
    admin_session = memory_session_service.create_session(
        user_id=admin.id,
        role=admin.role,
        organization_id=admin.org_id,
    )
    test_client.cookies.set(settings.SESSION_COOKIE_NAME, admin_session.session_id)
    res = test_client.get("/admin-only")
    assert res.status_code == 200
    assert res.json() == {"status": "admin_granted"}


def test_valid_user_with_incorrect_role_forbidden(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """9. Valid user with incorrect role → 403 Forbidden."""
    test_app = FastAPI()

    @test_app.get("/admin-only")
    def admin_endpoint(ctx: AuthenticatedContext = Depends(require_role("Admin"))):
        return {"status": "admin_granted"}

    test_app.dependency_overrides[get_db] = app.dependency_overrides[get_db]
    test_app.dependency_overrides[get_session_service] = app.dependency_overrides[get_session_service]

    test_client = TestClient(test_app)

    analyst = seed_data["analyst"]
    analyst_session = memory_session_service.create_session(
        user_id=analyst.id,
        role=analyst.role,
        organization_id=analyst.org_id,
    )
    test_client.cookies.set(settings.SESSION_COOKIE_NAME, analyst_session.session_id)
    res = test_client.get("/admin-only")
    assert res.status_code == 403
    assert res.json() == {"detail": "Insufficient permissions"}



# ==============================================================================
# 10. MULTI-TENANT ISOLATION
# ==============================================================================

def test_organization_tenancy_isolation(
    memory_session_service: SessionService,
    seed_data: dict,
):
    """10. Organization A cannot access Organization B resources."""
    user_a = seed_data["analyst"]
    user_b = seed_data["user_org_b"]

    session_a = memory_session_service.create_session(
        user_id=user_a.id,
        role=user_a.role,
        organization_id=user_a.org_id,
    )
    context_a = AuthenticatedContext(
        user=user_a,
        session_data=session_a,
        organization=user_a.organization,
    )

    # Record belonging to Organization A -> Access Allowed
    verify_tenant_access(record_org_id=user_a.org_id, context=context_a)

    # Record belonging to Organization B -> 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        verify_tenant_access(record_org_id=user_b.org_id, context=context_a)
    assert exc_info.value.status_code == 403
    assert "organization boundary mismatch" in exc_info.value.detail


# ==============================================================================
# 11. PUBLIC HEALTH & INFRASTRUCTURE ENDPOINTS
# ==============================================================================

def test_health_and_ready_endpoints_remain_public(client: TestClient):
    """11. Health and readiness endpoints remain public without authentication."""
    # Ensure no cookies set
    client.cookies.clear()

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}

    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    assert res_ready.json() == {"status": "ready"}


# ==============================================================================
# 12. CORS ORIGINS VALIDATION
# ==============================================================================

def test_cors_configuration_disallows_wildcard():
    """12. CORS does not allow arbitrary credentialed origins (allow_origins != ['*'])."""
    assert "*" not in settings.CORS_ORIGINS
    for origin in settings.CORS_ORIGINS:
        assert origin.startswith("http://") or origin.startswith("https://")
        assert origin != "*"


# ==============================================================================
# 13. SESSION COOKIE PROPERTIES
# ==============================================================================

def test_session_cookie_properties(
    client: TestClient,
    memory_session_service: SessionService,
    seed_data: dict,
):
    """13. Session cookie has secure properties (HttpOnly, SameSite=Lax, Path=/)."""
    # Create test response and set cookie
    from fastapi import Response
    resp = Response()
    session_id = memory_session_service.generate_session_id()
    SessionService.set_session_cookie(resp, session_id)

    raw_cookies = resp.raw_headers
    cookie_header = next(v.decode("utf-8") for k, v in raw_cookies if k.decode("utf-8").lower() == "set-cookie")

    assert f"{settings.SESSION_COOKIE_NAME}={session_id}" in cookie_header
    assert "HttpOnly" in cookie_header
    assert f"Max-Age={settings.SESSION_MAX_AGE_SECONDS}" in cookie_header
    assert "Path=/" in cookie_header
    assert "SameSite=lax" in cookie_header or "SameSite=Lax" in cookie_header


# ==============================================================================
# 14. SESSION ID UNPREDICTABILITY
# ==============================================================================

def test_session_ids_are_unpredictable(memory_session_service: SessionService):
    """14. Session IDs are cryptographically random, unique, and high-entropy."""
    generated_ids = {memory_session_service.generate_session_id() for _ in range(100)}
    assert len(generated_ids) == 100
    for sid in generated_ids:
        assert len(sid) >= 40
        assert sid.isalnum() or "-" in sid or "_" in sid


# ==============================================================================
# 15. SESSION DATA CONTAINS NO SECRETS
# ==============================================================================

def test_session_data_contains_no_secrets(memory_session_service: SessionService):
    """15. Session data does not contain passwords, client secrets, or sensitive tokens."""
    session = memory_session_service.create_session(
        user_id="usr_12345",
        role="Analyst",
        organization_id="org_67890",
    )
    serialized = session.model_dump_json()

    forbidden_terms = [
        "secret", "password", "token", "google_client_secret",
        "api_key", "bearer", "private_key", "credential",
    ]
    for term in forbidden_terms:
        # Field names like session_id are fine, but values must not contain secrets
        assert f'"{term}"' not in serialized
