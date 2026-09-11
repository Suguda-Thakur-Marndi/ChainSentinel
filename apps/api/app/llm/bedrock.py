"""AWS Bedrock Runtime LLM Provider implementation for Anthropic Claude models.

Communicates with the bedrock-runtime service using standard AWS SDK credential resolution,
Anthropic Messages API formatting, deterministic error handling, and bounded retries.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterator, List, Optional

import boto3
from botocore.config import Config as BotoConfig

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, LLMResponse, LLMStreamChunk
from app.llm.errors import (
    LLMBaseError,
    LLMResponseError,
    map_boto_exception,
)
from app.llm.observability import emit_llm_telemetry
from app.llm.retry import LLMRetryPolicy
from app.llm.security import validate_request_safety

ANTHROPIC_BEDROCK_VERSION = "bedrock-2023-05-31"


class BedrockLLMProvider(LLMProvider):
    """Production adapter for AWS Bedrock Runtime executing Anthropic Claude models."""

    def __init__(
        self,
        region_name: Optional[str] = None,
        allowed_models: Optional[List[str]] = None,
        boto3_client: Optional[Any] = None,
        retry_policy: Optional[LLMRetryPolicy] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self._region_name = (
            region_name or settings.effective_bedrock_region
        ).strip()
        self._allowed_models = (
            allowed_models
            if allowed_models is not None
            else list(settings.BEDROCK_ALLOWED_MODELS)
        )
        self._timeout_seconds = timeout_seconds or settings.BEDROCK_TIMEOUT_SECONDS
        self._retry_policy = retry_policy or LLMRetryPolicy(
            max_retries=settings.BEDROCK_MAX_RETRIES,
            base_delay_seconds=settings.BEDROCK_BACKOFF_BASE_SECONDS,
            max_delay_seconds=settings.BEDROCK_BACKOFF_MAX_SECONDS,
        )

        if boto3_client is not None:
            self._client = boto3_client
        else:
            boto_config = BotoConfig(
                region_name=self._region_name,
                connect_timeout=min(self._timeout_seconds, 10.0),
                read_timeout=self._timeout_seconds,
                retries={"max_attempts": 0},  # RiskWise manages retries deterministically
            )
            self._client = boto3.client("bedrock-runtime", config=boto_config)

    @property
    def provider_name(self) -> str:
        return "bedrock"

    @property
    def region_name(self) -> str:
        return self._region_name

    @property
    def allowed_models(self) -> List[str]:
        return list(self._allowed_models)

    def _build_anthropic_payload(self, request: LLMRequest) -> Dict[str, Any]:
        """Format request payload conforming strictly to Anthropic Messages API on Bedrock."""
        messages_payload = []
        for msg in request.messages:
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            messages_payload.append({
                "role": role_val,
                "content": msg.content,
            })

        payload: Dict[str, Any] = {
            "anthropic_version": ANTHROPIC_BEDROCK_VERSION,
            "max_tokens": request.max_tokens,
            "messages": messages_payload,
        }

        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if request.stop_sequences:
            payload["stop_sequences"] = request.stop_sequences

        return payload

    def _parse_response_body(
        self,
        raw_body: bytes,
        request: LLMRequest,
        latency_ms: float,
    ) -> LLMResponse:
        """Parse raw Bedrock response JSON into normalized LLMResponse contract."""
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise LLMResponseError(
                f"Failed to parse Bedrock response JSON: {exc}",
                details={"raw_bytes_len": len(raw_body)},
            ) from exc

        # Extract text content from blocks
        content_blocks = parsed.get("content", [])
        text_parts: List[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        generated_text = "".join(text_parts)

        # Extract token usage metadata safely (never invent counts)
        usage = parsed.get("usage", {})
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_tokens = input_tokens + output_tokens

        stop_reason = parsed.get("stop_reason")
        response_model = parsed.get("model", request.model_id)

        metadata: Dict[str, Any] = {
            "bedrock_id": parsed.get("id"),
            "stop_sequence": parsed.get("stop_sequence"),
            "usage": usage,
        }

        return LLMResponse(
            provider=self.provider_name,
            model_id=response_model,
            text=generated_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            stop_reason=stop_reason,
            request_id=request.request_id,
            latency_ms=round(latency_ms, 2),
            metadata=metadata,
        )

    def invoke(self, request: LLMRequest) -> LLMResponse:
        """Invoke Claude model on Bedrock Runtime with deterministic validation and bounded retries."""
        # 1. Enforce strict pre-invocation validation and allowlisting
        validate_request_safety(request, self._allowed_models)

        payload = self._build_anthropic_payload(request)
        serialized_body = json.dumps(payload).encode("utf-8")

        attempt = 1
        max_attempts = max(1, self._retry_policy.max_retries + 1)

        while True:
            start_time = time.perf_counter()
            try:
                raw_response = self._client.invoke_model(
                    modelId=request.model_id,
                    body=serialized_body,
                    contentType="application/json",
                    accept="application/json",
                )

                latency_ms = (time.perf_counter() - start_time) * 1000.0
                body_stream = raw_response.get("body")
                raw_body = body_stream.read() if hasattr(body_stream, "read") else bytes(body_stream)

                response = self._parse_response_body(raw_body, request, latency_ms)

                emit_llm_telemetry(
                    request=request,
                    response=response,
                    latency_ms=latency_ms,
                    attempt=attempt,
                )
                return response

            except Exception as exc:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                mapped_error = map_boto_exception(exc)

                # Check if retry is allowed
                if attempt < max_attempts and self._retry_policy.is_retry_allowed(attempt, mapped_error):
                    delay = self._retry_policy.compute_backoff(attempt)
                    self._retry_policy.sleep(delay)
                    attempt += 1
                    continue

                # Final failure: emit telemetry and raise mapped error
                emit_llm_telemetry(
                    request=request,
                    response=None,
                    error=mapped_error,
                    latency_ms=latency_ms,
                    attempt=attempt,
                )
                raise mapped_error from exc

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Stream an incremental Claude completion from Bedrock Runtime."""
        validate_request_safety(request, self._allowed_models)

        payload = self._build_anthropic_payload(request)
        serialized_body = json.dumps(payload).encode("utf-8")

        start_time = time.perf_counter()
        attempt = 1

        try:
            response = self._client.invoke_model_with_response_stream(
                modelId=request.model_id,
                body=serialized_body,
                contentType="application/json",
                accept="application/json",
            )
            event_stream = response.get("body", [])
            chunk_idx = 0
            accumulated_text = []

            for event in event_stream:
                chunk = event.get("chunk")
                if not chunk:
                    continue

                chunk_bytes = chunk.get("bytes")
                if not chunk_bytes:
                    continue

                data = json.loads(chunk_bytes.decode("utf-8"))
                event_type = data.get("type")

                if event_type == "content_block_delta":
                    delta = data.get("delta", {})
                    text_frag = delta.get("text", "")
                    accumulated_text.append(text_frag)
                    yield LLMStreamChunk(
                        text=text_frag,
                        index=chunk_idx,
                    )
                    chunk_idx += 1
                elif event_type == "message_delta":
                    stop_reason = data.get("delta", {}).get("stop_reason")
                    usage = data.get("usage", {})
                    out_tok = usage.get("output_tokens")
                    yield LLMStreamChunk(
                        text="",
                        index=chunk_idx,
                        stop_reason=stop_reason,
                        output_tokens=out_tok,
                    )
                    chunk_idx += 1

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            # Record successful streaming execution
            full_text = "".join(accumulated_text)
            synthetic_resp = LLMResponse(
                provider=self.provider_name,
                model_id=request.model_id,
                text=full_text,
                latency_ms=latency_ms,
            )
            emit_llm_telemetry(request, response=synthetic_resp, latency_ms=latency_ms, attempt=attempt)

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            mapped_error = map_boto_exception(exc)
            emit_llm_telemetry(request, response=None, error=mapped_error, latency_ms=latency_ms, attempt=attempt)
            raise mapped_error from exc
