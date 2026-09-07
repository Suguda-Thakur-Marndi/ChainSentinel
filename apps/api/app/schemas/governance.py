"""Pydantic schemas for governance, recommendations, approvals, actions, verification, audit trails, and notifications."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class RecommendationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_MODIFICATION = "REQUEST_MODIFICATION"


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TargetEntityType(str, Enum):
    SHIPMENT = "SHIPMENT"
    SUPPLIER = "SUPPLIER"
    FACILITY = "FACILITY"
    ROUTE = "ROUTE"
    INVENTORY = "INVENTORY"


class AuditActorType(str, Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"


class AuditStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class NotificationCategory(str, Enum):
    RISK_ALERT = "RISK_ALERT"
    SHIPMENT_DELAY = "SHIPMENT_DELAY"
    RECOMMENDATION = "RECOMMENDATION"
    SYSTEM = "SYSTEM"


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


# Recommendation
class RecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: Optional[str] = Field(None, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    rationale: Optional[str] = Field(None, max_length=1000)
    estimated_cost: Optional[float] = Field(None, ge=0.0)
    expected_benefit_json: dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: RecommendationStatus = RecommendationStatus.PENDING


class RecommendationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    rationale: Optional[str] = Field(None, max_length=1000)
    estimated_cost: Optional[float] = Field(None, ge=0.0)
    expected_benefit_json: Optional[dict[str, Any]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: Optional[RecommendationStatus] = None


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    incident_id: Optional[str] = None
    title: str
    rationale: Optional[str] = None
    estimated_cost: Optional[float] = None
    expected_benefit_json: dict[str, Any]
    confidence: Optional[float] = None
    status: str
    created_at: datetime


class RecommendationListResponse(PaginatedResponse[RecommendationResponse]):
    pass


# Approval (Human-in-the-loop sign-off)
class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(..., max_length=64)
    decision: ApprovalDecision = ApprovalDecision.APPROVE
    comments: Optional[str] = Field(None, max_length=1000)


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    recommendation_id: str
    decided_by_user_id: Optional[str] = None
    decision: str
    comments: Optional[str] = None
    decided_at: datetime


class ApprovalListResponse(PaginatedResponse[ApprovalResponse]):
    pass


# Action (Executed mitigation)
class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: Optional[str] = Field(None, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=100)
    target_entity_type: Optional[TargetEntityType] = None
    target_entity_id: Optional[str] = Field(None, max_length=64)
    execution_payload: dict[str, Any] = Field(default_factory=dict)


class ActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[ActionStatus] = None
    result_payload: Optional[dict[str, Any]] = None


class ActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    recommendation_id: Optional[str] = None
    action_type: str
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[str] = None
    status: str
    execution_payload: dict[str, Any]
    result_payload: dict[str, Any]
    executed_at: datetime


class ActionListResponse(PaginatedResponse[ActionResponse]):
    pass


# VerificationResult
class VerificationResultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., max_length=64)
    verified: bool = False
    risk_score_before: Optional[float] = None
    risk_score_after: Optional[float] = None
    observation_summary: Optional[str] = Field(None, max_length=1000)


class VerificationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_id: str
    verified: bool
    risk_score_before: Optional[float] = None
    risk_score_after: Optional[float] = None
    observation_summary: Optional[str] = None
    verified_at: datetime


class VerificationResultListResponse(PaginatedResponse[VerificationResultResponse]):
    pass


# AuditLog (Immutable Audit Trail)
class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    actor_type: str
    actor_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    status: str
    request_id: Optional[str] = None
    before_json: Optional[dict[str, Any]] = None
    after_json: Optional[dict[str, Any]] = None
    timestamp: datetime


class AuditLogListResponse(PaginatedResponse[AuditLogResponse]):
    pass


# Notification
class NotificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Optional[str] = Field(None, max_length=64)
    category: NotificationCategory = NotificationCategory.RISK_ALERT
    severity: NotificationSeverity = NotificationSeverity.INFO
    title: str = Field(..., min_length=1, max_length=255)
    summary: Optional[str] = Field(None, max_length=1000)
    is_read: bool = False


class NotificationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_read: bool = True


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    user_id: Optional[str] = None
    category: str
    severity: str
    title: str
    summary: Optional[str] = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(PaginatedResponse[NotificationResponse]):
    pass


class BatchNotificationReadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    updated_count: int
    message: str = "All notifications marked as read"

