"""Deterministic mock LLM provider for unit tests and local isolation.

Provides zero-external-dependency, reproducible LLM completions, predictable token
telemetry, failure simulation, timeout simulation, and request recording.
Production code must never utilize this provider.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Union

from app.llm.base import LLMProvider
from app.llm.contracts import LLMRequest, LLMResponse, LLMStreamChunk
from app.llm.errors import LLMThrottlingError, LLMTimeoutError
from app.llm.observability import emit_llm_telemetry
from app.llm.security import validate_request_safety


class DeterministicMockLLMProvider(LLMProvider):
    """Deterministic, zero-network LLM provider strictly for tests."""

    def __init__(
        self,
        allowed_models: Optional[List[str]] = None,
        canned_response: Optional[str] = None,
    ) -> None:
        self._allowed_models = allowed_models or [
            "anthropic.claude-sonnet-4-6",
            "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "mock-claude",
        ]
        self._canned_response = canned_response
        self.recorded_requests: List[LLMRequest] = []
        self._injected_failure: Optional[Union[Exception, Callable[[], Any]]] = None
        self._throttling_budget: int = 0
        self._simulated_timeout_delay: Optional[float] = None

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def allowed_models(self) -> List[str]:
        return list(self._allowed_models)

    def set_canned_response(self, text: Optional[str]) -> None:
        """Configure canned completion text."""
        self._canned_response = text

    def inject_failure(self, failure: Optional[Union[Exception, Callable[[], Any]]]) -> None:
        """Inject an exception or callable to be raised on next invocation."""
        self._injected_failure = failure

    def simulate_throttling(self, failure_count: int = 1) -> None:
        """Simulate a number of 429 throttling errors before succeeding."""
        self._throttling_budget = failure_count

    def simulate_timeout(self, delay_seconds: float = 0.05) -> None:
        """Simulate a timeout exception."""
        self._simulated_timeout_delay = delay_seconds

    def clear(self) -> None:
        """Reset all state, recorded requests, and failure mocks."""
        self.recorded_requests.clear()
        self._injected_failure = None
        self._throttling_budget = 0
        self._simulated_timeout_delay = None

    def _generate_deterministic_text(self, request: LLMRequest) -> str:
        if self._canned_response is not None:
            return self._canned_response

        # Deterministic text seeded from prompt
        last_msg = request.messages[-1].content if request.messages else "empty"
        digest = hashlib.sha256(last_msg.encode("utf-8")).hexdigest()[:8]
        return f"[MOCK_CLAUDE_COMPLETION:{digest}] Deterministic response for model {request.model_id}."

    def invoke(self, request: LLMRequest) -> LLMResponse:
        """Execute deterministic mock completion with security enforcement."""
        validate_request_safety(request, self._allowed_models)
        self.recorded_requests.append(request)

        start_time = time.perf_counter()

        # 1. Check injected timeout simulation
        if self._simulated_timeout_delay is not None:
            time.sleep(self._simulated_timeout_delay)
            self._simulated_timeout_delay = None
            err = LLMTimeoutError(
                f"Simulated timeout exceeded for model {request.model_id}.",
                details={"model_id": request.model_id},
            )
            emit_llm_telemetry(request, response=None, error=err, latency_ms=10.0)
            raise err

        # 2. Check throttling budget
        if self._throttling_budget > 0:
            self._throttling_budget -= 1
            err = LLMThrottlingError(
                "Simulated Bedrock rate limit exceeded (ThrottlingException).",
                details={"budget_remaining": self._throttling_budget},
            )
            emit_llm_telemetry(request, response=None, error=err, latency_ms=5.0)
            raise err

        # 3. Check injected failure
        if self._injected_failure is not None:
            failure = self._injected_failure
            self._injected_failure = None
            if callable(failure):
                failure()
            elif isinstance(failure, Exception):
                emit_llm_telemetry(request, response=None, error=failure, latency_ms=5.0)
                raise failure

        # 4. Generate deterministic completion
        completion_text = self._generate_deterministic_text(request)

        # Deterministic predictable token calculation: ~4 chars per token
        prompt_chars = sum(len(m.content) for m in request.messages)
        if request.system_prompt:
            prompt_chars += len(request.system_prompt)
        input_tokens = max(1, prompt_chars // 4)
        output_tokens = max(1, len(completion_text) // 4)
        total_tokens = input_tokens + output_tokens

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        if latency_ms < 0.1:
            latency_ms = 0.5  # Realistic minimum for tests

        response = LLMResponse(
            provider=self.provider_name,
            model_id=request.model_id,
            text=completion_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            stop_reason="end_turn",
            request_id=request.request_id,
            latency_ms=round(latency_ms, 2),
            metadata={"mock": True, "call_count": len(self.recorded_requests)},
        )

        emit_llm_telemetry(request, response=response, latency_ms=latency_ms)
        return response

    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Yield deterministic chunks for streaming tests."""
        validate_request_safety(request, self._allowed_models)
        self.recorded_requests.append(request)

        text = self._generate_deterministic_text(request)
        words = text.split(" ")
        accumulated_out_tokens = 0

        for idx, word in enumerate(words):
            frag = word + (" " if idx < len(words) - 1 else "")
            accumulated_out_tokens += max(1, len(frag) // 4)
            is_final = idx == len(words) - 1
            yield LLMStreamChunk(
                text=frag,
                index=idx,
                stop_reason="end_turn" if is_final else None,
                output_tokens=accumulated_out_tokens if is_final else None,
            )
