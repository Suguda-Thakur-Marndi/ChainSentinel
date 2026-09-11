"""Observability, telemetry, metrics, and structured logging for LLM operations.

Tracks request attribution, latency, token usage, and status while strictly preventing
the logging of full prompt texts, completions, or sensitive secrets.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger
from app.llm.contracts import LLMRequest, LLMResponse

logger = get_logger("llm.observability")


def compute_content_fingerprint(text: Optional[str]) -> str:
    """Generate collision-resistant SHA-256 fingerprint for audit logging without leaking text."""
    if not text:
        return "empty"
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def compute_request_fingerprint(request: LLMRequest) -> str:
    """Generate SHA-256 fingerprint representing conversation input structure."""
    parts = []
    if request.system_prompt:
        parts.append(f"sys:{request.system_prompt.strip()}")
    for msg in request.messages:
        parts.append(f"{msg.role.value}:{msg.content.strip()}")
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class LLMTelemetryRecord(BaseModel):
    """Structured telemetry payload for an LLM provider invocation."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    latency_ms: float = Field(..., ge=0.0)
    attempt: int = Field(default=1, ge=1)
    organization_id: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
    agent_run_id: Optional[str] = None
    execution_id: Optional[str] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    error_category: Optional[str] = None
    safe_prompt_fingerprint: str = Field(..., min_length=1)
    safe_response_fingerprint: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LLMMetricsCollector:
    """Thread-safe collector for LLM performance and operational metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Reset all metrics to zero."""
        with getattr(self, "_lock", threading.Lock()):
            self.invocations_total: int = 0
            self.invocations_successful: int = 0
            self.invocations_failed: int = 0
            self.throttling_count: int = 0
            self.timeout_count: int = 0
            self.total_input_tokens: int = 0
            self.total_output_tokens: int = 0
            self.latencies_ms: List[float] = []

    def record_call(
        self,
        status: str,
        latency_ms: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        error_category: Optional[str] = None,
    ) -> None:
        with self._lock:
            self.invocations_total += 1
            if status == "SUCCESS":
                self.invocations_successful += 1
            else:
                self.invocations_failed += 1

            if error_category == "LLM_THROTTLING_ERROR":
                self.throttling_count += 1
            elif error_category == "LLM_TIMEOUT_ERROR":
                self.timeout_count += 1

            if input_tokens:
                self.total_input_tokens += input_tokens
            if output_tokens:
                self.total_output_tokens += output_tokens

            self.latencies_ms.append(round(latency_ms, 2))

    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            avg_latency = (
                round(sum(self.latencies_ms) / len(self.latencies_ms), 2)
                if self.latencies_ms
                else 0.0
            )
            return {
                "invocations_total": self.invocations_total,
                "invocations_successful": self.invocations_successful,
                "invocations_failed": self.invocations_failed,
                "throttling_count": self.throttling_count,
                "timeout_count": self.timeout_count,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "average_latency_ms": avg_latency,
            }


global_llm_metrics = LLMMetricsCollector()


def emit_llm_telemetry(
    request: LLMRequest,
    response: Optional[LLMResponse] = None,
    error: Optional[Exception] = None,
    latency_ms: float = 0.0,
    attempt: int = 1,
) -> LLMTelemetryRecord:
    """Emit a sanitized structured telemetry event and update global metrics."""
    status = "SUCCESS" if response is not None else "FAILED"
    error_category = getattr(error, "category", None)
    if error_category and hasattr(error_category, "value"):
        error_category = error_category.value
    elif error:
        error_category = error.__class__.__name__

    input_tokens = response.input_tokens if response else None
    output_tokens = response.output_tokens if response else None
    total_tokens = response.total_tokens if response else None

    prompt_fp = compute_request_fingerprint(request)
    resp_fp = compute_content_fingerprint(response.text) if response else None

    record = LLMTelemetryRecord(
        provider=response.provider if response else "bedrock",
        model_id=request.model_id,
        status=status,
        latency_ms=round(latency_ms, 2),
        attempt=attempt,
        organization_id=request.organization_id,
        request_id=request.request_id,
        correlation_id=request.correlation_id,
        trace_id=request.trace_id,
        agent_run_id=request.agent_run_id,
        execution_id=request.execution_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        error_category=error_category,
        safe_prompt_fingerprint=prompt_fp,
        safe_response_fingerprint=resp_fp,
    )

    # Update thread-safe in-memory metrics
    global_llm_metrics.record_call(
        status=status,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error_category=error_category,
    )

    # Structured log line without raw prompt or completions
    log_data = record.model_dump(mode="json")
    if status == "SUCCESS":
        logger.info(
            "LLM invocation succeeded in %.2fms (model: %s, in_tok: %s, out_tok: %s): %s",
            latency_ms,
            request.model_id,
            input_tokens,
            output_tokens,
            log_data,
        )
    else:
        logger.warning(
            "LLM invocation failed after attempt %d (error: %s): %s",
            attempt,
            error_category,
            log_data,
        )

    return record
