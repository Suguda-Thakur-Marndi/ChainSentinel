"""RiskWise external data ingestion foundation & provider architecture.

Provider-agnostic ingestion framework supporting weather, traffic, AIS, air,
rail, logistics, and news signals with a strongly-typed canonical normalization layer.
"""

from app.integrations.base import (
    BaseProviderAdapter,
    IngestionBatch,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderType,
    RawEvent,
)
from app.integrations.boundaries import (
    CanonicalEventStorage,
    InMemoryCanonicalEventStorage,
    InMemoryIngestionScheduler,
    InMemoryRawEventStorage,
    IngestionScheduler,
    RawEventStorage,
    ScheduledIngestionJob,
    ShipmentEventBridge,
    WebhookReceiver,
)
from app.integrations.canonical import (
    CanonicalEventType,
    CanonicalExternalEvent,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.integrations.config import (
    AuthMode,
    ProviderConfig,
    RateLimitConfig,
    RetryConfig,
    SecretResolver,
)
from app.integrations.errors import (
    DuplicateEventError,
    IngestionError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderDisabledError,
    ProviderNotFoundError,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderValidationError,
)
from app.integrations.idempotency import IdempotencyEngine
from app.integrations.normalizers import (
    BaseEventNormalizer,
    CoordinateValidator,
    DefaultEventNormalizer,
    MockAISNormalizer,
    MockTrafficNormalizer,
    MockWeatherNormalizer,
    NormalizationPipeline,
    TimestampNormalizer,
)
from app.integrations.rate_limiter import ProviderRateLimiter
from app.integrations.registry import ProviderRegistry, default_provider_registry
from app.integrations.retry import RetryPolicy
from app.integrations.service import (
    IngestionMetadata,
    IngestionResult,
    IngestionService,
    IngestionStatus,
)

__all__ = [
    # Base
    "ProviderType",
    "ProviderCapabilities",
    "ProviderHealthStatus",
    "ProviderHealthResult",
    "RawEvent",
    "IngestionBatch",
    "BaseProviderAdapter",
    # Canonical & Taxonomy
    "CanonicalEventType",
    "EventSourceType",
    "EventSeverity",
    "EventQuality",
    "EventLocation",
    "EntityCorrelation",
    "CanonicalExternalEvent",
    # Normalizers
    "BaseEventNormalizer",
    "DefaultEventNormalizer",
    "NormalizationPipeline",
    "TimestampNormalizer",
    "CoordinateValidator",
    "MockWeatherNormalizer",
    "MockAISNormalizer",
    "MockTrafficNormalizer",
    # Errors
    "IngestionError",
    "ProviderConfigurationError",
    "ProviderNotFoundError",
    "ProviderDisabledError",
    "ProviderAuthenticationError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderConnectionError",
    "ProviderResponseError",
    "ProviderValidationError",
    "ProviderPermanentError",
    "DuplicateEventError",
    # Config & Secrets
    "AuthMode",
    "RetryConfig",
    "RateLimitConfig",
    "ProviderConfig",
    "SecretResolver",
    # Retry & Idempotency & Rate Limit
    "RetryPolicy",
    "IdempotencyEngine",
    "ProviderRateLimiter",
    # Boundaries
    "RawEventStorage",
    "InMemoryRawEventStorage",
    "CanonicalEventStorage",
    "InMemoryCanonicalEventStorage",
    "ShipmentEventBridge",
    "ScheduledIngestionJob",
    "IngestionScheduler",
    "InMemoryIngestionScheduler",
    "WebhookReceiver",
    # Registry
    "ProviderRegistry",
    "default_provider_registry",
    # Service
    "IngestionStatus",
    "IngestionMetadata",
    "IngestionResult",
    "IngestionService",
]
