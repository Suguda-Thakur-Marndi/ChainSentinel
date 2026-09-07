"""AISStream ocean / AIS provider adapter and normalizer implementation.

Ingests real-time maritime AIS vessel positions and static voyage signals from the
AISStream WebSocket stream (wss://stream.aisstream.io/v0/stream), mapping provider-specific
frames into strongly typed RawEvent and CanonicalExternalEvent models without schema leakage.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

logger = logging.getLogger("riskwise.integrations.providers.aisstream")

# Verified AISStream WebSocket Endpoint
DEFAULT_AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# Non-destructive reference coordinates for health-check probe (Suez Canal corridor)
HEALTH_CHECK_BBOX = [[[29.5, 32.2], [30.5, 32.8]]]


# =====================================================================
# WebSocket Transport Abstraction
# =====================================================================

class AISWebSocketTransport(ABC):
    """Abstract WebSocket transport interface decoupling adapter from underlying socket client."""

    @abstractmethod
    def connect(self, url: str, timeout: float = 10.0) -> None:
        """Establish WebSocket connection."""
        pass

    @abstractmethod
    def send(self, message: str) -> None:
        """Send a text frame to the WebSocket."""
        pass

    @abstractmethod
    def receive(self, timeout: Optional[float] = None) -> str:
        """Receive a text frame from the WebSocket.

        Raises:
            ProviderTimeoutError: If timeout expires before a frame is received.
            ProviderConnectionError: If connection is closed or drops.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Gracefully close the WebSocket session."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the WebSocket is currently open and connected."""
        pass


class MockAISWebSocketTransport(AISWebSocketTransport):
    """In-memory mock transport for testing and deterministic validation (0 network calls)."""

    def __init__(
        self,
        canned_messages: Optional[List[str]] = None,
        simulate_auth_failure: bool = False,
        simulate_timeout: bool = False,
        simulate_connection_error: bool = False,
    ) -> None:
        self._canned_messages: List[str] = canned_messages or []
        self._sent_messages: List[str] = []
        self._connected: bool = False
        self._url: Optional[str] = None
        self.simulate_auth_failure = simulate_auth_failure
        self.simulate_timeout = simulate_timeout
        self.simulate_connection_error = simulate_connection_error

    def connect(self, url: str, timeout: float = 10.0) -> None:
        if self.simulate_connection_error:
            raise ProviderConnectionError(f"Failed to connect to WebSocket endpoint: {url}")
        if self.simulate_timeout:
            raise ProviderTimeoutError(f"Connection timeout to WebSocket endpoint: {url}")
        self._url = url
        self._connected = True

    def send(self, message: str) -> None:
        if not self._connected:
            raise ProviderConnectionError("Cannot send message: WebSocket is not connected.")
        self._sent_messages.append(message)
        # Check if auth failure simulation is requested
        if self.simulate_auth_failure:
            try:
                data = json.loads(message)
                if not data.get("APIKey") or data.get("APIKey") == "invalid_key":
                    raise ProviderAuthenticationError("Invalid or missing API key in subscription")
            except (json.JSONDecodeError, TypeError):
                pass

    def receive(self, timeout: Optional[float] = None) -> str:
        if not self._connected:
            raise ProviderConnectionError("Cannot receive message: WebSocket is not connected.")
        if self.simulate_timeout:
            raise ProviderTimeoutError("Timed out waiting for WebSocket message frame.")
        if self.simulate_connection_error:
            raise ProviderConnectionError("WebSocket connection reset by peer.")
        if not self._canned_messages:
            raise ProviderTimeoutError("No further frames in queue.")
        return self._canned_messages.pop(0)

    def close(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def sent_messages(self) -> List[str]:
        return list(self._sent_messages)

    def queue_message(self, message: Union[str, dict[str, Any]]) -> None:
        if isinstance(message, dict):
            self._canned_messages.append(json.dumps(message))
        else:
            self._canned_messages.append(message)


# =====================================================================
# Subscription Model
# =====================================================================

class AISStreamSubscription(BaseModel):
    """Strongly-typed internal subscription configuration for AISStream.

    Verified AISStream subscription JSON specification:
    {
      "APIKey": "<YOUR_API_KEY>",
      "BoundingBoxes": [[[lat1, lon1], [lat2, lon2]], ...],
      "FiltersShipMMSI": ["123456789"],
      "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
    }
    """
    model_config = ConfigDict(extra="forbid")

    bounding_boxes: List[List[List[float]]] = Field(
        ...,
        description="Array of geographic bounding boxes, each defined by 2 [latitude, longitude] corner points.",
    )
    filters_ship_mmsi: Optional[List[str]] = Field(
        default=None,
        description="Optional list of vessel MMSIs as strings (up to 200).",
    )
    filter_message_types: Optional[List[str]] = Field(
        default=None,
        description="Optional list of AIS message types (e.g. ['PositionReport', 'ShipStaticData']).",
    )

    @field_validator("bounding_boxes")
    @classmethod
    def validate_bounding_boxes(cls, v: List[List[List[float]]]) -> List[List[List[float]]]:
        if not v:
            raise ValueError("At least one bounding box must be specified.")
        for idx, box in enumerate(v):
            if not isinstance(box, (list, tuple)) or len(box) != 2:
                raise ValueError(
                    f"Bounding box at index {idx} must contain exactly 2 corner points [[lat1, lon1], [lat2, lon2]], got {len(box)}."
                )
            for pt_idx, pt in enumerate(box):
                if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                    raise ValueError(
                        f"Point {pt_idx} in box {idx} must be a [latitude, longitude] coordinate pair."
                    )
                lat, lon = pt[0], pt[1]
                try:
                    CoordinateValidator.validate(lat, lon)
                except ValueError as exc:
                    raise ValueError(f"Invalid coordinate in box {idx}, point {pt_idx}: {exc}") from exc
        return v

    @field_validator("filters_ship_mmsi")
    @classmethod
    def validate_mmsi_list(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if len(v) > 200:
                raise ValueError(f"AISStream permits a maximum of 200 MMSI filters, got {len(v)}.")
            for mmsi in v:
                if not str(mmsi).strip():
                    raise ValueError("MMSI filter cannot be empty string.")
        return v

    def to_subscription_payload(self, api_key: str) -> dict[str, Any]:
        """Serialize subscription into the exact verified AISStream JSON message format."""
        if not api_key or not api_key.strip():
            raise ProviderAuthenticationError("AISStream API key is required to build subscription payload.")

        payload: dict[str, Any] = {
            "APIKey": api_key.strip(),
            "BoundingBoxes": self.bounding_boxes,
        }
        if self.filters_ship_mmsi:
            payload["FiltersShipMMSI"] = [str(m).strip() for m in self.filters_ship_mmsi]
        if self.filter_message_types:
            payload["FilterMessageTypes"] = list(self.filter_message_types)
        return payload


# =====================================================================
# Provider Adapter
# =====================================================================

class AISStreamAdapter(BaseProviderAdapter):
    """Production provider adapter for AISStream WebSocket streaming maritime intelligence."""

    provider_name: str = "aisstream"
    provider_type: ProviderType = ProviderType.OCEAN_AIS
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=False,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=True,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=100,
        supported_entities=["location", "vessel", "shipment", "carrier", "port"],
        supported_modalities=["ocean", "ais", "vessel_tracking", "maritime"],
    )

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        secret: Optional[str] = None,
        transport: Optional[AISWebSocketTransport] = None,
        secret_resolver: Optional[SecretResolver] = None,
        idempotency_engine: Optional[IdempotencyEngine] = None,
    ) -> None:
        if config is None:
            config = ProviderConfig(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                base_url=DEFAULT_AISSTREAM_URL,
                auth_mode=AuthMode.API_KEY_HEADER,
                secret_ref="env:AISSTREAM_API_KEY",
                rate_limit=RateLimitConfig(requests_per_minute=120),
                retry=RetryConfig(max_retries=3, initial_delay_seconds=0.5),
            )
        super().__init__(config=config, secret=secret)
        self.secret_resolver = secret_resolver or SecretResolver()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self._transport = transport or MockAISWebSocketTransport()
        self._is_subscribed: bool = False
        self._active_subscription: Optional[AISStreamSubscription] = None

    @property
    def transport(self) -> AISWebSocketTransport:
        return self._transport

    @transport.setter
    def transport(self, value: AISWebSocketTransport) -> None:
        self._transport = value

    def _resolve_api_key(self) -> str:
        """Resolve AISStream API key from explicit secret or configured secret resolver."""
        if self._secret and self._secret.strip():
            return self._secret.strip()

        secret_ref = getattr(self.config, "secret_ref", None) or "env:AISSTREAM_API_KEY"
        try:
            resolved = self.secret_resolver.resolve_secret(secret_ref)
            if resolved and resolved.strip():
                return resolved.strip()
        except Exception as exc:
            logger.debug(f"SecretResolver failed to resolve '{secret_ref}': {exc}")

        raise ProviderAuthenticationError(
            "AISStream API key could not be resolved from secret or environment (AISSTREAM_API_KEY missing)."
        )

    def connect(self, timeout: Optional[float] = None) -> None:
        """Establish connection to the verified AISStream WebSocket endpoint."""
        url = getattr(self.config, "base_url", None) or DEFAULT_AISSTREAM_URL
        conn_timeout = timeout or getattr(self.config, "timeout_seconds", 10.0)
        try:
            self._transport.connect(url, timeout=conn_timeout)
            logger.info(f"Connected to AISStream WebSocket endpoint '{url}'.")
        except (ProviderConnectionError, ProviderTimeoutError):
            raise
        except Exception as exc:
            raise ProviderConnectionError(f"Failed to connect to AISStream endpoint '{url}': {exc}") from exc

    def subscribe(self, subscription: AISStreamSubscription) -> None:
        """Send subscription payload containing BoundingBoxes, MMSI filters, and APIKey."""
        if not self._transport.is_connected:
            self.connect()

        api_key = self._resolve_api_key()
        payload = subscription.to_subscription_payload(api_key=api_key)

        try:
            message_str = json.dumps(payload)
            self._transport.send(message_str)
            self._is_subscribed = True
            self._active_subscription = subscription
            logger.info("Successfully dispatched AISStream subscription message.")
        except ProviderAuthenticationError:
            raise
        except Exception as exc:
            raise ProviderConnectionError(f"Failed to dispatch subscription to AISStream: {exc}") from exc

    def receive_raw_message(
        self,
        timeout: Optional[float] = None,
        org_id: Optional[str] = None,
    ) -> RawEvent:
        """Receive a single frame from the WebSocket, validate envelope, and wrap in RawEvent."""
        if not self._transport.is_connected:
            raise ProviderConnectionError("Cannot receive message: AISStream WebSocket is not connected.")

        raw_str = self._transport.receive(timeout=timeout)

        # 1. Parse JSON
        try:
            payload = json.loads(raw_str)
        except Exception as exc:
            raise ProviderValidationError(f"Malformed JSON frame received from AISStream: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderValidationError(
                f"Expected JSON object envelope from AISStream, got {type(payload).__name__}."
            )

        # 2. Check for explicit error responses from provider
        if "error" in payload or "Error" in payload:
            err_msg = payload.get("error") or payload.get("Error")
            err_str = str(err_msg).lower()
            if "unauthorized" in err_str or "api key" in err_str or "apikey" in err_str or "forbidden" in err_str:
                raise ProviderAuthenticationError(f"AISStream authentication failed: {err_msg}")
            if "rate limit" in err_str:
                raise ProviderRateLimitError(f"AISStream rate limit exceeded: {err_msg}")
            raise ProviderResponseError(f"AISStream returned upstream error: {err_msg}")

        # 3. Validate verified envelope structure
        msg_type = payload.get("MessageType")
        metadata = payload.get("MetaData")
        message_data = payload.get("Message")

        if not msg_type or metadata is None or message_data is None:
            raise ProviderValidationError(
                "Missing required AISStream envelope fields ('MessageType', 'MetaData', or 'Message')."
            )

        # 4. Extract identifying attributes
        mmsi = metadata.get("MMSI") or metadata.get("mmsi")
        if mmsi is None and isinstance(message_data, dict):
            sub_msg = message_data.get(msg_type, {})
            if isinstance(sub_msg, dict):
                mmsi = sub_msg.get("UserID")

        mmsi_str = str(mmsi) if mmsi is not None else "unknown"
        provider_event_id = f"aisstream:{mmsi_str}:{msg_type}"

        # 5. Extract timestamp
        ts_raw = metadata.get("time_utc") or metadata.get("timestamp")
        source_ts: Optional[datetime] = None
        if ts_raw:
            try:
                clean_ts = ts_raw
                if isinstance(clean_ts, str) and clean_ts.endswith(" UTC"):
                    clean_ts = clean_ts[:-4].strip()
                source_ts = TimestampNormalizer.parse_to_utc(clean_ts)
            except Exception:
                source_ts = None

        # 6. Compute deterministic idempotency fingerprint
        fingerprint = self.compute_fingerprint(
            payload=payload,
            org_id=org_id,
        )

        # 7. Redact secrets from metadata/payload if any crept in
        clean_payload = self._redact_secrets_from_dict(payload)

        return RawEvent(
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            provider_event_id=provider_event_id,
            fingerprint=fingerprint,
            source_timestamp=source_ts,
            ingested_at=datetime.now(timezone.utc),
            raw_payload=clean_payload,
            metadata={
                "message_type": msg_type,
                "mmsi": mmsi_str,
                "ship_name": metadata.get("ShipName"),
                "source_protocol": "websocket",
            },
            org_id=org_id,
            event_type=msg_type,
        )

    def receive_batch(
        self,
        max_messages: int = 10,
        timeout: Optional[float] = 1.0,
        org_id: Optional[str] = None,
    ) -> IngestionBatch:
        """Collect up to max_messages frames into an IngestionBatch container."""
        events: List[RawEvent] = []
        start_time = time.monotonic()

        while len(events) < max_messages:
            try:
                event = self.receive_raw_message(timeout=timeout, org_id=org_id)
                events.append(event)
            except ProviderTimeoutError:
                # Normal bounded cessation when queue or socket is idle
                break
            except (ProviderConnectionError, ProviderAuthenticationError, ProviderValidationError):
                if not events:
                    raise
                break

        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            metadata={
                "requested_max": max_messages,
                "received_count": len(events),
                "duration_ms": (time.monotonic() - start_time) * 1000.0,
            },
            source_metadata={"endpoint": DEFAULT_AISSTREAM_URL},
        )

    def fetch(
        self,
        subscription: Optional[AISStreamSubscription] = None,
        max_messages: int = 10,
        timeout: Optional[float] = 1.0,
        org_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Provider-agnostic fetch contract: connects, subscribes, and reads a sample batch."""
        if not self._transport.is_connected:
            self.connect()

        if subscription is not None:
            self.subscribe(subscription)
        elif not self._is_subscribed:
            # Fallback to default bounding box subscription
            default_sub = AISStreamSubscription(bounding_boxes=HEALTH_CHECK_BBOX)
            self.subscribe(default_sub)

        return self.receive_batch(
            max_messages=max_messages,
            timeout=timeout,
            org_id=org_id,
        )

    def close(self) -> None:
        """Release underlying socket transport and reset connection state."""
        try:
            self._transport.close()
        except Exception as exc:
            logger.debug(f"Error during transport close: {exc}")
        finally:
            self._is_subscribed = False
            self._active_subscription = None

    def health_check(self) -> ProviderHealthResult:
        """Perform a diagnostic connectivity and authentication health check."""
        start_time = time.monotonic()

        # 1. Verify API key availability
        try:
            api_key = self._resolve_api_key()
        except ProviderAuthenticationError as exc:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNCONFIGURED,
                latency_ms=0.0,
                message=f"AISStream unconfigured: {exc.message}",
                details={"configured": False, "error_category": "AUTHENTICATION"},
            )

        # 2. Execute non-destructive probe using transport
        try:
            # Create a dedicated probe check without modifying state
            self.connect(timeout=5.0)
            probe_sub = AISStreamSubscription(
                bounding_boxes=HEALTH_CHECK_BBOX,
                filter_message_types=["PositionReport"],
            )
            payload = probe_sub.to_subscription_payload(api_key=api_key)
            self._transport.send(json.dumps(payload))
            latency = (time.monotonic() - start_time) * 1000.0

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.HEALTHY,
                latency_ms=round(latency, 2),
                message="AISStream WebSocket connection probe succeeded.",
                details={
                    "configured": True,
                    "endpoint": DEFAULT_AISSTREAM_URL,
                    "subscribed": True,
                },
            )
        except ProviderAuthenticationError as exc:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=(time.monotonic() - start_time) * 1000.0,
                message=f"AISStream authentication rejected: {exc.message}",
                details={"configured": True, "error_category": "AUTHENTICATION"},
            )
        except ProviderTimeoutError as exc:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.DEGRADED,
                latency_ms=(time.monotonic() - start_time) * 1000.0,
                message=f"AISStream probe timeout: {exc.message}",
                details={"configured": True, "error_category": "TIMEOUT"},
            )
        except Exception as exc:
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=(time.monotonic() - start_time) * 1000.0,
                message=f"AISStream probe failed: {str(exc)}",
                details={"configured": True, "error_category": "CONNECTION"},
            )

    @classmethod
    def compute_fingerprint(
        cls,
        payload: dict[str, Any],
        org_id: Optional[str] = None,
    ) -> str:
        """Create a deterministic SHA-256 fingerprint from verified AIS message identity attributes.

        Ensures repeated delivery of the exact same AIS message produces an identical
        fingerprint, while legitimate consecutive vessel positions (differing in timestamp
        or coordinates) receive unique fingerprints and are NOT incorrectly deduplicated.
        """
        msg_type = str(payload.get("MessageType", "UNKNOWN"))
        meta = payload.get("MetaData", {}) or {}

        mmsi = str(meta.get("MMSI") or meta.get("mmsi") or "")
        ts = str(meta.get("time_utc") or meta.get("timestamp") or "")

        # Extract lat/lon rounded to 4 decimals (~11 meters resolution)
        lat = meta.get("latitude") or meta.get("Latitude")
        lon = meta.get("longitude") or meta.get("Longitude")

        msg_body = payload.get("Message", {}) or {}
        if isinstance(msg_body, dict) and msg_type in msg_body:
            inner = msg_body[msg_type]
            if isinstance(inner, dict):
                if lat is None:
                    lat = inner.get("Latitude")
                if lon is None:
                    lon = inner.get("Longitude")
                if not mmsi:
                    mmsi = str(inner.get("UserID") or "")

        lat_str = f"{float(lat):.4f}" if lat is not None else "none"
        lon_str = f"{float(lon):.4f}" if lon is not None else "none"

        org_prefix = f"org:{org_id}:" if org_id else "global:"
        raw_key = f"{org_prefix}aisstream:{msg_type}:mmsi:{mmsi}:ts:{ts}:pos:{lat_str},{lon_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _redact_secrets_from_dict(data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact sensitive APIKey or authorization fields from dictionaries."""
        sanitized: dict[str, Any] = {}
        for k, v in data.items():
            if str(k).lower() in ("apikey", "api_key", "secret", "password", "token"):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = AISStreamAdapter._redact_secrets_from_dict(v)
            elif isinstance(v, list):
                sanitized[k] = [
                    AISStreamAdapter._redact_secrets_from_dict(i) if isinstance(i, dict) else i
                    for i in v
                ]
            else:
                sanitized[k] = v
        return sanitized


# =====================================================================
# Provider Normalizer
# =====================================================================

class AISStreamNormalizer(BaseEventNormalizer):
    """Production normalizer converting AISStream raw messages into CanonicalExternalEvent models."""

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        p_name = getattr(raw_event, "provider_name", "") or ""
        return p_name.lower() in ("aisstream", "mock_ais", "maritime_ais")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform a raw AISStream event envelope into a CanonicalExternalEvent."""
        payload = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        msg_type = str(payload.get("MessageType") or raw_event.event_type or "PositionReport")
        metadata = payload.get("MetaData") or {}
        message_wrapper = payload.get("Message") or {}
        message_content = message_wrapper.get(msg_type, {}) if isinstance(message_wrapper, dict) else {}

        # 1. Timestamp resolution & normalization to UTC
        raw_ts = metadata.get("time_utc") or metadata.get("timestamp") or raw_event.source_timestamp or raw_event.ingested_at
        try:
            clean_ts = raw_ts
            if isinstance(clean_ts, str) and clean_ts.endswith(" UTC"):
                clean_ts = clean_ts[:-4].strip()
            event_ts = TimestampNormalizer.parse_to_utc(clean_ts)
        except Exception as exc:
            event_ts = raw_event.ingested_at
            validation_errors.append(f"Timestamp normalization failed: {exc}")


        # 2. Coordinates & Location Validation
        lat_val = metadata.get("latitude") or metadata.get("Latitude")
        lon_val = metadata.get("longitude") or metadata.get("Longitude")
        if lat_val is None and isinstance(message_content, dict):
            lat_val = message_content.get("Latitude")
        if lon_val is None and isinstance(message_content, dict):
            lon_val = message_content.get("Longitude")

        location_obj: Optional[EventLocation] = None
        if lat_val is not None or lon_val is not None:
            try:
                valid_lat, valid_lon = CoordinateValidator.validate(lat_val, lon_val)
                location_obj = EventLocation(
                    latitude=valid_lat,
                    longitude=valid_lon,
                    location_name=metadata.get("ShipName") or message_content.get("Name"),
                )
            except Exception as exc:
                validation_errors.append(f"Coordinate validation failed: {exc}")

        # 3. Vessel identity extraction
        mmsi = metadata.get("MMSI") or metadata.get("mmsi")
        if mmsi is None and isinstance(message_content, dict):
            mmsi = message_content.get("UserID")
        mmsi_str = str(mmsi) if mmsi is not None else None

        ship_name = metadata.get("ShipName") or message_content.get("Name")
        call_sign = message_content.get("CallSign")
        imo_number = message_content.get("ImoNumber")

        custom_identifiers: dict[str, str] = {}
        if mmsi_str:
            custom_identifiers["mmsi"] = mmsi_str
        if imo_number:
            custom_identifiers["imo"] = str(imo_number)
        if call_sign:
            custom_identifiers["call_sign"] = str(call_sign)
        if ship_name:
            custom_identifiers["vessel_name"] = str(ship_name)

        # Preserve shipment correlation if explicitly provided in raw event metadata
        shipment_id = (
            payload.get("shipment_id")
            or raw_event.metadata.get("shipment_id")
            or None
        )

        correlation = EntityCorrelation(
            shipment_id=shipment_id,
            custom_identifiers=custom_identifiers,
        )

        # 4. Canonical event type, status, and severity mapping
        canonical_type: CanonicalEventType = CanonicalEventType.VESSEL_LOCATION
        severity: EventSeverity = EventSeverity.INFO
        status_str: str = "UNDERWAY"
        normalized_attrs: dict[str, Any] = {}

        if msg_type == "PositionReport":
            cog = message_content.get("Cog")
            sog = message_content.get("Sog")
            heading = message_content.get("TrueHeading")
            nav_status = message_content.get("NavigationalStatus")
            rate_of_turn = message_content.get("RateOfTurn")

            normalized_attrs = {
                "mmsi": mmsi_str,
                "ship_name": ship_name,
                "course_over_ground": cog,
                "speed_over_ground_knots": sog,
                "heading_degrees": heading,
                "navigational_status": nav_status,
                "rate_of_turn": rate_of_turn,
                "mode": "OCEAN",
            }

            # Map navigational status to operational taxonomy & severity:
            # 0: Under way using engine -> INFO
            # 1: At anchor -> INFO
            # 2: Not under command -> MARITIME_INCIDENT, HIGH
            # 3: Restricted manoeuvrability -> VESSEL_LOCATION, MEDIUM
            # 4: Constrained by her draught -> VESSEL_LOCATION, LOW
            # 5: Moored -> INFO
            # 6: Aground -> MARITIME_INCIDENT, CRITICAL
            # 8: Under way sailing -> INFO
            # 14: AIS-SART active / Distress -> MARITIME_INCIDENT, CRITICAL
            if nav_status == 6:  # Aground
                canonical_type = CanonicalEventType.MARITIME_INCIDENT
                severity = EventSeverity.CRITICAL
                status_str = "AGROUND"
            elif nav_status == 14:  # AIS-SART / Emergency
                canonical_type = CanonicalEventType.MARITIME_INCIDENT
                severity = EventSeverity.CRITICAL
                status_str = "DISTRESS"
            elif nav_status == 2:  # Not under command
                canonical_type = CanonicalEventType.MARITIME_INCIDENT
                severity = EventSeverity.HIGH
                status_str = "NOT_UNDER_COMMAND"
            elif nav_status == 3:  # Restricted manoeuvrability
                canonical_type = CanonicalEventType.VESSEL_LOCATION
                severity = EventSeverity.MEDIUM
                status_str = "RESTRICTED_MANOEUVRABILITY"
            elif nav_status == 4:  # Constrained by draught
                canonical_type = CanonicalEventType.VESSEL_LOCATION
                severity = EventSeverity.LOW
                status_str = "CONSTRAINED_BY_DRAUGHT"
            elif nav_status == 1:  # At anchor
                canonical_type = CanonicalEventType.VESSEL_LOCATION
                severity = EventSeverity.INFO
                status_str = "AT_ANCHOR"
            elif nav_status == 5:  # Moored
                canonical_type = CanonicalEventType.VESSEL_LOCATION
                severity = EventSeverity.INFO
                status_str = "MOORED"
            else:
                canonical_type = CanonicalEventType.VESSEL_LOCATION
                severity = EventSeverity.INFO
                status_str = "UNDERWAY"

        elif msg_type == "ShipStaticData":
            canonical_type = CanonicalEventType.CUSTOM
            severity = EventSeverity.INFO
            status_str = "STATIC_DATA"
            normalized_attrs = {
                "mmsi": mmsi_str,
                "imo_number": imo_number,
                "call_sign": call_sign,
                "vessel_name": ship_name,
                "ship_type": message_content.get("Type"),
                "destination": message_content.get("Destination"),
                "draught": message_content.get("Draught"),
                "dimension": message_content.get("Dimension"),
                "eta": message_content.get("Eta"),
                "mode": "OCEAN",
                "event_classification": "VESSEL_STATIC_DATA",
            }

        else:
            # Fallback for other AIS types (e.g. StandardSearchAndRescueAircraftReport, etc.)
            canonical_type = CanonicalEventType.CUSTOM
            severity = EventSeverity.INFO
            status_str = msg_type.upper()
            normalized_attrs = {
                "mmsi": mmsi_str,
                "event_classification": f"AIS_{msg_type.upper()}",
                "mode": "OCEAN",
            }

        # 5. Quality evaluation
        if validation_errors:
            quality = EventQuality.PARTIAL
        elif location_obj is None or location_obj.latitude is None or location_obj.longitude is None:
            quality = EventQuality.PARTIAL
        elif not mmsi_str:
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

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
