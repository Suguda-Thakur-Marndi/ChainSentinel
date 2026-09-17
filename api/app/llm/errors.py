"""Deterministic error taxonomy and exception hierarchy for LLM / Bedrock integration.

Integrates with Phase 9 error classification (RETRYABLE vs NON_RETRYABLE) and FastAPI
AppError envelopes, guaranteeing that credential leakage, security violations, and
invalid requests fail closed immediately.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Dict, Optional
from fastapi import status

from app.core.errors import AppError


class ErrorClassification(str, Enum):
    """Classification of error determining automatic recovery eligibility."""

    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"


class LLMErrorCategory(str, Enum):
    """Deterministic error categories for LLM provider operations and telemetry."""

    LLM_VALIDATION_ERROR = "LLM_VALIDATION_ERROR"
    LLM_AUTHENTICATION_ERROR = "LLM_AUTHENTICATION_ERROR"
    LLM_AUTHORIZATION_ERROR = "LLM_AUTHORIZATION_ERROR"
    LLM_THROTTLING_ERROR = "LLM_THROTTLING_ERROR"
    LLM_TIMEOUT_ERROR = "LLM_TIMEOUT_ERROR"
    LLM_TRANSIENT_ERROR = "LLM_TRANSIENT_ERROR"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_RESPONSE_ERROR = "LLM_RESPONSE_ERROR"
    LLM_CONFIGURATION_ERROR = "LLM_CONFIGURATION_ERROR"


# Categories strictly never eligible for automatic retries
NON_RETRYABLE_LLM_CATEGORIES = frozenset({
    LLMErrorCategory.LLM_VALIDATION_ERROR,
    LLMErrorCategory.LLM_AUTHENTICATION_ERROR,
    LLMErrorCategory.LLM_AUTHORIZATION_ERROR,
    LLMErrorCategory.LLM_CONFIGURATION_ERROR,
    LLMErrorCategory.LLM_RESPONSE_ERROR,
    LLMErrorCategory.LLM_PROVIDER_ERROR,
})

# Secret redaction patterns to prevent leaking credentials in error messages
CREDENTIAL_SCRUB_PATTERNS = [
    re.compile(r"aws_access_key_id[=:\s]+[A-Z0-9]{16,32}", re.IGNORECASE),
    re.compile(r"aws_secret_access_key[=:\s]+[A-Za-z0-9/+=]{30,}", re.IGNORECASE),
    re.compile(r"aws_session_token[=:\s]+[A-Za-z0-9/+=]{50,}", re.IGNORECASE),
    re.compile(r"(AIzaSy[A-Za-z0-9_-]{33})", re.IGNORECASE),
    re.compile(r"(sk-[a-zA-Z0-9_-]{10,})", re.IGNORECASE),
    re.compile(r"(bearer\s+[a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(r"((?:gemini|google)?_?api_key[=:\s]+['\"]?[A-Za-z0-9_-]{20,}['\"]?)", re.IGNORECASE),
]


def sanitize_error_message(message: str) -> str:
    """Strip any AWS credentials, authorization tokens, or secrets from error text."""
    if not message:
        return ""
    sanitized = message
    for pattern in CREDENTIAL_SCRUB_PATTERNS:
        sanitized = pattern.sub("[REDACTED_CREDENTIAL]", sanitized)
    return sanitized


class LLMBaseError(AppError):
    """Base exception for all LLM and Bedrock operations."""

    def __init__(
        self,
        message: str,
        category: LLMErrorCategory,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        code: str = "LLM_ERROR",
        public_message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        clean_message = sanitize_error_message(message)
        super().__init__(
            message=clean_message,
            status_code=status_code,
            code=code,
            details=details,
        )
        self.category = category
        self.classification = classification
        self.public_message = public_message or "An internal error occurred during LLM operation."

    @property
    def retryable(self) -> bool:
        if self.category in NON_RETRYABLE_LLM_CATEGORIES:
            return False
        return self.classification == ErrorClassification.RETRYABLE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.code,
            "category": self.category.value,
            "message": self.message,
            "public_message": self.public_message,
            "classification": self.classification.value,
            "retryable": self.retryable,
            "status_code": self.status_code,
            "details": self.details,
        }


class LLMValidationError(LLMBaseError):
    """Raised when request structure, messages, tokens, or model parameters fail validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_VALIDATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_VALIDATION_ERROR,
            classification=ErrorClassification.NON_RETRYABLE,
            status_code=status.HTTP_400_BAD_REQUEST,
            code=code,
            public_message=public_message or "LLM request validation failed.",
            details=details,
        )


class LLMAuthenticationError(LLMBaseError):
    """Raised when AWS credentials or IAM authentication fails. Never retry automatically."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_AUTHENTICATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_AUTHENTICATION_ERROR,
            classification=ErrorClassification.NON_RETRYABLE,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=code,
            public_message=public_message or "LLM provider authentication failed.",
            details=details,
        )


class LLMAuthorizationError(LLMBaseError):
    """Raised on IAM permissions denial (AccessDeniedException) or model access restriction."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_AUTHORIZATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_AUTHORIZATION_ERROR,
            classification=ErrorClassification.NON_RETRYABLE,
            status_code=status.HTTP_403_FORBIDDEN,
            code=code,
            public_message=public_message or "Caller lacks authorization for requested LLM model.",
            details=details,
        )


class LLMThrottlingError(LLMBaseError):
    """Raised when Bedrock rate limits or provisioned throughput are exceeded. Safely retryable."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_THROTTLING_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_THROTTLING_ERROR,
            classification=ErrorClassification.RETRYABLE,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code=code,
            public_message=public_message or "LLM rate limit or throughput quota exceeded.",
            details=details,
        )


class LLMTimeoutError(LLMBaseError):
    """Raised when external Bedrock call exceeds configured bounded timeout. Safely retryable."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_TIMEOUT_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_TIMEOUT_ERROR,
            classification=ErrorClassification.RETRYABLE,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            code=code,
            public_message=public_message or "LLM provider operation timed out.",
            details=details,
        )


class LLMTransientError(LLMBaseError):
    """Raised on temporary network drops, connection resets, or 503 service unavailabilities."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_TRANSIENT_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_TRANSIENT_ERROR,
            classification=ErrorClassification.RETRYABLE,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=code,
            public_message=public_message or "A temporary transient provider error occurred.",
            details=details,
        )


class LLMProviderError(LLMBaseError):
    """Raised when Bedrock returns unhandled server-side errors or model not found."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_PROVIDER_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_PROVIDER_ERROR,
            classification=ErrorClassification.NON_RETRYABLE,
            status_code=status.HTTP_502_BAD_GATEWAY,
            code=code,
            public_message=public_message or "Upstream LLM provider returned an unrecoverable failure.",
            details=details,
        )


class LLMResponseError(LLMBaseError):
    """Raised when provider returns an unparseable or corrupted response payload."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_RESPONSE_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_RESPONSE_ERROR,
            classification=ErrorClassification.NON_RETRYABLE,
            status_code=status.HTTP_502_BAD_GATEWAY,
            code=code,
            public_message=public_message or "Failed to parse provider response payload.",
            details=details,
        )


class LLMConfigurationError(LLMBaseError):
    """Raised when model ID is disallowed or LLM settings are missing/invalid."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "LLM_CONFIGURATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            category=LLMErrorCategory.LLM_CONFIGURATION_ERROR,
            classification=ErrorClassification.NON_RETRYABLE,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code=code,
            public_message=public_message or "LLM provider configuration error.",
            details=details,
        )


# ==============================================================================
# PHASE 10 STEP 2: PROMPT & INVOCATION ERROR TAXONOMY
# ==============================================================================

class PromptValidationError(LLMValidationError):
    """Raised when a ClaudePrompt or PromptBuilder fails structural validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "PROMPT_VALIDATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "Prompt validation failed.",
        )


class PromptInjectionDetectedError(LLMValidationError):
    """Raised when hostile prompt injection or delimiter override directives are detected."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "PROMPT_INJECTION_DETECTED",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "Adversarial prompt injection pattern detected.",
        )


class PromptBudgetExceededError(LLMValidationError):
    """Raised when prompt characters, context size, or token request exceed configured limits."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "PROMPT_BUDGET_EXCEEDED",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "Prompt size exceeds configured budget limit.",
        )


class MessageContractError(LLMValidationError):
    """Raised when conversational message roles or turn sequences violate Bedrock/Claude contracts."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "MESSAGE_CONTRACT_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "Invalid conversational message sequence or role.",
        )


class StructuredOutputValidationError(LLMResponseError):
    """Raised when LLM completion fails JSON decoding or Pydantic schema validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "STRUCTURED_OUTPUT_VALIDATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "LLM response failed structured output schema validation.",
        )


class InvocationConfigurationError(LLMConfigurationError):
    """Raised when invocation parameters, model options, or budget profiles are misconfigured."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "INVOCATION_CONFIGURATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "Invalid Claude invocation service configuration.",
        )


class InvocationResponseError(LLMResponseError):
    """Raised when the provider response envelope is corrupt, missing, or truncated."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        code: str = "INVOCATION_RESPONSE_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            code=code,
            public_message=public_message or "Corrupted or unexpected provider response envelope.",
        )


def map_boto_exception(exc: Exception) -> LLMBaseError:
    """Deterministically map boto3/botocore exceptions to the RiskWise LLM error taxonomy.
    
    Ensures raw exceptions are never exposed to clients, and scrubs all credentials.
    """
    if isinstance(exc, LLMBaseError):
        return exc

    exc_str = sanitize_error_message(str(exc))
    exc_type = exc.__class__.__name__

    # Check for botocore ClientError
    error_code = ""
    http_status = 500
    if hasattr(exc, "response") and isinstance(exc.response, dict):
        err_dict = exc.response.get("Error", {})
        error_code = str(err_dict.get("Code", "")).strip()
        http_status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500))

    # 1. Throttling
    if (
        error_code in {
            "ThrottlingException",
            "RequestLimitExceeded",
            "TooManyRequestsException",
            "ProvisionedThroughputExceededException",
        }
        or http_status == 429
        or "throttling" in exc_str.lower()
        or "rate limit" in exc_str.lower()
    ):
        return LLMThrottlingError(
            message=f"Bedrock throttling encountered: {exc_str}",
            details={"aws_error_code": error_code, "status_code": http_status},
        )

    # 2. Authorization / Permissions
    if (
        error_code in {"AccessDeniedException", "UnauthorizedException"}
        or http_status == 403
        or "accessdenied" in exc_str.lower()
    ):
        return LLMAuthorizationError(
            message=f"Bedrock access denied: {exc_str}",
            details={"aws_error_code": error_code, "status_code": http_status},
        )

    # 3. Authentication / Missing or Invalid Credentials
    if (
        error_code in {
            "UnrecognizedClientException",
            "InvalidSignatureException",
            "ExpiredTokenException",
            "MissingAuthenticationToken",
        }
        or http_status == 401
        or exc_type in {"NoCredentialsError", "PartialCredentialsError", "CredentialRetrievalError"}
        or "credentials" in exc_str.lower()
    ):
        return LLMAuthenticationError(
            message=f"Bedrock authentication failure: {exc_str}",
            details={"aws_error_code": error_code, "status_code": http_status},
        )

    # 4. Validation / Malformed Request
    if (
        error_code in {"ValidationException", "ModelNotReadyException"}
        or http_status == 400
        or exc_type in {"ParamValidationError"}
        or "validation" in exc_str.lower()
    ):
        return LLMValidationError(
            message=f"Bedrock request validation failure: {exc_str}",
            details={"aws_error_code": error_code, "status_code": http_status},
        )

    # 5. Timeouts
    if (
        exc_type in {"ReadTimeoutError", "ConnectTimeoutError"}
        or "timeout" in exc_str.lower()
        or http_status == 504
    ):
        return LLMTimeoutError(
            message=f"Bedrock request timed out: {exc_str}",
            details={"aws_error_code": error_code, "status_code": http_status},
        )

    # 6. Transient / Network Connection Failures
    if (
        exc_type in {"EndpointConnectionError", "ConnectionClosedError"}
        or http_status in {502, 503}
        or "connection" in exc_str.lower()
    ):
        return LLMTransientError(
            message=f"Bedrock transient communication failure: {exc_str}",
            details={"aws_error_code": error_code, "status_code": http_status},
        )

    # 7. Fallback Provider Error
    return LLMProviderError(
        message=f"Bedrock invocation failed: {exc_str}",
        details={"aws_error_code": error_code, "status_code": http_status, "exception_type": exc_type},
    )


def map_gemini_exception(exc: Exception) -> LLMBaseError:
    """Deterministically map Google Gemini API exceptions into strongly typed LLMBaseError hierarchy.

    Guarantees:
    - Never leaks API keys, authorization tokens, or internal trace paths
    - Correctly sets retryable classification (429/ResourceExhausted -> RETRYABLE, 401/403/400 -> NON_RETRYABLE)
    - Conforms to existing RiskWise error contracts
    """
    if isinstance(exc, LLMBaseError):
        return exc

    exc_str = sanitize_error_message(str(exc))
    exc_type = exc.__class__.__name__

    http_status = 500
    if hasattr(exc, "code") and isinstance(exc.code, int):
        http_status = exc.code
    elif hasattr(exc, "status_code") and isinstance(exc.status_code, int):
        http_status = exc.status_code

    error_code = str(getattr(exc, "status", getattr(exc, "code", ""))).strip()
    exc_lower = exc_str.lower()

    # 1. Throttling / Rate Limits / Resource Exhaustion
    if (
        http_status == 429
        or error_code in {"RESOURCE_EXHAUSTED", "429"}
        or "resource_exhausted" in exc_lower
        or "rate limit" in exc_lower
        or "quota" in exc_lower
        or "too many requests" in exc_lower
        or "throttling" in exc_lower
    ):
        return LLMThrottlingError(
            message=f"Gemini API rate limit or quota exceeded: {exc_str}",
            details={"status_code": http_status, "provider": "gemini", "error_code": error_code},
        )

    # 2. Authorization / Permissions
    if (
        http_status == 403
        or error_code in {"PERMISSION_DENIED", "403"}
        or "permission_denied" in exc_lower
        or "access denied" in exc_lower
        or "forbidden" in exc_lower
    ):
        return LLMAuthorizationError(
            message=f"Gemini API access denied: {exc_str}",
            details={"status_code": http_status, "provider": "gemini", "error_code": error_code},
        )

    # 3. Authentication / Missing or Invalid Credentials
    if (
        http_status == 401
        or error_code in {"UNAUTHENTICATED", "401"}
        or "unauthenticated" in exc_lower
        or "invalid api key" in exc_lower
        or "api key not valid" in exc_lower
        or "api_key" in exc_lower
    ):
        return LLMAuthenticationError(
            message="Gemini API authentication failure: Invalid or missing API credentials.",
            details={"status_code": http_status, "provider": "gemini", "error_code": error_code},
        )

    # 4. Validation / Malformed Request / Invalid Argument / Not Found
    if (
        http_status in {400, 404}
        or error_code in {"INVALID_ARGUMENT", "NOT_FOUND", "400", "404"}
        or "invalid_argument" in exc_lower
        or "not_found" in exc_lower
        or "validation" in exc_lower
        or "model not found" in exc_lower
    ):
        return LLMValidationError(
            message=f"Gemini API request validation failure: {exc_str}",
            details={"status_code": http_status, "provider": "gemini", "error_code": error_code},
        )

    # 5. Timeouts / Deadline Exceeded
    if (
        http_status in {408, 504}
        or error_code in {"DEADLINE_EXCEEDED", "504"}
        or "deadline_exceeded" in exc_lower
        or "timeout" in exc_lower
        or exc_type in {"TimeoutException", "ConnectTimeout", "ReadTimeout"}
    ):
        return LLMTimeoutError(
            message=f"Gemini API request timed out: {exc_str}",
            details={"status_code": http_status, "provider": "gemini", "error_code": error_code},
        )

    # 6. Transient / Unavailable / Network Connection Failures
    if (
        http_status in {502, 503}
        or error_code in {"UNAVAILABLE", "503"}
        or "unavailable" in exc_lower
        or "connection" in exc_lower
        or exc_type in {"ConnectError", "NetworkError", "RemoteProtocolError"}
    ):
        return LLMTransientError(
            message=f"Gemini API transient communication failure: {exc_str}",
            details={"status_code": http_status, "provider": "gemini", "error_code": error_code},
        )

    # 7. Fallback Provider Error
    return LLMProviderError(
        message=f"Gemini API invocation failed: {exc_str}",
        details={"status_code": http_status, "provider": "gemini", "exception_type": exc_type, "error_code": error_code},
    )


def is_retryable_llm_error(exc: Exception) -> bool:
    """Deterministically determine whether an LLM error is safe to retry."""
    if isinstance(exc, LLMBaseError):
        return exc.retryable

    exc_module = getattr(exc.__class__, "__module__", "")
    exc_type = exc.__class__.__name__
    exc_str = str(exc).lower()

    if (
        "genai" in exc_module
        or "google" in exc_module
        or "gemini" in exc_type.lower()
        or (hasattr(exc, "code") and isinstance(getattr(exc, "code", None), int))
        or "resource_exhausted" in exc_str
    ):
        mapped = map_gemini_exception(exc)
        return mapped.retryable

    mapped = map_boto_exception(exc)
    return mapped.retryable
