"""Core strongly typed error taxonomy and failure classifications for RiskWise LangGraph agents.

Distinguishes between RETRYABLE and NON_RETRYABLE errors, ensuring that security,
tenant isolation, routing, and evidence integrity violations fail closed immediately.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Dict, Optional


class ErrorClassification(str, Enum):
    """Classification of agent failure determining automatic recovery eligibility."""

    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"


class AgentErrorCategory(str, Enum):
    """Deterministic error categories for agent pipeline observability and recovery."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    SECURITY_ERROR = "SECURITY_ERROR"
    TENANT_ISOLATION_ERROR = "TENANT_ISOLATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    CONTRACT_ERROR = "CONTRACT_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    RATE_LIMIT_ERROR = "RATE_LIMIT_ERROR"
    STATE_ERROR = "STATE_ERROR"
    ROUTING_ERROR = "ROUTING_ERROR"
    APPROVAL_ERROR = "APPROVAL_ERROR"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


# Categories that must NEVER be retried automatically under any circumstances
NON_RETRYABLE_ERROR_CATEGORIES = frozenset({
    AgentErrorCategory.SECURITY_ERROR,
    AgentErrorCategory.TENANT_ISOLATION_ERROR,
    AgentErrorCategory.AUTHORIZATION_ERROR,
    AgentErrorCategory.CONTRACT_ERROR,
    AgentErrorCategory.VALIDATION_ERROR,
    AgentErrorCategory.STATE_ERROR,
    AgentErrorCategory.APPROVAL_ERROR,
})


class AgentGraphError(Exception):
    """Base exception for all LangGraph orchestration failures in RiskWise."""

    def __init__(
        self,
        message: str,
        classification: ErrorClassification = ErrorClassification.NON_RETRYABLE,
        error_code: str = "AGENT_GRAPH_ERROR",
        details: Optional[Dict[str, Any]] = None,
        category: Optional[AgentErrorCategory] = None,
        public_message: Optional[str] = None,
        node_id: Optional[str] = None,
        stage: Optional[str] = None,
        attempt: Optional[int] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.classification = classification
        self.error_code = error_code
        self.details = dict(details or {})
        self.category = category or AgentErrorCategory.INTERNAL_ERROR
        self.public_message = public_message or "An internal error occurred during agent graph execution."
        self.node_id = node_id or self.details.get("node_id")
        self.stage = stage or self.details.get("stage")
        self.attempt = attempt or self.details.get("attempt", 1)
        self.trace_id = trace_id or self.details.get("trace_id")

    @property
    def retryable(self) -> bool:
        """Determine whether this error is safe for automatic retry."""
        if getattr(self, "_retryable_override", None) is not None:
            if self.category in NON_RETRYABLE_ERROR_CATEGORIES:
                return False
            return bool(self._retryable_override)
        if self.category in NON_RETRYABLE_ERROR_CATEGORIES:
            return False
        return self.classification == ErrorClassification.RETRYABLE

    @retryable.setter
    def retryable(self, value: bool) -> None:
        """Set retryable flag, updating classification accordingly."""
        self._retryable_override = bool(value)
        if value:
            self.classification = ErrorClassification.RETRYABLE
        else:
            self.classification = ErrorClassification.NON_RETRYABLE

    def to_dict(self) -> Dict[str, Any]:
        """Serialize error details for audit logging and structured error records."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "category": self.category.value,
            "message": self.message,
            "public_message": self.public_message,
            "classification": self.classification.value,
            "retryable": self.retryable,
            "node_id": self.node_id,
            "stage": self.stage,
            "attempt": self.attempt,
            "trace_id": self.trace_id,
            "details": self.details,
        }


class AgentValidationError(AgentGraphError):
    """Raised when agent state, input references, or payloads fail schema validation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_VALIDATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.VALIDATION_ERROR,
            public_message=public_message or "Input validation failed for agent execution.",
        )


class AgentSecurityError(AgentGraphError):
    """Raised on security violations, credential leakage attempts, or tampering.
    
    CRITICAL: Must always be NON_RETRYABLE and fail closed immediately.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_SECURITY_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.SECURITY_ERROR,
            public_message=public_message or "A security violation prevented execution.",
        )


class AgentTenantIsolationError(AgentGraphError):
    """Raised on any tenant mismatch, missing tenant, or cross-tenant data access.
    
    CRITICAL: Must always be NON_RETRYABLE and fail closed.
    """

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code="AGENT_TENANT_ISOLATION_ERROR",
            details=details,
            category=AgentErrorCategory.TENANT_ISOLATION_ERROR,
            public_message=public_message or "Tenant isolation policy violation detected.",
        )


class AgentAuthorizationError(AgentGraphError):
    """Raised when caller lacks required role or permission for node or action."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_AUTHORIZATION_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.AUTHORIZATION_ERROR,
            public_message=public_message or "Action unauthorized for current caller context.",
        )


class AgentUnauthorizedNodeError(AgentAuthorizationError):
    """Raised when a graph attempts to execute a node not in the verified allowlist."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_UNAUTHORIZED_NODE_ERROR",
            public_message="Node execution unauthorized.",
        )


class AgentToolAuthorizationError(AgentAuthorizationError):
    """Raised when a node attempts to invoke an unauthorized, unregistered, or scope-violating tool."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_TOOL_AUTHORIZATION_ERROR",
            public_message="Tool invocation unauthorized.",
        )


class AgentContractError(AgentGraphError):
    """Raised when a node or edge violates its declared topological contract."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_CONTRACT_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.CONTRACT_ERROR,
            public_message=public_message or "Agent contract violation detected.",
        )


class AgentEvidenceIntegrityError(AgentContractError):
    """Raised when evidence verification, provenance lineage, or bundle fingerprint fails."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_EVIDENCE_INTEGRITY_ERROR",
            public_message="Evidence bundle integrity verification failed.",
        )


class AgentGraphValidationError(AgentContractError):
    """Raised when graph structure fails integrity validation (e.g. unreachable nodes, unbounded cycles)."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_GRAPH_VALIDATION_ERROR",
            public_message="Agent graph structure validation failed.",
        )


class AgentDependencyFailureError(AgentGraphError):
    """Raised when an external dependency (retriever, DB, remote service) fails."""

    def __init__(
        self,
        message: str,
        retryable: bool = True,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_DEPENDENCY_FAILURE",
        public_message: Optional[str] = None,
    ) -> None:
        classification = (
            ErrorClassification.RETRYABLE if retryable else ErrorClassification.NON_RETRYABLE
        )
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.DEPENDENCY_ERROR,
            public_message=public_message or "A backend dependency operation failed.",
        )


class AgentTimeoutError(AgentGraphError):
    """Raised when a node or whole graph run exceeds configured timeout thresholds."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code="AGENT_TIMEOUT_ERROR",
            details=details,
            category=AgentErrorCategory.TIMEOUT_ERROR,
            public_message=public_message or "Operation timed out during agent execution.",
        )


class AgentTransientError(AgentGraphError):
    """Raised for transient temporary network or resource conflicts that can safely be retried."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_TRANSIENT_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.TRANSIENT_ERROR,
            public_message=public_message or "A temporary transient error occurred.",
        )


class AgentRateLimitError(AgentGraphError):
    """Raised when an agent operation exceeds configured rate or capacity limits."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_RATE_LIMIT_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.RATE_LIMIT_ERROR,
            public_message=public_message or "Rate limit exceeded. Please retry later.",
        )


class AgentStateError(AgentGraphError):
    """Raised on state corruption, state hash mismatch, or invalid state mutation."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_STATE_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.STATE_ERROR,
            public_message=public_message or "Agent execution state integrity error.",
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
            error_code="AGENT_STATE_OWNERSHIP_VIOLATION",
            public_message="Unauthorized state field modification attempt.",
        )
        self.category = AgentErrorCategory.STATE_ERROR


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
            category=AgentErrorCategory.STATE_ERROR,
            public_message="Agent state exceeded maximum allowed payload size.",
        )


class AgentRoutingError(AgentGraphError):
    """Raised on invalid route selection, cycle/loop detection, or max steps exceeded."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_ROUTING_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.ROUTING_ERROR,
            public_message=public_message or "Graph routing resolution error.",
        )


class AgentInvalidRouteError(AgentRoutingError):
    """Raised when a routing decision selects an invalid, unregistered, or unpermitted node."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_INVALID_ROUTE_ERROR",
            public_message="Invalid destination node in graph routing.",
        )


class AgentMaxStepsExceededError(AgentRoutingError):
    """Raised when graph execution reaches the maximum allowed steps without terminating."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_MAX_STEPS_EXCEEDED",
            public_message="Graph execution exceeded maximum permitted step limit.",
        )


class AgentInvalidEdgeError(AgentRoutingError):
    """Raised when an invalid, unknown, or unallowlisted graph edge transition is attempted."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_INVALID_EDGE_ERROR",
            public_message="Invalid edge transition attempted.",
        )


class AgentStageTransitionError(AgentRoutingError):
    """Raised when an illegal or unauthorized stage jump violates graph pipeline topology."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_STAGE_TRANSITION_ERROR",
            public_message="Forbidden pipeline stage transition attempted.",
        )


class AgentApprovalError(AgentGraphError):
    """Raised on approval boundary violations, unauthorized approvals, or tampered approvals."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_APPROVAL_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.APPROVAL_ERROR,
            public_message=public_message or "Governance human approval boundary violation.",
        )


class AgentApprovalBoundaryViolationError(AgentApprovalError):
    """Raised when a side-effecting action is attempted without valid human approval."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            details=details,
            error_code="AGENT_APPROVAL_BOUNDARY_VIOLATION",
            public_message="Action requires verified human approval before execution.",
        )


class AgentPersistenceError(AgentGraphError):
    """Raised when database or checkpoint persistence encounters an error or conflict."""

    def __init__(
        self,
        message: str,
        retryable: bool = True,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_PERSISTENCE_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        classification = (
            ErrorClassification.RETRYABLE if retryable else ErrorClassification.NON_RETRYABLE
        )
        super().__init__(
            message=message,
            classification=classification,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.PERSISTENCE_ERROR,
            public_message=public_message or "A persistence storage operation failed.",
        )


class AgentInternalError(AgentGraphError):
    """Raised on unexpected runtime errors or unhandled system exceptions."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: str = "AGENT_INTERNAL_ERROR",
        public_message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message=message,
            classification=ErrorClassification.NON_RETRYABLE,
            error_code=error_code,
            details=details,
            category=AgentErrorCategory.INTERNAL_ERROR,
            public_message=public_message or "An internal error occurred during agent execution.",
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
            error_code="AGENT_MISSING_INPUT_ERROR",
            public_message="Required input data or evidence is missing.",
        )


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
            category=AgentErrorCategory.INTERNAL_ERROR,
            public_message="An error occurred while executing an agent node.",
        )


def categorize_error(exc: Exception) -> AgentErrorCategory:
    """Deterministically categorize any exception into the AgentErrorCategory taxonomy."""
    if isinstance(exc, AgentGraphError):
        return exc.category

    # Check standard library and common framework exceptions
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return AgentErrorCategory.TIMEOUT_ERROR
    if isinstance(exc, PermissionError):
        return AgentErrorCategory.AUTHORIZATION_ERROR
    if isinstance(exc, (ValueError, TypeError)):
        return AgentErrorCategory.VALIDATION_ERROR
    if isinstance(exc, (ConnectionError, ConnectionRefusedError, ConnectionResetError, OSError)):
        return AgentErrorCategory.TRANSIENT_ERROR

    # Check exception class name or message patterns
    exc_name = exc.__class__.__name__.lower()
    exc_msg = str(exc).lower()

    if "tenant" in exc_name or "tenant" in exc_msg:
        return AgentErrorCategory.TENANT_ISOLATION_ERROR
    if "security" in exc_name or "forbidden" in exc_msg or "credential" in exc_msg:
        return AgentErrorCategory.SECURITY_ERROR
    if "auth" in exc_name or "permission" in exc_msg:
        return AgentErrorCategory.AUTHORIZATION_ERROR
    if "timeout" in exc_name or "timeout" in exc_msg:
        return AgentErrorCategory.TIMEOUT_ERROR
    if "rate" in exc_msg and "limit" in exc_msg:
        return AgentErrorCategory.RATE_LIMIT_ERROR
    if "route" in exc_name or "routing" in exc_msg:
        return AgentErrorCategory.ROUTING_ERROR
    if "approval" in exc_name or "approval" in exc_msg:
        return AgentErrorCategory.APPROVAL_ERROR
    if "database" in exc_name or "integrity" in exc_name or "sql" in exc_name:
        return AgentErrorCategory.PERSISTENCE_ERROR
    if "state" in exc_name or "state" in exc_msg:
        return AgentErrorCategory.STATE_ERROR

    return AgentErrorCategory.UNKNOWN_ERROR


def is_retryable_error(exc: Exception) -> bool:
    """Deterministically determine whether an exception is eligible for automatic retry.
    
    CRITICAL: Security, tenant isolation, authorization, contract, state, and approval
    violations are strictly NEVER retryable under any circumstances.
    """
    category = categorize_error(exc)
    if category in NON_RETRYABLE_ERROR_CATEGORIES:
        return False

    if isinstance(exc, AgentGraphError):
        return exc.retryable

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    if isinstance(exc, (ConnectionError, ConnectionRefusedError, ConnectionResetError)):
        return True

    return category in {
        AgentErrorCategory.DEPENDENCY_ERROR,
        AgentErrorCategory.TIMEOUT_ERROR,
        AgentErrorCategory.TRANSIENT_ERROR,
        AgentErrorCategory.RATE_LIMIT_ERROR,
        AgentErrorCategory.PERSISTENCE_ERROR,
    }
