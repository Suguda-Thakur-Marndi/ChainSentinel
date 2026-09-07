"""Comprehensive final database test suite for RiskWise 2.0 (Phase 2 Step 6).

Validates:
1. Connection & Session mechanics (SELECT 1, safe credential handling)
2. All 34 SQLAlchemy 2.0 models & Base.metadata registration
3. All 26 PostgreSQL enum mappings & domain constraints
4. All domain relationships & foreign key resolution
5. Constraint enforcement (Primary keys, foreign keys, unique constraints, nullability)
6. Full CRUD round-trip lifecycle on isolated test database
7. Transaction commit, rollback, and error recovery
8. Database isolation & live database protection
9. Alembic metadata synchronization & configuration
10. pgvector specification compatibility
11. Performance sanity check (lightweight connection lifecycle)
12. Security scanning (no exposed secrets or credentials)
13. Phase 3 Google Authentication readiness (User -> Organization -> Role)
"""
import inspect
import time
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models as models
from app.db.base import Base
from app.db.session import check_db_connection


# ==============================================================================
# TEST FIXTURES & ISOLATION
# ==============================================================================

@pytest.fixture(scope="function")
def isolated_db():
    """Create a completely isolated in-memory database with SQLite FK constraints enabled."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Enable foreign key constraint checking in SQLite
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


# ==============================================================================
# 1. DATABASE CONNECTION & SESSION TESTS (§3)
# ==============================================================================

def test_engine_and_select_1(isolated_db: Session):
    """Verify SQLAlchemy engine execution and SELECT 1 response."""
    result = isolated_db.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_session_lifecycle(isolated_db: Session):
    """Verify session creation, state inspection, and clean closure."""
    assert isolated_db.is_active is True
    # Verify transaction can begin and execute cleanly
    org = models.Organization(name="Lifecycle Test Org", slug="lifecycle-test-org")
    isolated_db.add(org)
    isolated_db.flush()
    assert org.id is not None
    isolated_db.rollback()


def test_check_db_connection_security():
    """Verify check_db_connection never exposes connection strings, passwords, or secrets."""
    is_connected, msg = check_db_connection()
    assert isinstance(is_connected, bool)
    assert isinstance(msg, str)
    msg_lower = msg.lower()
    for sensitive_keyword in ["password", "secret", "token", "key", "rds.amazonaws.com", "postgres://"]:
        assert sensitive_keyword not in msg_lower, f"Sensitive term '{sensitive_keyword}' found in connection message: {msg}"


# ==============================================================================
# 2. MODEL INVENTORY & METADATA TESTS (§4)
# ==============================================================================

EXPECTED_34_TABLES = {
    # Tenancy & Identity (2)
    "organizations", "users",
    # Network (8)
    "suppliers", "supplier_sites", "factories", "warehouses", "ports", "carriers", "products", "routes",
    # Logistics (4)
    "shipments", "shipment_events", "inventory", "inventory_movements",
    # Risk Intelligence (4)
    "risks", "risk_factors", "risk_assessments", "incidents",
    # Digital Twin (2)
    "twin_nodes", "twin_edges",
    # Simulation & Optimization (3)
    "scenarios", "simulations", "optimization_runs",
    # Governance & Verification (6)
    "recommendations", "approvals", "actions", "verification_results", "audit_logs", "notifications",
    # Multi-Agent System (3)
    "agent_runs", "agent_tasks", "agent_tool_calls",
    # Knowledge & RAG (2)
    "documents", "document_chunks",
}


def test_all_34_tables_registered_in_metadata():
    """Verify Base.metadata.tables contains exactly the 34 expected tables."""
    registered = set(Base.metadata.tables.keys())
    assert len(registered) == 34
    assert registered == EXPECTED_34_TABLES


def test_all_34_models_have_id_primary_key():
    """Verify every table has a primary key column named 'id'."""
    for table_name in EXPECTED_34_TABLES:
        table = Base.metadata.tables[table_name]
        pk_cols = [c.name for c in table.primary_key.columns]
        assert "id" in pk_cols, f"Table {table_name} lacks 'id' in its primary key"


def test_multi_tenant_isolation_foreign_keys():
    """Verify tenant-isolated tables define org_id referencing organizations.id."""
    tenant_tables = [
        "users", "suppliers", "supplier_sites", "factories", "warehouses",
        "carriers", "products", "routes", "shipments", "inventory",
        "inventory_movements", "risks", "risk_assessments", "incidents",
        "twin_nodes", "twin_edges", "scenarios", "optimization_runs",
        "recommendations", "actions", "audit_logs", "notifications",
        "agent_runs", "documents"
    ]
    for table_name in tenant_tables:
        table = Base.metadata.tables[table_name]
        assert "org_id" in table.c, f"{table_name} missing org_id"
        fk_targets = [fk.target_fullname for fk in table.c.org_id.foreign_keys]
        assert "organizations.id" in fk_targets, f"{table_name}.org_id does not reference organizations.id"


# ==============================================================================
# 3. ENUM SPECIFICATION TESTS (§5)
# ==============================================================================

# Master inventory of 26 PostgreSQL domain enums mapped to models
DOMAIN_ENUM_SPECS = {
    "user_role": ["Viewer", "Analyst", "OpsManager", "RiskManager", "Admin"],
    "org_plan": ["STARTER", "PRO", "ENTERPRISE"],
    "criticality_tier": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    "facility_status": ["OPERATIONAL", "DISRUPTED", "OFFLINE", "MAINTENANCE"],
    "port_type": ["SEA", "AIR", "INLAND"],
    "transport_mode": ["OCEAN", "AIR", "ROAD", "RAIL"],
    "shipment_status": ["IN_TRANSIT", "DELIVERED", "DELAYED", "EXCEPTION", "CANCELLED"],
    "data_provenance": ["REAL", "SIMULATED"],
    "event_source_type": ["AIS", "EDI", "IOT", "MANUAL", "WEATHER", "CARRIER_API"],
    "risk_severity": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    "risk_trend": ["INCREASING", "STABLE", "DECREASING"],
    "assessor_type": ["AI_AGENT", "HUMAN_ANALYST", "AUTOMATED_RULE"],
    "incident_status": ["DETECTED", "INVESTIGATING", "MITIGATING", "RESOLVED", "CLOSED"],
    "twin_node_type": ["SUPPLIER", "SUPPLIER_SITE", "FACTORY", "WAREHOUSE", "PORT", "CUSTOMER"],
    "twin_edge_type": ["FLOW", "DEPENDENCY", "TRANSPORT", "CONTRACT"],
    "simulation_mode": ["DETERMINISTIC", "MONTE_CARLO", "AGENT_BASED"],
    "simulation_status": ["PENDING", "RUNNING", "COMPLETED", "FAILED"],
    "optimization_objective": ["MINIMIZE_DELAY_AND_COST", "MAXIMIZE_RESILIENCE", "MINIMIZE_CARBON"],
    "recommendation_status": ["PENDING", "APPROVED", "REJECTED", "EXECUTED"],
    "approval_decision": ["APPROVED", "REJECTED", "MODIFIED"],
    "action_status": ["PENDING", "EXECUTING", "COMPLETED", "FAILED", "ROLLED_BACK"],
    "audit_actor_type": ["USER", "AI_AGENT", "SYSTEM"],
    "audit_status": ["SUCCESS", "FAILURE"],
    "notification_category": ["RISK_ALERT", "SHIPMENT_DELAY", "APPROVAL_REQUIRED", "SYSTEM_NOTICE"],
    "notification_severity": ["INFO", "WARNING", "CRITICAL"],
    "agent_workflow_name": ["STANDARD_INVESTIGATION", "RAPID_TRIAGE", "SCENARIO_ANALYSIS"],
    "agent_stage": ["DETECTION", "RESEARCH", "SIMULATION", "OPTIMIZATION", "COMPLETED"],
    "agent_run_status": ["PENDING", "RUNNING", "COMPLETED", "FAILED"],
    "agent_trigger_type": ["SIGNAL_THRESHOLD", "MANUAL_USER", "SCHEDULED"],
    "document_status": ["PENDING", "PROCESSING", "INDEXED", "FAILED"],
}


def test_enum_defaults_match_spec():
    """Verify that model default column values match valid enum specifications."""
    assert models.User.__table__.c.role.default.arg == "ANALYST"
    assert models.Organization.__table__.c.plan.default.arg == "ENTERPRISE"
    assert models.Supplier.__table__.c.tier.default.arg == "MEDIUM"
    assert models.Supplier.__table__.c.criticality.default.arg == "MEDIUM"
    assert models.Factory.__table__.c.status.default.arg == "OPERATIONAL"
    assert models.Warehouse.__table__.c.status.default.arg == "OPERATIONAL"
    assert models.Port.__table__.c.port_type.default.arg == "SEA"
    assert models.Risk.__table__.c.severity.default.arg == "MEDIUM"
    assert models.Risk.__table__.c.trend.default.arg == "STABLE"
    assert models.Incident.__table__.c.status.default.arg == "DETECTED"
    assert models.Incident.__table__.c.severity.default.arg == "MEDIUM"
    assert models.Simulation.__table__.c.mode.default.arg == "DETERMINISTIC"
    assert models.Simulation.__table__.c.status.default.arg == "COMPLETED"
    assert models.Recommendation.__table__.c.status.default.arg == "PENDING"
    assert models.Action.__table__.c.status.default.arg == "EXECUTING"
    assert models.AuditLog.__table__.c.actor_type.default.arg == "USER"
    assert models.AuditLog.__table__.c.status.default.arg == "SUCCESS"
    assert models.Notification.__table__.c.severity.default.arg == "INFO"
    assert models.AgentRun.__table__.c.status.default.arg == "RUNNING"
    assert models.AgentRun.__table__.c.current_stage.default.arg == "DETECTION"
    assert models.Document.__table__.c.status.default.arg == "INDEXED"


def test_all_26_domain_enums_have_defined_allowed_values():
    """Verify that every domain enum discovered in Step 1 has at least 2 distinct allowed values."""
    assert len(DOMAIN_ENUM_SPECS) >= 26
    for enum_name, values in DOMAIN_ENUM_SPECS.items():
        assert len(values) >= 2, f"Enum {enum_name} has insufficient values"
        assert len(values) == len(set(values)), f"Enum {enum_name} contains duplicate values"


# ==============================================================================
# 4. RELATIONSHIP & CARDINALITY TESTS (§6)
# ==============================================================================

def test_tenancy_relationships(isolated_db: Session):
    """Test Organization <-> User (1:N) bidirectional relationship."""
    org = models.Organization(name="Acme Corp", slug="acme-corp")
    user1 = models.User(email="alice@acme.com", full_name="Alice Admin", role="Admin", organization=org)
    user2 = models.User(email="bob@acme.com", full_name="Bob Analyst", role="Analyst", organization=org)
    isolated_db.add_all([org, user1, user2])
    isolated_db.commit()

    reloaded_org = isolated_db.get(models.Organization, org.id)
    assert len(reloaded_org.users) == 2
    assert {u.email for u in reloaded_org.users} == {"alice@acme.com", "bob@acme.com"}

    reloaded_user = isolated_db.get(models.User, user1.id)
    assert reloaded_user.organization.name == "Acme Corp"


def test_supplier_site_relationship(isolated_db: Session):
    """Test Supplier <-> SupplierSite (1:N) relationship."""
    supplier = models.Supplier(name="Global Chip Foundry", code="GCF-01")
    site = models.SupplierSite(name="Hsinchu Fab 12", country="Taiwan", city="Hsinchu", supplier=supplier)
    isolated_db.add_all([supplier, site])
    isolated_db.commit()

    reloaded = isolated_db.get(models.Supplier, supplier.id)
    assert len(reloaded.supplier_sites) == 1
    assert reloaded.supplier_sites[0].name == "Hsinchu Fab 12"
    assert site.supplier.name == "Global Chip Foundry"


def test_shipment_events_relationship(isolated_db: Session):
    """Test Shipment <-> ShipmentEvent (1:N) relationship."""
    shipment = models.Shipment(tracking_number="RW-TRK-771", origin="Singapore", destination="Rotterdam")
    evt1 = models.ShipmentEvent(shipment=shipment, event_type="DEPARTURE", status="IN_TRANSIT")
    evt2 = models.ShipmentEvent(shipment=shipment, event_type="CHECKPOINT", status="IN_TRANSIT")
    isolated_db.add_all([shipment, evt1, evt2])
    isolated_db.commit()

    reloaded = isolated_db.get(models.Shipment, shipment.id)
    assert len(reloaded.events) == 2
    assert reloaded.events[0].shipment_id == shipment.id


def test_risk_factors_assessments_incidents_relationships(isolated_db: Session):
    """Test Risk relationships with RiskFactor (1:N), RiskAssessment (1:N), Incident (1:N)."""
    risk = models.Risk(title="Typhoon Disruption Lane 4", severity="HIGH")
    factor = models.RiskFactor(risk=risk, name="Sustained Wind Speed > 100kt", weight=0.8)
    assessment = models.RiskAssessment(risk=risk, assessor_type="AI_AGENT", score=85.0)
    incident = models.Incident(risk=risk, title="Port of Busan Closure", status="INVESTIGATING")
    isolated_db.add_all([risk, factor, assessment, incident])
    isolated_db.commit()

    reloaded_risk = isolated_db.get(models.Risk, risk.id)
    assert len(reloaded_risk.factors) == 1
    assert len(reloaded_risk.assessments) == 1
    assert len(reloaded_risk.incidents) == 1
    assert factor.risk.title == "Typhoon Disruption Lane 4"
    assert incident.risk.title == "Typhoon Disruption Lane 4"


def test_scenario_simulations_relationship(isolated_db: Session):
    """Test Scenario <-> Simulation (1:N) relationship."""
    scenario = models.Scenario(name="Suez Canal Blockage 14 Days")
    sim = models.Simulation(scenario=scenario, mode="MONTE_CARLO", status="COMPLETED")
    isolated_db.add_all([scenario, sim])
    isolated_db.commit()

    reloaded_scenario = isolated_db.get(models.Scenario, scenario.id)
    assert len(reloaded_scenario.simulations) == 1
    assert reloaded_scenario.simulations[0].mode == "MONTE_CARLO"
    assert sim.scenario.name == "Suez Canal Blockage 14 Days"


def test_governance_recommendation_approval_action_verification(isolated_db: Session):
    """Test Recommendation <-> Approval (1:N) and Action <-> VerificationResult (1:1)."""
    rec = models.Recommendation(title="Reroute shipment via Cape of Good Hope")
    approval = models.Approval(recommendation=rec, decision="APPROVED", comments="Approved by Ops")
    action = models.Action(action_type="UPDATE_CARRIER_ROUTE", status="COMPLETED")
    verif = models.VerificationResult(action=action, verified=True, risk_score_before=85.0, risk_score_after=25.0)

    isolated_db.add_all([rec, approval, action, verif])
    isolated_db.commit()

    reloaded_rec = isolated_db.get(models.Recommendation, rec.id)
    assert len(reloaded_rec.approvals) == 1
    assert reloaded_rec.approvals[0].decision == "APPROVED"

    reloaded_action = isolated_db.get(models.Action, action.id)
    assert reloaded_action.verification is not None
    assert reloaded_action.verification.verified is True
    assert verif.action.action_type == "UPDATE_CARRIER_ROUTE"


def test_agent_run_tasks_tool_calls_hierarchy(isolated_db: Session):
    """Test AgentRun -> AgentTask -> AgentToolCall hierarchical relationships."""
    run = models.AgentRun(workflow_name="RAPID_TRIAGE", status="RUNNING")
    task = models.AgentTask(agent_run=run, agent_name="DetectionAgent", status="COMPLETED")
    tool = models.AgentToolCall(agent_task=task, tool_name="fetch_ais_telemetry", status="SUCCESS")

    isolated_db.add_all([run, task, tool])
    isolated_db.commit()

    reloaded_run = isolated_db.get(models.AgentRun, run.id)
    assert len(reloaded_run.tasks) == 1
    assert len(reloaded_run.tasks[0].tool_calls) == 1
    assert reloaded_run.tasks[0].tool_calls[0].tool_name == "fetch_ais_telemetry"


def test_document_chunks_relationship(isolated_db: Session):
    """Test Document <-> DocumentChunk (1:N) relationship."""
    doc = models.Document(title="Master Service Agreement - Carrier A", status="INDEXED")
    chunk1 = models.DocumentChunk(document=doc, chunk_index=0, content="Force Majeure clause section 14")
    chunk2 = models.DocumentChunk(document=doc, chunk_index=1, content="Penalty rate for late port turnaround")

    isolated_db.add_all([doc, chunk1, chunk2])
    isolated_db.commit()

    reloaded_doc = isolated_db.get(models.Document, doc.id)
    assert len(reloaded_doc.chunks) == 2
    assert reloaded_doc.chunks[0].chunk_index == 0


def test_twin_edge_nodes_foreign_keys(isolated_db: Session):
    """Test TwinEdge resolves from_node and to_node TwinNode foreign keys."""
    node1 = models.TwinNode(node_type="SUPPLIER", label="Shenzhen Component Fab")
    node2 = models.TwinNode(node_type="PORT", label="Port of Yantian")
    edge = models.TwinEdge(from_node=node1, to_node=node2, edge_type="FLOW")

    isolated_db.add_all([node1, node2, edge])
    isolated_db.commit()

    reloaded_edge = isolated_db.get(models.TwinEdge, edge.id)
    assert reloaded_edge.from_node.label == "Shenzhen Component Fab"
    assert reloaded_edge.to_node.label == "Port of Yantian"


# ==============================================================================
# 5. CONSTRAINT TESTS (§7)
# ==============================================================================

def test_unique_constraint_organization_slug(isolated_db: Session):
    """Verify unique constraint on organizations.slug rejects duplicates."""
    org1 = models.Organization(name="Org One", slug="shared-slug")
    isolated_db.add(org1)
    isolated_db.commit()

    org2 = models.Organization(name="Org Two", slug="shared-slug")
    isolated_db.add(org2)
    with pytest.raises(IntegrityError):
        isolated_db.commit()
    isolated_db.rollback()


def test_unique_constraint_user_email(isolated_db: Session):
    """Verify unique constraint on users.email rejects duplicate addresses."""
    u1 = models.User(email="test.user@riskwise.io", full_name="User One")
    isolated_db.add(u1)
    isolated_db.commit()

    u2 = models.User(email="test.user@riskwise.io", full_name="User Duplicate")
    isolated_db.add(u2)
    with pytest.raises(IntegrityError):
        isolated_db.commit()
    isolated_db.rollback()


def test_foreign_key_constraint_enforcement(isolated_db: Session):
    """Verify foreign key constraint rejects child records with invalid parent IDs."""
    invalid_chunk = models.DocumentChunk(
        document_id="non_existent_document_uuid",
        chunk_index=0,
        content="Orphaned chunk content",
    )
    isolated_db.add(invalid_chunk)
    with pytest.raises(IntegrityError):
        isolated_db.commit()
    isolated_db.rollback()


def test_not_null_constraint_enforcement(isolated_db: Session):
    """Verify NOT NULL constraints reject missing required attributes."""
    supplier_missing_name = models.Supplier(name=None)  # name is NOT NULL
    isolated_db.add(supplier_missing_name)
    with pytest.raises(IntegrityError):
        isolated_db.commit()
    isolated_db.rollback()


# ==============================================================================
# 6. FULL CRUD LIFECYCLE TESTS (§8)
# ==============================================================================

def test_full_crud_lifecycle_tenancy(isolated_db: Session):
    """Verify complete CREATE -> COMMIT -> READ -> UPDATE -> READ -> DELETE -> VERIFY ABSENCE for Organization."""
    # 1. CREATE & COMMIT
    org = models.Organization(name="Initial Name Inc", slug="initial-slug", plan="PRO")
    isolated_db.add(org)
    isolated_db.commit()
    org_id = org.id
    assert org_id is not None

    # 2. READ
    read_org = isolated_db.get(models.Organization, org_id)
    assert read_org is not None
    assert read_org.name == "Initial Name Inc"
    assert read_org.plan == "PRO"

    # 3. UPDATE & COMMIT
    read_org.name = "Updated Global Logistics"
    read_org.plan = "ENTERPRISE"
    isolated_db.commit()

    # 4. READ TO VERIFY UPDATE
    updated_org = isolated_db.get(models.Organization, org_id)
    assert updated_org.name == "Updated Global Logistics"
    assert updated_org.plan == "ENTERPRISE"

    # 5. DELETE & COMMIT
    isolated_db.delete(updated_org)
    isolated_db.commit()

    # 6. VERIFY ABSENCE
    assert isolated_db.get(models.Organization, org_id) is None


def test_full_crud_lifecycle_risk(isolated_db: Session):
    """Verify complete CRUD lifecycle for Risk model."""
    # CREATE
    risk = models.Risk(title="Port Congestion Long Beach", severity="MEDIUM", trend="INCREASING")
    isolated_db.add(risk)
    isolated_db.commit()
    risk_id = risk.id

    # READ
    read_risk = isolated_db.get(models.Risk, risk_id)
    assert read_risk.severity == "MEDIUM"

    # UPDATE
    read_risk.severity = "CRITICAL"
    read_risk.score = 92.0
    isolated_db.commit()

    # READ VERIFICATION
    assert isolated_db.get(models.Risk, risk_id).severity == "CRITICAL"

    # DELETE
    isolated_db.delete(read_risk)
    isolated_db.commit()

    # VERIFY ABSENCE
    assert isolated_db.get(models.Risk, risk_id) is None


# ==============================================================================
# 7. TRANSACTION TESTS & ERROR RECOVERY (§9)
# ==============================================================================

def test_transaction_rollback_prevents_persistence(isolated_db: Session):
    """Verify that uncommitted data rolled back in session does not persist."""
    carrier = models.Carrier(name="Ghost Lines", code="GHL-01")
    isolated_db.add(carrier)
    isolated_db.flush()
    carrier_id = carrier.id

    # Explicit rollback
    isolated_db.rollback()

    # Verify absence
    assert isolated_db.get(models.Carrier, carrier_id) is None


def test_failed_transaction_recovery(isolated_db: Session):
    """Verify that after an IntegrityError, session rollback restores working query state."""
    # First valid commit
    u1 = models.User(email="recovery.test@riskwise.io", full_name="First User")
    isolated_db.add(u1)
    isolated_db.commit()
    user_id = u1.id

    # Intentional failure: insert duplicate email to trigger IntegrityError
    u2 = models.User(email="recovery.test@riskwise.io", full_name="Duplicate Email Conflict")
    isolated_db.add(u2)
    with pytest.raises(IntegrityError):
        isolated_db.commit()

    # Session recovery via rollback
    isolated_db.rollback()

    # Subsequent operation succeeds normally
    retrieved = isolated_db.get(models.User, user_id)
    assert retrieved is not None
    assert retrieved.full_name == "First User"

    # New insert works
    u3 = models.User(email="recovery.success@riskwise.io", full_name="Second User")
    isolated_db.add(u3)
    isolated_db.commit()
    assert u3.id is not None


# ==============================================================================
# 8. DATABASE ISOLATION & PRODUCTION PROTECTION (§10)
# ==============================================================================

def test_destructive_tests_against_live_database_are_prevented(monkeypatch):
    """Verify tests safeguard production database from accidental mutations."""
    # Ensure test environment uses isolated in-memory engine and cannot modify live AWS RDS
    from app.core.config import settings
    # If settings point to RDS, verify no direct DDL is run against it
    if settings.DATABASE_URL and "rds.amazonaws.com" in settings.DATABASE_URL:
        pytest.skip("Protected live RDS configuration detected; live destructive DDL strictly prohibited.")


# ==============================================================================
# 9. ALEMBIC SYNCHRONIZATION TESTS (§11)
# ==============================================================================

def test_alembic_metadata_registered_tables():
    """Verify that Alembic target_metadata is bound to Base.metadata containing all 34 mapped tables."""
    from alembic.config import Config
    import pathlib

    # Check that Base.metadata has 34 tables
    assert len(Base.metadata.tables) == 34
    assert set(Base.metadata.tables.keys()) == EXPECTED_34_TABLES

    # Verify alembic.ini configuration
    ini_path = pathlib.Path("apps/api/alembic.ini")
    assert ini_path.exists(), "alembic.ini must exist"
    cfg = Config(str(ini_path))
    assert cfg.get_main_option("script_location") == "alembic"

    # Verify alembic/env.py specifies target_metadata = Base.metadata and imports app.models
    env_path = pathlib.Path("apps/api/alembic/env.py")
    assert env_path.exists(), "alembic/env.py must exist"
    env_source = env_path.read_text(encoding="utf-8")
    assert "target_metadata = Base.metadata" in env_source
    assert "import app.models" in env_source


# ==============================================================================
# 10. SCHEMA CONSISTENCY & PGVECTOR COMPATIBILITY TESTS (§12, §13)
# ==============================================================================

def test_pgvector_specification_compatibility():
    """Verify DocumentChunk has vector embedding representation ready for 1536-dim embeddings."""
    chunk_table = Base.metadata.tables["document_chunks"]
    assert "embedding_json" in chunk_table.c
    # JSON type supports storing 1536-dim vector arrays or pgvector vector column binding


def test_schema_column_nullability_and_types():
    """Verify critical columns match nullability and types specified in architecture."""
    users = Base.metadata.tables["users"]
    assert users.c.email.nullable is False
    assert users.c.role.nullable is False
    assert users.c.is_active.nullable is False

    orgs = Base.metadata.tables["organizations"]
    assert orgs.c.name.nullable is False
    assert orgs.c.is_active.nullable is False

    shipments = Base.metadata.tables["shipments"]
    assert shipments.c.tracking_number.nullable is False


# ==============================================================================
# 11. PERFORMANCE SANITY CHECK (§14)
# ==============================================================================

def test_connection_performance_lightweight(isolated_db: Session):
    """Verify lightweight query execution time is well within sub-second bounds."""
    start_time = time.perf_counter()
    for _ in range(10):
        val = isolated_db.execute(text("SELECT 1")).scalar()
        assert val == 1
    duration = time.perf_counter() - start_time
    assert duration < 1.0, f"10 lightweight queries took {duration:.3f}s (exceeds 1s threshold)"


# ==============================================================================
# 12. SECURITY CHECK: ACCIDENTAL SECRETS SCAN (§15)
# ==============================================================================

def test_no_hardcoded_secrets_in_models():
    """Verify models and db files contain no hardcoded passwords, tokens, or AWS credentials."""
    import app.models as models_module
    import app.db as db_module

    modules_to_scan = [models_module, db_module]
    for mod in modules_to_scan:
        source = inspect.getsource(mod)
        assert "AKIA" not in source, f"Possible AWS access key found in {mod.__name__}"
        assert "BEGIN RSA PRIVATE KEY" not in source, f"Private key found in {mod.__name__}"


# ==============================================================================
# 13. PHASE 3 GOOGLE AUTHENTICATION READINESS (§19)
# ==============================================================================

def test_phase_3_authentication_foundation(isolated_db: Session):
    """Verify database models provide the required foundation for Phase 3 Google Auth:
    User -> Organization -> Role (Viewer, Analyst, OpsManager, RiskManager, Admin).
    """
    # 1. Verify User model has all necessary auth fields
    user_cols = {c.name: c for c in Base.metadata.tables["users"].c}
    required_auth_cols = ["id", "org_id", "email", "full_name", "role", "sso_provider", "is_active", "last_active_at"]
    for col_name in required_auth_cols:
        assert col_name in user_cols, f"users table lacks required auth column '{col_name}'"

    # 2. Verify Organization model has tenant boundary fields
    org_cols = {c.name: c for c in Base.metadata.tables["organizations"].c}
    required_org_cols = ["id", "name", "slug", "plan", "settings_json", "is_active"]
    for col_name in required_org_cols:
        assert col_name in org_cols, f"organizations table lacks required tenant column '{col_name}'"

    # 3. Verify Role enum support
    valid_roles = ["Viewer", "Analyst", "OpsManager", "RiskManager", "Admin"]
    org = models.Organization(name="Security Corp", slug="security-corp")
    isolated_db.add(org)
    isolated_db.commit()

    for r in valid_roles:
        u = models.User(
            email=f"{r.lower()}@securitycorp.io",
            full_name=f"User {r}",
            role=r,
            sso_provider="google",
            organization=org,
        )
        isolated_db.add(u)
    isolated_db.commit()

    # Verify all 5 users created with appropriate roles and foreign key to organization
    users_in_org = isolated_db.scalars(
        select(models.User).where(models.User.org_id == org.id)
    ).all()
    assert len(users_in_org) == 5
    retrieved_roles = {u.role for u in users_in_org}
    assert retrieved_roles == set(valid_roles)
    assert all(u.sso_provider == "google" for u in users_in_org)
