"""NOAA National Weather Service (NWS) Active Alerts API provider adapter and normalizer.

Ingests authoritative US Common Alerting Protocol (CAP) and GeoJSON severe weather
declarations, marine advisories, tropical cyclone warnings, and flood emergencies.
Maps government-declared emergency warnings into strongly typed RawEvent and
CanonicalExternalEvent models with polygon geofences and operational severity ratings.
"""
from __future__ import annotations

import logging
import math
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

logger = logging.getLogger("riskwise.integrations.providers.noaa")

# Default NOAA NWS Endpoints
DEFAULT_NOAA_ALERTS_URL = "https://api.weather.gov/alerts/active"
DEFAULT_USER_AGENT = "ChainSentinel/2.0 (SupplyChainRiskDefense; +https://github.com/chainsentinel)"
DEFAULT_ACCEPT_HEADER = "application/geo+json"


class NOAAAlertsAdapter(BaseProviderAdapter):
    """Production provider adapter for NOAA National Weather Service Active Alerts."""

    provider_name: str = "noaa_nws"
    provider_type: ProviderType = ProviderType.WEATHER
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=True,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=500,
        supported_entities=["port", "route", "facility", "supplier_site", "warehouse", "vessel"],
        supported_modalities=["weather", "marine", "gale", "hurricane", "flood", "storm"],
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
                base_url=DEFAULT_NOAA_ALERTS_URL,
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
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": DEFAULT_ACCEPT_HEADER,
            }
            self._internal_client = httpx.Client(timeout=timeout, headers=headers)
        return self._internal_client

    def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    @classmethod
    def compute_alert_fingerprint(
        cls,
        alert_id: str,
        sent_or_effective: Union[datetime, str],
        severity: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute deterministic, collision-resistant SHA-256 fingerprint for a NOAA alert."""
        if isinstance(sent_or_effective, datetime):
            ts_str = str(int(sent_or_effective.timestamp()))
        else:
            ts_str = str(sent_or_effective)

        payload = {
            "alert_id": str(alert_id),
            "sent_or_effective": ts_str,
            "severity": str(severity or "").upper(),
        }
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="noaa_nws",
            payload=payload,
            organization_id=org_id,
        )

    def fetch(
        self,
        area: Optional[str] = None,
        severity: Optional[str] = None,
        urgency: Optional[str] = None,
        certainty: Optional[str] = None,
        event: Optional[str] = None,
        point: Optional[Tuple[float, float]] = None,
        port_coords: Optional[Tuple[float, float]] = None,
        facility_coords: Optional[Tuple[float, float]] = None,
        status: str = "actual",
        message_type: str = "alert",
        org_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        port_id: Optional[str] = None,
        route_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IngestionBatch:
        """Fetch active severe weather and maritime emergency alerts from NOAA NWS."""
        effective_org_id = organization_id or org_id
        target_url = getattr(self.config, "base_url", None) or DEFAULT_NOAA_ALERTS_URL

        # Support entity-coordinate spatial queries
        if port_coords and not point:
            point = port_coords
        if facility_coords and not point:
            point = facility_coords

        params: Dict[str, str] = {
            "status": status,
            "message_type": message_type,
        }
        if area:
            params["area"] = area.strip()
        if severity:
            params["severity"] = severity.strip()
        if urgency:
            params["urgency"] = urgency.strip()
        if certainty:
            params["certainty"] = certainty.strip()
        if event:
            params["event"] = event.strip()
        if point:
            lat, lon = point
            params["point"] = f"{lat:.4f},{lon:.4f}"

        # Bounded retry execution
        retry_cfg = getattr(self.config, "retry", None) or RetryConfig(max_retries=3, initial_delay_seconds=0.5)

        def _do_get() -> httpx.Response:
            try:
                return self.client.get(target_url, params=params)
            except httpx.TimeoutException as exc:
                raise ProviderTimeoutError(
                    f"NOAA NWS request timed out: {exc}",
                    provider_name=self.provider_name,
                ) from exc
            except httpx.NetworkError as exc:
                raise ProviderConnectionError(
                    f"NOAA NWS network failure: {exc}",
                    provider_name=self.provider_name,
                ) from exc

        try:
            resp, _ = RetryPolicy.execute_with_retry(
                _do_get,
                config=retry_cfg,
                provider_name=self.provider_name,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            if not isinstance(exc, IngestionError):
                raise ProviderConnectionError(
                    f"NOAA NWS fetch failed: {exc}",
                    provider_name=self.provider_name,
                ) from exc
            raise

        if resp.status_code == 400:
            raise ProviderValidationError(
                f"NOAA NWS rejected request parameters (HTTP 400): {resp.text[:200]}",
                provider_name=self.provider_name,
                status_code=400,
            )
        if resp.status_code == 403:
            raise ProviderAuthenticationError(
                f"NOAA NWS forbidden (HTTP 403) - verify User-Agent header: {resp.text[:200]}",
                provider_name=self.provider_name,
                status_code=403,
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else None
            raise ProviderRateLimitError(
                "NOAA NWS rate limit exceeded (HTTP 429)",
                provider_name=self.provider_name,
                retry_after_seconds=retry_seconds,
            )
        if resp.status_code >= 500:
            raise ProviderResponseError(
                f"NOAA NWS service error HTTP {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise ProviderResponseError(
                f"NOAA NWS returned unexpected status HTTP {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"NOAA NWS response is not valid GeoJSON: {exc}",
                provider_name=self.provider_name,
            ) from exc

        features = data.get("features", [])
        events: List[RawEvent] = []
        fetched_at = datetime.now(timezone.utc)

        for feature in features:
            props = feature.get("properties") or {}
            alert_id = feature.get("id") or props.get("id") or "unknown"
            effective_str = props.get("effective") or props.get("sent") or str(fetched_at)
            severity_str = props.get("severity") or "Unknown"

            fingerprint = self.compute_alert_fingerprint(
                alert_id=alert_id,
                sent_or_effective=effective_str,
                severity=severity_str,
                org_id=effective_org_id,
            )

            try:
                source_ts = TimestampNormalizer.parse_to_utc(effective_str)
            except Exception:
                source_ts = fetched_at

            metadata: Dict[str, Any] = {
                "headline": props.get("headline"),
                "event": props.get("event"),
                "severity": severity_str,
                "urgency": props.get("urgency"),
                "certainty": props.get("certainty"),
                "area_desc": props.get("areaDesc"),
                "sender_name": props.get("senderName"),
                "correlation_id": correlation_id,
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
                provider_event_id=str(alert_id),
                fingerprint=fingerprint,
                source_timestamp=source_ts,
                ingested_at=fetched_at,
                raw_payload=feature,
                metadata=metadata,
                org_id=effective_org_id,
                event_type=CanonicalEventType.WEATHER_ALERT.value,
            )
            events.append(raw_event)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            metadata={"total_features": len(features), "target_url": target_url},
            source_metadata={"title": data.get("title", "NOAA NWS Active Alerts")},
            fetched_at=fetched_at,
        )

    def health_check(self) -> ProviderHealthResult:
        """Perform non-destructive connectivity and schema validation probe."""
        start = time.perf_counter()
        target_url = getattr(self.config, "base_url", None) or DEFAULT_NOAA_ALERTS_URL
        try:
            # Probe with status=actual and limit query to extreme/severe alerts to minimize bandwidth
            resp = self.client.get(target_url, params={"status": "actual", "message_type": "alert", "severity": "Extreme"})
            latency = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.HEALTHY,
                        latency_ms=latency,
                        message="NOAA NWS Active Alerts API operational and reachable.",
                        details={"features_count": len(data.get("features", []))},
                    )
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="NOAA NWS returned unexpected non-GeoJSON payload structure.",
                )

            if resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=latency,
                    rate_limited=True,
                    message="NOAA NWS rate limit exceeded.",
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"NOAA NWS health check returned HTTP {resp.status_code}",
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"NOAA NWS connectivity probe failed: {exc.__class__.__name__}",
            )


class NOAANormalizer(BaseEventNormalizer):
    """Normalizes NOAA NWS CAP and GeoJSON alerts into CanonicalExternalEvent models.

    Maps emergency severity (Extreme, Severe, Moderate), certainty, urgency,
    affected geographic zones, and geometry into operational risk contracts.
    """

    @classmethod
    def is_point_in_polygon(cls, lat: float, lon: float, ring: List[List[float]]) -> bool:
        """Ray-casting algorithm to determine if a point (lat, lon) is within a polygon vertex ring.

        Args:
            lat: Latitude of test point.
            lon: Longitude of test point.
            ring: List of [longitude, latitude] coordinate pairs from GeoJSON polygon outer ring.
        """
        inside = False
        n = len(ring)
        if n < 3:
            return False
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]  # xi=lon, yi=lat
            xj, yj = ring[j][0], ring[j][1]  # xj=lon, yj=lat
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    @classmethod
    def haversine_distance_km(cls, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points on the Earth in kilometers."""
        R = 6371.0  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2.0)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0)**2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c

    @classmethod
    def matches_entity_location(
        cls,
        event_or_location: Any,
        entity_lat: float,
        entity_lon: float,
        max_radius_km: float = 50.0,
    ) -> bool:
        """Determine if a severe weather alert geometrically encompasses or borders an entity location.

        1. If Polygon/MultiPolygon geofence is present, executes rigorous ray-casting point-in-polygon containment.
        2. If only centroid coordinates are present, executes Haversine proximity evaluation against max_radius_km.
        3. If neither geometry nor coordinates exist, returns False (defensible spatial matching only).
        """
        geofence = None
        lat = None
        lon = None

        if isinstance(event_or_location, CanonicalExternalEvent):
            if event_or_location.location:
                geofence = event_or_location.location.geofence
                lat = event_or_location.location.latitude
                lon = event_or_location.location.longitude
        elif isinstance(event_or_location, EventLocation):
            geofence = event_or_location.geofence
            lat = event_or_location.latitude
            lon = event_or_location.longitude
        elif isinstance(event_or_location, dict):
            geofence = event_or_location.get("geometry") or event_or_location.get("geofence")
            lat = event_or_location.get("latitude") or event_or_location.get("lat")
            lon = event_or_location.get("longitude") or event_or_location.get("lon")

        # 1. Polygon containment check
        if geofence and isinstance(geofence, dict):
            gtype = geofence.get("type")
            coords = geofence.get("coordinates") or []
            if gtype == "Polygon" and coords and isinstance(coords[0], list):
                if cls.is_point_in_polygon(entity_lat, entity_lon, coords[0]):
                    return True
            elif gtype == "MultiPolygon" and coords:
                for poly in coords:
                    if poly and isinstance(poly[0], list):
                        if cls.is_point_in_polygon(entity_lat, entity_lon, poly[0]):
                            return True

        # 2. Centroid Haversine proximity check
        if lat is not None and lon is not None:
            dist = cls.haversine_distance_km(lat, lon, entity_lat, entity_lon)
            return dist <= max_radius_km

        return False

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        p_name = getattr(raw_event, "provider_name", "")
        return p_name in ("noaa_nws", "noaa", "nws", "weather_alert")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Map raw NOAA GeoJSON feature into CanonicalExternalEvent."""
        feature = raw_event.raw_payload or {}
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        validation_errors: List[str] = []

        # 1. Geographic Location & Geofence Extraction
        location_obj: Optional[EventLocation] = None
        lat: Optional[float] = None
        lon: Optional[float] = None

        if geom and isinstance(geom, dict):
            geom_type = geom.get("type")
            coords = geom.get("coordinates") or []
            # Calculate centroid from Polygon outer ring
            if geom_type == "Polygon" and coords and isinstance(coords[0], list):
                ring = coords[0]
                valid_pts = [pt for pt in ring if len(pt) >= 2]
                if valid_pts:
                    lon = sum(pt[0] for pt in valid_pts) / len(valid_pts)
                    lat = sum(pt[1] for pt in valid_pts) / len(valid_pts)
            elif geom_type == "MultiPolygon" and coords and isinstance(coords[0], list):
                ring = coords[0][0] if coords[0] and isinstance(coords[0][0], list) else []
                valid_pts = [pt for pt in ring if len(pt) >= 2]
                if valid_pts:
                    lon = sum(pt[0] for pt in valid_pts) / len(valid_pts)
                    lat = sum(pt[1] for pt in valid_pts) / len(valid_pts)
            elif geom_type == "Point" and coords and len(coords) >= 2:
                lon = coords[0]
                lat = coords[1]

        area_desc = props.get("areaDesc") or raw_event.metadata.get("area_desc")
        if lat is not None and lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=area_desc,
                    country_code="US",
                    geofence=geom if geom else None,
                )
            except ValueError as ve:
                validation_errors.append(str(ve))
                location_obj = EventLocation(
                    location_name=area_desc,
                    country_code="US",
                    geofence=geom if geom else None,
                )
        elif area_desc:
            location_obj = EventLocation(
                location_name=area_desc,
                country_code="US",
                geofence=geom if geom else None,
            )

        # 2. Timestamp Normalization
        effective_str = props.get("effective") or props.get("sent")
        if effective_str:
            try:
                event_ts = TimestampNormalizer.parse_to_utc(effective_str)
            except Exception as exc:
                event_ts = raw_event.ingested_at
                validation_errors.append(f"Invalid timestamp: {exc}")
        else:
            event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 3. Operational Severity Mapping
        raw_sev = str(props.get("severity") or "").strip().lower()
        if raw_sev == "extreme":
            severity = EventSeverity.CRITICAL
        elif raw_sev == "severe":
            severity = EventSeverity.HIGH
        elif raw_sev == "moderate":
            severity = EventSeverity.MEDIUM
        elif raw_sev == "minor":
            severity = EventSeverity.LOW
        else:
            severity = EventSeverity.INFO

        # 4. Canonical Event Type Classification
        raw_event_name = str(props.get("event") or "").strip().lower()
        if any(term in raw_event_name for term in ["hurricane", "typhoon", "cyclone", "tropical storm"]):
            canonical_type = CanonicalEventType.CYCLONE
        elif any(term in raw_event_name for term in ["flood", "flash flood", "coastal flood"]):
            canonical_type = CanonicalEventType.FLOOD
        elif any(term in raw_event_name for term in ["storm", "gale", "tornado", "blizzard", "high wind", "squall"]):
            canonical_type = CanonicalEventType.STORM
        elif severity == EventSeverity.CRITICAL:
            canonical_type = CanonicalEventType.EXTREME_WEATHER
        else:
            canonical_type = CanonicalEventType.WEATHER_ALERT

        # 5. Entity Correlation
        meta = raw_event.metadata or {}
        ugc_list = props.get("geocode", {}).get("UGC", [])
        ugc_str = ",".join(ugc_list) if isinstance(ugc_list, list) else str(ugc_list or "")

        correlation = EntityCorrelation(
            shipment_id=meta.get("shipment_id"),
            carrier_id=meta.get("carrier_id"),
            port_id=meta.get("port_id"),
            route_id=meta.get("route_id"),
            supplier_id=meta.get("supplier_id"),
            facility_id=meta.get("facility_id"),
            custom_identifiers={
                "nws_event": str(props.get("event") or "Weather Alert"),
                "sender": str(props.get("senderName") or "NWS"),
                "urgency": str(props.get("urgency") or "Unknown"),
                "certainty": str(props.get("certainty") or "Unknown"),
                "ugc_codes": ugc_str,
            },
        )

        headline = props.get("headline") or props.get("event") or "NOAA Severe Weather Alert"
        description = props.get("description") or headline

        # 6. Quality Rating
        quality = EventQuality.VALID if not validation_errors and location_obj else EventQuality.PARTIAL

        normalized_attrs = {
            "headline": headline,
            "description": description,
            "event": props.get("event"),
            "severity_raw": props.get("severity"),
            "urgency": props.get("urgency"),
            "certainty": props.get("certainty"),
            "response": props.get("response"),
            "instruction": props.get("instruction"),
            "area_desc": area_desc,
            "sender_name": props.get("senderName"),
            "effective": props.get("effective"),
            "expires": props.get("expires"),
            "ends": props.get("ends"),
            "has_polygon": geom is not None and geom.get("type") in ("Polygon", "MultiPolygon"),
        }

        alert_id = feature.get("id") or props.get("id") or raw_event.provider_event_id or "unknown"

        return CanonicalExternalEvent(
            provider=raw_event.provider_name or "noaa_nws",
            source_event_id=str(alert_id),
            event_type=canonical_type,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp or event_ts,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=correlation,
            severity=severity,
            status="ACTIVE",
            confidence=0.99,
            source_type=EventSourceType.REAL,
            source_url=str(alert_id) if str(alert_id).startswith("http") else None,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=normalized_attrs,
            provider_metadata=props,
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )
