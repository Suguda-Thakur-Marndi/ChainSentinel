"""OpenWeather provider adapter and normalizer implementation.

Ingests real-time weather observations and alerts from OpenWeather API endpoints
(Current Weather Data 2.5 and One Call 3.0 alerts), mapping provider-specific responses
into strongly typed RawEvent and CanonicalExternalEvent models without schema leakage.
"""
from __future__ import annotations

import logging
import re
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

logger = logging.getLogger("riskwise.integrations.providers.openweather")

# Default OpenWeather endpoints
DEFAULT_OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
ONE_CALL_BASE_URL = "https://api.openweathermap.org/data/3.0/onecall"
HEALTH_CHECK_COORDINATES = (51.5074, -0.1278)  # London coordinates for non-destructive probe


class OpenWeatherAdapter(BaseProviderAdapter):
    """Production provider adapter for OpenWeather API integration."""

    provider_name: str = "openweather"
    provider_type: ProviderType = ProviderType.WEATHER
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=50,
        supported_entities=["location", "route", "facility", "port", "shipment"],
        supported_modalities=["weather", "climate", "alerts"],
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
                base_url=DEFAULT_OPENWEATHER_BASE_URL,
                auth_mode=AuthMode.API_KEY_QUERY,
                secret_ref="env:OPENWEATHER_API_KEY",
                rate_limit=RateLimitConfig(requests_per_minute=60),
                retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
            )
        super().__init__(config=config, secret=secret)
        self.secret_resolver = secret_resolver or SecretResolver()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self._external_client = http_client
        self._internal_client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Provide an active HTTP client instance."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            timeout = getattr(self.config, "timeout_seconds", 10.0)
            self._internal_client = httpx.Client(timeout=timeout)
        return self._internal_client

    def close(self) -> None:
        """Release underlying HTTP resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    def resolve_api_key(self) -> str:
        """Resolve OpenWeather API key securely without exposing credentials.

        Raises:
            ProviderConfigurationError: If no key can be resolved from secret, config, or environment.
        """
        if self._secret:
            return self._secret

        secret_ref = getattr(self.config, "secret_ref", None) or "env:OPENWEATHER_API_KEY"
        resolved = self.secret_resolver.resolve_secret(secret_ref)
        if resolved:
            return resolved

        # Direct environment variable fallback
        fallback = self.secret_resolver.resolve_secret("OPENWEATHER_API_KEY")
        if fallback:
            return fallback

        raise ProviderConfigurationError(
            "OpenWeather API key is not configured. Set secret or OPENWEATHER_API_KEY environment variable.",
            provider_name=self.provider_name,
        )

    def _sanitize_url_for_logging(self, url: str) -> str:
        """Redact sensitive query parameters such as appid from URL strings."""
        return re.sub(r"(appid=)[^&]+", r"\1[REDACTED]", str(url), flags=re.IGNORECASE)

    @classmethod
    def compute_observation_fingerprint(
        cls,
        latitude: float,
        longitude: float,
        observation_timestamp: Union[int, float, datetime],
        weather_id: Optional[int] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute a deterministic, collision-resistant SHA-256 fingerprint for a weather observation."""
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
            "dt": ts_str,
            "weather_id": weather_id,
        }
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="openweather",
            payload=obs_payload,
            organization_id=org_id,
        )

    def fetch(
        self,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        units: Optional[str] = None,
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        org_id: Optional[str] = None,
        route_id: Optional[str] = None,
        shipment_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        port_id: Optional[str] = None,
        locations: Optional[List[Dict[str, float]]] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch weather observations from OpenWeather for given coordinates.

        Strictly enforces pre-request coordinate validation using CoordinateValidator.
        Preserves original raw payload inside RawEvent boundaries.
        """
        # Batch coordinates request
        if locations is not None and isinstance(locations, list):
            events: List[RawEvent] = []
            for loc in locations:
                sub_batch = self.fetch(
                    latitude=loc.get("latitude", loc.get("lat")),
                    longitude=loc.get("longitude", loc.get("lon")),
                    units=units,
                    correlation_id=correlation_id,
                    organization_id=organization_id or org_id,
                    route_id=route_id,
                    shipment_id=shipment_id,
                    facility_id=facility_id,
                    port_id=port_id,
                    **kwargs,
                )
                events.extend(sub_batch.events)
            return IngestionBatch(
                provider_name=self.provider_name,
                events=events,
                source_metadata={"batch_size": len(events)},
                fetched_at=datetime.now(timezone.utc),
            )

        # 1. Coordinate resolution & pre-request validation
        eff_lat = latitude if latitude is not None else lat
        eff_lon = longitude if longitude is not None else lon

        if eff_lat is None or eff_lon is None:
            raise ProviderValidationError(
                "Both latitude and longitude coordinates are required for OpenWeather observation.",
                provider_name=self.provider_name,
            )

        try:
            valid_lat, valid_lon = CoordinateValidator.validate(eff_lat, eff_lon)
        except (ValueError, TypeError) as ve:
            raise ProviderValidationError(
                f"Invalid coordinates for OpenWeather request: {str(ve)}",
                provider_name=self.provider_name,
            ) from ve

        # 2. Resolve credentials
        api_key = self.resolve_api_key()

        # 3. Build query parameters
        eff_units = units or getattr(self.config, "extra_settings", {}).get("units", "metric")
        base_url = getattr(self.config, "base_url", None) or DEFAULT_OPENWEATHER_BASE_URL

        params: Dict[str, Any] = {
            "lat": valid_lat,
            "lon": valid_lon,
            "appid": api_key,
            "units": eff_units,
        }
        if "lang" in kwargs:
            params["lang"] = kwargs["lang"]

        # 4. Execute HTTP request with robust error classification
        safe_url = self._sanitize_url_for_logging(f"{base_url}?lat={valid_lat}&lon={valid_lon}")
        logger.debug("Executing OpenWeather request to %s (correlation_id=%s)", safe_url, correlation_id)

        try:
            resp = self.client.get(base_url, params=params)
        except httpx.TimeoutException as te:
            raise ProviderTimeoutError(
                f"OpenWeather request timed out: {str(te)}",
                provider_name=self.provider_name,
            ) from te
        except httpx.RequestError as re_err:
            raise ProviderConnectionError(
                f"OpenWeather network connection failure: {str(re_err)}",
                provider_name=self.provider_name,
            ) from re_err

        # 5. Handle HTTP status codes
        status = resp.status_code
        if status in (401, 403):
            raise ProviderAuthenticationError(
                "OpenWeather authentication failed: Invalid or unauthorized API key.",
                provider_name=self.provider_name,
                status_code=status,
            )

        if status == 429:
            retry_after_hdr = resp.headers.get("Retry-After")
            retry_after_val: Optional[float] = None
            if retry_after_hdr:
                try:
                    retry_after_val = float(retry_after_hdr)
                except ValueError:
                    retry_after_val = None
            raise ProviderRateLimitError(
                "OpenWeather rate limit exceeded (HTTP 429).",
                provider_name=self.provider_name,
                retry_after=retry_after_val,
            )

        if status == 400:
            err_details = resp.text[:200]
            raise ProviderValidationError(
                f"OpenWeather rejected request parameters (HTTP 400): {err_details}",
                provider_name=self.provider_name,
            )

        if status == 404:
            raise ProviderPermanentError(
                f"OpenWeather endpoint or location not found (HTTP 404): {resp.text[:200]}",
                provider_name=self.provider_name,
            )

        if status in (500, 502, 503, 504):
            raise ProviderResponseError(
                f"OpenWeather upstream server error (HTTP {status})",
                status_code=status,
                provider_name=self.provider_name,
            )

        if status >= 400:
            raise ProviderResponseError(
                f"OpenWeather HTTP error {status}: {resp.text[:200]}",
                status_code=status,
                provider_name=self.provider_name,
            )

        # 6. Parse JSON payload
        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("Response root must be a JSON object")
        except Exception as exc:
            raise ProviderResponseError(
                f"OpenWeather returned malformed JSON payload: {str(exc)}",
                provider_name=self.provider_name,
            ) from exc

        # 7. Preserve RawEvent boundary
        # Strip appid if somehow present in response
        sanitized_payload = SecretResolver.sanitize_payload(data)
        if "appid" in sanitized_payload:
            sanitized_payload.pop("appid", None)

        dt_val = data.get("dt")
        source_ts: Optional[datetime] = None
        if dt_val is not None:
            try:
                source_ts = TimestampNormalizer.parse_to_utc(dt_val)
            except Exception:
                source_ts = datetime.now(timezone.utc)
        else:
            source_ts = datetime.now(timezone.utc)

        # Compute deterministic observation fingerprint
        weather_items = data.get("weather", [])
        primary_w_id = weather_items[0].get("id") if weather_items and isinstance(weather_items, list) else None
        effective_org = organization_id or org_id
        fingerprint = self.compute_observation_fingerprint(
            latitude=valid_lat,
            longitude=valid_lon,
            observation_timestamp=dt_val if dt_val is not None else source_ts,
            weather_id=primary_w_id,
            org_id=effective_org,
        )

        city_id = data.get("id")
        provider_event_id = f"ow_{city_id}_{dt_val}" if (city_id and dt_val) else (f"ow_{dt_val}" if dt_val else None)

        raw_event = RawEvent(
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            provider_event_id=provider_event_id,
            fingerprint=fingerprint,
            source_timestamp=source_ts,
            raw_payload=sanitized_payload,
            metadata={
                "units": eff_units,
                "requested_lat": valid_lat,
                "requested_lon": valid_lon,
                "correlation_id": correlation_id,
                "route_id": route_id,
                "shipment_id": shipment_id,
                "facility_id": facility_id,
                "port_id": port_id,
            },
            org_id=effective_org,
        )

        return IngestionBatch(
            provider_name=self.provider_name,
            events=[raw_event],
            source_metadata={
                "endpoint": base_url,
                "units": eff_units,
                "correlation_id": correlation_id,
            },
            fetched_at=datetime.now(timezone.utc),
        )

    def health_check(self) -> ProviderHealthResult:
        """Perform non-destructive connectivity and authentication probe.

        Distinguishes HEALTHY, UNCONFIGURED, UNHEALTHY, and DEGRADED states
        without exposing API keys or secrets.
        """
        start = time.perf_counter()

        # 1. Verify key configuration
        try:
            api_key = self.resolve_api_key()
        except ProviderConfigurationError as cfg_err:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                latency_ms=latency,
                message=str(cfg_err),
            )

        # 2. Probe with canonical reference coordinates
        base_url = getattr(self.config, "base_url", None) or DEFAULT_OPENWEATHER_BASE_URL
        probe_lat, probe_lon = HEALTH_CHECK_COORDINATES
        params = {
            "lat": probe_lat,
            "lon": probe_lon,
            "appid": api_key,
            "units": "metric",
        }

        try:
            resp = self.client.get(base_url, params=params)
            latency = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                try:
                    payload = resp.json()
                    if isinstance(payload, dict) and "main" in payload:
                        return ProviderHealthResult(
                            provider_name=self.provider_name,
                            status=ProviderHealthStatus.HEALTHY,
                            latency_ms=latency,
                            message="OpenWeather API operational and responsive.",
                            details={"status_code": 200, "city": payload.get("name", "Unknown")},
                        )
                    else:
                        return ProviderHealthResult(
                            provider_name=self.provider_name,
                            status=ProviderHealthStatus.UNHEALTHY,
                            latency_ms=latency,
                            message="OpenWeather API returned malformed response structure.",
                            details={"status_code": 200},
                        )
                except Exception:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.UNHEALTHY,
                        latency_ms=latency,
                        message="OpenWeather response could not be parsed as JSON.",
                    )

            if resp.status_code in (401, 403):
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="OpenWeather authentication failed: Invalid or expired API key.",
                    details={"status_code": resp.status_code},
                )

            if resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="OpenWeather quota exhausted or rate limit active (HTTP 429).",
                    details={"status_code": 429},
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"OpenWeather returned unexpected HTTP status {resp.status_code}.",
                details={"status_code": resp.status_code},
            )

        except httpx.TimeoutException:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message="OpenWeather health probe timed out.",
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"OpenWeather connection error: {exc.__class__.__name__}",
            )


class OpenWeatherNormalizer(BaseEventNormalizer):
    """Normalizes OpenWeather raw payloads into CanonicalExternalEvent models.

    Adheres strictly to verified OpenWeather fields and ensures normal ambient
    weather observations never trigger false-positive critical-risk events.
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        p_name = getattr(raw_event, "provider_name", "")
        return p_name.lower().strip() == "openweather"

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform OpenWeather RawEvent into CanonicalExternalEvent."""
        p = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        # 1. Timestamp resolution
        ts_val = p.get("dt") or raw_event.source_timestamp or raw_event.ingested_at
        try:
            event_ts = TimestampNormalizer.parse_to_utc(ts_val)
        except Exception as exc:
            event_ts = raw_event.ingested_at
            validation_errors.append(f"Timestamp normalization fallback: {str(exc)}")

        # 2. Location resolution
        coord = p.get("coord") if isinstance(p.get("coord"), dict) else {}
        lat = coord.get("lat") if "lat" in coord else (p.get("lat") or p.get("latitude"))
        lon = coord.get("lon") if "lon" in coord else (p.get("lon") or p.get("longitude"))
        city_name = p.get("name") or p.get("city") or p.get("location_name")
        sys_info = p.get("sys") if isinstance(p.get("sys"), dict) else {}
        country = sys_info.get("country") or p.get("country")

        location_obj: Optional[EventLocation] = None
        if lat is not None or lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=str(city_name) if city_name else None,
                    country_code=str(country)[:3] if country else None,
                )
            except Exception as exc:
                validation_errors.append(f"Coordinate validation failed: {str(exc)}")

        # 3. Entity correlation propagation
        meta = raw_event.metadata or {}
        correlation = EntityCorrelation(
            shipment_id=meta.get("shipment_id") or p.get("shipment_id"),
            route_id=meta.get("route_id") or p.get("route_id"),
            facility_id=meta.get("facility_id") or p.get("facility_id"),
            port_id=meta.get("port_id") or p.get("port_id"),
            carrier_id=meta.get("carrier_id") or p.get("carrier_id"),
        )

        # 4. Normalized attributes extraction - ONLY verified fields
        norm_attrs: Dict[str, Any] = {}
        main_data = p.get("main") if isinstance(p.get("main"), dict) else {}
        wind_data = p.get("wind") if isinstance(p.get("wind"), dict) else {}
        rain_data = p.get("rain") if isinstance(p.get("rain"), dict) else {}
        snow_data = p.get("snow") if isinstance(p.get("snow"), dict) else {}
        clouds_data = p.get("clouds") if isinstance(p.get("clouds"), dict) else {}
        weather_list = p.get("weather") if isinstance(p.get("weather"), list) else []
        primary_w = weather_list[0] if weather_list and isinstance(weather_list[0], dict) else {}

        # Temperature
        if "temp" in main_data:
            norm_attrs["temperature_celsius"] = float(main_data["temp"])
        elif "temp_c" in p:
            norm_attrs["temperature_celsius"] = float(p["temp_c"])

        if "feels_like" in main_data:
            norm_attrs["feels_like_celsius"] = float(main_data["feels_like"])
        if "temp_min" in main_data:
            norm_attrs["temp_min_celsius"] = float(main_data["temp_min"])
        if "temp_max" in main_data:
            norm_attrs["temp_max_celsius"] = float(main_data["temp_max"])

        # Pressure & Humidity
        if "pressure" in main_data:
            norm_attrs["pressure_hpa"] = float(main_data["pressure"])
        if "humidity" in main_data:
            norm_attrs["humidity_percent"] = float(main_data["humidity"])

        # Visibility
        if "visibility" in p and p["visibility"] is not None:
            norm_attrs["visibility_meters"] = float(p["visibility"])

        # Wind
        if "speed" in wind_data:
            norm_attrs["wind_speed_mps"] = float(wind_data["speed"])
        elif "wind_speed_knots" in p:
            norm_attrs["wind_speed_mps"] = float(p["wind_speed_knots"]) * 0.514444

        if "deg" in wind_data:
            norm_attrs["wind_deg"] = float(wind_data["deg"])
        if "gust" in wind_data:
            norm_attrs["wind_gust_mps"] = float(wind_data["gust"])

        # Precipitation
        if isinstance(rain_data, dict):
            if "1h" in rain_data:
                norm_attrs["rain_1h_mm"] = float(rain_data["1h"])
            if "3h" in rain_data:
                norm_attrs["rain_3h_mm"] = float(rain_data["3h"])
        elif "rain_mm" in p:
            norm_attrs["rain_1h_mm"] = float(p["rain_mm"])

        if isinstance(snow_data, dict):
            if "1h" in snow_data:
                norm_attrs["snow_1h_mm"] = float(snow_data["1h"])
            if "3h" in snow_data:
                norm_attrs["snow_3h_mm"] = float(snow_data["3h"])

        # Clouds
        if "all" in clouds_data:
            norm_attrs["clouds_percent"] = float(clouds_data["all"])

        # Weather condition
        if primary_w:
            w_id = primary_w.get("id")
            w_main = primary_w.get("main")
            w_desc = primary_w.get("description")
            w_icon = primary_w.get("icon")
            if w_id is not None:
                norm_attrs["weather_id"] = int(w_id)
            if w_main:
                norm_attrs["weather_main"] = str(w_main)
            if w_desc:
                norm_attrs["weather_description"] = str(w_desc)
            if w_icon:
                norm_attrs["weather_icon"] = str(w_icon)
        elif "conditions" in p:
            norm_attrs["weather_main"] = str(p["conditions"])

        # Sunrise & sunset
        if "sunrise" in sys_info:
            try:
                norm_attrs["sunrise_utc"] = TimestampNormalizer.parse_to_utc(sys_info["sunrise"]).isoformat()
            except Exception:
                pass
        if "sunset" in sys_info:
            try:
                norm_attrs["sunset_utc"] = TimestampNormalizer.parse_to_utc(sys_info["sunset"]).isoformat()
            except Exception:
                pass

        # 5. Event Type & Severity Determination
        # Check for One Call 3.0 alerts
        alerts_list = p.get("alerts")
        if alerts_list and isinstance(alerts_list, list) and len(alerts_list) > 0:
            canonical_type = CanonicalEventType.WEATHER_ALERT
            first_alert = alerts_list[0]
            norm_attrs["alert_event"] = first_alert.get("event")
            norm_attrs["alert_sender"] = first_alert.get("sender_name")
            norm_attrs["alert_description"] = first_alert.get("description")
            norm_attrs["alert_tags"] = first_alert.get("tags", [])
            alert_name = str(first_alert.get("event", "")).lower()

            if any(k in alert_name for k in ["tornado", "cyclone", "hurricane", "extreme", "danger"]):
                severity = EventSeverity.CRITICAL
            elif any(k in alert_name for k in ["warning", "storm", "blizzard", "flood", "gale"]):
                severity = EventSeverity.HIGH
            elif any(k in alert_name for k in ["watch", "advisory", "statement"]):
                severity = EventSeverity.MEDIUM
            else:
                severity = EventSeverity.LOW
        else:
            # Observation evaluation from verified metrics
            temp_c = norm_attrs.get("temperature_celsius", 20.0)
            wind_speed = norm_attrs.get("wind_speed_mps", 0.0)
            rain_1h = norm_attrs.get("rain_1h_mm", 0.0)
            w_id = norm_attrs.get("weather_id")

            # Severe indicators:
            # - Tornado (781): CRITICAL EXTREME_WEATHER
            # - Squalls (771), Hurricane-force wind (> 32 m/s): CRITICAL
            # - Thunderstorm (2xx), Gale/Storm wind (> 20 m/s), Torrential Rain (> 30 mm): HIGH
            # - Normal weather: INFO / LOW (NEVER critical risk)
            if w_id == 781 or (w_id and w_id == 781):  # Tornado
                canonical_type = CanonicalEventType.EXTREME_WEATHER
                severity = EventSeverity.CRITICAL
            elif wind_speed >= 32.0 or (w_id and w_id == 771):  # Hurricane force or Squall
                canonical_type = CanonicalEventType.STORM
                severity = EventSeverity.CRITICAL
            elif w_id is not None and 200 <= w_id <= 232:  # Thunderstorm
                canonical_type = CanonicalEventType.STORM
                if w_id in (202, 212, 221, 232) or wind_speed > 17.0:
                    severity = EventSeverity.HIGH
                else:
                    severity = EventSeverity.MEDIUM
            elif wind_speed >= 20.0:  # Strong gale / storm wind
                canonical_type = CanonicalEventType.STORM
                severity = EventSeverity.HIGH
            elif temp_c >= 45.0 or temp_c <= -25.0:  # Extreme temperature
                canonical_type = CanonicalEventType.EXTREME_WEATHER
                severity = EventSeverity.HIGH
            elif rain_1h >= 50.0:  # Violent torrential rain
                canonical_type = CanonicalEventType.EXTREME_WEATHER
                severity = EventSeverity.HIGH
            elif rain_1h >= 25.0:  # Heavy rain
                canonical_type = CanonicalEventType.STORM
                severity = EventSeverity.MEDIUM
            else:
                # Normal ambient weather observation
                canonical_type = CanonicalEventType.CUSTOM
                norm_attrs["event_classification"] = "WEATHER_OBSERVATION"
                if wind_speed >= 10.8 or rain_1h >= 5.0:  # Fresh breeze or moderate rain
                    severity = EventSeverity.LOW
                else:
                    severity = EventSeverity.INFO

        # 6. Quality determination
        if validation_errors:
            quality = EventQuality.INVALID
        elif location_obj is None:
            quality = EventQuality.PARTIAL
        elif not correlation.is_correlated:
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

        canonical_event = CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=canonical_type,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=correlation,
            status=norm_attrs.get("weather_main", "OBSERVED"),
            severity=severity,
            confidence=0.98 if quality == EventQuality.VALID else 0.90,
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=norm_attrs,
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )

        return canonical_event
