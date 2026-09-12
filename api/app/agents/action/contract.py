"""Domain contracts, schemas, enums, and deterministic identifiers for the RiskWise Action Agent (Phase 17).

Provides strongly typed Pydantic V2 definitions with:
- Strict field validation (`extra="forbid"`, `validate_assignment=True`)
- Reproducible deterministic UUIDv5 action ID generation
- Canonical SHA-256 action fingerprint computation
- Scrubbing of sensitive credentials and chain-of-thought
- Uncompromising tenant scoping and mandatory approval binding
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.action.errors import (
    ActionSecurityViolationError,
    ActionTenantIsolationError,
    InvalidActionRequestError,
)
from app.agents.errors import (
    AgentSecurityError,
    AgentValidationError,
)
from app.agents.contracts import (
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.rag.contracts import RAG_UUID_NAMESPACE


class ActionType(str, Enum):
    """Supported operational action taxonomy for execution adapters."""

    SHIPMENT_REROUTE = "SHIPMENT_REROUTE"
    CARRIER_REALLOCATION = "CARRIER_REALLOCATION"
    FACILITY_REALLOCATION = "FACILITY_REALLOCATION"
    EXPEDITE_SHIPMENT = "EXPEDITE_SHIPMENT"
    HOLD_SHIPMENT = "HOLD_SHIPMENT"
    MONITOR = "MONITOR"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if isinstance(value, str):
            val_upper = value.upper().strip()
            aliases = {
                "REROUTE_SHIPMENT": cls.SHIPMENT_REROUTE,
                "SELECT_ROUTE": cls.SHIPMENT_REROUTE,
                "REALLOCATE_CARRIER": cls.CARRIER_REALLOCATION,
                "REALLOCATE_FACILITY": cls.FACILITY_REALLOCATION,
                "EXPEDITE": cls.EXPEDITE_SHIPMENT,
                "HOLD": cls.HOLD_SHIPMENT,
                "MONITORING": cls.MONITOR,
            }
            if val_upper in aliases:
                return aliases[val_upper]
        return super()._missing_(value)


class ExecutionStatus(str, Enum):
    """Granular execution status returned by the Action Agent and adapters."""

    SUCCEEDED = "SUCCEEDED"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class TargetEntityType(str, Enum):
    """Operational entity types subject to mitigation actions."""

    SHIPMENT = "SHIPMENT"
    CARRIER = "CARRIER"
    FACILITY = "FACILITY"
    ROUTE = "ROUTE"
    SUPPLIER = "SUPPLIER"
    INVENTORY = "INVENTORY"


class IdempotencyResult(str, Enum):
    """Outcome of idempotency evaluation for an incoming action command."""

    FIRST_EXECUTION = "FIRST_EXECUTION"
    REPLAYED_IDEMPOTENT = "REPLAYED_IDEMPOTENT"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"


class ActionActor(BaseModel):
    """Identity and authorization attributes of the human/system executing the action."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    actor_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., min_length=1, max_length=64)
    email: Optional[str] = Field(default=None, max_length=256)

    @field_validator("actor_id", "organization_id", "role", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidActionRequestError(f"ActionActor field '{info.field_name}' must be non-empty.")
        return v.strip()

    @field_validator("actor_id", "role", "email", mode="after")
    @classmethod
    def validate_no_secrets(cls, v: Optional[str], info: Any) -> Optional[str]:
        if v is not None:
            validate_no_sensitive_values(v, f"ActionActor.{info.field_name}")
        return v


def generate_deterministic_action_id(
    organization_id: str,
    decision_id: str,
    approval_id: str,
    action_type: str,
    target_entity_id: str,
    idempotency_key: str,
) -> str:
    """Generate a reproducible UUIDv5 action identifier from canonical intent parameters."""
    if not organization_id or not str(organization_id).strip():
        raise ActionTenantIsolationError("organization_id must be non-empty.")
    token = (
        f"{str(organization_id).strip()}:{str(decision_id).strip()}:{str(approval_id).strip()}:"
        f"{str(action_type).strip()}:{str(target_entity_id).strip()}:{str(idempotency_key).strip()}"
    )
    raw_uuid = str(uuid.uuid5(RAG_UUID_NAMESPACE, token))
    return f"act_{raw_uuid}"


def compute_action_fingerprint(
    organization_id: str,
    decision_id: str,
    approval_id: str,
    action_type: str,
    target_entity_type: str,
    target_entity_id: str,
    parameters: Dict[str, Any],
    policy_version: str = "1.0",
    approval_fingerprint: Optional[str] = None,
) -> str:
    """Generate a deterministic SHA-256 fingerprint over canonicalized action intent."""
    payload: Dict[str, Any] = {
        "organization_id": str(organization_id).strip(),
        "decision_id": str(decision_id).strip(),
        "approval_id": str(approval_id).strip(),
        "action_type": str(action_type).strip(),
        "target_entity_type": str(target_entity_type).strip(),
        "target_entity_id": str(target_entity_id).strip(),
        "parameters": parameters or {},
        "policy_version": str(policy_version).strip(),
        "approval_fingerprint": str(approval_fingerprint or "").strip(),
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ActionCommand(BaseModel):
    """Strongly typed, immutable operational command requiring prior human approval."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    action_id: Optional[str] = Field(default=None, max_length=64)
    decision_id: str = Field(..., min_length=1, max_length=64)
    approval_id: str = Field(..., min_length=1, max_length=64)
    candidate_id: Optional[str] = Field(default=None, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    action_type: ActionType
    target_entity_type: TargetEntityType
    target_entity_id: str = Field(..., min_length=1, max_length=64)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(..., min_length=1, max_length=128)
    trace_id: str = Field(..., min_length=1, max_length=64)
    run_id: Optional[str] = Field(default=None, max_length=64)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expiration_timestamp: Optional[datetime] = None
    approval_fingerprint: Optional[str] = Field(default=None, max_length=64)
    actor: Optional[ActionActor] = None
    policy_version: str = Field(default="1.0", min_length=1, max_length=16)

    @field_validator("decision_id", "approval_id", "organization_id", "target_entity_id", "idempotency_key", "trace_id", mode="before")
    @classmethod
    def validate_non_empty_strings(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidActionRequestError(f"ActionCommand field '{info.field_name}' must be a non-empty string.")
        return v.strip()

    @model_validator(mode="after")
    def validate_command_invariants(self) -> ActionCommand:
        # 1. Enforce deterministic action_id if not explicitly provided
        if not self.action_id:
            object.__setattr__(
                self,
                "action_id",
                generate_deterministic_action_id(
                    organization_id=self.organization_id,
                    decision_id=self.decision_id,
                    approval_id=self.approval_id,
                    action_type=self.action_type.value,
                    target_entity_id=self.target_entity_id,
                    idempotency_key=self.idempotency_key,
                ),
            )

        # 2. Actor tenant isolation
        if self.actor and self.actor.organization_id != self.organization_id:
            raise ActionTenantIsolationError(
                f"Actor tenant '{self.actor.organization_id}' does not match command tenant '{self.organization_id}'."
            )

        # 3. Security validation on parameters (no secrets, no CoT, no URLs)
        try:
            validate_no_forbidden_keys(self.parameters, "parameters")
        except AgentValidationError as e:
            raise ActionSecurityViolationError(f"Prohibited credential or secret key detected in parameters: {e}") from e

        for pk, pv in self.parameters.items():
            if isinstance(pv, str):
                try:
                    validate_no_sensitive_values(pv, f"parameters.{pk}")
                    validate_no_reasoning_content(pv, f"parameters.{pk}")
                except (AgentValidationError, AgentSecurityError) as e:
                    raise ActionSecurityViolationError(f"Security validation failure in parameter '{pk}': {e}") from e

                # Forbid arbitrary user URLs (SSRF prevention)
                if re.match(r"^https?://", pv.strip(), re.IGNORECASE):
                    raise ActionSecurityViolationError(
                        f"Arbitrary URL injection detected in parameter '{pk}': '{pv}'. External URLs are forbidden."
                    )
                # Forbid arbitrary code execution patterns
                if any(kw in pv for kw in ("__import__", "exec(", "eval(", "os.system", "subprocess.")):
                    raise ActionSecurityViolationError(
                        f"Prohibited executable code pattern detected in parameter '{pk}'."
                    )

        # 4. Parameter count limit
        if len(self.parameters) > 50:
            raise InvalidActionRequestError(f"Parameters count ({len(self.parameters)}) exceeds limit (50).")

        return self


# Backward-compatible alias
ActionRequest = ActionCommand


class ActionResult(BaseModel):
    """Strongly typed, authoritative outcome of operational action dispatch."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    action_id: str = Field(..., min_length=1, max_length=64)
    decision_id: str = Field(..., min_length=1, max_length=64)
    approval_id: str = Field(..., min_length=1, max_length=64)
    candidate_id: Optional[str] = Field(default=None, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=64)
    target_entity_type: str = Field(..., min_length=1, max_length=64)
    target_entity_id: str = Field(..., min_length=1, max_length=64)
    status: str = Field(default=ExecutionStatus.SUCCEEDED.value)
    execution_start: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    execution_end: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    adapter: str = Field(..., min_length=1, max_length=64)
    provider: str = Field(..., min_length=1, max_length=64)
    provider_request_id: Optional[str] = Field(default=None, max_length=128)
    provider_response_reference: Optional[str] = Field(default=None, max_length=256)
    idempotency_result: str = Field(default=IdempotencyResult.FIRST_EXECUTION.value)
    error_code: Optional[str] = Field(default=None, max_length=64)
    error_message: Optional[str] = Field(default=None, max_length=1000)
    audit_reference: Optional[str] = Field(default=None, max_length=128)
    trace_id: str = Field(..., min_length=1, max_length=64)
    execution_payload: Dict[str, Any] = Field(default_factory=dict)
    result_payload: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = Field(..., min_length=64, max_length=64)
    policy_version: str = Field(default="1.0", min_length=1, max_length=16)

    @field_validator("action_id", "decision_id", "approval_id", "organization_id", "fingerprint", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ValueError(f"ActionResult field '{info.field_name}' must be non-empty.")
        return v.strip()

    @model_validator(mode="after")
    def validate_result_invariants(self) -> ActionResult:
        # Ensure result payloads do not contain sensitive tokens
        validate_no_forbidden_keys(self.execution_payload, "execution_payload")
        validate_no_forbidden_keys(self.result_payload, "result_payload")
        return self
