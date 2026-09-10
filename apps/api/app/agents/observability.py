"""Observability, telemetry, and structured execution logging for LangGraph agents.

Emits structured telemetry events for every node execution and state transition,
while strictly scrubbing all credentials, API keys, passwords, and sensitive context.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger

logger = get_logger("agents")


class NodeExecutionTelemetry(BaseModel):
    """Structured telemetry payload capturing the execution metrics of an agent node."""

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(..., min_length=1)
    organization_id: str = Field(..., min_length=1)
    actor_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    correlation_id: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    node_name: str = Field(..., min_length=1)
    duration_ms: float = Field(..., ge=0.0)
    status: str = Field(..., min_length=1)
    stage: Optional[str] = None
    error_code: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    step_count: int = Field(default=0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentRunTelemetry(BaseModel):
    """Comprehensive, strongly typed telemetry record for node and graph execution runs."""

    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(..., min_length=1)
    agent_run_id: str = Field(..., min_length=1)
    execution_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    correlation_id: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    parent_span_id: Optional[str] = None
    node_id: str = Field(..., min_length=1)
    stage: Optional[str] = None
    attempt: int = Field(default=1, ge=1)
    status: str = Field(..., min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    duration_ms: float = Field(default=0.0, ge=0.0)
    retry_count: int = Field(default=0, ge=0)
    error_code: Optional[str] = None
    error_category: Optional[str] = None
    selected_route: Optional[str] = None
    state_version: str = Field(default="1.0.0")
    input_state_hash: Optional[str] = None
    output_state_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def scrub_metadata(cls, v: Any) -> Dict[str, Any]:
        """Strictly scrub credentials and secrets from telemetry metadata."""
        if isinstance(v, dict):
            return sanitize_sensitive_data(v)
        return {}


class AgentToolCallTelemetry(BaseModel):
    """Observability contract for auditing agent tool calls."""

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(..., min_length=1)
    agent_run_id: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    attempt: int = Field(default=1, ge=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: str = Field(default="SUCCESS")
    safe_input_fingerprint: str = Field(..., min_length=1)
    safe_output_fingerprint: str = Field(..., min_length=1)
    error_code: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def scrub_metadata(cls, v: Any) -> Dict[str, Any]:
        """Strictly scrub credentials from tool call metadata."""
        if isinstance(v, dict):
            return sanitize_sensitive_data(v)
        return {}


class AgentMetricsCollector:
    """Thread-safe, lightweight metrics collector for LangGraph agent pipeline executions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Reset all internal counters and metrics to zero."""
        with getattr(self, "_lock", threading.Lock()):
            self.executions_total: int = 0
            self.executions_successful: int = 0
            self.executions_failed: int = 0
            self.node_latencies: Dict[str, List[float]] = {}
            self.node_retries: int = 0
            self.node_timeouts: int = 0
            self.recovery_count: int = 0
            self.approval_waits: int = 0
            self.approval_resume_count: int = 0
            self.routing_failures: int = 0
            self.security_failures: int = 0

    def record_graph_execution(self, status: str, duration_ms: float) -> None:
        with self._lock:
            self.executions_total += 1
            if status in ("SUCCESS", "COMPLETED", "TERMINATED"):
                self.executions_successful += 1
            else:
                self.executions_failed += 1

    def record_node_latency(self, node_id: str, duration_ms: float) -> None:
        with self._lock:
            if node_id not in self.node_latencies:
                self.node_latencies[node_id] = []
            self.node_latencies[node_id].append(round(duration_ms, 2))

    def record_node_retry(self, node_id: Optional[str] = None) -> None:
        with self._lock:
            self.node_retries += 1

    def record_node_timeout(self, node_id: Optional[str] = None) -> None:
        with self._lock:
            self.node_timeouts += 1

    def record_recovery(self, decision: Optional[str] = None) -> None:
        with self._lock:
            self.recovery_count += 1

    def record_approval_wait(self) -> None:
        with self._lock:
            self.approval_waits += 1

    def record_approval_resume(self) -> None:
        with self._lock:
            self.approval_resume_count += 1

    def record_routing_failure(self) -> None:
        with self._lock:
            self.routing_failures += 1

    def record_security_failure(self) -> None:
        with self._lock:
            self.security_failures += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot dictionary of all tracked metrics."""
        with self._lock:
            avg_latencies = {}
            for node, lats in self.node_latencies.items():
                avg_latencies[node] = round(sum(lats) / len(lats), 2) if lats else 0.0

            return {
                "executions_total": self.executions_total,
                "executions_successful": self.executions_successful,
                "executions_failed": self.executions_failed,
                "node_retries": self.node_retries,
                "node_timeouts": self.node_timeouts,
                "recovery_count": self.recovery_count,
                "approval_waits": self.approval_waits,
                "approval_resume_count": self.approval_resume_count,
                "routing_failures": self.routing_failures,
                "security_failures": self.security_failures,
                "average_node_latencies_ms": avg_latencies,
            }


global_metrics_collector = AgentMetricsCollector()


class AgentObservability:
    """Central emitter of sanitized, structured observability events for agent executions."""

    @staticmethod
    def record_node_execution(
        run_id: str,
        organization_id: str,
        actor_id: str,
        request_id: str,
        correlation_id: str,
        trace_id: str,
        node_name: str,
        duration_ms: float,
        status: str,
        error_code: Optional[str] = None,
        retry_count: int = 0,
        step_count: int = 0,
        stage: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> NodeExecutionTelemetry:
        """Emit a structured telemetry event and log to application stream."""
        sanitized_meta = sanitize_sensitive_data(metadata) if metadata else {}
        telemetry = NodeExecutionTelemetry(
            run_id=run_id,
            organization_id=organization_id,
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            node_name=node_name,
            duration_ms=round(duration_ms, 2),
            status=status,
            stage=stage,
            error_code=error_code,
            retry_count=retry_count,
            step_count=step_count,
            metadata=sanitized_meta,
        )

        sanitized_extra = sanitize_sensitive_data(extra_data) if extra_data else {}
        log_payload = {**telemetry.model_dump(), **sanitized_extra}

        # Track metrics
        global_metrics_collector.record_node_latency(node_name, duration_ms)

        if status == "SUCCESS":
            logger.info("Agent node '%s' completed successfully in %.2fms: %s", node_name, duration_ms, log_payload)
        else:
            logger.warning("Agent node '%s' completed with status '%s' in %.2fms: %s", node_name, status, duration_ms, log_payload)

        return telemetry

    @classmethod
    def emit_node_telemetry(cls, telemetry: NodeExecutionTelemetry) -> NodeExecutionTelemetry:
        """Convenience method to emit a typed NodeExecutionTelemetry instance."""
        return cls.record_node_execution(
            run_id=telemetry.run_id,
            organization_id=telemetry.organization_id,
            actor_id=telemetry.actor_id,
            request_id=telemetry.request_id,
            correlation_id=telemetry.correlation_id,
            trace_id=telemetry.trace_id,
            node_name=telemetry.node_name,
            duration_ms=telemetry.duration_ms,
            status=telemetry.status,
            error_code=telemetry.error_code,
            retry_count=telemetry.retry_count,
            step_count=telemetry.step_count,
            stage=telemetry.stage,
            metadata=telemetry.metadata,
        )

    @staticmethod
    def record_run_telemetry(telemetry: AgentRunTelemetry) -> AgentRunTelemetry:
        """Record and log strongly typed AgentRunTelemetry."""
        log_payload = telemetry.model_dump(mode="json")

        if telemetry.status == "SUCCESS":
            logger.info(
                "Agent run telemetry for node '%s' [trace=%s, attempt=%d]: SUCCESS (%.2fms)",
                telemetry.node_id,
                telemetry.trace_id,
                telemetry.attempt,
                telemetry.duration_ms,
                extra={"telemetry": log_payload},
            )
        else:
            logger.warning(
                "Agent run telemetry for node '%s' [trace=%s, attempt=%d]: %s (%.2fms, code=%s, cat=%s)",
                telemetry.node_id,
                telemetry.trace_id,
                telemetry.attempt,
                telemetry.status,
                telemetry.duration_ms,
                telemetry.error_code,
                telemetry.error_category,
                extra={"telemetry": log_payload},
            )

        return telemetry

    @staticmethod
    def record_tool_call(telemetry: AgentToolCallTelemetry) -> AgentToolCallTelemetry:
        """Record and log strongly typed AgentToolCallTelemetry."""
        log_payload = telemetry.model_dump(mode="json")
        logger.info(
            "Agent tool call '%s' [run=%s, attempt=%d]: %s",
            telemetry.tool_name,
            telemetry.agent_run_id,
            telemetry.attempt,
            telemetry.status,
            extra={"tool_telemetry": log_payload},
        )
        return telemetry
