"""Domain contracts, schemas, and deterministic identifiers for the Verification Agent (Phase 18).

Establishes the authoritative boundary between:
A. Intended Outcome (derived strictly from approved DecisionResult & ActionCommand)
B. Observed Outcome (derived strictly from authoritative post-action evidence)

Invariants:
- Frozen/strict Pydantic V2 models with extra="forbid"
- Deterministic UUIDv5 identifiers and SHA-256 canonical fingerprints
- Strict evidence precedence: REAL > ESTIMATED > SIMULATED
- No arbitrary URLs, code execution, or prompt injection payloads
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.action.contract import ActionType, TargetEntityType


VERIFICATION_NAMESPACE_UUID = uuid.UUID("3456789a-bcde-0123-4567-89abcdef0123")

URL_PATTERN = re.compile(r"^(https?|ftp|file|javascript|data):", re.IGNORECASE)
PROMPT_INJECTION_PATTERN = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions|system\s+prompt|drop\s+table|delete\s+from|<script)",
    re.IGNORECASE,
)
CODE_EXEC_PATTERN = re.compile(r"(eval\(|exec\(|__import__|os\.system|subprocess)", re.IGNORECASE)


class VerificationStatus(str, Enum):
    """Authoritative outcome verification status."""

    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    EXPIRED = "EXPIRED"
    CONFLICT = "CONFLICT"
    ERROR = "ERROR"


class EvidenceSourcePrecedence(str, Enum):
    """Hierarchical classification of evidence authority.
    
    Precedence rule:
    REAL > ESTIMATED > SIMULATED
    """

    REAL = "REAL"
    ESTIMATED = "ESTIMATED"
    SIMULATED = "SIMULATED"

    @property
    def rank(self) -> int:
        """Numeric rank for strict precedence comparison (higher = more authoritative)."""
        if self == EvidenceSourcePrecedence.REAL:
            return 3
        if self == EvidenceSourcePrecedence.ESTIMATED:
            return 2
        return 1

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, EvidenceSourcePrecedence):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, EvidenceSourcePrecedence):
            return self.rank >= other.rank
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, EvidenceSourcePrecedence):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, EvidenceSourcePrecedence):
            return self.rank <= other.rank
        return NotImplemented


def _sanitize_string_value(val: str, field_name: str) -> str:
    """Validate strings for URLs, prompt injection, and code execution attacks."""
    cleaned = val.strip()
    if URL_PATTERN.match(cleaned):
        raise ValueError(f"Arbitrary URLs are strictly forbidden in field '{field_name}'.")
    if PROMPT_INJECTION_PATTERN.search(cleaned):
        raise ValueError(f"Potential injection pattern detected in field '{field_name}'.")
    if CODE_EXEC_PATTERN.search(cleaned):
        raise ValueError(f"Code execution pattern detected in field '{field_name}'.")
    return cleaned


class ObservedEvidenceItem(BaseModel):
    """Individual item of post-action operational evidence with provenance."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    evidence_id: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., min_length=1, max_length=64)
    source_precedence: EvidenceSourcePrecedence = Field(default=EvidenceSourcePrecedence.REAL)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entity_type: TargetEntityType
    entity_id: str = Field(..., min_length=1, max_length=128)
    observed_attributes: Dict[str, Any] = Field(default_factory=dict)
    raw_reference_id: Optional[str] = Field(None, max_length=128)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id", "source_type", "entity_id", mode="before")
    @classmethod
    def validate_safe_strings(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string.")
        return _sanitize_string_value(v, info.field_name)

    @field_validator("timestamp", mode="after")
    @classmethod
    def ensure_utc_timestamp(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)


class IntendedOutcome(BaseModel):
    """Specification of the intended real-world outcome derived from the approved action."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    action_type: ActionType
    target_entity_type: TargetEntityType
    target_entity_id: str = Field(..., min_length=1, max_length=128)
    expected_attributes: Dict[str, Any] = Field(default_factory=dict)
    observation_window_seconds: int = Field(default=86400, ge=60, le=2592000)  # 1m to 30d
    required_precedence: EvidenceSourcePrecedence = Field(default=EvidenceSourcePrecedence.REAL)

    @field_validator("target_entity_id", mode="before")
    @classmethod
    def validate_safe_id(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string.")
        return _sanitize_string_value(v, info.field_name)


class ObservedOutcome(BaseModel):
    """Synthesized post-action operational outcome derived from authoritative evidence."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    target_entity_type: TargetEntityType
    target_entity_id: str = Field(..., min_length=1, max_length=128)
    observed_attributes: Dict[str, Any] = Field(default_factory=dict)
    evidence_count: int = Field(default=0, ge=0)
    highest_precedence: Optional[EvidenceSourcePrecedence] = None
    evidence_items: List[ObservedEvidenceItem] = Field(default_factory=list)
    conflict_detected: bool = False
    conflict_details: Optional[str] = Field(None, max_length=1000)

    @field_validator("target_entity_id", mode="before")
    @classmethod
    def validate_safe_id(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string.")
        return _sanitize_string_value(v, info.field_name)


class VerificationCommand(BaseModel):
    """Command requesting verification of an executed operational action."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    verification_id: Optional[str] = Field(None, max_length=128)
    action_id: str = Field(..., min_length=1, max_length=128)
    decision_id: Optional[str] = Field(None, max_length=128)
    approval_id: Optional[str] = Field(None, max_length=128)
    organization_id: str = Field(..., min_length=1, max_length=128)
    action_type: ActionType
    target_entity_type: TargetEntityType
    target_entity_id: str = Field(..., min_length=1, max_length=128)
    action_parameters: Dict[str, Any] = Field(default_factory=dict)
    action_executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observation_window_seconds: int = Field(default=86400, ge=60, le=2592000)
    trace_id: Optional[str] = Field(None, max_length=128)
    policy_version: str = Field(default="1.0", max_length=32)

    @field_validator("action_id", "organization_id", "target_entity_id", mode="before")
    @classmethod
    def validate_required_strings(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string.")
        return _sanitize_string_value(v, info.field_name)

    @field_validator("decision_id", "approval_id", "trace_id", "verification_id", mode="before")
    @classmethod
    def validate_optional_strings(cls, v: Any, info: Any) -> Optional[str]:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"Field '{info.field_name}' must be a string.")
        return _sanitize_string_value(v, info.field_name)

    @field_validator("action_executed_at", mode="after")
    @classmethod
    def ensure_utc_action_executed_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="after")
    def populate_defaults(self) -> VerificationCommand:
        if not self.verification_id:
            generated = generate_deterministic_verification_id(
                organization_id=self.organization_id,
                action_id=self.action_id,
                policy_version=self.policy_version,
            )
            object.__setattr__(self, "verification_id", generated)
        return self


class VerificationResultPayload(BaseModel):
    """Strongly typed verification result establishing post-action operational truth."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    verification_id: str = Field(..., min_length=1, max_length=128)
    action_id: str = Field(..., min_length=1, max_length=128)
    decision_id: Optional[str] = Field(None, max_length=128)
    approval_id: Optional[str] = Field(None, max_length=128)
    organization_id: str = Field(..., min_length=1, max_length=128)
    action_type: ActionType
    target_entity_type: TargetEntityType
    target_entity_id: str = Field(..., min_length=1, max_length=128)
    status: VerificationStatus
    verified: bool = False
    intended_outcome: IntendedOutcome
    observed_outcome: ObservedOutcome
    observation_window_start: datetime
    observation_window_end: datetime
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    policy_version: str = Field(default="1.0", max_length=32)
    fingerprint: str = Field(..., min_length=16, max_length=128)
    risk_score_before: Optional[float] = Field(None, ge=0.0, le=100.0)
    risk_score_after: Optional[float] = Field(None, ge=0.0, le=100.0)
    observation_summary: str = Field(default="", max_length=2000)
    provenance: Dict[str, Any] = Field(default_factory=dict)


def generate_deterministic_verification_id(
    organization_id: str,
    action_id: str,
    policy_version: str = "1.0",
) -> str:
    """Generate a deterministic, repeatable UUIDv5 verification identifier."""
    seed_str = f"verification:{organization_id}:{action_id}:{policy_version}"
    return str(uuid.uuid5(VERIFICATION_NAMESPACE_UUID, seed_str))


def compute_verification_fingerprint(
    organization_id: str,
    action_id: str,
    intended_outcome: Dict[str, Any],
    observed_outcome: Dict[str, Any],
    status: str,
    policy_version: str = "1.0",
) -> str:
    """Compute a canonical SHA-256 fingerprint for verification state."""
    canonical_dict = {
        "organization_id": organization_id,
        "action_id": action_id,
        "intended_outcome": intended_outcome,
        "observed_outcome": observed_outcome,
        "status": status,
        "policy_version": policy_version,
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
