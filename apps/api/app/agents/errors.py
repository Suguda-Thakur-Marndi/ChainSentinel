"""Core strongly typed error taxonomy and failure classifications for RiskWise LangGraph agents.

Distinguishes between RETRYABLE and NON_RETRYABLE errors, ensuring that security,
tenant isolation, routing, and evidence integrity violations fail closed immediately.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ErrorClassification(str, Enum):
    """Classification of agent failure determining automatic recovery eligibility."""

    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"


class AgentGraphError(Exception):
    """Base exception for all LangGraph orchestration failures in RiskWise."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "AGENT_GRAPH_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.classification = classification
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize error details for audit logging and structured error records."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "classification": self.classification.value,
            "details": self.details,
        }


class AgentValidationError(AgentGraphError):
    """Raised when agent state, input references, or payloads fail schema validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_VALIDATION_ERROR",
            details=details,
        )


class AgentTenantIsolationError(AgentGraphError):
    """Raised on any tenant mismatch, missing tenant, or cross-tenant data access.
    
    CRITICAL: Must always be NON_RETRYABLE and fail closed.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_TENANT_ISOLATION_ERROR",
            details=details,
        )


class AgentUnauthorizedNodeError(AgentGraphError):
    """Raised when a graph attempts to execute a node not in the verified allowlist."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_UNAUTHORIZED_NODE_ERROR",
            details=details,
        )


class AgentInvalidRouteError(AgentGraphError):
    """Raised when a routing decision selects an invalid, unregistered, or unpermitted node."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_INVALID_ROUTE_ERROR",
            details=details,
        )


class AgentDependencyFailureError(AgentGraphError):
    """Raised when an external dependency (retriever, DB, remote service) fails."""

    def __init__(
        self,
        message: str,
        retryable: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        classification = (
            ErrorClassification.RETRYABLE if retryable else ErrorClassification.NON_RETRYABLE
        )
        super().__init__(
            message=message,
            classification=classification,
            error_code="AGENT_DEPENDENCY_FAILURE",
            details=details,
        )


class AgentTimeoutError(AgentGraphError):
    """Raised when a node or whole graph run exceeds configured timeout thresholds."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code="AGENT_TIMEOUT_ERROR",
            details=details,
        )


class AgentMaxStepsExceededError(AgentGraphError):
    """Raised when graph execution reaches the maximum allowed steps without terminating."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_MAX_STEPS_EXCEEDED",
            details=details,
        )


class AgentEvidenceIntegrityError(AgentGraphError):
    """Raised when evidence verification, provenance lineage, or bundle fingerprint fails."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_EVIDENCE_INTEGRITY_ERROR",
            details=details,
        )


class AgentToolAuthorizationError(AgentGraphError):
    """Raised when a node attempts to invoke an unauthorized, unregistered, or scope-violating tool."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_TOOL_AUTHORIZATION_ERROR",
            details=details,
        )


class AgentApprovalBoundaryViolationError(AgentGraphError):
    """Raised when a side-effecting action is attempted without valid human approval."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_APPROVAL_BOUNDARY_VIOLATION",
            details=details,
        )


class AgentStateOwnershipViolationError(AgentValidationError):
    """Raised when an unauthorized node attempts to overwrite authoritative or protected state fields."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
        )
        self.error_code = "AGENT_STATE_OWNERSHIP_VIOLATION"


class AgentStateSizeLimitError(AgentGraphError):
    """Raised when agent state exceeds maximum configured structural or byte limits."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_STATE_SIZE_LIMIT",
            details=details,
        )


class AgentInvalidEdgeError(AgentGraphError):
    """Raised when an invalid, unknown, or unallowlisted graph edge transition is attempted."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_INVALID_EDGE_ERROR",
            details=details,
        )


class AgentStageTransitionError(AgentGraphError):
    """Raised when an illegal or unauthorized stage jump violates graph pipeline topology."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_STAGE_TRANSITION_ERROR",
            details=details,
        )


class AgentGraphValidationError(AgentGraphError):
    """Raised when graph structure fails integrity validation (e.g. unreachable nodes, unbounded cycles)."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_GRAPH_VALIDATION_ERROR",
            details=details,
        )


class AgentMissingInputError(AgentValidationError):
    """Raised when a node execution lacks mandatory input requirements, evidence, or references."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
        )
        self.error_code = "AGENT_MISSING_INPUT_ERROR"


class AgentNodeExecutionError(AgentGraphError):
    """Raised when a node handler fails during execution."""

    def __init__(
        self,
        message: str,
        node_name: Optional[str] = None,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        det = dict(details or {})
        if node_name:
            det["node_name"] = node_name
        classification = (
            ErrorClassification.RETRYABLE if retryable else ErrorClassification.NON_RETRYABLE
        )
        super().__init__(
            message=message,
            classification=classification,
            error_code="AGENT_NODE_EXECUTION_ERROR",
            details=det,
        )


