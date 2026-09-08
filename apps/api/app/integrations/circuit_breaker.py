"""Provider-level circuit breaker implementation for external data ingestion.

Implements the standard state machine:
  CLOSED (normal operation)
    ↓ (failures >= failure_threshold)
  OPEN (fast-fail, no provider calls, cooldown period)
    ↓ (cooldown elapsed)
  HALF_OPEN (single probe permitted)
    ↓ (success -> CLOSED) or (failure -> OPEN)

Thread-safe and configurable per provider.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("riskwise.integrations.circuit_breaker")


class CircuitState(str, Enum):
    """Operational states of a provider circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerConfig(BaseModel):
    """Configuration options for provider circuit breaker."""

    model_config = ConfigDict(extra="allow")

    failure_threshold: int = Field(default=5, ge=1, le=100)
    cooldown_seconds: float = Field(default=30.0, ge=0.001, le=3600.0)
    success_threshold: int = Field(default=1, ge=1, le=10)


class CircuitBreakerOpenError(Exception):
    """Raised when an operation is attempted while the provider circuit is OPEN."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        cooldown_remaining: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.cooldown_remaining = cooldown_remaining
        self.retriable = False
        self.details = dict(details or {})
        if cooldown_remaining is not None:
            self.details["cooldown_remaining_seconds"] = round(cooldown_remaining, 2)
        if provider_name:
            self.details["provider_name"] = provider_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": "CircuitBreakerOpenError",
            "message": self.message,
            "provider_name": self.provider_name,
            "retriable": self.retriable,
            "cooldown_remaining": self.cooldown_remaining,
            "details": self.details,
        }

    def to_safe_dict(self) -> Dict[str, Any]:
        return self.to_dict()


class _ProviderCircuitState:
    """Internal state tracker for a single provider."""

    def __init__(self, config: CircuitBreakerConfig) -> None:
        self.config = config
        self.state: CircuitState = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change: float = time.monotonic()
        self.total_trips: int = 0


class ProviderCircuitBreaker:
    """Thread-safe circuit breaker managing failure states per external provider."""

    def __init__(self, default_config: Optional[CircuitBreakerConfig] = None) -> None:
        self.default_config = default_config or CircuitBreakerConfig()
        self._lock = threading.Lock()
        self._provider_configs: Dict[str, CircuitBreakerConfig] = {}
        self._states: Dict[str, _ProviderCircuitState] = {}

    def set_provider_config(self, provider_name: str, config: CircuitBreakerConfig) -> None:
        """Assign custom circuit breaker configuration for a specific provider."""
        key = provider_name.lower().strip()
        with self._lock:
            self._provider_configs[key] = config
            if key in self._states:
                self._states[key].config = config

    def _get_state_tracker(self, provider_name: str) -> _ProviderCircuitState:
        """Internal helper to get or create state tracker for a provider."""
        key = provider_name.lower().strip()
        if key not in self._states:
            cfg = self._provider_configs.get(key, self.default_config)
            self._states[key] = _ProviderCircuitState(config=cfg)
        return self._states[key]

    def get_state(self, provider_name: str) -> CircuitState:
        """Get current circuit state for a provider, evaluating cooldown expiration."""
        key = provider_name.lower().strip()
        now = time.monotonic()
        with self._lock:
            tracker = self._get_state_tracker(key)
            if tracker.state == CircuitState.OPEN:
                if (now - tracker.last_state_change) >= tracker.config.cooldown_seconds:
                    tracker.state = CircuitState.HALF_OPEN
                    tracker.last_state_change = now
                    tracker.consecutive_successes = 0
                    logger.info(
                        "Circuit breaker for provider '%s' transitioned from OPEN to HALF_OPEN",
                        key,
                    )
            return tracker.state

    def can_execute(self, provider_name: str) -> bool:
        """Check if an external call to provider is currently permitted.

        Returns:
            True if state is CLOSED or HALF_OPEN (probe).
            False if state is OPEN.
        """
        state = self.get_state(provider_name)
        return state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self, provider_name: str) -> None:
        """Record a successful provider call."""
        key = provider_name.lower().strip()
        now = time.monotonic()
        with self._lock:
            tracker = self._get_state_tracker(key)
            if tracker.state == CircuitState.HALF_OPEN:
                tracker.consecutive_successes += 1
                if tracker.consecutive_successes >= tracker.config.success_threshold:
                    tracker.state = CircuitState.CLOSED
                    tracker.consecutive_failures = 0
                    tracker.consecutive_successes = 0
                    tracker.last_state_change = now
                    logger.info(
                        "Circuit breaker for provider '%s' transitioned from HALF_OPEN to CLOSED (recovered)",
                        key,
                    )
            elif tracker.state == CircuitState.CLOSED:
                tracker.consecutive_failures = 0

    def record_failure(self, provider_name: str, exc: Optional[Exception] = None) -> None:
        """Record a provider call failure."""
        key = provider_name.lower().strip()
        now = time.monotonic()
        with self._lock:
            tracker = self._get_state_tracker(key)
            tracker.last_failure_time = now
            tracker.consecutive_failures += 1

            if tracker.state == CircuitState.HALF_OPEN:
                # Any failure in probe immediately trips back to OPEN
                tracker.state = CircuitState.OPEN
                tracker.last_state_change = now
                tracker.consecutive_successes = 0
                tracker.total_trips += 1
                logger.warning(
                    "Circuit breaker for provider '%s' probe failed, returned to OPEN (error: %s)",
                    key,
                    exc,
                )
            elif tracker.state == CircuitState.CLOSED:
                if tracker.consecutive_failures >= tracker.config.failure_threshold:
                    tracker.state = CircuitState.OPEN
                    tracker.last_state_change = now
                    tracker.total_trips += 1
                    logger.warning(
                        "Circuit breaker for provider '%s' TRIPPED from CLOSED to OPEN after %d consecutive failures (error: %s)",
                        key,
                        tracker.consecutive_failures,
                        exc,
                    )

    def get_status(self, provider_name: str) -> Dict[str, Any]:
        """Get diagnostic status dictionary for a provider's circuit breaker."""
        key = provider_name.lower().strip()
        now = time.monotonic()
        with self._lock:
            tracker = self._get_state_tracker(key)
            # Evaluate cooldown
            state = tracker.state
            cooldown_remaining = 0.0
            if state == CircuitState.OPEN:
                elapsed = now - tracker.last_state_change
                if elapsed >= tracker.config.cooldown_seconds:
                    state = CircuitState.HALF_OPEN
                    tracker.state = CircuitState.HALF_OPEN
                    tracker.last_state_change = now
                else:
                    cooldown_remaining = max(0.0, tracker.config.cooldown_seconds - elapsed)

            return {
                "provider_name": key,
                "state": state.value,
                "consecutive_failures": tracker.consecutive_failures,
                "consecutive_successes": tracker.consecutive_successes,
                "failure_threshold": tracker.config.failure_threshold,
                "cooldown_seconds": tracker.config.cooldown_seconds,
                "cooldown_remaining_seconds": round(cooldown_remaining, 2),
                "total_trips": tracker.total_trips,
            }

    def reset(self, provider_name: Optional[str] = None) -> None:
        """Reset circuit breaker state for a specific provider or all providers."""
        key = provider_name.lower().strip() if provider_name else None
        now = time.monotonic()
        with self._lock:
            if key:
                if key in self._states:
                    cfg = self._states[key].config
                    self._states[key] = _ProviderCircuitState(config=cfg)
            else:
                for k, tracker in self._states.items():
                    self._states[k] = _ProviderCircuitState(config=tracker.config)
