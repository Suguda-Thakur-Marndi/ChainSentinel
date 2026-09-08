"""OpenSky Network provider adapter and normalizer implementation.

Ingests real-time air traffic intelligence and ADS-B state vectors from the
OpenSky Network REST API (GET /states/all) via OAuth2 client-credentials authentication,
mapping provider-specific state vectors into strongly typed RawEvent and CanonicalExternalEvent
models without schema leakage.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.base import (
    BaseProviderAdapter,
    IngestionBatch,
    ProviderCapabilities,
    ProviderHealthResult,
    ProviderHealthStatus,
    ProviderType,
    RawEvent,
)
from app.integrations.boundaries import ScheduledIngestionJob
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
from app.integrations.rate_limiter import ProviderRateLimiter
from app.integrations.retry import RetryPolicy

logger = logging.getLogger("riskwise.integrations.providers.opensky")

# Verified OpenSky Network REST Root and OAuth2 Token Endpoint
DEFAULT_OPENSKY_BASE_URL = "https://opensky-network.org/api"
DEFAULT_OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)

# Reference ICAO24 regex (24-bit transponder address represented as a 6-character hex string)
ICAO24_PATTERN = re.compile(r"^[0-9a-fA-F]{6}$")

# Non-destructive reference ICAO24 for health-check probe
HEALTH_CHECK_ICAO24 = "3c6444"


# =====================================================================
# Bounding Box Configuration
# =====================================================================

class OpenSkyBoundingBox(BaseModel):
    """WGS84 bounding box filtering specification for OpenSky Network queries."""

    model_config = ConfigDict(extra="forbid")

    min_latitude: float = Field(..., ge=-90.0, le=90.0, description="Lower bound latitude (lamin)")
    min_longitude: float = Field(..., ge=-180.0, le=180.0, description="Lower bound longitude (lomin)")
    max_latitude: float = Field(..., ge=-90.0, le=90.0, description="Upper bound latitude (lamax)")
    max_longitude: float = Field(..., ge=-180.0, le=180.0, description="Upper bound longitude (lomax)")

    @model_validator(mode="after")
    def validate_bounds(self) -> "OpenSkyBoundingBox":
        CoordinateValidator.validate(self.min_latitude, self.min_longitude)
        CoordinateValidator.validate(self.max_latitude, self.max_longitude)

        if self.min_latitude > self.max_latitude:
            raise ProviderValidationError(
                f"min_latitude ({self.min_latitude}) cannot be greater than max_latitude ({self.max_latitude})"
            )
        if self.min_longitude > self.max_longitude:
            raise ProviderValidationError(
                f"min_longitude ({self.min_longitude}) cannot be greater than max_longitude ({self.max_longitude})"
            )
        return self

    def to_query_params(self) -> Dict[str, float]:
        """Convert bounding box to OpenSky REST API query parameters."""
        return {
            "lamin": float(self.min_latitude),
            "lomin": float(self.min_longitude),
            "lamax": float(self.max_latitude),
            "lomax": float(self.max_longitude),
        }


# =====================================================================
# Typed State Vector Representation
# =====================================================================

class OpenSkyStateVector(BaseModel):
    """Typed representation of an aircraft state vector from OpenSky Network.

    Field order according to official OpenSky specification:
    0: icao24 (str)
    1: callsign (str or None)
    2: origin_country (str)
    3: time_position (int or None, Unix seconds)
    4: last_contact (int, Unix seconds)
    5: longitude (float or None, WGS84 degrees)
    6: latitude (float or None, WGS84 degrees)
    7: baro_altitude (float or None, meters)
    8: on_ground (bool)
    9: velocity (float or None, m/s)
    10: true_track (float or None, degrees)
    11: vertical_rate (float or None, m/s)
    12: sensors (list of int or None)
    13: geo_altitude (float or None, meters)
    14: squawk (str or None)
    15: spi (bool)
    16: position_source (int)
    17: category (int or None, if extended=1)
    """

    model_config = ConfigDict(extra="allow")

    icao24: str
    callsign: Optional[str] = None
    origin_country: Optional[str] = None
    time_position: Optional[int] = None
    last_contact: Optional[int] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    baro_altitude: Optional[float] = None
    on_ground: bool = False
    velocity: Optional[float] = None
    true_track: Optional[float] = None
    vertical_rate: Optional[float] = None
    sensors: Optional[List[int]] = None
    geo_altitude: Optional[float] = None
    squawk: Optional[str] = None
    spi: bool = False
    position_source: int = 0
    category: Optional[int] = None

    @classmethod
    def from_raw_array(cls, arr: Sequence[Any]) -> "OpenSkyStateVector":
        """Parse an OpenSky raw state array into a strongly typed OpenSkyStateVector.

        Handles arrays of 17 or 18 elements without index errors.
        """
        if not isinstance(arr, (list, tuple)) or len(arr) < 17:
            raise ProviderValidationError(
                f"Expected state vector array with at least 17 elements, got: {type(arr).__name__} (len={len(arr) if isinstance(arr, (list, tuple)) else 0})"
            )

        def _clean_str(val: Any) -> Optional[str]:
            if val is None:
                return None
            s = str(val).strip()
            return s if s else None

        def _clean_float(val: Any) -> Optional[float]:
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        def _clean_int(val: Any) -> Optional[int]:
            if val is None:
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        icao = str(arr[0]).strip().lower()
        callsign = _clean_str(arr[1])
        origin_country = _clean_str(arr[2])
        time_position = _clean_int(arr[3])
        last_contact = _clean_int(arr[4])
        longitude = _clean_float(arr[5])
        latitude = _clean_float(arr[6])
        baro_altitude = _clean_float(arr[7])
        on_ground = bool(arr[8])
        velocity = _clean_float(arr[9])
        true_track = _clean_float(arr[10])
        vertical_rate = _clean_float(arr[11])

        sensors_raw = arr[12]
        sensors: Optional[List[int]] = None
        if isinstance(sensors_raw, list):
            sensors = [int(s) for s in sensors_raw if _clean_int(s) is not None]

        geo_altitude = _clean_float(arr[13])
        squawk = _clean_str(arr[14])
        spi = bool(arr[15])
        position_source = _clean_int(arr[16]) or 0
        category = _clean_int(arr[17]) if len(arr) > 17 else None

        return cls(
            icao24=icao,
            callsign=callsign,
            origin_country=origin_country,
            time_position=time_position,
            last_contact=last_contact,
            longitude=longitude,
            latitude=latitude,
            baro_altitude=baro_altitude,
            on_ground=on_ground,
            velocity=velocity,
            true_track=true_track,
            vertical_rate=vertical_rate,
            sensors=sensors,
            geo_altitude=geo_altitude,
            squawk=squawk,
            spi=spi,
            position_source=position_source,
            category=category,
        )

    def to_raw_payload(self, response_time: Optional[int] = None) -> Dict[str, Any]:
        """Convert state vector to a safe dictionary representation for RawEvent storage."""
        return {
            "icao24": self.icao24,
            "callsign": self.callsign,
            "origin_country": self.origin_country,
            "time_position": self.time_position,
            "last_contact": self.last_contact,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "baro_altitude": self.baro_altitude,
            "on_ground": self.on_ground,
            "velocity": self.velocity,
            "true_track": self.true_track,
            "vertical_rate": self.vertical_rate,
            "sensors": self.sensors,
            "geo_altitude": self.geo_altitude,
            "squawk": self.squawk,
            "spi": self.spi,
            "position_source": self.position_source,
            "category": self.category,
            "response_time": response_time,
        }


# =====================================================================
# OAuth2 Token Lifecycle Manager
# =====================================================================

class OpenSkyOAuthTokenManager:
    """Manages OAuth2 client-credentials token acquisition, caching, and refresh for OpenSky Network.

    Critical Security Rule:
    Never logs or exposes client_secret or access_token in plain text.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str = DEFAULT_OPENSKY_TOKEN_URL,
        http_client: Optional[httpx.Client] = None,
        refresh_margin_seconds: float = 60.0,
    ) -> None:
        if not client_id or not client_id.strip():
            raise ProviderConfigurationError("OpenSky client_id cannot be empty", provider_name="opensky")
        if not client_secret or not client_secret.strip():
            raise ProviderConfigurationError("OpenSky client_secret cannot be empty", provider_name="opensky")

        self.client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self.token_url = token_url
        self._external_client = http_client
        self._internal_client: Optional[httpx.Client] = None
        self.refresh_margin_seconds = refresh_margin_seconds

        self._access_token: Optional[str] = None
        self._expires_at: Optional[float] = None  # time.monotonic() reference
        self._token_type: str = "Bearer"

    @property
    def client(self) -> httpx.Client:
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            self._internal_client = httpx.Client(timeout=10.0)
        return self._internal_client

    def is_token_valid(self) -> bool:
        """Return True if an access token is cached and not near expiration."""
        if not self._access_token or self._expires_at is None:
            return False
        return time.monotonic() < (self._expires_at - self.refresh_margin_seconds)

    def get_token(self, force_refresh: bool = False) -> str:
        """Retrieve a valid OAuth2 access token, refreshing if expired or forced.

        Raises:
            ProviderAuthenticationError: If authentication fails at the token endpoint.
            ProviderConnectionError: If connection to auth server fails.
            ProviderTimeoutError: If auth server times out.
        """
        if not force_refresh and self.is_token_valid():
            return self._access_token  # type: ignore[return-value]

        return self._fetch_new_token()

    def invalidate_token(self) -> None:
        """Invalidate the cached token, forcing a refresh on the next request."""
        self._access_token = None
        self._expires_at = None

    def _fetch_new_token(self) -> str:
        """Execute OAuth2 client_credentials token request."""
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self._client_secret,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            logger.info("Requesting OAuth2 access token from OpenSky auth server")
            resp = self.client.post(self.token_url, data=data, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Timeout connecting to OpenSky OAuth token endpoint: {str(exc)}",
                provider_name="opensky",
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError(
                f"Network failure reaching OpenSky OAuth token endpoint: {str(exc)}",
                provider_name="opensky",
            ) from exc

        if resp.status_code in (400, 401, 403):
            self.invalidate_token()
            raise ProviderAuthenticationError(
                f"OpenSky OAuth authentication failed with HTTP {resp.status_code}",
                provider_name="opensky",
                status_code=resp.status_code,
            )

        if resp.status_code >= 500:
            raise ProviderConnectionError(
                f"OpenSky OAuth token endpoint returned upstream server error HTTP {resp.status_code}",
                provider_name="opensky",
                status_code=resp.status_code,
            )

        if resp.status_code != 200:
            raise ProviderResponseError(
                f"Unexpected status code from OpenSky OAuth endpoint: HTTP {resp.status_code}",
                provider_name="opensky",
                status_code=resp.status_code,
            )

        try:
            payload = resp.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"Failed to parse JSON response from OpenSky OAuth endpoint: {str(exc)}",
                provider_name="opensky",
            ) from exc

        access_token = payload.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise ProviderResponseError(
                "OpenSky OAuth token response missing valid 'access_token' field",
                provider_name="opensky",
            )

        expires_in = payload.get("expires_in", 1800)
        try:
            expires_in_sec = float(expires_in)
        except (ValueError, TypeError):
            expires_in_sec = 1800.0

        self._access_token = access_token
        self._expires_at = time.monotonic() + expires_in_sec
        self._token_type = payload.get("token_type", "Bearer")

        logger.info(
            "Acquired OpenSky OAuth access token (valid for %.0fs, refresh margin=%.0fs)",
            expires_in_sec,
            self.refresh_margin_seconds,
        )
        return self._access_token

    def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()


# =====================================================================
# Dedicated Provider Adapter: OpenSkyAdapter
# =====================================================================

class OpenSkyAdapter(BaseProviderAdapter):
    """Production provider adapter for OpenSky Network Air Traffic (ADS-B) integration."""

    provider_name: str = "opensky"
    provider_type: ProviderType = ProviderType.AIR
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=500,
        supported_entities=["aircraft", "flight", "carrier", "shipment"],
        supported_modalities=["air", "adsb", "state_vector"],
    )

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        secret: Optional[str] = None,
        client_id: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
        secret_resolver: Optional[SecretResolver] = None,
        idempotency_engine: Optional[IdempotencyEngine] = None,
        rate_limiter: Optional[ProviderRateLimiter] = None,
        token_manager: Optional[OpenSkyOAuthTokenManager] = None,
    ) -> None:
        if config is None:
            config = ProviderConfig(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                base_url=DEFAULT_OPENSKY_BASE_URL,
                auth_mode=AuthMode.OAUTH2,
                secret_ref="env:OPENSKY_CLIENT_SECRET",
                extra_settings={"client_id_ref": "env:OPENSKY_CLIENT_ID"},
                rate_limit=RateLimitConfig(requests_per_minute=60),
                retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
            )
        super().__init__(config=config, secret=secret)
        self.secret_resolver = secret_resolver or SecretResolver()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self._rate_limiter = rate_limiter or ProviderRateLimiter()
        self._retry_policy = RetryPolicy(config.retry)
        self._external_client = http_client
        self._internal_client: Optional[httpx.Client] = None

        self._explicit_client_id = client_id
        self._token_manager = token_manager

    @property
    def client(self) -> httpx.Client:
        """Provide an active HTTP client instance."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            timeout = getattr(self.config, "timeout_seconds", 10.0)
            self._internal_client = httpx.Client(timeout=timeout)
        return self._internal_client

    def resolve_client_id(self) -> str:
        """Resolve OpenSky client ID securely without exposing credentials."""
        if self._explicit_client_id:
            return self._explicit_client_id

        extra = getattr(self.config, "extra_settings", {}) or {}
        client_id_ref = extra.get("client_id_ref") or "env:OPENSKY_CLIENT_ID"
        resolved = self.secret_resolver.resolve_secret(client_id_ref)
        if resolved:
            return resolved

        fallback = self.secret_resolver.resolve_secret("OPENSKY_CLIENT_ID")
        if fallback:
            return fallback

        raise ProviderConfigurationError(
            "Missing OpenSky client ID. Configure via extra_settings['client_id_ref'] or OPENSKY_CLIENT_ID.",
            provider_name=self.provider_name,
        )

    def resolve_client_secret(self) -> str:
        """Resolve OpenSky client secret securely without exposing credentials."""
        if self._secret:
            return self._secret

        secret_ref = getattr(self.config, "secret_ref", None) or "env:OPENSKY_CLIENT_SECRET"
        resolved = self.secret_resolver.resolve_secret(secret_ref)
        if resolved:
            return resolved

        fallback = self.secret_resolver.resolve_secret("OPENSKY_CLIENT_SECRET")
        if fallback:
            return fallback

        raise ProviderConfigurationError(
            "Missing OpenSky client secret. Configure via secret_ref or OPENSKY_CLIENT_SECRET.",
            provider_name=self.provider_name,
        )

    def get_token_manager(self) -> OpenSkyOAuthTokenManager:
        """Provide or initialize the OAuth2 token lifecycle manager."""
        if self._token_manager is not None:
            return self._token_manager

        client_id = self.resolve_client_id()
        client_secret = self.resolve_client_secret()
        extra = getattr(self.config, "extra_settings", {}) or {}
        token_url = extra.get("token_url") or DEFAULT_OPENSKY_TOKEN_URL

        self._token_manager = OpenSkyOAuthTokenManager(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            http_client=self.client,
        )
        return self._token_manager

    def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()
        if self._token_manager is not None:
            self._token_manager.close()

    # -----------------------------------------------------------------
    # Ingestion & Polling Implementation
    # -----------------------------------------------------------------

    def fetch(
        self,
        bounding_box: Optional[OpenSkyBoundingBox] = None,
        icao24: Optional[Union[str, Sequence[str]]] = None,
        time_sec: Optional[int] = None,
        extended: bool = True,
        org_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch real-time aircraft state vectors from OpenSky Network GET /states/all.

        Parameters:
            bounding_box: Optional geographic WGS84 bounding box filter (lamin, lomin, lamax, lomax).
            icao24: Optional ICAO 24-bit address filter (single 6-char hex string or list).
            time_sec: Optional historical epoch timestamp (seconds).
            extended: Whether to include aircraft category (extended=1).
            org_id: Optional tenant isolation scope.

        Returns:
            IngestionBatch containing standardized RawEvent items for each aircraft observation.
        """
        # 1. Rate limiting check
        rl_cfg = getattr(self.config, "rate_limit", None)
        if not self._rate_limiter.acquire(self.provider_name, rl_cfg):
            _, wait_time = self._rate_limiter.check_limit(self.provider_name, rl_cfg)
            raise ProviderRateLimitError(
                f"Rate limit exceeded for provider '{self.provider_name}'",
                provider_name=self.provider_name,
                retry_after_seconds=wait_time,
            )

        # 2. Parameter validation & query construction
        params: List[Tuple[str, Union[str, int, float]]] = []

        if bounding_box is not None:
            for k, v in bounding_box.to_query_params().items():
                params.append((k, v))

        if icao24 is not None:
            if isinstance(icao24, str):
                icao_list = [icao24]
            else:
                icao_list = list(icao24)

            for item in icao_list:
                cleaned_icao = str(item).strip().lower()
                if not ICAO24_PATTERN.match(cleaned_icao):
                    raise ProviderValidationError(
                        f"Invalid ICAO24 transponder identifier: '{item}'. Must be a 6-character hex string.",
                        provider_name=self.provider_name,
                    )
                params.append(("icao24", cleaned_icao))

        if time_sec is not None:
            try:
                time_val = int(time_sec)
                params.append(("time", time_val))
            except (ValueError, TypeError) as exc:
                raise ProviderValidationError(
                    f"Invalid 'time' parameter: '{time_sec}'. Must be an integer timestamp.",
                    provider_name=self.provider_name,
                ) from exc

        if extended:
            params.append(("extended", 1))

        # 3. Request URL construction
        base_url = (getattr(self.config, "base_url", None) or DEFAULT_OPENSKY_BASE_URL).rstrip("/")
        states_url = f"{base_url}/states/all"

        # 4. Token acquisition & execution with automatic 401 recovery
        token_mgr = self.get_token_manager()
        max_auth_retries = 1
        auth_attempts = 0

        while True:
            token = token_mgr.get_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            def _send_request() -> httpx.Response:
                try:
                    resp = self.client.get(states_url, params=params, headers=headers)
                except httpx.TimeoutException as exc:
                    raise ProviderTimeoutError(
                        f"Request timeout contacting OpenSky states endpoint: {str(exc)}",
                        provider_name=self.provider_name,
                    ) from exc
                except httpx.RequestError as exc:
                    raise ProviderConnectionError(
                        f"Connection failure contacting OpenSky states endpoint: {str(exc)}",
                        provider_name=self.provider_name,
                    ) from exc

                if resp.status_code >= 500:
                    raise ProviderConnectionError(
                        f"OpenSky upstream server error: HTTP {resp.status_code}",
                        provider_name=self.provider_name,
                        status_code=resp.status_code,
                    )
                return resp

            response: httpx.Response = self._retry_policy.execute(_send_request)

            # Handle 401 Unauthorized with single bounded token refresh
            if response.status_code == 401:
                auth_attempts += 1
                if auth_attempts <= max_auth_retries:
                    logger.warning("OpenSky returned HTTP 401. Invalidating token and refreshing...")
                    token_mgr.invalidate_token()
                    continue
                else:
                    raise ProviderAuthenticationError(
                        "OpenSky returned HTTP 401 Unauthorized after token refresh attempt.",
                        provider_name=self.provider_name,
                        status_code=401,
                    )

            # Handle 403 Forbidden
            if response.status_code == 403:
                raise ProviderAuthenticationError(
                    "OpenSky returned HTTP 403 Forbidden. Verify client credentials and permissions.",
                    provider_name=self.provider_name,
                    status_code=403,
                )

            # Handle 429 Too Many Requests
            if response.status_code == 429:
                retry_after_hdr = response.headers.get("Retry-After")
                retry_after_sec = None
                if retry_after_hdr:
                    try:
                        retry_after_sec = float(retry_after_hdr)
                    except (ValueError, TypeError):
                        pass
                raise ProviderRateLimitError(
                    f"OpenSky rate limit / credit quota exceeded (HTTP 429). Retry-After: {retry_after_sec or 'unspecified'}s",
                    provider_name=self.provider_name,
                    retry_after_seconds=retry_after_sec,
                )

            # Handle 5xx Upstream Server Errors
            if response.status_code >= 500:
                raise ProviderConnectionError(
                    f"OpenSky upstream server error: HTTP {response.status_code}",
                    provider_name=self.provider_name,
                    status_code=response.status_code,
                )

            if response.status_code != 200:
                raise ProviderResponseError(
                    f"OpenSky returned unexpected status code: HTTP {response.status_code}",
                    provider_name=self.provider_name,
                    status_code=response.status_code,
                )

            # Success
            break

        # 5. Parse response payload
        try:
            data = response.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"Failed to parse OpenSky JSON response: {str(exc)}",
                provider_name=self.provider_name,
            ) from exc

        if not isinstance(data, dict):
            raise ProviderResponseError(
                f"Expected JSON object in OpenSky response, got: {type(data).__name__}",
                provider_name=self.provider_name,
            )

        resp_time = data.get("time")
        raw_states = data.get("states")

        # 6. Parse states into RawEvents
        events: List[RawEvent] = []
        now_utc = datetime.now(timezone.utc)

        if raw_states and isinstance(raw_states, list):
            for state_arr in raw_states:
                if not isinstance(state_arr, (list, tuple)):
                    continue

                try:
                    vector = OpenSkyStateVector.from_raw_array(state_arr)
                except Exception as exc:
                    logger.debug("Skipping malformed state vector: %s", exc)
                    continue

                raw_payload = vector.to_raw_payload(response_time=resp_time)
                fingerprint = self.compute_fingerprint(raw_payload, org_id=org_id)

                # Determine observation timestamp
                obs_epoch = vector.time_position or vector.last_contact or resp_time
                obs_dt = (
                    datetime.fromtimestamp(obs_epoch, tz=timezone.utc)
                    if obs_epoch
                    else now_utc
                )

                provider_event_id = f"{vector.icao24}_{obs_epoch or int(now_utc.timestamp())}"

                raw_event = RawEvent(
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    provider_event_id=provider_event_id,
                    fingerprint=fingerprint,
                    source_timestamp=obs_dt,
                    ingested_at=now_utc,
                    raw_payload=raw_payload,
                    metadata={
                        "response_time": resp_time,
                        "position_source": vector.position_source,
                        "category": vector.category,
                        "origin_country": vector.origin_country,
                    },
                    org_id=org_id,
                    event_type="LOCATION_UPDATE",
                )
                events.append(raw_event)

        logger.info("Successfully fetched %d OpenSky aircraft state vectors", len(events))
        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            source_metadata={
                "response_time": resp_time,
                "count": len(events),
                "endpoint": states_url,
            },
            fetched_at=now_utc,
        )

    # -----------------------------------------------------------------
    # Diagnostic Health Check
    # -----------------------------------------------------------------

    def health_check(self) -> ProviderHealthResult:
        """Perform a diagnostic connectivity and authentication health check.

        Never exposes client_secret or access_token in the result.
        """
        start_time = time.monotonic()

        # 1. Verify credentials configuration
        try:
            client_id = self.resolve_client_id()
            client_secret = self.resolve_client_secret()
        except ProviderConfigurationError as exc:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                latency_ms=0.0,
                message=f"OpenSky unconfigured: {exc.message}",
                details={"configured": False, "error_category": "CONFIGURATION"},
            )

        # 2. Verify token acquisition
        token_mgr = self.get_token_manager()
        try:
            token = token_mgr.get_token()
        except ProviderAuthenticationError as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"OpenSky authentication rejected: {exc.message}",
                details={"configured": True, "error_category": "AUTHENTICATION"},
            )
        except ProviderTimeoutError as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message=f"OpenSky auth timeout: {exc.message}",
                details={"configured": True, "error_category": "TIMEOUT"},
            )
        except Exception as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"OpenSky auth error: {str(exc)}",
                details={"configured": True, "error_category": "AUTHENTICATION"},
            )

        # 3. Lightweight API probe check (single ICAO query)
        base_url = (getattr(self.config, "base_url", None) or DEFAULT_OPENSKY_BASE_URL).rstrip("/")
        probe_url = f"{base_url}/states/all"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            resp = self.client.get(
                probe_url,
                params=[("icao24", HEALTH_CHECK_ICAO24)],
                headers=headers,
                timeout=5.0,
            )
            latency = (time.monotonic() - start_time) * 1000.0

            if resp.status_code == 200:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.HEALTHY,
                    latency_ms=round(latency, 2),
                    message="OpenSky REST API and OAuth2 connectivity probe succeeded.",
                    details={
                        "configured": True,
                        "endpoint": probe_url,
                        "authenticated": True,
                    },
                )
            elif resp.status_code in (401, 403):
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"OpenSky API authorization rejected: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "AUTHENTICATION", "status_code": resp.status_code},
                )
            elif resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message="OpenSky rate limit or credit quota reached (HTTP 429).",
                    details={"configured": True, "error_category": "RATE_LIMIT"},
                )
            elif resp.status_code >= 500:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"OpenSky upstream error: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "UPSTREAM", "status_code": resp.status_code},
                )
            else:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message=f"OpenSky returned unexpected probe status: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "RESPONSE", "status_code": resp.status_code},
                )
        except httpx.TimeoutException as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message=f"OpenSky probe timeout: {str(exc)}",
                details={"configured": True, "error_category": "TIMEOUT"},
            )
        except Exception as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"OpenSky probe failed: {str(exc)}",
                details={"configured": True, "error_category": "CONNECTION"},
            )

    # -----------------------------------------------------------------
    # Deterministic Idempotency Fingerprint
    # -----------------------------------------------------------------

    @classmethod
    def compute_fingerprint(
        cls,
        payload: Dict[str, Any],
        org_id: Optional[str] = None,
    ) -> str:
        """Create a deterministic SHA-256 fingerprint from verified aircraft state vector identity.

        Ensures repeated delivery of the exact same observation produces an identical
        fingerprint, while legitimate consecutive observations (differing in timestamp
        or coordinates) receive unique fingerprints and are NOT incorrectly deduplicated.
        """
        icao = str(payload.get("icao24") or "").strip().lower()
        time_pos = payload.get("time_position")
        last_contact = payload.get("last_contact")
        resp_time = payload.get("response_time")
        timestamp_key = str(time_pos if time_pos is not None else (last_contact if last_contact is not None else resp_time or ""))

        lat = payload.get("latitude")
        lon = payload.get("longitude")
        lat_str = f"{float(lat):.4f}" if lat is not None else "none"
        lon_str = f"{float(lon):.4f}" if lon is not None else "none"

        baro_alt = payload.get("baro_altitude")
        baro_str = f"{float(baro_alt):.1f}" if baro_alt is not None else "none"

        velocity = payload.get("velocity")
        vel_str = f"{float(velocity):.1f}" if velocity is not None else "none"

        on_ground = "1" if payload.get("on_ground") else "0"

        org_prefix = f"org:{org_id}:" if org_id else "global:"
        raw_key = (
            f"{org_prefix}opensky:state:{icao}:ts:{timestamp_key}:"
            f"pos:{lat_str},{lon_str}:alt:{baro_str}:vel:{vel_str}:gnd:{on_ground}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# =====================================================================
# Canonical Normalizer: OpenSkyNormalizer
# =====================================================================

class OpenSkyNormalizer(BaseEventNormalizer):
    """Production normalizer converting OpenSky RawEvent instances into CanonicalExternalEvent models."""

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Return True if the raw event was produced by OpenSky."""
        return raw_event.provider_name.lower().strip() == "opensky"

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform an OpenSky RawEvent into a CanonicalExternalEvent.

        Adheres strictly to the canonical model without schema leakage:
        - Maps aircraft positions to CanonicalEventType.LOCATION_UPDATE
        - Elevates severity only on verified emergency squawk codes (7700, 7600, 7500)
        - Normalizes units to WGS84 and SI (meters, m/s, degrees)
        - Preserves nullability without fabricating coordinates or metrics
        - Establishes EntityCorrelation without fabricating shipment relationships
        """
        payload = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        # 1. Aircraft Identification
        icao24 = str(payload.get("icao24") or "").strip().lower()
        callsign = payload.get("callsign")
        if callsign:
            callsign = str(callsign).strip() or None

        origin_country = payload.get("origin_country")
        if origin_country:
            origin_country = str(origin_country).strip() or None

        if not icao24:
            validation_errors.append("Missing required aircraft ICAO24 identifier.")

        # 2. Timestamp Normalization
        time_pos = payload.get("time_position")
        last_contact = payload.get("last_contact")
        resp_time = payload.get("response_time")

        event_ts_val = time_pos if time_pos is not None else (last_contact if last_contact is not None else resp_time)
        if event_ts_val is None and raw_event.source_timestamp is not None:
            event_ts_val = raw_event.source_timestamp

        try:
            if event_ts_val is not None:
                event_ts = TimestampNormalizer.parse_to_utc(event_ts_val)
            else:
                event_ts = raw_event.ingested_at
                validation_errors.append("Missing observation timestamp; fell back to ingested_at.")
        except Exception as exc:
            event_ts = raw_event.ingested_at
            validation_errors.append(f"Timestamp normalization error: {str(exc)}")

        observed_at = None
        if time_pos is not None:
            try:
                observed_at = TimestampNormalizer.parse_to_utc(time_pos)
            except Exception:
                pass

        # 3. Spatial Coordinates Validation
        lat = payload.get("latitude")
        lon = payload.get("longitude")
        location_obj: Optional[EventLocation] = None

        if lat is not None or lon is not None:
            try:
                valid_lat, valid_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=valid_lat,
                    longitude=valid_lon,
                    location_name=f"{callsign or icao24} ({origin_country})" if origin_country else callsign or icao24,
                    country_code=None,
                )
            except Exception as exc:
                validation_errors.append(f"Coordinate validation failure: {str(exc)}")
                location_obj = None

        # 4. Telemetry & Units Normalization
        baro_alt = payload.get("baro_altitude")      # meters
        geo_alt = payload.get("geo_altitude")        # meters
        velocity = payload.get("velocity")            # m/s ground speed
        true_track = payload.get("true_track")        # degrees clockwise from north
        vertical_rate = payload.get("vertical_rate")  # m/s
        on_ground = bool(payload.get("on_ground", False))
        squawk = payload.get("squawk")
        if squawk:
            squawk = str(squawk).strip()
        spi = bool(payload.get("spi", False))
        position_source = payload.get("position_source", 0)
        category = payload.get("category")

        # 5. Operational Status & Severity Mapping
        # By default, aircraft position telemetry is informational.
        # Elevate only if transponder transmits an emergency squawk code:
        # 7700: General Emergency
        # 7600: Radio Communication Failure (Lost Comm)
        # 7500: Unlawful Interference / Hijacking
        canonical_type = CanonicalEventType.LOCATION_UPDATE
        severity = EventSeverity.INFO
        status_str = "ON_GROUND" if on_ground else "AIRBORNE"

        if squawk == "7700":
            canonical_type = CanonicalEventType.LOCATION_UPDATE
            severity = EventSeverity.CRITICAL
            status_str = "EMERGENCY"
        elif squawk == "7600":
            canonical_type = CanonicalEventType.LOCATION_UPDATE
            severity = EventSeverity.HIGH
            status_str = "RADIO_FAILURE"
        elif squawk == "7500":
            canonical_type = CanonicalEventType.LOCATION_UPDATE
            severity = EventSeverity.CRITICAL
            status_str = "UNLAWFUL_INTERFERENCE"

        # 6. Entity Correlation
        # Preserve verified aircraft identity. Shipment correlation remains UNRESOLVED
        # unless established through downstream correlation.
        custom_ids: Dict[str, str] = {}
        if icao24:
            custom_ids["icao24"] = icao24
        if callsign:
            custom_ids["callsign"] = callsign
        if origin_country:
            custom_ids["origin_country"] = origin_country

        correlation = EntityCorrelation(
            shipment_id=payload.get("shipment_id"),
            carrier_id=payload.get("carrier_id"),
            custom_identifiers=custom_ids,
        )

        # 7. Normalized Attributes Envelope (preserving standard SI units)
        normalized_attrs: Dict[str, Any] = {
            "icao24": icao24,
            "callsign": callsign,
            "origin_country": origin_country,
            "baro_altitude_meters": baro_alt,
            "geo_altitude_meters": geo_alt,
            "velocity_mps": velocity,
            "true_track_degrees": true_track,
            "vertical_rate_mps": vertical_rate,
            "on_ground": on_ground,
            "squawk": squawk,
            "spi": spi,
            "position_source": position_source,
            "category": category,
            "mode": "AIR",
            "event_classification": "AIRCRAFT_STATE_VECTOR",
        }

        # 8. Event Quality Determination
        if validation_errors:
            quality = EventQuality.PARTIAL
        elif location_obj is None or location_obj.latitude is None or location_obj.longitude is None:
            quality = EventQuality.PARTIAL
        elif not icao24:
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=canonical_type,
            event_timestamp=event_ts,
            observed_at=observed_at,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=correlation,
            severity=severity,
            status=status_str,
            confidence=0.99 if quality == EventQuality.VALID else 0.70,
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=normalized_attrs,
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )


# =====================================================================
# Scheduler Helper
# =====================================================================

def create_opensky_polling_job(
    job_id: str,
    cron_or_interval: str = "interval:60",
    bounding_box: Optional[OpenSkyBoundingBox] = None,
    icao24: Optional[Union[str, Sequence[str]]] = None,
    organization_id: Optional[str] = None,
    enabled: bool = True,
) -> ScheduledIngestionJob:
    """Create a standardized ScheduledIngestionJob descriptor for periodic OpenSky state polling."""
    parameters: Dict[str, Any] = {}
    if bounding_box:
        parameters["bounding_box"] = bounding_box.model_dump()
    if icao24:
        if isinstance(icao24, str):
            parameters["icao24"] = [icao24]
        else:
            parameters["icao24"] = list(icao24)

    return ScheduledIngestionJob(
        job_id=job_id,
        provider_name="opensky",
        cron_or_interval=cron_or_interval,
        enabled=enabled,
        parameters=parameters,
        organization_id=organization_id,
    )
