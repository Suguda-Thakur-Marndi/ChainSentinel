"""TomTom provider adapter and normalizer implementation.

Ingests real-time road and traffic intelligence from TomTom API endpoints
(Traffic Flow Segment Data v4 and Traffic Incident Details v5), mapping provider-specific
payloads into strongly typed RawEvent and CanonicalExternalEvent models without schema leakage.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

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

logger = logging.getLogger("riskwise.integrations.providers.tomtom")

# Verified TomTom Endpoints
DEFAULT_TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
DEFAULT_TOMTOM_INCIDENTS_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"
HEALTH_CHECK_COORDINATES = (52.3731, 4.8922)  # Amsterdam reference coordinates for non-destructive probe


class TomTomAdapter(BaseProviderAdapter):
    """Production provider adapter for TomTom Road & Traffic API integration."""

    provider_name: str = "tomtom"
    provider_type: ProviderType = ProviderType.ROAD_TRAFFIC
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=100,
        supported_entities=["location", "route", "facility", "shipment", "carrier"],
        supported_modalities=["traffic", "road_traffic", "incidents", "congestion"],
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
                base_url=DEFAULT_TOMTOM_FLOW_URL,
                auth_mode=AuthMode.API_KEY_QUERY,
                secret_ref="env:TOMTOM_API_KEY",
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
        """Resolve TomTom API key securely without exposing credentials.

        Raises:
            ProviderConfigurationError: If no key can be resolved from secret, config, or environment.
        """
        if self._secret:
            return self._secret

        secret_ref = getattr(self.config, "secret_ref", None) or "env:TOMTOM_API_KEY"
        resolved = self.secret_resolver.resolve_secret(secret_ref)
        if resolved:
            return resolved

        fallback = self.secret_resolver.resolve_secret("TOMTOM_API_KEY")
        if fallback:
            return fallback

        raise ProviderConfigurationError(
            "TomTom API key is not configured. Set secret or TOMTOM_API_KEY environment variable.",
            provider_name=self.provider_name,
        )

    def _sanitize_url_for_logging(self, url: str) -> str:
        """Redact sensitive query parameters such as key from URL strings."""
        return re.sub(r"(key=)[^&]+", r"\1[REDACTED]", str(url), flags=re.IGNORECASE)

    @classmethod
    def compute_flow_fingerprint(
        cls,
        latitude: float,
        longitude: float,
        timestamp: Union[int, float, str, datetime],
        frc: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute deterministic SHA-256 fingerprint for a traffic flow observation."""
        rounded_lat = round(float(latitude), 4)
        rounded_lon = round(float(longitude), 4)

        if isinstance(timestamp, (int, float)):
            ts_str = str(int(timestamp))
        elif isinstance(timestamp, datetime):
            ts_str = str(int(timestamp.timestamp()))
        else:
            ts_str = str(timestamp)

        flow_payload = {
            "lat": rounded_lat,
            "lon": rounded_lon,
            "ts": ts_str,
            "frc": frc or "FRC_UNKNOWN",
        }
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="tomtom",
            payload=flow_payload,
            organization_id=org_id,
        )

    @classmethod
    def compute_incident_fingerprint(
        cls,
        incident_id: str,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute deterministic SHA-256 fingerprint for a traffic incident using provider ID."""
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="tomtom",
            provider_event_id=str(incident_id).strip(),
            organization_id=org_id,
        )

    def fetch_flow(
        self,
        latitude: float,
        longitude: float,
        unit: str = "KMPH",
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        route_id: Optional[str] = None,
        shipment_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch traffic flow segment data for a specific geographic coordinate."""
        # 1. Coordinate validation before HTTP request
        try:
            valid_lat, valid_lon = CoordinateValidator.validate(latitude, longitude)
        except (ValueError, TypeError) as ve:
            raise ProviderValidationError(
                f"Invalid coordinates for TomTom traffic flow: {str(ve)}",
                provider_name=self.provider_name,
            ) from ve

        # 2. Key resolution
        api_key = self.resolve_api_key()

        # 3. Parameters
        base_url = getattr(self.config, "base_url", None) or DEFAULT_TOMTOM_FLOW_URL
        params: Dict[str, Any] = {
            "key": api_key,
            "point": f"{valid_lat},{valid_lon}",
            "unit": unit,
        }

        safe_url = self._sanitize_url_for_logging(f"{base_url}?point={valid_lat},{valid_lon}&unit={unit}")
        logger.debug("Executing TomTom flow request: %s (correlation_id=%s)", safe_url, correlation_id)

        # 4. HTTP Execution with error classification
        try:
            resp = self.client.get(base_url, params=params)
        except httpx.TimeoutException as te:
            raise ProviderTimeoutError(
                f"TomTom traffic flow request timed out: {str(te)}",
                provider_name=self.provider_name,
            ) from te
        except httpx.RequestError as re_err:
            raise ProviderConnectionError(
                f"TomTom network connection failure: {str(re_err)}",
                provider_name=self.provider_name,
            ) from re_err

        status = resp.status_code
        if status in (401, 403):
            raise ProviderAuthenticationError(
                "TomTom authentication failed: Invalid or unauthorized API key.",
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
                "TomTom rate limit exceeded (HTTP 429).",
                provider_name=self.provider_name,
                retry_after=retry_after_val,
            )
        if status == 400:
            raise ProviderValidationError(
                f"TomTom rejected request parameters (HTTP 400): {resp.text[:200]}",
                provider_name=self.provider_name,
            )
        if status == 404:
            raise ProviderPermanentError(
                f"TomTom endpoint or segment not found (HTTP 404): {resp.text[:200]}",
                provider_name=self.provider_name,
            )
        if status in (500, 502, 503, 504):
            raise ProviderResponseError(
                f"TomTom upstream server error (HTTP {status})",
                status_code=status,
                provider_name=self.provider_name,
            )
        if status >= 400:
            raise ProviderResponseError(
                f"TomTom HTTP error {status}: {resp.text[:200]}",
                status_code=status,
                provider_name=self.provider_name,
            )

        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("Response root must be a JSON object")
        except Exception as exc:
            raise ProviderResponseError(
                f"TomTom returned malformed JSON payload: {str(exc)}",
                provider_name=self.provider_name,
            ) from exc

        # 5. Sanitize & build RawEvent
        sanitized_payload = SecretResolver.sanitize_payload(data)
        if "key" in sanitized_payload:
            sanitized_payload.pop("key", None)

        now_utc = datetime.now(timezone.utc)
        flow_data = data.get("flowSegmentData", {})
        frc = flow_data.get("frc")
        fingerprint = self.compute_flow_fingerprint(
            latitude=valid_lat,
            longitude=valid_lon,
            timestamp=now_utc,
            frc=frc,
            org_id=organization_id,
        )

        provider_event_id = f"tt_flow_{round(valid_lat, 4)}_{round(valid_lon, 4)}_{int(now_utc.timestamp())}"

        raw_event = RawEvent(
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            provider_event_id=provider_event_id,
            fingerprint=fingerprint,
            source_timestamp=now_utc,
            raw_payload=sanitized_payload,
            metadata={
                "operation": "flowSegmentData",
                "requested_lat": valid_lat,
                "requested_lon": valid_lon,
                "unit": unit,
                "correlation_id": correlation_id,
                "route_id": route_id,
                "shipment_id": shipment_id,
                "facility_id": facility_id,
            },
            org_id=organization_id,
        )

        return IngestionBatch(
            provider_name=self.provider_name,
            events=[raw_event],
            source_metadata={"endpoint": base_url, "operation": "flowSegmentData"},
            fetched_at=now_utc,
        )

    def fetch_incidents(
        self,
        bbox: Sequence[float],
        fields: Optional[str] = None,
        language: str = "en-GB",
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        route_id: Optional[str] = None,
        shipment_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch traffic incident details within a specified bounding box (minLon, minLat, maxLon, maxLat)."""
        if len(bbox) != 4:
            raise ProviderValidationError(
                f"Bounding box must contain exactly 4 coordinates (minLon, minLat, maxLon, maxLat), got {len(bbox)}",
                provider_name=self.provider_name,
            )

        min_lon, min_lat, max_lon, max_lat = [float(x) for x in bbox]

        # Validate bounding coordinates
        try:
            valid_min_lat, valid_min_lon = CoordinateValidator.validate(min_lat, min_lon)
            valid_max_lat, valid_max_lon = CoordinateValidator.validate(max_lat, max_lon)
        except (ValueError, TypeError) as ve:
            raise ProviderValidationError(
                f"Invalid bounding box coordinate: {str(ve)}",
                provider_name=self.provider_name,
            ) from ve

        if valid_min_lat > valid_max_lat:
            raise ProviderValidationError(
                f"minLat ({valid_min_lat}) cannot be greater than maxLat ({valid_max_lat})",
                provider_name=self.provider_name,
            )

        api_key = self.resolve_api_key()
        base_url = DEFAULT_TOMTOM_INCIDENTS_URL

        params: Dict[str, Any] = {
            "key": api_key,
            "bbox": f"{valid_min_lon},{valid_min_lat},{valid_max_lon},{valid_max_lat}",
            "language": language,
        }
        if fields:
            params["fields"] = fields

        safe_url = self._sanitize_url_for_logging(f"{base_url}?bbox={params['bbox']}")
        logger.debug("Executing TomTom incidents request: %s (correlation_id=%s)", safe_url, correlation_id)

        try:
            resp = self.client.get(base_url, params=params)
        except httpx.TimeoutException as te:
            raise ProviderTimeoutError(
                f"TomTom incidents request timed out: {str(te)}",
                provider_name=self.provider_name,
            ) from te
        except httpx.RequestError as re_err:
            raise ProviderConnectionError(
                f"TomTom network connection failure: {str(re_err)}",
                provider_name=self.provider_name,
            ) from re_err

        status = resp.status_code
        if status in (401, 403):
            raise ProviderAuthenticationError(
                "TomTom authentication failed: Invalid or unauthorized API key.",
                provider_name=self.provider_name,
                status_code=status,
            )
        if status == 429:
            retry_after_hdr = resp.headers.get("Retry-After")
            retry_after_val = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
            raise ProviderRateLimitError(
                "TomTom rate limit exceeded (HTTP 429).",
                provider_name=self.provider_name,
                retry_after=retry_after_val,
            )
        if status == 400:
            raise ProviderValidationError(
                f"TomTom rejected incident query parameters (HTTP 400): {resp.text[:200]}",
                provider_name=self.provider_name,
            )
        if status in (500, 502, 503, 504):
            raise ProviderResponseError(
                f"TomTom upstream server error (HTTP {status})",
                status_code=status,
                provider_name=self.provider_name,
            )
        if status >= 400:
            raise ProviderResponseError(
                f"TomTom HTTP error {status}: {resp.text[:200]}",
                status_code=status,
                provider_name=self.provider_name,
            )

        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("Response root must be a JSON object")
        except Exception as exc:
            raise ProviderResponseError(
                f"TomTom returned malformed JSON payload: {str(exc)}",
                provider_name=self.provider_name,
            ) from exc

        now_utc = datetime.now(timezone.utc)
        events: List[RawEvent] = []
        raw_incidents = data.get("incidents", [])

        for idx, inc in enumerate(raw_incidents):
            if not isinstance(inc, dict):
                continue
            sanitized_inc = SecretResolver.sanitize_payload(inc)
            inc_id = inc.get("id") or inc.get("properties", {}).get("id") or f"inc_gen_{idx}_{int(now_utc.timestamp())}"
            fingerprint = self.compute_incident_fingerprint(incident_id=inc_id, org_id=organization_id)

            raw_ev = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=str(inc_id),
                fingerprint=fingerprint,
                source_timestamp=now_utc,
                raw_payload=sanitized_inc,
                metadata={
                    "operation": "incidentDetails",
                    "bbox": list(bbox),
                    "correlation_id": correlation_id,
                    "route_id": route_id,
                    "shipment_id": shipment_id,
                },
                org_id=organization_id,
            )
            events.append(raw_ev)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            source_metadata={"endpoint": base_url, "operation": "incidentDetails", "count": len(events)},
            fetched_at=now_utc,
        )

    def fetch(self, **kwargs: Any) -> IngestionBatch:
        """Unified fetch entry point supporting flow or incident queries."""
        if "bbox" in kwargs and kwargs["bbox"] is not None:
            return self.fetch_incidents(**kwargs)

        lat = kwargs.get("latitude") if kwargs.get("latitude") is not None else kwargs.get("lat")
        lon = kwargs.get("longitude") if kwargs.get("longitude") is not None else kwargs.get("lon")

        if lat is not None and lon is not None:
            clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("latitude", "longitude", "lat", "lon")}
            return self.fetch_flow(latitude=lat, longitude=lon, **clean_kwargs)

        locations = kwargs.get("locations")
        if locations and isinstance(locations, list):
            all_events: List[RawEvent] = []
            for loc in locations:
                sub_batch = self.fetch_flow(
                    latitude=loc.get("latitude", loc.get("lat")),
                    longitude=loc.get("longitude", loc.get("lon")),
                    **{k: v for k, v in kwargs.items() if k != "locations"},
                )
                all_events.extend(sub_batch.events)
            return IngestionBatch(
                provider_name=self.provider_name,
                events=all_events,
                source_metadata={"batch_size": len(all_events)},
                fetched_at=datetime.now(timezone.utc),
            )

        raise ProviderValidationError(
            "Either coordinates (latitude, longitude) or bounding box (bbox) are required for TomTom fetch.",
            provider_name=self.provider_name,
        )

    def health_check(self) -> ProviderHealthResult:
        """Perform non-destructive connectivity and authentication probe using reference coordinates."""
        start = time.perf_counter()

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

        base_url = getattr(self.config, "base_url", None) or DEFAULT_TOMTOM_FLOW_URL
        probe_lat, probe_lon = HEALTH_CHECK_COORDINATES
        params = {
            "key": api_key,
            "point": f"{probe_lat},{probe_lon}",
            "unit": "KMPH",
        }

        try:
            resp = self.client.get(base_url, params=params)
            latency = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                try:
                    payload = resp.json()
                    if isinstance(payload, dict) and "flowSegmentData" in payload:
                        return ProviderHealthResult(
                            provider_name=self.provider_name,
                            status=ProviderHealthStatus.HEALTHY,
                            latency_ms=latency,
                            message="TomTom Traffic API operational and responsive.",
                            details={"status_code": 200},
                        )
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.UNHEALTHY,
                        latency_ms=latency,
                        message="TomTom API returned malformed response structure.",
                    )
                except Exception:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.UNHEALTHY,
                        latency_ms=latency,
                        message="TomTom response could not be parsed as JSON.",
                    )

            if resp.status_code in (401, 403):
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="TomTom authentication failed: Invalid or expired API key.",
                    details={"status_code": resp.status_code},
                )

            if resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="TomTom quota exhausted or rate limit active (HTTP 429).",
                    details={"status_code": 429},
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"TomTom returned unexpected HTTP status {resp.status_code}.",
                details={"status_code": resp.status_code},
            )

        except httpx.TimeoutException:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message="TomTom health probe timed out.",
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"TomTom connection error: {exc.__class__.__name__}",
            )


class TomTomNormalizer(BaseEventNormalizer):
    """Normalizes TomTom traffic flow and incident payloads into CanonicalExternalEvent models.

    Conforms strictly to existing canonical taxonomy (TRAFFIC_CONGESTION, ROAD_INCIDENT,
    ROAD_CLOSURE, CUSTOM) without artificial risk inflation.
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        p_name = getattr(raw_event, "provider_name", "")
        return p_name.lower().strip() == "tomtom"

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        p = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        meta = raw_event.metadata or {}
        operation = meta.get("operation")

        if "flowSegmentData" in p or operation == "flowSegmentData":
            return self._normalize_flow(raw_event, p, validation_errors)
        return self._normalize_incident(raw_event, p, validation_errors)

    def _normalize_flow(
        self,
        raw_event: RawEvent,
        p: Dict[str, Any],
        validation_errors: List[str],
    ) -> CanonicalExternalEvent:
        flow = p.get("flowSegmentData", p)
        meta = raw_event.metadata or {}

        # 1. Timing
        event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 2. Location
        lat = meta.get("requested_lat")
        lon = meta.get("requested_lon")

        # Fallback to coordinates array in flow data if available
        if (lat is None or lon is None) and "coordinates" in flow:
            coords = flow.get("coordinates", {}).get("coordinate", [])
            if coords and isinstance(coords, list):
                lat = coords[0].get("latitude")
                lon = coords[0].get("longitude")

        location_obj: Optional[EventLocation] = None
        if lat is not None and lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(latitude=v_lat, longitude=v_lon)
            except Exception as exc:
                validation_errors.append(f"Flow coordinate validation failed: {str(exc)}")

        # 3. Attributes
        norm_attrs: Dict[str, Any] = {"operation": "flowSegmentData"}
        current_speed = flow.get("currentSpeed")
        free_flow_speed = flow.get("freeFlowSpeed")
        current_travel_time = flow.get("currentTravelTime")
        free_flow_travel_time = flow.get("freeFlowTravelTime")
        confidence = flow.get("confidence")
        frc = flow.get("frc")
        road_closure = flow.get("roadClosure", False)

        if current_speed is not None:
            norm_attrs["current_speed_kmh"] = float(current_speed)
        if free_flow_speed is not None:
            norm_attrs["free_flow_speed_kmh"] = float(free_flow_speed)
        if current_travel_time is not None:
            norm_attrs["current_travel_time_sec"] = float(current_travel_time)
        if free_flow_travel_time is not None:
            norm_attrs["free_flow_travel_time_sec"] = float(free_flow_travel_time)
        if confidence is not None:
            norm_attrs["confidence"] = float(confidence)
        if frc is not None:
            norm_attrs["road_category"] = str(frc)
        if road_closure is not None:
            norm_attrs["road_closure"] = bool(road_closure)

        # Congestion ratio calculation
        congestion_ratio = 1.0
        if current_speed is not None and free_flow_speed and free_flow_speed > 0:
            congestion_ratio = current_speed / free_flow_speed
            norm_attrs["congestion_ratio"] = round(congestion_ratio, 2)

        # 4. Canonical Event Type & Severity
        delay_min: Optional[float] = None
        if current_travel_time is not None and free_flow_travel_time is not None:
            diff_sec = max(0.0, current_travel_time - free_flow_travel_time)
            delay_min = round(diff_sec / 60.0, 1)
            norm_attrs["delay_minutes"] = delay_min

        if road_closure:
            canonical_type = CanonicalEventType.ROAD_CLOSURE
            severity = EventSeverity.HIGH
        elif congestion_ratio < 0.4 or (delay_min and delay_min > 20.0):
            canonical_type = CanonicalEventType.TRAFFIC_CONGESTION
            severity = EventSeverity.HIGH
        elif congestion_ratio < 0.7 or (delay_min and delay_min > 5.0):
            canonical_type = CanonicalEventType.TRAFFIC_CONGESTION
            severity = EventSeverity.MEDIUM
        else:
            # Normal ambient traffic flow
            canonical_type = CanonicalEventType.CUSTOM
            norm_attrs["event_classification"] = "TRAFFIC_FLOW"
            if congestion_ratio < 0.85:
                severity = EventSeverity.LOW
            else:
                severity = EventSeverity.INFO

        correlation = EntityCorrelation(
            route_id=meta.get("route_id"),
            shipment_id=meta.get("shipment_id"),
            facility_id=meta.get("facility_id"),
        )

        quality = EventQuality.VALID if (location_obj and correlation.is_correlated and not validation_errors) else (
            EventQuality.PARTIAL if (location_obj and not validation_errors) else EventQuality.INVALID
        )

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=canonical_type,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=correlation,
            status="FLOW_OBSERVED",
            severity=severity,
            delay_minutes=delay_min,
            confidence=float(confidence) if confidence is not None else 0.95,
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=norm_attrs,
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )

    def _normalize_incident(
        self,
        raw_event: RawEvent,
        p: Dict[str, Any],
        validation_errors: List[str],
    ) -> CanonicalExternalEvent:
        props = p.get("properties", p)
        geom = p.get("geometry", {})
        meta = raw_event.metadata or {}

        # 1. Timing
        ts_val = props.get("startTime") or raw_event.source_timestamp or raw_event.ingested_at
        try:
            event_ts = TimestampNormalizer.parse_to_utc(ts_val)
        except Exception as exc:
            event_ts = raw_event.ingested_at
            validation_errors.append(f"Incident timestamp normalization fallback: {str(exc)}")

        # 2. Location from GeoJSON coordinates: [longitude, latitude]
        location_obj: Optional[EventLocation] = None
        coordinates = geom.get("coordinates")
        lat = None
        lon = None
        if coordinates and isinstance(coordinates, list) and len(coordinates) >= 2:
            # GeoJSON format is [lon, lat]
            if isinstance(coordinates[0], (int, float)) and isinstance(coordinates[1], (int, float)):
                lon = float(coordinates[0])
                lat = float(coordinates[1])
            elif isinstance(coordinates[0], list) and len(coordinates[0]) >= 2:
                # LineString coordinates [[lon, lat], ...]
                lon = float(coordinates[0][0])
                lat = float(coordinates[0][1])

        if lat is not None and lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=props.get("roadName") or props.get("from"),
                )
            except Exception as exc:
                validation_errors.append(f"Incident coordinate validation failed: {str(exc)}")

        # 3. Incident Attributes
        norm_attrs: Dict[str, Any] = {"operation": "incidentDetails"}
        inc_id = p.get("id") or props.get("id")
        icon_category = props.get("iconCategory")
        magnitude_delay = props.get("magnitudeOfDelay")
        delay_sec = props.get("delay")
        length_meters = props.get("length")
        road_name = props.get("roadName")
        road_numbers = props.get("roadNumbers")
        events_list = props.get("events", [])
        primary_desc = events_list[0].get("description") if events_list and isinstance(events_list, list) else None

        if inc_id:
            norm_attrs["incident_id"] = str(inc_id)
        if icon_category is not None:
            norm_attrs["icon_category"] = int(icon_category)
        if magnitude_delay is not None:
            norm_attrs["magnitude_of_delay"] = int(magnitude_delay)
        if delay_sec is not None:
            norm_attrs["delay_seconds"] = float(delay_sec)
            norm_attrs["delay_minutes"] = round(float(delay_sec) / 60.0, 1)
        if length_meters is not None:
            norm_attrs["length_meters"] = float(length_meters)
        if road_name:
            norm_attrs["road_name"] = str(road_name)
        if road_numbers:
            norm_attrs["road_numbers"] = list(road_numbers)
        if primary_desc:
            norm_attrs["description"] = str(primary_desc)
        if "from" in props:
            norm_attrs["from_location"] = str(props["from"])
        if "to" in props:
            norm_attrs["to_location"] = str(props["to"])

        delay_minutes = norm_attrs.get("delay_minutes")

        # 4. Canonical Event Type & Severity Mapping
        # iconCategory 8 = Road Closed
        # iconCategory 6 = Jam / Congestion
        # iconCategory 1 = Accident
        # iconCategory 7 = Lane Closed
        # iconCategory 9 = Road Works
        desc_lower = (primary_desc or "").lower()
        is_closure = (icon_category == 8) or ("closed" in desc_lower)

        if is_closure:
            canonical_type = CanonicalEventType.ROAD_CLOSURE
            norm_attrs["is_closed"] = True
        elif icon_category == 6 or "jam" in desc_lower or "congestion" in desc_lower:
            canonical_type = CanonicalEventType.TRAFFIC_CONGESTION
        else:
            canonical_type = CanonicalEventType.ROAD_INCIDENT

        # Severity mapping:
        # magnitudeOfDelay: 0=unknown, 1=minor, 2=moderate, 3=major, 4=indefinite/blocked
        if is_closure or magnitude_delay == 4 or (delay_minutes and delay_minutes >= 60.0):
            severity = EventSeverity.CRITICAL
        elif magnitude_delay == 3 or (delay_minutes and delay_minutes >= 30.0):
            severity = EventSeverity.HIGH
        elif magnitude_delay == 2 or (delay_minutes and delay_minutes >= 10.0):
            severity = EventSeverity.MEDIUM
        else:
            severity = EventSeverity.LOW

        correlation = EntityCorrelation(
            route_id=meta.get("route_id") or p.get("route_id"),
            shipment_id=meta.get("shipment_id") or p.get("shipment_id"),
        )

        quality = EventQuality.VALID if (location_obj and correlation.is_correlated and not validation_errors) else (
            EventQuality.PARTIAL if (location_obj and not validation_errors) else EventQuality.INVALID
        )

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=str(inc_id) if inc_id else raw_event.provider_event_id,
            event_type=canonical_type,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=correlation,
            status="ACTIVE",
            severity=severity,
            delay_minutes=delay_minutes,
            confidence=0.92,
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=norm_attrs,
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )
