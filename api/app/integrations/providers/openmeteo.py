"""Open-Meteo weather and marine forecast provider adapter and normalizer.

Ingests high-resolution global atmospheric forecasts and specialized ocean marine telemetry
(significant wave height, wave period, swell, wind gusts) from the Open-Meteo API.
Operates with zero required authentication for standard tiers (CC BY 4.0), providing
resilient complementary meteorological coverage for shipping lanes and ports.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import httpx

from app.integrations.base import (
    BaseProviderAdapter,
    IngestionBatch,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderType,
    RawEvent,
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
    IngestionError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
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
    TimestampNormalizer,
)
from app.integrations.retry import RetryPolicy

logger = logging.getLogger("riskwise.integrations.providers.openmeteo")

DEFAULT_OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_OPENMETEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
DEFAULT_HEALTH_CHECK_COORDS = (51.5074, -0.1278)  # London coordinates for non-destructive probe

# WMO Weather interpretation codes (WW) severity mapping
WMO_CODE_DESCRIPTIONS: Dict[int, Tuple[str, str]] = {
    0: ("Clear sky", "CLEAR"),
    1: ("Mainly clear", "MOSTLY_CLEAR"),
    2: ("Partly cloudy", "PARTLY_CLOUDY"),
    3: ("Overcast", "OVERCAST"),
    45: ("Fog", "FOG"),
    48: ("Depositing rime fog", "FOG"),
    51: ("Light drizzle", "DRIZZLE"),
    53: ("Moderate drizzle", "DRIZZLE"),
    55: ("Dense drizzle", "DRIZZLE"),
    61: ("Slight rain", "RAIN"),
    63: ("Moderate rain", "RAIN"),
    65: ("Heavy rain", "HEAVY_RAIN"),
    71: ("Slight snow fall", "SNOW"),
    73: ("Moderate snow fall", "SNOW"),
    75: ("Heavy snow fall", "HEAVY_SNOW"),
    77: ("Snow grains", "SNOW"),
    80: ("Slight rain showers", "RAIN_SHOWERS"),
    81: ("Moderate rain showers", "RAIN_SHOWERS"),
    82: ("Violent rain showers", "VIOLENT_RAIN"),
    85: ("Slight snow showers", "SNOW_SHOWERS"),
    86: ("Heavy snow showers", "SNOW_SHOWERS"),
    95: ("Thunderstorm", "THUNDERSTORM"),
    96: ("Thunderstorm with slight hail", "THUNDERSTORM_HAIL"),
    99: ("Thunderstorm with heavy hail", "SEVERE_THUNDERSTORM"),
}


class OpenMeteoAdapter(BaseProviderAdapter):
    """Production provider adapter for Open-Meteo Weather & Marine API."""

    provider_name: str = "openmeteo"
    provider_type: ProviderType = ProviderType.WEATHER
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=True,
        max_batch_size=100,
        supported_entities=["location", "route", "facility", "port", "shipment"],
        supported_modalities=["weather", "marine", "waves", "wind", "alerts"],
    )

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        secret: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
        secret_resolver: Optional[SecretResolver] = None,
        idempotency_engine: Optional[IdempotencyEngine] = None,
    ) -> None:
        if config is None:
            config = ProviderConfig(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                base_url=DEFAULT_OPENMETEO_FORECAST_URL,
                auth_mode=AuthMode.NONE,
                secret_ref="env:OPENMETEO_API_KEY",
                rate_limit=RateLimitConfig(requests_per_minute=120),
                retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
            )
        super().__init__(config=config, secret=secret)
        self.secret_resolver = secret_resolver or SecretResolver()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self._external_client = http_client
        self._internal_client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Provide active HTTP client instance."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            timeout = getattr(self.config, "timeout_seconds", 10.0)
            headers = {"User-Agent": "ChainSentinel/2.0 (SupplyChainRiskDefense)"}
            self._internal_client = httpx.Client(timeout=timeout, headers=headers)
        return self._internal_client

    def close(self) -> None:
        """Release underlying HTTP resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    @classmethod
    def compute_observation_fingerprint(
        cls,
        latitude: float,
        longitude: float,
        observation_timestamp: Union[int, float, datetime, str],
        weather_code: Optional[int] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute a deterministic, collision-resistant SHA-256 fingerprint."""
        rounded_lat = round(float(latitude), 4)
        rounded_lon = round(float(longitude), 4)
        if isinstance(observation_timestamp, (int, float)):
            ts_str = str(int(observation_timestamp))
        elif isinstance(observation_timestamp, datetime):
            ts_str = str(int(observation_timestamp.timestamp()))
        else:
            ts_str = str(observation_timestamp)

        obs_payload = {
            "lat": rounded_lat,
            "lon": rounded_lon,
            "ts": ts_str,
            "weather_code": weather_code,
        }
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="openmeteo",
            payload=obs_payload,
            organization_id=org_id,
        )

    def fetch(
        self,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        include_marine: bool = False,
        locations: Optional[List[Dict[str, float]]] = None,
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        org_id: Optional[str] = None,
        route_id: Optional[str] = None,
        shipment_id: Optional[str] = None,
        port_id: Optional[str] = None,
        facility_id: Optional[str] = None,
    ) -> IngestionBatch:
        """Fetch real-time atmospheric or marine observations for given coordinates."""
        target_lat = latitude if latitude is not None else lat
        target_lon = longitude if longitude is not None else lon

        query_locations: List[Dict[str, Any]] = []
        if locations:
            query_locations.extend(locations)
        elif target_lat is not None and target_lon is not None:
            query_locations.append({"lat": target_lat, "lon": target_lon})
        else:
            raise ProviderValidationError(
                "Open-Meteo requires either (latitude, longitude) or locations list.",
                provider_name=self.provider_name,
            )

        events: List[RawEvent] = []
        fetched_at = datetime.now(timezone.utc)
        effective_org_id = organization_id or org_id

        for loc in query_locations:
            l_lat = loc.get("lat") or loc.get("latitude")
            l_lon = loc.get("lon") or loc.get("longitude")
            if l_lat is None or l_lon is None:
                continue

            CoordinateValidator.validate(l_lat, l_lon)

            # Atmospheric forecast parameters
            params: Dict[str, Any] = {
                "latitude": l_lat,
                "longitude": l_lon,
                "current": (
                    "temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "precipitation,rain,weather_code,surface_pressure,"
                    "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
                ),
                "timezone": "UTC",
            }

            # Optional API key support if configured
            api_key = self._secret or self.secret_resolver.resolve_secret(
                getattr(self.config, "secret_ref", None) or "env:OPENMETEO_API_KEY"
            )
            if api_key:
                params["apikey"] = api_key

            target_url = getattr(self.config, "base_url", None) or DEFAULT_OPENMETEO_FORECAST_URL

            try:
                resp = self.client.get(target_url, params=params)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"Open-Meteo request timed out: {exc}",
                    provider_name=self.provider_name,
                ) from exc
            except httpx.ConnectError as exc:
                raise ProviderConnectionError(
                    f"Open-Meteo network connection failed: {exc}",
                    provider_name=self.provider_name,
                ) from exc
            except Exception as exc:
                raise ProviderConnectionError(
                    f"Open-Meteo request failed: {exc}",
                    provider_name=self.provider_name,
                ) from exc

            if resp.status_code == 400:
                raise ProviderValidationError(
                    f"Open-Meteo HTTP 400 Bad Request: {resp.text[:200]}",
                    provider_name=self.provider_name,
                    status_code=400,
                )
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
                raise ProviderRateLimitError(
                    "Open-Meteo daily or hourly quota limit reached (HTTP 429)",
                    provider_name=self.provider_name,
                    retry_after_seconds=retry_seconds,
                )
            if resp.status_code >= 500:
                raise ProviderResponseError(
                    f"Open-Meteo service error HTTP {resp.status_code}",
                    provider_name=self.provider_name,
                    status_code=resp.status_code,
                )
            if resp.status_code != 200:
                raise ProviderResponseError(
                    f"Open-Meteo unexpected HTTP status {resp.status_code}",
                    provider_name=self.provider_name,
                    status_code=resp.status_code,
                )

            try:
                data = resp.json()
            except Exception as exc:
                raise ProviderResponseError(
                    f"Open-Meteo response not valid JSON: {exc}",
                    provider_name=self.provider_name,
                ) from exc

            current = data.get("current") or {}
            time_str = current.get("time")
            try:
                source_ts = TimestampNormalizer.parse_to_utc(time_str) if time_str else fetched_at
            except Exception:
                source_ts = fetched_at

            # Optional Marine telemetry query
            marine_data: Dict[str, Any] = {}
            if include_marine:
                try:
                    marine_params = {
                        "latitude": l_lat,
                        "longitude": l_lon,
                        "current": "wave_height,wave_direction,wave_period,wind_wave_height,swell_wave_height",
                        "timezone": "UTC",
                    }
                    if api_key:
                        marine_params["apikey"] = api_key
                    m_resp = self.client.get(DEFAULT_OPENMETEO_MARINE_URL, params=marine_params)
                    if m_resp.status_code == 200:
                        marine_data = m_resp.json().get("current", {})
                except Exception as m_exc:
                    logger.debug("Open-Meteo marine query non-fatal fallback: %s", m_exc)

            combined_payload = {
                "forecast": data,
                "marine": marine_data,
                "requested_lat": l_lat,
                "requested_lon": l_lon,
            }

            fingerprint = self.compute_observation_fingerprint(
                latitude=l_lat,
                longitude=l_lon,
                observation_timestamp=time_str or fetched_at,
                weather_code=current.get("weather_code"),
                org_id=effective_org_id,
            )

            metadata: Dict[str, Any] = {
                "correlation_id": correlation_id,
                "route_id": route_id or loc.get("route_id"),
                "shipment_id": shipment_id or loc.get("shipment_id"),
                "port_id": port_id or loc.get("port_id"),
                "facility_id": facility_id or loc.get("facility_id"),
                "source_url": target_url,
            }

            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=f"om_{round(l_lat, 4)}_{round(l_lon, 4)}_{time_str or int(fetched_at.timestamp())}",
                fingerprint=fingerprint,
                source_timestamp=source_ts,
                ingested_at=fetched_at,
                raw_payload=combined_payload,
                metadata=metadata,
                org_id=effective_org_id,
                event_type=CanonicalEventType.WEATHER_ALERT.value,
            )
            events.append(raw_event)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            metadata={"locations_queried": len(query_locations)},
            fetched_at=fetched_at,
        )

    def health_check(self) -> ProviderHealthResult:
        """Perform non-destructive connectivity probe."""
        start = time.perf_counter()
        lat, lon = DEFAULT_HEALTH_CHECK_COORDS
        target_url = getattr(self.config, "base_url", None) or DEFAULT_OPENMETEO_FORECAST_URL
        params = {"latitude": lat, "longitude": lon, "current": "temperature_2m"}
        try:
            resp = self.client.get(target_url, params=params)
            latency = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "current" in data:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.HEALTHY,
                        latency_ms=latency,
                        message="Open-Meteo weather API operational and reachable.",
                        details={"status_code": 200, "elevation": data.get("elevation")},
                    )
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="Open-Meteo returned unexpected payload structure.",
                )

            if resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Open-Meteo rate limit or daily quota reached (HTTP 429).",
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"Open-Meteo returned HTTP {resp.status_code}.",
            )
        except httpx.TimeoutException:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message="Open-Meteo health probe timed out.",
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"Open-Meteo connectivity error: {exc.__class__.__name__}",
            )


class OpenMeteoNormalizer(BaseEventNormalizer):
    """Normalizes Open-Meteo raw observation envelopes into CanonicalExternalEvent models.

    Maps WMO weather codes, wind speeds, gusts, and ocean wave metrics into operational
    severity without generating false-positive critical alarms during standard conditions.
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        p_name = getattr(raw_event, "provider_name", "")
        return p_name in ("openmeteo", "open_meteo")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Translate raw payload into canonical representation."""
        payload = raw_event.raw_payload or {}
        forecast_data = payload.get("forecast") or payload
        raw_marine = payload.get("marine") or {}
        marine_data = raw_marine.get("current") if isinstance(raw_marine.get("current"), dict) else raw_marine
        current = forecast_data.get("current") or {}
        validation_errors: List[str] = []

        # 1. Geographic Location Extraction
        lat = forecast_data.get("latitude") or payload.get("requested_lat")
        lon = forecast_data.get("longitude") or payload.get("requested_lon")
        location_obj: Optional[EventLocation] = None

        if lat is not None and lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=None,
                    country_code=None,
                )
            except ValueError as ve:
                validation_errors.append(str(ve))
        else:
            validation_errors.append("Missing latitude and longitude in Open-Meteo payload")

        # 2. Timestamp Normalization
        time_str = current.get("time")
        if time_str:
            try:
                event_ts = TimestampNormalizer.parse_to_utc(time_str)
            except Exception as exc:
                event_ts = raw_event.ingested_at
                validation_errors.append(f"Invalid timestamp: {exc}")
        else:
            event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 3. Weather Metrics Extraction
        temp_c = current.get("temperature_2m")
        wind_kmh = current.get("wind_speed_10m")
        wind_mps = (wind_kmh / 3.6) if wind_kmh is not None else None
        gusts_kmh = current.get("wind_gusts_10m")
        gusts_mps = (gusts_kmh / 3.6) if gusts_kmh is not None else None
        precip_mm = current.get("precipitation")
        weather_code = current.get("weather_code")
        wave_height_m = marine_data.get("wave_height")

        # 4. Severity Mapping Invariant
        # Normal weather must never become critical risk
        severity = EventSeverity.INFO
        condition_desc, condition_key = WMO_CODE_DESCRIPTIONS.get(weather_code, ("Unknown", "UNKNOWN"))

        if (
            (wind_mps is not None and wind_mps >= 32.7)  # Hurricane force (> 64 knots)
            or (wave_height_m is not None and wave_height_m >= 9.0)  # Phenomenal sea
            or weather_code == 99  # Severe thunderstorm with heavy hail
        ):
            severity = EventSeverity.CRITICAL
        elif (
            (wind_mps is not None and wind_mps >= 24.5)  # Severe gale (> 48 knots)
            or (gusts_mps is not None and gusts_mps >= 28.0)
            or (wave_height_m is not None and wave_height_m >= 6.0)  # Very high sea
            or weather_code in (95, 96)  # Thunderstorm
        ):
            severity = EventSeverity.HIGH
        elif (
            (wind_mps is not None and wind_mps >= 17.2)  # Gale force (> 34 knots)
            or (wave_height_m is not None and wave_height_m >= 3.5)
            or (precip_mm is not None and precip_mm >= 25.0)
            or weather_code in (65, 75, 82, 86)  # Heavy rain/snow
        ):
            severity = EventSeverity.MEDIUM
        elif (
            (wind_mps is not None and wind_mps >= 10.8)  # Strong breeze
            or (wave_height_m is not None and wave_height_m >= 2.0)
            or weather_code in (61, 63, 71, 73, 80, 81)
        ):
            severity = EventSeverity.LOW

        # 5. Entity Correlation Binding
        meta = raw_event.metadata or {}
        corr = EntityCorrelation(
            shipment_id=meta.get("shipment_id"),
            route_id=meta.get("route_id"),
            port_id=meta.get("port_id"),
            facility_id=meta.get("facility_id"),
            custom_identifiers={
                "wmo_code": str(weather_code) if weather_code is not None else "unknown",
            },
        )

        # 6. Quality Assessment
        if validation_errors:
            quality = EventQuality.INVALID
        elif location_obj is None:
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

        # 7. Normalized Attributes
        normalized_attrs = {
            "temperature_celsius": temp_c,
            "apparent_temperature_celsius": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "precipitation_mm": precip_mm,
            "rain_mm": current.get("rain"),
            "surface_pressure_hpa": current.get("surface_pressure"),
            "wind_speed_mps": round(wind_mps, 2) if wind_mps is not None else None,
            "wind_gusts_mps": round(gusts_mps, 2) if gusts_mps is not None else None,
            "wind_direction_degrees": current.get("wind_direction_10m"),
            "weather_code": weather_code,
            "weather_condition": condition_desc,
            "condition_key": condition_key,
            "wave_height_meters": wave_height_m,
            "wave_direction_degrees": marine_data.get("wave_direction"),
            "wave_period_seconds": marine_data.get("wave_period"),
            "swell_wave_height_meters": marine_data.get("swell_wave_height"),
        }

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=CanonicalEventType.WEATHER_ALERT,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp or event_ts,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=corr,
            severity=severity,
            status=condition_key,
            confidence=0.95,
            source_type=EventSourceType.REAL,
            source_url=DEFAULT_OPENMETEO_FORECAST_URL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=normalized_attrs,
            provider_metadata={
                "elevation": forecast_data.get("elevation"),
                "generationtime_ms": forecast_data.get("generationtime_ms"),
                "utc_offset_seconds": forecast_data.get("utc_offset_seconds"),
            },
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )
