"""Pydantic schemas for multi-agent autonomous investigation runs, tasks, and tool call audits."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class AgentWorkflowName(str, Enum):
    STANDARD_INVESTIGATION = "STANDARD_INVESTIGATION"
    RAPID_TRIAGE = "RAPID_TRIAGE"
    DEEP_SUPPLIER_ANALYSIS = "DEEP_SUPPLIER_ANALYSIS"
    LANE_DISRUPTION_ASSESSMENT = "LANE_DISRUPTION_ASSESSMENT"


class AgentStage(str, Enum):
    DETECTION = "DETECTION"
    RESEARCH = "RESEARCH"
    SIMULATION = "SIMULATION"
    SYNTHESIS = "SYNTHESIS"
    COMPLETE = "COMPLETE"


class AgentRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentTriggerType(str, Enum):
    SIGNAL_THRESHOLD = "SIGNAL_THRESHOLD"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"
    SCHEDULED_RUN = "SCHEDULED_RUN"


# AgentRun
class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: Optional[str] = Field(None, max_length=64)
    workflow_name: AgentWorkflowName = AgentWorkflowName.STANDARD_INVESTIGATION
    trigger_type: AgentTriggerType = AgentTriggerType.MANUAL_TRIGGER


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    incident_id: Optional[str] = None
    workflow_name: str
    current_stage: str
    status: str
    trigger_type: str
    confidence: Optional[float] = None
    outcome_summary: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class AgentRunListResponse(PaginatedResponse[AgentRunResponse]):
    pass


# AgentTask
class AgentTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_run_id: str
    agent_name: str
    status: str
    duration_ms: Optional[float] = None
    findings_json: dict[str, Any]
    confidence: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class AgentTaskListResponse(PaginatedResponse[AgentTaskResponse]):
    pass


# AgentToolCall
class AgentToolCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_task_id: str
    tool_name: str
    input_args: dict[str, Any]
    output_result: dict[str, Any]
    status: str
    duration_ms: Optional[float] = None
    executed_at: datetime


class AgentToolCallListResponse(PaginatedResponse[AgentToolCallResponse]):
    pass
