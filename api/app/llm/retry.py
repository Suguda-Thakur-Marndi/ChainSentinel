"""Configurable exponential backoff and retry policy for Bedrock LLM invocation.

Integrates with Phase 9 retry principles: retries ONLY explicitly retryable errors
(throttling, transient network faults, eligible timeouts) and strictly refuses to retry
authentication failures, authorization denials, validation errors, or security violations.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Optional

from app.llm.errors import is_retryable_llm_error


class LLMRetryPolicy:
    """Deterministic exponential backoff with bounded jitter for LLM calls."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 4.0,
        jitter: bool = True,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.max_retries = max(0, max_retries)
        self.base_delay_seconds = max(0.01, base_delay_seconds)
        self.max_delay_seconds = max(self.base_delay_seconds, max_delay_seconds)
        self.jitter = jitter
        self._sleep_fn = sleep_fn or time.sleep

    def compute_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay with bounded jitter."""
        if attempt <= 1:
            delay = self.base_delay_seconds
        else:
            delay = min(
                self.max_delay_seconds,
                self.base_delay_seconds * (2 ** (attempt - 1)),
            )

        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)

        return round(delay, 4)

    def is_retry_allowed(self, attempt: int, error: Exception) -> bool:
        """Check if an attempt can be retried under this policy.
        
        For attempt = 1 (initial attempt), retrying is allowed if max_retries >= 1.
        For attempt = max_retries, one further retry is still allowed.
        When attempt > max_retries, all retry budget is exhausted.
        """
        if attempt > self.max_retries:
            return False
        return is_retryable_llm_error(error)

    def sleep(self, delay: float) -> None:
        """Execute sleep delay."""
        if delay > 0:
            self._sleep_fn(delay)
