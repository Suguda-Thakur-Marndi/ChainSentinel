"""Central provider factory for resolving and constructing LLM backends."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.bedrock import BedrockLLMProvider
from app.llm.errors import LLMConfigurationError
from app.llm.mock import DeterministicMockLLMProvider


class LLMProviderFactory:
    """Factory resolving LLM provider implementations without arbitrary dynamic imports."""

    _SUPPORTED_PROVIDERS = frozenset({"bedrock", "mock"})

    @classmethod
    def create_provider(
        cls,
        provider_name: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMProvider:
        """Resolve and instantiate a validated LLM provider.
        
        Args:
            provider_name: 'bedrock' or 'mock'. Defaults to settings.LLM_PROVIDER.
            kwargs: Provider-specific configuration overrides (e.g. boto3_client, allowed_models).
        """
        raw_name = provider_name or getattr(settings, "LLM_PROVIDER", "bedrock")
        clean_name = raw_name.strip().lower()

        if clean_name not in cls._SUPPORTED_PROVIDERS:
            raise LLMConfigurationError(
                f"Unsupported LLM provider: '{raw_name}'. Supported providers: {sorted(list(cls._SUPPORTED_PROVIDERS))}",
                details={"requested_provider": raw_name, "supported": sorted(list(cls._SUPPORTED_PROVIDERS))},
            )

        if clean_name == "mock":
            return DeterministicMockLLMProvider(**kwargs)

        if clean_name == "bedrock":
            return BedrockLLMProvider(**kwargs)

        raise LLMConfigurationError(f"Provider resolution failed for '{clean_name}'.")


def get_llm_provider(provider_name: Optional[str] = None, **kwargs: Any) -> LLMProvider:
    """Convenience helper to obtain configured LLM provider."""
    return LLMProviderFactory.create_provider(provider_name=provider_name, **kwargs)
