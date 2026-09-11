"""Research Agent package for RiskWise LangGraph orchestration.

Provides deterministic, evidence-grounded research capabilities consuming
the Phase 8 RAG evidence boundary without executing side effects or calculating
authoritative risk scores.
"""

from __future__ import annotations

from app.agents.research.agent import ResearchAgent
from app.agents.research.claude_contract import (
    ClaudeConflictItem,
    ClaudeFindingItem,
    ClaudeResearchResponse,
)
from app.agents.research.claude_service import (
    ClaudeResearchService,
    RESEARCH_PROMPT_VERSION,
)
from app.agents.research.contract import (
    FindingType,
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
    compute_research_fingerprint,
    generate_deterministic_finding_id,
    generate_deterministic_research_id,
)
from app.agents.research.errors import (
    EvidenceIntegrityError,
    InvalidEvidenceError,
    InvalidResearchRequestError,
    MissingEvidenceError,
    ResearchCitationIntegrityError,
    ResearchError,
    ResearchGroundingError,
    ResearchLLMError,
    ResearchTenantIsolationError,
)
from app.agents.research.evidence import (
    EvidenceValidationResult,
    EvidenceValidator,
)
from app.agents.research.node import (
    RESEARCH_NODE_CONTRACT,
    research_node,
)

__all__ = [
    "ClaudeConflictItem",
    "ClaudeFindingItem",
    "ClaudeResearchResponse",
    "ClaudeResearchService",
    "EvidenceIntegrityError",
    "EvidenceValidationResult",
    "EvidenceValidator",
    "FindingType",
    "InvalidEvidenceError",
    "InvalidResearchRequestError",
    "MissingEvidenceError",
    "RESEARCH_NODE_CONTRACT",
    "RESEARCH_PROMPT_VERSION",
    "ResearchAgent",
    "ResearchCitationIntegrityError",
    "ResearchError",
    "ResearchFinding",
    "ResearchGroundingError",
    "ResearchLLMError",
    "ResearchRequest",
    "ResearchResult",
    "ResearchTenantIsolationError",
    "compute_research_fingerprint",
    "generate_deterministic_finding_id",
    "generate_deterministic_research_id",
    "research_node",
]

