"""Tracking services package for RiskWise 2.0 / ChainSentinel.

Initializes the central LiveMapAggregator and registers telemetry providers.
"""
from __future__ import annotations

from typing import Optional
from app.services.tracking.aggregator import LiveMapAggregator
from app.services.tracking.aisstream_provider import AISStreamProvider
from app.services.tracking.aircraft_provider import AircraftTrackingProvider
from app.services.tracking.internal_provider import InternalRiskWiseProvider
from app.services.tracking.mobility_provider import MobilityTrackingProvider
from app.services.tracking.models import (
    LiveMapObject,
    LiveMapResponse,
    ProviderHealth,
    ProviderHealthStatus,
    ProvidersHealthResponse,
)
from app.services.tracking.project44_provider import Project44TrackingProvider
from app.services.tracking.tomtom_provider import TomTomTrackingProvider
from app.services.tracking.weather_provider import WeatherTrackingProvider

_aggregator_instance: Optional[LiveMapAggregator] = None


def get_tracking_aggregator() -> LiveMapAggregator:
    """Return the singleton instance of LiveMapAggregator with all providers registered."""
    global _aggregator_instance
    if _aggregator_instance is None:
        from pathlib import Path
        import dotenv
        _base_dir = Path(__file__).resolve().parent.parent.parent.parent
        _root_env = _base_dir / ".env"
        if _root_env.exists():
            dotenv.load_dotenv(_root_env, override=False)
        agg = LiveMapAggregator()

        # 1. AISStream (Maritime Vessels)
        ais = AISStreamProvider(on_update=agg.handle_provider_update)
        agg.register_provider(ais)

        # 2. Aircraft Provider (OpenSky / Aviation)
        aircraft = AircraftTrackingProvider(on_update=agg.handle_provider_update)
        agg.register_provider(aircraft)

        # 3. Project44 (Logistics & Shipments)
        p44 = Project44TrackingProvider(on_update=agg.handle_provider_update)
        agg.register_provider(p44)

        # 4. OpenWeather (Corridor Meteorological Hazards)
        weather = WeatherTrackingProvider(on_update=agg.handle_provider_update)
        agg.register_provider(weather)

        # 5. TomTom (Port Gate & Road Freight Delays)
        tomtom = TomTomTrackingProvider(on_update=agg.handle_provider_update)
        agg.register_provider(tomtom)

        # 6. Mobility Database (Public Transit / Rail)
        mobility = MobilityTrackingProvider(on_update=agg.handle_provider_update)
        agg.register_provider(mobility)

        # 7. Internal RiskWise Supply Chain Assets (Verified Shipments & Ports)
        internal = InternalRiskWiseProvider(on_update=agg.handle_provider_update)
        agg.register_provider(internal)

        _aggregator_instance = agg

    return _aggregator_instance


__all__ = [
    "get_tracking_aggregator",
    "LiveMapAggregator",
    "LiveMapObject",
    "LiveMapResponse",
    "ProviderHealth",
    "ProviderHealthStatus",
    "ProvidersHealthResponse",
]
