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


class PredictionExplanationError(PredictionAgentError):
    """Base exception for Claude Prediction Explanation layer failures."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "PREDICTION_EXPLANATION_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
        )


class PredictionValueContradictionError(PredictionExplanationError):
    """Raised when Claude explanation contradicts authoritative predicted value or units."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_VALUE_CONTRADICTION",
            details=details,
        )


class PredictionStatusContradictionError(PredictionExplanationError):
    """Raised when Claude asserts a conflicting status or claims a prediction when status is NOT_AVAILABLE."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_STATUS_CONTRADICTION",
            details=details,
        )


class PredictionUncertaintyFabricationError(PredictionExplanationError):
    """Raised when Claude invents confidence scores, intervals, or probabilities not supplied by the model."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_UNCERTAINTY_FABRICATION",
            details=details,
        )


class PredictionModelMetricsFabricationError(PredictionExplanationError):
    """Raised when Claude invents model performance metrics (MAE, RMSE, accuracy) not present in metadata."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_MODEL_METRICS_FABRICATION",
            details=details,
        )


class PredictionFeatureFabricationError(PredictionExplanationError):
    """Raised when Claude invents unsupplied features or fabricated feature importance values."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_FEATURE_FABRICATION",
            details=details,
        )


class PredictionExplanationCitationIntegrityError(PredictionExplanationError):
    """Raised when Claude cites an ungrounded, fabricated, or cross-tenant citation/evidence reference."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_CITATION_INTEGRITY_ERROR",
            details=details,
        )


class PredictionExplanationGroundingError(PredictionExplanationError):
    """Raised when Claude prediction explanations contain ungrounded or speculative claims."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_GROUNDING_ERROR",
            details=details,
        )


class PredictionExplanationLLMError(PredictionExplanationError):
    """Raised when Claude invocation, parsing, or token budgeting encounters a failure."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=classification,
            error_code="PREDICTION_LLM_ERROR",
            details=details,
        )


class PredictionContextBudgetExceededError(PredictionExplanationError):
    """Raised when serialized prediction context exceeds token/character budgeting limits."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="PREDICTION_CONTEXT_BUDGET_EXCEEDED",
            details=details,
        )

