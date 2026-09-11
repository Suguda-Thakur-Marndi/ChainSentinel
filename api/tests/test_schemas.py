"""Unit tests validating Pydantic schemas, validation rules, pagination, and error contracts for RiskWise 2.0 Core API Contract."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    PaginatedResponse,
    PaginationMeta,
    PaginationParams,
    SortOrder,
)
from app.schemas.tenancy import (
    OrgPlan,
    OrganizationResponse,
    OrganizationUpdate,
    UserCreate,
    UserResponse,
    UserRole,
    UserUpdate,
)
from app.schemas.network import (
    CarrierCreate,
    CarrierResponse,
    CriticalityTier,
    FactoryCreate,
    FactoryResponse,
    FacilityStatus,
    PortResponse,
    ProductCreate,
    ProductResponse,
    RouteCreate,
    RouteResponse,
    SupplierCreate,
    SupplierResponse,
    SupplierSiteCreate,
    SupplierSiteResponse,
    SupplierUpdate,
    TransportMode,
    WarehouseCreate,
    WarehouseResponse,
)
from app.schemas.logistics import (
    DataProvenance,
    InventoryCreate,
    InventoryMovementCreate,
    InventoryMovementType,
    InventoryResponse,
    ShipmentCreate,
    ShipmentEventCreate,
    ShipmentResponse,
    ShipmentStatus,
    ShipmentUpdate,
)
from app.schemas.risk import (
    AssessorType,
    IncidentCreate,
    IncidentResponse,
    IncidentStatus,
    IncidentUpdate,
    RiskAssessmentCreate,
    RiskAssessmentResponse,
    RiskCreate,
    RiskFactorCreate,
    RiskFactorResponse,
    RiskResponse,
    RiskSeverity,
    RiskTrend,
    RiskUpdate,
)
from app.schemas.digital_twin import (
    TwinEdgeCreate,
    TwinEdgeResponse,
    TwinEdgeType,
    TwinNodeCreate,
    TwinNodeResponse,
    TwinNodeType,
)
from app.schemas.simulation import (
    OptimizationObjective,
    OptimizationRunCreate,
    OptimizationRunResponse,
    ScenarioCreate,
    ScenarioResponse,
    SimulationCreate,
    SimulationMode,
    SimulationResponse,
    SimulationStatus,
)
from app.schemas.governance import (
    ActionCreate,
    ActionResponse,
    ApprovalCreate,
    ApprovalDecision,
    ApprovalResponse,
    AuditActorType,
    AuditLogResponse,
    AuditStatus,
    NotificationCategory,
    NotificationResponse,
    NotificationSeverity,
    NotificationUpdate,
    RecommendationCreate,
    RecommendationResponse,
    RecommendationStatus,
    TargetEntityType,
    VerificationResultResponse,
)
from app.schemas.agents import (
    AgentRunCreate,
    AgentRunResponse,
    AgentRunStatus,
    AgentStage,
    AgentTaskResponse,
    AgentToolCallResponse,
    AgentTriggerType,
    AgentWorkflowName,
)
from app.schemas.knowledge import (
    DocumentChunkResponse,
    DocumentCreate,
    DocumentResponse,
    DocumentStatus,
)


# ==========================================
# 1. Common Schemas (Pagination, Error, Sort)
# ==========================================

def test_pagination_params_valid():
    p = PaginationParams(page=2, limit=50)
    assert p.page == 2
    assert p.limit == 50


def test_pagination_params_invalid_page():
    with pytest.raises(ValidationError):
        PaginationParams(page=0, limit=20)


def test_pagination_params_invalid_limit():
    with pytest.raises(ValidationError):
        PaginationParams(page=1, limit=101)


def test_pagination_meta_and_paginated_response():
    meta = PaginationMeta(total=45, page=1, limit=20, pages=3)
    response = PaginatedResponse[str](items=["item1", "item2"], pagination=meta)
    assert response.pagination.total == 45
    assert len(response.items) == 2


def test_error_response_envelope():
    detail = ErrorDetail(code="NOT_FOUND", message="Supplier not found", details={"id": "sup-123"})
    err = ErrorResponse(error=detail)
    assert err.error.code == "NOT_FOUND"
    assert err.error.message == "Supplier not found"
    assert err.error.details == {"id": "sup-123"}


# ==========================================
# 2. Tenancy Schemas (Organization, User)
# ==========================================

def test_user_create_and_validation():
    user = UserCreate(email="analyst@acme.com", full_name="Alice Analyst", role=UserRole.ANALYST)
    assert user.email == "analyst@acme.com"
    assert user.role == UserRole.ANALYST

    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", role=UserRole.ANALYST)


def test_server_controlled_field_rejection():
    # Extra fields like 'id' or 'org_id' in Create schema must be forbidden
    with pytest.raises(ValidationError):
        SupplierCreate(name="Acme", id="custom_id")


# ==========================================
# 3. Network Schemas
# ==========================================

def test_supplier_create_and_response():
    now = datetime.now(timezone.utc)
    create_req = SupplierCreate(
        name="Apex Microelectronics",
        code="APX-01",
        country="TW",
        tier=CriticalityTier.CRITICAL,
        criticality=CriticalityTier.HIGH,
        reliability_score=94.5,
        lead_time_days=45.0,
    )
    assert create_req.name == "Apex Microelectronics"
    assert create_req.tier == CriticalityTier.CRITICAL

    # Test Response schema
    resp = SupplierResponse(
        id="sup-1",
        org_id="org-1",
        name=create_req.name,
        code=create_req.code,
        country=create_req.country,
        tier=create_req.tier.value,
        criticality=create_req.criticality.value,
        reliability_score=create_req.reliability_score,
        created_at=now,
    )
    assert resp.id == "sup-1"
    assert resp.tier == "CRITICAL"


def test_port_response_reference_data():
    now = datetime.now(timezone.utc)
    port = PortResponse(
        id="port-sgsin",
        code="SGSIN",
        name="Port of Singapore",
        country="SG",
        port_type="SEA",
        latitude=1.264,
        longitude=103.84,
        congestion_score=42.0,
        average_wait_hours=18.5,
        created_at=now,
    )
    assert port.code == "SGSIN"
    assert port.port_type == "SEA"


# ==========================================
# 4. Logistics Schemas
# ==========================================

def test_shipment_create_and_validation():
    now = datetime.now(timezone.utc)
    shipment = ShipmentCreate(
        tracking_number="TRK-987654",
        route_id="route-1",
        carrier_id="carrier-1",
        origin="Shenzhen, CN",
        destination="Long Beach, US",
        status=ShipmentStatus.IN_TRANSIT,
        current_lat=22.54,
        current_lng=114.05,
        eta=now,
        eta_confidence=0.88,
        data_provenance=DataProvenance.REAL,
    )
    assert shipment.tracking_number == "TRK-987654"
    assert shipment.status == ShipmentStatus.IN_TRANSIT
    assert shipment.data_provenance == DataProvenance.REAL


def test_shipment_invalid_coordinates():
    with pytest.raises(ValidationError):
        ShipmentCreate(tracking_number="TRK-1", current_lat=95.0)  # > 90


# ==========================================
# 5. Risk Schemas
# ==========================================

def test_risk_create_and_update():
    risk = RiskCreate(
        title="Typhoon approaching Kaohsiung port",
        risk_type="CLIMATE",
        severity=RiskSeverity.HIGH,
        location="Taiwan Strait",
        probability=0.75,
        impact=85.0,
        risk_score=78.2,
        trend=RiskTrend.INCREASING,
    )
    assert risk.severity == RiskSeverity.HIGH
    assert risk.trend == RiskTrend.INCREASING


def test_incident_create_and_status():
    incident = IncidentCreate(
        title="Red Sea transit halt due to regional conflict",
        status=IncidentStatus.DETECTED,
        severity=RiskSeverity.CRITICAL,
        location="Bab-el-Mandeb Strait",
        affected_assets=["shipment-101", "shipment-102"],
    )
    assert incident.status == IncidentStatus.DETECTED
    assert len(incident.affected_assets) == 2


# ==========================================
# 6. Governance Schemas
# ==========================================

def test_governance_approval_cycle():
    rec = RecommendationCreate(
        title="Reroute container vessel via Cape of Good Hope",
        rationale="Avoid high-risk corridor and prevent projected 14-day delay",
        estimated_cost=45000.0,
        expected_benefit_json={"delay_reduction_days": 10.5, "loss_avoidance_usd": 350000.0},
        confidence=0.92,
    )
    assert rec.status == RecommendationStatus.PENDING

    appr = ApprovalCreate(
        recommendation_id="rec-001",
        decision=ApprovalDecision.APPROVE,
        comments="Approved by Ops Director per contingency SOP-22",
    )
    assert appr.decision == ApprovalDecision.APPROVE


# ==========================================
# 7. Multi-Agent Schemas
# ==========================================

def test_agent_run_create():
    run = AgentRunCreate(
        incident_id="inc-500",
        workflow_name=AgentWorkflowName.STANDARD_INVESTIGATION,
        trigger_type=AgentTriggerType.SIGNAL_THRESHOLD,
    )
    assert run.workflow_name == AgentWorkflowName.STANDARD_INVESTIGATION
    assert run.trigger_type == AgentTriggerType.SIGNAL_THRESHOLD


# ==========================================
# 8. Digital Twin & Simulation Schemas
# ==========================================

def test_digital_twin_and_simulation():
    node = TwinNodeCreate(
        node_type=TwinNodeType.FACTORY,
        label="Penang Assembly Plant 1",
        latitude=5.4164,
        longitude=100.3327,
        health_score=92.0,
    )
    assert node.node_type == TwinNodeType.FACTORY

    edge = TwinEdgeCreate(
        from_node_id="node-1",
        to_node_id="node-2",
        edge_type=TwinEdgeType.FLOW,
        flow_capacity=5000.0,
        current_flow=4200.0,
        risk_score=15.0,
    )
    assert edge.edge_type == TwinEdgeType.FLOW

    scen = ScenarioCreate(
        name="Taiwan Strait Closure 30 Days",
        description="Simulate complete disruption of sea lanes in Taiwan Strait",
        variables_json={"lane_blocked": True, "lead_time_multiplier": 2.5},
    )
    assert scen.name == "Taiwan Strait Closure 30 Days"
