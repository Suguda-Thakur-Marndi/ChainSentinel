"""Strongly typed Pydantic V2 domain contracts for Human Approval boundary.

Enforces zero-trust governance, strict field ownership, multi-tenant isolation,
deterministic identity, and cryptographic audit fingerprinting.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import (
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.errors import AgentValidationError

APPROVAL_UUID_NAMESPACE = uuid.UUID("d4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a")


class ApprovalDecision(str, Enum):
    """Explicit human sign-off decision values."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"


class ApprovalStatus(str, Enum):
    """Lifecycle status representing the operational state of an approval boundary."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class ApprovalActor(BaseModel):
    """Strongly typed representation of the human actor responsible for governance decisions."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    actor_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., min_length=1, max_length=64)
    email: Optional[str] = Field(default=None, max_length=256)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    request_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("actor_id", "organization_id", "role", mode="before")
    @classmethod
    def validate_non_empty_strings(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError(f"ApprovalActor field '{info.field_name}' must be a non-empty string.")
        return v.strip()

    @field_validator("actor_id", "role", "email", mode="after")
    @classmethod
    def validate_no_secrets(cls, v: Optional[str], info: Any) -> Optional[str]:
        if v is not None:
            try:
                validate_no_sensitive_values(v, f"ApprovalActor.{info.field_name}")
            except AgentValidationError as e:
                raise ValueError(str(e)) from e
        return v


class ApprovalAuditContext(BaseModel):
    """Audit and correlation context binding human decisions to systemic telemetry."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    correlation_id: str = Field(..., min_length=1, max_length=64)
    trace_id: str = Field(..., min_length=1, max_length=64)
    request_id: str = Field(..., min_length=1, max_length=64)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("correlation_id", "trace_id", "request_id", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError(f"ApprovalAuditContext field '{info.field_name}' must be non-empty.")
        return v.strip()


class ApprovalRequest(BaseModel):
    """Validated input requesting human sign-off on an operational decision candidate."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    approval_id: Optional[str] = Field(default=None, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    decision_id: str = Field(..., min_length=1, max_length=64)
    decision_reference: Optional[Dict[str, Any]] = None
    candidate_id: str = Field(..., min_length=1, max_length=64)
    recommendation_id: Optional[str] = Field(default=None, max_length=64)
    requester_id: Optional[str] = Field(default=None, max_length=64)
    required_role: str = Field(default="RiskManager", min_length=1, max_length=64)
    expiration_timestamp: Optional[datetime] = None
    evidence_references: List[str] = Field(default_factory=list)
    constraints: List[Dict[str, Any]] = Field(default_factory=list)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    trace_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("organization_id", "decision_id", "candidate_id", mode="before")
    @classmethod
    def validate_non_empty_ids(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError(f"ApprovalRequest field '{info.field_name}' must be a non-empty string.")
        return v.strip()

    @model_validator(mode="after")
    def validate_approval_request_invariants(self) -> ApprovalRequest:
        # Validate decision reference tenant if present
        if self.decision_reference and isinstance(self.decision_reference, dict):
            dec_org = self.decision_reference.get("organization_id")
            if dec_org and dec_org.strip() != self.organization_id:
                raise ValueError(
                    f"Decision reference tenant '{dec_org}' does not match request tenant '{self.organization_id}'."
                )

        # Scrub sensitive data and CoT from reference payloads
        try:
            if self.decision_reference:
                validate_no_forbidden_keys(self.decision_reference, "decision_reference")
            for c in self.constraints:
                validate_no_forbidden_keys(c, "constraints")
        except AgentValidationError as e:
            raise ValueError(str(e)) from e

        return self


class ApprovalDecisionInput(BaseModel):
    """Payload representing an explicit human governance action."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision: ApprovalDecision
    actor: ApprovalActor
    comments: Optional[str] = Field(default=None, max_length=1000)
    decided_at: Optional[datetime] = None

    @field_validator("comments", mode="after")
    @classmethod
    def validate_comments_safety(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                validate_no_sensitive_values(v, "comments")
                validate_no_forbidden_keys({"comments": v}, "comments")
            except AgentValidationError as e:
                raise ValueError(str(e)) from e
        return v


class ApprovalResult(BaseModel):
    """Strongly typed output of the Human Approval boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    approval_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    decision_id: str = Field(..., min_length=1, max_length=64)
    candidate_id: str = Field(..., min_length=1, max_length=64)
    recommendation_id: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default=ApprovalStatus.PENDING.value)
    actor_id: Optional[str] = Field(default=None, max_length=64)
    actor_role: Optional[str] = Field(default=None, max_length=64)
    decided_at: Optional[datetime] = None
    reason: Optional[str] = Field(default=None, max_length=1000)
    comments: Optional[str] = Field(default=None, max_length=1000)
    evidence_references: List[str] = Field(default_factory=list)
    audit_reference: Optional[str] = Field(default=None, max_length=256)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    requires_human_approval: bool = True
    side_effect_allowed: bool = False
    fingerprint: Optional[str] = None

    @field_validator("approval_id", "organization_id", "decision_id", "candidate_id", mode="before")
    @classmethod
    def validate_non_empty_result_ids(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError(f"ApprovalResult field '{info.field_name}' must be a non-empty string.")
        return v.strip()

    @model_validator(mode="after")
    def validate_approval_result_invariants(self) -> ApprovalResult:
        # If APPROVED, actor_id and decided_at must be populated
        if self.status == ApprovalStatus.APPROVED.value:
            if not self.actor_id:
                raise ValueError("Approved ApprovalResult must record actor_id.")
            if not self.decided_at:
                raise ValueError("Approved ApprovalResult must record decided_at timestamp.")
            if self.requires_human_approval:
                raise ValueError("Approved ApprovalResult cannot require human approval.")
            if not self.side_effect_allowed:
                raise ValueError("Approved ApprovalResult must set side_effect_allowed=True.")
        elif self.status == ApprovalStatus.REJECTED.value:
            if not self.actor_id:
                raise ValueError("Rejected ApprovalResult must record actor_id.")
            if self.side_effect_allowed:
                raise ValueError("Rejected ApprovalResult cannot allow side effects.")
        elif self.status == ApprovalStatus.PENDING.value:
            if not self.requires_human_approval:
                raise ValueError("Pending ApprovalResult must have requires_human_approval=True.")
            if self.side_effect_allowed:
                raise ValueError("Pending ApprovalResult cannot allow side effects.")

        try:
            validate_no_forbidden_keys(self.provenance, "provenance")
            for k, v in self.provenance.items():
                if isinstance(v, str):
                    validate_no_reasoning_content(v, f"provenance.{k}")
        except AgentValidationError as e:
            raise ValueError(str(e)) from e
        return self


def generate_deterministic_approval_id(
    organization_id: str,
    decision_id: str,
    candidate_id: str,
) -> str:
    """Generate a reproducible, collision-free UUIDv5 identifier for an approval boundary.

    Identity is bound to the immutable tuple: (organization_id, decision_id, candidate_id).
    """
    canonical_seed = f"{organization_id.strip()}:{decision_id.strip()}:{candidate_id.strip()}"
    return str(uuid.uuid5(APPROVAL_UUID_NAMESPACE, canonical_seed))


def compute_approval_fingerprint(
    organization_id: str,
    decision_id: str,
    candidate_id: str,
    status: str,
    actor_id: Optional[str] = None,
    decision: Optional[str] = None,
    decided_at_str: Optional[str] = None,
    evidence_references: Optional[List[str]] = None,
) -> str:
    """Compute a deterministic SHA-256 digest over normalized approval governance fields."""
    payload = {
        "organization_id": organization_id.strip(),
        "decision_id": decision_id.strip(),
        "candidate_id": candidate_id.strip(),
        "status": status.strip(),
        "actor_id": actor_id.strip() if actor_id else None,
        "decision": decision.strip() if decision else None,
        "decided_at": decided_at_str,
        "evidence_references": sorted(list(set(evidence_references or []))),
    }
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


class PendingApprovalItem(BaseModel):
    """Summarized pending decision awaiting human approval."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    approval_id: str = Field(..., min_length=1, max_length=64)
    decision_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    rationale: Optional[str] = Field(default=None, max_length=1000)
    estimated_cost: Optional[float] = None
    confidence: Optional[float] = None
    status: str = Field(default=ApprovalStatus.PENDING.value)
    preferred_candidate_id: Optional[str] = Field(default=None, max_length=64)
    action_type: Optional[str] = Field(default=None, max_length=64)
    tradeoffs: Dict[str, Any] = Field(default_factory=dict)
    requires_human_approval: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PendingApprovalListResponse(BaseModel):
    """Paginated list of pending decisions awaiting human governance review."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    items: List[PendingApprovalItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class ApprovalDossier(BaseModel):
    """Comprehensive review dossier providing full inspection context for human sign-off."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    approval_id: str = Field(..., min_length=1, max_length=64)
    decision_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    rationale: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(default=ApprovalStatus.PENDING.value)
    confidence: Optional[float] = None
    decision_result: Dict[str, Any] = Field(default_factory=dict)
    decision_explanation: Optional[Dict[str, Any]] = None
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    preferred_candidate: Optional[Dict[str, Any]] = None
    tradeoffs: Dict[str, Any] = Field(default_factory=dict)
    evidence_references: List[str] = Field(default_factory=list)
    audit_history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: Optional[datetime] = None
    decided_by_user_id: Optional[str] = Field(default=None, max_length=64)
    decision: Optional[str] = Field(default=None, max_length=50)
    comments: Optional[str] = Field(default=None, max_length=1000)


class HumanDecisionRequest(BaseModel):
    """Input payload for a human signing off (approving or rejecting) an operational decision."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision: ApprovalDecision
    comments: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("comments", mode="after")
    @classmethod
    def validate_comments_safety(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                validate_no_sensitive_values(v, "comments")
                validate_no_forbidden_keys({"comments": v}, "comments")
            except AgentValidationError as e:
                raise ValueError(str(e)) from e
        return v
