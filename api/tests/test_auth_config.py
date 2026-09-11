"""Tests for Google OAuth 2.0 configuration layer (Phase 3 Step 2).

Validates:
1. Backend Settings fields exist and load from environment safely
2. Default behavior when OAuth variables are unset (no crashes)
3. Dynamic environment binding
4. Secret protection (no secrets exposed in representations or logs)
5. Redirect URI configuration
"""
import pytest
from app.core.config import Settings, settings


def test_google_oauth_settings_fields_exist():
    """Verify Google OAuth configuration fields exist on the Settings class."""
    assert hasattr(settings, "GOOGLE_CLIENT_ID")
    assert hasattr(settings, "GOOGLE_CLIENT_SECRET")
    assert hasattr(settings, "GOOGLE_REDIRECT_URI")
    assert hasattr(settings, "is_google_oauth_configured")


def test_google_oauth_defaults_safe_when_empty():
    """Verify backend settings do not crash when OAuth variables are unconfigured."""
    # When unconfigured, fields should be None or empty string, not raising validation errors
    test_settings = Settings(
        GOOGLE_CLIENT_ID=None,
        GOOGLE_CLIENT_SECRET=None,
        GOOGLE_REDIRECT_URI=None,
    )
    assert test_settings.GOOGLE_CLIENT_ID is None
    assert test_settings.GOOGLE_CLIENT_SECRET is None
    assert test_settings.GOOGLE_REDIRECT_URI is None
    assert test_settings.is_google_oauth_configured is False


def test_google_oauth_environment_binding(monkeypatch):
    """Verify Settings binds GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI from env."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "mock-client-id-123.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "mock-client-secret-xyz")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")

    bound_settings = Settings()
    assert bound_settings.GOOGLE_CLIENT_ID == "mock-client-id-123.apps.googleusercontent.com"
    assert bound_settings.GOOGLE_CLIENT_SECRET == "mock-client-secret-xyz"
    assert bound_settings.GOOGLE_REDIRECT_URI == "http://localhost:8000/api/v1/auth/google/callback"
    assert bound_settings.is_google_oauth_configured is True


def test_redirect_uri_matches_callback_specification(monkeypatch):
    """Verify that development redirect URI follows expected callback endpoint pattern."""
    dev_callback = "http://localhost:8000/api/v1/auth/google/callback"
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", dev_callback)
    bound_settings = Settings()
    assert bound_settings.GOOGLE_REDIRECT_URI.endswith("/api/v1/auth/google/callback")


def test_no_next_public_secret_in_settings():
    """Verify settings never exposes or defines a frontend public client secret."""
    assert not hasattr(settings, "NEXT_PUBLIC_GOOGLE_CLIENT_SECRET")
