"""Provider adapters and provider-specific normalization packages."""

from app.integrations.providers.openweather import (
    DEFAULT_OPENWEATHER_BASE_URL,
    ONE_CALL_BASE_URL,
    OpenWeatherAdapter,
    OpenWeatherNormalizer,
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
]
