"""Centralized typed exception definitions for RiskWise Risk Engine."""

from __future__ import annotations

from typing import Any, Optional
from fastapi import status

from app.core.errors import AppError


HTTP_422_UNPROCESSABLE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)


class RiskEngineError(AppError):
    """Base exception for all Risk Engine operations."""

    def __init__(
        self,
        message: str = "A risk engine error occurred",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "RISK_ENGINE_ERROR",
        details: Optional[Any] = None,
    ):
        super().__init__(message=message, status_code=status_code, code=code, details=details)


class RiskEngineInputError(RiskEngineError):
    """Raised when an invalid input type is supplied across the engine boundary."""

    def __init__(
        self,
        message: str = "Invalid input to Risk Engine. Only NormalizedRiskSignal is accepted.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="INVALID_RISK_ENGINE_INPUT",
            details=details,
        )


class TenantMismatchError(RiskEngineError):
    """Raised when a signal or entity violates the organization tenant boundary."""

    def __init__(
        self,
        message: str = "Cross-tenant signal detected in risk evaluation context.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            code="TENANT_MISMATCH",
            details=details,
        )


class InvalidContextError(RiskEngineError):
    """Raised when the RiskEvaluationContext is incomplete or invalid."""

    def __init__(
        self,
        message: str = "RiskEvaluationContext is invalid or missing required fields.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="INVALID_EVALUATION_CONTEXT",
            details=details,
        )


class InvalidSignalQualityError(RiskEngineError):
    """Raised when a signal fails the risk engine quality gate."""

    def __init__(
        self,
        message: str = "Signal failed risk engine quality gating.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=HTTP_422_UNPROCESSABLE,
            code="INVALID_SIGNAL_QUALITY",
            details=details,
        )


class EvaluatorRegistrationError(RiskEngineError):
    """Raised when registering an evaluator conflicts or is invalid."""

    def __init__(
        self,
        message: str = "Evaluator registration failed.",
        details: Optional[Any] = None,
    ):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            code="EVALUATOR_REGISTRATION_ERROR",
            details=details,
        )
