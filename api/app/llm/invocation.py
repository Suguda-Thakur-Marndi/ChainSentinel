"""Safe, strongly typed Claude invocation service with structured output validation.

Handles budget enforcement, Markdown code-fence stripping, strict JSON parsing
(strictly avoiding eval/exec), Pydantic schema validation, and structured error handling
for LLM invocations.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm.security import sanitize_sensitive_data
from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.contracts import LLMMessage, LLMRequest, LLMResponse, MessageRole, TokenUsage
from app.llm.errors import (
    InvocationConfigurationError,
    InvocationResponseError,
    LLMBaseError,
    LLMResponseError,
    LLMValidationError,
    PromptBudgetExceededError,
    PromptValidationError,
    StructuredOutputValidationError,
    sanitize_error_message,
)
from app.llm.prompts import ClaudePrompt

T = TypeVar("T", bound=BaseModel)

# Default enterprise context and token budgets
DEFAULT_MAX_PROMPT_CHARS = 200_000  # ~50k tokens
DEFAULT_MAX_CONTEXT_CHARS = 150_000
DEFAULT_MAX_OUTPUT_TOKENS = 8192

# Regex to safely extract content inside markdown JSON or generic code blocks
CODE_FENCE_PATTERN = re.compile(
    r"```(?:json)?\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


class PromptBudget(BaseModel):
    """Deterministic context and token budget configuration for Claude prompts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_prompt_chars: int = Field(
        default=DEFAULT_MAX_PROMPT_CHARS,
        gt=0,
        description="Maximum allowed character count for the total prompt (system + messages)",
    )
    max_context_chars: int = Field(
        default=DEFAULT_MAX_CONTEXT_CHARS,
        gt=0,
        description="Maximum allowed character count across structured context blocks",
    )
    max_output_tokens: int = Field(
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        gt=0,
        description="Maximum allowed completion tokens for the invocation",
    )


class ClaudeInvocationResult(BaseModel, Generic[T]):
    """Typed result representing the outcome of a safe Claude invocation."""

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="Whether invocation and structured parsing succeeded")
    status: str = Field(..., description="Status string: SUCCESS, FAILED, BUDGET_EXCEEDED, VALIDATION_ERROR")
    parsed_output: Optional[T] = Field(default=None, description="Parsed and validated Pydantic model instance")
    raw_text: Optional[str] = Field(default=None, description="Raw completion text if available")
    provider: str = Field(..., min_length=1, description="Underlying provider name (e.g. bedrock, mock)")
    model_id: str = Field(..., min_length=1, description="Model ID used for invocation")
    prompt_fingerprint: str = Field(..., min_length=1, description="Deterministic fingerprint of the input prompt")
    latency_ms: float = Field(..., ge=0.0, description="Roundtrip latency in milliseconds")
    token_usage: Optional[TokenUsage] = Field(default=None, description="Token usage metrics if supplied by provider")
    error_category: Optional[str] = Field(default=None, description="Error category if invocation failed")
    error_message: Optional[str] = Field(default=None, description="Sanitized error message if invocation failed")
    request_id: Optional[str] = Field(default=None, description="API request ID")
    correlation_id: Optional[str] = Field(default=None, description="Workflow correlation ID")
    trace_id: Optional[str] = Field(default=None, description="Distributed trace ID")
    agent_run_id: Optional[str] = Field(default=None, description="Agent run ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Sanitized invocation metadata")


def strip_markdown_code_fences(raw_text: str) -> str:
    """Extract raw JSON content from Markdown code fences (e.g. ```json ... ```).
    
    Handles whitespace, multi-line blocks, bare JSON without fences, and fences embedded within narrative text.
    """
    clean = raw_text.strip()
    if not clean:
        return ""

    match = CODE_FENCE_PATTERN.search(clean)
    if match:
        return match.group(1).strip()

    if clean.startswith("```"):
        lines = clean.split("\n")
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()

    return clean


def parse_json_safely(raw_text: str) -> Any:
    """Parse JSON string safely using standard json.loads.
    
    CRITICAL: Never uses eval() or exec().
    Raises:
        StructuredOutputValidationError: If JSON decoding fails.
    """
    clean = strip_markdown_code_fences(raw_text)
    if not clean:
        raise StructuredOutputValidationError("Cannot parse empty response text as JSON.")

    try:
        return json.loads(clean)
    except Exception as exc:
        raise StructuredOutputValidationError(
            f"Failed to parse LLM response as valid JSON: {exc}",
            details={"raw_sample": clean[:200]},
        ) from exc


def validate_structured_output(parsed_json: Any, schema_cls: Type[T]) -> T:
    """Validate parsed JSON dictionary against a strongly typed Pydantic model.
    
    Raises:
        StructuredOutputValidationError: If the payload violates the schema contract.
    """
    if not isinstance(parsed_json, dict):
        raise StructuredOutputValidationError(
            f"Expected JSON object (dict) matching {schema_cls.__name__}, got {type(parsed_json).__name__}.",
            details={"type": type(parsed_json).__name__},
        )

    try:
        return schema_cls.model_validate(parsed_json)
    except ValidationError as val_err:
        raise StructuredOutputValidationError(
            f"LLM structured response failed schema validation for {schema_cls.__name__}: {val_err.error_count()} errors.",
            details={"errors": val_err.errors()},
        ) from val_err


class ClaudeInvocationService:
    """Safe invocation wrapper coordinating Claude prompts, providers, budget enforcement, and structured schemas."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        model_id: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        budget: Optional[PromptBudget] = None,
    ) -> None:
        if provider is not None:
            self._provider = provider
        else:
            from app.llm.factory import get_llm_provider
            self._provider = get_llm_provider()
        self._model_id = model_id or settings.BEDROCK_MODEL_ID
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._budget = budget or PromptBudget()

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def temperature(self) -> float:
        return self._temperature

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def budget(self) -> PromptBudget:
        return self._budget

    def _check_budget(self, prompt: ClaudePrompt, max_tokens: int) -> None:
        """Enforce character and token budgets prior to any provider invocation.
        
        Raises:
            PromptBudgetExceededError: If prompt, context, or token request exceeds budget.
        """
        # 1. Total prompt character length
        total_prompt_chars = len(prompt.system_instruction) + sum(len(m.content) for m in prompt.messages)
        if total_prompt_chars > self._budget.max_prompt_chars:
            raise PromptBudgetExceededError(
                f"Total prompt size ({total_prompt_chars} chars) exceeds maximum allowed budget ({self._budget.max_prompt_chars} chars).",
                details={
                    "total_chars": total_prompt_chars,
                    "budget_limit": self._budget.max_prompt_chars,
                },
            )

        # 2. Context blocks character length
        if prompt.context_blocks:
            total_context_chars = sum(len(b.content) for b in prompt.context_blocks)
            if total_context_chars > self._budget.max_context_chars:
                raise PromptBudgetExceededError(
                    f"Structured context size ({total_context_chars} chars) exceeds maximum allowed context budget ({self._budget.max_context_chars} chars).",
                    details={
                        "context_chars": total_context_chars,
                        "context_budget_limit": self._budget.max_context_chars,
                    },
                )

        # 3. Maximum output token boundary
        if max_tokens > self._budget.max_output_tokens:
            raise PromptBudgetExceededError(
                f"Requested max_tokens ({max_tokens}) exceeds maximum allowed output token budget ({self._budget.max_output_tokens}).",
                details={
                    "requested_max_tokens": max_tokens,
                    "budget_limit": self._budget.max_output_tokens,
                },
            )

    def invoke(
        self,
        prompt: ClaudePrompt,
        response_schema: Optional[Type[T]] = None,
        organization_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        agent_run_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        fail_closed: bool = True,
    ) -> ClaudeInvocationResult[T]:
        """Invoke Claude with boundary checks, budget enforcement, and structured schema parsing.
        
        Returns:
            ClaudeInvocationResult containing validated output or typed error diagnostics.
        """
        start_time = time.perf_counter()

        if not isinstance(prompt, ClaudePrompt):
            err = PromptValidationError(f"Expected ClaudePrompt instance, got {type(prompt).__name__}.")
            if fail_closed:
                raise err
            return ClaudeInvocationResult(
                success=False,
                status="VALIDATION_ERROR",
                provider=self._provider.provider_name,
                model_id=self._model_id,
                prompt_fingerprint="invalid",
                latency_ms=0.0,
                error_category="PROMPT_VALIDATION_ERROR",
                error_message=str(err),
            )

        # 1. Enforce Budget before provider invocation
        try:
            self._check_budget(prompt, self._max_tokens)
        except PromptBudgetExceededError as budget_err:
            if fail_closed:
                raise
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return ClaudeInvocationResult(
                success=False,
                status="BUDGET_EXCEEDED",
                provider=self._provider.provider_name,
                model_id=self._model_id,
                prompt_fingerprint=prompt.prompt_fingerprint,
                latency_ms=duration_ms,
                error_category="PROMPT_BUDGET_EXCEEDED",
                error_message=str(budget_err),
                request_id=request_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )

        metadata = sanitize_sensitive_data(dict(prompt.context_metadata))
        metadata.update({
            "prompt_purpose": prompt.purpose,
            "prompt_version": prompt.version,
            "prompt_fingerprint": prompt.prompt_fingerprint,
        })

        request = LLMRequest(
            model_id=self._model_id,
            messages=prompt.messages,
            system_prompt=prompt.system_instruction,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            metadata=metadata,
            organization_id=organization_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            execution_id=execution_id,
        )

        try:
            raw_response = self._provider.invoke(request)
        except Exception as exc:
            if fail_closed:
                raise
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            category = getattr(exc, "category", "LLM_PROVIDER_ERROR")
            if hasattr(category, "value"):
                category = category.value
            return ClaudeInvocationResult(
                success=False,
                status="FAILED",
                provider=self._provider.provider_name,
                model_id=self._model_id,
                prompt_fingerprint=prompt.prompt_fingerprint,
                latency_ms=duration_ms,
                error_category=str(category),
                error_message=sanitize_error_message(str(exc)),
                request_id=request_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
                agent_run_id=agent_run_id,
            )

        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # 3. Parse and validate structured output if schema is provided
        parsed_model: Optional[T] = None
        if response_schema is not None:
            try:
                parsed_json = parse_json_safely(raw_response.text)
                parsed_model = validate_structured_output(parsed_json, response_schema)
            except StructuredOutputValidationError as schema_err:
                if fail_closed:
                    raise
                return ClaudeInvocationResult(
                    success=False,
                    status="VALIDATION_ERROR",
                    raw_text=raw_response.text,
                    provider=raw_response.provider,
                    model_id=raw_response.model_id,
                    prompt_fingerprint=prompt.prompt_fingerprint,
                    latency_ms=duration_ms,
                    token_usage=TokenUsage(
                        input_tokens=raw_response.input_tokens,
                        output_tokens=raw_response.output_tokens,
                        total_tokens=raw_response.total_tokens,
                    ),
                    error_category="STRUCTURED_OUTPUT_VALIDATION_ERROR",
                    error_message=str(schema_err),
                    request_id=request_id,
                    correlation_id=correlation_id,
                    trace_id=trace_id,
                    agent_run_id=agent_run_id,
                )

        token_usage = None
        if raw_response.input_tokens is not None or raw_response.output_tokens is not None:
            token_usage = TokenUsage(
                input_tokens=raw_response.input_tokens,
                output_tokens=raw_response.output_tokens,
                total_tokens=raw_response.total_tokens,
            )

        return ClaudeInvocationResult(
            success=True,
            status="SUCCESS",
            parsed_output=parsed_model,
            raw_text=raw_response.text,
            provider=raw_response.provider,
            model_id=raw_response.model_id,
            prompt_fingerprint=prompt.prompt_fingerprint,
            latency_ms=duration_ms,
            token_usage=token_usage,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            metadata=sanitize_sensitive_data(raw_response.metadata),
        )

    def invoke_structured(
        self,
        prompt: ClaudePrompt,
        response_schema: Type[T],
        organization_id: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        agent_run_id: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> Tuple[T, LLMResponse]:
        """Invoke Claude with strict boundary checks and parse into strongly typed response contract.
        
        Preserved for exact backwards compatibility with Phase 10 Steps 3–6.
        Returns:
            Tuple containing (validated_pydantic_instance, raw_llm_response).
        """
        if not isinstance(prompt, ClaudePrompt):
            raise PromptValidationError(f"Expected ClaudePrompt instance, got {type(prompt).__name__}.")

        # Enforce budget before provider call
        self._check_budget(prompt, self._max_tokens)

        metadata = sanitize_sensitive_data(dict(prompt.context_metadata))
        metadata.update({
            "prompt_purpose": prompt.purpose,
            "prompt_version": prompt.version,
            "prompt_fingerprint": prompt.prompt_fingerprint,
        })

        request = LLMRequest(
            model_id=self._model_id,
            messages=prompt.messages,
            system_prompt=prompt.system_instruction,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            metadata=metadata,
            organization_id=organization_id,
            request_id=request_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            execution_id=execution_id,
        )

        raw_response = self._provider.invoke(request)

        # Parse and validate structured output
        parsed_json = parse_json_safely(raw_response.text)
        validated_model = validate_structured_output(parsed_json, response_schema)

        return validated_model, raw_response
