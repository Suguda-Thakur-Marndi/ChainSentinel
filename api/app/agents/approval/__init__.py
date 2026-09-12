"""Human Approval package for RiskWise 2.0 LangGraph multi-agent pipeline.

Establishes the governance boundary between Decision and Action, enforcing
zero-trust human sign-off, strict RBAC authorization, and auditable persistence.
"""

from __future__ import annotations

from app.agents.approval.agent import HumanApprovalAgent
from app.agents.approval.contract import (
    APPROVAL_UUID_NAMESPACE,
    ApprovalActor,
    ApprovalAuditContext,
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalDossier,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
    HumanDecisionRequest,
    PendingApprovalItem,
    PendingApprovalListResponse,
    compute_approval_fingerprint,
    generate_deterministic_approval_id,
)
from app.agents.approval.errors import (
    ApprovalAgentError,
    ApprovalAlreadyFinalizedError,
    ApprovalAuthorizationError,
    ApprovalCandidateMismatchError,
    ApprovalDecisionRequiredError,
    ApprovalExpiredError,
    ApprovalNotFoundError,
    ApprovalPersistenceError,
    ApprovalStateOwnershipViolationError,
    ApprovalTenantIsolationError,
    InvalidApprovalRequestError,
    InvalidApprovalTransitionError,
)
from app.agents.approval.node import (
    HUMAN_APPROVAL_NODE_CONTRACT,
    human_approval_node,
)
from app.agents.approval.persistence import ApprovalRepository
from app.agents.approval.service import HumanApprovalService

__all__ = [
    # Contracts & Enums
    "APPROVAL_UUID_NAMESPACE",
    "ApprovalDecision",
    "ApprovalStatus",
    "ApprovalActor",
    "ApprovalAuditContext",
    "ApprovalRequest",
    "ApprovalDecisionInput",
    "ApprovalResult",
    "PendingApprovalItem",
    "PendingApprovalListResponse",
    "ApprovalDossier",
    "HumanDecisionRequest",
    "generate_deterministic_approval_id",
    "compute_approval_fingerprint",
    # Service & Agent & Persistence
    "HumanApprovalService",
    "HumanApprovalAgent",
    "ApprovalRepository",
    # Node & Contract
    "HUMAN_APPROVAL_NODE_CONTRACT",
    "human_approval_node",
    # Errors
    "ApprovalAgentError",
    "InvalidApprovalRequestError",
    "ApprovalTenantIsolationError",
    "ApprovalAuthorizationError",
    "ApprovalNotFoundError",
    "InvalidApprovalTransitionError",
    "ApprovalAlreadyFinalizedError",
    "ApprovalCandidateMismatchError",
    "ApprovalDecisionRequiredError",
    "ApprovalExpiredError",
    "ApprovalPersistenceError",
    "ApprovalStateOwnershipViolationError",
]
