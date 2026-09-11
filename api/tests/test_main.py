from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "RiskWise API"
    assert data["version"] == "1.0.0"
    assert data["docs"] == "/docs"
    assert data["openapi"] == "/openapi.json"


def test_root_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_v1_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_v1_health_db_success():
    with patch("app.api.v1.endpoints.health.check_db_connection", return_value=(True, "Database connection successful")):
        response = client.get("/api/v1/health/db")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_api_v1_health_db_unavailable():
    with patch("app.api.v1.endpoints.health.check_db_connection", return_value=(False, "Database connection unavailable")):
        response = client.get("/api/v1/health/db")
        assert response.status_code == 503
        assert response.json() == {"detail": {"status": "unavailable"}}


def test_openapi_spec():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "RiskWise API"
    assert data["info"]["version"] == "1.0.0"
    assert "/api/v1/health" in data["paths"]
    assert "/api/v1/health/db" in data["paths"]


def test_docs_page():
    response = client.get("/docs")
    assert response.status_code == 200
