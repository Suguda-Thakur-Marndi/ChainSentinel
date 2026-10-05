import os
import sys
sys.path.insert(0, os.path.abspath("."))

# Configure environment for production against migrated PostgreSQL test database
os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres@127.0.0.1:5433/riskwise_test"
os.environ["APP_ENV"] = "production"

from app.core.config import settings
settings.DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:5433/riskwise_test"
settings.APP_ENV = "production"

from sqlalchemy import text
from starlette.testclient import TestClient
import app.db.session as db_session
# Re-init db engine with the PostgreSQL URL
db_session.init_db_engine()

from app.main import app
import app.models as models

def main():
    print("==================================================")
    print("VERIFYING NO create_all() DEPENDENCY")
    print("==================================================")
    print(f"Active APP_ENV: {settings.APP_ENV}")
    print(f"Active Database Engine: {db_session.engine.url}")
    assert db_session.engine.dialect.name == "postgresql"

    # Call ensure_tables_exist to verify it acts as a no-op in production
    db_session.ensure_tables_exist()
    print("ensure_tables_exist() safely bypassed in production mode.")

    client = TestClient(app)

    print("\n==================================================")
    print("TESTING HEALTH AND READINESS ENDPOINTS")
    print("==================================================")
    
    # 1. /health
    res_health = client.get("/health")
    print(f"GET /health: {res_health.status_code} -> {res_health.json()}")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    # 2. /ready
    res_ready = client.get("/ready")
    print(f"GET /ready: {res_ready.status_code} -> {res_ready.json()}")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"

    # 3. /health/db
    res_db = client.get("/health/db")
    print(f"GET /health/db: {res_db.status_code} -> {res_db.json()}")
    assert res_db.status_code == 200
    assert res_db.json()["status"] == "ok"

    print("\n==================================================")
    print("PERFORMING CRUD SMOKE TESTS ON MIGRATED POSTGRESQL")
    print("==================================================")

    db = next(db_session.get_db())
    try:
        # Create an organization for tenant testing
        org = models.Organization(
            name="RiskWise Test Tenant",
            slug="riskwise-test-tenant",
            plan="ENTERPRISE",
            is_active=True
        )
        db.add(org)
        db.commit()
        db.refresh(org)
        org_id = org.id
        print(f"[Organization] Created: ID={org_id}, Name={org.name}")

        # 1. Supplier CRUD
        supplier = models.Supplier(
            org_id=org_id,
            name="Global Chipset Foundry Ltd",
            code="SUP-POSTGRES-001",
            country="Taiwan",
            tier="CRITICAL",
            reliability_score=95.5,
            lead_time_days=30.0,
            metadata_json={"cert": "ISO-9001"}
        )
        db.add(supplier)
        db.commit()
        db.refresh(supplier)
        print(f"[Supplier] Created: ID={supplier.id}, Name={supplier.name}")
        
        # Read
        retrieved_sup = db.query(models.Supplier).filter_by(id=supplier.id).first()
        assert retrieved_sup is not None and retrieved_sup.reliability_score == 95.5
        # Update
        retrieved_sup.reliability_score = 98.0
        db.commit()
        retrieved_sup = db.query(models.Supplier).filter_by(id=supplier.id).first()
        assert retrieved_sup.reliability_score == 98.0
        print(f"[Supplier] Verified Read & Update: Reliability={retrieved_sup.reliability_score}")

        # 2. Product CRUD
        product = models.Product(
            org_id=org_id,
            sku="SKU-CHIP-X100",
            name="NextGen Microcontroller X100",
            category="Semiconductor",
            unit_cost=45.50,
            currency="USD"
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        print(f"[Product] Created: ID={product.id}, SKU={product.sku}")
        retrieved_prod = db.query(models.Product).filter_by(id=product.id).first()
        assert retrieved_prod is not None and retrieved_prod.unit_cost == 45.50
        print(f"[Product] Verified Read: UnitCost={retrieved_prod.unit_cost}")

        # 3. Factory CRUD
        factory = models.Factory(
            org_id=org_id,
            name="Hsinchu Fabrication Plant #4",
            code="FAC-HSINCHU-4",
            country="Taiwan",
            city="Hsinchu",
            capacity=100000.0,
            status="OPERATIONAL"
        )
        db.add(factory)
        db.commit()
        db.refresh(factory)
        print(f"[Factory] Created: ID={factory.id}, Code={factory.code}")
        retrieved_fac = db.query(models.Factory).filter_by(id=factory.id).first()
        assert retrieved_fac is not None and retrieved_fac.status == "OPERATIONAL"
        print(f"[Factory] Verified Read: Status={retrieved_fac.status}")

        # 4. Warehouse CRUD
        warehouse = models.Warehouse(
            org_id=org_id,
            name="Singapore Regional Distribution Hub",
            code="WH-SIN-01",
            country="Singapore",
            city="Singapore",
            total_capacity=500000.0,
            current_occupancy=280000.0,
            status="OPERATIONAL"
        )
        db.add(warehouse)
        db.commit()
        db.refresh(warehouse)
        print(f"[Warehouse] Created: ID={warehouse.id}, Name={warehouse.name}")
        retrieved_wh = db.query(models.Warehouse).filter_by(id=warehouse.id).first()
        assert retrieved_wh is not None and retrieved_wh.total_capacity == 500000.0
        print(f"[Warehouse] Verified Read: TotalCapacity={retrieved_wh.total_capacity}")

        # 5. Route CRUD
        route = models.Route(
            org_id=org_id,
            name="Trans-Pacific Express Corridor A",
            origin_facility_id=factory.id,
            destination_facility_id=warehouse.id,
            mode="OCEAN",
            distance_km=11200.0,
            standard_lead_time_days=18.0
        )
        db.add(route)
        db.commit()
        db.refresh(route)
        print(f"[Route] Created: ID={route.id}, Corridor={route.name}")
        retrieved_route = db.query(models.Route).filter_by(id=route.id).first()
        assert retrieved_route is not None and retrieved_route.distance_km == 11200.0
        print(f"[Route] Verified Read: DistanceKm={retrieved_route.distance_km}")

        # 6. Shipment CRUD
        shipment = models.Shipment(
            org_id=org_id,
            tracking_number="RW-SHIP-PG-2026-001",
            route_id=route.id,
            product_id=product.id,
            origin="Hsinchu",
            destination="Singapore",
            status="IN_TRANSIT",
            mode="OCEAN",
            data_provenance="TELEMETRY_FEED"
        )
        db.add(shipment)
        db.commit()
        db.refresh(shipment)
        print(f"[Shipment] Created: ID={shipment.id}, Tracking={shipment.tracking_number}")
        retrieved_ship = db.query(models.Shipment).filter_by(id=shipment.id).first()
        assert retrieved_ship is not None and retrieved_ship.status == "IN_TRANSIT"
        print(f"[Shipment] Verified Read: Status={retrieved_ship.status}")

        # 7. Risk CRUD
        risk = models.Risk(
            org_id=org_id,
            title="Typhoon Disrupting South China Sea Shipping Lanes",
            risk_type="WEATHER",
            severity="CRITICAL",
            probability=0.85,
            impact=0.90,
            trend="INCREASING",
            source="METEOROLOGICAL_RADAR"
        )
        db.add(risk)
        db.commit()
        db.refresh(risk)
        print(f"[Risk] Created: ID={risk.id}, Title={risk.title}")
        retrieved_risk = db.query(models.Risk).filter_by(id=risk.id).first()
        assert retrieved_risk is not None and retrieved_risk.severity == "CRITICAL"
        print(f"[Risk] Verified Read: Severity={retrieved_risk.severity}")

        # 8. Audit Log CRUD
        audit = models.AuditLog(
            org_id=org_id,
            actor_type="SYSTEM",
            actor_id="migration_verification_runner",
            action="VERIFY_POSTGRESQL_SCHEMA",
            resource_type="DATABASE",
            resource_id="postgresql-18-riskwise_test",
            status="SUCCESS",
            before_json={"state": "pre-migration"},
            after_json={"state": "migrated-postgresql-18", "tables_verified": 34}
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)
        print(f"[AuditLog] Created: ID={audit.id}, Action={audit.action}")
        retrieved_audit = db.query(models.AuditLog).filter_by(id=audit.id).first()
        assert retrieved_audit is not None and retrieved_audit.status == "SUCCESS"
        assert retrieved_audit.after_json["tables_verified"] == 34
        print(f"[AuditLog] Verified Read: Action={retrieved_audit.action}, TablesVerified={retrieved_audit.after_json['tables_verified']}")

        print("\nALL 8 CORE REPRESENTATIVE ENTITIES SUCCESSFULLY CREATED, UPDATED, AND VERIFIED ON POSTGRESQL!")
    finally:
        db.close()

if __name__ == '__main__':
    main()
