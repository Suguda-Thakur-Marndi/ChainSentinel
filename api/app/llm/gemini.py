"""Google Gemini API LLM Provider implementation using the official google-genai SDK.

Communicates with the Google Gemini API using server-side credentials, native
GenerateContentConfig parameterization, deterministic error taxonomy mapping,
bounded exponential backoff retries, and strict tenant/model security validation.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.contracts import LLMMessage, LLMRequest, LLMResponse, LLMStreamChunk, MessageRole
from app.llm.errors import (
    LLMAuthenticationError,
    LLMBaseError,
    LLMResponseError,
    map_gemini_exception,
)
from app.llm.observability import emit_llm_telemetry
from app.llm.retry import LLMRetryPolicy
from app.llm.security import validate_request_safety


class GeminiLLMProvider(LLMProvider):
    """Production LLM provider adapter for Google Gemini API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        allowed_models: Optional[List[str]] = None,
        client: Optional[Any] = None,
        retry_policy: Optional[LLMRetryPolicy] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        # Resolve API key strictly server-side without logging or persisting
        self._api_key = (
            api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self._allowed_models = (
            allowed_models
            if allowed_models is not None
            else list(getattr(settings, "GEMINI_ALLOWED_MODELS", [
                "gemini-2.5-flash",
                "gemini-2.5-pro",
                "gemini-2.0-flash",
                "gemini-1.5-flash",
                "gemini-1.5-pro",
            ]))
        )
        self._timeout_seconds = timeout_seconds or getattr(settings, "GEMINI_TIMEOUT_SECONDS", 30.0)
        self._retry_policy = retry_policy or LLMRetryPolicy(
            max_retries=getattr(settings, "GEMINI_MAX_RETRIES", 3),
            base_delay_seconds=getattr(settings, "GEMINI_BACKOFF_BASE_SECONDS", 0.5),
            max_delay_seconds=getattr(settings, "GEMINI_BACKOFF_MAX_SECONDS", 4.0),
        )

        if client is not None:
            self._client = client
        else:
            if not self._api_key or not self._api_key.strip():
                # In environments where credentials are not yet injected, client initialization
                # will fail closed when an actual API call is attempted.
                self._client = None
            else:
                from google import genai
                from google.genai import types

                # Configure timeout in milliseconds via HttpOptions
                timeout_ms = int(self._timeout_seconds * 1000)
                http_options = types.HttpOptions(timeout=timeout_ms)
                self._client = genai.Client(api_key=self._api_key.strip(), http_options=http_options)

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def allowed_models(self) -> List[str]:
        return list(self._allowed_models)

    def _ensure_client(self) -> Any:
        """Verify client availability or fail closed with typed authentication error."""
        if self._client is not None:
            return self._client

        # Attempt late binding from environment if key became available
        resolved_key = (
            self._api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not resolved_key or not resolved_key.strip():
            raise LLMAuthenticationError(
                "Gemini API key is missing. Set GEMINI_API_KEY in server-side environment or AWS Secrets Manager.",
                details={"provider": "gemini"},
            )

        from google import genai
        from google.genai import types

        timeout_ms = int(self._timeout_seconds * 1000)
        http_options = types.HttpOptions(timeout=timeout_ms)
        self._client = genai.Client(api_key=resolved_key.strip(), http_options=http_options)
        self._api_key = resolved_key.strip()
        return self._client

    def _build_contents_and_config(self, request: LLMRequest) -> tuple[List[Any], Any]:
        """Format request payload conforming to Google GenAI SDK types."""
        from google.genai import types

        contents: List[types.Content] = []
        for msg in request.messages:
            # Map RiskWise message roles to Gemini content roles: user -> user, assistant -> model
            role_str = "model" if msg.role == MessageRole.ASSISTANT else "user"
            contents.append(
                types.Content(
                    role=role_str,
                    parts=[types.Part.from_text(text=msg.content)],
                )
            )

        config_kwargs: Dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            config_kwargs["temperature"] = request.temperature
        if request.system_prompt:
            config_kwargs["system_instruction"] = request.system_prompt
        if request.stop_sequences:
            config_kwargs["stop_sequences"] = request.stop_sequences

        config = types.GenerateContentConfig(**config_kwargs)
        return contents, config

    def invoke(self, request: LLMRequest) -> LLMResponse:
        """Invoke Gemini model with deterministic validation and bounded retries."""
        # 1. Enforce strict pre-invocation validation and allowlisting
        validate_request_safety(request, self._allowed_models)
        client = self._ensure_client()

        contents, config = self._build_contents_and_config(request)

        attempt = 1
        max_attempts = max(1, self._retry_policy.max_retries + 1)

        while True:
            start_time = time.perf_counter()
            try:
                raw_response = client.models.generate_content(
                    model=request.model_id,
                    contents=contents,
                    config=config,
                )

                latency_ms = (time.perf_counter() - start_time) * 1000.0

                # Extract completion text safely
                text_content = ""
                if hasattr(raw_response, "text") and raw_response.text:
                    text_content = raw_response.text
                elif hasattr(raw_response, "candidates") and raw_response.candidates:
                    parts = []
                    for c in raw_response.candidates:
                        if hasattr(c, "content") and c.content and hasattr(c.content, "parts"):
                            for p in c.content.parts:
                                if hasattr(p, "text") and p.text:
                                    parts.append(p.text)
                    text_content = "".join(parts)

                # Extract token usage metadata safely (never invent counts)
                input_tokens = None
                output_tokens = None
                total_tokens = None
                if hasattr(raw_response, "usage_metadata") and raw_response.usage_metadata is not None:
                    u = raw_response.usage_metadata
                    input_tokens = getattr(u, "prompt_token_count", None)
                    output_tokens = getattr(u, "candidates_token_count", None)
                    total_tokens = getattr(u, "total_token_count", None)
                    if total_tokens is None and isinstance(input_tokens, int) and isinstance(output_tokens, int):
                        total_tokens = input_tokens + output_tokens

                # Extract finish reason
                stop_reason = None
                if hasattr(raw_response, "candidates") and raw_response.candidates:
                    c0 = raw_response.candidates[0]
                    if hasattr(c0, "finish_reason") and c0.finish_reason is not None:
                        stop_reason = str(c0.finish_reason)

                response_model = getattr(raw_response, "model_version", request.model_id) or request.model_id

                response = LLMResponse(
                    provider=self.provider_name,
                    model_id=response_model,
                    text=text_content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    stop_reason=stop_reason,
                    request_id=request.request_id,
                    latency_ms=round(latency_ms, 2),
                    metadata={"provider": "gemini", "finish_reason": stop_reason},
                )

                emit_llm_telemetry(
                    request=request,
                    response=response,
                    latency_ms=latency_ms,
                    attempt=attempt,
                )
                return response

            except Exception as exc:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                mapped_error = map_gemini_exception(exc)

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
        """Stream an incremental Gemini completion yielding validated chunks."""
        validate_request_safety(request, self._allowed_models)
        client = self._ensure_client()

        contents, config = self._build_contents_and_config(request)

        start_time = time.perf_counter()
        attempt = 1

        try:
            stream_response = client.models.generate_content_stream(
                model=request.model_id,
                contents=contents,
                config=config,
            )

            chunk_idx = 0
            accumulated_text = []

            for chunk in stream_response:
                chunk_text = getattr(chunk, "text", "") or ""
                if chunk_text:
                    accumulated_text.append(chunk_text)
                    yield LLMStreamChunk(
                        text=chunk_text,
                        index=chunk_idx,
                    )
                    chunk_idx += 1

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            full_text = "".join(accumulated_text)
            synthetic_resp = LLMResponse(
                provider=self.provider_name,
                model_id=request.model_id,
                text=full_text,
                latency_ms=round(latency_ms, 2),
            )
            emit_llm_telemetry(request, response=synthetic_resp, latency_ms=latency_ms, attempt=attempt)

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            mapped_error = map_gemini_exception(exc)
            emit_llm_telemetry(request, response=None, error=mapped_error, latency_ms=latency_ms, attempt=attempt)
            raise mapped_error from exc
