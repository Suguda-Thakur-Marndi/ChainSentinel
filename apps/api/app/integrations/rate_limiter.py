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
                    return False, wait_time

            # Check requests per hour
            if config.requests_per_hour is not None:
                q_hour = self._hour_windows.setdefault(provider_name, deque())
                while q_hour and (now - q_hour[0]) > 3600.0:
                    q_hour.popleft()

                if len(q_hour) >= config.requests_per_hour:
                    oldest = q_hour[0]
                    wait_time = max(0.1, 3600.0 - (now - oldest))
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
                return False

            if config is not None:
                if config.requests_per_minute is not None:
                    q_min = self._minute_windows.setdefault(provider_name, deque())
                    while q_min and (now - q_min[0]) > 60.0:
                        q_min.popleft()
                    if len(q_min) >= config.requests_per_minute:
                        return False

                if config.requests_per_hour is not None:
                    q_hour = self._hour_windows.setdefault(provider_name, deque())
                    while q_hour and (now - q_hour[0]) > 3600.0:
                        q_hour.popleft()
                    if len(q_hour) >= config.requests_per_hour:
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
        return duration

    def reset(self, provider_name: Optional[str] = None) -> None:
        """Reset rate limiter state for one or all providers."""
        with self._lock:
            if provider_name:
                self._minute_windows.pop(provider_name, None)
                self._hour_windows.pop(provider_name, None)
                self._cooldowns.pop(provider_name, None)
            else:
                self._minute_windows.clear()
                self._hour_windows.clear()
                self._cooldowns.clear()
