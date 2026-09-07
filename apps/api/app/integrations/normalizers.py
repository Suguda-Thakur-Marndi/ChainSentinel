"""Normalization abstractions and pipeline for external supply-chain signals.

Translates raw provider envelopes (RawEvent) into strongly typed,
provider-independent CanonicalExternalEvent models.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from app.integrations.base import RawEvent
from app.integrations.canonical import (
    CanonicalEventType,
    CanonicalExternalEvent,
    EntityCorrelation,
    EventLocation,
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.integrations.config import SecretResolver

logger = logging.getLogger("riskwise.integrations.normalizers")


class TimestampNormalizer:
    """Robust parser normalizing diverse timestamp formats to timezone-aware UTC."""

    @classmethod
    def parse_to_utc(cls, val: Any) -> datetime:
        """Parse ISO string, Unix epoch (seconds/ms), or datetime into UTC datetime.

        Raises:
            ValueError: If val is missing, unparseable, or impossible.
        """
        if val is None:
            raise ValueError("Timestamp value cannot be None")

        if isinstance(val, datetime):
            if val.tzinfo is None:
                return val.replace(tzinfo=timezone.utc)
            return val.astimezone(timezone.utc)

        if isinstance(val, (int, float)):
            # Distinguish epoch milliseconds (> 1e11) from seconds
            if val > 1e11:
                return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(val, tz=timezone.utc)

        if isinstance(val, str):
            clean_str = val.strip()
            if not clean_str:
                raise ValueError("Timestamp string cannot be empty")

            # Try ISO 8601 parsing
            try:
                # Handle standard 'Z' suffix or Go-style ' UTC' suffix
                if clean_str.endswith("Z"):
                    clean_str = clean_str[:-1] + "+00:00"
                elif clean_str.endswith(" UTC"):
                    clean_str = clean_str[:-4].strip()
                dt = datetime.fromisoformat(clean_str)
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception as exc:
                # Try numeric string epoch fallback
                try:
                    num = float(clean_str)
                    return cls.parse_to_utc(num)
                except ValueError:
                    pass
                raise ValueError(f"Malformed or unsupported timestamp string: '{val}'") from exc

        raise ValueError(f"Unsupported timestamp type: {type(val).__name__} for value '{val}'")


class CoordinateValidator:
    """Validator ensuring spatial coordinates adhere to WGS84 bounding limits."""

    @classmethod
    def validate(
        cls,
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Tuple[Optional[float], Optional[float]]:
        """Validate latitude (-90 to +90) and longitude (-180 to +180).

        Raises:
            ValueError: If latitude or longitude are outside geographic bounds.
        """
        if latitude is not None:
            lat = float(latitude)
            if lat < -90.0 or lat > 90.0:
                raise ValueError(f"Latitude out of bounds [-90, +90]: {lat}")
        else:
            lat = None

        if longitude is not None:
            lon = float(longitude)
            if lon < -180.0 or lon > 180.0:
                raise ValueError(f"Longitude out of bounds [-180, +180]: {lon}")
        else:
            lon = None

        return lat, lon


class BaseEventNormalizer(ABC):
    """Abstract normalizer converting provider-specific RawEvent into CanonicalExternalEvent."""

    @abstractmethod
    def can_normalize(self, raw_event: RawEvent) -> bool:
        """Check if this normalizer handles the given raw event."""
        pass

    @abstractmethod
    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Transform a raw event into a CanonicalExternalEvent."""
        pass


class DefaultEventNormalizer(BaseEventNormalizer):
    """Fallback generic normalizer extracting common top-level conventions."""

    def can_normalize(self, raw_event: RawEvent) -> bool:
        return True

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        payload = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        # 1. Timestamp resolution
        ts_val = raw_event.source_timestamp or payload.get("timestamp") or payload.get("event_timestamp") or raw_event.ingested_at
        try:
            event_ts = TimestampNormalizer.parse_to_utc(ts_val)
        except Exception as exc:
            event_ts = raw_event.ingested_at
            validation_errors.append(f"Timestamp normalization fallback: {str(exc)}")

        # 2. Location resolution
        lat = payload.get("latitude") or payload.get("lat")
        lon = payload.get("longitude") or payload.get("lon")
        loc_name = payload.get("location_name") or payload.get("location")
        country = payload.get("country_code") or payload.get("country")
        location_obj: Optional[EventLocation] = None

        if lat is not None or lon is not None or loc_name is not None or country is not None:
            try:
                valid_lat, valid_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=valid_lat,
                    longitude=valid_lon,
                    location_name=str(loc_name) if loc_name else None,
                    country_code=str(country)[:3] if country else None,
                )
            except Exception as exc:
                validation_errors.append(f"Location validation failed: {str(exc)}")

        # 3. Entity correlation
        correlation = EntityCorrelation(
            shipment_id=payload.get("shipment_id"),
            carrier_id=payload.get("carrier_id"),
            port_id=payload.get("port_id"),
            route_id=payload.get("route_id"),
            supplier_id=payload.get("supplier_id"),
            facility_id=payload.get("facility_id"),
        )

        # 4. Event type resolution
        raw_type = raw_event.event_type or payload.get("event_type") or "CUSTOM"
        canonical_type = raw_type
        if isinstance(raw_type, str):
            try:
                canonical_type = CanonicalEventType(raw_type.upper())
            except ValueError:
                canonical_type = CanonicalEventType.CUSTOM

        # 5. Quality determination
        if validation_errors:
            quality = EventQuality.PARTIAL
        elif location_obj is None or not correlation.is_correlated:
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
            status=payload.get("status"),
            severity=EventSeverity(payload.get("severity", "INFO")),
            delay_minutes=payload.get("delay_minutes"),
            confidence=payload.get("confidence"),
            source_type=EventSourceType(payload.get("source_type", "REAL")),
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes=payload,
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=quality,
            validation_errors=validation_errors,
        )


class NormalizationPipeline:
    """Central pipeline executing validation, normalizer routing, and quality assessment."""

    def __init__(self) -> None:
        self._normalizers: List[Tuple[int, BaseEventNormalizer]] = []
        self._default_normalizer = DefaultEventNormalizer()

    def register_normalizer(self, normalizer: BaseEventNormalizer, priority: int = 0) -> None:
        """Register a normalizer with higher priority executing earlier."""
        self._normalizers.append((priority, normalizer))
        self._normalizers.sort(key=lambda x: x[0], reverse=True)

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        """Process a RawEvent into a CanonicalExternalEvent through registered normalizers.

        Steps:
        1. Sanitize raw payload (credential redaction)
        2. Resolve appropriate normalizer
        3. Execute normalization
        4. Validate coordinates, timestamps, and quality assessment
        5. Traceability binding
        """
        # Ensure credentials are wiped from raw payload
        raw_event.raw_payload = SecretResolver.sanitize_payload(raw_event.raw_payload)

        # Select normalizer
        selected_normalizer: BaseEventNormalizer = self._default_normalizer
        for _, norm in self._normalizers:
            if norm.can_normalize(raw_event):
                selected_normalizer = norm
                break

        canonical_event = selected_normalizer.normalize(raw_event)

        # Guarantee raw event reference and fingerprint propagation
        raw_id = getattr(raw_event, "event_id", getattr(raw_event, "id", None))
        if not canonical_event.raw_event_id and raw_id:
            canonical_event.raw_event_id = raw_id

        if not canonical_event.payload_fingerprint and raw_event.fingerprint:
            canonical_event.payload_fingerprint = raw_event.fingerprint

        raw_org = getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None))
        if not canonical_event.org_id and raw_org:
            canonical_event.org_id = raw_org

        # Deep sanitize normalized attributes and provider metadata
        canonical_event.normalized_attributes = SecretResolver.sanitize_payload(
            canonical_event.normalized_attributes
        )
        canonical_event.provider_metadata = SecretResolver.sanitize_payload(
            canonical_event.provider_metadata
        )

        # Strict Quality Assessment
        validation_errors = list(canonical_event.validation_errors)

        # Verify coordinates if location is specified
        if canonical_event.location:
            try:
                CoordinateValidator.validate(
                    canonical_event.location.latitude,
                    canonical_event.location.longitude,
                )
            except ValueError as ve:
                validation_errors.append(str(ve))

        # Check required fields
        if not canonical_event.provider or not canonical_event.event_timestamp:
            canonical_event.quality = EventQuality.INVALID
            validation_errors.append("Missing mandatory provider or event_timestamp")
        elif validation_errors:
            canonical_event.quality = EventQuality.INVALID
        elif canonical_event.location is None or not canonical_event.is_correlated:
            canonical_event.quality = EventQuality.PARTIAL
        else:
            canonical_event.quality = EventQuality.VALID

        canonical_event.validation_errors = validation_errors
        return canonical_event


# =====================================================================
# Mock / Test Normalizers
# =====================================================================

class MockWeatherNormalizer(BaseEventNormalizer):
    """Normalizer for mock weather alerts and ambient observations."""

    def can_normalize(self, raw_event: RawEvent) -> bool:
        return raw_event.provider_name in ("mock_weather", "openweather", "weather_service")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        p = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        # Timestamp
        ts_raw = raw_event.source_timestamp or p.get("timestamp") or raw_event.ingested_at
        try:
            event_ts = TimestampNormalizer.parse_to_utc(ts_raw)
        except Exception as e:
            event_ts = raw_event.ingested_at
            validation_errors.append(str(e))

        # Coordinates
        lat = p.get("lat") or p.get("latitude")
        lon = p.get("lon") or p.get("longitude")
        location_obj = None
        if lat is not None or lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=p.get("city") or p.get("location_name"),
                    country_code=p.get("country"),
                )
            except Exception as e:
                validation_errors.append(str(e))

        # Severity
        temp = p.get("temp_c", 20.0)
        wind = p.get("wind_speed_knots", 10.0)
        severity = EventSeverity.INFO
        if wind > 40.0 or temp > 45.0 or temp < -20.0:
            severity = EventSeverity.HIGH
        elif wind > 25.0:
            severity = EventSeverity.MEDIUM

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=CanonicalEventType.WEATHER_ALERT,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=EntityCorrelation(route_id=p.get("route_id")),
            severity=severity,
            status=p.get("conditions", "ACTIVE"),
            confidence=p.get("confidence", 0.95),
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes={
                "temperature_celsius": temp,
                "wind_speed_knots": wind,
                "conditions": p.get("conditions"),
            },
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=EventQuality.VALID if (location_obj and not validation_errors) else EventQuality.PARTIAL,
            validation_errors=validation_errors,
        )


class MockAISNormalizer(BaseEventNormalizer):
    """Normalizer for ocean AIS vessel position signals."""

    def can_normalize(self, raw_event: RawEvent) -> bool:
        return raw_event.provider_name in ("mock_ais", "aisstream", "maritime_ais")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        p = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        ts_raw = p.get("timestamp") or raw_event.source_timestamp or raw_event.ingested_at
        try:
            event_ts = TimestampNormalizer.parse_to_utc(ts_raw)
        except Exception as e:
            event_ts = raw_event.ingested_at
            validation_errors.append(str(e))

        lat = p.get("latitude") or p.get("lat")
        lon = p.get("longitude") or p.get("lon")
        location_obj = None
        if lat is not None or lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(latitude=v_lat, longitude=v_lon)
            except Exception as e:
                validation_errors.append(str(e))

        mmsi = str(p.get("mmsi") or raw_event.provider_event_id or "")

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id or mmsi,
            event_type=CanonicalEventType.VESSEL_LOCATION,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=EntityCorrelation(
                custom_identifiers={"mmsi": mmsi},
                shipment_id=p.get("shipment_id"),  # Unresolved if None
            ),
            severity=EventSeverity.INFO,
            status="UNDERWAY",
            confidence=0.99,
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes={
                "mmsi": mmsi,
                "speed_knots": p.get("speed"),
                "heading_degrees": p.get("heading"),
            },
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=EventQuality.VALID if (location_obj and not validation_errors) else EventQuality.PARTIAL,
            validation_errors=validation_errors,
        )


class MockTrafficNormalizer(BaseEventNormalizer):
    """Normalizer for road incidents and traffic congestion events."""

    def can_normalize(self, raw_event: RawEvent) -> bool:
        return raw_event.provider_name in ("mock_traffic", "tomtom", "here_traffic")

    def normalize(self, raw_event: RawEvent) -> CanonicalExternalEvent:
        p = raw_event.raw_payload or {}
        validation_errors: List[str] = []

        ts_raw = p.get("timestamp") or raw_event.source_timestamp or raw_event.ingested_at
        try:
            event_ts = TimestampNormalizer.parse_to_utc(ts_raw)
        except Exception as e:
            event_ts = raw_event.ingested_at
            validation_errors.append(str(e))

        lat = p.get("latitude") or p.get("lat")
        lon = p.get("longitude") or p.get("lon")
        location_obj = None
        if lat is not None or lon is not None:
            try:
                v_lat, v_lon = CoordinateValidator.validate(lat, lon)
                location_obj = EventLocation(
                    latitude=v_lat,
                    longitude=v_lon,
                    location_name=p.get("road_name"),
                )
            except Exception as e:
                validation_errors.append(str(e))

        delay = float(p.get("delay_minutes", 0.0))
        severity = EventSeverity.LOW
        if delay > 60.0:
            severity = EventSeverity.CRITICAL
        elif delay > 30.0:
            severity = EventSeverity.HIGH
        elif delay > 10.0:
            severity = EventSeverity.MEDIUM

        return CanonicalExternalEvent(
            provider=raw_event.provider_name,
            source_event_id=raw_event.provider_event_id,
            event_type=CanonicalEventType.ROAD_INCIDENT,
            event_timestamp=event_ts,
            observed_at=raw_event.source_timestamp,
            received_at=raw_event.ingested_at,
            location=location_obj,
            correlation=EntityCorrelation(
                route_id=p.get("route_id"),
                shipment_id=p.get("shipment_id"),
            ),
            severity=severity,
            status=p.get("status", "ACTIVE"),
            delay_minutes=delay,
            confidence=0.90,
            source_type=EventSourceType.REAL,
            raw_event_id=getattr(raw_event, "event_id", getattr(raw_event, "id", None)),
            normalized_attributes={
                "delay_minutes": delay,
                "road_name": p.get("road_name"),
                "cause": p.get("cause"),
            },
            provider_metadata=raw_event.metadata or {},
            payload_fingerprint=raw_event.fingerprint,
            org_id=getattr(raw_event, "org_id", getattr(raw_event, "organization_id", None)),
            quality=EventQuality.VALID if (location_obj and not validation_errors) else EventQuality.PARTIAL,
            validation_errors=validation_errors,
        )
