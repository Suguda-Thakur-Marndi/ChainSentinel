"""Pydantic schemas for risk intelligence, risk factors, assessments, and incidents."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

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
