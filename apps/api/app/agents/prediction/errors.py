"""Strongly typed error taxonomy for the RiskWise Prediction Agent.

All errors inherit from AgentGraphError and are classified as RETRYABLE
or NON_RETRYABLE. Security, tenant, authorization, feature validation,
and invalid output violations always fail closed immediately (NON_RETRYABLE).
Model timeouts and transient infrastructure execution failures are RETRYABLE.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents.errors import AgentGraphError, ErrorClassification


class PredictionAgentError(AgentGraphError):
    """Base exception for all Prediction Agent operational failures."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "PREDICTION_AGENT_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
        )


class InvalidPredictionRequestError(PredictionAgentError):
    """Raised when a prediction request is malformed, missing required fields, or invalid."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="INVALID_PREDICTION_REQUEST",
            details=details,
        )


class PredictionTenantIsolationError(PredictionAgentError):
    """Raised when cross-tenant prediction request, feature, evidence, or assessment is detected.

    CRITICAL: Must always fail closed immediately. Never retryable.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_TENANT_ISOLATION_ERROR",
            details=details,
        )


class FeatureValidationError(PredictionAgentError):
    """Raised when a feature value, unit, range, timestamp, or provenance fails validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="FEATURE_VALIDATION_ERROR",
            details=details,
        )


class ModelUnavailableError(PredictionAgentError):
    """Raised when no production ML model is configured or available."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="MODEL_UNAVAILABLE",
            details=details,
        )


class ModelTimeoutError(PredictionAgentError):
    """Raised when model inference times out.

    Classified as RETRYABLE.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code="MODEL_TIMEOUT",
            details=details,
        )


class ModelExecutionError(PredictionAgentError):
    """Raised when model service execution encounters an unexpected transient failure.

    Classified as RETRYABLE.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code="MODEL_EXECUTION_ERROR",
            details=details,
        )


class InvalidModelOutputError(PredictionAgentError):
    """Raised when model output contains NaN, Inf, negative delay, impossible values, or invalid metadata."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="INVALID_MODEL_OUTPUT",
            details=details,
        )


class PredictionAuthorizationError(PredictionAgentError):
    """Raised when caller/actor is unauthorized to invoke prediction services."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_AUTHORIZATION_ERROR",
            details=details,
        )
