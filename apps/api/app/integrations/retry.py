"""Bounded exponential backoff retry policy with jitter and Retry-After support."""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Optional, TypeVar

from app.integrations.config import RetryConfig
from app.integrations.errors import (
    DuplicateEventError,
    IngestionError,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderDisabledError,
    ProviderPermanentError,
    ProviderRateLimitError,
    ProviderValidationError,
)

logger = logging.getLogger("riskwise.ingestion.retry")

T = TypeVar("T")


class RetryPolicy:
    """Safe, bounded retry policy respecting transient vs permanent failure boundaries."""

    _NON_RETRIABLE_TYPES = (
        ProviderAuthenticationError,
        ProviderValidationError,
        ProviderPermanentError,
        ProviderConfigurationError,
        ProviderDisabledError,
        DuplicateEventError,
    )

    def __init__(self, config: Optional[RetryConfig] = None) -> None:
        self.config = config or RetryConfig()

    @classmethod
    def is_retriable(cls, exc: Exception) -> bool:
        """Evaluate whether an exception qualifies for transient retry."""
        if isinstance(exc, cls._NON_RETRIABLE_TYPES):
            return False

        if isinstance(exc, IngestionError):
            return exc.retriable

        # Standard library networking / OS exceptions
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True

        return False

    @classmethod
    def compute_delay(
        cls,
        attempt: int,
        config: RetryConfig,
        retry_after: Optional[float] = None,
    ) -> float:
        """Calculate next backoff duration with optional Retry-After and jitter."""
        if retry_after is not None and retry_after > 0:
            return min(retry_after, config.max_delay_seconds)

        base_delay = config.initial_delay_seconds * (config.backoff_factor ** attempt)
        clamped_delay = min(base_delay, config.max_delay_seconds)

        if config.jitter:
            # Full jitter: random uniform between [0.75 * clamped_delay, 1.25 * clamped_delay]
            jitter_min = clamped_delay * 0.75
            jitter_max = clamped_delay * 1.25
            return random.uniform(jitter_min, jitter_max)

        return clamped_delay

    def execute(
        self,
        operation: Callable[[], T],
        on_retry: Optional[Callable[[int, float, Exception], None]] = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> T:
        """Execute a callable with bounded exponential retry using instance config."""
        retries = 0
        while True:
            try:
                return operation()
            except Exception as exc:
                if not self.is_retriable(exc) or retries >= self.config.max_retries:
                    raise exc

                retry_after = getattr(exc, "retry_after_seconds", None)
                if retry_after is None:
                    retry_after = getattr(exc, "retry_after", None)

                delay = self.compute_delay(
                    attempt=retries,
                    config=self.config,
                    retry_after=retry_after,
                )

                if on_retry:
                    on_retry(retries + 1, delay, exc)

                sleep_func(delay)
                retries += 1

    @classmethod
    def execute_with_retry(
        cls,
        operation: Callable[[], T],
        config: RetryConfig,
        provider_name: str = "provider",
        correlation_id: Optional[str] = None,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> tuple[T, int]:
        """Execute a callable with bounded exponential retry.

        Returns:
            tuple[T, int]: (operation_result, total_retries_executed)
        """
        policy = cls(config=config)
        retries_count = [0]

        def _on_retry(att: int, delay: float, exc: Exception) -> None:
            retries_count[0] = att
            logger.info(
                "Transient error in provider '%s'; retrying in %.2fs (attempt %d/%d, error=%s, correlation_id=%s)",
                provider_name,
                delay,
                att,
                config.max_retries,
                type(exc).__name__,
                correlation_id,
            )

        res = policy.execute(operation, on_retry=_on_retry, sleep_func=sleep_func)
        return res, retries_count[0]
