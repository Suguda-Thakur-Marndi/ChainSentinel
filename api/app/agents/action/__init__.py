"""RiskWise 2.0 Action Agent Subsystem (Phase 17).

Provides strongly typed execution adapters, mandatory human approval binding,
strict idempotency, target entity validation, and LangGraph action node integration.
"""

from app.agents.action.agent import ActionAgent
from app.agents.action.contract import (
    ActionActor,
    ActionCommand,
    ActionRequest,
    ActionResult,
    ActionType,
    ExecutionStatus,
    IdempotencyResult,
    TargetEntityType,
    compute_action_fingerprint,
    generate_deterministic_action_id,
)
from app.agents.action.errors import (
    ActionAgentError,
    ActionApprovalInvalidError,
    ActionApprovalMismatchError,
    ActionApprovalMissingError,
    ActionAuthorizationError,
    ActionExecutionFailedError,
    ActionIdempotencyConflictError,
    ActionProviderRejectedError,
    ActionProviderTimeoutError,
    ActionProviderUnavailableError,
    ActionSecurityViolationError,
    ActionStaleDecisionError,
    ActionTargetNotFoundError,
    ActionTargetStateConflictError,
    ActionTenantIsolationError,
    ActionUnsupportedTypeError,
    InvalidActionRequestError,
)
from app.agents.action.executors import (
    ActionExecutorRegistry,
    BaseActionExecutor,
    CarrierReallocationExecutor,
    FacilityReallocationExecutor,
    MockActionExecutor,
    MonitorExecutor,
    ShipmentExpediteExecutor,
    ShipmentHoldExecutor,
    ShipmentRerouteExecutor,
)
from app.agents.action.node import ACTION_NODE_CONTRACT, action_node
from app.agents.action.persistence import ActionPersistenceService
from app.agents.action.policy import ACTION_ALLOWLIST, ActionSafetyPolicy

__all__ = [
    # Contracts
    "ActionActor",
    "ActionCommand",
    "ActionRequest",
    "ActionResult",
    "ActionType",
    "ExecutionStatus",
    "IdempotencyResult",
    "TargetEntityType",
    "generate_deterministic_action_id",
    "compute_action_fingerprint",
    # Errors
    "ActionAgentError",
    "InvalidActionRequestError",
    "ActionTenantIsolationError",
    "ActionApprovalMissingError",
    "ActionApprovalInvalidError",
    "ActionApprovalMismatchError",
    "ActionAuthorizationError",
    "ActionIdempotencyConflictError",
    "ActionStaleDecisionError",
    "ActionTargetNotFoundError",
    "ActionTargetStateConflictError",
    "ActionUnsupportedTypeError",
    "ActionSecurityViolationError",
    "ActionProviderUnavailableError",
    "ActionProviderTimeoutError",
    "ActionProviderRejectedError",
    "ActionExecutionFailedError",
    # Policy
    "ACTION_ALLOWLIST",
    "ActionSafetyPolicy",
    # Executors
    "BaseActionExecutor",
    "ShipmentRerouteExecutor",
    "CarrierReallocationExecutor",
    "FacilityReallocationExecutor",
    "ShipmentExpediteExecutor",
    "ShipmentHoldExecutor",
    "MonitorExecutor",
    "MockActionExecutor",
    "ActionExecutorRegistry",
    # Persistence
    "ActionPersistenceService",
    # Agent & Node
    "ActionAgent",
    "ACTION_NODE_CONTRACT",
    "action_node",
]
