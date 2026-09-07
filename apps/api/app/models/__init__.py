"""SQLAlchemy database models package.

Exposes and registers all RiskWise 2.0 domain entities with Base.metadata.
"""
from app.db.base import Base, generate_uuid

# Tenancy & Identity
from app.models.tenancy import Organization, User

# Supply Chain Network
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

# Logistics & Telemetry
from app.models.logistics import (
    Inventory,
    InventoryMovement,
    Shipment,
    ShipmentEvent,
)

# Risk Intelligence & Incidents
from app.models.risk import (
    Incident,
    Risk,
    RiskAssessment,
    RiskFactor,
)

# Digital Twin Graph
from app.models.digital_twin import TwinEdge, TwinNode

# Simulation & Prescriptive Optimization
from app.models.simulation import OptimizationRun, Scenario, Simulation

# Governance, Approvals & Auditing
from app.models.governance import (
    Action,
    Approval,
    AuditLog,
    Notification,
    Recommendation,
    VerificationResult,
)

# AI Agents & Tool Execution
from app.models.agents import AgentRun, AgentTask, AgentToolCall

# Knowledge Base & RAG Corpus
from app.models.knowledge import Document, DocumentChunk

__all__ = [
    "Base",
    "generate_uuid",
    # Tenancy
    "Organization",
    "User",
    # Network
    "Supplier",
    "SupplierSite",
    "Factory",
    "Warehouse",
    "Port",
    "Carrier",
    "Product",
    "Route",
    # Logistics
    "Shipment",
    "ShipmentEvent",
    "Inventory",
    "InventoryMovement",
    # Risk
    "Risk",
    "RiskFactor",
    "RiskAssessment",
    "Incident",
    # Digital Twin
    "TwinNode",
    "TwinEdge",
    # Simulation
    "Scenario",
    "Simulation",
    "OptimizationRun",
    # Governance
    "Recommendation",
    "Approval",
    "Action",
    "VerificationResult",
    "AuditLog",
    "Notification",
    # Agents
    "AgentRun",
    "AgentTask",
    "AgentToolCall",
    # Knowledge
    "Document",
    "DocumentChunk",
]
