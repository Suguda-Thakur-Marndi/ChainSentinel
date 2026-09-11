"""Typed exception hierarchy for the RiskWise Digital Twin subsystem.

Provides specific, non-leaking, domain-aligned exceptions for graph validation,
tenant isolation, reference integrity, persistence, and traversal queries.
"""

from __future__ import annotations


class DigitalTwinError(Exception):
    """Base exception for all Digital Twin operations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TwinValidationError(DigitalTwinError):
    """Raised when twin graph, node, edge, or snapshot validation fails."""
    pass


class TwinNodeError(DigitalTwinError):
    """Raised when node creation, identity, or attribute constraints are violated."""
    pass


class TwinEdgeError(DigitalTwinError):
    """Raised when edge creation, identity, or relationship constraints are violated."""
    pass


class TwinReferenceError(DigitalTwinError):
    """Raised when an edge references a non-existent source or target node."""
    pass


class TwinTenantIsolationError(DigitalTwinError):
    """Raised when cross-tenant data access, graph contamination, or isolation is breached."""
    pass


class TwinFingerprintError(DigitalTwinError):
    """Raised when a computed fingerprint does not match expected graph content or metadata."""
    pass


class TwinPersistenceError(DigitalTwinError):
    """Raised when transactional persistence of twin nodes or edges fails."""
    pass


class TwinSnapshotError(DigitalTwinError):
    """Raised when snapshot creation, serialization, or immutability invariants fail."""
    pass


class TwinQueryError(DigitalTwinError):
    """Raised when twin query parameters or constraints are violated."""
    pass


class TwinTraversalError(DigitalTwinError):
    """Raised when graph traversal exceeds depth, size limits, or encounters an invalid state."""
    pass
