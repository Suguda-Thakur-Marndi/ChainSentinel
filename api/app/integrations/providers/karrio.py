"""Karrio multi-carrier tracking and logistics integration provider adapter and normalizer.

Ingests real-time parcel and freight tracking events, status milestones, delivery delays,
exceptions, and ETA revisions from the Karrio open-source logistics tracking API.
Maps provider-specific tracker responses into strongly typed RawEvent and CanonicalExternalEvent
models without schema leakage.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

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
from app.integrations.boundaries import ScheduledIngestionJob, WebhookReceiver
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

logger = logging.getLogger("riskwise.integrations.providers.karrio")

# Verified Karrio Defaults
DEFAULT_KARRIO_BASE_URL = "http://localhost:5002"
DEFAULT_KARRIO_TRACKERS_ENDPOINT = "/v1/trackers"


# =====================================================================
# Karrio Domain Models & Status Taxonomy
# =====================================================================

class KarrioTrackingStatus(str, Enum):
    """Normalized tracking statuses defined by the Karrio platform."""

    PENDING = "pending"
    CREATED = "created"
    LABEL_PRINTED = "label_printed"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    READY_FOR_PICKUP = "ready_for_pickup"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    DELIVERY_DELAYED = "delivery_delayed"
    ON_HOLD = "on_hold"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class KarrioIncidentReason(str, Enum):
    """Standardized exception and incident reasons mapped by Karrio."""

    CARRIER_DAMAGED_PARCEL = "carrier_damaged_parcel"
    CARRIER_SORTING_ERROR = "carrier_sorting_error"
    CARRIER_ADDRESS_NOT_FOUND = "carrier_address_not_found"
    CARRIER_PARCEL_LOST = "carrier_parcel_lost"
    CARRIER_NOT_ENOUGH_TIME = "carrier_not_enough_time"
    CARRIER_VEHICLE_ISSUE = "carrier_vehicle_issue"
    CONSIGNEE_REFUSED = "consignee_refused"
    CONSIGNEE_BUSINESS_CLOSED = "consignee_business_closed"
    CONSIGNEE_NOT_AVAILABLE = "consignee_not_available"
    CONSIGNEE_NOT_HOME = "consignee_not_home"
    CONSIGNEE_INCORRECT_ADDRESS = "consignee_incorrect_address"
    CONSIGNEE_ACCESS_RESTRICTED = "consignee_access_restricted"
    CUSTOMS_DELAY = "customs_delay"
    CUSTOMS_DOCUMENTATION = "customs_documentation"
    CUSTOMS_DUTIES_UNPAID = "customs_duties_unpaid"
    WEATHER_DELAY = "weather_delay"
    NATURAL_DISASTER = "natural_disaster"
    UNKNOWN = "unknown"


class KarrioTrackingEvent(BaseModel):
    """Discrete milestone event emitted along a shipment's journey."""

    model_config = ConfigDict(extra="allow")

    date: Optional[str] = None
    time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None
    timestamp: Optional[Union[int, float]] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    reason: Optional[str] = None


class KarrioTracker(BaseModel):
    """Standardized Karrio package tracker representation."""

    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    carrier_name: str
    carrier_id: Optional[str] = None
    tracking_number: str
    status: str = "unknown"
    delivered: bool = False
    estimated_delivery: Optional[str] = None
    actual_delivery: Optional[str] = None
    events: List[KarrioTrackingEvent] = Field(default_factory=list)
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    info: Dict[str, Any] = Field(default_factory=dict)


# =====================================================================
# Dedicated Provider Adapter: KarrioAdapter
# =====================================================================

class KarrioAdapter(BaseProviderAdapter):
    """Production provider adapter for Karrio multi-carrier logistics tracking integration."""

    provider_name: str = "karrio"
    provider_type: ProviderType = ProviderType.LOGISTICS_TRACKING
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=True,
        supports_webhooks=True,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=500,
        supported_entities=["tracker", "tracking_number", "shipment", "parcel"],
        supported_modalities=["parcel", "freight", "logistics"],
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
                base_url=DEFAULT_KARRIO_BASE_URL,
                auth_mode=AuthMode.API_KEY_HEADER,
                secret_ref="env:KARRIO_API_KEY",
                rate_limit=RateLimitConfig(requests_per_minute=120),
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
        """Resolve Karrio API key securely from config, secret, or environment variables."""
        if self._secret:
            return self._secret

        secret_ref = getattr(self.config, "secret_ref", None) or "env:KARRIO_API_KEY"
        resolved = self.secret_resolver.resolve_secret(secret_ref)
        if resolved:
            return resolved

        fallback = self.secret_resolver.resolve_secret("KARRIO_API_KEY")
        if fallback:
            return fallback

        key_fallback = self.secret_resolver.resolve_secret("KARRIO_KEY")
        if key_fallback:
            return key_fallback

        return None

    def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    def get_tracker_url(self, carrier_name: str, tracking_number: str) -> str:
        """Build the target endpoint URL for querying a specific package tracker."""
        base_url = (getattr(self.config, "base_url", None) or DEFAULT_KARRIO_BASE_URL).rstrip("/")
        clean_carrier = carrier_name.strip().lower()
        clean_tracking = tracking_number.strip()
        return f"{base_url}/v1/trackers/{clean_carrier}/{clean_tracking}"

    def get_trackers_url(self) -> str:
        """Build the target endpoint URL for listing or creating trackers."""
        base_url = (getattr(self.config, "base_url", None) or DEFAULT_KARRIO_BASE_URL).rstrip("/")
        return f"{base_url}/v1/trackers"

    def _build_auth_headers(self) -> Dict[str, str]:
        """Generate HTTP headers including Karrio token authentication when configured."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        api_key = self.resolve_api_key()
        if api_key:
            clean_key = api_key.strip()
            if clean_key.lower().startswith("token ") or clean_key.lower().startswith("bearer "):
                headers["Authorization"] = clean_key
            else:
                headers["Authorization"] = f"Token {clean_key}"
        return headers

    # -----------------------------------------------------------------
    # Ingestion Implementation
    # -----------------------------------------------------------------

    def fetch(
        self,
        carrier_name: Optional[str] = None,
        tracking_number: Optional[str] = None,
        shipment_id: Optional[str] = None,
        org_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch tracking details from Karrio for a specific package consignment.

        Parameters:
            carrier_name: Shipping carrier slug (e.g., 'fedex', 'ups', 'dhl', 'auspost').
            tracking_number: Consignment tracking identifier.
            shipment_id: Optional verified RiskWise shipment identifier for explicit correlation.
            org_id: Optional tenant isolation scope.

        Returns:
            IngestionBatch containing standardized RawEvent items for each tracking milestone.
        """
        if not carrier_name or not carrier_name.strip():
            raise ProviderValidationError(
                "carrier_name parameter is required to track a package via Karrio",
                provider_name=self.provider_name,
            )
        if not tracking_number or not tracking_number.strip():
            raise ProviderValidationError(
                "tracking_number parameter is required to track a package via Karrio",
                provider_name=self.provider_name,
            )

        clean_carrier = carrier_name.strip().lower()
        clean_tracking = tracking_number.strip()

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
        url = self.get_tracker_url(clean_carrier, clean_tracking)
        headers = self._build_auth_headers()

        # 3. HTTP Request with bounded retry policy
        def _send_request() -> httpx.Response:
            try:
                resp = self.client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"Request timeout contacting Karrio tracking service: {str(exc)}",
                    provider_name=self.provider_name,
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderConnectionError(
                    f"Network failure contacting Karrio tracking service: {str(exc)}",
                    provider_name=self.provider_name,
                ) from exc

            if resp.status_code >= 500:
                raise ProviderConnectionError(
                    f"Karrio upstream server error: HTTP {resp.status_code}",
                    provider_name=self.provider_name,
                    status_code=resp.status_code,
                )
            return resp

        response = self._retry_policy.execute(_send_request)

        # 4. HTTP Status Validation
        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(
                f"Karrio authorization rejected with HTTP {response.status_code}. Verify API token.",
                provider_name=self.provider_name,
                status_code=response.status_code,
            )
        if response.status_code == 404:
            raise ProviderResponseError(
                f"Tracker for {clean_carrier} package '{clean_tracking}' was not found (HTTP 404).",
                provider_name=self.provider_name,
                status_code=404,
            )
        if response.status_code == 429:
            retry_after_hdr = response.headers.get("Retry-After")
            retry_after_sec = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
            raise ProviderRateLimitError(
                f"Karrio rate limit exceeded (HTTP 429). Retry-After: {retry_after_sec or 'unspecified'}s",
                provider_name=self.provider_name,
                retry_after_seconds=retry_after_sec,
            )
        if response.status_code != 200:
            raise ProviderResponseError(
                f"Karrio returned unexpected status code: HTTP {response.status_code}",
                provider_name=self.provider_name,
                status_code=response.status_code,
            )

        # 5. JSON Deserialization
        try:
            tracker_data = response.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"Failed to parse Karrio response as valid JSON: {str(exc)}",
                provider_name=self.provider_name,
            ) from exc

        tracker = KarrioTracker.model_validate(tracker_data)

        # 6. Convert Tracker Events into RawEvent models
        now_utc = datetime.now(timezone.utc)
        events: List[RawEvent] = []

        # Extract explicit shipment_id from request or tracker metadata
        resolved_shipment_id = shipment_id or tracker.metadata.get("shipment_id")

        if not tracker.events:
            # Single event representing current overall tracker status
            raw_dict = tracker.model_dump()
            raw_dict["event_index"] = 0
            if resolved_shipment_id:
                raw_dict["shipment_id"] = resolved_shipment_id

            fingerprint = self.compute_fingerprint(raw_dict, org_id=org_id)
            provider_event_id = f"karrio:{clean_carrier}:{clean_tracking}:root:{int(now_utc.timestamp())}"

            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=provider_event_id,
                fingerprint=fingerprint,
                source_timestamp=now_utc,
                ingested_at=now_utc,
                raw_payload=raw_dict,
                metadata={
                    "carrier_name": clean_carrier,
                    "tracking_number": clean_tracking,
                    "status": tracker.status,
                    "delivered": tracker.delivered,
                    "event_type": "TRACKER_SUMMARY",
                },
                org_id=org_id,
                event_type="LOGISTICS_MILESTONE",
            )
            events.append(raw_event)
        else:
            # Multi-event historical progression
            for idx, ev in enumerate(tracker.events):
                raw_dict = ev.model_dump()
                raw_dict["carrier_name"] = tracker.carrier_name
                raw_dict["carrier_id"] = tracker.carrier_id
                raw_dict["tracking_number"] = tracker.tracking_number
                raw_dict["overall_status"] = tracker.status
                raw_dict["estimated_delivery"] = tracker.estimated_delivery
                raw_dict["actual_delivery"] = tracker.actual_delivery
                raw_dict["delivered"] = tracker.delivered
                raw_dict["event_index"] = idx
                if resolved_shipment_id:
                    raw_dict["shipment_id"] = resolved_shipment_id

                # Resolve event timestamp
                event_dt: Optional[datetime] = None
                if ev.timestamp:
                    try:
                        event_dt = TimestampNormalizer.parse_to_utc(ev.timestamp)
                    except Exception:
                        pass

                if event_dt is None and ev.date:
                    date_time_str = f"{ev.date.strip()}T{ev.time.strip()}" if ev.time else ev.date.strip()
                    try:
                        event_dt = TimestampNormalizer.parse_to_utc(date_time_str)
                    except Exception:
                        event_dt = now_utc

                if event_dt is None:
                    event_dt = now_utc

                raw_dict["normalized_event_timestamp"] = event_dt.isoformat()
                fingerprint = self.compute_fingerprint(raw_dict, org_id=org_id)
                provider_event_id = f"karrio:{clean_carrier}:{clean_tracking}:{idx}:{int(event_dt.timestamp())}"

                raw_event = RawEvent(
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    provider_event_id=provider_event_id,
                    fingerprint=fingerprint,
                    source_timestamp=event_dt,
                    ingested_at=now_utc,
                    raw_payload=raw_dict,
                    metadata={
                        "carrier_name": clean_carrier,
                        "tracking_number": clean_tracking,
                        "event_index": idx,
                        "code": ev.code,
                        "status": ev.status or tracker.status,
                    },
                    org_id=org_id,
                    event_type="LOGISTICS_MILESTONE",
                )
                events.append(raw_event)

        logger.info(
            "Successfully fetched %d tracking events for %s package %s from Karrio",
            len(events),
            clean_carrier,
            clean_tracking,
        )
        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            source_metadata={
                "carrier_name": clean_carrier,
                "tracking_number": clean_tracking,
                "status": tracker.status,
                "delivered": tracker.delivered,
                "estimated_delivery": tracker.estimated_delivery,
                "count": len(events),
                "endpoint": url,
            },
            fetched_at=now_utc,
        )

    def fetch_batch(
        self,
        tracking_numbers: Optional[List[str]] = None,
        carrier_name: Optional[str] = None,
        org_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch tracking lists across multiple trackers via GET /v1/trackers."""
        url = self.get_trackers_url()
        headers = self._build_auth_headers()
        params: Dict[str, Any] = {"limit": min(kwargs.get("limit", 100), 500)}
        if carrier_name:
            params["carrier_name"] = carrier_name.strip().lower()
        if tracking_numbers:
            params["tracking_number"] = ",".join(tracking_numbers)

        now_utc = datetime.now(timezone.utc)
        resp = self.client.get(url, headers=headers, params=params)

        if resp.status_code != 200:
            raise ProviderResponseError(
                f"Karrio list trackers failed with HTTP {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )

        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        all_events: List[RawEvent] = []
        for item in results:
            tracker = KarrioTracker.model_validate(item)
            raw_dict = tracker.model_dump()
            fingerprint = self.compute_fingerprint(raw_dict, org_id=org_id)
            p_id = f"karrio:{tracker.carrier_name}:{tracker.tracking_number}:batch:{int(now_utc.timestamp())}"

            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=p_id,
                fingerprint=fingerprint,
                source_timestamp=now_utc,
                ingested_at=now_utc,
                raw_payload=raw_dict,
                metadata={
                    "carrier_name": tracker.carrier_name,
                    "tracking_number": tracker.tracking_number,
                    "status": tracker.status,
                    "delivered": tracker.delivered,
                },
                org_id=org_id,
                event_type="LOGISTICS_MILESTONE",
            )
            all_events.append(raw_event)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=all_events,
            source_metadata={"endpoint": url, "count": len(all_events)},
            fetched_at=now_utc,
        )

    # -----------------------------------------------------------------
    # Diagnostic Health Check
    # -----------------------------------------------------------------

    def health_check(self) -> ProviderHealthResult:
        """Perform diagnostic health check by probing the Karrio trackers endpoint.

        Validates reachability, authorization, and response schema.
        """
        start_time = time.monotonic()
        api_key = self.resolve_api_key()

        auth_mode = getattr(self.config, "auth_mode", AuthMode.NONE)
        if auth_mode == AuthMode.API_KEY_HEADER and not api_key:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                latency_ms=0.0,
                message="Karrio tracking provider unconfigured: missing API key (KARRIO_API_KEY).",
                details={"configured": False, "error_category": "CONFIGURATION"},
            )

        probe_url = f"{self.get_trackers_url()}?limit=1"
        headers = self._build_auth_headers()

        try:
            resp = self.client.get(probe_url, headers=headers, timeout=5.0)
            latency = (time.monotonic() - start_time) * 1000.0

            if resp.status_code == 200:
                try:
                    payload = resp.json()
                    if not isinstance(payload, (dict, list)):
                        raise ValueError("Payload is not a valid JSON structure")
                except Exception:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.UNHEALTHY,
                        latency_ms=round(latency, 2),
                        message="Karrio health probe returned HTTP 200 but body is not valid JSON.",
                        details={"configured": True, "error_category": "RESPONSE"},
                    )

                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.HEALTHY,
                    latency_ms=round(latency, 2),
                    message="Karrio tracking service probe succeeded and JSON verified.",
                    details={"configured": True, "endpoint": probe_url},
                )
            elif resp.status_code in (401, 403):
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"Karrio authorization rejected: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "AUTHENTICATION", "status_code": resp.status_code},
                )
            elif resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message="Karrio rate limit exceeded (HTTP 429).",
                    details={"configured": True, "error_category": "RATE_LIMIT"},
                )
            elif resp.status_code >= 500:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=round(latency, 2),
                    message=f"Karrio upstream error: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "UPSTREAM", "status_code": resp.status_code},
                )
            else:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=round(latency, 2),
                    message=f"Karrio returned unexpected status code: HTTP {resp.status_code}",
                    details={"configured": True, "error_category": "RESPONSE", "status_code": resp.status_code},
                )
        except httpx.TimeoutException as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.DEGRADED,
                latency_ms=round(latency, 2),
                message=f"Karrio probe timeout: {str(exc)}",
                details={"configured": True, "error_category": "TIMEOUT"},
            )
        except Exception as exc:
            latency = (time.monotonic() - start_time) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=round(latency, 2),
                message=f"Karrio probe connection failed: {str(exc)}",
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
        """Create a collision-resistant SHA-256 fingerprint from tracking milestone state.

        Deduplicates identical polling queries while preserving legitimate consecutive updates
        differing in status, milestone code, coordinates, timestamp, or event index.
        """
        carrier = str(payload.get("carrier_name") or "").lower().strip()
        tracking = str(payload.get("tracking_number") or "").strip()
        code = str(payload.get("code") or "").upper().strip()
        status = str(payload.get("status") or payload.get("overall_status") or "").lower().strip()
        date_val = str(payload.get("date") or "")
        time_val = str(payload.get("time") or "")
        ts_val = str(payload.get("timestamp") or payload.get("normalized_event_timestamp") or "")
        event_idx = str(payload.get("event_index") if payload.get("event_index") is not None else "")

        lat = payload.get("latitude")
        lon = payload.get("longitude")
        lat_str = f"{float(lat):.4f}" if lat is not None else "none"
        lon_str = f"{float(lon):.4f}" if lon is not None else "none"
        loc_str = str(payload.get("location") or "").lower().strip()
        desc_str = str(payload.get("description") or "").lower().strip()

        org_prefix = f"org:{org_id}:" if org_id else "global:"
        raw_key = (
            f"{org_prefix}karrio:{carrier}:{tracking}:{code}:{status}:"
            f"{date_val}:{time_val}:{ts_val}:{event_idx}:{lat_str},{lon_str}:{loc_str}:{desc_str}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


# =====================================================================
# Canonical Normalizer: KarrioNormalizer
# =====================================================================

class KarrioNormalizer(BaseEventNormalizer):
    """Production normalizer translating Karrio RawEvent items into CanonicalExternalEvent models.

    Adheres strictly to the canonical model without schema leakage:
    - Maps delivery milestone events to CanonicalEventType.SHIPMENT_STATUS
    - Maps delay events and exceptions to CanonicalEventType.SHIPMENT_DELAY
    - Maps coordinates and validates bounds via CoordinateValidator
    - Maps estimated delivery dates into canonical ETA
    - Preserves carrier name, tracking number, and carrier ID in EntityCorrelation
    - Strictly prevents false correlation to shipment_id unless explicitly provided
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Return True if the raw event was produced by the Karrio provider."""
        return raw_event.provider_name.lower().strip() == "karrio"

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform a Karrio RawEvent into a CanonicalExternalEvent."""
        payload = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        # 1. Timing Resolution
        event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 2. Extract Identifiers
        tracking_number = payload.get("tracking_number")
        carrier_name = payload.get("carrier_name")
        carrier_id = payload.get("carrier_id")
        shipment_id = payload.get("shipment_id")

        custom_ids: Dict[str, str] = {
            "provider": "karrio",
        }
        if tracking_number:
            custom_ids["tracking_number"] = str(tracking_number)
        if carrier_name:
            custom_ids["carrier_name"] = str(carrier_name).lower()
        if carrier_id:
            custom_ids["carrier_id"] = str(carrier_id)

        # 3. Correlation (Strict Isolation: shipment_id is None unless explicitly given)
        correlation = EntityCorrelation(
            shipment_id=str(shipment_id) if shipment_id else None,
            carrier_id=str(carrier_id) if carrier_id else (str(carrier_name) if carrier_name else None),
            custom_identifiers=custom_ids,
        )

        # 4. Status & Severity Mapping
        raw_status = str(payload.get("status") or payload.get("overall_status") or "unknown").lower().strip()
        reason = str(payload.get("reason") or "").lower().strip()
        code = str(payload.get("code") or "").upper().strip()

        canonical_type: CanonicalEventType = CanonicalEventType.SHIPMENT_STATUS
        severity: EventSeverity = EventSeverity.INFO
        status_str: str = raw_status.upper()
        delay_minutes: Optional[float] = None

        if raw_status in ("delivered", "completed"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.INFO
            status_str = "DELIVERED"
        elif raw_status in ("in_transit", "transit", "transferred"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.INFO
            status_str = "IN_TRANSIT"
        elif raw_status in ("out_for_delivery",):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.LOW
            status_str = "OUT_FOR_DELIVERY"
        elif raw_status in ("picked_up", "collected"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.INFO
            status_str = "PICKED_UP"
        elif raw_status in ("ready_for_pickup", "at_location"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.INFO
            status_str = "READY_FOR_PICKUP"
        elif raw_status in ("pending", "created", "label_printed", "label_created"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.INFO
            status_str = "PENDING"
        elif raw_status in ("delivery_delayed", "delayed", "rescheduled"):
            canonical_type = CanonicalEventType.SHIPMENT_DELAY
            severity = EventSeverity.HIGH if "major" in str(payload.get("description") or "").lower() else EventSeverity.MEDIUM
            status_str = "DELAYED"
        elif raw_status in ("delivery_failed", "failed"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.HIGH
            status_str = "DELIVERY_FAILED"
        elif raw_status in ("on_hold", "exception", "customs_hold"):
            canonical_type = CanonicalEventType.SHIPMENT_DELAY
            severity = EventSeverity.HIGH
            status_str = "ON_HOLD"
        elif raw_status in ("cancelled", "canceled"):
            canonical_type = CanonicalEventType.SHIPMENT_STATUS
            severity = EventSeverity.CRITICAL
            status_str = "CANCELLED"
        else:
            canonical_type = CanonicalEventType.CUSTOM
            severity = EventSeverity.INFO
            status_str = raw_status.upper()

        # Check Incident Reason overrides
        if reason in (
            KarrioIncidentReason.CARRIER_DAMAGED_PARCEL.value,
            KarrioIncidentReason.CARRIER_PARCEL_LOST.value,
        ):
            severity = EventSeverity.CRITICAL
            status_str = f"INCIDENT_{reason.upper()}"
        elif reason in (
            KarrioIncidentReason.CARRIER_SORTING_ERROR.value,
            KarrioIncidentReason.CARRIER_ADDRESS_NOT_FOUND.value,
            KarrioIncidentReason.CARRIER_VEHICLE_ISSUE.value,
            KarrioIncidentReason.CUSTOMS_DELAY.value,
            KarrioIncidentReason.CUSTOMS_DOCUMENTATION.value,
            KarrioIncidentReason.WEATHER_DELAY.value,
            KarrioIncidentReason.NATURAL_DISASTER.value,
        ):
            severity = EventSeverity.HIGH
            canonical_type = CanonicalEventType.SHIPMENT_DELAY
            status_str = f"EXCEPTION_{reason.upper()}"
        elif reason in (
            KarrioIncidentReason.CONSIGNEE_REFUSED.value,
            KarrioIncidentReason.CONSIGNEE_BUSINESS_CLOSED.value,
            KarrioIncidentReason.CONSIGNEE_NOT_AVAILABLE.value,
        ):
            severity = EventSeverity.MEDIUM
            status_str = f"EXCEPTION_{reason.upper()}"

        # 5. Location Handling & Coordinate Validation
        location_obj: Optional[EventLocation] = None
        lat = payload.get("latitude")
        lon = payload.get("longitude")
        loc_name = payload.get("location")

        if lat is not None or lon is not None:
            try:
                valid_lat, valid_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=valid_lat,
                    longitude=valid_lon,
                    location_name=str(loc_name) if loc_name else f"Milestone at ({valid_lat:.4f}, {valid_lon:.4f})",
                )
            except Exception as exc:
                validation_errors.append(f"Coordinate validation failure: {str(exc)}")
                location_obj = None
        elif loc_name:
            location_obj = EventLocation(
                location_name=str(loc_name),
            )

        # 6. Estimated Delivery Date (ETA)
        eta_dt: Optional[datetime] = None
        est_delivery = payload.get("estimated_delivery")
        if est_delivery:
            try:
                eta_dt = TimestampNormalizer.parse_to_utc(est_delivery)
            except Exception as exc:
                validation_errors.append(f"ETA normalization failure: {str(exc)}")

        # Delay computation if baseline scheduled ETA is given
        scheduled_eta = payload.get("scheduled_eta")
        if eta_dt and scheduled_eta:
            try:
                sched_dt = TimestampNormalizer.parse_to_utc(scheduled_eta)
                diff_sec = (eta_dt - sched_dt).total_seconds()
                if diff_sec > 0:
                    delay_minutes = round(diff_sec / 60.0, 1)
            except Exception:
                pass

        if delay_minutes is None and payload.get("delay_minutes") is not None:
            try:
                delay_minutes = float(payload["delay_minutes"])
            except Exception:
                pass

        # 7. Quality Assessment
        quality = EventQuality.PARTIAL if validation_errors else EventQuality.VALID

        normalized_attrs = dict(payload)
        normalized_attrs["mode"] = "PARCEL"
        normalized_attrs["carrier_name"] = carrier_name
        normalized_attrs["tracking_number"] = tracking_number

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
            eta=eta_dt,
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
# Webhook Boundary Receiver: KarrioWebhookReceiver
# =====================================================================

class KarrioWebhookReceiver(WebhookReceiver):
    """Production webhook receiver boundary validating and processing Karrio push notifications."""

    def verify_signature(
        self,
        payload_bytes: bytes,
        signature: str,
        secret: str,
    ) -> bool:
        """Verify Karrio webhook payload authenticity using HMAC-SHA256 signature or shared secret.

        Parameters:
            payload_bytes: Raw request body bytes.
            signature: Signature string from 'X-Karrio-Signature' or secret token header.
            secret: Webhook shared secret configured for the tenant.

        Returns:
            True if signature matches; False otherwise.
        """
        if not signature or not secret:
            return False

        clean_sig = signature.strip()
        clean_secret = secret.strip()

        # Direct token match support
        if hmac.compare_digest(clean_sig, clean_secret):
            return True

        # HMAC-SHA256 signature verification
        expected_sig = hmac.new(
            clean_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(clean_sig, expected_sig)

    def parse_payload(
        self,
        raw_body: bytes,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        """Parse raw webhook JSON bytes into a tracking event dictionary.

        Raises:
            ProviderValidationError: If JSON is malformed or missing expected tracker data.
        """
        try:
            data = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ProviderValidationError(
                f"Failed to decode Karrio webhook JSON payload: {str(exc)}",
                provider_name="karrio",
            ) from exc

        if not isinstance(data, dict):
            raise ProviderValidationError(
                "Karrio webhook payload must be a JSON object",
                provider_name="karrio",
            )

        # Handle Karrio webhook wrapper: {"event": "tracker_updated", "data": {...}}
        if "data" in data and isinstance(data["data"], dict):
            tracker_data = dict(data["data"])
            tracker_data["webhook_event"] = data.get("event")
            return tracker_data

        return data


# =====================================================================
# Scheduler Helper
# =====================================================================

def create_karrio_polling_job(
    job_id: str,
    carrier_name: str,
    tracking_number: str,
    cron_or_interval: str = "interval:15",
    shipment_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    enabled: bool = True,
) -> ScheduledIngestionJob:
    """Create a standardized ScheduledIngestionJob descriptor for periodic Karrio package tracking."""
    return ScheduledIngestionJob(
        job_id=job_id,
        provider_name="karrio",
        cron_or_interval=cron_or_interval,
        enabled=enabled,
        parameters={
            "carrier_name": carrier_name.strip().lower(),
            "tracking_number": tracking_number.strip(),
            "shipment_id": shipment_id,
        },
        organization_id=organization_id,
    )
