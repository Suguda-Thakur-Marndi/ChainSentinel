"""Provider-agnostic interface, data models, and contracts for external signal ingestion."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


def _generate_event_uuid() -> str:
    return str(uuid.uuid4())


class ProviderType(str, Enum):
    """Broad categories of external supply chain signal providers."""
    WEATHER = "WEATHER"
    TRAFFIC = "TRAFFIC"
    ROAD_TRAFFIC = "ROAD_TRAFFIC"
    AIS = "AIS"
    OCEAN_AIS = "OCEAN_AIS"
    AIR = "AIR"
    RAIL = "RAIL"
    TRACKING = "TRACKING"
    LOGISTICS_TRACKING = "LOGISTICS_TRACKING"
    NEWS_RESEARCH = "NEWS_RESEARCH"
    CUSTOM = "CUSTOM"


class ProviderCapabilities(BaseModel):
    """Declared capabilities and operational bounds of a provider adapter."""
    model_config = ConfigDict(extra="allow")

    supports_polling: bool = True
    supports_webhook: bool = False
    supports_webhooks: bool = False
    supports_streaming: bool = False
    supports_batch: bool = True
    supports_health_check: bool = True
    supports_historical: bool = False
    max_batch_size: int = Field(default=100, ge=1, le=10000)
    supported_entities: list[str] = Field(default_factory=list)
    supported_modalities: list[str] = Field(default_factory=list)


class ProviderHealthStatus(str, Enum):
    """Health check outcome of a provider connection."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNCONFIGURED = "UNCONFIGURED"


class ProviderHealthResult(BaseModel):
    """Diagnostic health report for an external provider adapter."""
    model_config = ConfigDict(extra="allow")

    provider_name: Optional[str] = None
    status: ProviderHealthStatus
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_successful_check: Optional[datetime] = None
    details: dict[str, Any] = Field(default_factory=dict)


class RawEvent(BaseModel):
    """Storage boundary envelope representing raw, un-normalized external signals."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    event_id: str = Field(default_factory=_generate_event_uuid)
    provider_name: str
    provider_type: Optional[ProviderType] = None
    provider_event_id: Optional[str] = None
    fingerprint: Optional[str] = None
    source_timestamp: Optional[datetime] = None
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    org_id: Optional[str] = None  # None indicates global public data; non-None indicates tenant-scoped stream
    event_type: Optional[str] = None

    @property
    def id(self) -> str:
        return self.event_id

    @property
    def organization_id(self) -> Optional[str]:
        return self.org_id

    @organization_id.setter
    def organization_id(self, value: Optional[str]) -> None:
        self.org_id = value


class IngestionBatch(BaseModel):
    """Batch container for multi-item ingestion outcomes."""
    model_config = ConfigDict(extra="allow")

    batch_id: str = Field(default_factory=_generate_event_uuid)
    provider_name: str
    events: list[RawEvent] = Field(default_factory=list)
    cursor: Optional[str] = None
    has_more: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BaseProviderAdapter(ABC):
    """Abstract Base Class for all RiskWise external data provider adapters."""

    provider_name: str = "base"
    provider_type: ProviderType = ProviderType.CUSTOM
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(self, config: Any = None, secret: Optional[str] = None) -> None:
        self.config = config
        self._secret = secret

    def health_check(self) -> ProviderHealthResult:
        """Execute a connectivity and authentication health probe."""
        return ProviderHealthResult(
            provider_name=getattr(self, "provider_name", "unknown"),
            status=ProviderHealthStatus.HEALTHY,
            message="Base health check passed",
        )

    @abstractmethod
    def fetch(self, **kwargs: Any) -> IngestionBatch:
        """Fetch raw external signals from the provider."""
        pass

    def parse_webhook(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> RawEvent:
        """Parse incoming webhook event payload into a RawEvent boundary object."""
        raise NotImplementedError(
            f"Provider '{getattr(self, 'provider_name', 'unknown')}' does not implement webhook reception."
        )

    def close(self) -> None:
        """Release any underlying client sessions or socket connections."""
        pass

    def __enter__(self) -> "BaseProviderAdapter":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
