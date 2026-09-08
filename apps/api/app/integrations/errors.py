"""Error hierarchy for external data ingestion and provider adapter operations."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class FailureCategory(str, Enum):
    """Deterministic taxonomy of ingestion and external provider failure modes."""

    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    NORMALIZATION_ERROR = "NORMALIZATION_ERROR"
    IDEMPOTENCY_ERROR = "IDEMPOTENCY_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def classify_failure(exc: Exception) -> FailureCategory:
    """Deterministically map any exception to a standard FailureCategory.

    Preserves the original exception type and details while providing
    a consistent operational classification across all providers.
    """
    if exc is None:
        return FailureCategory.INTERNAL_ERROR

    # If exception already has an explicit category assigned
    if hasattr(exc, "failure_category") and getattr(exc, "failure_category") is not None:
        cat = getattr(exc, "failure_category")
        if isinstance(cat, FailureCategory):
            return cat
        if isinstance(cat, str) and cat in FailureCategory.__members__:
            return FailureCategory(cat)

    exc_name = exc.__class__.__name__

    # Circuit Breaker
    if exc_name == "CircuitBreakerOpenError":
        return FailureCategory.CIRCUIT_OPEN

    # Timeout
    if exc_name in ("ProviderTimeoutError", "TimeoutError", "ReadTimeout", "ConnectTimeout"):
        return FailureCategory.TIMEOUT
    if "timeout" in exc_name.lower() or "timeout" in str(exc).lower():
        return FailureCategory.TIMEOUT

    # Rate Limiting
    if exc_name in ("ProviderRateLimitError", "RateLimitExceededError"):
        return FailureCategory.RATE_LIMITED
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return FailureCategory.RATE_LIMITED

    # Authentication & Authorization
    if exc_name in ("ProviderAuthenticationError",):
        if status_code == 403:
            return FailureCategory.AUTHORIZATION
        return FailureCategory.AUTHENTICATION
    if status_code == 401:
        return FailureCategory.AUTHENTICATION
    if status_code == 403:
        return FailureCategory.AUTHORIZATION

    # Configuration
    if exc_name in ("ProviderConfigurationError",):
        return FailureCategory.CONFIGURATION_ERROR

    # Provider Availability
    if exc_name in ("ProviderDisabledError", "ProviderNotFoundError"):
        return FailureCategory.PROVIDER_UNAVAILABLE
    if status_code in (502, 503, 504):
        return FailureCategory.PROVIDER_UNAVAILABLE

    # Validation & Bad Request
    if exc_name in ("ProviderValidationError",):
        return FailureCategory.INVALID_REQUEST
    if status_code in (400, 422):
        return FailureCategory.INVALID_REQUEST

    # Transient Network
    if exc_name in ("ProviderConnectionError", "ConnectionError", "NetworkError", "ConnectError"):
        return FailureCategory.TRANSIENT_NETWORK
    if isinstance(exc, (ConnectionResetError, ConnectionRefusedError, BrokenPipeError)):
        return FailureCategory.TRANSIENT_NETWORK

    # Normalization & Parsing
    if exc_name in ("NormalizationError", "SchemaValidationError"):
        return FailureCategory.NORMALIZATION_ERROR

    # Idempotency & Duplication
    if exc_name in ("DuplicateEventError", "IdempotencyError"):
        return FailureCategory.IDEMPOTENCY_ERROR

    # Response format / Server errors
    if exc_name in ("ProviderResponseError", "DecodeError", "JSONDecodeError"):
        return FailureCategory.MALFORMED_RESPONSE

    return FailureCategory.INTERNAL_ERROR


class IngestionError(Exception):
    """Base exception for all external provider ingestion failures."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        retriable: bool = False,
        failure_category: Optional[FailureCategory] = None,
        original_exception: Optional[Exception] = None,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.details = dict(details or {})
        self.details.update(extra)
        self.retriable = retriable
        self.original_exception = original_exception
        if original_exception and not self.__cause__:
            self.__cause__ = original_exception
        self.failure_category: FailureCategory = failure_category or FailureCategory.INTERNAL_ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "provider_name": self.provider_name,
            "retriable": self.retriable,
            "failure_category": self.failure_category.value,
            "details": self.details,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        """Alias for safe serializable error dictionary."""
        return self.to_dict()


class ProviderConfigurationError(IngestionError):
    """Configuration syntax, missing required fields, or validation error."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=details,
            retriable=False,
            failure_category=FailureCategory.CONFIGURATION_ERROR,
            **extra,
        )


class ProviderNotFoundError(IngestionError):
    """Requested provider adapter is not registered in ProviderRegistry."""

    def __init__(
        self,
        message_or_name: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        resolved_name = provider_name or message_or_name
        msg = (
            message_or_name
            if ("not registered" in message_or_name or " " in message_or_name)
            else f"Provider '{resolved_name}' is not registered in ProviderRegistry."
        )
        super().__init__(
            message=msg,
            provider_name=resolved_name,
            details=details,
            retriable=False,
            failure_category=FailureCategory.PROVIDER_UNAVAILABLE,
            **extra,
        )


class ProviderDisabledError(IngestionError):
    """Provider adapter is configured but marked disabled."""

    def __init__(
        self,
        message_or_name: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        resolved_name = provider_name or message_or_name
        msg = (
            message_or_name
            if ("disabled" in message_or_name or " " in message_or_name)
            else f"Provider '{resolved_name}' is currently disabled."
        )
        super().__init__(
            message=msg,
            provider_name=resolved_name,
            details=details,
            retriable=False,
            failure_category=FailureCategory.PROVIDER_UNAVAILABLE,
            **extra,
        )


class ProviderAuthenticationError(IngestionError):
    """API key invalid, token expired, or unauthorized (HTTP 401/403). Non-retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        status_code: Optional[int] = 401,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        merged_details = dict(details or {})
        if status_code is not None:
            merged_details["status_code"] = status_code
        merged_details.update(extra)
        cat = FailureCategory.AUTHORIZATION if status_code == 403 else FailureCategory.AUTHENTICATION
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=merged_details,
            retriable=False,
            failure_category=cat,
        )
        self.status_code = status_code


class ProviderRateLimitError(IngestionError):
    """External API quota exhausted or rate limit hit (HTTP 429). Retriable with backoff."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        retry_after_seconds: Optional[float] = None,
        retry_after: Optional[float] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        effective_retry_after = retry_after_seconds if retry_after_seconds is not None else retry_after
        merged_details = dict(details or {})
        if effective_retry_after is not None:
            merged_details["retry_after_seconds"] = effective_retry_after
        merged_details.update(extra)
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=merged_details,
            retriable=True,
            failure_category=FailureCategory.RATE_LIMITED,
        )
        self.retry_after_seconds = effective_retry_after
        self.retry_after = effective_retry_after
        self.status_code = 429


class ProviderTimeoutError(IngestionError):
    """Network connection or read timeout during provider communication. Retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=details,
            retriable=True,
            failure_category=FailureCategory.TIMEOUT,
            **extra,
        )


class ProviderConnectionError(IngestionError):
    """DNS resolution, TCP connection drop, or network unreachable. Retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=details,
            retriable=True,
            failure_category=FailureCategory.TRANSIENT_NETWORK,
            **extra,
        )


class ProviderResponseError(IngestionError):
    """Provider returned unexpected HTTP 5xx or unparseable malformed payload."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        merged_details = dict(details or {})
        if status_code is not None:
            merged_details["status_code"] = status_code
        merged_details.update(extra)
        retriable = status_code in (500, 502, 503, 504) if status_code else False
        cat = FailureCategory.PROVIDER_UNAVAILABLE if status_code in (502, 503, 504) else FailureCategory.MALFORMED_RESPONSE
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=merged_details,
            retriable=retriable,
            failure_category=cat,
        )
        self.status_code = status_code


class ProviderValidationError(IngestionError):
    """Malformed request payload or illegal query parameter (HTTP 400/422). Non-retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=details,
            retriable=False,
            failure_category=FailureCategory.INVALID_REQUEST,
            **extra,
        )
        self.status_code = 400


class ProviderPermanentError(IngestionError):
    """Resource permanently removed (HTTP 404/410) or feature unsupported. Non-retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=details,
            retriable=False,
            failure_category=FailureCategory.INVALID_REQUEST,
            **extra,
        )


class DuplicateEventError(IngestionError):
    """Event fingerprint matches previously ingested event within deduplication TTL."""

    def __init__(
        self,
        fingerprint: str,
        provider_name: Optional[str] = None,
        existing_event_id: Optional[str] = None,
        **extra: Any,
    ) -> None:
        merged_details = {"fingerprint": fingerprint, "existing_event_id": existing_event_id}
        merged_details.update(extra)
        super().__init__(
            message=f"Duplicate event detected for fingerprint '{fingerprint}'.",
            provider_name=provider_name,
            details=merged_details,
            retriable=False,
            failure_category=FailureCategory.IDEMPOTENCY_ERROR,
        )
        self.fingerprint = fingerprint
        self.existing_event_id = existing_event_id


class NormalizationError(IngestionError):
    """Normalization or schema mapping failure for an external event payload."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        event_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        original_exception: Optional[Exception] = None,
        **extra: Any,
    ) -> None:
        merged_details = dict(details or {})
        if event_id:
            merged_details["event_id"] = event_id
        merged_details.update(extra)
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=merged_details,
            retriable=False,
            failure_category=FailureCategory.NORMALIZATION_ERROR,
            original_exception=original_exception,
        )
        self.event_id = event_id


class IdempotencyError(IngestionError):
    """Failure during idempotency evaluation or state recording."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=details,
            retriable=False,
            failure_category=FailureCategory.IDEMPOTENCY_ERROR,
            **extra,
        )
