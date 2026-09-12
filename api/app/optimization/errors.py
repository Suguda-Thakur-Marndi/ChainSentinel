"""Typed exception hierarchy for RiskWise Optimization Subsystem (Phase 14)."""
from __future__ import annotations

from typing import Any, Dict, Optional


class OptimizationError(Exception):
    """Base exception for all optimization errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class OptimizationValidationError(OptimizationError):
    """Raised when an optimization request, problem, or candidate fails validation."""
    pass


class OptimizationTenantIsolationError(OptimizationError):
    """Raised when cross-tenant boundary violation is detected."""
    pass


class OptimizationResourceLimitError(OptimizationError):
    """Raised when problem size exceeds hard configured safety limits."""
    pass


class OptimizationDataMissingError(OptimizationError):
    """Raised when required business data (cost, capacity, transit time) is missing."""
    pass


class OptimizationSolverUnavailableError(OptimizationError):
    """Raised when Google OR-Tools or solver backend is not available."""
    pass


class OptimizationInfeasibleError(OptimizationError):
    """Raised when mathematical model is proven infeasible by the solver."""
    pass


class OptimizationExecutionError(OptimizationError):
    """Raised when unexpected error occurs during solver formulation or execution."""
    pass
