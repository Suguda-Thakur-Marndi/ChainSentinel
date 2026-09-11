"""Provider configuration, authentication definitions, and secure runtime secret resolution."""
from __future__ import annotations

from enum import Enum
import os
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.integrations.base import ProviderType


class AuthMode(str, Enum):
    """Supported authentication mechanisms for external providers."""
    NONE = "NONE"
    API_KEY_HEADER = "API_KEY_HEADER"
    API_KEY_QUERY = "API_KEY_QUERY"
    BEARER_TOKEN = "BEARER_TOKEN"
    OAUTH2 = "OAUTH2"
    BASIC_AUTH = "BASIC_AUTH"


class RetryConfig(BaseModel):
    """Configuration for bounded exponential backoff retry policy."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    max_retries: int = Field(default=3, ge=0, le=10)
    initial_delay_seconds: float = Field(default=0.5, ge=0.001, le=60.0)
    max_delay_seconds: float = Field(default=10.0, ge=0.01, le=300.0)
    backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0)
    jitter: bool = True

    @model_validator(mode="before")
    @classmethod
    def handle_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "initial_backoff_seconds" in data and "initial_delay_seconds" not in data:
                data["initial_delay_seconds"] = data.pop("initial_backoff_seconds")
            if "backoff_multiplier" in data and "backoff_factor" not in data:
                data["backoff_factor"] = data.pop("backoff_multiplier")
        return data


class RateLimitConfig(BaseModel):
    """Configuration for client-side rate-limiting and quota bounds."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    requests_per_minute: Optional[int] = Field(default=60, ge=1, le=10000)
    requests_per_hour: Optional[int] = Field(None, ge=1, le=500000)
    burst_limit: Optional[int] = Field(None, ge=1, le=1000)


class ProviderConfig(BaseModel):
    """Strongly typed configuration for an external signal provider."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    provider_name: str = Field(..., min_length=1, max_length=100)
    provider_type: ProviderType
    enabled: bool = True
    base_url: Optional[str] = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=120.0)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    polling_interval_seconds: Optional[int] = Field(None, ge=5, le=86400)
    auth_mode: AuthMode = AuthMode.NONE
    secret_ref: Optional[str] = None  # Reference pointer to secret (e.g. 'env:TOMTOM_API_KEY')
    extra_settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def handle_config_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "retry_config" in data and "retry" not in data:
                data["retry"] = data.pop("retry_config")
            if "rate_limit_config" in data and "rate_limit" not in data:
                data["rate_limit"] = data.pop("rate_limit_config")
        return data

    @property
    def retry_config(self) -> RetryConfig:
        return self.retry

    @property
    def rate_limit_config(self) -> RateLimitConfig:
        return self.rate_limit


class SecretResolver:
    """Secure runtime resolver for external provider credentials.

    CRITICAL SECURITY MANDATE:
    Never stores or persists API keys, secrets, or tokens in source code,
    configuration objects, or database records. Resolves secrets via
    secure references at runtime from environment variables or AWS Secrets Manager.
    """

    _SENSITIVE_PATTERNS = re.compile(
        r"(api[_-]?key|secret|token|password|auth|credential)", re.IGNORECASE
    )

    @classmethod
    def resolve_secret(cls, secret_ref: Optional[str], default: Optional[str] = None) -> Optional[str]:
        """Resolve a secret value at runtime given a reference identifier.

        Supported reference schemes:
        - 'env:VAR_NAME': Lookup from os.environ
        - 'VAR_NAME': Direct environment variable name fallback
        - None: returns default
        """
        if not secret_ref:
            return default

        if secret_ref.startswith("env:"):
            env_var = secret_ref[4:]
            return os.environ.get(env_var, default)

        # Direct env var lookup if present
        if secret_ref in os.environ:
            return os.environ[secret_ref]

        return default

    def resolve(self, secret_ref: Optional[str], default: Optional[str] = None) -> Optional[str]:
        """Instance method alias for resolve_secret."""
        return self.resolve_secret(secret_ref, default)

    @classmethod
    def sanitize_payload(cls, data: Any) -> Any:
        """Deeply sanitize dictionaries/lists to remove any sensitive keys or credentials."""
        if isinstance(data, dict):
            sanitized: dict[str, Any] = {}
            for k, v in data.items():
                if cls._SENSITIVE_PATTERNS.search(str(k)):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = cls.sanitize_payload(v)
            return sanitized
        elif isinstance(data, list):
            return [cls.sanitize_payload(item) for item in data]
        return data
