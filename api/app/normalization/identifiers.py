"""Deterministic, namespace-aware identifier normalization for Phase 6 Step 3.

Provides safe identifier cleanup, canonical formatting, and strict namespace isolation
for maritime, aviation, logistics, and supply chain entity identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class NormalizedIdentifier:
    """Encapsulates a normalized identifier with its namespace, type, and validity status."""

    raw_value: str
    normalized_value: str
    namespace: str
    identifier_type: str
    is_valid: bool
    validation_error: Optional[str] = None

    @property
    def qualified_key(self) -> str:
        """Globally unambiguous identifier key incorporating namespace and type."""
        return f"{self.namespace.upper()}:{self.identifier_type.upper()}:{self.normalized_value}"


class IdentifierNormalizer:
    """Deterministic normalizer for external entity identifiers."""

    _IMO_PATTERN = re.compile(r"^\d{7}$")
    _MMSI_PATTERN = re.compile(r"^\d{9}$")
    _ICAO24_PATTERN = re.compile(r"^[0-9a-fA-F]{6}$")
    _UNLOCODE_PATTERN = re.compile(r"^[A-Za-z]{2}[A-Za-z0-9]{3}$")
    _CALLSIGN_PATTERN = re.compile(r"^[A-Za-z0-9\-_]{2,10}$")

    @classmethod
    def normalize_imo(cls, raw: Optional[str]) -> NormalizedIdentifier:
        """Normalize an International Maritime Organization (IMO) ship number.

        Rules:
        - Trim whitespace.
        - Strip optional case-insensitive 'IMO' prefix and separators.
        - Validate exact 7-digit requirement.
        - Preserve raw identifier.
        """
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace="MARITIME",
                identifier_type="IMO",
                is_valid=False,
                validation_error="Empty or non-string IMO identifier",
            )

        trimmed = raw.strip()
        cleaned = trimmed
        if cleaned.upper().startswith("IMO"):
            cleaned = cleaned[3:].strip()
        # Remove common separators like space or hyphen
        cleaned = cleaned.replace("-", "").replace(" ", "")

        is_valid = bool(cls._IMO_PATTERN.match(cleaned))
        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=cleaned if is_valid else trimmed,
            namespace="MARITIME",
            identifier_type="IMO",
            is_valid=is_valid,
            validation_error=None if is_valid else f"IMO must be exactly 7 digits, got '{cleaned}'",
        )

    @classmethod
    def normalize_mmsi(cls, raw: Optional[str]) -> NormalizedIdentifier:
        """Normalize a Maritime Mobile Service Identity (MMSI) number.

        Rules:
        - Trim whitespace.
        - Validate exact 9-digit requirement.
        - Preserve raw identifier.
        """
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace="MARITIME",
                identifier_type="MMSI",
                is_valid=False,
                validation_error="Empty or non-string MMSI identifier",
            )

        trimmed = raw.strip()
        cleaned = trimmed.replace("-", "").replace(" ", "")
        is_valid = bool(cls._MMSI_PATTERN.match(cleaned))

        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=cleaned if is_valid else trimmed,
            namespace="MARITIME",
            identifier_type="MMSI",
            is_valid=is_valid,
            validation_error=None if is_valid else f"MMSI must be exactly 9 digits, got '{cleaned}'",
        )

    @classmethod
    def normalize_icao24(cls, raw: Optional[str]) -> NormalizedIdentifier:
        """Normalize an ICAO 24-bit aircraft transponder address.

        Rules:
        - Trim whitespace.
        - Normalize to lowercase hexadecimal (RFC standard for ICAO24).
        - Validate exact 6 hex characters.
        - Preserve raw identifier.
        """
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace="AVIATION",
                identifier_type="ICAO24",
                is_valid=False,
                validation_error="Empty or non-string ICAO24 identifier",
            )

        trimmed = raw.strip()
        is_valid = bool(cls._ICAO24_PATTERN.match(trimmed))
        cleaned = trimmed.lower() if is_valid else trimmed

        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=cleaned,
            namespace="AVIATION",
            identifier_type="ICAO24",
            is_valid=is_valid,
            validation_error=None if is_valid else f"ICAO24 must be 6 hexadecimal characters, got '{trimmed}'",
        )

    @classmethod
    def normalize_callsign(cls, raw: Optional[str], namespace: str = "AVIATION") -> NormalizedIdentifier:
        """Normalize an aviation or maritime radio call sign.

        Rules:
        - Trim whitespace.
        - Uppercase alphanumeric representation.
        - Preserve raw identifier.
        """
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace=namespace.upper(),
                identifier_type="CALLSIGN",
                is_valid=False,
                validation_error="Empty or non-string callsign",
            )

        trimmed = raw.strip()
        cleaned = trimmed.upper()
        is_valid = bool(cls._CALLSIGN_PATTERN.match(cleaned))

        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=cleaned if is_valid else trimmed,
            namespace=namespace.upper(),
            identifier_type="CALLSIGN",
            is_valid=is_valid,
            validation_error=None if is_valid else f"Malformed callsign format: '{trimmed}'",
        )

    @classmethod
    def normalize_unlocode(cls, raw: Optional[str]) -> NormalizedIdentifier:
        """Normalize a UN/LOCODE (United Nations Code for Trade and Transport Locations).

        Rules:
        - Trim whitespace and remove internal spaces/hyphens.
        - Uppercase 5-character string (2-letter country + 3-character location).
        - Preserve raw identifier.
        """
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace="PORT",
                identifier_type="UNLOCODE",
                is_valid=False,
                validation_error="Empty or non-string UN/LOCODE",
            )

        trimmed = raw.strip()
        cleaned = trimmed.replace(" ", "").replace("-", "").upper()
        is_valid = bool(cls._UNLOCODE_PATTERN.match(cleaned))

        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=cleaned if is_valid else trimmed,
            namespace="PORT",
            identifier_type="UNLOCODE",
            is_valid=is_valid,
            validation_error=None if is_valid else f"UN/LOCODE must be 5 alphanumeric characters (2 country + 3 location), got '{trimmed}'",
        )

    @classmethod
    def normalize_tracking_number(cls, raw: Optional[str], carrier_namespace: Optional[str] = None) -> NormalizedIdentifier:
        """Normalize a carrier shipment tracking number.

        Rules:
        - Trim whitespace.
        - Namespace must reflect the specific carrier (e.g. 'FEDEX', 'UPS', 'DHL').
        - Does NOT arbitrarily strip special characters (e.g. hyphens, leading zeroes).
        - Preserves exact raw identifier.
        """
        namespace = (carrier_namespace or "LOGISTICS").upper()
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace=namespace,
                identifier_type="TRACKING_NUMBER",
                is_valid=False,
                validation_error="Empty or non-string tracking number",
            )

        trimmed = raw.strip()
        is_valid = len(trimmed) >= 3
        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=trimmed,
            namespace=namespace,
            identifier_type="TRACKING_NUMBER",
            is_valid=is_valid,
            validation_error=None if is_valid else "Tracking number too short",
        )

    @classmethod
    def normalize_generic(
        cls,
        raw: Optional[str],
        namespace: str,
        identifier_type: str,
    ) -> NormalizedIdentifier:
        """Safely normalize a generic external identifier without arbitrary character stripping."""
        ns = (namespace or "GENERIC").upper()
        itype = (identifier_type or "EXTERNAL").upper()
        if not raw or not isinstance(raw, str):
            return NormalizedIdentifier(
                raw_value=str(raw or ""),
                normalized_value="",
                namespace=ns,
                identifier_type=itype,
                is_valid=False,
                validation_error="Empty or non-string identifier",
            )

        trimmed = raw.strip()
        return NormalizedIdentifier(
            raw_value=trimmed,
            normalized_value=trimmed,
            namespace=ns,
            identifier_type=itype,
            is_valid=bool(trimmed),
            validation_error=None if trimmed else "Empty identifier after trimming",
        )
