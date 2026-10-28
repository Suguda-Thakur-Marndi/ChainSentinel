"""OpenStreetMap Nominatim geocoding and spatial reference provider adapter and normalizer.

Provides forward and reverse geocoding reference telemetry for enterprise supply-chain entities
(supplier facilities, manufacturing plants, logistics hubs, container ports, warehouses).
Adheres strictly to OpenStreetMap Foundation usage policy (mandatory descriptive User-Agent,
1 request per second client-side rate limit, structured error containment).
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

logger = logging.getLogger("riskwise.integrations.providers.nominatim")

DEFAULT_NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
DEFAULT_NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_USER_AGENT = "ChainSentinel/2.0 (SupplyChainRiskDefense; admin@chainsentinel.local)"


class NominatimAdapter(BaseProviderAdapter):
    """Production provider adapter for OpenStreetMap Nominatim geocoding engine."""

    provider_name: str = "nominatim"
    provider_type: ProviderType = ProviderType.GEOCODING
    capabilities: ProviderCapabilities = ProviderCapabilities(
        supports_polling=True,
        supports_webhook=False,
        supports_webhooks=False,
        supports_streaming=False,
        supports_batch=False,
        supports_health_check=True,
        supports_historical=False,
        max_batch_size=20,
        supported_entities=["supplier", "supplier_site", "factory", "warehouse", "port", "facility", "route"],
        supported_modalities=["geocoding", "reverse_geocoding", "reference_data"],
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
                base_url=DEFAULT_NOMINATIM_SEARCH_URL,
                auth_mode=AuthMode.NONE,
                secret_ref=None,
                # Enforce OSM 1 req/sec policy
                rate_limit=RateLimitConfig(requests_per_minute=60, burst_limit=1),
                retry=RetryConfig(max_retries=2, initial_delay_seconds=1.0),
            )
        super().__init__(config=config, secret=secret)
        self.secret_resolver = secret_resolver or SecretResolver()
        self.idempotency_engine = idempotency_engine or IdempotencyEngine()
        self._external_client = http_client
        self._internal_client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Provide active HTTP client with mandated OSM User-Agent."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            timeout = getattr(self.config, "timeout_seconds", 10.0)
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "application/json",
            }
            self._internal_client = httpx.Client(timeout=timeout, headers=headers)
        return self._internal_client

    def close(self) -> None:
        """Release underlying HTTP resources."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            self._internal_client.close()

    @classmethod
    def compute_geocoding_fingerprint(
        cls,
        osm_id: Union[int, str],
        osm_type: str,
        query_or_coords: str,
        org_id: Optional[str] = None,
    ) -> str:
        """Compute deterministic SHA-256 fingerprint for a geocoding result."""
        payload = {
            "osm_id": str(osm_id),
            "osm_type": str(osm_type),
            "ref": str(query_or_coords),
        }
        return IdempotencyEngine.compute_fingerprint(
            event_or_provider="nominatim",
            payload=payload,
            organization_id=org_id,
        )

    def fetch(
        self,
        query: Optional[str] = None,
        q: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        limit: int = 5,
        country_codes: Optional[str] = None,
        correlation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        org_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        facility_id: Optional[str] = None,
        warehouse_id: Optional[str] = None,
        port_id: Optional[str] = None,
    ) -> IngestionBatch:
        """Execute forward or reverse geocoding via Nominatim.

        Forward Geocoding: Provide query (or q) string.
        Reverse Geocoding: Provide latitude and longitude coordinates.
        """
        search_query = query or q
        target_lat = latitude if latitude is not None else lat
        target_lon = longitude if longitude is not None else lon
        effective_org_id = organization_id or org_id
        fetched_at = datetime.now(timezone.utc)

        if search_query:
            # Forward geocoding
            target_url = DEFAULT_NOMINATIM_SEARCH_URL
            params: Dict[str, Any] = {
                "q": search_query.strip(),
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": min(max(1, limit), 20),
            }
            if country_codes:
                params["countrycodes"] = country_codes.strip()
            query_ref = f"q:{search_query.strip()}"
        elif target_lat is not None and target_lon is not None:
            # Reverse geocoding
            CoordinateValidator.validate(target_lat, target_lon)
            target_url = DEFAULT_NOMINATIM_REVERSE_URL
            params = {
                "lat": target_lat,
                "lon": target_lon,
                "format": "jsonv2",
                "addressdetails": 1,
            }
            query_ref = f"coords:{round(target_lat, 4)},{round(target_lon, 4)}"
        else:
            raise ProviderValidationError(
                "Nominatim requires either 'query' (for forward geocoding) or ('latitude', 'longitude') for reverse geocoding.",
                provider_name=self.provider_name,
            )

        try:
            resp = self.client.get(target_url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Nominatim geocoding request timed out: {exc}",
                provider_name=self.provider_name,
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderConnectionError(
                f"Nominatim network connection failed: {exc}",
                provider_name=self.provider_name,
            ) from exc
        except Exception as exc:
            raise ProviderConnectionError(
                f"Nominatim request error: {exc}",
                provider_name=self.provider_name,
            ) from exc

        if resp.status_code == 403:
            raise ProviderAuthenticationError(
                "Nominatim access forbidden (HTTP 403). Ensure valid User-Agent is supplied according to OSM Usage Policy.",
                provider_name=self.provider_name,
                status_code=403,
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            retry_seconds = float(retry_after) if retry_after and retry_after.isdigit() else 1.0
            raise ProviderRateLimitError(
                "Nominatim rate limit exceeded (HTTP 429). Respect 1 req/sec policy.",
                provider_name=self.provider_name,
                retry_after_seconds=retry_seconds,
            )
        if resp.status_code >= 500:
            raise ProviderResponseError(
                f"Nominatim service error HTTP {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise ProviderResponseError(
                f"Nominatim returned unexpected HTTP status {resp.status_code}",
                provider_name=self.provider_name,
                status_code=resp.status_code,
            )

        try:
            raw_data = resp.json()
        except Exception as exc:
            raise ProviderResponseError(
                f"Nominatim response is not valid JSON: {exc}",
                provider_name=self.provider_name,
            ) from exc

        # Format items: list for search, single dict for reverse
        items: List[Dict[str, Any]] = raw_data if isinstance(raw_data, list) else ([raw_data] if isinstance(raw_data, dict) and "error" not in raw_data else [])
        events: List[RawEvent] = []

        for item in items:
            osm_id = item.get("osm_id") or "0"
            osm_type = item.get("osm_type") or "N"
            fingerprint = self.compute_geocoding_fingerprint(
                osm_id=osm_id,
                osm_type=osm_type,
                query_or_coords=query_ref,
                org_id=effective_org_id,
            )

            metadata: Dict[str, Any] = {
                "source_url": target_url,
                "correlation_id": correlation_id,
                "query_ref": query_ref,
            }
            if supplier_id:
                metadata["supplier_id"] = supplier_id
            if facility_id:
                metadata["facility_id"] = facility_id
            if warehouse_id:
                metadata["warehouse_id"] = warehouse_id
            if port_id:
                metadata["port_id"] = port_id

            raw_event = RawEvent(
                provider_name=self.provider_name,
                provider_type=self.provider_type,
                provider_event_id=f"osm_{osm_type}_{osm_id}",
                fingerprint=fingerprint,
                source_timestamp=fetched_at,
                ingested_at=fetched_at,
                raw_payload=item,
                metadata=metadata,
                org_id=effective_org_id,
                event_type=CanonicalEventType.GEOCODING_REFERENCE.value,
            )
            events.append(raw_event)

        return IngestionBatch(
            provider_name=self.provider_name,
            events=events,
            metadata={"query_ref": query_ref, "matches_count": len(events)},
            fetched_at=fetched_at,
        )

    def health_check(self) -> ProviderHealthResult:
        """Perform non-destructive probe verifying Nominatim accessibility."""
        start = time.perf_counter()
        params = {"q": "London", "format": "jsonv2", "limit": 1}
        try:
            resp = self.client.get(DEFAULT_NOMINATIM_SEARCH_URL, params=params)
            latency = (time.perf_counter() - start) * 1000.0

            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0:
                    return ProviderHealthResult(
                        provider_name=self.provider_name,
                        status=ProviderHealthStatus.HEALTHY,
                        latency_ms=latency,
                        message="Nominatim OSM geocoding service operational.",
                        details={"status_code": 200, "sample_place": data[0].get("display_name")},
                    )
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.UNHEALTHY,
                    latency_ms=latency,
                    message="Nominatim returned empty or invalid response.",
                )

            if resp.status_code == 429:
                return ProviderHealthResult(
                    provider_name=self.provider_name,
                    status=ProviderHealthStatus.DEGRADED,
                    latency_ms=latency,
                    message="Nominatim rate limit reached (HTTP 429).",
                )

            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"Nominatim returned HTTP {resp.status_code}.",
            )
        except httpx.TimeoutException:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message="Nominatim health check timed out.",
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000.0
            return ProviderHealthResult(
                provider_name=self.provider_name,
                status=ProviderHealthStatus.UNHEALTHY,
                latency_ms=latency,
                message=f"Nominatim connectivity error: {exc.__class__.__name__}",
            )


class NominatimNormalizer(BaseEventNormalizer):
    """Normalizes Nominatim geocoding payloads into CanonicalExternalEvent models.

    Maps OpenStreetMap coordinates, address details, and bounding boxes into
    standardized WGS84 spatial models with attribution.
    """

    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        p_name = getattr(raw_event, "provider_name", "")
        return p_name in ("nominatim", "osm", "osm_nominatim")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Map raw Nominatim payload into CanonicalExternalEvent."""
        item = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        # 1. Coordinate Validation
        lat_raw = item.get("lat")
        lon_raw = item.get("lon")
        location_obj: Optional[EventLocation] = None

        if lat_raw is not None and lon_raw is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat_raw, lon_raw)
                addr = item.get("address") or {}
                country_code = addr.get("country_code", "").upper() if addr.get("country_code") else None
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=item.get("display_name"),
                    country_code=country_code,
                    region=addr.get("state") or addr.get("region"),
                )
            except ValueError as ve:
                validation_errors.append(str(ve))
        else:
            validation_errors.append("Nominatim payload missing 'lat' or 'lon'")

        # 2. Timestamp
        event_ts = raw_event.source_timestamp or raw_event.ingested_at

        # 3. Entity Correlation
        meta = raw_event.metadata or {}
        corr = EntityCorrelation(
            supplier_id=meta.get("supplier_id"),
            facility_id=meta.get("facility_id"),
            port_id=meta.get("port_id"),
            custom_identifiers={
                "osm_id": str(item.get("osm_id") or "unknown"),
                "osm_type": str(item.get("osm_type") or "unknown"),
                "category": str(item.get("category") or "unknown"),
                "place_type": str(item.get("type") or "unknown"),
            },
        )

        # 4. Quality Assessment
        if validation_errors:
            quality = EventQuality.INVALID
        elif location_obj is None:
            quality = EventQuality.PARTIAL
        else:
            quality = EventQuality.VALID

        # 5. Normalized Attributes
        addr = item.get("address") or {}
        normalized_attrs = {
            "display_name": item.get("display_name"),
            "osm_id": item.get("osm_id"),
            "osm_type": item.get("osm_type"),
            "category": item.get("category"),
            "place_type": item.get("type"),
            "place_rank": item.get("place_rank"),
            "importance": item.get("importance"),
            "boundingbox": item.get("boundingbox"),
            "country": addr.get("country"),
            "country_code": addr.get("country_code", "").upper() if addr.get("country_code") else None,
            "state": addr.get("state"),
            "city": addr.get("city") or addr.get("town") or addr.get("village"),
            "postcode": addr.get("postcode"),
            "attribution": "Data © OpenStreetMap contributors, ODbL 1.0",
        }

        importance = item.get("importance")
        confidence = float(importance) if importance is not None else 0.8

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=CanonicalEventType.GEOCODING_REFERENCE,
            event_timestamp=event_ts,
            observed_at=event_ts,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=corr,
            severity=EventSeverity.INFO,
            status="GEOCODED",
            confidence=min(1.0, max(0.1, confidence)),
            source_type=EventSourceType.REAL,
            source_url=meta.get("source_url") or DEFAULT_NOMINATIM_SEARCH_URL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=normalized_attrs,
            provider_metadata={
                "licence": item.get("licence"),
                "query_ref": meta.get("query_ref"),
            },
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )
