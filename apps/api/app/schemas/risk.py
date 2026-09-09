"""Pydantic schemas for risk intelligence, risk factors, assessments, and incidents."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.normalization.contract import EntityType, NormalizedRiskSignal
from app.schemas.common import PaginatedResponse


# Enums
class RiskSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskTrend(str, Enum):
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"


class AssessorType(str, Enum):
    AI_AGENT = "AI_AGENT"
    HUMAN_ANALYST = "HUMAN_ANALYST"
    DETERMINISTIC_ENGINE = "DETERMINISTIC_ENGINE"


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# Risk
class RiskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    risk_type: Optional[str] = Field(None, max_length=50)
    severity: RiskSeverity = RiskSeverity.MEDIUM
    location: Optional[str] = Field(None, max_length=255)
    probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    impact: Optional[float] = Field(None, ge=0.0, le=100.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    trend: RiskTrend = RiskTrend.STABLE
    source: Optional[str] = Field(None, max_length=100)


class RiskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    risk_type: Optional[str] = Field(None, max_length=50)
    severity: Optional[RiskSeverity] = None
    location: Optional[str] = Field(None, max_length=255)
    probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    impact: Optional[float] = Field(None, ge=0.0, le=100.0)
    risk_score: Optional[float] = Field(None, ge=0.0, le=100.0)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    trend: Optional[RiskTrend] = None
    source: Optional[str] = Field(None, max_length=100)


class RiskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    title: str
    risk_type: Optional[str] = None
    severity: str
    location: Optional[str] = None
    probability: Optional[float] = None
    impact: Optional[float] = None
    risk_score: Optional[float] = None
    confidence: Optional[float] = None
    trend: str
    source: Optional[str] = None
    detected_at: datetime
    updated_at: Optional[datetime] = None


class RiskListResponse(PaginatedResponse[RiskResponse]):
    pass


# RiskFactor
class RiskFactorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    weight: float = Field(default=1.0, ge=0.0)
    score: float = Field(default=50.0, ge=0.0, le=100.0)
    evidence_json: dict[str, Any] = Field(default_factory=dict)


class RiskFactorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    weight: Optional[float] = Field(None, ge=0.0)
    score: Optional[float] = Field(None, ge=0.0, le=100.0)
    evidence_json: Optional[dict[str, Any]] = None


class RiskFactorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    risk_id: str
    name: str
    category: Optional[str] = None
    weight: float
    score: float
    evidence_json: dict[str, Any]
    created_at: datetime


class RiskFactorListResponse(PaginatedResponse[RiskFactorResponse]):
    pass


# RiskAssessment (Generated Evaluation)
class RiskAssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(..., max_length=64)
    assessor_type: AssessorType = AssessorType.AI_AGENT
    assessor_id: Optional[str] = Field(None, max_length=64)
    methodology: Optional[str] = Field(None, max_length=100)
    findings: dict[str, Any] = Field(default_factory=dict)
    score: float = Field(default=50.0, ge=0.0, le=100.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class RiskAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    risk_id: str
    assessor_type: str
    assessor_id: Optional[str] = None
    methodology: Optional[str] = None
    findings: dict[str, Any]
    score: float
    confidence: float
    created_at: datetime


class RiskAssessmentListResponse(PaginatedResponse[RiskAssessmentResponse]):
    pass


class RiskEvaluationRequest(BaseModel):
    """Client request for deterministic risk evaluation over normalized signals."""
    model_config = ConfigDict(extra="forbid")

    scope: str = Field(default="GLOBAL", max_length=50, description="Evaluation scope (GLOBAL, SHIPMENT, SUPPLIER, PORT, ROUTE)")
    scope_entity_id: Optional[str] = Field(None, max_length=64, description="Target entity ID if scope is specific entity")
    scope_entity_type: Optional[EntityType] = Field(None, description="Target entity type")
    risk_id: Optional[str] = Field(None, max_length=64, description="Optional associated Risk entity ID")
    signals: list[NormalizedRiskSignal] = Field(default_factory=list, description="List of Phase 6 NormalizedRiskSignals to evaluate")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Operational metadata or correlation details")


class RiskAssessmentDetailResponse(BaseModel):
    """Comprehensive detail response representing completed RiskAssessment with full traceability."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    assessment_id: str
    org_id: Optional[str] = None
    risk_id: str
    assessor_type: str
    assessor_id: Optional[str] = None
    methodology: Optional[str] = None
    score: float
    risk_level: Optional[str] = None
    probability: Optional[float] = None  # Always None in Phase 7
    impact: Optional[float] = None       # Always None in Phase 7
    confidence: float
    primary_factor_id: Optional[str] = None
    primary_driver: Optional[dict[str, Any]] = None
    factor_contributions: list[dict[str, Any]] = Field(default_factory=list)
    factors: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_summary: Optional[dict[str, Any]] = None
    limitations: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    source_signals: list[str] = Field(default_factory=list)
    explanation: Optional[dict[str, Any]] = None
    fingerprint: Optional[str] = None
    findings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class FactorChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    factor_id: str
    factor_type: str
    name: str
    previous_severity: Optional[str] = None
    current_severity: Optional[str] = None
    severity_changed: bool = False
    previous_confidence: Optional[float] = None
    current_confidence: Optional[float] = None
    confidence_delta: float = 0.0
    previous_contribution: Optional[float] = None
    current_contribution: Optional[float] = None
    contribution_delta: float = 0.0
    status: str


class EvidenceChangesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    previous_evidence_count: int = 0
    current_evidence_count: int = 0
    evidence_count_delta: int = 0
    previous_source_count: int = 0
    current_source_count: int = 0
    source_count_delta: int = 0
    previous_corroborating_count: int = 0
    current_corroborating_count: int = 0
    corroborating_count_delta: int = 0
    details: list[str] = Field(default_factory=list)


class SourceChangesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    previous_independent_sources: int = 0
    current_independent_sources: int = 0
    independent_sources_delta: int = 0
    previous_real_sources: int = 0
    current_real_sources: int = 0
    real_sources_delta: int = 0
    previous_estimated_sources: int = 0
    current_estimated_sources: int = 0
    estimated_sources_delta: int = 0
    previous_simulated_sources: int = 0
    current_simulated_sources: int = 0
    simulated_sources_delta: int = 0
    added_providers: list[str] = Field(default_factory=list)
    removed_providers: list[str] = Field(default_factory=list)


class ConflictChangesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str = "NO_CHANGE"
    previous_conflict_count: int = 0
    current_conflict_count: int = 0
    conflict_count_delta: int = 0
    details: list[str] = Field(default_factory=list)


class QualityChangesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str = "UNCHANGED"
    previous_valid_count: int = 0
    current_valid_count: int = 0
    previous_partial_count: int = 0
    current_partial_count: int = 0
    new_limitations: list[str] = Field(default_factory=list)
    resolved_limitations: list[str] = Field(default_factory=list)


class AssessmentComparisonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    previous_assessment_id: Optional[str] = None
    current_assessment_id: str
    previous_evaluated_at: Optional[datetime] = None
    current_evaluated_at: datetime
    previous_score: Optional[float] = None
    current_score: float
    score_delta: float = 0.0
    previous_risk_level: Optional[str] = None
    current_risk_level: str
    risk_level_changed: bool = False
    previous_primary_factor_id: Optional[str] = None
    current_primary_factor_id: Optional[str] = None
    primary_driver_change_status: str = "SAME"
    previous_primary_driver: Optional[dict[str, Any]] = None
    current_primary_driver: Optional[dict[str, Any]] = None
    direction: str = "STABLE"
    factor_changes: list[FactorChangeResponse] = Field(default_factory=list)
    evidence_changes: EvidenceChangesResponse = Field(default_factory=EvidenceChangesResponse)
    source_changes: SourceChangesResponse = Field(default_factory=SourceChangesResponse)
    conflict_changes: ConflictChangesResponse = Field(default_factory=ConflictChangesResponse)
    quality_changes: QualityChangesResponse = Field(default_factory=QualityChangesResponse)
    explanation: str = ""


class RiskHistorySummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: str
    entity_scope: str = "GLOBAL"
    entity_id: Optional[str] = None
    assessment_count: int = 0
    first_assessment_id: Optional[str] = None
    latest_assessment_id: Optional[str] = None
    first_score: Optional[float] = None
    latest_score: Optional[float] = None
    score_delta: Optional[float] = None
    minimum_score: Optional[float] = None
    maximum_score: Optional[float] = None
    average_score: Optional[float] = None
    first_risk_level: Optional[str] = None
    latest_risk_level: Optional[str] = None
    trend: str = "INSUFFICIENT_HISTORY"
    primary_driver: Optional[dict[str, Any]] = None
    driver_changes_count: int = 0
    conflict_count: int = 0
    source_summary: Optional[dict[str, Any]] = None
    history_start: Optional[datetime] = None
    history_end: Optional[datetime] = None
    assessments: list[dict[str, Any]] = Field(default_factory=list)
    transitions: list[AssessmentComparisonResponse] = Field(default_factory=list)
    overall_comparison: Optional[AssessmentComparisonResponse] = None


# Incident
class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: Optional[str] = Field(None, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    status: IncidentStatus = IncidentStatus.DETECTED
    severity: RiskSeverity = RiskSeverity.MEDIUM
    location: Optional[str] = Field(None, max_length=255)
    source: Optional[str] = Field(None, max_length=100)
    affected_assets: list[Any] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_id: Optional[str] = Field(None, max_length=64)
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[IncidentStatus] = None
    severity: Optional[RiskSeverity] = None
    location: Optional[str] = Field(None, max_length=255)
    source: Optional[str] = Field(None, max_length=100)
    affected_assets: Optional[list[Any]] = None
    resolved_at: Optional[datetime] = None


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    risk_id: Optional[str] = None
    title: str
    status: str
    severity: str
    location: Optional[str] = None
    source: Optional[str] = None
    affected_assets: list[Any]
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class IncidentListResponse(PaginatedResponse[IncidentResponse]):
    pass
