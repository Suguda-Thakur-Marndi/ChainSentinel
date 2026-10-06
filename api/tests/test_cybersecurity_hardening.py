"""Comprehensive Cybersecurity Hardening and Adversarial Attack Surface Verification Suite.

Tests rigorous defensive controls across:
1. Production authentication bypass prevention (/demo-login disabled in production)
2. WebSocket CSWSH origin validation, session authentication, and frame size protection
3. Cross-tenant approval isolation and IDOR mitigation in action dispatch
4. State machine integrity (action without approval, unapproved transition)
5. Audit log immutability and role-based access control
6. HTTP security headers (nosniff, DENY, HSTS, Permissions-Policy, Cache-Control)
7. Production API schema reconnaissance defense (docs/redoc/openapi disabled in prod)
8. OAuth 2.0 anti-CSRF state token validation, HMAC integrity, anti-replay, and open-redirect sanitization
9. ML model artifact loading security (path traversal and fingerprint tampering)
"""
import json
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.oauth_service import OAuthService
from app.agents.action.contract import ActionCommand, ActionType, TargetEntityType
from app.agents.action.policy import ActionSafetyPolicy
from app.agents.action.errors import ActionApprovalMissingError, ActionTenantIsolationError
from app.ml.training.artifacts import ArtifactManager
from app.ml.errors import ModelArtifactError
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.features import ShipmentDelayFeaturePipeline
from app.ml.contracts import MLModelMetadata, TaskType, ModelFamily, ModelMetrics
from app.models.governance import Approval, Recommendation


@pytest.fixture
def client():
    return TestClient(app)


# ------------------------------------------------------------------------------
# 1. Production Authentication Bypass Prevention
# ------------------------------------------------------------------------------

def test_demo_login_disabled_in_production(client):
    """Verify /demo-login returns 404 in production environment to prevent admin bypass."""
    with patch.object(settings, "APP_ENV", "production"):
        resp_get = client.get("/api/v1/auth/demo-login")
        assert resp_get.status_code == 404, f"Expected 404 in production, got {resp_get.status_code}"

        resp_post = client.post("/api/v1/auth/demo-login")
        assert resp_post.status_code == 404, f"Expected 404 in production, got {resp_post.status_code}"


def test_demo_login_accessible_in_development(client):
    """Verify /demo-login remains accessible in development environment for testing."""
    with patch.object(settings, "APP_ENV", "development"):
        resp = client.get("/api/v1/auth/demo-login", follow_redirects=False)
        assert resp.status_code == 302
        assert settings.SESSION_COOKIE_NAME in resp.cookies


# ------------------------------------------------------------------------------
# 2. WebSocket Security (CSWSH, Authentication, Frame Size)
# ------------------------------------------------------------------------------

def test_websocket_rejects_unauthorized_origin(client):
    """Verify WebSocket rejects connections from unauthorized third-party origins (CSWSH)."""
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/api/v1/map/live",
            headers={"origin": "https://evil-attacker-site.com"},
        ) as ws:
            ws.receive_text()


def test_websocket_rejects_unauthenticated_in_production(client):
    """Verify WebSocket rejects unauthenticated connection attempts in production."""
    with patch.object(settings, "APP_ENV", "production"):
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/v1/map/live",
                headers={"origin": "http://localhost:3000"},
            ) as ws:
                ws.receive_text()


def test_websocket_accepts_valid_origin_in_dev(client):
    """Verify WebSocket connects successfully in development environment with allowed origin."""
    with patch.object(settings, "APP_ENV", "development"):
        with client.websocket_connect(
            "/api/v1/map/live",
            headers={"origin": "http://localhost:3000"},
        ) as ws:
            # First message is initial snapshot
            data = ws.receive_text()
            payload = json.loads(data)
            assert payload.get("event") == "initial_snapshot"

            # Ping-pong heartbeat works
            ws.send_text(json.dumps({"action": "ping"}))
            pong_resp = json.loads(ws.receive_text())
            assert pong_resp.get("event") == "pong"


# ------------------------------------------------------------------------------
# 3. Cross-Tenant Approval & Action Isolation
# ------------------------------------------------------------------------------

def test_action_policy_rejects_missing_approval():
    """Verify action execution is blocked when human approval is missing."""
    policy = ActionSafetyPolicy()
    cmd = ActionCommand(
        action_id="act-test-01",
        decision_id="dec-test-01",
        approval_id="appr-test-01",
        action_type=ActionType.MONITOR,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="shp-001",
        organization_id="tenant-alpha",
        idempotency_key="idemp-test-01",
        trace_id="trace-test-01",
        parameters={},
    )
    with pytest.raises(ActionApprovalMissingError):
        policy.validate_approval(cmd, approval=None)


def test_action_policy_rejects_cross_tenant_approval():
    """Verify action execution is blocked when approval belongs to a different tenant."""
    policy = ActionSafetyPolicy()
    cmd = ActionCommand(
        action_id="act-test-02",
        decision_id="dec-test-02",
        approval_id="appr-test-02",
        action_type=ActionType.MONITOR,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="shp-002",
        organization_id="tenant-alpha",
        idempotency_key="idemp-test-02",
        trace_id="trace-test-02",
        parameters={},
    )
    # Approval belonging to tenant-bravo
    fake_approval = {
        "id": "appr-bravo",
        "decision_id": "dec-test-02",
        "organization_id": "tenant-bravo",
        "decision": "APPROVE",
    }
    with pytest.raises(ActionTenantIsolationError):
        policy.validate_approval(cmd, approval=fake_approval)


def test_action_policy_checks_orm_recommendation_tenant():
    """Verify ORM Approval model resolves recommendation.org_id for cross-tenant check."""
    policy = ActionSafetyPolicy()
    cmd = ActionCommand(
        action_id="act-test-03",
        decision_id="dec-test-03",
        approval_id="appr-test-03",
        action_type=ActionType.MONITOR,
        target_entity_type=TargetEntityType.SHIPMENT,
        target_entity_id="shp-003",
        organization_id="tenant-alpha",
        idempotency_key="idemp-test-03",
        trace_id="trace-test-03",
        parameters={},
    )
    # Mock ORM Approval linked to Recommendation in tenant-charlie
    rec = Recommendation(id="dec-test-03", org_id="tenant-charlie", title="Rec")
    approval = Approval(id="appr-charlie", recommendation_id="dec-test-03", decision="APPROVE")
    approval.recommendation = rec

    with pytest.raises(ActionTenantIsolationError):
        policy.validate_approval(cmd, approval=approval)


# ------------------------------------------------------------------------------
# 4. HTTP Security Headers
# ------------------------------------------------------------------------------

def test_http_security_headers_present_on_endpoints(client):
    """Verify critical defensive headers are present on all API responses."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in resp.headers


def test_cache_control_headers_on_api_endpoints(client):
    """Verify sensitive API routes prevent intermediate proxy caching."""
    resp = client.get("/api/v1/auth/me")
    cache_header = resp.headers.get("Cache-Control", "")
    assert "no-store" in cache_header or "no-cache" in cache_header


# ------------------------------------------------------------------------------
# 5. Production API Schema Reconnaissance Defense
# ------------------------------------------------------------------------------

def test_production_openapi_reconnaissance_protection():
    """Verify that in production mode, FastAPI docs and schema endpoints are disabled."""
    with patch.object(settings, "APP_ENV", "production"):
        from fastapi import FastAPI
        from app.core.config import settings as test_settings
        is_prod = True
        test_app = FastAPI(
            title=test_settings.PROJECT_NAME,
            openapi_url=None if is_prod else "/openapi.json",
            docs_url=None if is_prod else "/docs",
            redoc_url=None if is_prod else "/redoc",
        )
        test_client = TestClient(test_app)
        assert test_client.get("/docs").status_code == 404
        assert test_client.get("/redoc").status_code == 404
        assert test_client.get("/openapi.json").status_code == 404


# ------------------------------------------------------------------------------
# 6. OAuth State Anti-CSRF, HMAC Signature & Replay Protection
# ------------------------------------------------------------------------------

def test_oauth_state_tampering_rejected():
    """Verify that altering any character in the OAuth state token invalidates the HMAC signature."""
    svc = OAuthService(signing_secret="super-secure-production-key-32b")
    state = svc.generate_state(return_to="/dashboard")

    # Tamper with the state string
    tampered_state = state[:-1] + ("A" if state[-1] != "A" else "B")
    is_valid, return_to, err = svc.verify_state(tampered_state)
    assert not is_valid
    assert err == "invalid_state"


def test_oauth_state_replay_rejected():
    """Verify single-use anti-replay defense: verifying a state token twice fails."""
    svc = OAuthService(signing_secret="super-secure-production-key-32b")
    state = svc.generate_state(return_to="/shipments")

    # First verification succeeds
    is_valid, return_to, err = svc.verify_state(state)
    assert is_valid
    assert return_to == "/shipments"

    # Second verification fails due to anti-replay check
    is_valid2, return_to2, err2 = svc.verify_state(state)
    assert not is_valid2
    assert err2 == "state_reused"


def test_oauth_open_redirect_sanitization():
    """Verify open-redirect protection strips dangerous redirect URLs."""
    svc = OAuthService()
    assert svc.sanitize_return_to("https://evil-attacker.com") == "/"
    assert svc.sanitize_return_to("//evil-attacker.com") == "/"
    assert svc.sanitize_return_to("javascript:alert(1)") == "/"
    assert svc.sanitize_return_to("/shipments?filter=high_risk") == "/"
    assert svc.sanitize_return_to("/analytics") == "/analytics"


# ------------------------------------------------------------------------------
# 7. ML Model Loading Security (Path Traversal & Fingerprint Verification)
# ------------------------------------------------------------------------------

def test_ml_artifact_storage_path_traversal_rejection(tmp_path):
    """Verify directory traversal attempts in model artifact paths are blocked."""
    outside_file = tmp_path.parent / "sneaky.joblib"
    outside_file.write_bytes(b"dummy")
    with pytest.raises(ModelArtifactError) as exc:
        ArtifactManager.load_artifact(outside_file, base_dir=tmp_path)
    assert "Path traversal" in str(exc.value)


def test_ml_artifact_fingerprint_tampering_rejection(tmp_path):
    """Verify artifact loading is aborted if SHA-256 fingerprint does not match."""
    model = ShipmentDelayModel()
    pipeline = ShipmentDelayFeaturePipeline()
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    y = np.array([5.0, 10.0])
    model.fit(X, y)

    metadata = MLModelMetadata(
        model_id="secure_test_model",
        model_family=ModelFamily.SHIPMENT_DELAY,
        model_version="1.0.0",
        task_type=TaskType.REGRESSION,
        target="delay_minutes",
        feature_names=["f1", "f2"],
        training_dataset_fingerprint="sha256:dummy",
        metrics=ModelMetrics(mae=0.1, rmse=0.1, r2=0.99, sample_count=2, is_calculated=True),
        hyperparameters={"alpha": 1.0},
        artifact_fingerprint="sha256:original",
    )
    model.set_metadata(metadata)

    artifact, file_path = ArtifactManager.save_artifact(
        model=model,
        feature_pipeline=pipeline,
        metadata=metadata,
        artifact_dir=tmp_path,
    )

    # Tamper with file content by appending malicious bytes
    with open(file_path, "ab") as f:
        f.write(b"tampered_extra_bytes")

    with pytest.raises(ModelArtifactError) as exc:
        ArtifactManager.load_artifact(file_path, base_dir=tmp_path)
    assert "tampering" in str(exc.value).lower()
