"""Abstract Base Provider for Live Map Tracking Subsystems."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Coroutine, List, Optional
from app.services.tracking.models import LiveMapObject, ProviderHealth, ProviderHealthStatus


class TrackingProvider(ABC):
    """Abstract base class representing an external or internal geospatial telemetry provider."""

    name: str = "base"
    purpose: str = "general"

    def __init__(self, on_update: Optional[Callable[[List[LiveMapObject]], Coroutine[None, None, None]]] = None):
        self._on_update = on_update
        self._is_running = False

    @abstractmethod
    async def start(self) -> None:
        """Start provider background worker/stream."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully terminate background worker/stream."""
        pass

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Return runtime health status and telemetry metrics."""
        pass

    @abstractmethod
    async def get_objects(self) -> List[LiveMapObject]:
        """Retrieve current cached live map objects."""
        pass
