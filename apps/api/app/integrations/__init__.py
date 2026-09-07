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
from app.integrations.providers import (
    DEFAULT_AISSTREAM_URL,
    DEFAULT_OPENWEATHER_BASE_URL,
    DEFAULT_TOMTOM_FLOW_URL,
    DEFAULT_TOMTOM_INCIDENTS_URL,
    ONE_CALL_BASE_URL,
    AISStreamAdapter,
    AISStreamNormalizer,
    AISStreamSubscription,
    AISWebSocketTransport,
    MockAISWebSocketTransport,
    OpenWeatherAdapter,
    OpenWeatherNormalizer,
    TomTomAdapter,
    TomTomNormalizer,
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
    # Providers (OpenWeather, TomTom, AISStream)
    "DEFAULT_OPENWEATHER_BASE_URL",
    "ONE_CALL_BASE_URL",
    "OpenWeatherAdapter",
    "OpenWeatherNormalizer",
    "DEFAULT_TOMTOM_FLOW_URL",
    "DEFAULT_TOMTOM_INCIDENTS_URL",
    "TomTomAdapter",
    "TomTomNormalizer",
    "DEFAULT_AISSTREAM_URL",
    "AISStreamAdapter",
    "AISStreamNormalizer",
    "AISStreamSubscription",
    "AISWebSocketTransport",
    "MockAISWebSocketTransport",
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

# Pre-register built-in provider adapters into default registry
if not default_provider_registry.is_registered(OpenWeatherAdapter.provider_name):
    default_provider_registry.register(
        OpenWeatherAdapter,
        default_config=ProviderConfig(
            provider_name=OpenWeatherAdapter.provider_name,
            provider_type=OpenWeatherAdapter.provider_type,
            base_url=DEFAULT_OPENWEATHER_BASE_URL,
            auth_mode=AuthMode.API_KEY_QUERY,
            secret_ref="env:OPENWEATHER_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=60),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )

if not default_provider_registry.is_registered(TomTomAdapter.provider_name):
    default_provider_registry.register(
        TomTomAdapter,
        default_config=ProviderConfig(
            provider_name=TomTomAdapter.provider_name,
            provider_type=TomTomAdapter.provider_type,
            base_url=DEFAULT_TOMTOM_FLOW_URL,
            auth_mode=AuthMode.API_KEY_QUERY,
            secret_ref="env:TOMTOM_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=60),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )

if not default_provider_registry.is_registered(AISStreamAdapter.provider_name):
    default_provider_registry.register(
        AISStreamAdapter,
        default_config=ProviderConfig(
            provider_name=AISStreamAdapter.provider_name,
            provider_type=AISStreamAdapter.provider_type,
            base_url=DEFAULT_AISSTREAM_URL,
            auth_mode=AuthMode.API_KEY_HEADER,
            secret_ref="env:AISSTREAM_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=120),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )

