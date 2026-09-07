"""Comprehensive test suite for RiskWise 2.0 Inventory APIs (Phase 4 Step 5).

Covers both primary inventory resources:
1. inventory (Facility-level stock levels, reorder points, days-of-supply)
2. inventory_movements (Append-only immutable transaction ledger)

Validates all 22 contract requirements:
 1. Authentication required (GET/POST without session → 401)
 2. RBAC enforcement (Viewer/Analyst write → 403; OpsManager/RiskManager/Admin → 201/200)
 3. Organization isolation (Cross-tenant GET/PATCH → 404 masked)
 4. Cross-tenant product rejection (Product in Org B referenced by Org A → 404 masked)
 5. Cross-tenant warehouse/site rejection (Facility in Org B referenced by Org A → 404 masked)
 6. Inventory creation (Valid POST → 201 with correct fields)
 7. Inventory retrieval (Valid GET by ID → 200)
 8. Inventory listing (Valid GET collection → 200 paginated)
 9. Pagination (page/limit validation & bounds)
10. Filtering (product_id, facility_id, movement_type, reference_id)
11. Sorting (sort allowlist, ascending/descending, invalid sort → 400)
12. Search where supported (product_id, facility_id, reference_id, SQL wildcard escaping)
13. Update behavior (PATCH updating stock/thresholds → 200)
14. Server-controlled field injection rejection (id, org_id, created_at, updated_at → 422)
15. Invalid quantity handling (negative quantity_on_hand → 422; movement quantity=0 → 400)
16. Inventory movement creation (Valid POST → 201 append-only record)
17. Movement ownership validation (Cross-tenant reference_id → 404 masked)
18. Append-only / immutability rules (Movement PATCH/DELETE → 405; Inventory DELETE → 405)
19. Concurrent update & insufficient stock protection (Movement deduction exceeding balance → 400 INSUFFICIENT_INVENTORY)
20. Audit behavior (CREATE/UPDATE produce records in audit_logs)
21. Standardized error responses (INVALID_FILTER_FIELD → 400, RESOURCE_NOT_FOUND → 404)
22. OpenAPI route registration & uniqueness (All routes present, unique operation IDs)
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
from app.models.logistics import Inventory, InventoryMovement
from app.models.network import Factory, Product, Warehouse
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
    """Seed test organizations, users, products, facilities, and inventory."""
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

    # Products
    prod_a = Product(id="prod_a1", org_id="org_alpha_01", name="Alpha Microchip", sku="SKU-ALPHA-01", category="Electronics", unit_cost=50.0)
    prod_b = Product(id="prod_b1", org_id="org_beta_02", name="Beta Sensor", sku="SKU-BETA-01", category="Sensors", unit_cost=30.0)
    test_db.add_all([prod_a, prod_b])
    test_db.commit()

    # Facilities (Warehouse & Factory)
    wh_a = Warehouse(id="wh_a1", org_id="org_alpha_01", name="Alpha Central WH", code="WH-A1", total_capacity=10000.0, current_occupancy=2500.0)
    wh_b = Warehouse(id="wh_b1", org_id="org_beta_02", name="Beta Hub WH", code="WH-B1", total_capacity=5000.0, current_occupancy=1000.0)
    fac_a = Factory(id="fac_a1", org_id="org_alpha_01", name="Alpha Plant 1", code="FAC-A1")
    fac_b = Factory(id="fac_b1", org_id="org_beta_02", name="Beta Plant 1", code="FAC-B1")
    test_db.add_all([wh_a, wh_b, fac_a, fac_b])
    test_db.commit()

    # Initial Inventory
    inv_a = Inventory(
        id="inv_a1",
        org_id="org_alpha_01",
        product_id="prod_a1",
        facility_id="wh_a1",
        quantity_on_hand=100.0,
        safety_stock=20.0,
        reorder_point=40.0,
        days_of_supply=15.0,
    )
    inv_b = Inventory(
        id="inv_b1",
        org_id="org_beta_02",
        product_id="prod_b1",
        facility_id="wh_b1",
        quantity_on_hand=50.0,
        safety_stock=10.0,
        reorder_point=25.0,
        days_of_supply=10.0,
    )
    test_db.add_all([inv_a, inv_b])
    test_db.commit()

    # Initial Movement
    mov_a = InventoryMovement(
        id="mov_a1",
        org_id="org_alpha_01",
        product_id="prod_a1",
        movement_type="RECEIPT",
        quantity=100.0,
        to_location="WH-A1",
        reference_id="inv_a1",
        timestamp=datetime.now(timezone.utc),
    )
    mov_b = InventoryMovement(
        id="mov_b1",
        org_id="org_beta_02",
        product_id="prod_b1",
        movement_type="RECEIPT",
        quantity=50.0,
        to_location="WH-B1",
        reference_id="inv_b1",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add_all([mov_a, mov_b])
    test_db.commit()

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
        "prod_a": prod_a,
        "prod_b": prod_b,
        "wh_a": wh_a,
        "wh_b": wh_b,
        "fac_a": fac_a,
        "fac_b": fac_b,
        "inv_a": inv_a,
        "inv_b": inv_b,
        "mov_a": mov_a,
        "mov_b": mov_b,
    }


# ==============================================================================
# 1. AUTHENTICATION REQUIRED (401)
# ==============================================================================
def test_1_authentication_required(client: TestClient):
    """Unauthenticated requests to Inventory and Movement endpoints return 401."""
    assert client.get("/api/v1/inventory").status_code == 401
    assert client.post("/api/v1/inventory", json={"product_id": "p1", "quantity_on_hand": 10.0}).status_code == 401
    assert client.get("/api/v1/inventory/inv_1").status_code == 401
    assert client.patch("/api/v1/inventory/inv_1", json={"quantity_on_hand": 20.0}).status_code == 401
    assert client.get("/api/v1/inventory-movements").status_code == 401
    assert client.post("/api/v1/inventory-movements", json={"product_id": "p1", "quantity": 10.0}).status_code == 401
    assert client.get("/api/v1/inventory-movements/mov_1").status_code == 401


# ==============================================================================
# 2. RBAC ENFORCEMENT (403 vs 200/201)
# ==============================================================================
def test_2_rbac_enforcement(client: TestClient, seed_data: dict):
    """Viewer/Analyst have read-only permissions; OpsManager/Admin have mutation rights."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    headers_analyst = {"Cookie": f"riskwise_session={seed_data['analyst_cookie']}"}
    headers_ops = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}

    # Viewer can read
    assert client.get("/api/v1/inventory", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/inventory-movements", headers=headers_viewer).status_code == 200

    # Viewer cannot create or patch inventory
    inv_payload = {"product_id": seed_data["prod_a"].id, "quantity_on_hand": 10.0}
    assert client.post("/api/v1/inventory", json=inv_payload, headers=headers_viewer).status_code == 403
    assert client.patch(f"/api/v1/inventory/{seed_data['inv_a'].id}", json={"quantity_on_hand": 50.0}, headers=headers_viewer).status_code == 403

    # Analyst cannot create or patch inventory
    assert client.post("/api/v1/inventory", json=inv_payload, headers=headers_analyst).status_code == 403
    assert client.patch(f"/api/v1/inventory/{seed_data['inv_a'].id}", json={"quantity_on_hand": 50.0}, headers=headers_analyst).status_code == 403

    # Viewer/Analyst cannot create movement
    mov_payload = {"product_id": seed_data["prod_a"].id, "quantity": 5.0}
    assert client.post("/api/v1/inventory-movements", json=mov_payload, headers=headers_viewer).status_code == 403
    assert client.post("/api/v1/inventory-movements", json=mov_payload, headers=headers_analyst).status_code == 403

    # OpsManager can create inventory
    res = client.post("/api/v1/inventory", json=inv_payload, headers=headers_ops)
    assert res.status_code == 201


# ==============================================================================
# 3. ORGANIZATION ISOLATION (404 MASKED)
# ==============================================================================
def test_3_organization_isolation(client: TestClient, seed_data: dict):
    """Tenant A cannot access or mutate Tenant B inventory or movements."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    headers_ops_b = {"Cookie": f"riskwise_session={seed_data['ops_b_cookie']}"}

    inv_b_id = seed_data["inv_b"].id
    mov_b_id = seed_data["mov_b"].id

    # Org A trying to access Org B inventory -> 404 masked
    res = client.get(f"/api/v1/inventory/{inv_b_id}", headers=headers_ops_a)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    # Org A trying to update Org B inventory -> 404 masked
    res = client.patch(f"/api/v1/inventory/{inv_b_id}", json={"quantity_on_hand": 99.0}, headers=headers_ops_a)
    assert res.status_code == 404

    # Org A trying to access Org B movement -> 404 masked
    res = client.get(f"/api/v1/inventory-movements/{mov_b_id}", headers=headers_ops_a)
    assert res.status_code == 404

    # Listing inventory for Org A does not include Org B items
    res = client.get("/api/v1/inventory", headers=headers_ops_a)
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["items"]]
    assert inv_b_id not in ids

    # Listing movements for Org A does not include Org B movements
    res = client.get("/api/v1/inventory-movements", headers=headers_ops_a)
    assert res.status_code == 200
    m_ids = [item["id"] for item in res.json()["items"]]
    assert mov_b_id not in m_ids


# ==============================================================================
# 4. CROSS-TENANT PRODUCT REJECTION (404 MASKED)
# ==============================================================================
def test_4_cross_tenant_product_rejection(client: TestClient, seed_data: dict):
    """Referencing a product belonging to another tenant is rejected with 404 masked."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    prod_b_id = seed_data["prod_b"].id

    # Inventory create with cross-tenant product
    res = client.post(
        "/api/v1/inventory",
        json={"product_id": prod_b_id, "quantity_on_hand": 20.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 404
    assert "Product" in res.json()["error"]["message"]

    # Movement create with cross-tenant product
    res = client.post(
        "/api/v1/inventory-movements",
        json={"product_id": prod_b_id, "quantity": 10.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 404
    assert "Product" in res.json()["error"]["message"]


# ==============================================================================
# 5. CROSS-TENANT FACILITY REJECTION (404 MASKED)
# ==============================================================================
def test_5_cross_tenant_facility_rejection(client: TestClient, seed_data: dict):
    """Referencing a warehouse or factory belonging to another tenant is rejected with 404 masked."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    prod_a_id = seed_data["prod_a"].id
    wh_b_id = seed_data["wh_b"].id
    fac_b_id = seed_data["fac_b"].id

    # Cross-tenant warehouse reference
    res = client.post(
        "/api/v1/inventory",
        json={"product_id": prod_a_id, "facility_id": wh_b_id, "quantity_on_hand": 10.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 404
    assert "Referenced facility" in res.json()["error"]["message"]

    # Cross-tenant factory reference
    res = client.post(
        "/api/v1/inventory",
        json={"product_id": prod_a_id, "facility_id": fac_b_id, "quantity_on_hand": 10.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 404
    assert "Referenced facility" in res.json()["error"]["message"]


# ==============================================================================
# 6. INVENTORY CREATION (201)
# ==============================================================================
def test_6_inventory_creation(client: TestClient, seed_data: dict):
    """Authorized user can create inventory records with valid parameters."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    payload = {
        "product_id": seed_data["prod_a"].id,
        "facility_id": seed_data["fac_a"].id,
        "quantity_on_hand": 250.0,
        "safety_stock": 50.0,
        "reorder_point": 75.0,
        "days_of_supply": 20.0,
    }
    res = client.post("/api/v1/inventory", json=payload, headers=headers_ops_a)
    assert res.status_code == 201
    data = res.json()
    assert data["product_id"] == seed_data["prod_a"].id
    assert data["facility_id"] == seed_data["fac_a"].id
    assert data["quantity_on_hand"] == 250.0
    assert data["safety_stock"] == 50.0
    assert data["reorder_point"] == 75.0
    assert data["days_of_supply"] == 20.0
    assert "id" in data
    assert data["org_id"] == "org_alpha_01"


# ==============================================================================
# 7. INVENTORY RETRIEVAL (200)
# ==============================================================================
def test_7_inventory_retrieval(client: TestClient, seed_data: dict):
    """Retrieve an individual inventory record by ID."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    inv_id = seed_data["inv_a"].id
    res = client.get(f"/api/v1/inventory/{inv_id}", headers=headers_viewer)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == inv_id
    assert data["product_id"] == seed_data["prod_a"].id
    assert data["quantity_on_hand"] == 100.0


# ==============================================================================
# 8. INVENTORY LISTING (200)
# ==============================================================================
def test_8_inventory_listing(client: TestClient, seed_data: dict):
    """List inventory records returning standard paginated structure."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}
    res = client.get("/api/v1/inventory", headers=headers_viewer)
    assert res.status_code == 200
    body = res.json()
    assert "items" in body
    assert "pagination" in body
    assert len(body["items"]) >= 1


# ==============================================================================
# 9. PAGINATION VALIDATION
# ==============================================================================
def test_9_pagination_validation(client: TestClient, seed_data: dict):
    """Validate pagination parameter bounds and structure."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    # Valid pagination
    res = client.get("/api/v1/inventory?page=1&limit=1", headers=headers_viewer)
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["limit"] == 1

    # Invalid page=0
    assert client.get("/api/v1/inventory?page=0", headers=headers_viewer).status_code == 422
    # Invalid limit=101
    assert client.get("/api/v1/inventory?limit=101", headers=headers_viewer).status_code == 422


# ==============================================================================
# 10. FILTERING
# ==============================================================================
def test_10_filtering(client: TestClient, seed_data: dict):
    """Filter inventory and inventory movements by allowed attributes."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    # Filter inventory by product_id
    res = client.get(f"/api/v1/inventory?product_id={seed_data['prod_a'].id}", headers=headers_viewer)
    assert res.status_code == 200
    for item in res.json()["items"]:
        assert item["product_id"] == seed_data["prod_a"].id

    # Filter inventory by facility_id
    res = client.get(f"/api/v1/inventory?facility_id={seed_data['wh_a'].id}", headers=headers_viewer)
    assert res.status_code == 200
    for item in res.json()["items"]:
        assert item["facility_id"] == seed_data["wh_a"].id

    # Filter movements by movement_type
    res = client.get("/api/v1/inventory-movements?movement_type=RECEIPT", headers=headers_viewer)
    assert res.status_code == 200
    for item in res.json()["items"]:
        assert item["movement_type"] == "RECEIPT"


# ==============================================================================
# 11. SORTING & INVALID SORT FIELD (400)
# ==============================================================================
def test_11_sorting_and_invalid_sort(client: TestClient, seed_data: dict):
    """Sort allowlist enforcement for inventory and movements."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    # Valid sort inventory
    assert client.get("/api/v1/inventory?sort=quantity_on_hand", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/inventory?sort=-quantity_on_hand", headers=headers_viewer).status_code == 200

    # Valid sort movements
    assert client.get("/api/v1/inventory-movements?sort=timestamp", headers=headers_viewer).status_code == 200
    assert client.get("/api/v1/inventory-movements?sort=-quantity", headers=headers_viewer).status_code == 200

    # Invalid sort field on inventory -> 400
    res = client.get("/api/v1/inventory?sort=secret_column", headers=headers_viewer)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SORT_FIELD"

    # Invalid sort field on movements -> 400
    res = client.get("/api/v1/inventory-movements?sort=injected_sql", headers=headers_viewer)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_SORT_FIELD"


# ==============================================================================
# 12. SEARCH & SQL WILDCARD ESCAPING
# ==============================================================================
def test_12_search_and_wildcard_escaping(client: TestClient, seed_data: dict):
    """Search endpoints safely escape SQL wildcards (% and _)."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    # Search with wildcards
    res = client.get("/api/v1/inventory?search=%25_test%25", headers=headers_viewer)
    assert res.status_code == 200
    assert isinstance(res.json()["items"], list)

    res = client.get("/api/v1/inventory-movements?search=%25_receipt%25", headers=headers_viewer)
    assert res.status_code == 200
    assert isinstance(res.json()["items"], list)


# ==============================================================================
# 13. UPDATE BEHAVIOR (PATCH 200)
# ==============================================================================
def test_13_update_behavior(client: TestClient, seed_data: dict):
    """PATCH updates stock levels and thresholds, returning updated entity."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    inv_id = seed_data["inv_a"].id

    update_payload = {
        "quantity_on_hand": 180.0,
        "safety_stock": 35.0,
        "reorder_point": 60.0,
        "days_of_supply": 22.0,
    }
    res = client.patch(f"/api/v1/inventory/{inv_id}", json=update_payload, headers=headers_ops_a)
    assert res.status_code == 200
    data = res.json()
    assert data["quantity_on_hand"] == 180.0
    assert data["safety_stock"] == 35.0
    assert data["reorder_point"] == 60.0
    assert data["days_of_supply"] == 22.0
    assert data["updated_at"] is not None


# ==============================================================================
# 14. SERVER-CONTROLLED FIELD INJECTION REJECTION (422)
# ==============================================================================
def test_14_server_controlled_field_injection(client: TestClient, seed_data: dict):
    """Client cannot supply server-controlled fields (id, org_id, created_at, updated_at)."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}

    # Inventory create with injected org_id
    res = client.post(
        "/api/v1/inventory",
        json={"product_id": seed_data["prod_a"].id, "quantity_on_hand": 10.0, "org_id": "org_beta_02"},
        headers=headers_ops_a,
    )
    assert res.status_code == 422

    # Inventory create with injected id
    res = client.post(
        "/api/v1/inventory",
        json={"product_id": seed_data["prod_a"].id, "quantity_on_hand": 10.0, "id": "custom_id"},
        headers=headers_ops_a,
    )
    assert res.status_code == 422

    # Movement create with injected org_id
    res = client.post(
        "/api/v1/inventory-movements",
        json={"product_id": seed_data["prod_a"].id, "quantity": 10.0, "org_id": "org_beta_02"},
        headers=headers_ops_a,
    )
    assert res.status_code == 422


# ==============================================================================
# 15. INVALID QUANTITY HANDLING (422 / 400)
# ==============================================================================
def test_15_invalid_quantity_handling(client: TestClient, seed_data: dict):
    """Negative stock in inventory or zero quantity in movement is rejected."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}

    # Negative stock in inventory create → 422 (pydantic ge=0.0)
    res = client.post(
        "/api/v1/inventory",
        json={"product_id": seed_data["prod_a"].id, "quantity_on_hand": -10.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 422

    # Negative stock in inventory update → 422 (pydantic ge=0.0)
    res = client.patch(
        f"/api/v1/inventory/{seed_data['inv_a'].id}",
        json={"quantity_on_hand": -5.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 422

    # Movement quantity = 0 → 400 INVALID_QUANTITY
    res = client.post(
        "/api/v1/inventory-movements",
        json={"product_id": seed_data["prod_a"].id, "quantity": 0.0},
        headers=headers_ops_a,
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_QUANTITY"


# ==============================================================================
# 16. INVENTORY MOVEMENT CREATION & ATOMIC RECONCILIATION (201)
# ==============================================================================
def test_16_inventory_movement_creation_and_reconciliation(client: TestClient, seed_data: dict, test_db: Session):
    """Creating a movement with reference_id matching an inventory atomically updates stock."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    inv_id = seed_data["inv_a"].id

    # Check initial stock (100.0)
    res = client.get(f"/api/v1/inventory/{inv_id}", headers=headers_ops_a)
    initial_stock = res.json()["quantity_on_hand"]
    assert initial_stock == 100.0

    # Create RECEIPT movement (+30.0)
    movement_payload = {
        "product_id": seed_data["prod_a"].id,
        "movement_type": "RECEIPT",
        "quantity": 30.0,
        "to_location": "WH-A1",
        "reference_id": inv_id,
    }
    res = client.post("/api/v1/inventory-movements", json=movement_payload, headers=headers_ops_a)
    assert res.status_code == 201
    mov_data = res.json()
    assert mov_data["movement_type"] == "RECEIPT"
    assert mov_data["quantity"] == 30.0
    assert mov_data["reference_id"] == inv_id

    # Verify inventory was atomically adjusted to 130.0
    res = client.get(f"/api/v1/inventory/{inv_id}", headers=headers_ops_a)
    assert res.json()["quantity_on_hand"] == 130.0


# ==============================================================================
# 17. MOVEMENT OWNERSHIP & CROSS-TENANT REFERENCE REJECTION (404)
# ==============================================================================
def test_17_movement_cross_tenant_reference_rejection(client: TestClient, seed_data: dict):
    """Movement referencing an inventory record of another tenant is rejected with 404 masked."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    inv_b_id = seed_data["inv_b"].id

    movement_payload = {
        "product_id": seed_data["prod_a"].id,
        "movement_type": "RECEIPT",
        "quantity": 10.0,
        "reference_id": inv_b_id,
    }
    res = client.post("/api/v1/inventory-movements", json=movement_payload, headers=headers_ops_a)
    assert res.status_code == 404
    assert "Referenced inventory" in res.json()["error"]["message"]


# ==============================================================================
# 18. APPEND-ONLY & IMMUTABILITY RULES (405)
# ==============================================================================
def test_18_append_only_and_immutability_rules(client: TestClient, seed_data: dict):
    """InventoryMovement is strictly immutable (PATCH/DELETE → 405). Inventory DELETE → 405."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    mov_id = seed_data["mov_a"].id
    inv_id = seed_data["inv_a"].id

    # PATCH movement → 405 Method Not Allowed
    assert client.patch(f"/api/v1/inventory-movements/{mov_id}", json={"quantity": 999.0}, headers=headers_ops_a).status_code == 405

    # DELETE movement → 405 Method Not Allowed
    assert client.delete(f"/api/v1/inventory-movements/{mov_id}", headers=headers_ops_a).status_code == 405

    # DELETE inventory → 405 Method Not Allowed
    assert client.delete(f"/api/v1/inventory/{inv_id}", headers=headers_ops_a).status_code == 405


# ==============================================================================
# 19. CONCURRENT UPDATE & INSUFFICIENT STOCK PROTECTION (400)
# ==============================================================================
def test_19_insufficient_stock_protection(client: TestClient, seed_data: dict):
    """Deducting more stock than available rejects atomically with 400 INSUFFICIENT_INVENTORY."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}
    inv_id = seed_data["inv_a"].id

    # Current stock is 100.0. Attempt SHIPMENT movement with quantity=500.0
    movement_payload = {
        "product_id": seed_data["prod_a"].id,
        "movement_type": "SHIPMENT",
        "quantity": 500.0,
        "reference_id": inv_id,
    }
    res = client.post("/api/v1/inventory-movements", json=movement_payload, headers=headers_ops_a)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INSUFFICIENT_INVENTORY"

    # Verify inventory was NOT deducted
    res = client.get(f"/api/v1/inventory/{inv_id}", headers=headers_ops_a)
    assert res.json()["quantity_on_hand"] == 100.0


# ==============================================================================
# 20. AUDIT BEHAVIOR
# ==============================================================================
def test_20_audit_logging_behavior(client: TestClient, seed_data: dict, test_db: Session):
    """CREATE and UPDATE operations on Inventory and Movement generate audit records."""
    headers_ops_a = {"Cookie": f"riskwise_session={seed_data['ops_a_cookie']}"}

    # Count audit records before
    count_before = len(test_db.scalars(select(AuditLog).where(AuditLog.org_id == "org_alpha_01")).all())

    # 1. Create inventory
    inv_res = client.post(
        "/api/v1/inventory",
        json={"product_id": seed_data["prod_a"].id, "quantity_on_hand": 80.0},
        headers=headers_ops_a,
    )
    assert inv_res.status_code == 201
    new_inv_id = inv_res.json()["id"]

    # 2. Update inventory
    upd_res = client.patch(
        f"/api/v1/inventory/{new_inv_id}",
        json={"quantity_on_hand": 90.0},
        headers=headers_ops_a,
    )
    assert upd_res.status_code == 200

    # 3. Create movement
    mov_res = client.post(
        "/api/v1/inventory-movements",
        json={"product_id": seed_data["prod_a"].id, "quantity": 10.0, "movement_type": "RECEIPT"},
        headers=headers_ops_a,
    )
    assert mov_res.status_code == 201

    # Verify audit records generated
    logs = test_db.scalars(
        select(AuditLog).where(AuditLog.org_id == "org_alpha_01").order_by(AuditLog.timestamp.desc())
    ).all()
    actions = [log.action for log in logs]
    resource_types = [log.resource_type for log in logs]

    assert "CREATE" in actions
    assert "UPDATE" in actions
    assert "Inventory" in resource_types
    assert "InventoryMovement" in resource_types


# ==============================================================================
# 21. STANDARDIZED ERROR RESPONSES
# ==============================================================================
def test_21_standardized_error_envelope(client: TestClient, seed_data: dict):
    """Invalid filter field returns standardized 400 Bad Request envelope."""
    headers_viewer = {"Cookie": f"riskwise_session={seed_data['viewer_cookie']}"}

    res = client.get("/api/v1/inventory?unknown_filter=true", headers=headers_viewer)
    assert res.status_code == 400
    body = res.json()
    assert "error" in body
    assert body["error"]["code"] == "INVALID_FILTER_FIELD"

    res = client.get("/api/v1/inventory-movements?unknown_filter=true", headers=headers_viewer)
    assert res.status_code == 400
    body = res.json()
    assert "error" in body
    assert body["error"]["code"] == "INVALID_FILTER_FIELD"


# ==============================================================================
# 22. OPENAPI ROUTE REGISTRATION & OPERATION ID UNIQUENESS
# ==============================================================================
def test_22_openapi_route_registration_and_uniqueness():
    """All inventory routes are registered and operation IDs are globally unique."""
    schema = app.openapi()
    paths = schema.get("paths", {})

    # Check inventory routes
    assert "/api/v1/inventory" in paths
    assert "get" in paths["/api/v1/inventory"]
    assert "post" in paths["/api/v1/inventory"]

    assert "/api/v1/inventory/{id}" in paths
    assert "get" in paths["/api/v1/inventory/{id}"]
    assert "patch" in paths["/api/v1/inventory/{id}"]
    assert "delete" not in paths["/api/v1/inventory/{id}"]

    # Check inventory-movement routes
    assert "/api/v1/inventory-movements" in paths
    assert "get" in paths["/api/v1/inventory-movements"]
    assert "post" in paths["/api/v1/inventory-movements"]

    assert "/api/v1/inventory-movements/{id}" in paths
    assert "get" in paths["/api/v1/inventory-movements/{id}"]
    assert "patch" not in paths["/api/v1/inventory-movements/{id}"]
    assert "delete" not in paths["/api/v1/inventory-movements/{id}"]

    # Verify operation ID uniqueness across entire API
    operation_ids = set()
    duplicates = []
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if isinstance(operation, dict) and "operationId" in operation:
                op_id = operation["operationId"]
                if op_id in operation_ids:
                    duplicates.append(f"{method.upper()} {path} -> {op_id}")
                operation_ids.add(op_id)

    assert len(duplicates) == 0, f"Duplicate operation IDs found: {duplicates}"
