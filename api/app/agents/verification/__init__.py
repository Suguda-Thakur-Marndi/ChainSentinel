"""RiskWise Verification Agent (Phase 18).

Provides:
- Strongly typed verification contracts (VerificationResultPayload, VerificationCommand, etc.)
- Deterministic outcome status and precedence hierarchy (REAL > ESTIMATED > SIMULATED)
- Read-only authoritative evidence collection
- Domain-specific verifiers for all action types
- Replay idempotency and transactional persistence
- LangGraph verification node integration
"""

from app.agents.verification.agent import VerificationAgent
from app.agents.verification.contract import (
    EvidenceSourcePrecedence,
    IntendedOutcome,
    ObservedEvidenceItem,
    ObservedOutcome,
    VerificationCommand,
    VerificationResultPayload,
    VerificationStatus,
    compute_verification_fingerprint,
    generate_deterministic_verification_id,
)
from app.agents.verification.errors import (
    VerificationActionNotExecutedError,
    VerificationActionNotFoundError,
    VerificationAgentError,
    VerificationApprovalMismatchError,
    VerificationEvidenceConflictError,
    VerificationObservationWindowExpiredError,
    VerificationSecurityViolationError,
    VerificationTenantIsolationError,
)
from app.agents.verification.evidence import EvidenceCollector
from app.agents.verification.persistence import VerificationPersistenceManager
from app.agents.verification.policy import VerificationPolicy
from app.agents.verification.verifiers import (
    BaseActionVerifier,
    CarrierReallocationVerifier,
    ExpediteShipmentVerifier,
    FacilityReallocationVerifier,
    HoldShipmentVerifier,
    MonitorVerifier,
    ShipmentRerouteVerifier,
    get_verifier_for_action,
)

__all__ = [
    "VerificationAgent",
    "VerificationCommand",
    "VerificationResultPayload",
    "VerificationStatus",
    "EvidenceSourcePrecedence",
    "IntendedOutcome",
    "ObservedOutcome",
    "ObservedEvidenceItem",
    "compute_verification_fingerprint",
    "generate_deterministic_verification_id",
    "VerificationAgentError",
    "VerificationActionNotFoundError",
    "VerificationActionNotExecutedError",
    "VerificationTenantIsolationError",
    "VerificationApprovalMismatchError",
    "VerificationEvidenceConflictError",
    "VerificationObservationWindowExpiredError",
    "VerificationSecurityViolationError",
    "EvidenceCollector",
    "VerificationPersistenceManager",
    "VerificationPolicy",
    "BaseActionVerifier",
    "ShipmentRerouteVerifier",
    "CarrierReallocationVerifier",
    "FacilityReallocationVerifier",
    "ExpediteShipmentVerifier",
    "HoldShipmentVerifier",
    "MonitorVerifier",
    "get_verifier_for_action",
]
