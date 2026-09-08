"""Provider adapters and provider-specific normalization packages."""

from app.integrations.providers.aisstream import (
    DEFAULT_AISSTREAM_URL,
    AISStreamAdapter,
    AISStreamNormalizer,
    AISStreamSubscription,
    AISWebSocketTransport,
    MockAISWebSocketTransport,
)
from app.integrations.providers.opensky import (
    DEFAULT_OPENSKY_BASE_URL,
    DEFAULT_OPENSKY_TOKEN_URL,
    OpenSkyAdapter,
    OpenSkyBoundingBox,
    OpenSkyNormalizer,
    OpenSkyOAuthTokenManager,
    OpenSkyStateVector,
    create_opensky_polling_job,
)
from app.integrations.providers.openweather import (
    DEFAULT_OPENWEATHER_BASE_URL,
    ONE_CALL_BASE_URL,
    OpenWeatherAdapter,
    OpenWeatherNormalizer,
)
from app.integrations.providers.rail import (
    DEFAULT_TFNSW_ALERTS_URL,
    DEFAULT_TFNSW_BASE_URL,
    DEFAULT_TFNSW_TRIP_UPDATES_URL,
    DEFAULT_TFNSW_VEHICLE_POSITIONS_URL,
    DELAY_MAJOR_THRESHOLD_SECONDS,
    DELAY_MEDIUM_THRESHOLD_SECONDS,
    DELAY_MINOR_THRESHOLD_SECONDS,
    RailAdapter,
    RailFeedConfig,
    RailFeedType,
    RailNormalizer,
    create_rail_polling_job,
)
from app.integrations.providers.tomtom import (
    DEFAULT_TOMTOM_FLOW_URL,
    DEFAULT_TOMTOM_INCIDENTS_URL,
    TomTomAdapter,
    TomTomNormalizer,
)

__all__ = [
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
]

