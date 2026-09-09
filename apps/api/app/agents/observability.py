"""Observability, telemetry, and structured execution logging for LangGraph agents.

Emits structured telemetry events for every node execution and state transition,
while strictly scrubbing all credentials and never logging chain-of-thought.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger

logger = get_logger("agents")


class NodeExecutionTelemetry(BaseModel):
    """Structured telemetry payload capturing the execution metrics of an agent node."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., min_length=1)
    organization_id: str = Field(..., min_length=1)
    actor_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    correlation_id: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    node_name: str = Field(..., min_length=1)
    duration_ms: float = Field(..., ge=0.0)
    status: str = Field(..., min_length=1)
    error_code: Optional[str] = None
    retry_count: int = Field(default=0, ge=0)
    step_count: int = Field(default=0, ge=0)


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
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> NodeExecutionTelemetry:
        """Emit a structured telemetry event and log to application stream."""
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
            error_code=error_code,
            retry_count=retry_count,
            step_count=step_count,
        )

        sanitized_extra = sanitize_sensitive_data(extra_data) if extra_data else {}
        log_payload = {**telemetry.model_dump(), **sanitized_extra}

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
        )
