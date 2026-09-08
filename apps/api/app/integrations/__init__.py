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
    DEFAULT_OPENSKY_BASE_URL,
    DEFAULT_OPENSKY_TOKEN_URL,
    DEFAULT_OPENWEATHER_BASE_URL,
    DEFAULT_TFNSW_ALERTS_URL,
    DEFAULT_TFNSW_BASE_URL,
    DEFAULT_TFNSW_TRIP_UPDATES_URL,
    DEFAULT_TFNSW_VEHICLE_POSITIONS_URL,
    DEFAULT_TOMTOM_FLOW_URL,
    DEFAULT_TOMTOM_INCIDENTS_URL,
    DELAY_MAJOR_THRESHOLD_SECONDS,
    DELAY_MEDIUM_THRESHOLD_SECONDS,
    DELAY_MINOR_THRESHOLD_SECONDS,
    ONE_CALL_BASE_URL,
    AISStreamAdapter,
    AISStreamNormalizer,
    AISStreamSubscription,
    AISWebSocketTransport,
    MockAISWebSocketTransport,
    OpenSkyAdapter,
    OpenSkyBoundingBox,
    OpenSkyNormalizer,
    OpenSkyOAuthTokenManager,
    OpenSkyStateVector,
    OpenWeatherAdapter,
    OpenWeatherNormalizer,
    RailAdapter,
    RailFeedConfig,
    RailFeedType,
    RailNormalizer,
    DEFAULT_KARRIO_BASE_URL,
    DEFAULT_KARRIO_TRACKERS_ENDPOINT,
    KarrioAdapter,
    KarrioIncidentReason,
    KarrioNormalizer,
    KarrioTracker,
    KarrioTrackingEvent,
    KarrioTrackingStatus,
    KarrioWebhookReceiver,
    TomTomAdapter,
    TomTomNormalizer,
    create_karrio_polling_job,
    create_opensky_polling_job,
    create_rail_polling_job,
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
    # Providers (OpenWeather, TomTom, AISStream, OpenSky, Rail)
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
    "DEFAULT_OPENSKY_BASE_URL",
    "DEFAULT_OPENSKY_TOKEN_URL",
    "OpenSkyAdapter",
    "OpenSkyNormalizer",
    "OpenSkyOAuthTokenManager",
    "OpenSkyBoundingBox",
    "OpenSkyStateVector",
    "create_opensky_polling_job",
    "DEFAULT_TFNSW_BASE_URL",
    "DEFAULT_TFNSW_TRIP_UPDATES_URL",
    "DEFAULT_TFNSW_VEHICLE_POSITIONS_URL",
    "DEFAULT_TFNSW_ALERTS_URL",
    "DELAY_MINOR_THRESHOLD_SECONDS",
    "DELAY_MEDIUM_THRESHOLD_SECONDS",
    "DELAY_MAJOR_THRESHOLD_SECONDS",
    "RailAdapter",
    "RailNormalizer",
    "RailFeedType",
    "RailFeedConfig",
    "create_rail_polling_job",
    "DEFAULT_KARRIO_BASE_URL",
    "DEFAULT_KARRIO_TRACKERS_ENDPOINT",
    "KarrioAdapter",
    "KarrioNormalizer",
    "KarrioTracker",
    "KarrioTrackingEvent",
    "KarrioTrackingStatus",
    "KarrioIncidentReason",
    "KarrioWebhookReceiver",
    "create_karrio_polling_job",
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

if not default_provider_registry.is_registered(OpenSkyAdapter.provider_name):
    default_provider_registry.register(
        OpenSkyAdapter,
        default_config=ProviderConfig(
            provider_name=OpenSkyAdapter.provider_name,
            provider_type=OpenSkyAdapter.provider_type,
            base_url=DEFAULT_OPENSKY_BASE_URL,
            auth_mode=AuthMode.OAUTH2,
            secret_ref="env:OPENSKY_CLIENT_SECRET",
            extra_settings={"client_id_ref": "env:OPENSKY_CLIENT_ID"},
            rate_limit=RateLimitConfig(requests_per_minute=60),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )

if not default_provider_registry.is_registered(RailAdapter.provider_name):
    default_provider_registry.register(
        RailAdapter,
        default_config=ProviderConfig(
            provider_name=RailAdapter.provider_name,
            provider_type=RailAdapter.provider_type,
            base_url=DEFAULT_TFNSW_TRIP_UPDATES_URL,
            auth_mode=AuthMode.API_KEY_HEADER,
            secret_ref="env:TFNSW_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=60),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )

if not default_provider_registry.is_registered(KarrioAdapter.provider_name):
    default_provider_registry.register(
        KarrioAdapter,
        default_config=ProviderConfig(
            provider_name=KarrioAdapter.provider_name,
            provider_type=KarrioAdapter.provider_type,
            base_url=DEFAULT_KARRIO_BASE_URL,
            auth_mode=AuthMode.API_KEY_HEADER,
            secret_ref="env:KARRIO_API_KEY",
            rate_limit=RateLimitConfig(requests_per_minute=120),
            retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
        ),
    )


