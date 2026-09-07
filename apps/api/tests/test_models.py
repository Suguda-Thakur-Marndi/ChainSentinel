"""Unit tests for SQLAlchemy models, Base metadata registration, and schema integrity."""
import pytest
from app.db.base import Base
import app.models as models
from app.db.session import check_db_connection


def test_models_import():
    """Verify all 34 core models are importable from app.models."""
    expected_models = [
        # Tenancy
        models.Organization,
        models.User,
        # Network
        models.Supplier,
        models.SupplierSite,
        models.Factory,
        models.Warehouse,
        models.Port,
        models.Carrier,
        models.Product,
        models.Route,
        # Logistics
        models.Shipment,
        models.ShipmentEvent,
        models.Inventory,
        models.InventoryMovement,
        # Risk
        models.Risk,
        models.RiskFactor,
        models.RiskAssessment,
        models.Incident,
        # Digital Twin
        models.TwinNode,
        models.TwinEdge,
        # Simulation
        models.Scenario,
        models.Simulation,
        models.OptimizationRun,
        # Governance
        models.Recommendation,
        models.Approval,
        models.Action,
        models.VerificationResult,
        models.AuditLog,
        models.Notification,
        # Agents
        models.AgentRun,
        models.AgentTask,
        models.AgentToolCall,
        # Knowledge
        models.Document,
        models.DocumentChunk,
    ]
    assert len(expected_models) == 34
    for model_cls in expected_models:
        assert hasattr(model_cls, "__tablename__")


def test_base_metadata_tables():
    """Verify Base.metadata contains exactly 34 registered tables and no duplicates."""
    tables = Base.metadata.tables
    assert len(tables) == 34

    expected_tables = {
        "organizations",
        "users",
        "suppliers",
        "supplier_sites",
        "factories",
        "warehouses",
        "ports",
        "carriers",
        "products",
        "routes",
        "shipments",
        "shipment_events",
        "inventory",
        "inventory_movements",
        "risks",
        "risk_factors",
        "risk_assessments",
        "incidents",
        "twin_nodes",
        "twin_edges",
        "scenarios",
        "simulations",
        "optimization_runs",
        "recommendations",
        "approvals",
        "actions",
        "verification_results",
        "audit_logs",
        "notifications",
        "agent_runs",
        "agent_tasks",
        "agent_tool_calls",
        "documents",
        "document_chunks",
    }
    assert set(tables.keys()) == expected_tables


def test_primary_keys_configured():
    """Verify each mapped table has a primary key named 'id'."""
    for table_name, table in Base.metadata.tables.items():
        assert len(table.primary_key.columns) >= 1, f"Table {table_name} missing PK"
        pk_names = [col.name for col in table.primary_key.columns]
        assert "id" in pk_names, f"Table {table_name} PK does not include 'id'"


def test_foreign_key_relationships():
    """Verify critical tenant-isolation foreign keys to organizations.id."""
    org_table = Base.metadata.tables["organizations"]
    assert "id" in org_table.c

    tenant_tables = [
        "users",
        "suppliers",
        "factories",
        "warehouses",
        "carriers",
        "products",
        "routes",
        "shipments",
        "inventory",
        "inventory_movements",
        "risks",
        "risk_assessments",
        "incidents",
        "twin_nodes",
        "twin_edges",
        "scenarios",
        "optimization_runs",
        "recommendations",
        "actions",
        "audit_logs",
        "notifications",
        "agent_runs",
        "documents",
    ]
    for tbl_name in tenant_tables:
        tbl = Base.metadata.tables[tbl_name]
        assert "org_id" in tbl.c, f"{tbl_name} missing org_id column"
        fks = [fk.target_fullname for fk in tbl.c.org_id.foreign_keys]
        assert "organizations.id" in fks, f"{tbl_name}.org_id FK does not target organizations.id"


def test_db_connection_function_safe():
    """Verify check_db_connection returns a tuple without throwing or mutating data."""
    is_connected, msg = check_db_connection()
    assert isinstance(is_connected, bool)
    assert isinstance(msg, str)
    # Check that secrets are not leaked in the message
    assert "password" not in msg.lower()
    assert "secret" not in msg.lower()
