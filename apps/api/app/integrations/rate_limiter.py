"""Provider rate limiting abstraction.

Provides thread-safe in-memory rate limiting supporting sliding-window /
token-bucket semantics and provider-signaled Retry-After backoffs.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from app.integrations.config import RateLimitConfig


class ProviderRateLimiter:
    """Thread-safe rate limiter tracking per-provider request windows and cooldowns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # provider_name -> deque of monotonic timestamps for requests within the minute window
        self._minute_windows: Dict[str, Deque[float]] = {}
        # provider_name -> deque of monotonic timestamps for requests within the hour window
        self._hour_windows: Dict[str, Deque[float]] = {}
        # provider_name -> monotonic timestamp until which the provider is blocked (e.g. Retry-After)
        self._cooldowns: Dict[str, float] = {}
        # Observability stats
        self._total_throttled: Dict[str, int] = {}
        self._cooldown_counts: Dict[str, int] = {}

    def check_limit(
        self,
        provider_name: str,
        config: Optional[RateLimitConfig] = None,
    ) -> Tuple[bool, Optional[float]]:
        """Check if a request is permitted under rate limit and cooldown rules.

        Returns:
            (is_allowed, wait_seconds_needed). If allowed, wait_seconds_needed is None.
        """
        now = time.monotonic()

        with self._lock:
            # Check cooldown / Retry-After first
            cooldown_until = self._cooldowns.get(provider_name, 0.0)
            if now < cooldown_until:
                wait_time = cooldown_until - now
                self._total_throttled[provider_name] = self._total_throttled.get(provider_name, 0) + 1
                return False, wait_time

            if config is None:
                return True, None

            # Check requests per minute
            if config.requests_per_minute is not None:
                q_min = self._minute_windows.setdefault(provider_name, deque())
                while q_min and (now - q_min[0]) > 60.0:
                    q_min.popleft()

                if len(q_min) >= config.requests_per_minute:
                    oldest = q_min[0]
                    wait_time = max(0.1, 60.0 - (now - oldest))
                    self._total_throttled[provider_name] = self._total_throttled.get(provider_name, 0) + 1
                    return False, wait_time

            # Check requests per hour
            if config.requests_per_hour is not None:
                q_hour = self._hour_windows.setdefault(provider_name, deque())
                while q_hour and (now - q_hour[0]) > 3600.0:
                    q_hour.popleft()

                if len(q_hour) >= config.requests_per_hour:
                    oldest = q_hour[0]
                    wait_time = max(0.1, 3600.0 - (now - oldest))
                    self._total_throttled[provider_name] = self._total_throttled.get(provider_name, 0) + 1
                    return False, wait_time

            return True, None

    def acquire(
        self,
        provider_name: str,
        config: Optional[RateLimitConfig] = None,
    ) -> bool:
        """Attempt to acquire a request token.

        If allowed, records the request timestamp and returns True.
        If blocked, returns False without recording.
        """
        now = time.monotonic()

        with self._lock:
            cooldown_until = self._cooldowns.get(provider_name, 0.0)
            if now < cooldown_until:
                self._total_throttled[provider_name] = self._total_throttled.get(provider_name, 0) + 1
                return False

            if config is not None:
                if config.requests_per_minute is not None:
                    q_min = self._minute_windows.setdefault(provider_name, deque())
                    while q_min and (now - q_min[0]) > 60.0:
                        q_min.popleft()
                    if len(q_min) >= config.requests_per_minute:
                        self._total_throttled[provider_name] = self._total_throttled.get(provider_name, 0) + 1
                        return False

                if config.requests_per_hour is not None:
                    q_hour = self._hour_windows.setdefault(provider_name, deque())
                    while q_hour and (now - q_hour[0]) > 3600.0:
                        q_hour.popleft()
                    if len(q_hour) >= config.requests_per_hour:
                        self._total_throttled[provider_name] = self._total_throttled.get(provider_name, 0) + 1
                        return False

            # Record token usage
            if config and config.requests_per_minute is not None:
                self._minute_windows.setdefault(provider_name, deque()).append(now)
            if config and config.requests_per_hour is not None:
                self._hour_windows.setdefault(provider_name, deque()).append(now)

            return True

    def record_rate_limit(
        self,
        provider_name: str,
        retry_after: Optional[float] = None,
        default_cooldown: float = 60.0,
    ) -> float:
        """Record that a provider signaled rate limiting.

        Sets a cooldown until now + retry_after (or default_cooldown).
        Returns the duration of the cooldown in seconds.
        """
        duration = retry_after if retry_after is not None and retry_after > 0 else default_cooldown
        now = time.monotonic()
        with self._lock:
            self._cooldowns[provider_name] = now + duration
            self._cooldown_counts[provider_name] = self._cooldown_counts.get(provider_name, 0) + 1
        return duration

    def get_provider_status(self, provider_name: str) -> Dict[str, Any]:
        """Return safe diagnostic status of the rate limiter for a provider."""
        now = time.monotonic()
        with self._lock:
            cooldown_until = self._cooldowns.get(provider_name, 0.0)
            is_cooling_down = now < cooldown_until
            cooldown_remaining = max(0.0, cooldown_until - now) if is_cooling_down else 0.0
            minute_count = len(self._minute_windows.get(provider_name, []))
            hour_count = len(self._hour_windows.get(provider_name, []))
            throttled = self._total_throttled.get(provider_name, 0)
            cooldown_events = self._cooldown_counts.get(provider_name, 0)

            return {
                "provider_name": provider_name,
                "is_cooling_down": is_cooling_down,
                "cooldown_remaining_seconds": round(cooldown_remaining, 2),
                "minute_window_count": minute_count,
                "hour_window_count": hour_count,
                "total_throttled_requests": throttled,
                "total_cooldown_events": cooldown_events,
            }

    def reset(self, provider_name: Optional[str] = None) -> None:
        """Reset rate limiter state for one or all providers."""
        with self._lock:
            if provider_name:
                self._minute_windows.pop(provider_name, None)
                self._hour_windows.pop(provider_name, None)
                self._cooldowns.pop(provider_name, None)
                self._total_throttled.pop(provider_name, None)
                self._cooldown_counts.pop(provider_name, None)
            else:
                self._minute_windows.clear()
                self._hour_windows.clear()
                self._cooldowns.clear()
                self._total_throttled.clear()
                self._cooldown_counts.clear()
