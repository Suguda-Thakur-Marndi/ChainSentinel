"""Provider-neutral abstract base class for LLM backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from app.llm.contracts import LLMRequest, LLMResponse, LLMStreamChunk


class LLMProvider(ABC):
    """Abstract interface defining standard LLM provider operations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider implementation (e.g. 'bedrock', 'mock')."""
        ...

    @abstractmethod
    def invoke(self, request: LLMRequest) -> LLMResponse:
        """Synchronously execute a validated LLM completion request."""
        ...

    @abstractmethod
    def stream(self, request: LLMRequest) -> Iterator[LLMStreamChunk]:
        """Stream an incremental LLM completion request yielding text chunks."""
        ...
