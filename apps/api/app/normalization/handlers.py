"""Domain-specific normalization handlers and registry for Phase 6.

Transforms CanonicalExternalEvent objects into domain-neutral NormalizedRiskSignal
instances without coupling to specific external provider names.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.integrations.canonical import (
    CanonicalEventType,
    CanonicalExternalEvent,
    EventQuality,
    EventSeverity,
    EventSourceType,
)
from app.normalization.contract import (
    CorrelationStatus,
    NormalizedRiskSignal,
    OperationalValues,
    SignalDomain,
    SignalEntityReferences,
    SignalStatus,
    SignalType,
)
from app.normalization.status import StatusNormalizer
from app.normalization.units import UnitNormalizer

logger = logging.getLogger("riskwise.normalization.handlers")


class BaseDomainNormalizationHandler(ABC):
    """Abstract base handler for domain-specific risk signal normalization."""

    @abstractmethod
    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        """Determine if this handler applies to the given canonical event."""
        pass

    @abstractmethod
    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        """Convert a canonical event into a typed NormalizedRiskSignal."""
        pass

    def _extract_base_entities(self, event: CanonicalExternalEvent) -> SignalEntityReferences:
        """Extract standard supply-chain entity references from canonical correlation."""
        corr = event.correlation
        custom = corr.custom_identifiers if corr else {}

        entities = SignalEntityReferences(
            shipment_id=corr.shipment_id if corr else None,
            carrier_id=corr.carrier_id if corr else None,
            port_id=corr.port_id if corr else None,
            route_id=corr.route_id if corr else None,
            supplier_id=corr.supplier_id if corr else None,
            facility_id=corr.facility_id if corr else None,
            unresolved_identifiers=dict(custom) if custom else {},
        )

        # Infer transit asset identifiers from custom identifiers if available
        if "vessel_mmsi" in entities.unresolved_identifiers:
            entities.vessel_mmsi = entities.unresolved_identifiers["vessel_mmsi"]
        elif "mmsi" in entities.unresolved_identifiers:
            entities.vessel_mmsi = entities.unresolved_identifiers["mmsi"]

        if "aircraft_icao24" in entities.unresolved_identifiers:
            entities.aircraft_icao24 = entities.unresolved_identifiers["aircraft_icao24"]
        elif "icao24" in entities.unresolved_identifiers:
            entities.aircraft_icao24 = entities.unresolved_identifiers["icao24"]

        if "flight_number" in entities.unresolved_identifiers:
            entities.flight_number = entities.unresolved_identifiers["flight_number"]
        elif "callsign" in entities.unresolved_identifiers:
            entities.flight_number = entities.unresolved_identifiers["callsign"]

        if "trip_id" in entities.unresolved_identifiers:
            entities.trip_id = entities.unresolved_identifiers["trip_id"]

        if "vehicle_id" in entities.unresolved_identifiers:
            entities.vehicle_id = entities.unresolved_identifiers["vehicle_id"]

        # Assess correlation status
        if entities.shipment_id or entities.supplier_id:
            entities.correlation_status = CorrelationStatus.RESOLVED
        elif entities.port_id or entities.route_id or entities.carrier_id:
            entities.correlation_status = CorrelationStatus.PARTIAL
        elif entities.unresolved_identifiers or entities.vessel_mmsi or entities.aircraft_icao24:
            entities.correlation_status = CorrelationStatus.PARTIAL
        else:
            entities.correlation_status = CorrelationStatus.NONE

        return entities


# -----------------------------------------------------------------------------
# 1. Weather Domain Handler
# -----------------------------------------------------------------------------
class WeatherNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes meteorological alerts, storms, and environmental signals."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.WEATHER_ALERT,
        CanonicalEventType.STORM,
        CanonicalEventType.FLOOD,
        CanonicalEventType.CYCLONE,
        CanonicalEventType.EXTREME_WEATHER,
        "WEATHER_ALERT",
        "STORM",
        "FLOOD",
        "CYCLONE",
        "EXTREME_WEATHER",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        return ev_type in self._SUPPORTED_TYPES or "weather" in ev_type.lower()

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        raw_temp = attrs.get("temperature_celsius") or attrs.get("temperature")
        temp_unit = attrs.get("temperature_unit", "celsius" if "temperature_celsius" in attrs else None)
        temp_norm = UnitNormalizer.normalize_temperature(raw_temp, temp_unit)

        raw_wind = attrs.get("wind_speed_mps") or attrs.get("wind_speed")
        wind_unit = "m/s" if "wind_speed_mps" in attrs else attrs.get("wind_speed_unit")
        speed_norm = UnitNormalizer.normalize_speed(raw_wind, wind_unit)

        measurements = OperationalValues(
            temperature_celsius=temp_norm.normalized_value,
            speed_kmh=speed_norm.normalized_value,
            disruption_level=1.0 if event.severity in (EventSeverity.HIGH, EventSeverity.CRITICAL) else 0.4,
            operational_status=event.status,
        )

        signal_type = SignalType.HAZARD
        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        if "flood" in ev_str.lower() or "storm" in ev_str.lower():
            signal_type = SignalType.DISRUPTION

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.WEATHER,
            signal_type=signal_type,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.9,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            location_name=event.location.location_name if event.location else None,
            country_code=event.location.country_code if event.location else None,
            region=event.location.region if event.location else None,
            precision_meters=event.location.precision_meters if event.location else None,
            entities=self._extract_base_entities(event),
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 2. Road Traffic Domain Handler
# -----------------------------------------------------------------------------
class RoadTrafficNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes highway incidents, road congestion, and traffic closures."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.ROAD_INCIDENT,
        CanonicalEventType.ROAD_CLOSURE,
        CanonicalEventType.TRAFFIC_CONGESTION,
        "ROAD_INCIDENT",
        "ROAD_CLOSURE",
        "TRAFFIC_CONGESTION",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        return ev_type in self._SUPPORTED_TYPES or "traffic" in ev_type.lower() or "road" in ev_type.lower()

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        raw_delay = event.delay_minutes or attrs.get("delay_minutes") or attrs.get("delay")
        delay_unit = attrs.get("delay_unit", "minutes" if "delay_minutes" in attrs or event.delay_minutes else None)
        delay_norm = UnitNormalizer.normalize_duration(raw_delay, delay_unit)

        raw_length = attrs.get("length_meters") or attrs.get("jam_length")
        length_unit = "m" if "length_meters" in attrs else attrs.get("length_unit")
        dist_norm = UnitNormalizer.normalize_distance(raw_length, length_unit)

        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        signal_type = SignalType.CONGESTION if "congestion" in ev_str.lower() else SignalType.INCIDENT
        if "closure" in ev_str.lower():
            signal_type = SignalType.DISRUPTION

        measurements = OperationalValues(
            delay_minutes=delay_norm.normalized_value,
            distance_km=dist_norm.normalized_value,
            disruption_level=0.8 if "closure" in ev_str.lower() else 0.5,
            operational_status=event.status,
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.ROAD,
            signal_type=signal_type,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.85,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            location_name=event.location.location_name if event.location else None,
            country_code=event.location.country_code if event.location else None,
            entities=self._extract_base_entities(event),
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 3. Ocean AIS Domain Handler
# -----------------------------------------------------------------------------
class OceanAISNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes vessel movements, maritime delays, and port alerts."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.VESSEL_LOCATION,
        CanonicalEventType.VESSEL_DELAY,
        CanonicalEventType.MARITIME_INCIDENT,
        CanonicalEventType.PORT_CONGESTION,
        CanonicalEventType.PORT_CLOSURE,
        CanonicalEventType.PORT_DELAY,
        "VESSEL_LOCATION",
        "VESSEL_DELAY",
        "MARITIME_INCIDENT",
        "PORT_CONGESTION",
        "PORT_CLOSURE",
        "PORT_DELAY",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type).lower()
        if "airport" in ev_type:
            return False
        return (
            ev_type.upper() in self._SUPPORTED_TYPES
            or "vessel" in ev_type
            or "maritime" in ev_type
            or "port" in ev_type
            or "ocean" in ev_type
            or "ais" in ev_type
        )

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        raw_speed = attrs.get("speed_over_ground_knots") or attrs.get("speed_knots") or attrs.get("speed")
        speed_unit = "knots" if ("speed_over_ground_knots" in attrs or "speed_knots" in attrs) else attrs.get("speed_unit")
        speed_norm = UnitNormalizer.normalize_speed(raw_speed, speed_unit)

        entities = self._extract_base_entities(event)
        if "mmsi" in attrs and not entities.vessel_mmsi:
            entities.vessel_mmsi = str(attrs["mmsi"])

        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        signal_type = SignalType.STATUS_UPDATE
        if "delay" in ev_str.lower():
            signal_type = SignalType.DELAY
        elif "incident" in ev_str.lower() or "closure" in ev_str.lower():
            signal_type = SignalType.DISRUPTION
        elif "congestion" in ev_str.lower():
            signal_type = SignalType.CONGESTION

        measurements = OperationalValues(
            speed_kmh=speed_norm.normalized_value,
            delay_minutes=event.delay_minutes,
            eta=event.eta,
            operational_status=event.status,
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.OCEAN,
            signal_type=signal_type,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.95,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            location_name=event.location.location_name if event.location else None,
            entities=entities,
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 4. Air Freight Domain Handler
# -----------------------------------------------------------------------------
class AirFreightNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes flight delays, cancellations, and air transit telemetry."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.FLIGHT_DELAY,
        CanonicalEventType.FLIGHT_CANCELLATION,
        CanonicalEventType.AIRPORT_DISRUPTION,
        "FLIGHT_DELAY",
        "FLIGHT_CANCELLATION",
        "AIRPORT_DISRUPTION",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        return ev_type in self._SUPPORTED_TYPES or "flight" in ev_type.lower() or "air" in ev_type.lower()

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        raw_speed = attrs.get("velocity_mps") or attrs.get("speed_mps") or attrs.get("speed")
        speed_unit = "m/s" if ("velocity_mps" in attrs or "speed_mps" in attrs) else attrs.get("speed_unit")
        speed_norm = UnitNormalizer.normalize_speed(raw_speed, speed_unit)

        entities = self._extract_base_entities(event)
        if "icao24" in attrs and not entities.aircraft_icao24:
            entities.aircraft_icao24 = str(attrs["icao24"])
        if "callsign" in attrs and not entities.flight_number:
            entities.flight_number = str(attrs["callsign"]).strip()

        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        signal_type = SignalType.STATUS_UPDATE
        if "delay" in ev_str.lower():
            signal_type = SignalType.DELAY
        elif "cancellation" in ev_str.lower():
            signal_type = SignalType.DISRUPTION

        measurements = OperationalValues(
            speed_kmh=speed_norm.normalized_value,
            delay_minutes=event.delay_minutes,
            eta=event.eta,
            operational_status=event.status,
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.AIR,
            signal_type=signal_type,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.95,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            entities=entities,
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 5. Rail Transit Domain Handler
# -----------------------------------------------------------------------------
class RailTransitNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes rail logistics, train delays, and track disruptions."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.TRAIN_DELAY,
        CanonicalEventType.RAIL_DISRUPTION,
        "TRAIN_DELAY",
        "RAIL_DISRUPTION",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        return ev_type in self._SUPPORTED_TYPES or "rail" in ev_type.lower() or "train" in ev_type.lower()

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        raw_delay = event.delay_minutes or attrs.get("delay_minutes")
        if raw_delay is None and "delay_seconds" in attrs:
            raw_delay = attrs["delay_seconds"] / 60.0

        entities = self._extract_base_entities(event)
        if "trip_id" in attrs and not entities.trip_id:
            entities.trip_id = str(attrs["trip_id"])
        if "route_id" in attrs and not entities.route_id:
            entities.route_id = str(attrs["route_id"])

        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        signal_type = SignalType.DISRUPTION if "disruption" in ev_str.lower() else SignalType.DELAY

        measurements = OperationalValues(
            delay_minutes=raw_delay,
            eta=event.eta,
            operational_status=event.status,
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.RAIL,
            signal_type=signal_type,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.9,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            entities=entities,
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 6. Logistics & Tracking Domain Handler
# -----------------------------------------------------------------------------
class LogisticsTrackingNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes carrier milestones, tracking updates, and delivery exceptions."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.PARCEL_STATUS,
        CanonicalEventType.DELIVERY_DELAY,
        CanonicalEventType.SHIPMENT_STATUS,
        CanonicalEventType.SHIPMENT_DELAY,
        CanonicalEventType.ETA_CHANGE,
        CanonicalEventType.LOCATION_UPDATE,
        "PARCEL_STATUS",
        "DELIVERY_DELAY",
        "SHIPMENT_STATUS",
        "SHIPMENT_DELAY",
        "ETA_CHANGE",
        "LOCATION_UPDATE",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        return (
            ev_type in self._SUPPORTED_TYPES
            or "shipment" in ev_type.lower()
            or "tracking" in ev_type.lower()
            or "parcel" in ev_type.lower()
        )

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        raw_delay = event.delay_minutes or attrs.get("delay_minutes")

        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        signal_type = SignalType.STATUS_UPDATE
        if "delay" in ev_str.lower():
            signal_type = SignalType.DELAY
        elif "eta" in ev_str.lower():
            signal_type = SignalType.STATUS_UPDATE

        measurements = OperationalValues(
            delay_minutes=raw_delay,
            eta=event.eta,
            operational_status=event.status,
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.LOGISTICS,
            signal_type=signal_type,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.9,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            entities=self._extract_base_entities(event),
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 7. Intelligence & News Domain Handler
# -----------------------------------------------------------------------------
class IntelligenceNewsNormalizationHandler(BaseDomainNormalizationHandler):
    """Normalizes unstructured news, research reports, and geopolitical signals."""

    _SUPPORTED_TYPES = {
        CanonicalEventType.NEWS_EVENT,
        CanonicalEventType.GEOPOLITICAL_EVENT,
        "NEWS_EVENT",
        "GEOPOLITICAL_EVENT",
    }

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        ev_type = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        return ev_type in self._SUPPORTED_TYPES or "news" in ev_type.lower() or "geopolitical" in ev_type.lower()

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        attrs = dict(event.normalized_attributes)
        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)

        measurements = OperationalValues(
            disruption_level=0.7 if event.severity in (EventSeverity.HIGH, EventSeverity.CRITICAL) else 0.3,
            operational_status=event.status or "REPORTED",
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.INTELLIGENCE,
            signal_type=SignalType.INCIDENT,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.75,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            entities=self._extract_base_entities(event),
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=attrs,
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# 8. General Fallback Domain Handler
# -----------------------------------------------------------------------------
class GeneralNormalizationHandler(BaseDomainNormalizationHandler):
    """Fallback handler for arbitrary custom or unclassified canonical events."""

    def can_handle(self, event: CanonicalExternalEvent) -> bool:
        return True

    def normalize(self, event: CanonicalExternalEvent) -> NormalizedRiskSignal:
        ev_str = str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type)
        measurements = OperationalValues(
            delay_minutes=event.delay_minutes,
            eta=event.eta,
            operational_status=event.status,
        )

        return NormalizedRiskSignal(
            organization_id=event.org_id,
            domain=SignalDomain.GENERAL,
            signal_type=SignalType.CUSTOM,
            event_type=ev_str,
            status=StatusNormalizer.normalize_status(event.status),
            severity=event.severity,
            confidence=event.confidence if event.confidence is not None else 0.5,
            quality=event.quality,
            event_time=event.event_timestamp,
            observed_at=event.observed_at,
            received_at=event.received_at,
            latitude=event.latitude,
            longitude=event.longitude,
            entities=self._extract_base_entities(event),
            source=event.provider,
            source_type=event.source_type,
            provider=event.provider,
            canonical_event_id=event.event_id,
            raw_event_id=event.raw_event_id,
            provider_event_id=event.source_event_id,
            source_reference=event.source_url,
            correlation_id=event.correlation_id,
            trace_id=getattr(event, "trace_id", None),
            ingestion_run_id=event.ingestion_run_id,
            measurements=measurements,
            normalized_attributes=dict(event.normalized_attributes),
            canonical_attributes={"raw_status": event.status},
        )


# -----------------------------------------------------------------------------
# Domain Normalization Registry
# -----------------------------------------------------------------------------
class DomainNormalizationRegistry:
    """Registry managing domain handlers and routing canonical events without provider coupling."""

    def __init__(self) -> None:
        self._handlers: List[BaseDomainNormalizationHandler] = [
            WeatherNormalizationHandler(),
            RoadTrafficNormalizationHandler(),
            OceanAISNormalizationHandler(),
            AirFreightNormalizationHandler(),
            RailTransitNormalizationHandler(),
            LogisticsTrackingNormalizationHandler(),
            IntelligenceNewsNormalizationHandler(),
            GeneralNormalizationHandler(),  # Fallback must be last
        ]

    def register_handler(self, handler: BaseDomainNormalizationHandler, index: Optional[int] = None) -> None:
        """Register a custom domain handler."""
        if index is not None:
            self._handlers.insert(index, handler)
        else:
            # Insert before the general fallback handler
            self._handlers.insert(len(self._handlers) - 1, handler)

    def resolve_handler(self, event: CanonicalExternalEvent) -> BaseDomainNormalizationHandler:
        """Resolve the appropriate domain normalization handler for an event."""
        for handler in self._handlers:
            if handler.can_handle(event):
                return handler
        return self._handlers[-1]
