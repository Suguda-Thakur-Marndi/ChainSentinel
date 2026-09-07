"""Error hierarchy for external data ingestion and provider adapter operations."""
from __future__ import annotations

from typing import Any, Optional


class IngestionError(Exception):
    """Base exception for all external provider ingestion failures."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        retriable: bool = False,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.details = dict(details or {})
        self.details.update(extra)
        self.retriable = retriable

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "provider_name": self.provider_name,
            "retriable": self.retriable,
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
        super().__init__(message=message, provider_name=provider_name, details=details, retriable=False, **extra)


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
        super().__init__(message=msg, provider_name=resolved_name, details=details, retriable=False, **extra)


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
        super().__init__(message=msg, provider_name=resolved_name, details=details, retriable=False, **extra)


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
        super().__init__(message=message, provider_name=provider_name, details=merged_details, retriable=False)
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
        )
        self.retry_after_seconds = effective_retry_after
        self.retry_after = effective_retry_after


class ProviderTimeoutError(IngestionError):
    """Network connection or read timeout during provider communication. Retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(message=message, provider_name=provider_name, details=details, retriable=True, **extra)


class ProviderConnectionError(IngestionError):
    """DNS resolution, TCP connection drop, or network unreachable. Retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(message=message, provider_name=provider_name, details=details, retriable=True, **extra)


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
        # 502, 503, 504 are transient; 500 might be retriable
        retriable = status_code in (500, 502, 503, 504) if status_code else False
        super().__init__(
            message=message,
            provider_name=provider_name,
            details=merged_details,
            retriable=retriable,
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
        super().__init__(message=message, provider_name=provider_name, details=details, retriable=False, **extra)


class ProviderPermanentError(IngestionError):
    """Resource permanently removed (HTTP 404/410) or feature unsupported. Non-retriable."""

    def __init__(
        self,
        message: str,
        provider_name: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        super().__init__(message=message, provider_name=provider_name, details=details, retriable=False, **extra)


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
        )
        self.fingerprint = fingerprint
        self.existing_event_id = existing_event_id
