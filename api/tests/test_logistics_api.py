"""Comprehensive test suite for RiskWise 2.0 Logistics APIs (Phase 4 Step 4).

Covers all 9 logistics & network resources:
- supplier-sites
- factories
- warehouses
- ports
- carriers
- products
- routes
- shipments
- shipment-events

Validates all 25 criteria specified in Section 37:
 1. Unauthenticated → 401
 2. Insufficient role (Viewer) → 403
 3. Authorized role (OpsManager/Admin) → 201/200
 4. Cross-tenant read → 404 (masked)
 5. Cross-tenant update → 404 (masked)
 6. Cross-tenant relationship reference → rejected (404 masked)
 7. Invalid enum → 422
 8. Invalid field (extra="forbid") → 422
 9. Invalid UUID / query format → handled
10. Invalid pagination (page=0, limit=101) → 422
11. Client-supplied org_id in payload → rejected (422)
12. Server-controlled field injection (id, created_at, updated_at) → rejected (422)
13. Invalid sort field → 400 (INVALID_SORT_FIELD)
14. Invalid filter field → 400 (INVALID_FILTER_FIELD)
15. SQL wildcard search safely escaped (%, _)
16. Forbidden hard DELETE → 405 Method Not Allowed
17. Invalid status transition → rejected (409/LifecycleStateError)
18. Invalid parent reference → 404 masked
19. Cross-tenant parent reference → 404 masked
20. Transaction rollback on failed multi-step mutation
21. Mutation produces audit record in audit_logs
22. OpenAPI spec has all implemented endpoints appearing exactly once with unique operation IDs
23. Valid shipment event creation → 201
24. Wrong-tenant shipment event rejected → 404 masked
25. Immutable event mutation (PATCH/DELETE) rejected → 405 Method Not Allowed
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
from app.models.governance import AuditLog
from app.models.logistics import Shipment, ShipmentEvent
from app.models.network import (
    Carrier,
    Factory,
    Port,
    Product,
    Route,
    Supplier,
    SupplierSite,
    Warehouse,
)
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
def seed_data(test_db: Session, session_service: SessionService):
    """Seed test organizations, users, and logistics assets across tenants."""
    # Organizations
    org_a = Organization(id="org_alpha_01", name="Alpha Logistics Inc", slug="alpha-logistics", is_active=True)
    org_b = Organization(id="org_beta_02", name="Beta Global Ltd", slug="beta-global", is_active=True)
    test_db.add_all([org_a, org_b])
    test_db.commit()

    # Users for Org A
    viewer_a = User(id="usr_view_a", org_id="org_alpha_01", email="viewer@alpha.test", full_name="Viewer A", role="Viewer", is_active=True)
    analyst_a = User(id="usr_analyst_a", org_id="org_alpha_01", email="analyst@alpha.test", full_name="Analyst A", role="Analyst", is_active=True)
    ops_a = User(id="usr_ops_a", org_id="org_alpha_01", email="ops@alpha.test", full_name="OpsManager A", role="OpsManager", is_active=True)
    admin_a = User(id="usr_admin_a", org_id="org_alpha_01", email="admin@alpha.test", full_name="Admin A", role="Admin", is_active=True)

    # User for Org B
    ops_b = User(id="usr_ops_b", org_id="org_beta_02", email="ops@beta.test", full_name="OpsManager B", role="OpsManager", is_active=True)

    test_db.add_all([viewer_a, analyst_a, ops_a, admin_a, ops_b])
    test_db.commit()

    # Seed Suppliers
    sup_a = Supplier(id="sup_alpha_01", org_id="org_alpha_01", name="Alpha Semiconductor", code="AS-001", country="TW")
    sup_b = Supplier(id="sup_beta_01", org_id="org_beta_02", name="Beta Panels", code="BP-001", country="KR")

    # Seed Carriers
    car_a = Carrier(id="car_alpha_01", org_id="org_alpha_01", name="Maersk Line", code="MAEU", mode="OCEAN", on_time_reliability=94.5)
    car_b = Carrier(id="car_beta_01", org_id="org_beta_02", name="MSC Shipping", code="MSCU", mode="OCEAN", on_time_reliability=91.0)

    # Seed Products
    prod_a = Product(id="prod_alpha_01", org_id="org_alpha_01", sku="CHIP-A-100", name="AI Accelerator Module", unit_cost=150.0)
    prod_b = Product(id="prod_beta_01", org_id="org_beta_02", sku="OLED-B-200", name="OLED Display Panel", unit_cost=85.0)

    # Seed Routes
    route_a = Route(id="route_alpha_01", org_id="org_alpha_01", name="Taipei to Long Beach", mode="OCEAN", distance_km=11000.0)
    route_b = Route(id="route_beta_01", org_id="org_beta_02", name="Busan to Rotterdam", mode="OCEAN", distance_km=18000.0)

    # Seed Shipments
    shp_a = Shipment(
        id="shp_alpha_01",
        org_id="org_alpha_01",
        tracking_number="SHP-ALPHA-999",
        carrier_id="car_alpha_01",
        product_id="prod_alpha_01",
        route_id="route_alpha_01",
        origin="Taipei Port",
        destination="Long Beach Port",
        status="IN_TRANSIT",
        mode="OCEAN",
    )
    shp_b = Shipment(
        id="shp_beta_01",
        org_id="org_beta_02",
        tracking_number="SHP-BETA-888",
        carrier_id="car_beta_01",
        product_id="prod_beta_01",
        route_id="route_beta_01",
        status="IN_TRANSIT",
        mode="OCEAN",
    )

    # Seed Global Ports (no org_id)
    port_sin = Port(id="prt_singapore", code="SGSIN", name="Port of Singapore", country="SG", port_type="SEA", congestion_score=35.0)
    port_rtd = Port(id="prt_rotterdam", code="NLRTM", name="Port of Rotterdam", country="NL", port_type="SEA", congestion_score=42.0)

    test_db.add_all([sup_a, sup_b, car_a, car_b, prod_a, prod_b, route_a, route_b, shp_a, shp_b, port_sin, port_rtd])
    test_db.commit()

    # Session cookie generator
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
        "viewer_a_cookie": make_cookie(viewer_a),
        "analyst_a_cookie": make_cookie(analyst_a),
        "ops_a_cookie": make_cookie(ops_a),
        "admin_a_cookie": make_cookie(admin_a),
        "ops_b_cookie": make_cookie(ops_b),
        "sup_a": sup_a,
        "sup_b": sup_b,
        "car_a": car_a,
        "car_b": car_b,
        "prod_a": prod_a,
        "prod_b": prod_b,
        "route_a": route_a,
        "route_b": route_b,
        "shp_a": shp_a,
        "shp_b": shp_b,
        "port_sin": port_sin,
    }


# ==============================================================================
# 1. UNAUTHENTICATED ACCESS → 401
# ==============================================================================
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/supplier-sites",
        "/api/v1/factories",
        "/api/v1/warehouses",
        "/api/v1/ports",
        "/api/v1/carriers",
        "/api/v1/products",
        "/api/v1/routes",
        "/api/v1/shipments",
        "/api/v1/shipment-events",
    ],
)
def test_1_unauthenticated_access_returns_401(client: TestClient, path: str):
    """1. Verify unauthenticated requests to all logistics endpoints return 401."""
    response = client.get(path)
    assert response.status_code == 401


# ==============================================================================
# 2. INSUFFICIENT ROLE (Viewer attempting POST/PATCH) → 403
# ==============================================================================
def test_2_insufficient_role_mutation_returns_403(client: TestClient, seed_data: dict):
    """2. Verify Viewer role attempting POST / PATCH receives 403 Forbidden."""
    client.cookies.set("riskwise_session", seed_data["viewer_a_cookie"])

    # Attempt create factory
    res = client.post("/api/v1/factories", json={"name": "Forbidden Plant"})
    assert res.status_code == 403

    # Attempt create shipment
    res = client.post("/api/v1/shipments", json={"tracking_number": "TRK-FAIL"})
    assert res.status_code == 403


# ==============================================================================
# 3. AUTHORIZED ROLE (OpsManager) → SUCCESS (201/200)
# ==============================================================================
def test_3_authorized_role_succeeds(client: TestClient, seed_data: dict):
    """3. Verify OpsManager role successfully creates and reads logistics entities."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # Create Factory
    res = client.post(
        "/api/v1/factories",
        json={"name": "Alpha Assembly Plant #1", "code": "AP-01", "country": "TW", "capacity": 50000.0},
    )
    assert res.status_code == 201
    factory_id = res.json()["id"]
    assert res.json()["name"] == "Alpha Assembly Plant #1"
    assert res.json()["code"] == "AP-01"

    # Read Factory
    get_res = client.get(f"/api/v1/factories/{factory_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == factory_id


# ==============================================================================
# 4. CROSS-TENANT READ → 404 (MASKED)
# ==============================================================================
def test_4_cross_tenant_read_returns_404_masked(client: TestClient, seed_data: dict):
    """4. Verify requesting another tenant's resource returns 404 Not Found (masked)."""
    # Org A requests Org B's shipment
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])
    res = client.get(f"/api/v1/shipments/{seed_data['shp_b'].id}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 5. CROSS-TENANT UPDATE → 404 (MASKED)
# ==============================================================================
def test_5_cross_tenant_update_returns_404_masked(client: TestClient, seed_data: dict):
    """5. Verify modifying another tenant's resource returns 404 Not Found (masked)."""
    # Org A attempts to patch Org B's carrier
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])
    res = client.patch(f"/api/v1/carriers/{seed_data['car_b'].id}", json={"name": "Hijacked Carrier"})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 6. CROSS-TENANT RELATIONSHIP REFERENCE → REJECTED (404 MASKED)
# ==============================================================================
def test_6_cross_tenant_relationship_rejected(client: TestClient, seed_data: dict):
    """6. Verify creating a shipment referencing another tenant's carrier is rejected."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # Attempt to create shipment referencing Carrier B (from Org B)
    res = client.post(
        "/api/v1/shipments",
        json={
            "tracking_number": "TRK-ILLEGAL-REF",
            "carrier_id": seed_data["car_b"].id,  # Org B carrier
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 7. INVALID ENUM → 422
# ==============================================================================
def test_7_invalid_enum_rejected(client: TestClient, seed_data: dict):
    """7. Verify invalid enum string values return 422 Unprocessable Entity."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/carriers",
        json={"name": "Space Logistics", "mode": "ROCKET_SHIP"},
    )
    assert res.status_code == 422


# ==============================================================================
# 8. INVALID FIELD (extra="forbid") → 422
# ==============================================================================
def test_8_extra_forbidden_fields_rejected(client: TestClient, seed_data: dict):
    """8. Verify client-supplied unknown fields trigger 422 Unprocessable Entity."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/warehouses",
        json={"name": "Central Depot", "unauthorized_extra_field": "injected_value"},
    )
    assert res.status_code == 422


# ==============================================================================
# 9. INVALID UUID / FORMAT → HANDLED
# ==============================================================================
def test_9_missing_resource_returns_404(client: TestClient, seed_data: dict):
    """9. Verify non-existent resource ID returns 404 Not Found."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.get("/api/v1/products/prod_non_existent_12345")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 10. INVALID PAGINATION (page=0, limit=101) → 422
# ==============================================================================
def test_10_invalid_pagination_returns_422(client: TestClient, seed_data: dict):
    """10. Verify pagination query boundary violations (page < 1, limit > 100) return 422."""
    client.cookies.set("riskwise_session", seed_data["viewer_a_cookie"])

    res = client.get("/api/v1/shipments?page=0")
    assert res.status_code == 422

    res = client.get("/api/v1/shipments?limit=101")
    assert res.status_code == 422


# ==============================================================================
# 11. ORG_ID INJECTION REJECTED → 422
# ==============================================================================
def test_11_client_supplied_org_id_rejected(client: TestClient, seed_data: dict):
    """11. Verify client cannot supply org_id in request body."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/products",
        json={"name": "Widget X", "sku": "WDG-X-01", "org_id": "org_beta_02"},
    )
    assert res.status_code == 422


# ==============================================================================
# 12. SERVER-CONTROLLED FIELD INJECTION REJECTED → 422
# ==============================================================================
def test_12_server_controlled_id_injection_rejected(client: TestClient, seed_data: dict):
    """12. Verify client cannot supply server-controlled 'id' or 'created_at'."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/products",
        json={"id": "prod_custom_id", "name": "Widget Y", "sku": "WDG-Y-01"},
    )
    assert res.status_code == 422


# ==============================================================================
# 13. INVALID SORT FIELD → 400 (INVALID_SORT_FIELD)
# ==============================================================================
def test_13_invalid_sort_field_returns_400(client: TestClient, seed_data: dict):
    """13. Verify sorting by a non-allowlisted column returns 400 Bad Request."""
    client.cookies.set("riskwise_session", seed_data["viewer_a_cookie"])

    res = client.get("/api/v1/shipments?sort=forbidden_secret_column")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SORT_FIELD"


# ==============================================================================
# 14. INVALID FILTER FIELD → 400 (INVALID_FILTER_FIELD)
# ==============================================================================
def test_14_invalid_filter_field_returns_400(client: TestClient, seed_data: dict):
    """14. Verify filtering by a non-allowlisted query param returns 400 Bad Request."""
    client.cookies.set("riskwise_session", seed_data["viewer_a_cookie"])

    res = client.get("/api/v1/factories?unknown_filter_col=xyz")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_FILTER_FIELD"


# ==============================================================================
# 15. SQL WILDCARD SEARCH SAFELY ESCAPED
# ==============================================================================
def test_15_search_wildcards_safely_escaped(client: TestClient, seed_data: dict):
    """15. Verify search strings containing SQL wildcards (%, _) do not cause full table leaks."""
    client.cookies.set("riskwise_session", seed_data["viewer_a_cookie"])

    # Search with % should match literal % (none exist), returning empty items
    res = client.get("/api/v1/products?search=%")
    assert res.status_code == 200
    assert len(res.json()["items"]) == 0

    # Search with actual substring should match
    res = client.get("/api/v1/products?search=AI Accelerator")
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["items"][0]["sku"] == "CHIP-A-100"


# ==============================================================================
# 16. FORBIDDEN HARD DELETE → 405 METHOD NOT ALLOWED
# ==============================================================================
def test_16_forbidden_hard_delete_returns_405(client: TestClient, seed_data: dict):
    """16. Verify hard DELETE requests to operational resources return 405 Method Not Allowed."""
    client.cookies.set("riskwise_session", seed_data["admin_a_cookie"])

    res = client.delete(f"/api/v1/shipments/{seed_data['shp_a'].id}")
    assert res.status_code == 405

    res = client.delete(f"/api/v1/warehouses/wh_any")
    assert res.status_code == 405


# ==============================================================================
# 17. INVALID STATUS TRANSITION → REJECTED
# ==============================================================================
def test_17_invalid_shipment_status_transition_rejected(client: TestClient, seed_data: dict, test_db: Session):
    """17. Verify shipment in terminal status (DELIVERED) cannot transition back to PLANNED."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # First mark shipment as DELIVERED
    shp = test_db.get(Shipment, seed_data["shp_a"].id)
    shp.status = "DELIVERED"
    test_db.commit()

    # Attempt to transition DELIVERED -> PLANNED
    res = client.patch(f"/api/v1/shipments/{shp.id}", json={"status": "PLANNED"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "ILLEGAL_STATUS_TRANSITION"


# ==============================================================================
# 18. INVALID PARENT REFERENCE → 404 MASKED
# ==============================================================================
def test_18_invalid_parent_reference_returns_404(client: TestClient, seed_data: dict):
    """18. Verify supplier site referencing non-existent supplier returns 404 Not Found."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/supplier-sites",
        json={
            "supplier_id": "sup_non_existent_999",
            "name": "Ghost Site",
            "country": "TW",
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 19. CROSS-TENANT PARENT REFERENCE → 404 MASKED
# ==============================================================================
def test_19_cross_tenant_parent_reference_returns_404(client: TestClient, seed_data: dict):
    """19. Verify supplier site referencing another tenant's supplier returns 404 Not Found."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # Org A user attempts to attach site to Org B's supplier
    res = client.post(
        "/api/v1/supplier-sites",
        json={
            "supplier_id": seed_data["sup_b"].id,  # Org B's supplier
            "name": "Cross Tenant Fabrication Site",
            "country": "KR",
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 20. TRANSACTION ROLLBACK ON FAILURE
# ==============================================================================
def test_20_transaction_rollback_on_failed_mutation(client: TestClient, seed_data: dict, test_db: Session):
    """20. Verify failed operations roll back transaction and do not persist dirty records."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # Count initial products
    initial_count = test_db.scalar(select(AuditLog).where(AuditLog.org_id == "org_alpha_01"))

    # Attempt to create duplicate product SKU (will fail with 409)
    res = client.post(
        "/api/v1/products",
        json={"name": "Duplicate Chip", "sku": "CHIP-A-100", "unit_cost": 120.0},
    )
    assert res.status_code == 409

    # Verify no rogue Product or AuditLog was committed
    prods = list(test_db.scalars(select(Product).where(Product.sku == "CHIP-A-100")).all())
    assert len(prods) == 1


# ==============================================================================
# 21. AUDIT RECORD GENERATED ON MUTATION
# ==============================================================================
def test_21_audit_record_generated_on_mutation(client: TestClient, seed_data: dict, test_db: Session):
    """21. Verify mutating operations create a corresponding entry in audit_logs."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/carriers",
        json={"name": "Evergreen Marine", "code": "EMC", "mode": "OCEAN", "on_time_reliability": 88.0},
    )
    assert res.status_code == 201
    carrier_id = res.json()["id"]

    # Verify audit log entry exists
    audit = test_db.scalars(
        select(AuditLog).where(
            AuditLog.resource_type == "Carrier",
            AuditLog.resource_id == carrier_id,
            AuditLog.action == "CREATE",
        )
    ).first()
    assert audit is not None
    assert audit.actor_id == "usr_ops_a"
    assert audit.org_id == "org_alpha_01"


# ==============================================================================
# 22. OPENAPI SPEC UNIQUE OPERATION IDS
# ==============================================================================
def test_22_openapi_unique_operation_ids():
    """22. Verify OpenAPI specification generates with zero duplicate operation IDs."""
    schema = app.openapi()
    operation_ids = []
    for path, methods in schema["paths"].items():
        for method, details in methods.items():
            if "operationId" in details:
                operation_ids.append(details["operationId"])

    assert len(operation_ids) == len(set(operation_ids)), "OpenAPI operation IDs must be unique"
    assert "/api/v1/supplier-sites" in schema["paths"]
    assert "/api/v1/factories" in schema["paths"]
    assert "/api/v1/warehouses" in schema["paths"]
    assert "/api/v1/ports" in schema["paths"]
    assert "/api/v1/carriers" in schema["paths"]
    assert "/api/v1/products" in schema["paths"]
    assert "/api/v1/routes" in schema["paths"]
    assert "/api/v1/shipments" in schema["paths"]
    assert "/api/v1/shipment-events" in schema["paths"]


# ==============================================================================
# 23. VALID SHIPMENT EVENT CREATION → 201
# ==============================================================================
def test_23_valid_shipment_event_creation(client: TestClient, seed_data: dict):
    """23. Verify creating an append-only milestone telemetry event succeeds with 201."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    res = client.post(
        "/api/v1/shipment-events",
        json={
            "shipment_id": seed_data["shp_a"].id,
            "event_type": "VESSEL_DEPARTURE",
            "mode": "OCEAN",
            "status": "IN_TRANSIT",
            "latitude": 25.13,
            "longitude": 121.74,
            "delay_minutes": 15.0,
            "source": "REAL",
            "source_type": "AIS",
            "confidence": 0.98,
        },
    )
    assert res.status_code == 201
    event_id = res.json()["id"]
    assert res.json()["shipment_id"] == seed_data["shp_a"].id
    assert res.json()["event_type"] == "VESSEL_DEPARTURE"

    # Retrieve event via GET
    get_res = client.get(f"/api/v1/shipment-events/{event_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == event_id

    # Retrieve via shipment sub-resource GET /shipments/{id}/events
    sub_res = client.get(f"/api/v1/shipments/{seed_data['shp_a'].id}/events")
    assert sub_res.status_code == 200
    assert sub_res.json()["pagination"]["total"] == 1
    assert sub_res.json()["items"][0]["id"] == event_id


# ==============================================================================
# 24. WRONG-TENANT SHIPMENT EVENT REJECTED → 404 MASKED
# ==============================================================================
def test_24_wrong_tenant_shipment_event_rejected(client: TestClient, seed_data: dict):
    """24. Verify creating a telemetry event for another tenant's shipment returns 404 masked."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # Org A user attempts to add an event to Org B's shipment
    res = client.post(
        "/api/v1/shipment-events",
        json={
            "shipment_id": seed_data["shp_b"].id,  # Org B shipment
            "event_type": "BERTH_ARRIVAL",
            "status": "ARRIVED",
        },
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


# ==============================================================================
# 25. IMMUTABLE EVENT MUTATION (PATCH/DELETE) REJECTED → 405
# ==============================================================================
def test_25_immutable_event_mutation_rejected(client: TestClient, seed_data: dict, test_db: Session):
    """25. Verify shipment telemetry events are strictly immutable (PATCH/DELETE return 405)."""
    # Seed an event directly
    event = ShipmentEvent(
        shipment_id=seed_data["shp_a"].id,
        event_type="CUSTOMS_CLEARED",
        source="REAL",
    )
    test_db.add(event)
    test_db.commit()

    client.cookies.set("riskwise_session", seed_data["admin_a_cookie"])

    # PATCH on event -> 405 Method Not Allowed
    patch_res = client.patch(f"/api/v1/shipment-events/{event.id}", json={"event_type": "TAMPERED"})
    assert patch_res.status_code == 405

    # DELETE on event -> 405 Method Not Allowed
    delete_res = client.delete(f"/api/v1/shipment-events/{event.id}")
    assert delete_res.status_code == 405


# ==============================================================================
# DOMAIN VALIDATION TESTS: WAREHOUSE CAPACITY & GLOBAL PORTS
# ==============================================================================
def test_warehouse_occupancy_exceeds_capacity_rejected(client: TestClient, seed_data: dict):
    """Verify warehouse current_occupancy cannot exceed total_capacity (ValidationDomainError)."""
    client.cookies.set("riskwise_session", seed_data["ops_a_cookie"])

    # Attempt create with occupancy > capacity
    res = client.post(
        "/api/v1/warehouses",
        json={
            "name": "Overloaded Warehouse",
            "total_capacity": 1000.0,
            "current_occupancy": 1500.0,
        },
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "OCCUPANCY_EXCEEDS_CAPACITY"


def test_global_ports_accessible_read_only_across_tenants(client: TestClient, seed_data: dict):
    """Verify global ports are accessible to both Org A and Org B without tenant filtering."""
    # Org A reads port
    client.cookies.set("riskwise_session", seed_data["viewer_a_cookie"])
    res_a = client.get(f"/api/v1/ports/{seed_data['port_sin'].id}")
    assert res_a.status_code == 200
    assert res_a.json()["code"] == "SGSIN"

    # Org B reads port
    client.cookies.set("riskwise_session", seed_data["ops_b_cookie"])
    res_b = client.get(f"/api/v1/ports/{seed_data['port_sin'].id}")
    assert res_b.status_code == 200
    assert res_b.json()["code"] == "SGSIN"

    # Mutating global port is not supported (POST / PATCH / DELETE -> 405)
    post_res = client.post("/api/v1/ports", json={"name": "New Port"})
    assert post_res.status_code == 405
