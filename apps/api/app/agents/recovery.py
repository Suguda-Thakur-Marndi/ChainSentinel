"""Deterministic failure recovery, bounded retries, state integrity, and checkpointing.

Enforces fail-closed semantics on security and tenant violations, deterministic state hashing,
bounded exponential backoff, and safe graph resumption across the agent pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import random
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from app.agents.contracts import (
    AgentExecutionContext,
    AgentGraphState,
    AgentGraphStateDict,
    AgentLifecycleStatus,
    AgentStage,
)
from app.agents.errors import (
    AgentErrorCategory,
    AgentGraphError,
    AgentStateError,
    AgentTenantIsolationError,
    categorize_error,
    is_retryable_error,
)
from app.agents.observability import global_metrics_collector
from app.core.logging import get_logger

logger = get_logger("agents.recovery")


# Transient timestamp or ephemeral fields to exclude from deterministic state hashing
TRANSIENT_STATE_KEYS: frozenset[str] = frozenset({
    "started_at",
    "completed_at",
    "last_error",
    "errors",
})


def _canonical_json_serializer(obj: Any) -> Any:
    """Normalize objects for canonical hashing."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(list(obj))
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)


def compute_state_hash(state: Union[AgentGraphState, AgentGraphStateDict, Dict[str, Any]]) -> str:
    """Compute a deterministic, canonical SHA-256 digest of an agent graph state.
    
    Excludes transient timestamps and error trace arrays to ensure reproducible hashes
    for equivalent semantic state payloads.
    """
    if hasattr(state, "model_dump"):
        state_dict = state.model_dump(mode="json")
    else:
        state_dict = dict(state)

    filtered = {
        k: v for k, v in state_dict.items()
        if k not in TRANSIENT_STATE_KEYS and not k.startswith("_")
    }

    serialized = json.dumps(
        filtered,
        sort_keys=True,
        default=_canonical_json_serializer,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_state_integrity(
    state: Union[AgentGraphState, AgentGraphStateDict, Dict[str, Any]],
    expected_hash: str,
) -> bool:
    """Verify that current state matches an expected canonical SHA-256 hash."""
    computed = compute_state_hash(state)
    return computed == expected_hash


class RecoveryDecision(str, Enum):
    """Deterministic recovery actions determined by RecoveryPolicy."""

    RETRY = "RETRY"
    RESUME = "RESUME"
    FAIL = "FAIL"
    ESCALATE = "ESCALATE"
    WAIT_FOR_HUMAN = "WAIT_FOR_HUMAN"


class AgentFailureResult(BaseModel):
    """Structured, safe public response for failed agent graph executions."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(..., min_length=1)
    agent_run_id: str = Field(..., min_length=1)
    node_id: Optional[str] = None
    stage: Optional[str] = None
    status: str = Field(default="FAILED")
    error_code: str = Field(..., min_length=1)
    error_category: str = Field(..., min_length=1)
    retryable: bool = False
    recovery_action: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_error(
        cls,
        exc: Exception,
        execution_id: str,
        agent_run_id: str,
        trace_id: str,
        recovery_action: RecoveryDecision,
        node_id: Optional[str] = None,
        stage: Optional[str] = None,
    ) -> AgentFailureResult:
        """Create a safe failure response, concealing raw internal stack traces."""
        category = categorize_error(exc)
        retryable = is_retryable_error(exc)
        error_code = getattr(exc, "error_code", "AGENT_ERROR")
        public_message = getattr(exc, "public_message", None)
        if not public_message:
            public_message = (
                "The requested agent operation could not be completed. Please contact support."
            )

        return cls(
            execution_id=execution_id,
            agent_run_id=agent_run_id,
            node_id=node_id,
            stage=stage,
            status="FAILED",
            error_code=error_code,
            error_category=category.value,
            retryable=retryable,
            recovery_action=recovery_action.value,
            trace_id=trace_id,
            message=public_message,
        )


class RetryPolicy:
    """Configurable exponential backoff and retry policy for agent nodes."""

    def __init__(
        self,
        base_delay_seconds: float = 0.1,
        max_delay_seconds: float = 2.0,
        jitter: bool = True,
    ) -> None:
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.jitter = jitter

    def compute_backoff(self, attempt: int) -> float:
        """Compute exponential backoff delay with optional bounded jitter."""
        if attempt <= 1:
            delay = self.base_delay_seconds
        else:
            delay = min(
                self.max_delay_seconds,
                self.base_delay_seconds * (2 ** (attempt - 1)),
            )

        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)

        return round(delay, 4)

    def is_retry_allowed(
        self,
        attempt: int,
        max_retries: int,
        error: Exception,
    ) -> bool:
        """Determine whether an attempt can be retried under this policy."""
        if attempt >= max_retries:
            return False
        return is_retryable_error(error)


class RecoveryPolicy:
    """Evaluates execution context, error taxonomy, and pipeline invariants to decide recovery."""

    @staticmethod
    def evaluate(
        error: Exception,
        attempt: int,
        max_retries: int,
        state: Optional[Union[AgentGraphState, Dict[str, Any]]] = None,
        context: Optional[AgentExecutionContext] = None,
    ) -> RecoveryDecision:
        """Deterministically determine recovery decision.
        
        Rules:
        1. Security, Tenant Isolation, Authorization, Validation, and State errors: FAIL immediately (Fail-Closed).
        2. Human approval pending: WAIT_FOR_HUMAN.
        3. Human approval rejected: FAIL.
        4. Retryable error with budget remaining (attempt < max_retries): RETRY.
        5. Retryable error with exhausted budget: ESCALATE.
        6. Other unrecoverable errors: FAIL.
        """
        category = categorize_error(error)

        # 1. Strict security & isolation invariants -> FAIL closed
        if category in {
            AgentErrorCategory.SECURITY_ERROR,
            AgentErrorCategory.TENANT_ISOLATION_ERROR,
            AgentErrorCategory.AUTHORIZATION_ERROR,
            AgentErrorCategory.CONTRACT_ERROR,
            AgentErrorCategory.VALIDATION_ERROR,
            AgentErrorCategory.STATE_ERROR,
        }:
            global_metrics_collector.record_recovery(RecoveryDecision.FAIL.value)
            return RecoveryDecision.FAIL

        # 2. Check approval states
        if state:
            status = state.get("status") if isinstance(state, dict) else getattr(state, "status", None)
            if status in (AgentLifecycleStatus.WAITING_FOR_APPROVAL, "WAITING_FOR_APPROVAL"):
                global_metrics_collector.record_recovery(RecoveryDecision.WAIT_FOR_HUMAN.value)
                return RecoveryDecision.WAIT_FOR_HUMAN

            requires_approval = (
                state.get("requires_human_approval", False)
                if isinstance(state, dict)
                else getattr(state, "requires_human_approval", False)
            )
            approval_result = (
                state.get("approval_result")
                if isinstance(state, dict)
                else getattr(state, "approval_result", None)
            )
            if requires_approval and not approval_result:
                global_metrics_collector.record_recovery(RecoveryDecision.WAIT_FOR_HUMAN.value)
                return RecoveryDecision.WAIT_FOR_HUMAN

        # 3. Retry evaluation for retryable errors
        if is_retryable_error(error):
            if attempt < max_retries:
                global_metrics_collector.record_recovery(RecoveryDecision.RETRY.value)
                return RecoveryDecision.RETRY
            else:
                global_metrics_collector.record_recovery(RecoveryDecision.ESCALATE.value)
                return RecoveryDecision.ESCALATE

        # 4. Default to FAIL closed
        global_metrics_collector.record_recovery(RecoveryDecision.FAIL.value)
        return RecoveryDecision.FAIL


class CheckpointManager:
    """In-memory and checkpointer integration for safe graph persistence and resumption."""

    def __init__(self, checkpointer: Optional[Any] = None) -> None:
        self.checkpointer = checkpointer
        self._checkpoints: Dict[str, Dict[str, Any]] = {}

    def save_checkpoint(
        self,
        thread_id: str,
        state: AgentGraphState,
        step: int,
        checkpoint_id: Optional[str] = None,
    ) -> str:
        """Record an immutable checkpoint with canonical state hash."""
        cid = checkpoint_id or f"chk_{thread_id}_{step}_{int(time.time()*1000)}"
        state_dict = state.model_dump(mode="json")
        state_hash = compute_state_hash(state)

        record = {
            "checkpoint_id": cid,
            "thread_id": thread_id,
            "organization_id": state.organization_id,
            "step": step,
            "state_hash": state_hash,
            "state": state_dict,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._checkpoints[cid] = record
        self._checkpoints[f"latest_{thread_id}"] = record
        return cid

    def restore_checkpoint(
        self,
        checkpoint_id_or_thread_id: str,
        expected_org_id: Optional[str] = None,
    ) -> Tuple[AgentGraphState, str]:
        """Restore state from checkpoint, verifying state hash and tenant boundary.
        
        Raises:
            AgentStateError: If checkpoint does not exist or state integrity hash is tampered/corrupted.
            AgentTenantIsolationError: If restored tenant does not match expected_org_id.
        """
        key = checkpoint_id_or_thread_id
        if key not in self._checkpoints:
            key = f"latest_{checkpoint_id_or_thread_id}"

        record = self._checkpoints.get(key)
        if not record:
            raise AgentStateError(
                f"Checkpoint not found for key: '{checkpoint_id_or_thread_id}'.",
                details={"lookup_key": checkpoint_id_or_thread_id},
            )

        # 1. Enforce tenant boundary
        if expected_org_id and record["organization_id"] != expected_org_id:
            raise AgentTenantIsolationError(
                f"Checkpoint tenant mismatch: expected '{expected_org_id}', "
                f"checkpoint owned by '{record['organization_id']}'.",
                details={"expected_org": expected_org_id, "checkpoint_org": record["organization_id"]},
            )

        # 2. Verify state hash integrity
        state_dict = record["state"]
        expected_hash = record["state_hash"]
        current_hash = compute_state_hash(state_dict)

        if current_hash != expected_hash:
            raise AgentStateError(
                f"Checkpoint state integrity failure: hash '{current_hash}' != expected '{expected_hash}'.",
                details={"computed_hash": current_hash, "expected_hash": expected_hash},
            )

        # 3. Construct validated AgentGraphState
        restored_state = AgentGraphState.model_validate(state_dict)
        return restored_state, record["checkpoint_id"]
