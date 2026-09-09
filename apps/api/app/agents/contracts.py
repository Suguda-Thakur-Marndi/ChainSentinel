"""Core strongly typed domain contracts for RiskWise LangGraph multi-agent architecture.

Defines AgentState (AgentGraphState), AgentExecutionContext, AgentLifecycleStatus,
AgentStage, AgentFinding, AgentConflict, AgentLimitation, RouteEvent, AgentErrorState,
NodeContract, ToolDefinition, RouteDecision, and bound evidence/risk references.
Strictly prohibits chain-of-thought, private reasoning, and cleartext credentials.
Enforces immutable tenant identity, authoritative field ownership, and fail-closed validation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from typing_extensions import TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.errors import (
    AgentApprovalBoundaryViolationError,
    AgentStateOwnershipViolationError,
    AgentStateSizeLimitError,
    AgentTenantIsolationError,
    AgentValidationError,
)

# Prohibited keys in any state dictionary: chain-of-thought, hidden monologue, credentials
FORBIDDEN_STATE_KEY_PATTERNS = [
    re.compile(r"^chain_of_thought$", re.IGNORECASE),
    re.compile(r"^private_reasoning$", re.IGNORECASE),
    re.compile(r"^hidden_reasoning$", re.IGNORECASE),
    re.compile(r"^internal_monologue$", re.IGNORECASE),
    re.compile(r"password|secret|token|api_key|credentials|authorization", re.IGNORECASE),
]


class AgentLifecycleStatus(str, Enum):
    """Lifecycle status representing the operational state of an agent graph run."""

    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    MAX_STEPS_REACHED = "MAX_STEPS_REACHED"


class AgentStage(str, Enum):
    """Architectural stage within the orchestrated multi-agent graph pipeline."""

    INITIALIZATION = "INITIALIZATION"
    RESEARCH = "RESEARCH"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    PREDICTION = "PREDICTION"
    SCENARIO_ANALYSIS = "SCENARIO_ANALYSIS"
    DECISION = "DECISION"
    APPROVAL = "APPROVAL"
    ACTION = "ACTION"
    VERIFICATION = "VERIFICATION"
    TERMINATION = "TERMINATION"


class ToolSideEffectType(str, Enum):
    """Classification of tool execution impact on system or external resources."""

    READ_ONLY = "READ_ONLY"
    SIDE_EFFECTING = "SIDE_EFFECTING"


class ConflictResolutionStatus(str, Enum):
    """Resolution lifecycle status for detected evidence or signal conflicts."""

    UNRESOLVED = "UNRESOLVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class LimitationCategory(str, Enum):
    """Classification of operational limitations and contextual gaps."""

    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    STALE_DATA = "STALE_DATA"
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    UNAVAILABLE_PROVIDER = "UNAVAILABLE_PROVIDER"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    INCOMPLETE_CORRELATION = "INCOMPLETE_CORRELATION"
    STATE_SIZE_LIMIT = "STATE_SIZE_LIMIT"
    UNSUPPORTED_MAPPING = "UNSUPPORTED_MAPPING"
    UNSAFE_SOURCE = "UNSAFE_SOURCE"
    TENANT_BOUNDARY_VIOLATION = "TENANT_BOUNDARY_VIOLATION"


def validate_no_forbidden_keys(data: Any, path: str = "root") -> None:
    """Recursively ensure no chain-of-thought or credential keys exist in any state payload."""
    if isinstance(data, dict):
        for k, v in data.items():
            key_str = str(k)
            for pattern in FORBIDDEN_STATE_KEY_PATTERNS:
                if pattern.search(key_str):
                    if "chain_of_thought" in key_str.lower() or "reasoning" in key_str.lower() or "monologue" in key_str.lower():
                        raise AgentValidationError(
                            f"Prohibited chain-of-thought or reasoning key '{k}' detected at '{path}.{k}'."
                        )
                    else:
                        raise AgentValidationError(
                            f"Prohibited credential or secret key '{k}' detected at '{path}.{k}'."
                        )
            validate_no_forbidden_keys(v, f"{path}.{k}")
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            validate_no_forbidden_keys(item, f"{path}[{idx}]")


SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"bearer\s+[a-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"password\s*[:=]?\s*['\"]?[^\s'\"]+['\"]?", re.IGNORECASE),
    re.compile(r"api_key\s*[:=]?\s*['\"]?[^\s'\"]+['\"]?", re.IGNORECASE),
    re.compile(r"secret\s*[:=]?\s*['\"]?[^\s'\"]+['\"]?", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9_\-]{10,}", re.IGNORECASE),
]

FORBIDDEN_REASONING_PATTERNS = [
    re.compile(r"chain_of_thought", re.IGNORECASE),
    re.compile(r"private_reasoning", re.IGNORECASE),
    re.compile(r"hidden_reasoning", re.IGNORECASE),
    re.compile(r"internal_monologue", re.IGNORECASE),
]


def validate_no_reasoning_content(text: str, field_name: str = "field") -> None:
    """Ensure no chain-of-thought or internal monologue reasoning is embedded in text values."""
    if not text or not isinstance(text, str):
        return
    for pattern in FORBIDDEN_REASONING_PATTERNS:
        if pattern.search(text):
            raise AgentValidationError(
                f"Prohibited chain-of-thought or reasoning content detected in '{field_name}'."
            )


def validate_no_sensitive_values(text: str, field_name: str = "field") -> None:
    """Ensure no raw passwords, bearer tokens, or API keys are embedded in text values."""
    if not text or not isinstance(text, str):
        return
    for pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            raise AgentValidationError(
                f"Prohibited sensitive credential or token pattern detected in '{field_name}'."
            )


def validate_json_serializable_primitives(data: Any, path: str = "root") -> None:
    """Ensure data only contains standard JSON-serializable primitives."""
    if data is None or isinstance(data, (str, int, float, bool)):
        return
    elif isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(k, str):
                raise AgentValidationError(f"Dictionary key at '{path}' must be string, got {type(k).__name__}.")
            validate_json_serializable_primitives(v, f"{path}.{k}")
    elif isinstance(data, (list, tuple)):
        for idx, item in enumerate(data):
            validate_json_serializable_primitives(item, f"{path}[{idx}]")
    else:
        raise AgentValidationError(
            f"Unsupported non-serializable object of type '{type(data).__name__}' at '{path}'."
        )



class RAGEvidenceReference(BaseModel):
    """Verified reference binding an authoritative Phase 8 RAGEvidenceBundle to agent state."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    bundle_fingerprint: str = Field(..., min_length=1, max_length=64)
    total_evidence_units: int = Field(default=0, ge=0)
    grounding_status: str = Field(default="GROUNDED")


class RiskAssessmentReference(BaseModel):
    """Verified reference binding an authoritative Phase 7 RiskAssessment to agent state."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    assessment_fingerprint: str = Field(..., min_length=1, max_length=64)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    risk_level: Optional[str] = None
    factor_count: int = Field(default=0, ge=0)


class RouteEvent(BaseModel):
    """Deterministic audit event recording a single graph node routing transition."""

    model_config = ConfigDict(extra="forbid")

    from_node: str = Field(..., min_length=1, max_length=64)
    to_node: str = Field(..., min_length=1, max_length=64)
    reason_code: str = Field(..., min_length=1, max_length=100)
    step_number: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("reason_code", mode="after")
    @classmethod
    def validate_reason_safety(cls, v: str) -> str:
        validate_no_forbidden_keys({"reason": v}, "RouteEvent")
        return v


class AgentFinding(BaseModel):
    """Strongly typed factual finding produced by an authorized agent node.

    Every factual finding must be traceable to evidence IDs when evidence exists.
    Private chain-of-thought and fabricated evidence IDs are strictly forbidden.
    """

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1, max_length=64)
    category: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=256)
    summary: str = Field(..., min_length=1, max_length=4096)
    severity: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_ids: List[str] = Field(default_factory=list)
    source_references: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    created_by_node: str = Field(..., min_length=1, max_length=64)

    @field_validator("title", "summary", mode="after")
    @classmethod
    def validate_no_secrets_or_cot(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"AgentFinding.{info.field_name}")
        validate_no_sensitive_values(v, f"AgentFinding.{info.field_name}")
        return v


class AgentConflict(BaseModel):
    """Strongly typed conflict identification across evidence, signals, or agent findings.

    Conflicts must never be silently resolved or discarded without explicit status tracking.
    """

    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(..., min_length=1, max_length=64)
    category: str = Field(..., min_length=1, max_length=64)
    affected_references: List[str] = Field(default_factory=list)
    source_evidence_ids: List[str] = Field(default_factory=list)
    description: str = Field(..., min_length=1, max_length=4096)
    severity: Optional[str] = None
    resolution_status: ConflictResolutionStatus = Field(default=ConflictResolutionStatus.UNRESOLVED)

    @field_validator("description", mode="after")
    @classmethod
    def validate_description_safety(cls, v: str) -> str:
        validate_no_forbidden_keys({"description": v}, "AgentConflict.description")
        validate_no_sensitive_values(v, "AgentConflict.description")
        validate_no_reasoning_content(v, "AgentConflict.description")
        return v


class AgentLimitation(BaseModel):
    """Explicit operational limitation or data gap encountered during execution.

    Limitations must survive downstream transitions to prevent unwarranted conclusions.
    """

    model_config = ConfigDict(extra="forbid")

    limitation_id: str = Field(..., min_length=1, max_length=64)
    category: LimitationCategory
    description: str = Field(..., min_length=1, max_length=4096)
    affected_nodes: List[str] = Field(default_factory=list)
    mitigation_or_impact: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("description", mode="after")
    @classmethod
    def validate_desc_safety(cls, v: str) -> str:
        validate_no_forbidden_keys({"description": v}, "AgentLimitation.description")
        validate_no_sensitive_values(v, "AgentLimitation.description")
        validate_no_reasoning_content(v, "AgentLimitation.description")
        return v


class AgentErrorState(BaseModel):
    """Structured error record capturing node-level failure without leaking secrets."""

    model_config = ConfigDict(extra="forbid")

    error_code: str = Field(..., min_length=1, max_length=64)
    category: str = Field(default="EXECUTION", min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=4096)
    retryable: bool = False
    node: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    correlation_id: Optional[str] = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_information: Dict[str, str] = Field(default_factory=dict)

    @field_validator("message", mode="after")
    @classmethod
    def scrub_message(cls, v: str) -> str:
        validate_no_forbidden_keys({"message": v}, "AgentErrorState.message")
        validate_no_sensitive_values(v, "AgentErrorState.message")
        return v



class AgentExecutionContext(BaseModel):
    """Immutable execution context encapsulating runtime identity, tenancy, and limits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: str = Field(..., min_length=1, max_length=64)
    actor_id: str = Field(..., min_length=1, max_length=64)
    request_id: str = Field(..., min_length=1, max_length=64)
    correlation_id: str = Field(..., min_length=1, max_length=64)
    trace_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(default="SYSTEM", min_length=1)
    roles: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    allowed_stages: List[AgentStage] = Field(default_factory=lambda: list(AgentStage))
    is_admin: bool = False
    feature_flags: Dict[str, bool] = Field(default_factory=dict)
    max_steps: int = Field(default=25, ge=1, le=100)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: float = Field(default=120.0, ge=1.0, le=600.0)
    max_state_size_bytes: int = Field(default=1_000_000, ge=10_000)

    @field_validator("organization_id", "actor_id", "request_id", "correlation_id", "trace_id", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise AgentTenantIsolationError(
                f"Context field '{info.field_name}' must be a non-empty string."
            )
        return v.strip()


# Definition of identity fields that nodes are strictly forbidden from mutating
IDENTITY_FIELDS: frozenset[str] = frozenset({
    "run_id",
    "organization_id",
    "actor_id",
    "request_id",
    "correlation_id",
    "trace_id",
    "started_at",
    "state_schema_version",
})

# Definition of authoritative field ownership across architectural stages
AUTHORITATIVE_FIELD_OWNERS: Dict[str, Set[AgentStage]] = {
    "evidence_bundle": {AgentStage.RESEARCH},
    "evidence_bundle_id": {AgentStage.RESEARCH},
    "evidence_references": {AgentStage.RESEARCH},
    "citation_references": {AgentStage.RESEARCH},
    "risk_assessment": {AgentStage.RISK_ASSESSMENT},
    "risk_assessment_id": {AgentStage.RISK_ASSESSMENT},
    "risk_assessment_reference": {AgentStage.RISK_ASSESSMENT},
    "risk_alert_references": {AgentStage.RISK_ASSESSMENT},
    "recommendation_references": {AgentStage.DECISION},
    "requires_human_approval": {AgentStage.APPROVAL, AgentStage.INITIALIZATION},
    "approval_reference": {AgentStage.APPROVAL},
    "approval_status": {AgentStage.APPROVAL},
    "side_effect_allowed": {AgentStage.APPROVAL},
    "completed_at": {AgentStage.TERMINATION},
    "termination_reason": {AgentStage.TERMINATION},
}


class AgentGraphState(BaseModel):
    """Strongly typed LangGraph execution state for RiskWise agent orchestration.

    Contains operational identity, lifecycle progress, evidence references,
    structured findings, and error telemetry. Forbids hidden reasoning and secrets.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # A. Operational Identity (Read-only / Immutable)
    run_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    actor_id: str = Field(..., min_length=1, max_length=64)

    # B. Correlation
    request_id: str = Field(..., min_length=1, max_length=64)
    correlation_id: str = Field(..., min_length=1, max_length=64)
    trace_id: str = Field(..., min_length=1, max_length=64)

    # C. Objective
    objective: str = Field(..., min_length=1, max_length=4096)
    input_references: Dict[str, Any] = Field(default_factory=dict)
    input_reference: Optional[str] = None
    requested_operation: Optional[str] = None

    # D. Lifecycle & Stage
    current_stage: AgentStage = Field(default=AgentStage.INITIALIZATION)
    current_node: Optional[str] = None
    status: AgentLifecycleStatus = Field(default=AgentLifecycleStatus.INITIALIZING)
    step_count: int = Field(default=0, ge=0)

    # E. Hardened Subsystem Evidence Bindings & References
    evidence_bundle_id: Optional[str] = None
    evidence_references: List[str] = Field(default_factory=list)
    citation_references: List[str] = Field(default_factory=list)
    evidence_bundle: Optional[RAGEvidenceReference] = None

    # F. Risk References
    risk_assessment_id: Optional[str] = None
    risk_assessment_reference: Optional[RiskAssessmentReference] = None
    risk_assessment: Optional[RiskAssessmentReference] = None
    risk_alert_references: List[str] = Field(default_factory=list)
    recommendation_references: List[str] = Field(default_factory=list)

    # G. Structured Findings, Limitations & Conflicts
    findings: Dict[str, Any] = Field(default_factory=dict)
    structured_findings: List[AgentFinding] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    limitations: List[AgentLimitation] = Field(default_factory=list)
    conflicts: List[AgentConflict] = Field(default_factory=list)

    # H. Routing & Route History
    selected_route: Optional[str] = None
    next_node: Optional[str] = None
    route_reason: Optional[str] = None
    route_history: List[RouteEvent] = Field(default_factory=list)

    # I. Reliability, Limits, Errors & Recovery
    retry_count: int = Field(default=0, ge=0)
    last_error: Optional[AgentErrorState] = None
    error_category: Optional[str] = None
    recovery_status: Optional[str] = None
    errors: List[Dict[str, Any]] = Field(default_factory=list)

    # J. Governance & Approval
    requires_human_approval: bool = False
    approval_reference: Optional[str] = None
    side_effect_allowed: bool = False
    approval_status: Optional[str] = None

    # K. Termination & Telemetry
    termination_reason: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    state_schema_version: str = Field(default="1.0.0", min_length=1, max_length=16)

    @field_validator("organization_id", "run_id", "actor_id", "request_id", "correlation_id", "trace_id", mode="before")
    @classmethod
    def validate_non_empty_ids(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise AgentTenantIsolationError(
                f"State field '{info.field_name}' must be a non-empty string."
            )
        return v.strip()

    @model_validator(mode="after")
    def validate_state_invariants(self) -> AgentGraphState:
        # 1. Reject forbidden chain-of-thought or credentials
        validate_no_forbidden_keys(self.findings, "findings")
        validate_no_forbidden_keys(self.input_references, "input_references")
        validate_no_forbidden_keys(self.metadata, "metadata")
        validate_json_serializable_primitives(self.findings, "findings")
        validate_json_serializable_primitives(self.input_references, "input_references")
        validate_json_serializable_primitives(self.metadata, "metadata")


        # 2. Enforce strict tenant isolation on bounded evidence
        if self.evidence_bundle and self.evidence_bundle.organization_id != self.organization_id:
            raise AgentTenantIsolationError(
                f"Cross-tenant evidence bundle '{self.evidence_bundle.bundle_id}' "
                f"belongs to '{self.evidence_bundle.organization_id}', state scoped to '{self.organization_id}'."
            )

        # 3. Enforce strict tenant isolation on bounded risk assessment
        active_risk_ref = self.risk_assessment or self.risk_assessment_reference
        if active_risk_ref and active_risk_ref.organization_id != self.organization_id:
            raise AgentTenantIsolationError(
                f"Cross-tenant risk assessment '{active_risk_ref.assessment_id}' "
                f"belongs to '{active_risk_ref.organization_id}', state scoped to '{self.organization_id}'."
            )

        # 4. Enforce tenant isolation on explicit cross-tenant prefixed references
        for ref_list_name, refs in [
            ("evidence_references", self.evidence_references),
            ("citation_references", self.citation_references),
            ("risk_alert_references", self.risk_alert_references),
            ("recommendation_references", self.recommendation_references),
        ]:
            for ref in refs:
                if ":" in ref:
                    prefix = ref.split(":", 1)[0]
                    if prefix.startswith("org_") and prefix != self.organization_id:
                        raise AgentTenantIsolationError(
                            f"Cross-tenant reference '{ref}' in '{ref_list_name}' does not match state tenant '{self.organization_id}'."
                        )

        if self.approval_reference and ":" in self.approval_reference:
            prefix = self.approval_reference.split(":", 1)[0]
            if prefix.startswith("org_") and prefix != self.organization_id:
                raise AgentTenantIsolationError(
                    f"Cross-tenant approval reference '{self.approval_reference}' does not match state tenant '{self.organization_id}'."
                )

        # 5. Enforce approval boundary on termination if human approval is required
        if self.requires_human_approval and self.status == AgentLifecycleStatus.COMPLETED:
            raise AgentApprovalBoundaryViolationError(
                "Cannot mark run as COMPLETED when requires_human_approval is True; "
                "must transition to WAITING_FOR_APPROVAL."
            )

        # 6. Synchronize reference aliases for bidirectional compatibility
        if self.evidence_bundle and not self.evidence_bundle_id:
            self.evidence_bundle_id = self.evidence_bundle.bundle_id
        if self.risk_assessment and not self.risk_assessment_id:
            self.risk_assessment_id = self.risk_assessment.assessment_id
        if self.risk_assessment and not self.risk_assessment_reference:
            self.risk_assessment_reference = self.risk_assessment
        elif self.risk_assessment_reference and not self.risk_assessment:
            self.risk_assessment = self.risk_assessment_reference
        if self.selected_route and not self.next_node:
            self.next_node = self.selected_route
        elif self.next_node and not self.selected_route:
            self.selected_route = self.next_node

        # 7. Structural size caps (prevent unbounded graph expansion)
        max_items = 100
        if len(self.structured_findings) > max_items:
            raise AgentStateSizeLimitError(
                f"State structured_findings count ({len(self.structured_findings)}) exceeds limit ({max_items})."
            )
        if len(self.limitations) > 50:
            raise AgentStateSizeLimitError(
                f"State limitations count ({len(self.limitations)}) exceeds limit (50)."
            )
        if len(self.conflicts) > 50:
            raise AgentStateSizeLimitError(
                f"State conflicts count ({len(self.conflicts)}) exceeds limit (50)."
            )
        if len(self.route_history) > max_items:
            raise AgentStateSizeLimitError(
                f"State route_history count ({len(self.route_history)}) exceeds limit ({max_items})."
            )
        if len(self.errors) > 50:
            raise AgentStateSizeLimitError(
                f"State errors count ({len(self.errors)}) exceeds limit (50)."
            )

        return self


# Primary domain alias: AgentState is identical to AgentGraphState
AgentState = AgentGraphState


def validate_state_update(
    current_state: AgentGraphState,
    updates: Optional[Dict[str, Any]] = None,
    node_id: Optional[str] = None,
    stage: Optional[AgentStage] = None,
    update_payload: Optional[Dict[str, Any]] = None,
    writer_node_id: Optional[str] = None,
    writer_stage: Optional[AgentStage] = None,
) -> None:
    """Validate a candidate state update against immutable identity and authoritative ownership rules.

    Raises:
        AgentTenantIsolationError: If an attempt is made to mutate organization_id.
        AgentValidationError: If forbidden keys or secrets exist.
        AgentStateOwnershipViolationError: If identity fields or unauthorized authoritative fields are updated.
        AgentStateSizeLimitError: If payload exceeds max byte limits.
    """
    actual_updates = updates if updates is not None else (update_payload or {})
    actual_node_id = node_id or writer_node_id or "unknown_node"
    actual_stage = stage or writer_stage or AgentStage.INITIALIZATION

    # Check payload size cap (500KB)
    import json
    try:
        payload_bytes = len(json.dumps(actual_updates, default=str).encode("utf-8"))
        if payload_bytes > 500_000:
            raise AgentStateSizeLimitError(
                f"State update payload size ({payload_bytes} bytes) exceeds limit (500000 bytes)."
            )
    except AgentStateSizeLimitError:
        raise
    except Exception:
        pass

    # 1. Enforce no secrets or chain-of-thought in update payload
    validate_no_forbidden_keys(actual_updates, f"update_from_{actual_node_id}")

    # Check for sensitive values embedded in string contents
    for k, v in actual_updates.items():
        if isinstance(v, str):
            validate_no_sensitive_values(v, str(k))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    for ik, iv in item.items():
                        if isinstance(iv, str):
                            validate_no_sensitive_values(iv, str(ik))

    # 2. Strict tenant immutability
    if "organization_id" in actual_updates:
        new_org = str(actual_updates["organization_id"]).strip()
        if new_org != current_state.organization_id:
            raise AgentTenantIsolationError(
                f"Node '{actual_node_id}' attempted to mutate immutable organization_id "
                f"from '{current_state.organization_id}' to '{new_org}'."
            )

    # 3. Read-only identity field protection
    for ident_field in IDENTITY_FIELDS:
        if ident_field in actual_updates and ident_field != "organization_id":
            current_val = getattr(current_state, ident_field, None)
            new_val = actual_updates[ident_field]
            if current_val is not None and new_val != current_val:
                raise AgentStateOwnershipViolationError(
                    f"Immutable identity field: Node '{actual_node_id}' attempted to mutate read-only identity field '{ident_field}'."
                )

    # 4. Authoritative field ownership protection
    for field_name, allowed_stages in AUTHORITATIVE_FIELD_OWNERS.items():
        if field_name in actual_updates and actual_updates[field_name] is not None:
            current_val = getattr(current_state, field_name, None)
            if current_val != actual_updates[field_name] and actual_stage not in allowed_stages:
                raise AgentStateOwnershipViolationError(
                    f"Node '{actual_node_id}' at stage '{actual_stage.value}' is not authorized to update authoritative field '{field_name}'. "
                    f"Allowed stages: {[s.value for s in allowed_stages]}."
                )


def apply_state_update(
    current_state: AgentGraphState,
    updates: Optional[Dict[str, Any]] = None,
    node_id: Optional[str] = None,
    stage: Optional[AgentStage] = None,
    update_payload: Optional[Dict[str, Any]] = None,
    writer_node_id: Optional[str] = None,
    writer_stage: Optional[AgentStage] = None,
) -> AgentGraphState:
    """Apply a validated state update, maintaining route history, step count, and immutability.

    Returns:
        A new validated AgentGraphState instance.
    """
    actual_updates = updates if updates is not None else (update_payload or {})
    actual_node_id = node_id or writer_node_id or "unknown_node"
    actual_stage = stage or writer_stage or AgentStage.INITIALIZATION

    validate_state_update(
        current_state=current_state,
        updates=actual_updates,
        node_id=actual_node_id,
        stage=actual_stage,
    )

    data = current_state.model_dump()
    data.update(actual_updates)
    data["current_node"] = actual_node_id
    data["current_stage"] = actual_stage

    # Record deterministic route event if route changed
    to_node = updates.get("next_node") or updates.get("selected_route")
    if to_node and to_node != current_state.current_node:
        event = RouteEvent(
            from_node=node_id,
            to_node=to_node,
            reason_code=str(updates.get("route_reason") or "EXPLICIT_TRANSITION"),
            step_number=data.get("step_count", current_state.step_count),
        )
        history = list(current_state.route_history)
        history.append(event)
        data["route_history"] = [h.model_dump() if isinstance(h, RouteEvent) else h for h in history]

    return AgentGraphState.model_validate(data)


class AgentGraphStateDict(TypedDict, total=False):
    """TypedDict schema compatible with LangGraph StateGraph nodes and reducers."""

    # Identity
    run_id: str
    organization_id: str
    actor_id: str
    # Correlation
    request_id: str
    correlation_id: str
    trace_id: str
    # Objective
    objective: str
    input_references: Dict[str, Any]
    input_reference: Optional[str]
    requested_operation: Optional[str]
    # Lifecycle
    current_stage: str
    current_node: Optional[str]
    status: str
    step_count: int
    # Evidence
    evidence_bundle_id: Optional[str]
    evidence_references: List[str]
    citation_references: List[str]
    evidence_bundle: Optional[Dict[str, Any]]
    # Risk
    risk_assessment_id: Optional[str]
    risk_assessment_reference: Optional[Dict[str, Any]]
    risk_assessment: Optional[Dict[str, Any]]
    risk_alert_references: List[str]
    recommendation_references: List[str]
    # Findings
    findings: Dict[str, Any]
    structured_findings: List[Dict[str, Any]]
    warnings: List[str]
    limitations: List[Dict[str, Any]]
    conflicts: List[Dict[str, Any]]
    # Routing
    selected_route: Optional[str]
    next_node: Optional[str]
    route_reason: Optional[str]
    route_history: List[Dict[str, Any]]
    # Recovery
    retry_count: int
    last_error: Optional[Dict[str, Any]]
    error_category: Optional[str]
    recovery_status: Optional[str]
    errors: List[Dict[str, Any]]
    # Governance
    requires_human_approval: bool
    approval_reference: Optional[str]
    side_effect_allowed: bool
    approval_status: Optional[str]
    # Termination
    termination_reason: Optional[str]
    started_at: str
    completed_at: Optional[str]
    metadata: Dict[str, Any]
    state_schema_version: str


class EdgeType(str, Enum):
    """Classification of graph edges governing transition semantics and safeguards."""

    NORMAL = "NORMAL"
    CONDITIONAL = "CONDITIONAL"
    RETRY = "RETRY"
    FAILURE = "FAILURE"
    TERMINATION = "TERMINATION"
    APPROVAL_GATE = "APPROVAL_GATE"


class RoutingReasonCode(str, Enum):
    """Deterministic, auditable reason codes for graph routing transitions."""

    INITIAL_ROUTE = "INITIAL_ROUTE"
    EVIDENCE_AVAILABLE = "EVIDENCE_AVAILABLE"
    RISK_REQUIRED = "RISK_REQUIRED"
    PREDICTION_REQUIRED = "PREDICTION_REQUIRED"
    SCENARIO_REQUIRED = "SCENARIO_REQUIRED"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    DEFAULT_COMPLETION = "DEFAULT_COMPLETION"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    REPEATED_NODE_LOOP_DETECTED = "REPEATED_NODE_LOOP_DETECTED"
    EXPLICIT_SELECTION = "EXPLICIT_SELECTION"
    GRAPH_START = "GRAPH_START"
    STATE_TRANSITION = "STATE_TRANSITION"


class ConditionCode(str, Enum):
    """Standardized deterministic condition identifiers evaluated for conditional edges."""

    ALWAYS = "ALWAYS"
    HAS_ERRORS = "HAS_ERRORS"
    IS_RETRYABLE = "IS_RETRYABLE"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    EVIDENCE_SATISFIED = "EVIDENCE_SATISFIED"
    MAX_STEPS_REACHED = "MAX_STEPS_REACHED"
    STAGE_COMPLETED = "STAGE_COMPLETED"


class NodeContract(BaseModel):
    """Specification of an orchestrated node interface in the LangGraph agent graph."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    stage: AgentStage
    is_side_effecting: bool = False
    side_effect_type: ToolSideEffectType = Field(default=ToolSideEffectType.READ_ONLY)
    input_keys: List[str] = Field(default_factory=list)
    required_inputs: List[str] = Field(default_factory=list)
    output_keys: List[str] = Field(default_factory=list)
    allowed_outputs: List[str] = Field(default_factory=list)
    output_fields: List[str] = Field(default_factory=list)
    allowed_state_fields: List[str] = Field(default_factory=list)
    requires_evidence: bool = False
    minimum_evidence: int = Field(default=0, ge=0)
    required_evidence_types: List[str] = Field(default_factory=list)
    required_references: List[str] = Field(default_factory=list)
    required_roles: List[str] = Field(default_factory=list)
    required_permissions: List[str] = Field(default_factory=list)
    retryable: bool = False
    max_retries: int = Field(default=0, ge=0, le=10)
    timeout_seconds: float = Field(default=30.0, ge=0.1, le=600.0)
    is_terminal: bool = False
    tenant_scoped: bool = True

    @model_validator(mode="after")
    def sync_and_validate_node_contract(self) -> NodeContract:
        # Sync input_keys and required_inputs
        if self.input_keys and not self.required_inputs:
            self.required_inputs = list(self.input_keys)
        elif self.required_inputs and not self.input_keys:
            self.input_keys = list(self.required_inputs)
        # Sync output fields variants
        outs = self.output_keys or self.allowed_outputs or self.output_fields or self.allowed_state_fields
        if outs:
            if not self.output_keys:
                self.output_keys = list(outs)
            if not self.allowed_outputs:
                self.allowed_outputs = list(outs)
            if not self.output_fields:
                self.output_fields = list(outs)
            if not self.allowed_state_fields:
                self.allowed_state_fields = list(outs)
        # Sync is_side_effecting and side_effect_type
        if self.is_side_effecting:
            self.side_effect_type = ToolSideEffectType.SIDE_EFFECTING
        elif self.side_effect_type == ToolSideEffectType.SIDE_EFFECTING:
            self.is_side_effecting = True
        return self

    @property
    def node_name(self) -> str:
        """Alias for node_id."""
        return self.node_id


AgentNodeContract = NodeContract


class AgentEdgeContract(BaseModel):
    """Specification of an explicit, validated transition between nodes in the LangGraph graph."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(..., min_length=1, max_length=64)
    from_node: str = Field(..., min_length=1, max_length=64)
    to_node: str = Field(..., min_length=1, max_length=64)
    edge_type: EdgeType = Field(default=EdgeType.NORMAL)
    reason_code: str = Field(..., min_length=1, max_length=100)
    condition_code: Optional[str] = None
    required_roles: List[str] = Field(default_factory=list)
    required_permissions: List[str] = Field(default_factory=list)
    is_terminal: bool = False

    @field_validator("edge_id", "from_node", "to_node", "reason_code", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise AgentValidationError(
                f"Edge field '{info.field_name}' must be a non-empty string."
            )
        return v.strip()


class ToolDefinition(BaseModel):
    """Contract definition for external tools invocable by future agent nodes."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    side_effect_type: ToolSideEffectType = Field(default=ToolSideEffectType.READ_ONLY)
    allowed_stages: List[AgentStage] = Field(default_factory=list)
    tenant_scoped: bool = True
    requires_audit: bool = True


class RouteDecision(BaseModel):
    """Structured decision returned by deterministic graph routing logic."""

    model_config = ConfigDict(extra="forbid")

    next_node: str = Field(..., min_length=1, max_length=64)
    reason_code: str = Field(..., min_length=1, max_length=100)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_references: List[str] = Field(default_factory=list)
    termination_flag: bool = False
    selected_edge: Optional[str] = None
    condition_code: Optional[str] = None

