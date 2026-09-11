"""Transport for NSW (TfNSW) Rail GTFS-Realtime provider adapter and normalizer implementation.

Ingests real-time train network intelligence, trip updates, vehicle positions, and service alerts
from official Transport for NSW GTFS-Realtime v2 Protocol Buffer (protobuf) feeds,
mapping provider-specific protobuf records into strongly typed RawEvent and CanonicalExternalEvent
models without schema leakage.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2
import httpx
from pydantic import BaseModel, ConfigDict, Field

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

logger = logging.getLogger("riskwise.integrations.providers.rail")

# Verified Transport for NSW GTFS-Realtime v2 Endpoints
DEFAULT_TFNSW_BASE_URL = "https://api.transport.nsw.gov.au/v2/gtfs"
DEFAULT_TFNSW_TRIP_UPDATES_URL = "https://api.transport.nsw.gov.au/v2/gtfs/realtime/sydneytrains"
DEFAULT_TFNSW_VEHICLE_POSITIONS_URL = "https://api.transport.nsw.gov.au/v2/gtfs/vehiclepos/sydneytrains"
DEFAULT_TFNSW_ALERTS_URL = "https://api.transport.nsw.gov.au/v2/gtfs/alerts/sydneytrains"

# Delay thresholds for conservative supply-chain rail classification (in seconds)
DELAY_MINOR_THRESHOLD_SECONDS = 300       # 5 minutes: minor operational delay (INFO/LOW)
DELAY_MEDIUM_THRESHOLD_SECONDS = 900      # 15 minutes: moderate delay (MEDIUM)
DELAY_MAJOR_THRESHOLD_SECONDS = 1800      # 30 minutes: major delay (HIGH)
# > 1800 seconds or CANCELED -> CRITICAL disruption


# =====================================================================
# Feed Type Enumeration & Models
# =====================================================================

class RailFeedType(str, Enum):
    """Supported GTFS-Realtime rail feed categories."""

    TRIP_UPDATES = "trip_updates"
    VEHICLE_POSITIONS = "vehicle_positions"
    ALERTS = "alerts"


class RailFeedConfig(BaseModel):
    """Configuration mapping for GTFS-Realtime rail endpoints."""

    model_config = ConfigDict(extra="allow")

    feed_type: RailFeedType = RailFeedType.TRIP_UPDATES
    endpoint_url: Optional[str] = None
    operator: str = "sydneytrains"  # "sydneytrains" or "nswtrains"


# =====================================================================
# Protobuf Deserialization Helpers
# =====================================================================

def _safe_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _serialize_trip_update(tu: gtfs_realtime_pb2.TripUpdate) -> Dict[str, Any]:
    """Extract a JSON-safe dictionary from a GTFS-Realtime TripUpdate protobuf message."""
    trip = tu.trip
    sched_rel_name = "SCHEDULED"
    if trip.HasField("schedule_relationship"):
        sched_rel_name = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.Name(trip.schedule_relationship)

    # Extract delay from stop_time_update (primary or highest delay)
    stop_updates: List[Dict[str, Any]] = []
    max_delay = 0
    primary_delay: Optional[int] = None
    primary_stop_id: Optional[str] = None

    for stu in tu.stop_time_update:
        arr_delay = stu.arrival.delay if stu.HasField("arrival") and stu.arrival.HasField("delay") else None
        dep_delay = stu.departure.delay if stu.HasField("departure") and stu.departure.HasField("delay") else None
        arr_time = stu.arrival.time if stu.HasField("arrival") and stu.arrival.HasField("time") else None
        dep_time = stu.departure.time if stu.HasField("departure") and stu.departure.HasField("time") else None

        stu_dict = {
            "stop_sequence": stu.stop_sequence if stu.HasField("stop_sequence") else None,
            "stop_id": _safe_str(stu.stop_id) if stu.HasField("stop_id") else None,
            "arrival_delay": arr_delay,
            "departure_delay": dep_delay,
            "arrival_time": arr_time,
            "departure_time": dep_time,
        }
        stop_updates.append(stu_dict)

        effective_delay = arr_delay if arr_delay is not None else dep_delay
        if effective_delay is not None:
            if primary_delay is None:
                primary_delay = effective_delay
                primary_stop_id = stu_dict["stop_id"]
            if abs(effective_delay) > abs(max_delay):
                max_delay = effective_delay

    if primary_delay is None and tu.HasField("delay"):
        primary_delay = tu.delay

    return {
        "entity_type": "TripUpdate",
        "trip_id": _safe_str(trip.trip_id) if trip.HasField("trip_id") else None,
        "route_id": _safe_str(trip.route_id) if trip.HasField("route_id") else None,
        "start_time": _safe_str(trip.start_time) if trip.HasField("start_time") else None,
        "start_date": _safe_str(trip.start_date) if trip.HasField("start_date") else None,
        "schedule_relationship": sched_rel_name,
        "vehicle_id": _safe_str(tu.vehicle.id) if tu.HasField("vehicle") and tu.vehicle.HasField("id") else None,
        "timestamp": tu.timestamp if tu.HasField("timestamp") else None,
        "delay_seconds": primary_delay,
        "max_delay_seconds": max_delay if max_delay != 0 else primary_delay,
        "stop_id": primary_stop_id,
        "stop_time_updates": stop_updates,
    }


def _serialize_vehicle_position(vp: gtfs_realtime_pb2.VehiclePosition) -> Dict[str, Any]:
    """Extract a JSON-safe dictionary from a GTFS-Realtime VehiclePosition protobuf message."""
    trip = vp.trip if vp.HasField("trip") else None
    pos = vp.position if vp.HasField("position") else None
    veh = vp.vehicle if vp.HasField("vehicle") else None

    status_name = "IN_TRANSIT_TO"
    if vp.HasField("current_status"):
        status_name = gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.Name(vp.current_status)

    return {
        "entity_type": "VehiclePosition",
        "vehicle_id": _safe_str(veh.id) if veh and veh.HasField("id") else None,
        "vehicle_label": _safe_str(veh.label) if veh and veh.HasField("label") else None,
        "trip_id": _safe_str(trip.trip_id) if trip and trip.HasField("trip_id") else None,
        "route_id": _safe_str(trip.route_id) if trip and trip.HasField("route_id") else None,
        "latitude": float(pos.latitude) if pos and pos.HasField("latitude") else None,
        "longitude": float(pos.longitude) if pos and pos.HasField("longitude") else None,
        "bearing": float(pos.bearing) if pos and pos.HasField("bearing") else None,
        "speed_mps": float(pos.speed) if pos and pos.HasField("speed") else None,
        "current_stop_sequence": vp.current_stop_sequence if vp.HasField("current_stop_sequence") else None,
        "stop_id": _safe_str(vp.stop_id) if vp.HasField("stop_id") else None,
        "current_status": status_name,
        "timestamp": vp.timestamp if vp.HasField("timestamp") else None,
    }


def _serialize_alert(al: gtfs_realtime_pb2.Alert) -> Dict[str, Any]:
    """Extract a JSON-safe dictionary from a GTFS-Realtime Alert protobuf message."""
    cause_name = "UNKNOWN_CAUSE"
    if al.HasField("cause"):
        cause_name = gtfs_realtime_pb2.Alert.Cause.Name(al.cause)

    effect_name = "UNKNOWN_EFFECT"
    if al.HasField("effect"):
        effect_name = gtfs_realtime_pb2.Alert.Effect.Name(al.effect)

    # Header text
    header_text: Optional[str] = None
    if al.HasField("header_text") and al.header_text.translation:
        header_text = al.header_text.translation[0].text

    # Description text
    desc_text: Optional[str] = None
    if al.HasField("description_text") and al.description_text.translation:
        desc_text = al.description_text.translation[0].text

    # Active period
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    if al.active_period:
        ap = al.active_period[0]
        start_ts = ap.start if ap.HasField("start") else None
        end_ts = ap.end if ap.HasField("end") else None

    # Informed entities
    informed_routes: List[str] = []
    informed_stops: List[str] = []
    for ie in al.informed_entity:
        if ie.HasField("route_id") and ie.route_id:
            informed_routes.append(ie.route_id)
        if ie.HasField("stop_id") and ie.stop_id:
            informed_stops.append(ie.stop_id)

    return {
        "entity_type": "Alert",
        "cause": cause_name,
        "effect": effect_name,
        "header_text": header_text,
        "description_text": desc_text,
        "active_period_start": start_ts,
        "active_period_end": end_ts,
        "route_id": informed_routes[0] if informed_routes else None,
        "stop_id": informed_stops[0] if informed_stops else None,
        "informed_routes": informed_routes,
        "informed_stops": informed_stops,
    }


# =====================================================================
# Dedicated Provider Adapter: RailAdapter
# =====================================================================

class RailAdapter(BaseProviderAdapter):
    """Production provider adapter for Transport for NSW (TfNSW) Rail GTFS-Realtime integration."""

    provider_name: str = "rail"
    provider_type: ProviderType = ProviderType.RAIL
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=1000,
        supported_entities=["train", "trip", "route", "stop", "station"],
        supported_modalities=["rail", "train", "gtfs_realtime"],
    )

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        secret: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
        secret_resolver: Optional[SecretResolver] = None,
        idempotency_engine: Optional[IdempotencyEngine] = None,
        rate_limiter: Optional[ProviderRateLimiter] = None,
    ) -> None:
        if config is None:
            config = ProviderConfig(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                base_url=DEFAULT_TFNSW_TRIP_UPDATES_URL,
                auth_mode=AuthMode.API_KEY_HEADER,
                secret_ref="env:TFNSW_API_KEY",
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

    @property
    def client(self) -> httpx.Client:
        """Provide an active HTTP client instance."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            timeout = getattr(self.config, "timeout_seconds", 15.0)
            self._internal_client = httpx.Client(timeout=timeout)
        return self._internal_client

    def resolve_api_key(self) -> Optional[str]:
        """Resolve TfNSW API key securely. Returns None if unauthenticated feed is configured."""
        if self._secret:
            return self._secret

        secret_ref = getattr(self.config, "secret_ref", None) or "env:TFNSW_API_KEY"
        resolved = self.secret_resolver.resolve_secret(secret_ref)
        if resolved:
            return resolved

        fallback = self.secret_resolver.resolve_secret("TFNSW_API_KEY")
        if fallback:
            return fallback

        rail_fallback = self.secret_resolver.resolve_secret("RAIL_API_KEY")
        if rail_fallback:
            return rail_fallback

        return None

    def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    def get_feed_url(self, feed_type: RailFeedType, operator: str = "sydneytrains") -> str:
        """Resolve the official target endpoint for the given feed type and operator."""
        extra = getattr(self.config, "extra_settings", {}) or {}
        custom_url = extra.get(f"{feed_type.value}_url") or extra.get("endpoint_url")
        if custom_url:
            return custom_url

        # Check if base_url is explicitly configured for this specific feed
        base_url = getattr(self.config, "base_url", None)
        if base_url and base_url != DEFAULT_TFNSW_TRIP_UPDATES_URL:
            return base_url

        if feed_type == RailFeedType.TRIP_UPDATES:
            return f"{DEFAULT_TFNSW_BASE_URL}/realtime/{operator}"
        elif feed_type == RailFeedType.VEHICLE_POSITIONS:
            return f"{DEFAULT_TFNSW_BASE_URL}/vehiclepos/{operator}"
        elif feed_type == RailFeedType.ALERTS:
            return f"{DEFAULT_TFNSW_BASE_URL}/alerts/{operator}"

        return DEFAULT_TFNSW_TRIP_UPDATES_URL

    # -----------------------------------------------------------------
    # Ingestion Implementation
    # -----------------------------------------------------------------

    def fetch(
        self,
        feed_type: Optional[RailFeedType] = None,
        operator: str = "sydneytrains",
        org_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch and decode GTFS-Realtime Protocol Buffer messages from Transport for NSW.

        Parameters:
            feed_type: Category of feed (TRIP_UPDATES, VEHICLE_POSITIONS, or ALERTS).
            operator: Rail operator ("sydneytrains" or "nswtrains").
            org_id: Optional tenant isolation scope.

        Returns:
            IngestionBatch containing standardized RawEvent items for each feed entity.
        """
        resolved_feed_type = feed_type or RailFeedType.TRIP_UPDATES

        # 1. Rate limiting check
        rl_cfg = getattr(self.config, "rate_limit", None)
        if not self._rate_limiter.acquire(self.provider_name, rl_cfg):
            _, wait_time = self._rate_limiter.check_limit(self.provider_name, rl_cfg)
            raise ProviderRateLimitError(
                f"Rate limit exceeded for provider '{self.provider_name}'",
                provider_name=self.provider_name,
                retry_after_seconds=wait_time,
            )

        # 2. Build URL and headers
        url = self.get_feed_url(resolved_feed_type, operator=operator)
        headers = {"Accept": "application/x-google-protobuf"}
        api_key = self.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"apikey {api_key}"

        # 3. HTTP Request with bounded retry policy
        def _send_request() -> httpx.Response:
            try:
                resp = self.client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"Request timeout contacting TfNSW GTFS-Realtime feed: {str(exc)}",
                    provider_name=self.provider_name,
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderConnectionError(
                    f"Network failure contacting TfNSW GTFS-Realtime feed: {str(exc)}",
                    provider_name=self.provider_name,
                ) from exc

            if resp.status_code >= 500:
                raise ProviderConnectionError(
                    f"TfNSW upstream server error: HTTP {resp.status_code}",
                    provider_name=self.provider_name,
                    status_code=resp.status_code,
                )
            return resp

        response = self._retry_policy.execute(_send_request)

        # 4. HTTP Status Validation
        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(
                f"TfNSW authorization rejected with HTTP {response.status_code}. Verify API key.",
                provider_name=self.provider_name,
                status_code=response.status_code,
            )
        if response.status_code == 429:
            retry_after_hdr = response.headers.get("Retry-After")
            retry_after_sec = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
            raise ProviderRateLimitError(
                f"TfNSW rate limit exceeded (HTTP 429). Retry-After: {retry_after_sec or 'unspecified'}s",
                provider_name=self.provider_name,
                retry_after_seconds=retry_after_sec,
            )
        if response.status_code != 200:
            raise ProviderResponseError(
                f"TfNSW returned unexpected status code: HTTP {response.status_code}",
                provider_name=self.provider_name,
                status_code=response.status_code,
            )

        # 5. Protocol Buffer Deserialization
        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            feed.ParseFromString(response.content)
        except DecodeError as exc:
            raise ProviderResponseError(
                f"Failed to decode GTFS-Realtime protocol buffer binary payload: {str(exc)}",
                provider_name=self.provider_name,
            ) from exc

        # 6. Parse Feed Header and Entities
        header_ts = feed.header.timestamp if feed.header.HasField("timestamp") else None
        header_dt = datetime.fromtimestamp(header_ts, tz=timezone.utc) if header_ts else None

        events: List[RawEvent] = []
        now_utc = datetime.now(timezone.utc)

        for entity in feed.entity:
            entity_id = entity.id
            if entity.is_deleted:
                continue

            raw_dict: Optional[Dict[str, Any]] = None
            if entity.HasField("trip_update"):
                raw_dict = _serialize_trip_update(entity.trip_update)
            elif entity.HasField("vehicle"):
                raw_dict = _serialize_vehicle_position(entity.vehicle)
            elif entity.HasField("alert"):
                raw_dict = _serialize_alert(entity.alert)

            if raw_dict is None:
                continue

            raw_dict["entity_id"] = entity_id
            raw_dict["feed_header_timestamp"] = header_ts
            raw_dict["operator"] = operator

            # Compute deterministic fingerprint
            fingerprint = self.compute_fingerprint(raw_dict, org_id=org_id)

            # Observation timestamp
            entity_ts = raw_dict.get("timestamp")
            obs_dt = (
                datetime.fromtimestamp(entity_ts, tz=timezone.utc)
                if entity_ts
                else (header_dt or now_utc)
            )

            provider_event_id = f"rail:{operator}:{entity_id}:{entity_ts or int(now_utc.timestamp())}"

            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=provider_event_id,
                fingerprint=fingerprint,
                source_timestamp=obs_dt,
                ingested_at=now_utc,
                raw_payload=raw_dict,
                metadata={
                    "feed_type": resolved_feed_type.value,
                    "operator": operator,
                    "header_timestamp": header_ts,
                    "entity_type": raw_dict["entity_type"],
                },
                org_id=org_id,
                event_type="RAIL_SIGNAL",
            )
            events.append(raw_event)

        logger.info(
            "Successfully fetched %d rail %s entities from TfNSW (%s)",
            len(events),
            resolved_feed_type.value,
            operator,
        )
        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            source_metadata={
                "feed_type": resolved_feed_type.value,
                "operator": operator,
                "header_timestamp": header_ts,
                "count": len(events),
                "endpoint": url,
            },
            fetched_at=now_utc,
        )

    # -----------------------------------------------------------------
    # Diagnostic Health Check
    # -----------------------------------------------------------------

    def health_check(self) -> ProviderHealthResult:
        """Perform a diagnostic connectivity and protobuf parsing health check.

        Validates that the GTFS-Realtime feed is reachable, authorized, and can be
        deserialized into a valid FeedMessage.
        """
        start_time = time.monotonic()
        api_key = self.resolve_api_key()

        # Check if auth mode is API_KEY_HEADER and no key is configured
        auth_mode = getattr(self.config, "auth_mode", AuthMode.NONE)
        if auth_mode == AuthMode.API_KEY_HEADER and not api_key:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                latency_ms=0.0,
                message="Rail provider unconfigured: missing TfNSW API key (TFNSW_API_KEY).",
                details={"configured": False, "error_category": "CONFIGURATION"},
            )

        probe_url = self.get_feed_url(RailFeedType.ALERTS)
        headers = {"Accept": "application/x-google-protobuf"}
        if api_key:
            headers["Authorization"] = f"apikey {api_key}"

        try:
            resp = self.client.get(probe_url, headers=headers, timeout=5.0)
            latency = (time.monotonic() - start_time) * 1000.0

            if resp.status_code == 200:
                # Verify body is valid GTFS-Realtime protobuf
                feed = gtfs_realtime_pb2.FeedMessage()
                try:
                    feed.ParseFromString(resp.content)
                except DecodeError:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.UNHEALTHY,
                        latency_ms=round(latency, 2),
                        message="TfNSW health probe returned HTTP 200 but body is not valid GTFS-Realtime protobuf.",
                        details={"configured": True, "error_category": "RESPONSE"},
                    )

                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.HEALTHY,
                    latency_ms=round(latency, 2),
                    message="TfNSW GTFS-Realtime rail probe succeeded and protobuf verified.",
                    details={
                        "configured": True,
                        "endpoint": probe_url,
                        "entity_count": len(feed.entity),
                    },
                )
            elif resp.status_code in (401, 403):
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"TfNSW rail authorization rejected: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "AUTHENTICATION", "status_code": resp.status_code},
                )
            elif resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message="TfNSW rate limit or quota exceeded (HTTP 429).",
                    details={"configured": True, "error_category": "RATE_LIMIT"},
                )
            elif resp.status_code >= 500:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"TfNSW upstream error: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "UPSTREAM", "status_code": resp.status_code},
                )
            else:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message=f"TfNSW returned unexpected status code: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "RESPONSE", "status_code": resp.status_code},
                )
        except httpx.TimeoutException as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message=f"TfNSW probe timeout: {str(exc)}",
                details={"configured": True, "error_category": "TIMEOUT"},
            )
        except Exception as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"TfNSW probe connection failed: {str(exc)}",
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
        """Create a collision-resistant SHA-256 fingerprint from GTFS-Realtime entity state.

        Deduplicates identical resubmissions while preserving legitimate consecutive updates
        differing in coordinates, delay, or timestamps.
        """
        entity_type = payload.get("entity_type", "UNKNOWN")
        entity_id = str(payload.get("entity_id") or "")
        trip_id = str(payload.get("trip_id") or "")
        route_id = str(payload.get("route_id") or "")
        vehicle_id = str(payload.get("vehicle_id") or "")
        ts = str(payload.get("timestamp") or payload.get("feed_header_timestamp") or "")

        pos_or_metric_key = ""
        if entity_type == "VehiclePosition":
            lat = payload.get("latitude")
            lon = payload.get("longitude")
            lat_str = f"{float(lat):.4f}" if lat is not None else "none"
            lon_str = f"{float(lon):.4f}" if lon is not None else "none"
            status = payload.get("current_status", "")
            pos_or_metric_key = f"pos:{lat_str},{lon_str}:status:{status}"
        elif entity_type == "TripUpdate":
            delay = payload.get("delay_seconds")
            sched = payload.get("schedule_relationship", "")
            stop = payload.get("stop_id", "")
            pos_or_metric_key = f"delay:{delay}:sched:{sched}:stop:{stop}"
        elif entity_type == "Alert":
            cause = payload.get("cause", "")
            effect = payload.get("effect", "")
            pos_or_metric_key = f"cause:{cause}:effect:{effect}"

        org_prefix = f"org:{org_id}:" if org_id else "global:"
        raw_key = (
            f"{org_prefix}rail:{entity_type}:{entity_id}:{trip_id}:"
            f"{route_id}:{vehicle_id}:ts:{ts}:{pos_or_metric_key}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# =====================================================================
# Canonical Normalizer: RailNormalizer
# =====================================================================

class RailNormalizer(BaseEventNormalizer):
    """Production normalizer translating GTFS-Realtime RawEvent items into CanonicalExternalEvent models.

    Strict Freight vs Passenger Rail Boundary:
    TfNSW feeds represent passenger rail networks (Sydney Trains and NSW Trains).
    Data serves as rail corridor disruption, delay, and congestion intelligence.
    Passenger rail data is NEVER used to infer commercial freight shipment locations,
    container status, or shipment ETAs.
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Return True if the raw event was produced by the Rail provider."""
        return raw_event.provider_name.lower().strip() == "rail"

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform a rail RawEvent into a CanonicalExternalEvent.

        Adheres strictly to the canonical model without schema leakage:
        - Maps vehicle positions to CanonicalEventType.LOCATION_UPDATE
        - Maps delay updates conservatively to TRAIN_DELAY or RAIL_DISRUPTION
        - Maps service alerts to RAIL_DISRUPTION, TRAIN_DELAY, or CUSTOM based on effect
        - Preserves route, stop, vehicle, and trip identifiers in EntityCorrelation
        - Strictly prevents false correlation to shipment_id
        """
        payload = raw_event.raw_payload or {}
        entity_type = payload.get("entity_type", "UNKNOWN")
        validation_errors: List[str] = []

        # 1. Timing Resolution
        event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 2. Extract Common Identifiers
        trip_id = payload.get("trip_id")
        route_id = payload.get("route_id")
        vehicle_id = payload.get("vehicle_id")
        stop_id = payload.get("stop_id")
        operator = payload.get("operator", "sydneytrains")

        custom_ids: Dict[str, str] = {
            "operator": str(operator),
            "entity_type": str(entity_type),
        }
        if trip_id:
            custom_ids["trip_id"] = str(trip_id)
        if route_id:
            custom_ids["route_id"] = str(route_id)
        if vehicle_id:
            custom_ids["vehicle_id"] = str(vehicle_id)
        if stop_id:
            custom_ids["stop_id"] = str(stop_id)

        # 3. Correlation (Strict Isolation: shipment_id is None unless explicitly given)
        correlation = EntityCorrelation(
            route_id=str(route_id) if route_id else None,
            shipment_id=payload.get("shipment_id"),
            carrier_id=payload.get("carrier_id"),
            custom_identifiers=custom_ids,
        )

        location_obj: Optional[EventLocation] = None
        canonical_type: CanonicalEventType = CanonicalEventType.CUSTOM
        severity: EventSeverity = EventSeverity.INFO
        status_str: Optional[str] = None
        delay_minutes: Optional[float] = None

        # -------------------------------------------------------------
        # Case A: VehiclePosition
        # -------------------------------------------------------------
        if entity_type == "VehiclePosition":
            canonical_type = CanonicalEventType.LOCATION_UPDATE
            severity = EventSeverity.INFO
            status_str = payload.get("current_status", "IN_TRANSIT_TO")

            lat = payload.get("latitude")
            lon = payload.get("longitude")
            if lat is not None or lon is not None:
                try:
                    valid_lat, valid_lon = CoordinateValidator.validate(lat, lon)
                    location_obj = EventLocation(
                        latitude=valid_lat,
                        longitude=valid_lon,
                        location_name=f"Train {vehicle_id or 'unknown'} (Route {route_id or 'N/A'})",
                        country_code="AU",
                    )
                except Exception as exc:
                    validation_errors.append(f"Coordinate validation failure: {str(exc)}")
                    location_obj = None

        # -------------------------------------------------------------
        # Case B: TripUpdate
        # -------------------------------------------------------------
        elif entity_type == "TripUpdate":
            delay_sec = payload.get("delay_seconds")
            sched_rel = payload.get("schedule_relationship", "SCHEDULED")

            if delay_sec is not None:
                delay_minutes = round(delay_sec / 60.0, 1)

            # Evaluate severity and event type based on conservative delay thresholds
            if sched_rel == "CANCELED":
                canonical_type = CanonicalEventType.RAIL_DISRUPTION
                severity = EventSeverity.CRITICAL
                status_str = "CANCELED"
            elif delay_sec is not None and delay_sec >= DELAY_MAJOR_THRESHOLD_SECONDS:
                canonical_type = CanonicalEventType.RAIL_DISRUPTION
                severity = EventSeverity.CRITICAL
                status_str = "MAJOR_DELAY"
            elif delay_sec is not None and delay_sec >= DELAY_MEDIUM_THRESHOLD_SECONDS:
                canonical_type = CanonicalEventType.TRAIN_DELAY
                severity = EventSeverity.HIGH
                status_str = "DELAYED"
            elif delay_sec is not None and delay_sec >= DELAY_MINOR_THRESHOLD_SECONDS:
                canonical_type = CanonicalEventType.TRAIN_DELAY
                severity = EventSeverity.MEDIUM
                status_str = "MODERATE_DELAY"
            elif delay_sec is not None and delay_sec > 60:
                canonical_type = CanonicalEventType.TRAIN_DELAY
                severity = EventSeverity.LOW
                status_str = "MINOR_DELAY"
            else:
                canonical_type = CanonicalEventType.TRAIN_DELAY
                severity = EventSeverity.INFO
                status_str = "ON_TIME"

        # -------------------------------------------------------------
        # Case C: Alert
        # -------------------------------------------------------------
        elif entity_type == "Alert":
            effect = payload.get("effect", "UNKNOWN_EFFECT")
            cause = payload.get("cause", "UNKNOWN_CAUSE")
            status_str = f"{cause}:{effect}"

            if effect == "NO_SERVICE":
                canonical_type = CanonicalEventType.RAIL_DISRUPTION
                severity = EventSeverity.CRITICAL
            elif effect == "SIGNIFICANT_DELAYS":
                canonical_type = CanonicalEventType.TRAIN_DELAY
                severity = EventSeverity.HIGH
            elif effect in ("REDUCED_SERVICE", "DETOUR", "MODIFIED_SERVICE"):
                canonical_type = CanonicalEventType.RAIL_DISRUPTION
                severity = EventSeverity.MEDIUM
            elif effect == "STOP_MOVED":
                canonical_type = CanonicalEventType.RAIL_DISRUPTION
                severity = EventSeverity.LOW
            elif effect == "ADDITIONAL_SERVICE":
                canonical_type = CanonicalEventType.CUSTOM
                severity = EventSeverity.INFO
            else:
                canonical_type = CanonicalEventType.RAIL_DISRUPTION
                severity = EventSeverity.INFO

        # -------------------------------------------------------------
        # Quality Evaluation
        # -------------------------------------------------------------
        if validation_errors:
            quality = EventQuality.PARTIAL
        elif entity_type == "VehiclePosition" and (location_obj is None or location_obj.latitude is None):
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

        normalized_attrs = dict(payload)
        normalized_attrs["mode"] = "RAIL"
        normalized_attrs["event_classification"] = f"RAIL_{entity_type.upper()}"
        normalized_attrs["passenger_rail_notice"] = (
            "Observation represents regional/passenger rail network infrastructure; "
            "not a commercial freight shipment."
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
            severity=severity,
            status=status_str,
            delay_minutes=delay_minutes,
            confidence=0.95 if quality == EventQuality.VALID else 0.70,
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

def create_rail_polling_job(
    job_id: str,
    cron_or_interval: str = "interval:30",
    feed_type: RailFeedType = RailFeedType.TRIP_UPDATES,
    operator: str = "sydneytrains",
    organization_id: Optional[str] = None,
    enabled: bool = True,
) -> ScheduledIngestionJob:
    """Create a standardized ScheduledIngestionJob descriptor for periodic TfNSW rail polling."""
    return ScheduledIngestionJob(
        job_id=job_id,
        provider_name="rail",
        cron_or_interval=cron_or_interval,
        enabled=enabled,
        parameters={
            "feed_type": feed_type.value,
            "operator": operator,
        },
        organization_id=organization_id,
    )
