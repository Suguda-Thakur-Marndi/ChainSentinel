"""Production-Grade OpenTelemetry Observability & GenAI Semantic Conventions.

Provides distributed tracing, metrics, and operation correlation across:
- HTTP API endpoints
- Database queries & transactions
- Bedrock LLM invocations (conforming to GenAI semantic conventions)
- LangGraph agent workflow nodes & execution steps
- Action dispatch & evidence verification

CRITICAL SECURITY RULE:
Never records raw prompts, completions, passwords, tokens, API keys, or confidential document content.
Message payload capture is strictly disabled by default.
All tracing operations fail safely and never disrupt operational request execution.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
import time
from typing import Any, Dict, Iterator, List, Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode, Span
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("core.telemetry")


# OpenTelemetry GenAI Semantic Conventions (Standard 2024/2025 conventions)
class GenAISemanticConventions:
    SYSTEM = "gen_ai.system"
    REQUEST_MODEL = "gen_ai.request.model"
    RESPONSE_MODEL = "gen_ai.response.model"
    USAGE_PROMPT_TOKENS = "gen_ai.usage.prompt_tokens"
    USAGE_COMPLETION_TOKENS = "gen_ai.usage.completion_tokens"
    RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
    OPERATION_NAME = "gen_ai.operation.name"

    # RiskWise Domain Correlative Attributes
    ORGANIZATION_ID = "riskwise.organization.id"
    USER_ID = "riskwise.user.id"
    REQUEST_ID = "riskwise.request.id"
    AGENT_RUN_ID = "riskwise.agent.run_id"
    AGENT_NAME = "riskwise.agent.name"
    WORKFLOW_ID = "riskwise.workflow.id"
    STAGE = "riskwise.stage"
    ACTION_TYPE = "riskwise.action.type"
    VERIFICATION_STATUS = "riskwise.verification.status"


class TelemetryManager:
    """Singleton managing OpenTelemetry tracer and meters with fail-safe error isolation."""

    _instance: Optional[TelemetryManager] = None

    def __init__(self) -> None:
        self.service_name = "riskwise-api"
        self.environment = settings.APP_ENV
        self.capture_message_payloads = False  # Mandatory security perimeter: disabled by default

        resource = Resource.create({
            "service.name": self.service_name,
            "deployment.environment": self.environment,
            "service.version": settings.VERSION,
        })

        provider = TracerProvider(resource=resource)
        # In production without an OTLP endpoint configured, keep spans in-memory/no-op
        # to guarantee zero overhead and zero network failures.
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter()
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception as e:
                logger.warning(f"OTLP exporter initialization skipped ({e}).")

        self.provider = provider
        self.tracer = provider.get_tracer("riskwise.tracer", settings.VERSION)

    @classmethod
    def get_instance(cls) -> TelemetryManager:
        if cls._instance is None:
            cls._instance = TelemetryManager()
        return cls._instance

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Span]:
        """Start a trace span with automatic exception handling and duration tracking."""
        attrs = attributes or {}
        span = self.tracer.start_span(name, attributes=attrs)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            span.end()

    def record_llm_invocation(
        self,
        model_id: str,
        duration_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        finish_reason: str = "stop",
        status: str = "success",
        error: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> None:
        """Record an LLM call strictly conforming to OpenTelemetry GenAI semantic conventions."""
        try:
            with self.start_span("gen_ai.chat") as span:
                span.set_attribute(GenAISemanticConventions.SYSTEM, "aws.bedrock")
                span.set_attribute(GenAISemanticConventions.REQUEST_MODEL, model_id)
                span.set_attribute(GenAISemanticConventions.RESPONSE_MODEL, model_id)
                span.set_attribute(GenAISemanticConventions.OPERATION_NAME, "chat")
                span.set_attribute(GenAISemanticConventions.USAGE_PROMPT_TOKENS, max(0, prompt_tokens))
                span.set_attribute(GenAISemanticConventions.USAGE_COMPLETION_TOKENS, max(0, completion_tokens))
                span.set_attribute(GenAISemanticConventions.RESPONSE_FINISH_REASONS, [finish_reason])
                span.set_attribute("latency_ms", duration_ms)

                if organization_id:
                    span.set_attribute(GenAISemanticConventions.ORGANIZATION_ID, organization_id)

                if error or status != "success":
                    span.set_status(Status(StatusCode.ERROR, error or "LLM invocation error"))
                else:
                    span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            logger.debug(f"Telemetry record_llm_invocation failure ({exc}); silently ignored.")

    def record_agent_step(
        self,
        agent_name: str,
        step_name: str,
        organization_id: str,
        workflow_id: str,
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        """Record an agent workflow step span."""
        try:
            with self.start_span(f"agent.{agent_name}.{step_name}") as span:
                span.set_attribute(GenAISemanticConventions.AGENT_NAME, agent_name)
                span.set_attribute("agent.step", step_name)
                span.set_attribute(GenAISemanticConventions.ORGANIZATION_ID, organization_id)
                span.set_attribute(GenAISemanticConventions.WORKFLOW_ID, workflow_id)
                if error:
                    span.set_status(Status(StatusCode.ERROR, error))
                else:
                    span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            logger.debug(f"Telemetry record_agent_step failure ({exc}); silently ignored.")


global_telemetry = TelemetryManager.get_instance()


class TelemetryMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware for W3C distributed tracing and request correlation."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        tracer = global_telemetry.tracer
        path = request.url.path
        method = request.method
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", "unknown")

        span_name = f"HTTP {method} {path}"
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.target", path)
            span.set_attribute("http.client_ip", request.client.host if request.client else "unknown")
            span.set_attribute(GenAISemanticConventions.REQUEST_ID, request_id)

            trace_id = format(span.get_span_context().trace_id, "032x")
            request.state.trace_id = trace_id

            try:
                response = await call_next(request)
                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
                else:
                    span.set_status(Status(StatusCode.OK))
                response.headers["X-Trace-ID"] = trace_id
                return response
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
