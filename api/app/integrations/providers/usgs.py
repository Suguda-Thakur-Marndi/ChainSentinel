"""USGS Earthquake Hazards Program provider adapter and normalizer.

Ingests real-time and historical global seismic telemetry from the United States
Geological Survey (USGS) Earthquake Hazards Program GeoJSON feeds and FDSN Event Web Service.
Maps seismic events, magnitude, epicenter depth, and tsunami warnings into strongly typed
RawEvent and CanonicalExternalEvent models.
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

logger = logging.getLogger("riskwise.integrations.providers.usgs")

# Default USGS Endpoints
DEFAULT_USGS_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
DEFAULT_USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
DEFAULT_USER_AGENT = "ChainSentinel/2.0 (SupplyChainRiskDefense; +https://github.com/chainsentinel)"

# Magnitude thresholds for operational supply-chain severity
MAG_CRITICAL_THRESHOLD = 7.0
MAG_HIGH_THRESHOLD = 6.0
MAG_MEDIUM_THRESHOLD = 5.0
MAG_LOW_THRESHOLD = 4.0


class USGSEarthquakeAdapter(BaseProviderAdapter):
    """Production provider adapter for USGS Earthquake Hazards Program."""

    provider_name: str = "usgs_earthquake"
    provider_type: ProviderType = ProviderType.SEISMIC
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=True,
        max_batch_size=500,
        supported_entities=["facility", "port", "route", "supplier_site", "warehouse", "factory"],
        supported_modalities=["seismic", "earthquake", "tsunami", "hazard"],
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
                base_url=DEFAULT_USGS_FEED_URL,
                auth_mode=AuthMode.NONE,
                secret_ref=None,
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
            headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json, application/geo+json"}
            self._internal_client = httpx.Client(timeout=timeout, headers=headers)
        return self._internal_client

    def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    @classmethod
    def compute_earthquake_fingerprint(
        cls,
        event_id: str,
        updated_timestamp: Union[int, float, datetime, str],
        magnitude: Optional[float] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute deterministic, collision-resistant SHA-256 fingerprint for a seismic event."""
        if isinstance(updated_timestamp, (int, float)):
            ts_str = str(int(updated_timestamp))
        elif isinstance(updated_timestamp, datetime):
            ts_str = str(int(updated_timestamp.timestamp()))
        else:
            ts_str = str(updated_timestamp)

        payload = {
            "usgs_id": str(event_id),
            "updated": ts_str,
            "mag": round(float(magnitude), 2) if magnitude is not None else None,
        }
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="usgs_earthquake",
            payload=payload,
            organization_id=org_id,
        )

    def fetch(
        self,
        min_magnitude: Optional[float] = None,
        feed_url: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        max_radius_km: Optional[float] = None,
        start_time: Optional[Union[datetime, str]] = None,
        end_time: Optional[Union[datetime, str]] = None,
        limit: int = 100,
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        org_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        port_id: Optional[str] = None,
        route_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
    ) -> IngestionBatch:
        """Fetch real-time or filtered seismic events from USGS.

        Supports two query modes:
        1. Pre-generated GeoJSON feed (default: 4.5+ magnitude past day, or custom feed URL).
        2. FDSN Event Web Service query (when spatial/temporal filters are provided).
        """
        effective_org_id = organization_id or org_id
        is_query_mode = any([
            latitude is not None and longitude is not None,
            start_time is not None,
            end_time is not None,
            min_magnitude is not None and feed_url is None,
        ])

        if is_query_mode:
            target_url = getattr(self.config, "base_url", None) or DEFAULT_USGS_QUERY_URL
            if "query" not in target_url:
                target_url = DEFAULT_USGS_QUERY_URL

            params: Dict[str, Any] = {
                "format": "geojson",
                "limit": min(limit, 500),
            }
            if min_magnitude is not None:
                params["minmagnitude"] = min_magnitude
            if latitude is not None and longitude is not None:
                CoordinateValidator.validate(latitude, longitude)
                params["latitude"] = latitude
                params["longitude"] = longitude
                if max_radius_km is not None:
                    params["maxradiuskm"] = max(1.0, float(max_radius_km))
            if start_time is not None:
                st = TimestampNormalizer.parse_to_utc(start_time)
                params["starttime"] = st.isoformat()
            if end_time is not None:
                et = TimestampNormalizer.parse_to_utc(end_time)
                params["endtime"] = et.isoformat()
        else:
            target_url = feed_url or getattr(self.config, "base_url", None) or DEFAULT_USGS_FEED_URL
            params = {}

        try:
            resp = self.client.get(target_url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"USGS Earthquake request timed out: {exc}",
                provider_name=self.provider_name,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                f"USGS Earthquake network connection failed: {exc}",
                provider_name=self.provider_name,
            ) from exc
        except Exception as exc:
            raise ProviderConnectionError(
                f"USGS Earthquake request error: {exc}",
                provider_name=self.provider_name,
            ) from exc

        if resp.status_code == 400:
            raise ProviderValidationError(
                f"USGS Earthquake returned HTTP 400 Bad Request: {resp.text[:200]}",
                provider_name=self.provider_name,
                status_code=400,
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
            raise ProviderRateLimitError(
                "USGS Earthquake rate limit reached (HTTP 429)",
                provider_name=self.provider_name,
                retry_after_seconds=retry_seconds,
            )
        if resp.status_code >= 500:
            raise ProviderResponseError(
                f"USGS Earthquake service error HTTP {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise ProviderResponseError(
                f"USGS Earthquake returned unexpected status HTTP {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"USGS Earthquake response is not valid JSON: {exc}",
                provider_name=self.provider_name,
            ) from exc

        features = data.get("features", [])
        events: List[RawEvent] = []
        fetched_at = datetime.now(timezone.utc)

        for feature in features:
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            coords = geom.get("coordinates") or []
            feature_id = feature.get("id") or props.get("code") or "unknown"

            # Parse event epoch milliseconds
            time_ms = props.get("time")
            source_ts = (
                datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc)
                if time_ms
                else fetched_at
            )

            updated_ms = props.get("updated") or time_ms or 0
            fingerprint = self.compute_earthquake_fingerprint(
                event_id=feature_id,
                updated_timestamp=updated_ms,
                magnitude=props.get("mag"),
                org_id=effective_org_id,
            )

            metadata: Dict[str, Any] = {
                "source_url": target_url,
                "correlation_id": correlation_id,
                "usgs_feature_id": feature_id,
            }
            if facility_id:
                metadata["facility_id"] = facility_id
            if port_id:
                metadata["port_id"] = port_id
            if route_id:
                metadata["route_id"] = route_id
            if supplier_id:
                metadata["supplier_id"] = supplier_id

            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=str(feature_id),
                fingerprint=fingerprint,
                source_timestamp=source_ts,
                ingested_at=fetched_at,
                raw_payload=feature,
                metadata=metadata,
                org_id=effective_org_id,
                event_type=CanonicalEventType.EARTHQUAKE.value,
            )
            events.append(raw_event)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            metadata={"total_features": len(features), "target_url": target_url},
            source_metadata=data.get("metadata", {}),
            fetched_at=fetched_at,
        )

    def health_check(self) -> ProviderHealthResult:
        """Perform non-destructive connectivity and schema validation probe."""
        start = time.perf_counter()
        target_url = getattr(self.config, "base_url", None) or DEFAULT_USGS_FEED_URL
        try:
            resp = self.client.get(target_url)
            latency = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.HEALTHY,
                        latency_ms=latency,
                        message="USGS Earthquake API operational and reachable.",
                        details={"features_count": len(data.get("features", []))},
                    )
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="USGS Earthquake returned malformed GeoJSON structure.",
                )

            if resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="USGS Earthquake rate limit encountered (HTTP 429).",
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"USGS Earthquake returned unexpected HTTP {resp.status_code}.",
            )
        except httpx.TimeoutException:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message="USGS Earthquake health probe timed out.",
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"USGS Earthquake connectivity probe failed: {exc.__class__.__name__}",
            )


class USGSEarthquakeNormalizer(BaseEventNormalizer):
    """Normalizes USGS GeoJSON earthquake features into CanonicalExternalEvent models.

    Maps Richter magnitude, depth, location, and tsunami flags to operational severity
    and structured attributes without leaking raw provider constructs.
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        p_name = getattr(raw_event, "provider_name", "")
        return p_name in ("usgs_earthquake", "usgs", "earthquake")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Map raw USGS GeoJSON feature into CanonicalExternalEvent."""
        feature = raw_event.raw_payload or {}
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        validation_errors: List[str] = []

        # 1. Geographic Location Extraction (GeoJSON coordinates: [longitude, latitude, depth_km])
        location_obj: Optional[EventLocation] = None
        depth_km: Optional[float] = None
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            if len(coords) >= 3:
                try:
                    depth_km = float(coords[2])
                except (ValueError, TypeError):
                    pass
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=props.get("place"),
                    country_code=None,
                )
            except ValueError as ve:
                validation_errors.append(str(ve))
        else:
            validation_errors.append("GeoJSON feature missing valid coordinates [lon, lat]")

        # 2. Timestamp Normalization
        time_ms = props.get("time")
        if time_ms is not None:
            try:
                event_ts = TimestampNormalizer.parse_to_utc(time_ms)
            except Exception as exc:
                event_ts = raw_event.ingested_at
                validation_errors.append(f"Invalid timestamp: {exc}")
        else:
            event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 3. Magnitude & Operational Severity Mapping
        raw_mag = props.get("mag")
        magnitude: Optional[float] = None
        if raw_mag is not None:
            try:
                magnitude = float(raw_mag)
            except (ValueError, TypeError):
                validation_errors.append(f"Unparseable magnitude value: {raw_mag}")

        tsunami_flag = bool(props.get("tsunami") == 1)
        alert_level = (props.get("alert") or "").lower()

        # Operational Severity Invariant: Grounded in seismic physical damage risk
        if tsunami_flag or alert_level == "red" or (magnitude is not None and magnitude >= MAG_CRITICAL_THRESHOLD):
            severity = EventSeverity.CRITICAL
        elif alert_level == "orange" or (magnitude is not None and magnitude >= MAG_HIGH_THRESHOLD):
            severity = EventSeverity.HIGH
        elif alert_level == "yellow" or (magnitude is not None and magnitude >= MAG_MEDIUM_THRESHOLD):
            severity = EventSeverity.MEDIUM
        elif magnitude is not None and magnitude >= MAG_LOW_THRESHOLD:
            severity = EventSeverity.LOW
        else:
            severity = EventSeverity.INFO

        # Event type: TSUNAMI if tsunami flag active, else EARTHQUAKE
        event_type = CanonicalEventType.TSUNAMI if tsunami_flag else CanonicalEventType.EARTHQUAKE

        # 4. Entity Correlation Binding
        meta = raw_event.metadata or {}
        corr = EntityCorrelation(
            facility_id=meta.get("facility_id"),
            port_id=meta.get("port_id"),
            route_id=meta.get("route_id"),
            supplier_id=meta.get("supplier_id"),
            custom_identifiers={
                "usgs_id": str(feature.get("id") or props.get("code") or "unknown"),
                "mag_type": str(props.get("magType") or "unknown"),
            },
        )

        # 5. Quality Assessment
        if validation_errors:
            quality = EventQuality.INVALID
        elif location_obj is None:
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

        # 6. Normalized Attributes
        normalized_attrs = {
            "magnitude": magnitude,
            "depth_km": depth_km,
            "place": props.get("place"),
            "felt_reports": props.get("felt"),
            "tsunami_warning": tsunami_flag,
            "alert_level": alert_level or None,
            "significance": props.get("sig"),
            "status": props.get("status", "AUTOMATIC").upper(),
            "mmi": props.get("mmi"),
            "cdi": props.get("cdi"),
            "dmin": props.get("dmin"),
            "gap": props.get("gap"),
            "rms": props.get("rms"),
            "mag_type": props.get("magType"),
        }

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=str(feature.get("id") or props.get("code") or ""),
            event_type=event_type,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp or event_ts,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=corr,
            severity=severity,
            status=props.get("status", "ACTIVE").upper(),
            confidence=0.98 if props.get("status") == "reviewed" else 0.85,
            source_type=EventSourceType.REAL,
            source_url=props.get("url"),
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=normalized_attrs,
            provider_metadata={
                "type": feature.get("type"),
                "network": props.get("net"),
                "code": props.get("code"),
                "sources": props.get("sources"),
                "types": props.get("types"),
            },
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )
