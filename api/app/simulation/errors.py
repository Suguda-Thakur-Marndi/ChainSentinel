"""Typed exception hierarchy for RiskWise Simulation Engine (Phase 13)."""
from __future__ import annotations


class SimulationError(Exception):
    """Base exception for all simulation engine operations."""

    def __init__(self, message: str, error_code: str = "SIMULATION_ERROR"):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class SimulationValidationError(SimulationError):
    """Raised when scenario parameters, changes, or entities fail validation."""

    def __init__(self, message: str):
        super().__init__(message, error_code="SIMULATION_VALIDATION_ERROR")


class SimulationTenantIsolationError(SimulationError):
    """Raised when a simulation attempts to access cross-tenant snapshots or entities."""

    def __init__(self, message: str = "Access denied: Multi-tenant boundary violation"):
        super().__init__(message, error_code="SIMULATION_TENANT_ISOLATION_ERROR")


class SimulationStateError(SimulationError):
    """Raised when simulation in-memory state manipulation fails."""

    def __init__(self, message: str):
        super().__init__(message, error_code="SIMULATION_STATE_ERROR")


class SimulationPropagationError(SimulationError):
    """Raised when effect propagation encounters an invalid condition."""

    def __init__(self, message: str):
        super().__init__(message, error_code="SIMULATION_PROPAGATION_ERROR")


class SimulationResourceLimitError(SimulationError):
    """Raised when graph traversal, depth, or effect count exceeds hard limits."""

    def __init__(self, message: str):
        super().__init__(message, error_code="SIMULATION_RESOURCE_LIMIT_ERROR")


class SimulationPersistenceError(SimulationError):
    """Raised when scenario or simulation database persistence fails."""

    def __init__(self, message: str):
        super().__init__(message, error_code="SIMULATION_PERSISTENCE_ERROR")
