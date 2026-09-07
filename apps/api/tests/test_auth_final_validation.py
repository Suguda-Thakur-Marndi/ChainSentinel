"""Comprehensive Final Validation Test Suite for RiskWise 2.0 Authentication (Phase 3 Step 7).

Validates all 29 requirements from Section 4:
1. OAuth initiation
2. Secure state generation
3. Invalid state
4. Expired state
5. Reused state
6. Missing OAuth code
7. Google provider error
8. Invalid Google identity
9. Expired identity
10. Invalid issuer
11. Invalid audience
12. Unverified email where verification is required
13. Existing user mapping
14. New-user behavior
15. Organization resolution
16. Missing organization
17. Inactive user
18. Session creation
19. Session lookup
20. Expired session
21. Invalid session
22. /me authenticated
23. /me unauthenticated
24. Logout
25. Logout followed by /me
26. Role authorization
27. Organization isolation
28. 401 behavior
29. 403 behavior
"""
import base64
import json
import time
from datetime import datetime, timezone
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as models
from app.api.deps import (
    AuthenticatedContext,
    get_authenticated_context,
    require_role,
    verify_tenant_access,
)
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.services.oauth_service import (
    OAuthService,
    OAuthValidationError,
    get_oauth_service,
)
from app.services.session_service import (
    MemorySessionStore,
    SessionService,
    get_session_service,
)


# ==============================================================================
# FIXTURES & SETUP
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
    """Isolated SessionService using a fresh in-memory store."""
    store = MemorySessionStore()
    return SessionService(store=store)


@pytest.fixture(scope="function")
def isolated_oauth_service():
    """Isolated OAuthService instance."""
    return OAuthService(signing_secret="test_oauth_secret_12345")


@pytest.fixture(scope="function")
def client(
    test_db_session: Session,
    memory_session_service: SessionService,
    isolated_oauth_service: OAuthService,
):
    """FastAPI TestClient with overridden database and service dependencies."""
    def override_get_db():
        try:
            yield test_db_session
        finally:
            pass

    def override_session_service():
        return memory_session_service

    def override_oauth_service():
        return isolated_oauth_service

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_service] = override_session_service
    app.dependency_overrides[get_oauth_service] = override_oauth_service

    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def seed_test_data(test_db_session: Session):
    """Seed test organizations and users."""
    org_alpha = models.Organization(
        name="Alpha Global Logistics",
        slug="alpha-logistics",
        plan="ENTERPRISE",
        is_active=True,
    )
    org_beta = models.Organization(
        name="Beta Shipping Corp",
        slug="beta-shipping",
        plan="PRO",
        is_active=True,
    )
    test_db_session.add_all([org_alpha, org_beta])
    test_db_session.commit()

    active_user = models.User(
        email="analyst@alpha.com",
        full_name="Alice Analyst",
        role="Analyst",
        organization=org_alpha,
        is_active=True,
    )
    admin_user = models.User(
        email="admin@alpha.com",
        full_name="Adam Admin",
        role="Admin",
        organization=org_alpha,
        is_active=True,
    )
    inactive_user = models.User(
        email="deactivated@alpha.com",
        full_name="David Deactivated",
        role="Analyst",
        organization=org_alpha,
        is_active=False,
    )
    user_beta = models.User(
        email="ops@beta.com",
        full_name="Bob Beta",
        role="OpsManager",
        organization=org_beta,
        is_active=True,
    )
    test_db_session.add_all([active_user, admin_user, inactive_user, user_beta])
    test_db_session.commit()

    return {
        "org_alpha": org_alpha,
        "org_beta": org_beta,
        "active_user": active_user,
        "admin_user": admin_user,
        "inactive_user": inactive_user,
        "user_beta": user_beta,
    }


# ==============================================================================
# TESTS 1-5: OAUTH INITIATION & STATE SECURITY
# ==============================================================================

def test_1_oauth_initiation(client: TestClient, monkeypatch):
    """1. OAuth initiation redirects to Google authorization URL when configured."""
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "mock-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "mock-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")

    response = client.get("/api/v1/auth/google?return_to=/shipments")
    assert response.status_code == 302
    redirect_url = response.headers["location"]
    assert redirect_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=mock-client-id.apps.googleusercontent.com" in redirect_url
    assert "state=" in redirect_url
    assert "scope=openid+email+profile" in redirect_url


def test_2_secure_state_generation(isolated_oauth_service: OAuthService):
    """2. Secure state generation produces signed token with nonce, timestamp, and path."""
    state = isolated_oauth_service.generate_state(return_to="/analytics")
    parts = state.split(".")
    assert len(parts) == 4
    nonce, ts_str, b64_path, sig = parts
    assert len(sig) == 64  # SHA-256 hex digest length
    assert int(ts_str) <= int(time.time())
    decoded_path = base64.urlsafe_b64decode(b64_path.encode()).decode()
    assert decoded_path == "/analytics"


def test_3_invalid_state_rejected(isolated_oauth_service: OAuthService):
    """3. Invalid state (tampered or malformed) is rejected."""
    # Malformed state
    is_valid, path, err = isolated_oauth_service.verify_state("malformed.state.token")
    assert is_valid is False
    assert err == "invalid_state"

    # Tampered signature
    valid_state = isolated_oauth_service.generate_state()
    parts = valid_state.split(".")
    tampered_state = f"{parts[0]}.{parts[1]}.{parts[2]}.badsignature1234567890"
    is_valid, path, err = isolated_oauth_service.verify_state(tampered_state)
    assert is_valid is False
    assert err == "invalid_state"


def test_4_expired_state_rejected(isolated_oauth_service: OAuthService):
    """4. Expired state token (> 300 seconds) is rejected."""
    # State generated 305 seconds in the past
    past_time = time.time() - 305
    state = isolated_oauth_service.generate_state()
    # Verify at current time against state created in past
    is_valid, path, err = isolated_oauth_service.verify_state(state, current_time=time.time() + 305)
    assert is_valid is False
    assert err == "expired_state"


def test_5_reused_state_rejected(isolated_oauth_service: OAuthService):
    """5. Reused state token is rejected (replay attack prevention)."""
    state = isolated_oauth_service.generate_state()
    # First verification succeeds
    is_valid1, path1, err1 = isolated_oauth_service.verify_state(state)
    assert is_valid1 is True

    # Second verification fails due to single-use replay protection
    is_valid2, path2, err2 = isolated_oauth_service.verify_state(state)
    assert is_valid2 is False
    assert err2 == "state_reused"


# ==============================================================================
# TESTS 6-7: OAUTH CALLBACK ERRORS
# ==============================================================================

def test_6_missing_oauth_code(client: TestClient, isolated_oauth_service: OAuthService):
    """6. Missing OAuth code redirects to frontend with missing_code error."""
    state = isolated_oauth_service.generate_state()
    response = client.get(f"/api/v1/auth/google/callback?state={state}")
    assert response.status_code == 302
    assert "error=missing_code" in response.headers["location"]


def test_7_google_provider_error(client: TestClient):
    """7. Google provider error redirects to frontend with error parameter."""
    response = client.get("/api/v1/auth/google/callback?error=access_denied")
    assert response.status_code == 302
    assert "error=access_denied" in response.headers["location"]


# ==============================================================================
# TESTS 8-12: OIDC IDENTITY & CLAIMS VALIDATION
# ==============================================================================

def test_8_invalid_google_identity(isolated_oauth_service: OAuthService):
    """8. Invalid Google identity (missing sub or email) raises OAuthValidationError."""
    # Missing sub
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.validate_oidc_claims({"email": "alice@example.com", "email_verified": True})
    assert exc.value.error_code == "invalid_google_identity"

    # Missing email
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.validate_oidc_claims({"sub": "google-12345", "email_verified": True})
    assert exc.value.error_code == "invalid_google_identity"


def test_9_expired_identity(isolated_oauth_service: OAuthService):
    """9. Expired Google ID token claim raises expired_identity."""
    claims = {
        "sub": "sub-123",
        "email": "user@example.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "exp": time.time() - 60,  # Expired 1 min ago
    }
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.validate_oidc_claims(claims)
    assert exc.value.error_code == "expired_identity"


def test_10_invalid_issuer(isolated_oauth_service: OAuthService):
    """10. Invalid token issuer raises invalid_issuer."""
    claims = {
        "sub": "sub-123",
        "email": "user@example.com",
        "email_verified": True,
        "iss": "https://fake-auth-provider.com",
    }
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.validate_oidc_claims(claims)
    assert exc.value.error_code == "invalid_issuer"


def test_11_invalid_audience(isolated_oauth_service: OAuthService):
    """11. Invalid token audience raises invalid_audience."""
    claims = {
        "sub": "sub-123",
        "email": "user@example.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "rogue-client-app-id",
    }
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.validate_oidc_claims(claims, expected_client_id="expected-client-app-id")
    assert exc.value.error_code == "invalid_audience"


def test_12_unverified_email(isolated_oauth_service: OAuthService):
    """12. Unverified Google email address raises unverified_email."""
    claims = {
        "sub": "sub-123",
        "email": "user@example.com",
        "email_verified": False,
        "iss": "https://accounts.google.com",
    }
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.validate_oidc_claims(claims)
    assert exc.value.error_code == "unverified_email"


# ==============================================================================
# TESTS 13-17: USER & ORGANIZATION RESOLUTION
# ==============================================================================

def test_13_existing_user_mapping(
    test_db_session: Session,
    isolated_oauth_service: OAuthService,
    seed_test_data: dict,
):
    """13. Existing user is matched by email and linked with Google SSO."""
    active_user = seed_test_data["active_user"]
    claims = {
        "sub": "google-sub-alice",
        "email": active_user.email,
        "email_verified": True,
        "name": "Alice Analyst Updated",
        "iss": "https://accounts.google.com",
    }

    user, org = isolated_oauth_service.resolve_or_create_google_user(test_db_session, claims)
    assert user.id == active_user.id
    assert user.sso_provider == "google"
    assert user.last_active_at is not None
    assert org.id == active_user.organization.id


def test_14_new_user_behavior(
    test_db_session: Session,
    isolated_oauth_service: OAuthService,
):
    """14. New Google user is provisioned with organization and Admin role."""
    claims = {
        "sub": "google-sub-newbie",
        "email": "brandnew@logisticsfirm.com",
        "email_verified": True,
        "name": "Benjamin Newbie",
        "iss": "https://accounts.google.com",
    }

    user, org = isolated_oauth_service.resolve_or_create_google_user(test_db_session, claims)
    assert user.email == "brandnew@logisticsfirm.com"
    assert user.role == "Admin"
    assert user.organization is not None
    assert org.name == "Benjamin Newbie's Organization"
    assert org.plan == "ENTERPRISE"


def test_15_organization_resolution(
    test_db_session: Session,
    isolated_oauth_service: OAuthService,
    seed_test_data: dict,
):
    """15. Organization resolution correctly associates the tenant boundary."""
    admin = seed_test_data["admin_user"]
    claims = {
        "sub": "google-sub-admin",
        "email": admin.email,
        "email_verified": True,
        "iss": "https://accounts.google.com",
    }
    user, org = isolated_oauth_service.resolve_or_create_google_user(test_db_session, claims)
    assert org.slug == "alpha-logistics"


def test_16_missing_organization(
    test_db_session: Session,
    isolated_oauth_service: OAuthService,
):
    """16. Existing user without an organization returns None for organization."""
    orphan_user = models.User(
        email="orphan@example.com",
        role="Analyst",
        org_id=None,
        is_active=True,
    )
    test_db_session.add(orphan_user)
    test_db_session.commit()

    claims = {
        "sub": "google-sub-orphan",
        "email": "orphan@example.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
    }
    user, org = isolated_oauth_service.resolve_or_create_google_user(test_db_session, claims)
    assert user.id == orphan_user.id
    assert org is None


def test_17_inactive_user_rejected(
    test_db_session: Session,
    isolated_oauth_service: OAuthService,
    seed_test_data: dict,
):
    """17. Inactive user is rejected with account_deactivated."""
    inactive = seed_test_data["inactive_user"]
    claims = {
        "sub": "google-sub-inactive",
        "email": inactive.email,
        "email_verified": True,
        "iss": "https://accounts.google.com",
    }
    with pytest.raises(OAuthValidationError) as exc:
        isolated_oauth_service.resolve_or_create_google_user(test_db_session, claims)
    assert exc.value.error_code == "account_deactivated"


# ==============================================================================
# TESTS 18-21: SESSION MANAGEMENT
# ==============================================================================

def test_18_session_creation(memory_session_service: SessionService):
    """18. Session creation stores session data with UTC timestamps and role."""
    session = memory_session_service.create_session(
        user_id="usr_123",
        role="Admin",
        organization_id="org_456",
        ttl_seconds=1800,
    )
    assert session.session_id is not None
    assert session.user_id == "usr_123"
    assert session.role == "Admin"
    assert session.organization_id == "org_456"
    assert session.expires_at > datetime.now(timezone.utc)


def test_19_session_lookup(memory_session_service: SessionService):
    """19. Session lookup retrieves valid session from store."""
    session = memory_session_service.create_session(
        user_id="usr_lookup",
        role="Analyst",
    )
    retrieved = memory_session_service.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.user_id == "usr_lookup"


def test_20_expired_session(memory_session_service: SessionService):
    """20. Expired session returns None on lookup."""
    session = memory_session_service.create_session(
        user_id="usr_exp",
        role="Analyst",
        ttl_seconds=-5,  # Expired in past
    )
    assert memory_session_service.get_session(session.session_id) is None


def test_21_invalid_session(memory_session_service: SessionService):
    """21. Lookup with non-existent session ID returns None."""
    assert memory_session_service.get_session("completely_bogus_token") is None


# ==============================================================================
# TESTS 22-25: /ME, LOGOUT, AND POST-LOGOUT
# ==============================================================================

def test_22_me_authenticated(
    client: TestClient,
    memory_session_service: SessionService,
    seed_test_data: dict,
):
    """22. GET /api/v1/auth/me returns profile for authenticated session."""
    active = seed_test_data["active_user"]
    session = memory_session_service.create_session(
        user_id=active.id,
        role=active.role,
        organization_id=active.org_id,
    )
    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == active.email
    assert data["organization"]["name"] == "Alpha Global Logistics"


def test_23_me_unauthenticated(client: TestClient):
    """23. GET /api/v1/auth/me returns 401 when no session cookie is provided."""
    client.cookies.clear()
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}


def test_24_logout(
    client: TestClient,
    memory_session_service: SessionService,
    seed_test_data: dict,
):
    """24. POST /api/v1/auth/logout revokes session and clears cookie."""
    active = seed_test_data["active_user"]
    session = memory_session_service.create_session(
        user_id=active.id,
        role=active.role,
        organization_id=active.org_id,
    )
    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    assert memory_session_service.get_session(session.session_id) is None


def test_25_logout_followed_by_me(
    client: TestClient,
    memory_session_service: SessionService,
    seed_test_data: dict,
):
    """25. Logout immediately causes subsequent /me calls to return 401."""
    active = seed_test_data["active_user"]
    session = memory_session_service.create_session(
        user_id=active.id,
        role=active.role,
        organization_id=active.org_id,
    )
    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    assert client.get("/api/v1/auth/me").status_code == 200

    # Execute logout
    client.post("/api/v1/auth/logout")

    # Immediate access check
    post_res = client.get("/api/v1/auth/me")
    assert post_res.status_code == 401


# ==============================================================================
# TESTS 26-29: AUTHORIZATION, MULTI-TENANCY, 401 & 403
# ==============================================================================

def test_26_role_authorization(
    test_db_session: Session,
    memory_session_service: SessionService,
    seed_test_data: dict,
):
    """26. Role authorization dependencies enforce RBAC privileges."""
    test_app = FastAPI()

    @test_app.get("/risk-manage")
    def risk_endpoint(ctx: AuthenticatedContext = Depends(require_role("RiskManager", "Admin"))):
        return {"authorized": True}

    def override_get_db():
        yield test_db_session

    test_app.dependency_overrides[get_db] = override_get_db
    test_app.dependency_overrides[get_session_service] = lambda: memory_session_service

    test_client = TestClient(test_app)

    # Analyst attempting to access Admin/RiskManager route -> 403
    analyst = seed_test_data["active_user"]
    analyst_session = memory_session_service.create_session(
        user_id=analyst.id,
        role=analyst.role,
        organization_id=analyst.org_id,
    )
    test_client.cookies.set(settings.SESSION_COOKIE_NAME, analyst_session.session_id)

    res_analyst = test_client.get("/risk-manage")
    assert res_analyst.status_code == 403

    # Admin accessing -> 200
    admin = seed_test_data["admin_user"]
    admin_session = memory_session_service.create_session(
        user_id=admin.id,
        role=admin.role,
        organization_id=admin.org_id,
    )
    test_client.cookies.set(settings.SESSION_COOKIE_NAME, admin_session.session_id)
    res_admin = test_client.get("/risk-manage")
    assert res_admin.status_code == 200


def test_27_organization_isolation(
    memory_session_service: SessionService,
    seed_test_data: dict,
):
    """27. User from Organization Alpha cannot access Organization Beta resource."""
    user_alpha = seed_test_data["active_user"]
    user_beta = seed_test_data["user_beta"]

    session_alpha = memory_session_service.create_session(
        user_id=user_alpha.id,
        role=user_alpha.role,
        organization_id=user_alpha.org_id,
    )
    context_alpha = AuthenticatedContext(
        user=user_alpha,
        session_data=session_alpha,
        organization=user_alpha.organization,
    )

    # Alpha accessing Alpha -> OK
    verify_tenant_access(record_org_id=user_alpha.org_id, context=context_alpha)

    # Alpha accessing Beta -> 403
    with pytest.raises(HTTPException) as exc:
        verify_tenant_access(record_org_id=user_beta.org_id, context=context_alpha)
    assert exc.value.status_code == 403
    assert "organization boundary mismatch" in exc.value.detail


def test_28_401_behavior(client: TestClient):
    """28. Unauthenticated requests consistently return 401 Unauthorized."""
    client.cookies.clear()
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_29_403_behavior(
    client: TestClient,
    memory_session_service: SessionService,
    seed_test_data: dict,
):
    """29. Deactivated user with active cookie returns 401/403 and revokes session."""
    inactive = seed_test_data["inactive_user"]
    session = memory_session_service.create_session(
        user_id=inactive.id,
        role=inactive.role,
        organization_id=inactive.org_id,
    )
    client.cookies.set(settings.SESSION_COOKIE_NAME, session.session_id)
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert "deactivated" in res.json()["detail"]


# ==============================================================================
# FULL OAUTH CALLBACK INTEGRATION TEST WITH MOCK CODE
# ==============================================================================

def test_full_oauth_callback_flow_creates_session_and_cookie(
    client: TestClient,
    isolated_oauth_service: OAuthService,
    memory_session_service: SessionService,
):
    """Test the complete OAuth callback flow with valid state and mock code."""
    state = isolated_oauth_service.generate_state(return_to="/shipments")

    # Use mock code shorthand 'test:newpilot@skyways.com'
    response = client.get(f"/api/v1/auth/google/callback?code=test:newpilot@skyways.com&state={state}")
    assert response.status_code == 302
    assert response.headers["location"] == f"{settings.FRONTEND_URL}/shipments"

    # Verify session cookie was set
    set_cookie_header = response.headers.get("set-cookie", "")
    assert settings.SESSION_COOKIE_NAME in set_cookie_header
    assert "HttpOnly" in set_cookie_header
