"""Deterministic unit normalization policy and conversion functions for Phase 6.

Standardizes operational telemetry into canonical engineering units:
- Distance: kilometers (km)
- Speed: kilometers per hour (km/h)
- Duration / Delay: minutes
- Temperature: Celsius (°C)
- Weight: kilograms (kg)

Enforces strict unknown-unit policy: Never fabricate units. If the source unit
is unknown or unspecified, the original value is preserved without conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class UnitConversionResult:
    """Result of an attempted unit normalization."""

    normalized_value: Optional[float]
    target_unit: str
    original_value: Optional[float]
    original_unit: Optional[str]
    is_converted: bool
    conversion_note: Optional[str] = None


class UnitNormalizer:
    """Deterministic converter for telemetry units across supply-chain domains."""

    # -------------------------------------------------------------------------
    # Distance Normalization -> kilometers (km)
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_distance(
        cls,
        value: Optional[float],
        unit: Optional[str],
    ) -> UnitConversionResult:
        """Convert distance to kilometers (km)."""
        if value is None:
            return UnitConversionResult(None, "km", None, unit, False, "Value is None")

        if unit is None or not unit.strip():
            # Unknown unit: preserve value, do NOT invent conversion
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=None,
                is_converted=False,
                conversion_note="Source unit unknown; preserved original without conversion.",
            )

        u = unit.strip().lower()
        if u in ("km", "kilometer", "kilometers"):
            return UnitConversionResult(round(value, 3), "km", value, unit, True)
        elif u in ("m", "meter", "meters"):
            return UnitConversionResult(round(value / 1000.0, 3), "km", value, unit, True)
        elif u in ("mi", "mile", "miles"):
            return UnitConversionResult(round(value * 1.609344, 3), "km", value, unit, True)
        elif u in ("nm", "nmi", "nautical_mile", "nautical_miles"):
            return UnitConversionResult(round(value * 1.852, 3), "km", value, unit, True)
        elif u in ("ft", "feet", "foot"):
            return UnitConversionResult(round(value * 0.0003048, 3), "km", value, unit, True)
        else:
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=unit,
                is_converted=False,
                conversion_note=f"Unrecognized distance unit '{unit}'; preserved without conversion.",
            )

    # -------------------------------------------------------------------------
    # Speed Normalization -> kilometers per hour (km/h)
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_speed(
        cls,
        value: Optional[float],
        unit: Optional[str],
    ) -> UnitConversionResult:
        """Convert speed to kilometers per hour (km/h)."""
        if value is None:
            return UnitConversionResult(None, "km/h", None, unit, False, "Value is None")

        if unit is None or not unit.strip():
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=None,
                is_converted=False,
                conversion_note="Source speed unit unknown; preserved original without conversion.",
            )

        u = unit.strip().lower()
        if u in ("km/h", "kmh", "kph"):
            return UnitConversionResult(round(value, 2), "km/h", value, unit, True)
        elif u in ("knots", "knot", "kt", "kts"):
            return UnitConversionResult(round(value * 1.852, 2), "km/h", value, unit, True)
        elif u in ("m/s", "mps", "meters_per_second"):
            return UnitConversionResult(round(value * 3.6, 2), "km/h", value, unit, True)
        elif u in ("mph", "miles_per_hour"):
            return UnitConversionResult(round(value * 1.609344, 2), "km/h", value, unit, True)
        else:
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=unit,
                is_converted=False,
                conversion_note=f"Unrecognized speed unit '{unit}'; preserved without conversion.",
            )

    # -------------------------------------------------------------------------
    # Duration / Delay Normalization -> minutes
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_duration(
        cls,
        value: Optional[float],
        unit: Optional[str],
    ) -> UnitConversionResult:
        """Convert duration or delay to minutes."""
        if value is None:
            return UnitConversionResult(None, "minutes", None, unit, False, "Value is None")

        if unit is None or not unit.strip():
            # Default convention: if unit is omitted for delay, check context; otherwise preserve
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=None,
                is_converted=False,
                conversion_note="Source duration unit unknown; preserved without conversion.",
            )

        u = unit.strip().lower()
        if u in ("min", "mins", "minute", "minutes"):
            return UnitConversionResult(round(value, 2), "minutes", value, unit, True)
        elif u in ("s", "sec", "secs", "second", "seconds"):
            return UnitConversionResult(round(value / 60.0, 2), "minutes", value, unit, True)
        elif u in ("h", "hr", "hrs", "hour", "hours"):
            return UnitConversionResult(round(value * 60.0, 2), "minutes", value, unit, True)
        elif u in ("d", "day", "days"):
            return UnitConversionResult(round(value * 1440.0, 2), "minutes", value, unit, True)
        else:
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=unit,
                is_converted=False,
                conversion_note=f"Unrecognized duration unit '{unit}'; preserved without conversion.",
            )

    # -------------------------------------------------------------------------
    # Temperature Normalization -> Celsius (°C)
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_temperature(
        cls,
        value: Optional[float],
        unit: Optional[str],
    ) -> UnitConversionResult:
        """Convert temperature to Celsius (°C)."""
        if value is None:
            return UnitConversionResult(None, "°C", None, unit, False, "Value is None")

        if unit is None or not unit.strip():
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=None,
                is_converted=False,
                conversion_note="Source temperature unit unknown; preserved without conversion.",
            )

        u = unit.strip().lower()
        if u in ("c", "celsius", "centigrade", "°c"):
            return UnitConversionResult(round(value, 2), "°C", value, unit, True)
        elif u in ("k", "kelvin"):
            return UnitConversionResult(round(value - 273.15, 2), "°C", value, unit, True)
        elif u in ("f", "fahrenheit", "°f"):
            return UnitConversionResult(round((value - 32.0) * 5.0 / 9.0, 2), "°C", value, unit, True)
        else:
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=unit,
                is_converted=False,
                conversion_note=f"Unrecognized temperature unit '{unit}'; preserved without conversion.",
            )

    # -------------------------------------------------------------------------
    # Weight Normalization -> kilograms (kg)
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_weight(
        cls,
        value: Optional[float],
        unit: Optional[str],
    ) -> UnitConversionResult:
        """Convert weight to kilograms (kg)."""
        if value is None:
            return UnitConversionResult(None, "kg", None, unit, False, "Value is None")

        if unit is None or not unit.strip():
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=None,
                is_converted=False,
                conversion_note="Source weight unit unknown; preserved without conversion.",
            )

        u = unit.strip().lower()
        if u in ("kg", "kilo", "kilogram", "kilograms"):
            return UnitConversionResult(round(value, 2), "kg", value, unit, True)
        elif u in ("lb", "lbs", "pound", "pounds"):
            return UnitConversionResult(round(value * 0.45359237, 2), "kg", value, unit, True)
        elif u in ("g", "gram", "grams"):
            return UnitConversionResult(round(value / 1000.0, 3), "kg", value, unit, True)
        elif u in ("t", "ton", "tons", "tonne", "tonnes", "metric_ton"):
            return UnitConversionResult(round(value * 1000.0, 2), "kg", value, unit, True)
        else:
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=unit,
                is_converted=False,
                conversion_note=f"Unrecognized weight unit '{unit}'; preserved without conversion.",
            )

    # -------------------------------------------------------------------------
    # Volume Normalization -> cubic meters (m³)
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_volume(
        cls,
        value: Optional[float],
        unit: Optional[str],
    ) -> UnitConversionResult:
        """Convert volume to cubic meters (m³)."""
        if value is None:
            return UnitConversionResult(None, "m³", None, unit, False, "Value is None")

        if unit is None or not unit.strip():
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=None,
                is_converted=False,
                conversion_note="Source volume unit unknown; preserved original without conversion.",
            )

        u = unit.strip().lower()
        if u in ("m3", "m³", "cbm", "cubic_meter", "cubic_meters"):
            return UnitConversionResult(round(value, 3), "m³", value, unit, True)
        elif u in ("l", "liter", "liters", "litre", "litres"):
            return UnitConversionResult(round(value / 1000.0, 3), "m³", value, unit, True)
        elif u in ("gal", "gallon", "gallons", "us_gal"):
            return UnitConversionResult(round(value * 0.00378541, 3), "m³", value, unit, True)
        elif u in ("cuft", "ft3", "ft³", "cubic_feet", "cubic_foot"):
            return UnitConversionResult(round(value * 0.0283168, 3), "m³", value, unit, True)
        else:
            return UnitConversionResult(
                normalized_value=value,
                target_unit="unknown",
                original_value=value,
                original_unit=unit,
                is_converted=False,
                conversion_note=f"Unrecognized volume unit '{unit}'; preserved without conversion.",
            )

    # -------------------------------------------------------------------------
    # Currency Normalization -> ISO 4217 Currency Representation
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_currency(
        cls,
        amount: Optional[float],
        currency: Optional[str],
    ) -> UnitConversionResult:
        """Standardize currency representation without fabricating FX conversion rates.

        Enforces strict unknown-FX policy: Never guess or invent exchange rates
        between currencies without an authoritative financial oracle.
        """
        if amount is None:
            return UnitConversionResult(None, "unknown", None, currency, False, "Amount is None")

        if currency is None or not currency.strip():
            return UnitConversionResult(
                normalized_value=amount,
                target_unit="unknown",
                original_value=amount,
                original_unit=None,
                is_converted=False,
                conversion_note="Source currency code unspecified; preserved without conversion.",
            )

        iso_code = currency.strip().upper()
        return UnitConversionResult(
            normalized_value=round(amount, 2),
            target_unit=iso_code,
            original_value=amount,
            original_unit=currency,
            is_converted=True,
            conversion_note="Standardized ISO-4217 currency; preserved without synthetic FX conversion.",
        )

    # -------------------------------------------------------------------------
    # Coordinate Bounds Normalization -> WGS84 Decimal Degrees
    # -------------------------------------------------------------------------
    @classmethod
    def normalize_coordinates(
        cls,
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Tuple[Optional[float], Optional[float]]:
        """Validate and normalize coordinates to standard WGS84 decimal degrees."""
        if latitude is not None:
            lat = float(latitude)
            if lat < -90.0 or lat > 90.0:
                raise ValueError(f"Latitude out of bounds [-90.0, +90.0]: {lat}")
            lat = round(lat, 6)
        else:
            lat = None

        if longitude is not None:
            lon = float(longitude)
            if lon < -180.0 or lon > 180.0:
                raise ValueError(f"Longitude out of bounds [-180.0, +180.0]: {lon}")
            lon = round(lon, 6)
        else:
            lon = None

        return lat, lon

