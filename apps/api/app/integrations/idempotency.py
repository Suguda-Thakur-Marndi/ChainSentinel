"""Idempotency engine and deterministic SHA-256 fingerprinting for external signal deduplication."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Any, Optional, Union


class IdempotencyEngine:
    """Thread-safe event deduplication engine using deterministic payload fingerprinting."""

    def __init__(self, ttl_seconds: int = 86400, default_ttl_seconds: Optional[int] = None) -> None:
        self.default_ttl_seconds = default_ttl_seconds or ttl_seconds
        self._lock = threading.Lock()
        # Storage format: fingerprint -> (expires_at_timestamp, event_id)
        self._seen: dict[str, tuple[float, Optional[str]]] = {}

    @classmethod
    def canonical_json(cls, data: Any) -> str:
        """Produce deterministic, sorted JSON representation for hashing."""
        def default_serializer(o: Any) -> str:
            if isinstance(o, datetime):
                return o.isoformat()
            return str(o)

        return json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            default=default_serializer,
            ensure_ascii=True,
        )

    @classmethod
    def compute_fingerprint(
        cls,
        event_or_provider: Any,
        provider_event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        source_timestamp: Optional[datetime] = None,
        organization_id: Optional[str] = None,
    ) -> str:
        """Compute a collision-resistant SHA-256 fingerprint.

        Supports either a RawEvent object or individual components.
        1. Primary: If provider_event_id is present, uses provider + provider_event_id.
        2. Fallback: If no event ID is provided, hashes provider + source_timestamp + canonical payload.
        """
        # If first argument is a RawEvent or object with event fields
        if hasattr(event_or_provider, "provider_name"):
            provider = getattr(event_or_provider, "provider_name")
            p_event_id = getattr(event_or_provider, "provider_event_id", None)
            raw_data = getattr(event_or_provider, "raw_payload", {})
            s_ts = getattr(event_or_provider, "source_timestamp", None)
            org = organization_id or getattr(event_or_provider, "organization_id", None) or getattr(event_or_provider, "org_id", None)
        else:
            provider = str(event_or_provider)
            p_event_id = provider_event_id
            raw_data = payload or {}
            s_ts = source_timestamp
            org = organization_id

        provider_clean = provider.lower().strip() if provider else "unknown"

        if p_event_id is not None and str(p_event_id).strip():
            raw_key = f"{provider_clean}:event_id:{str(p_event_id).strip()}"
        else:
            ts_str = s_ts.isoformat() if s_ts else ""
            canon = cls.canonical_json(raw_data)
            raw_key = f"{provider_clean}:ts:{ts_str}:payload:{canon}"

        if org:
            raw_key = f"org:{org}:{raw_key}"

        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def check_and_record(
        self,
        event_or_provider: Any,
        provider_event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        source_timestamp: Optional[datetime] = None,
        event_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        organization_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Verify if event has been seen. If new, records it in the deduplication ledger.

        Returns:
            tuple[bool, str]: (is_unique, fingerprint)
            is_unique is True if this is a fresh new event, False if duplicate.
        """
        fingerprint = self.compute_fingerprint(
            event_or_provider=event_or_provider,
            provider_event_id=provider_event_id,
            payload=payload,
            source_timestamp=source_timestamp,
            organization_id=organization_id,
        )

        internal_id = event_id
        if hasattr(event_or_provider, "event_id"):
            internal_id = getattr(event_or_provider, "event_id")

        now = datetime.now(timezone.utc).timestamp()
        ttl = ttl_seconds or self.default_ttl_seconds

        with self._lock:
            if fingerprint in self._seen:
                expires_at, _ = self._seen[fingerprint]
                if now < expires_at:
                    return False, fingerprint  # Is duplicate, not unique

            # Record new entry
            self._seen[fingerprint] = (now + ttl, internal_id)
            return True, fingerprint  # Is unique

    def is_duplicate(self, fingerprint: str) -> bool:
        """Check if a computed fingerprint is currently active in the deduplication store."""
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            if fingerprint in self._seen:
                expires_at, _ = self._seen[fingerprint]
                return now < expires_at
            return False

    def purge_expired(self) -> int:
        """Clean up expired entries to prevent memory growth."""
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            expired_keys = [k for k, (exp, _) in self._seen.items() if now >= exp]
            for k in expired_keys:
                del self._seen[k]
            return len(expired_keys)

    def clear(self) -> None:
        """Clear all entries (useful for test isolation)."""
        with self._lock:
            self._seen.clear()
