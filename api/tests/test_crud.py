"""CRUD verification tests proving full round-trip SQLAlchemy lifecycle operations on isolated test database."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.models.logistics import Shipment, ShipmentEvent
from app.models.network import Supplier
from app.models.tenancy import Organization
from app.repositories.shipment import ShipmentRepository
from app.repositories.supplier import SupplierRepository


@pytest.fixture(scope="function")
def test_db_session():
    """Create an isolated in-memory test database and session for CRUD verification."""
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


def test_supplier_crud_lifecycle(test_db_session: Session):
    """Test full Supplier lifecycle: Create -> Save -> Retrieve -> Update -> Verify -> Delete."""
    repo = SupplierRepository(test_db_session)

    # 1. Create Supplier
    created = repo.create_supplier(
        name="Apex Microelectronics Ltd",
        code="SUP-APEX-001",
        country="Taiwan",
        tier="CRITICAL",
        criticality="HIGH",
        reliability_score=92.5,
        financial_exposure=1500000.0,
        lead_time_days=45.0,
        org_id="org_test_supply_01",
        metadata_json={"certifications": ["ISO-9001", "IATF-16949"], "audit_score": 96},
    )
    assert created.id is not None
    assert created.name == "Apex Microelectronics Ltd"
    supplier_id = created.id

    # 2. Retrieve & Verify
    retrieved = repo.get(supplier_id)
    assert retrieved is not None
    assert retrieved.id == supplier_id
    assert retrieved.code == "SUP-APEX-001"
    assert retrieved.tier == "CRITICAL"
    assert retrieved.reliability_score == 92.5
    assert retrieved.metadata_json["audit_score"] == 96

    # 3. Retrieve by business code
    by_code = repo.get_by_code("SUP-APEX-001")
    assert by_code is not None
    assert by_code.id == supplier_id

    # 4. Update & Verify
    updated = repo.update_supplier(
        supplier_id,
        reliability_score=95.0,
        lead_time_days=40.0,
        tier="STRATEGIC",
    )
    assert updated is not None
    assert updated.reliability_score == 95.0
    assert updated.lead_time_days == 40.0
    assert updated.tier == "STRATEGIC"

    # Verify retrieval reflects update
    re_retrieved = repo.get(supplier_id)
    assert re_retrieved.reliability_score == 95.0

    # 5. Delete & Verify
    deleted = repo.delete(supplier_id)
    assert deleted is True
    assert repo.get(supplier_id) is None


def test_shipment_crud_lifecycle(test_db_session: Session):
    """Test full Shipment lifecycle: Create -> Save -> Retrieve -> Update status -> Verify."""
    repo = ShipmentRepository(test_db_session)

    # 1. Create Shipment
    now = datetime.now(timezone.utc)
    created = repo.create_shipment(
        tracking_number="RW-TRK-2026-9812",
        origin="Port of Kaohsiung (TW)",
        destination="Port of Long Beach (US)",
        status="IN_TRANSIT",
        mode="OCEAN",
        org_id="org_test_supply_01",
        current_lat=22.61,
        current_lng=120.28,
        eta=now,
        eta_confidence=0.91,
        delay_minutes=0.0,
        data_provenance="REAL",
    )
    assert created.id is not None
    assert created.tracking_number == "RW-TRK-2026-9812"
    shipment_id = created.id

    # 2. Retrieve & Verify
    retrieved = repo.get_by_tracking_number("RW-TRK-2026-9812")
    assert retrieved is not None
    assert retrieved.id == shipment_id
    assert retrieved.status == "IN_TRANSIT"
    assert retrieved.delay_minutes == 0.0

    # 3. Update Status & Delay metrics
    updated = repo.update_status(
        shipment_id=shipment_id,
        new_status="DELAYED",
        delay_minutes=180.0,
        current_lat=24.15,
        current_lng=135.40,
    )
    assert updated is not None
    assert updated.status == "DELAYED"
    assert updated.delay_minutes == 180.0
    assert updated.current_lat == 24.15

    # 4. Re-retrieve to verify persistent commit
    persisted = repo.get(shipment_id)
    assert persisted.status == "DELAYED"
    assert persisted.delay_minutes == 180.0


def test_shipment_event_association(test_db_session: Session):
    """Test ShipmentEvent creation, association with Shipment, and relationship loading."""
    repo = ShipmentRepository(test_db_session)

    # 1. Create base Shipment
    shipment = repo.create_shipment(
        tracking_number="RW-TRK-OCEAN-4401",
        origin="Shanghai Port",
        destination="Rotterdam Port",
        status="IN_TRANSIT",
        mode="OCEAN",
    )
    shipment_id = shipment.id

    # 2. Add first milestone event
    event1 = repo.add_event(
        shipment_id=shipment_id,
        event_type="VESSEL_DEPARTURE",
        mode="OCEAN",
        status="DEPARTED",
        latitude=31.23,
        longitude=121.47,
        source="AIS",
        source_type="SATELLITE",
        confidence=0.98,
        metadata_json={"vessel_name": "Ever Given", "mmsi": "353136000"},
    )
    assert event1.id is not None
    assert event1.shipment_id == shipment_id
    assert event1.event_type == "VESSEL_DEPARTURE"

    # 3. Add second milestone event (delay checkpoint)
    event2 = repo.add_event(
        shipment_id=shipment_id,
        event_type="WEATHER_REROUTE",
        mode="OCEAN",
        status="DELAYED",
        delay_minutes=360.0,
        latitude=12.50,
        longitude=43.30,
        source="WEATHER_ALERT",
        source_type="METEOROLOGICAL",
        confidence=0.88,
        metadata_json={"storm_name": "Cyclone Alpha", "swell_meters": 6.5},
    )
    assert event2.id is not None

    # 4. Retrieve Shipment with eager-loaded events
    loaded = repo.get_with_events(shipment_id)
    assert loaded is not None
    assert len(loaded.events) == 2
    assert loaded.events[0].event_type == "VESSEL_DEPARTURE"
    assert loaded.events[1].event_type == "WEATHER_REROUTE"
    assert loaded.events[1].delay_minutes == 360.0

    # 5. Retrieve events directly via repository
    events_list = repo.get_events(shipment_id)
    assert len(events_list) == 2
    assert events_list[0].source == "AIS"


def test_repository_rollback_on_failure(test_db_session: Session):
    """Test that failed repository operations safely roll back transaction and raise controlled error."""
    repo = SupplierRepository(test_db_session)

    # Create initial supplier
    supplier = Supplier(
        id="sup_fixed_id_001",
        name="Fixed ID Supplier",
        code="FIXED-01",
    )
    repo.create(supplier)

    # Attempt to insert duplicate primary key to trigger IntegrityError
    duplicate_supplier = Supplier(
        id="sup_fixed_id_001",
        name="Duplicate Supplier",
        code="FIXED-02",
    )
    with pytest.raises(Exception):
        repo.create(duplicate_supplier)

    # Verify session is clean and able to continue executing queries
    retrieved = repo.get("sup_fixed_id_001")
    assert retrieved is not None
    assert retrieved.name == "Fixed ID Supplier"

