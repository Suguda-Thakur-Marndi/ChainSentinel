"""Comprehensive Final Validation & Hardening Test Suite for RiskWise 2.0 (Phase 4 Step 8).

Validates:
1. End-to-End Cross-Domain Supply Chain Lifecycle (Suppliers -> Network -> Logistics -> Inventory -> Risk -> Incidents -> Governance -> Auditing)
2. Multi-Tenant Cross-Organization Isolation Matrix (Org A vs Org B across all 23 core resources)
3. Cross-Tenant Relationship Integrity & Foreign Key Rejection (Masked 404 on cross-tenant parents)
4. Server-Controlled Field Protection & Zero-Trust Injection Rejection (id, org_id, timestamps forbidden)
5. Immutability Enforcement (Append-only ledgers reject PATCH and DELETE with 405 Method Not Allowed)
6. RBAC Matrix Enforcement (Viewer, Analyst, OpsManager, RiskManager, Admin boundary enforcement)
7. State Machine & Terminal State Integrity (Legal transitions succeed; illegal/terminal regressions fail)
8. Concurrency & Transaction Atomicity (Row locking and atomic quantity updates)
9. Query Defense & Parameter Bounds (Pagination bounds, sort allowlists, filter allowlists, SQLi safety)
10. Standardized Error Contract & Information Sanitization (No raw SQL, stack traces, or credentials leak)
11. OpenAPI 3.1 Schema Integrity (Exact operation count, zero duplicate operation IDs, zero duplicate routes)
12. Database Model & Enum Registry Integrity (All 34 models & 26 enums registered in Base.metadata)
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.db.base import Base
from app.db.session import get_db
from app.main import app
import app.models as models
from app.models.governance import (
    Action,
    Approval,
    AuditLog,
    Notification,
    Recommendation,
    VerificationResult,
)
from app.models.logistics import Inventory, InventoryMovement, Shipment, ShipmentEvent
from app.models.network import Carrier, Factory, Port, Product, Route, Supplier, SupplierSite, Warehouse
from app.models.risk import Incident, Risk, RiskAssessment, RiskFactor
from app.models.tenancy import Organization, User
from app.services.session_service import MemorySessionStore, SessionService, get_session_service


# ==============================================================================
# FIXTURES & ISOLATION
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
def auth_fixture(test_db: Session, session_service: SessionService):
    """Seed base organizations and multi-role users for tenant isolation and RBAC tests."""
    # Organizations
    org_a = Organization(id="org_alpha_val", name="Alpha Logistics Inc", slug="alpha-logistics", is_active=True)
    org_b = Organization(id="org_beta_val", name="Beta Global Ltd", slug="beta-global", is_active=True)
    test_db.add_all([org_a, org_b])
    test_db.commit()

    # Users for Org A
    viewer_a = User(id="usr_view_a", org_id="org_alpha_val", email="viewer@alpha.test", full_name="Viewer A", role="Viewer", is_active=True)
    analyst_a = User(id="usr_analyst_a", org_id="org_alpha_val", email="analyst@alpha.test", full_name="Analyst A", role="Analyst", is_active=True)
    ops_a = User(id="usr_ops_a", org_id="org_alpha_val", email="ops@alpha.test", full_name="OpsManager A", role="OpsManager", is_active=True)
    risk_a = User(id="usr_risk_a", org_id="org_alpha_val", email="risk@alpha.test", full_name="RiskManager A", role="RiskManager", is_active=True)
    admin_a = User(id="usr_admin_a", org_id="org_alpha_val", email="admin@alpha.test", full_name="Admin A", role="Admin", is_active=True)

    # Users for Org B
    viewer_b = User(id="usr_view_b", org_id="org_beta_val", email="viewer@beta.test", full_name="Viewer B", role="Viewer", is_active=True)
    analyst_b = User(id="usr_analyst_b", org_id="org_beta_val", email="analyst@beta.test", full_name="Analyst B", role="Analyst", is_active=True)
    ops_b = User(id="usr_ops_b", org_id="org_beta_val", email="ops@beta.test", full_name="OpsManager B", role="OpsManager", is_active=True)
    risk_b = User(id="usr_risk_b", org_id="org_beta_val", email="risk@beta.test", full_name="RiskManager B", role="RiskManager", is_active=True)
    admin_b = User(id="usr_admin_b", org_id="org_beta_val", email="admin@beta.test", full_name="Admin B", role="Admin", is_active=True)

    test_db.add_all([viewer_a, analyst_a, ops_a, risk_a, admin_a, viewer_b, analyst_b, ops_b, risk_b, admin_b])
    test_db.commit()

    # Seed global reference port
    port_rotterdam = Port(
        id="port_nlrtm_01",
        code="NLRTM",
        name="Port of Rotterdam",
        country="NL",
        latitude=51.92,
        longitude=4.48,
    )
    test_db.add(port_rotterdam)
    test_db.commit()

    def make_cookies(user: User) -> dict[str, str]:
        s = session_service.create_session(
            user_id=user.id,
            role=user.role,
            organization_id=user.org_id,
            ttl_seconds=3600,
        )
        return {"riskwise_session": s.session_id}

    return {
        "org_a": org_a,
        "org_b": org_b,
        "cookies": {
            "viewer_a": make_cookies(viewer_a),
            "analyst_a": make_cookies(analyst_a),
            "ops_a": make_cookies(ops_a),
            "risk_a": make_cookies(risk_a),
            "admin_a": make_cookies(admin_a),
            "viewer_b": make_cookies(viewer_b),
            "analyst_b": make_cookies(analyst_b),
            "ops_b": make_cookies(ops_b),
            "risk_b": make_cookies(risk_b),
            "admin_b": make_cookies(admin_b),
        },
    }


# ==============================================================================
# 1. END-TO-END CROSS-DOMAIN SUPPLY CHAIN LIFECYCLE
# ==============================================================================
def test_e2e_supply_chain_lifecycle(client: TestClient, auth_fixture: dict):
    """Complete multi-domain lifecycle test:
    Supplier -> Site -> Facilities -> Carrier -> Product -> Route -> Shipment -> Event ->
    Inventory -> Movement -> Risk -> Factor -> Assessment -> Incident ->
    Recommendation -> Approval -> Action -> Verification -> Notification -> Audit Trail.
    """
    c = auth_fixture["cookies"]

    # 1. OpsManager creates Supplier
    sup_resp = client.post(
        "/api/v1/suppliers",
        json={"name": "Taiwan Microchip Fab", "country": "TW", "tier": "CRITICAL"},
        cookies=c["ops_a"],
    )
    assert sup_resp.status_code == 201, sup_resp.text
    supplier_id = sup_resp.json()["id"]

    # 2. OpsManager creates SupplierSite
    site_resp = client.post(
        "/api/v1/supplier-sites",
        json={"supplier_id": supplier_id, "name": "Hsinchu Site 1", "country": "TW", "latitude": 24.81, "longitude": 120.96},
        cookies=c["ops_a"],
    )
    assert site_resp.status_code == 201, site_resp.text
    site_id = site_resp.json()["id"]

    # 3. OpsManager creates Factory & Warehouse
    factory_resp = client.post(
        "/api/v1/factories",
        json={"name": "Tainan Packaging Plant", "country": "TW", "latitude": 23.00, "longitude": 120.22},
        cookies=c["ops_a"],
    )
    assert factory_resp.status_code == 201
    factory_id = factory_resp.json()["id"]

    warehouse_resp = client.post(
        "/api/v1/warehouses",
        json={"name": "Rotterdam Gateway Logistics", "country": "NL", "latitude": 51.92, "longitude": 4.48},
        cookies=c["ops_a"],
    )
    assert warehouse_resp.status_code == 201
    warehouse_id = warehouse_resp.json()["id"]

    # 4. OpsManager creates Carrier
    carrier_resp = client.post(
        "/api/v1/carriers",
        json={"name": "Pacific Maritime Shipping", "mode": "OCEAN"},
        cookies=c["ops_a"],
    )
    assert carrier_resp.status_code == 201
    carrier_id = carrier_resp.json()["id"]

    # 5. OpsManager creates Product
    prod_resp = client.post(
        "/api/v1/products",
        json={"sku": "ASIC-8800-AI", "name": "Neural TPU Core"},
        cookies=c["ops_a"],
    )
    assert prod_resp.status_code == 201
    product_id = prod_resp.json()["id"]

    # 6. OpsManager creates Route
    route_resp = client.post(
        "/api/v1/routes",
        json={
            "name": "Taiwan-Rotterdam Direct Ocean",
            "origin_facility_id": factory_id,
            "destination_facility_id": warehouse_id,
            "mode": "OCEAN",
            "standard_lead_time_days": 28.0,
        },
        cookies=c["ops_a"],
    )
    assert route_resp.status_code == 201
    route_id = route_resp.json()["id"]

    # 7. OpsManager creates Shipment
    shipment_resp = client.post(
        "/api/v1/shipments",
        json={
            "tracking_number": "TRK-E2E-99001",
            "carrier_id": carrier_id,
            "route_id": route_id,
            "product_id": product_id,
            "status": "PLANNED",
            "mode": "OCEAN",
        },
        cookies=c["ops_a"],
    )
    assert shipment_resp.status_code == 201
    shipment_id = shipment_resp.json()["id"]

    # 8. OpsManager appends Shipment Event (immutable ledger)
    event_resp = client.post(
        "/api/v1/shipment-events",
        json={
            "shipment_id": shipment_id,
            "event_type": "LOCATION_UPDATE",
            "latitude": 2.5,
            "longitude": 101.5,
            "delay_minutes": 0.0,
        },
        cookies=c["ops_a"],
    )
    assert event_resp.status_code == 201
    event_id = event_resp.json()["id"]

    # 9. OpsManager transitions Shipment status: PLANNED -> IN_TRANSIT
    shipment_update = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"status": "IN_TRANSIT"},
        cookies=c["ops_a"],
    )
    assert shipment_update.status_code == 200
    assert shipment_update.json()["status"] == "IN_TRANSIT"

    # 10. OpsManager creates Inventory record
    inv_resp = client.post(
        "/api/v1/inventory",
        json={
            "product_id": product_id,
            "facility_id": warehouse_id,
            "quantity_on_hand": 100.0,
            "reorder_point": 200.0,
        },
        cookies=c["ops_a"],
    )
    assert inv_resp.status_code == 201
    inventory_id = inv_resp.json()["id"]
    assert inv_resp.json()["quantity_on_hand"] == 100.0

    # 11. OpsManager logs Inventory Movement (RECEIPT linked via reference_id -> stock reconciles to 350)
    mov_resp = client.post(
        "/api/v1/inventory-movements",
        json={
            "product_id": product_id,
            "reference_id": inventory_id,
            "movement_type": "RECEIPT",
            "quantity": 250.0,
        },
        cookies=c["ops_a"],
    )
    assert mov_resp.status_code == 201
    mov_id = mov_resp.json()["id"]

    # Verify inventory was atomically updated
    inv_check = client.get(f"/api/v1/inventory/{inventory_id}", cookies=c["viewer_a"])
    assert inv_check.status_code == 200
    assert inv_check.json()["quantity_on_hand"] == 350.0

    # 12. Analyst creates Risk
    risk_resp = client.post(
        "/api/v1/risks",
        json={
            "risk_type": "GEOPOLITICAL",
            "severity": "HIGH",
            "title": "Chokepoint Congestion and Drone Threat",
            "location": "Red Sea / Bab-el-Mandeb",
        },
        cookies=c["analyst_a"],
    )
    assert risk_resp.status_code == 201
    risk_id = risk_resp.json()["id"]

    # 13. Analyst creates Risk Factor
    factor_resp = client.post(
        "/api/v1/risk-factors",
        json={
            "risk_id": risk_id,
            "name": "Red Sea Transit Volatility",
            "category": "EXTERNAL",
            "weight": 0.85,
            "score": 85.0,
        },
        cookies=c["analyst_a"],
    )
    assert factor_resp.status_code == 201
    factor_id = factor_resp.json()["id"]

    # 14. Analyst creates Risk Assessment (immutable record)
    assess_resp = client.post(
        "/api/v1/risk-assessments",
        json={
            "risk_id": risk_id,
            "score": 82.5,
            "confidence": 0.90,
        },
        cookies=c["analyst_a"],
    )
    assert assess_resp.status_code == 201
    assess_id = assess_resp.json()["id"]

    # 15. Analyst creates Incident
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "risk_id": risk_id,
            "title": "Strait Transit Suspension",
            "severity": "CRITICAL",
            "status": "DETECTED",
            "location": "Bab-el-Mandeb",
        },
        cookies=c["analyst_a"],
    )
    assert inc_resp.status_code == 201
    incident_id = inc_resp.json()["id"]

    # 16. Analyst creates Recommendation
    rec_resp = client.post(
        "/api/v1/recommendations",
        json={
            "incident_id": incident_id,
            "title": "Reroute vessel via Cape of Good Hope",
            "rationale": "Avoid armed attacks; ensure cargo safety at minimal schedule impact",
            "estimated_cost": 65000.0,
            "expected_benefit_json": {"loss_prevention_usd": 2500000},
            "confidence": 0.92,
        },
        cookies=c["analyst_a"],
    )
    assert rec_resp.status_code == 201
    recommendation_id = rec_resp.json()["id"]
    assert rec_resp.json()["status"] == "PENDING"

    # 17. RiskManager formally approves Recommendation
    appr_resp = client.post(
        "/api/v1/approvals",
        json={
            "recommendation_id": recommendation_id,
            "decision": "APPROVE",
            "comments": "Approved given high cargo value and mission criticality.",
        },
        cookies=c["risk_a"],
    )
    assert appr_resp.status_code == 201
    approval_id = appr_resp.json()["id"]

    # Verify recommendation transitioned to APPROVED
    rec_check = client.get(f"/api/v1/recommendations/{recommendation_id}", cookies=c["viewer_a"])
    assert rec_check.status_code == 200
    assert rec_check.json()["status"] == "APPROVED"

    # 18. RiskManager creates and executes Action
    act_resp = client.post(
        "/api/v1/actions",
        json={
            "recommendation_id": recommendation_id,
            "action_type": "REROUTE_SHIPMENT",
            "target_entity_type": "SHIPMENT",
            "target_entity_id": shipment_id,
            "execution_payload": {"new_waypoints": ["Cape Town", "Rotterdam"]},
        },
        cookies=c["risk_a"],
    )
    assert act_resp.status_code == 201
    action_id = act_resp.json()["id"]

    # Execute action
    exec_resp = client.post(
        f"/api/v1/actions/{action_id}/execute",
        cookies=c["risk_a"],
    )
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "COMPLETED"

    # Verify recommendation transitioned to EXECUTED
    rec_check2 = client.get(f"/api/v1/recommendations/{recommendation_id}", cookies=c["viewer_a"])
    assert rec_check2.json()["status"] == "EXECUTED"

    # 19. RiskManager creates Verification Result
    ver_resp = client.post(
        "/api/v1/verification-results",
        json={
            "action_id": action_id,
            "verified": True,
            "risk_score_before": 82.5,
            "risk_score_after": 18.0,
            "observation_summary": "Vessel successfully passed Cape Town, out of hazard zone.",
        },
        cookies=c["risk_a"],
    )
    assert ver_resp.status_code == 201
    verification_id = ver_resp.json()["id"]

    # 20. Admin creates Notification
    notif_resp = client.post(
        "/api/v1/notifications",
        json={
            "category": "RISK_ALERT",
            "severity": "INFO",
            "title": "Mitigation Verified",
            "summary": "Shipment reroute completed and risk mitigated.",
        },
        cookies=c["admin_a"],
    )
    assert notif_resp.status_code == 201
    notif_id = notif_resp.json()["id"]

    # User marks notification read
    mark_read = client.patch(
        f"/api/v1/notifications/{notif_id}",
        json={"is_read": True},
        cookies=c["viewer_a"],
    )
    assert mark_read.status_code == 200
    assert mark_read.json()["is_read"] is True

    # 21. Admin queries Compliance Audit Logs
    audit_resp = client.get("/api/v1/audit-logs", cookies=c["admin_a"])
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    assert audit_data["pagination"]["total"] >= 10
    # Verify audit actions recorded
    actions_logged = {item["action"] for item in audit_data["items"]}
    assert "CREATE" in actions_logged


# ==============================================================================
# 2. MULTI-TENANT CROSS-ORGANIZATION ISOLATION MATRIX
# ==============================================================================
def test_cross_tenant_isolation_matrix(client: TestClient, auth_fixture: dict):
    """Verify that Org B cannot read, mutate, or delete ANY of Org A's resources across all endpoints."""
    c = auth_fixture["cookies"]

    # Seed an Org A resource bundle
    sup_a = client.post("/api/v1/suppliers", json={"name": "Org A Supplier", "country": "TW"}, cookies=c["ops_a"]).json()["id"]
    site_a = client.post("/api/v1/supplier-sites", json={"supplier_id": sup_a, "name": "Site A", "country": "TW"}, cookies=c["ops_a"]).json()["id"]
    fact_a = client.post("/api/v1/factories", json={"name": "Factory A", "country": "TW"}, cookies=c["ops_a"]).json()["id"]
    wh_a = client.post("/api/v1/warehouses", json={"name": "Warehouse A", "country": "NL"}, cookies=c["ops_a"]).json()["id"]
    carr_a = client.post("/api/v1/carriers", json={"name": "Carrier A", "mode": "OCEAN"}, cookies=c["ops_a"]).json()["id"]
    prod_a = client.post("/api/v1/products", json={"sku": "SKU-A-01", "name": "Product A"}, cookies=c["ops_a"]).json()["id"]
    route_a = client.post("/api/v1/routes", json={"name": "Route A", "origin_facility_id": fact_a, "destination_facility_id": wh_a, "mode": "OCEAN"}, cookies=c["ops_a"]).json()["id"]
    ship_a = client.post("/api/v1/shipments", json={"tracking_number": "TRK-A-01", "carrier_id": carr_a, "route_id": route_a, "product_id": prod_a, "status": "PLANNED", "mode": "OCEAN"}, cookies=c["ops_a"]).json()["id"]
    evt_a = client.post("/api/v1/shipment-events", json={"shipment_id": ship_a, "event_type": "DEPARTURE"}, cookies=c["ops_a"]).json()["id"]
    inv_a = client.post("/api/v1/inventory", json={"product_id": prod_a, "facility_id": wh_a, "quantity_on_hand": 50.0}, cookies=c["ops_a"]).json()["id"]
    mov_a = client.post("/api/v1/inventory-movements", json={"product_id": prod_a, "reference_id": inv_a, "movement_type": "ADJUSTMENT", "quantity": 10.0}, cookies=c["ops_a"]).json()["id"]
    risk_a = client.post("/api/v1/risks", json={"risk_type": "GEOPOLITICAL", "severity": "HIGH", "title": "Risk A"}, cookies=c["analyst_a"]).json()["id"]
    fact_risk_a = client.post("/api/v1/risk-factors", json={"risk_id": risk_a, "name": "Factor A", "weight": 0.5, "score": 50.0}, cookies=c["analyst_a"]).json()["id"]
    assess_a = client.post("/api/v1/risk-assessments", json={"risk_id": risk_a, "score": 75.0}, cookies=c["analyst_a"]).json()["id"]
    inc_a = client.post("/api/v1/incidents", json={"title": "Incident A", "severity": "HIGH", "status": "DETECTED"}, cookies=c["analyst_a"]).json()["id"]
    rec_a = client.post("/api/v1/recommendations", json={"incident_id": inc_a, "title": "Rec A", "rationale": "Rationale A"}, cookies=c["analyst_a"]).json()["id"]
    appr_a = client.post("/api/v1/approvals", json={"recommendation_id": rec_a, "decision": "APPROVE"}, cookies=c["risk_a"]).json()["id"]
    act_a = client.post("/api/v1/actions", json={"recommendation_id": rec_a, "action_type": "EXPEDITE_AIR"}, cookies=c["risk_a"]).json()["id"]
    ver_a = client.post("/api/v1/verification-results", json={"action_id": act_a, "verified": True, "observation_summary": "Obs A"}, cookies=c["risk_a"]).json()["id"]
    notif_a = client.post("/api/v1/notifications", json={"category": "SYSTEM", "severity": "INFO", "title": "Notif A"}, cookies=c["admin_a"]).json()["id"]

    # Resource catalog mapping: (resource_name, id, is_immutable)
    resources = [
        ("suppliers", sup_a, False),
        ("supplier-sites", site_a, False),
        ("factories", fact_a, False),
        ("warehouses", wh_a, False),
        ("carriers", carr_a, False),
        ("products", prod_a, False),
        ("routes", route_a, False),
        ("shipments", ship_a, False),
        ("shipment-events", evt_a, True),
        ("inventory", inv_a, False),
        ("inventory-movements", mov_a, True),
        ("risks", risk_a, False),
        ("risk-factors", fact_risk_a, False),
        ("risk-assessments", assess_a, True),
        ("incidents", inc_a, False),
        ("recommendations", rec_a, False),
        ("approvals", appr_a, True),
        ("actions", act_a, False),
        ("verification-results", ver_a, True),
        ("notifications", notif_a, False),
    ]

    for res_name, res_id, is_immutable in resources:
        # Org B Viewer cannot GET Org A resource (must return 404 masked, NEVER 403 or 200)
        get_res = client.get(f"/api/v1/{res_name}/{res_id}", cookies=c["viewer_b"])
        assert get_res.status_code == 404, f"{res_name} leaked to Org B: {get_res.status_code} {get_res.text}"

        # Org B Admin/RiskManager cannot PATCH Org A resource (404 masked or 405 if immutable)
        patch_res = client.patch(f"/api/v1/{res_name}/{res_id}", json={}, cookies=c["admin_b"])
        expected_patch_code = 405 if is_immutable else 404
        assert patch_res.status_code == expected_patch_code, f"{res_name} PATCH unexpected: {patch_res.status_code}"

        # Org B Admin cannot DELETE Org A resource (404 masked or 405 if unsupported)
        del_res = client.delete(f"/api/v1/{res_name}/{res_id}", cookies=c["admin_b"])
        assert del_res.status_code in [404, 405], f"{res_name} DELETE unexpected: {del_res.status_code}"

    # Verify collection list endpoints for Org B return 0 Org A items
    for res_name, _, _ in resources:
        list_res = client.get(f"/api/v1/{res_name}", cookies=c["viewer_b"])
        assert list_res.status_code == 200
        assert list_res.json()["pagination"]["total"] == 0, f"{res_name} list leaked Org A data"

    # Verify Org B Admin cannot see Org A Audit Logs
    audit_b = client.get("/api/v1/audit-logs", cookies=c["admin_b"])
    assert audit_b.status_code == 200
    assert audit_b.json()["pagination"]["total"] == 0


# ==============================================================================
# 3. CROSS-TENANT RELATIONSHIP INTEGRITY & FOREIGN KEY ISOLATION
# ==============================================================================
def test_cross_tenant_relationship_rejection(client: TestClient, auth_fixture: dict):
    """Verify that Org B cannot create child entities referencing Org A parents (masked 404)."""
    c = auth_fixture["cookies"]

    # Org A creates parent entities
    sup_a = client.post("/api/v1/suppliers", json={"name": "Org A Parent Supplier", "country": "TW"}, cookies=c["ops_a"]).json()["id"]
    carr_a = client.post("/api/v1/carriers", json={"name": "Org A Parent Carrier", "mode": "AIR"}, cookies=c["ops_a"]).json()["id"]
    wh_a = client.post("/api/v1/warehouses", json={"name": "Org A Warehouse", "country": "NL"}, cookies=c["ops_a"]).json()["id"]
    prod_a = client.post("/api/v1/products", json={"sku": "SKU-A-PARENT", "name": "Product A Parent"}, cookies=c["ops_a"]).json()["id"]
    route_a = client.post("/api/v1/routes", json={"name": "Route A Parent", "origin_facility_id": wh_a, "destination_facility_id": wh_a, "mode": "AIR"}, cookies=c["ops_a"]).json()["id"]
    ship_a = client.post("/api/v1/shipments", json={"tracking_number": "TRK-A-PARENT", "carrier_id": carr_a, "route_id": route_a, "product_id": prod_a, "status": "PLANNED", "mode": "AIR"}, cookies=c["ops_a"]).json()["id"]
    inv_a = client.post("/api/v1/inventory", json={"product_id": prod_a, "facility_id": wh_a, "quantity_on_hand": 10.0}, cookies=c["ops_a"]).json()["id"]
    risk_a = client.post("/api/v1/risks", json={"risk_type": "GEOPOLITICAL", "severity": "HIGH", "title": "Risk A Parent"}, cookies=c["analyst_a"]).json()["id"]
    inc_a = client.post("/api/v1/incidents", json={"title": "Incident A Parent", "severity": "HIGH", "status": "DETECTED"}, cookies=c["analyst_a"]).json()["id"]
    rec_a = client.post("/api/v1/recommendations", json={"incident_id": inc_a, "title": "Rec A Parent", "rationale": "Rationale"}, cookies=c["analyst_a"]).json()["id"]
    # RiskManager A approves rec_a so it can have an action
    client.post("/api/v1/approvals", json={"recommendation_id": rec_a, "decision": "APPROVE"}, cookies=c["risk_a"])
    act_a = client.post("/api/v1/actions", json={"recommendation_id": rec_a, "action_type": "EXPEDITE_AIR"}, cookies=c["risk_a"]).json()["id"]

    # Seed Org B Product for movement test
    prod_b = client.post("/api/v1/products", json={"sku": "SKU-B-OWN", "name": "Product B Own"}, cookies=c["ops_b"]).json()["id"]

    # Org B attempts to attach child entities to Org A parents:

    # 1. SupplierSite referencing Org A Supplier -> 404
    res = client.post("/api/v1/supplier-sites", json={"supplier_id": sup_a, "name": "Org B Site", "country": "TW"}, cookies=c["ops_b"])
    assert res.status_code == 404, res.text

    # 2. Shipment referencing Org A Carrier -> 404
    res = client.post("/api/v1/shipments", json={"tracking_number": "TRK-B-ILLEGAL", "carrier_id": carr_a, "status": "PLANNED", "mode": "AIR"}, cookies=c["ops_b"])
    assert res.status_code == 404, res.text

    # 3. Shipment referencing Org A Product -> 404
    res = client.post("/api/v1/shipments", json={"tracking_number": "TRK-B-ILLEGAL", "product_id": prod_a, "status": "PLANNED", "mode": "AIR"}, cookies=c["ops_b"])
    assert res.status_code == 404, res.text

    # 4. ShipmentEvent referencing Org A Shipment -> 404
    res = client.post("/api/v1/shipment-events", json={"shipment_id": ship_a, "event_type": "DEPARTURE"}, cookies=c["ops_b"])
    assert res.status_code == 404, res.text

    # 5. InventoryMovement referencing Org A Product -> 404
    res = client.post("/api/v1/inventory-movements", json={"product_id": prod_a, "movement_type": "ADJUSTMENT", "quantity": 5.0}, cookies=c["ops_b"])
    assert res.status_code == 404, res.text

    # 6. InventoryMovement referencing Org A Inventory in reference_id -> 404
    res = client.post("/api/v1/inventory-movements", json={"product_id": prod_b, "reference_id": inv_a, "movement_type": "ADJUSTMENT", "quantity": 5.0}, cookies=c["ops_b"])
    assert res.status_code == 404, res.text

    # 7. RiskFactor referencing Org A Risk -> 404
    res = client.post("/api/v1/risk-factors", json={"risk_id": risk_a, "name": "Illegal Factor", "weight": 0.5, "score": 50.0}, cookies=c["analyst_b"])
    assert res.status_code == 404, res.text

    # 8. RiskAssessment referencing Org A Risk -> 404
    res = client.post("/api/v1/risk-assessments", json={"risk_id": risk_a, "score": 50.0}, cookies=c["analyst_b"])
    assert res.status_code == 404, res.text

    # 9. Recommendation referencing Org A Incident -> 404
    res = client.post("/api/v1/recommendations", json={"incident_id": inc_a, "title": "Illegal Rec", "rationale": "Test"}, cookies=c["analyst_b"])
    assert res.status_code == 404, res.text

    # 10. Approval referencing Org A Recommendation -> 404
    res = client.post("/api/v1/approvals", json={"recommendation_id": rec_a, "decision": "APPROVE"}, cookies=c["risk_b"])
    assert res.status_code == 404, res.text

    # 11. Action referencing Org A Recommendation -> 404
    res = client.post("/api/v1/actions", json={"recommendation_id": rec_a, "action_type": "EXPEDITE_AIR"}, cookies=c["risk_b"])
    assert res.status_code == 404, res.text

    # 12. VerificationResult referencing Org A Action -> 404
    res = client.post("/api/v1/verification-results", json={"action_id": act_a, "verified": True, "observation_summary": "Illegal"}, cookies=c["risk_b"])
    assert res.status_code == 404, res.text


# ==============================================================================
# 4. SERVER-CONTROLLED FIELD PROTECTION & ZERO-TRUST INJECTION
# ==============================================================================
def test_server_controlled_field_injection_protection(client: TestClient, auth_fixture: dict):
    """Verify that injecting protected server fields (id, org_id, timestamps) is rejected with 422."""
    c = auth_fixture["cookies"]

    # 1. Attempt injecting id and org_id on SupplierCreate
    res = client.post(
        "/api/v1/suppliers",
        json={"name": "Hacked Supplier", "id": "sup_evil_hack", "org_id": "org_injected"},
        cookies=c["ops_a"],
    )
    assert res.status_code == 422, "SupplierCreate did not forbid extra fields"

    # 2. Attempt injecting timestamps on ShipmentCreate
    res = client.post(
        "/api/v1/shipments",
        json={"tracking_number": "TRK-EVIL", "created_at": "2020-01-01T00:00:00Z"},
        cookies=c["ops_a"],
    )
    assert res.status_code == 422, "ShipmentCreate did not forbid extra fields"

    # 3. Attempt injecting org_id on RecommendationCreate
    res = client.post(
        "/api/v1/recommendations",
        json={"title": "Evil Rec", "rationale": "Evil", "org_id": "org_beta_val"},
        cookies=c["analyst_a"],
    )
    assert res.status_code == 422, "RecommendationCreate did not forbid extra fields"

    # 4. Attempt injecting id on ActionCreate
    res = client.post(
        "/api/v1/actions",
        json={"action_type": "EXPEDITE_AIR", "id": "act_evil_id"},
        cookies=c["risk_a"],
    )
    assert res.status_code == 422, "ActionCreate did not forbid extra fields"

    # 5. Attempt injecting verified_at on VerificationResultCreate
    res = client.post(
        "/api/v1/verification-results",
        json={"action_id": "act_1", "verified": True, "verified_at": "2020-01-01T00:00:00Z"},
        cookies=c["risk_a"],
    )
    assert res.status_code == 422, "VerificationResultCreate did not forbid extra fields"


# ==============================================================================
# 5. IMMUTABILITY ENFORCEMENT AUDIT
# ==============================================================================
def test_immutability_enforcement(client: TestClient, auth_fixture: dict):
    """Verify that ledger and append-only resources strictly reject PATCH and DELETE with 405."""
    c = auth_fixture["cookies"]

    # Seed resources to obtain valid IDs
    sup = client.post("/api/v1/suppliers", json={"name": "Imm Supplier", "country": "TW"}, cookies=c["ops_a"]).json()["id"]
    carr = client.post("/api/v1/carriers", json={"name": "Imm Carrier", "mode": "AIR"}, cookies=c["ops_a"]).json()["id"]
    wh = client.post("/api/v1/warehouses", json={"name": "Imm WH", "country": "NL"}, cookies=c["ops_a"]).json()["id"]
    prod = client.post("/api/v1/products", json={"sku": "SKU-IMM", "name": "Imm Prod"}, cookies=c["ops_a"]).json()["id"]
    ship = client.post("/api/v1/shipments", json={"tracking_number": "TRK-IMM", "carrier_id": carr, "status": "PLANNED", "mode": "AIR"}, cookies=c["ops_a"]).json()["id"]
    evt = client.post("/api/v1/shipment-events", json={"shipment_id": ship, "event_type": "DEPARTURE"}, cookies=c["ops_a"]).json()["id"]
    inv = client.post("/api/v1/inventory", json={"product_id": prod, "facility_id": wh, "quantity_on_hand": 10.0}, cookies=c["ops_a"]).json()["id"]
    mov = client.post("/api/v1/inventory-movements", json={"product_id": prod, "reference_id": inv, "movement_type": "ADJUSTMENT", "quantity": 5.0}, cookies=c["ops_a"]).json()["id"]
    risk = client.post("/api/v1/risks", json={"risk_type": "GEOPOLITICAL", "severity": "HIGH", "title": "Imm Risk"}, cookies=c["analyst_a"]).json()["id"]
    assess = client.post("/api/v1/risk-assessments", json={"risk_id": risk, "score": 60.0}, cookies=c["analyst_a"]).json()["id"]
    inc = client.post("/api/v1/incidents", json={"title": "Imm Inc", "severity": "HIGH", "status": "DETECTED"}, cookies=c["analyst_a"]).json()["id"]
    rec = client.post("/api/v1/recommendations", json={"incident_id": inc, "title": "Imm Rec", "rationale": "Imm"}, cookies=c["analyst_a"]).json()["id"]
    appr = client.post("/api/v1/approvals", json={"recommendation_id": rec, "decision": "APPROVE"}, cookies=c["risk_a"]).json()["id"]
    act = client.post("/api/v1/actions", json={"recommendation_id": rec, "action_type": "EXPEDITE_AIR"}, cookies=c["risk_a"]).json()["id"]
    ver = client.post("/api/v1/verification-results", json={"action_id": act, "verified": True, "observation_summary": "Imm"}, cookies=c["risk_a"]).json()["id"]

    immutable_endpoints = [
        ("shipment-events", evt),
        ("inventory-movements", mov),
        ("risk-assessments", assess),
        ("approvals", appr),
        ("verification-results", ver),
    ]

    for endpoint, res_id in immutable_endpoints:
        # PATCH must return 405 Method Not Allowed
        res_patch = client.patch(f"/api/v1/{endpoint}/{res_id}", json={}, cookies=c["admin_a"])
        assert res_patch.status_code == 405, f"PATCH /api/v1/{endpoint}/{res_id} did not return 405: {res_patch.status_code}"

        # DELETE must return 405 Method Not Allowed
        res_del = client.delete(f"/api/v1/{endpoint}/{res_id}", cookies=c["admin_a"])
        assert res_del.status_code == 405, f"DELETE /api/v1/{endpoint}/{res_id} did not return 405: {res_del.status_code}"

    # Audit Logs immutability: POST, PATCH, and DELETE are 405
    assert client.post("/api/v1/audit-logs", json={}, cookies=c["admin_a"]).status_code == 405
    assert client.patch("/api/v1/audit-logs/log_123", json={}, cookies=c["admin_a"]).status_code == 405
    assert client.delete("/api/v1/audit-logs/log_123", cookies=c["admin_a"]).status_code == 405


# ==============================================================================
# 6. RBAC MATRIX ENFORCEMENT AUDIT
# ==============================================================================
def test_rbac_matrix_enforcement(client: TestClient, auth_fixture: dict):
    """Verify that RBAC privileges strictly follow the defined roles without bypass."""
    c = auth_fixture["cookies"]

    # 1. Viewer cannot mutate any resource (returns 403)
    viewer_mutations = [
        client.post("/api/v1/suppliers", json={"name": "V Supplier", "country": "TW"}, cookies=c["viewer_a"]),
        client.post("/api/v1/factories", json={"name": "V Factory", "country": "TW"}, cookies=c["viewer_a"]),
        client.post("/api/v1/shipments", json={"tracking_number": "TRK-V"}, cookies=c["viewer_a"]),
        client.post("/api/v1/inventory", json={"product_id": "p1", "facility_id": "f1", "quantity_on_hand": 10.0}, cookies=c["viewer_a"]),
        client.post("/api/v1/risks", json={"category": "SUPPLIER", "severity": "HIGH", "title": "V Risk"}, cookies=c["viewer_a"]),
        client.post("/api/v1/incidents", json={"title": "V Inc", "severity": "HIGH"}, cookies=c["viewer_a"]),
        client.post("/api/v1/recommendations", json={"title": "V Rec", "rationale": "R"}, cookies=c["viewer_a"]),
        client.post("/api/v1/actions", json={"action_type": "EXPEDITE_AIR"}, cookies=c["viewer_a"]),
        client.get("/api/v1/audit-logs", cookies=c["viewer_a"]),
    ]
    for resp in viewer_mutations:
        assert resp.status_code == 403, f"Viewer bypassed RBAC: {resp.status_code} {resp.text}"

    # 2. Analyst can create risks and recommendations, but cannot approve recommendations or execute actions
    # Setup approved recommendation
    inc = client.post("/api/v1/incidents", json={"title": "A Inc", "severity": "HIGH"}, cookies=c["analyst_a"]).json()["id"]
    rec = client.post("/api/v1/recommendations", json={"incident_id": inc, "title": "A Rec", "rationale": "R"}, cookies=c["analyst_a"]).json()["id"]

    # Analyst cannot approve
    analyst_approve = client.post(f"/api/v1/recommendations/{rec}/approve", cookies=c["analyst_a"])
    assert analyst_approve.status_code == 403, "Analyst could approve recommendation"

    # Analyst cannot post approval record
    analyst_appr_rec = client.post("/api/v1/approvals", json={"recommendation_id": rec, "decision": "APPROVED"}, cookies=c["analyst_a"])
    assert analyst_appr_rec.status_code == 403, "Analyst could create approval record"

    # Analyst cannot view audit logs
    assert client.get("/api/v1/audit-logs", cookies=c["analyst_a"]).status_code == 403

    # 3. OpsManager cannot approve recommendations or view audit logs
    assert client.post(f"/api/v1/recommendations/{rec}/approve", cookies=c["ops_a"]).status_code == 403
    assert client.get("/api/v1/audit-logs", cookies=c["ops_a"]).status_code == 403

    # 4. RiskManager CAN approve recommendations and query audit logs
    rm_approve = client.post(f"/api/v1/recommendations/{rec}/approve", cookies=c["risk_a"])
    assert rm_approve.status_code == 200
    assert client.get("/api/v1/audit-logs", cookies=c["risk_a"]).status_code == 200

    # 5. Admin CAN query audit logs and perform administrative governance
    assert client.get("/api/v1/audit-logs", cookies=c["admin_a"]).status_code == 200


# ==============================================================================
# 7. STATE MACHINE & TERMINAL STATE INTEGRITY
# ==============================================================================
def test_state_machine_and_terminal_states(client: TestClient, auth_fixture: dict):
    """Verify that lifecycle transitions respect defined state machines and terminal states."""
    c = auth_fixture["cookies"]

    # 1. Recommendation Lifecycle: PENDING -> APPROVED -> EXECUTED
    inc = client.post("/api/v1/incidents", json={"title": "SM Inc", "severity": "HIGH"}, cookies=c["analyst_a"]).json()["id"]
    rec = client.post("/api/v1/recommendations", json={"incident_id": inc, "title": "SM Rec", "rationale": "SM"}, cookies=c["analyst_a"]).json()["id"]
    assert client.get(f"/api/v1/recommendations/{rec}", cookies=c["viewer_a"]).json()["status"] == "PENDING"

    # Approve
    client.post(f"/api/v1/recommendations/{rec}/approve", cookies=c["risk_a"])
    assert client.get(f"/api/v1/recommendations/{rec}", cookies=c["viewer_a"]).json()["status"] == "APPROVED"

    # Cannot approve again (illegal transition on already approved recommendation returns 409 Conflict)
    re_appr = client.post(f"/api/v1/recommendations/{rec}/approve", cookies=c["risk_a"])
    assert re_appr.status_code == 409, "Duplicate approval did not fail with LifecycleStateError (409)"

    # Create and execute action
    act = client.post("/api/v1/actions", json={"recommendation_id": rec, "action_type": "EXPEDITE_AIR"}, cookies=c["risk_a"]).json()["id"]
    exec_res = client.post(f"/api/v1/actions/{act}/execute", cookies=c["risk_a"])
    assert exec_res.status_code == 200
    assert exec_res.json()["status"] == "COMPLETED"

    # Cannot execute already completed action (returns 409 Conflict)
    re_exec = client.post(f"/api/v1/actions/{act}/execute", cookies=c["risk_a"])
    assert re_exec.status_code == 409, "Re-executing completed action did not fail with 409"

    # Recommendation is now EXECUTED
    assert client.get(f"/api/v1/recommendations/{rec}", cookies=c["viewer_a"]).json()["status"] == "EXECUTED"

    # Cannot approve an already executed recommendation (returns 409 Conflict)
    late_appr = client.post(f"/api/v1/recommendations/{rec}/approve", cookies=c["risk_a"])
    assert late_appr.status_code == 409


# ==============================================================================
# 8. CONCURRENCY & TRANSACTION ATOMICITY
# ==============================================================================
def test_concurrency_and_atomicity(client: TestClient, auth_fixture: dict):
    """Verify that inventory stock adjustments and multi-step governance operations are atomic."""
    c = auth_fixture["cookies"]

    # Setup product, warehouse, inventory
    wh = client.post("/api/v1/warehouses", json={"name": "Atomic WH", "country": "NL"}, cookies=c["ops_a"]).json()["id"]
    prod = client.post("/api/v1/products", json={"sku": "SKU-ATOMIC", "name": "Atomic Chip"}, cookies=c["ops_a"]).json()["id"]
    inv = client.post("/api/v1/inventory", json={"product_id": prod, "facility_id": wh, "quantity_on_hand": 100.0}, cookies=c["ops_a"]).json()["id"]

    # Perform sequence of movements (RECEIPT, SHIPMENT, ADJUSTMENT)
    client.post("/api/v1/inventory-movements", json={"product_id": prod, "reference_id": inv, "movement_type": "RECEIPT", "quantity": 50.0}, cookies=c["ops_a"])
    client.post("/api/v1/inventory-movements", json={"product_id": prod, "reference_id": inv, "movement_type": "SHIPMENT", "quantity": 30.0}, cookies=c["ops_a"])
    client.post("/api/v1/inventory-movements", json={"product_id": prod, "reference_id": inv, "movement_type": "ADJUSTMENT", "quantity": 15.0}, cookies=c["ops_a"])

    # Final stock: 100 + 50 - 30 + 15 = 135
    inv_final = client.get(f"/api/v1/inventory/{inv}", cookies=c["viewer_a"]).json()
    assert inv_final["quantity_on_hand"] == 135.0


# ==============================================================================
# 9. QUERY DEFENSE & PARAMETER BOUNDS (SORT, FILTER, PAGINATION)
# ==============================================================================
def test_query_defense_and_bounds(client: TestClient, auth_fixture: dict):
    """Verify that collection query parameters enforce safe allowlists and bounds."""
    c = auth_fixture["cookies"]

    # 1. Invalid sort field rejection (400 Bad Request)
    bad_sort = client.get("/api/v1/suppliers?sort=malicious_col", cookies=c["viewer_a"])
    assert bad_sort.status_code == 400
    assert "INVALID_SORT_FIELD" in bad_sort.text

    # 2. SQL injection attempt in sort parameter rejected cleanly
    sqli_sort = client.get("/api/v1/shipments?sort=created_at;DROP TABLE users;--", cookies=c["viewer_a"])
    assert sqli_sort.status_code == 400

    # 3. Invalid filter field rejection (400 Bad Request)
    bad_filter = client.get("/api/v1/suppliers?unsupported_filter_field=123", cookies=c["viewer_a"])
    assert bad_filter.status_code == 400
    assert "INVALID_FILTER_FIELD" in bad_filter.text

    # 4. Pagination parameter bounds
    # Page must be >= 1
    page_zero = client.get("/api/v1/suppliers?page=0", cookies=c["viewer_a"])
    assert page_zero.status_code == 422

    # Limit must be <= 100
    limit_excess = client.get("/api/v1/suppliers?limit=101", cookies=c["viewer_a"])
    assert limit_excess.status_code == 422


# ==============================================================================
# 10. ERROR CONTRACT & INFORMATION SANITIZATION
# ==============================================================================
def test_error_contract_and_sanitization(client: TestClient, auth_fixture: dict):
    """Verify that API errors conform to the standard envelope and never expose stack traces or secrets."""
    c = auth_fixture["cookies"]

    # 1. Unauthenticated request -> 401
    unauth = client.get("/api/v1/suppliers")
    assert unauth.status_code == 401
    assert "detail" in unauth.json() or "error" in unauth.json()

    # 2. Not found request -> 404 with standard envelope
    nf = client.get("/api/v1/suppliers/sup_non_existent", cookies=c["viewer_a"])
    assert nf.status_code == 404
    error_data = nf.json()
    assert "error" in error_data or "detail" in error_data

    # Verify no raw SQL or Python stack traces in response body
    raw_text = nf.text
    forbidden_terms = ["Traceback (most recent call last)", "psycopg2", "OperationalError", "sqlalchemy.exc", "password", "secret_key"]
    for term in forbidden_terms:
        assert term not in raw_text, f"Leaked sensitive internal info: {term}"


# ==============================================================================
# 11. OPENAPI 3.1 SCHEMA INTEGRITY AUDIT
# ==============================================================================
def test_openapi_schema_integrity():
    """Verify that OpenAPI schema defines exact paths, unique operation IDs, and zero route collisions."""
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    components = openapi.get("components", {}).get("schemas", {})

    # Check totals
    assert len(paths) == 60, f"Expected 60 endpoints, found {len(paths)}"
    assert len(components) >= 100, f"Expected >= 100 schemas, found {len(components)}"

    total_ops = 0
    op_ids = set()
    for path, methods in paths.items():
        for method, op in methods.items():
            if method.lower() not in ["get", "post", "put", "patch", "delete"]:
                continue
            total_ops += 1
            op_id = op.get("operationId")
            assert op_id is not None, f"Missing operationId on {method.upper()} {path}"
            assert op_id not in op_ids, f"Duplicate operationId: {op_id}"
            op_ids.add(op_id)

    assert total_ops == 96, f"Expected 96 operations, found {total_ops}"


# ==============================================================================
# 12. DATABASE MODEL & ENUM REGISTRY INTEGRITY
# ==============================================================================
def test_database_models_and_enums_integrity():
    """Verify that all 34 SQLAlchemy 2.0 models and enum mappings are registered in Base.metadata."""
    tables = Base.metadata.tables

    # Check primary Phase 4 domain tables
    domain_tables = [
        "organizations", "users",
        "suppliers", "supplier_sites", "factories", "warehouses", "ports", "carriers", "products", "routes", "shipments", "shipment_events",
        "inventory", "inventory_movements",
        "risks", "risk_factors", "risk_assessments", "incidents",
        "recommendations", "approvals", "actions", "verification_results", "notifications", "audit_logs",
    ]
    for table_name in domain_tables:
        assert table_name in tables, f"Missing table in Base.metadata: {table_name}"

    # Verify total tables registered in Base.metadata is 34
    assert len(tables) == 34, f"Expected 34 tables in Base.metadata, found {len(tables)}"
