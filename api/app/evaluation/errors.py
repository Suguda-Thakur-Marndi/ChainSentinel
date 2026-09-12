"""Domain exceptions for RiskWise 2.0 Evaluation & Quality Assurance (Phase 20)."""


class EvaluationError(Exception):
    """Base exception for all evaluation domain errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class EvaluationSecurityViolation(EvaluationError):
    """Raised when an evaluation test detects a security invariant violation (e.g. cross-tenant leakage)."""
    pass


class ContaminationError(EvaluationError):
    """Raised when an evaluation dataset is contaminated with training data or vice-versa."""
    pass


class InsufficientDataError(EvaluationError):
    """Raised when an evaluation case or metric has insufficient samples to yield a valid measurement."""
    pass


class MetricCalculationError(EvaluationError):
    """Raised when a mathematical or logic error occurs during metric computation."""
    pass


class SuiteExecutionError(EvaluationError):
    """Raised when an evaluation suite execution encounters an unrecoverable failure."""
    pass


# Aliases for consistent naming
DatasetContaminationError = ContaminationError
EvaluationExecutionError = SuiteExecutionError

