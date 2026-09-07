"""Provider registry and factory.

Manages registration, configuration, capability inspection, and lifecycle
of provider adapters with strict duplicate prevention and clear errors.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Type

from app.integrations.base import BaseProviderAdapter, ProviderCapabilities
from app.integrations.config import ProviderConfig
from app.integrations.errors import (
    ProviderConfigurationError,
    ProviderNotFoundError,
)

logger = logging.getLogger("riskwise.integrations.registry")


class ProviderRegistry:
    """Thread-safe provider registry and adapter factory."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._adapters: Dict[str, Type[BaseProviderAdapter]] = {}
        self._configs: Dict[str, ProviderConfig] = {}

    def register(
        self,
        adapter_cls: Type[BaseProviderAdapter],
        default_config: Optional[ProviderConfig] = None,
        overwrite: bool = False,
    ) -> None:
        """Register a provider adapter class and optional default config.

        Raises:
            ProviderConfigurationError: If already registered and overwrite is False.
        """
        if not issubclass(adapter_cls, BaseProviderAdapter):
            raise ProviderConfigurationError(
                f"Class {adapter_cls.__name__} must inherit from BaseProviderAdapter",
                provider_name=getattr(adapter_cls, "provider_name", "unknown"),
            )

        name = adapter_cls.provider_name.lower().strip()
        if not name:
            raise ProviderConfigurationError("Provider adapter must specify a non-empty provider_name")

        with self._lock:
            if name in self._adapters and not overwrite:
                raise ProviderConfigurationError(
                    f"Provider '{name}' is already registered. Use overwrite=True to replace.",
                    provider_name=name,
                )

            self._adapters[name] = adapter_cls
            if default_config is not None:
                self._configs[name] = default_config
            logger.info("Registered provider adapter: %s (overwrite=%s)", name, overwrite)

    def get_adapter_cls(self, provider_name: str) -> Type[BaseProviderAdapter]:
        """Retrieve adapter class by provider name.

        Raises:
            ProviderNotFoundError: If provider is not registered.
        """
        key = provider_name.lower().strip()
        with self._lock:
            adapter_cls = self._adapters.get(key)
        if not adapter_cls:
            raise ProviderNotFoundError(f"Provider '{provider_name}' is not registered", provider_name=provider_name)
        return adapter_cls

    def create_adapter(
        self,
        provider_name: str,
        config: Optional[ProviderConfig] = None,
    ) -> BaseProviderAdapter:
        """Instantiate an adapter with effective configuration."""
        adapter_cls = self.get_adapter_cls(provider_name)
        effective_config = config or self.get_config(provider_name)
        return adapter_cls(config=effective_config)

    def get_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """Get stored default configuration for a provider."""
        key = provider_name.lower().strip()
        with self._lock:
            return self._configs.get(key)

    def set_config(self, provider_name: str, config: ProviderConfig) -> None:
        """Set or update configuration for a provider."""
        key = provider_name.lower().strip()
        with self._lock:
            if key not in self._adapters:
                raise ProviderNotFoundError(
                    f"Cannot set config for unregistered provider '{provider_name}'",
                    provider_name=provider_name,
                )
            self._configs[key] = config

    def get_capabilities(self, provider_name: str) -> ProviderCapabilities:
        """Get capabilities declared by a registered provider."""
        adapter_cls = self.get_adapter_cls(provider_name)
        return adapter_cls.capabilities

    def is_registered(self, provider_name: str) -> bool:
        """Check if a provider is registered."""
        key = provider_name.lower().strip()
        with self._lock:
            return key in self._adapters

    def list_providers(self) -> List[Dict[str, Any]]:
        """List summary of all registered providers and their metadata."""
        with self._lock:
            items = []
            for name, cls in self._adapters.items():
                cfg = self._configs.get(name)
                caps = cls.capabilities
                items.append({
                    "provider_name": cls.provider_name,
                    "provider_type": cls.provider_type.value,
                    "enabled": cfg.enabled if cfg else True,
                    "capabilities": {
                        "supports_polling": caps.supports_polling,
                        "supports_webhooks": caps.supports_webhooks,
                        "supports_streaming": caps.supports_streaming,
                        "supports_batch": caps.supports_batch,
                        "supports_health_check": caps.supports_health_check,
                        "supported_modalities": caps.supported_modalities,
                    },
                })
            return items

    def unregister(self, provider_name: str) -> bool:
        """Unregister a provider."""
        key = provider_name.lower().strip()
        with self._lock:
            removed = self._adapters.pop(key, None) is not None
            self._configs.pop(key, None)
            return removed

    def clear(self) -> None:
        """Clear all registered adapters and configurations (useful for test isolation)."""
        with self._lock:
            self._adapters.clear()
            self._configs.clear()


# Default singleton instance for application use
default_provider_registry = ProviderRegistry()
