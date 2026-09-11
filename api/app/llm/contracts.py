"""Strongly typed contracts for LLM requests, responses, streaming chunks, and messages.

Enforces strict boundaries, input validation, and token usage contracts for AWS Bedrock
and Claude models.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_SYSTEM_PROMPT_CHARS = 65536  # 64 KB
MAX_MESSAGE_CONTENT_CHARS = 131072  # 128 KB
MAX_REQUEST_MESSAGES = 100
MAX_REQUEST_MAX_TOKENS = 8192


class MessageRole(str, Enum):
    """Allowed roles in LLM message sequences."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    """Strongly typed individual conversational turn."""

    model_config = ConfigDict(extra="forbid")

    role: MessageRole = Field(..., description="Role of the message sender")
    content: str = Field(..., min_length=1, description="Text content of the message")

    @field_validator("role", mode="before")
    @classmethod
    def parse_role(cls, v: Any) -> MessageRole:
        if isinstance(v, MessageRole):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            for r in MessageRole:
                if r.value == clean:
                    return r
            raise ValueError(f"Invalid message role '{v}'. Allowed roles: {[r.value for r in MessageRole]}")
        raise ValueError(f"Invalid role type: {type(v)}")

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Message content cannot be empty or whitespace only.")
        if len(v) > MAX_MESSAGE_CONTENT_CHARS:
            raise ValueError(
                f"Message content exceeds maximum allowed length of {MAX_MESSAGE_CONTENT_CHARS} characters."
            )
        return v


class TokenUsage(BaseModel):
    """Explicit token usage metrics returned by the provider."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)


class LLMRequest(BaseModel):
    """Strongly typed request contract for Bedrock/Claude invocation."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., min_length=1, description="Bedrock model identifier")
    messages: List[LLMMessage] = Field(..., min_length=1, description="List of messages in conversation")
    system_prompt: Optional[str] = Field(default=None, description="Optional system guidance prompt")
    temperature: Optional[float] = Field(default=0.0, ge=0.0, le=1.0, description="Sampling temperature")
    max_tokens: int = Field(default=4096, gt=0, le=MAX_REQUEST_MAX_TOKENS, description="Max tokens to generate")
    stop_sequences: Optional[List[str]] = Field(default=None, description="Optional custom stop sequences")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata for attribution and audit")

    # Identifiers for end-to-end tracing and isolation
    organization_id: Optional[str] = Field(default=None, description="Tenant organization identifier")
    request_id: Optional[str] = Field(default=None, description="API request correlation ID")
    correlation_id: Optional[str] = Field(default=None, description="Workflow correlation ID")
    trace_id: Optional[str] = Field(default=None, description="Distributed trace ID")
    agent_run_id: Optional[str] = Field(default=None, description="Agent run ID if invoked from graph")
    execution_id: Optional[str] = Field(default=None, description="Node or run execution ID")

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if len(clean) > MAX_SYSTEM_PROMPT_CHARS:
                raise ValueError(
                    f"System prompt exceeds maximum allowed size of {MAX_SYSTEM_PROMPT_CHARS} characters."
                )
            return clean
        return v

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: List[LLMMessage]) -> List[LLMMessage]:
        if not v:
            raise ValueError("LLMRequest must contain at least one message.")
        if len(v) > MAX_REQUEST_MESSAGES:
            raise ValueError(
                f"LLMRequest exceeds maximum of {MAX_REQUEST_MESSAGES} messages (got {len(v)})."
            )
        for idx, m in enumerate(v):
            if m.role == MessageRole.SYSTEM:
                from app.llm.errors import MessageContractError
                raise MessageContractError(
                    f"System messages are forbidden in messages sequence at index {idx}. "
                    "System instructions must be specified via system_prompt parameter.",
                    details={"index": idx},
                )
        return v

    @field_validator("metadata", mode="before")
    @classmethod
    def sanitize_request_metadata(cls, v: Any) -> Dict[str, Any]:
        if isinstance(v, dict):
            from app.llm.security import sanitize_sensitive_data
            return sanitize_sensitive_data(v)
        return {}


class LLMResponse(BaseModel):
    """Strongly typed normalized response contract from LLM provider."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., min_length=1, description="Name of the underlying provider (e.g. bedrock, mock)")
    model_id: str = Field(..., min_length=1, description="Model ID that fulfilled the request")
    text: str = Field(..., description="Generated text completion")
    input_tokens: Optional[int] = Field(default=None, ge=0, description="Count of prompt tokens")
    output_tokens: Optional[int] = Field(default=None, ge=0, description="Count of completion tokens")
    total_tokens: Optional[int] = Field(default=None, ge=0, description="Total count of tokens")
    stop_reason: Optional[str] = Field(default=None, description="Provider stop reason (e.g. end_turn, max_tokens)")
    request_id: Optional[str] = Field(default=None, description="Request ID associated with call")
    latency_ms: float = Field(..., ge=0.0, description="Provider invocation roundtrip latency in milliseconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Sanitized provider response metadata")


class LLMStreamChunk(BaseModel):
    """Incremental chunk emitted during streaming invocation."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., description="Incremental text fragment")
    index: int = Field(default=0, ge=0, description="Sequential chunk index")
    stop_reason: Optional[str] = Field(default=None, description="Stop reason if this is the final chunk")
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
