"""RiskWise Risk Agent Package — Phase 9 Step 5 & Phase 10 Step 4.

Provides the LangGraph Risk Agent node, contract, and orchestrator.
Delegates all risk calculation to the authoritative Phase 7 BaselineRiskEngine.
Provides the Claude Risk Explanation Service for controlled natural language explanation.
"""

from app.agents.risk.agent import RiskAgent
from app.agents.risk.claude_contract import (
    ClaudeEvidenceExplanation,
    ClaudeRiskConflictExplanation,
    ClaudeRiskDriverExplanation,
    ClaudeRiskExplanation,
    RiskExplanationInput,
    RiskExplanationResult,
    RiskExplanationStatus,
    RiskFactorExplanationInput,
    compute_explanation_fingerprint,
)
from app.agents.risk.claude_service import (
    ClaudeRiskExplanationService,
    RISK_EXPLANATION_PROMPT_VERSION,
)
from app.agents.risk.contract import (
    RiskAgentRequest,
    RiskAgentResult,
    generate_deterministic_risk_request_id,
)
from app.agents.risk.errors import (
    InvalidRiskRequestError,
    RiskAgentError,
    RiskEngineAdapterError,
    RiskEvidenceBoundaryError,
    RiskExplanationCitationIntegrityError,
    RiskExplanationError,
    RiskExplanationGroundingError,
    RiskExplanationLLMError,
    RiskFactorContradictionError,
    RiskInputValidationError,
    RiskScoreContradictionError,
    RiskTenantIsolationError,
    UnsupportedFindingMappingError,
)
from app.agents.risk.node import (
    RISK_NODE_CONTRACT,
    _emit_risk_audit,
    risk_node,
)

__all__ = [
    # Node
    "risk_node",
    "RISK_NODE_CONTRACT",
    "_emit_risk_audit",
    # Agent
    "RiskAgent",
    # Contracts
    "RiskAgentRequest",
    "RiskAgentResult",
    "generate_deterministic_risk_request_id",
    # Claude Explanation Contracts
    "ClaudeEvidenceExplanation",
    "ClaudeRiskConflictExplanation",
    "ClaudeRiskDriverExplanation",
    "ClaudeRiskExplanation",
    "RiskExplanationInput",
    "RiskExplanationResult",
    "RiskExplanationStatus",
    "RiskFactorExplanationInput",
    "compute_explanation_fingerprint",
    # Service
    "ClaudeRiskExplanationService",
    "RISK_EXPLANATION_PROMPT_VERSION",
    # Errors
    "RiskAgentError",
    "InvalidRiskRequestError",
    "RiskTenantIsolationError",
    "RiskEvidenceBoundaryError",
    "RiskEngineAdapterError",
    "RiskInputValidationError",
    "UnsupportedFindingMappingError",
    "RiskExplanationError",
    "RiskScoreContradictionError",
    "RiskFactorContradictionError",
    "RiskExplanationCitationIntegrityError",
    "RiskExplanationGroundingError",
    "RiskExplanationLLMError",
]
