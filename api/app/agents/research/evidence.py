"""Evidence boundary validation and safety screening for the Research Agent.

Validates incoming Phase 8 RAGEvidenceBundle instances against tenant isolation,
citation completeness, provenance lineage, and prompt-injection tampering.
Treats all retrieved content strictly as passive data, never instructions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.research.contract import ResearchRequest
from app.agents.research.errors import (
    EvidenceIntegrityError,
    InvalidEvidenceError,
    MissingEvidenceError,
    ResearchTenantIsolationError,
)
from app.rag.contracts import (
    GroundingStatus,
    PROMPT_INJECTION_PATTERNS,
    RAGEvidenceBundle,
    RAGEvidenceItem,
)


class EvidenceValidationResult:
    """Result container for evidence validation, safety screening, and extracted limitations."""

    def __init__(
        self,
        is_valid: bool,
        bundle: Optional[RAGEvidenceBundle],
        valid_items: List[RAGEvidenceItem],
        quarantined_items: List[RAGEvidenceItem],
        limitations: List[AgentLimitation],
        warnings: List[str],
    ) -> None:
        self.is_valid = is_valid
        self.bundle = bundle
        self.valid_items = valid_items
        self.quarantined_items = quarantined_items
        self.limitations = limitations
        self.warnings = warnings

    @property
    def has_sufficient_evidence(self) -> bool:
        return len(self.valid_items) > 0


RESEARCH_PROMPT_INJECTION_PATTERNS = PROMPT_INJECTION_PATTERNS + [
    re.compile(r"ignore\s+(all\s+)?instructions", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
]


class EvidenceValidator:
    """Enforces strict tenant isolation, safety checks, and provenance verification on RAG evidence."""

    @classmethod
    def validate_bundle(
        cls,
        request: ResearchRequest,
        bundle: Optional[RAGEvidenceBundle] = None,
        require_evidence: bool = True,
    ) -> EvidenceValidationResult:
        """Validate an evidence bundle against tenant isolation, integrity, and prompt injection."""
        target_bundle = bundle or request.evidence_bundle

        limitations: List[AgentLimitation] = []
        warnings: List[str] = []

        if target_bundle is None:
            if require_evidence:
                raise MissingEvidenceError(
                    f"Research request '{request.research_id}' requires an evidence bundle, but none was provided.",
                    details={"research_id": request.research_id, "organization_id": request.organization_id},
                )
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_no_bundle_{request.research_id[:8]}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description="No RAG evidence bundle was supplied for this research execution.",
                    affected_nodes=["research_agent"],
                )
            )
            return EvidenceValidationResult(
                is_valid=True,
                bundle=None,
                valid_items=[],
                quarantined_items=[],
                limitations=limitations,
                warnings=["Execution proceeding without evidence bundle."],
            )

        # 1. Structural schema verification
        if not isinstance(target_bundle, RAGEvidenceBundle):
            raise InvalidEvidenceError(
                f"Supplied evidence bundle is not an instance of RAGEvidenceBundle (got {type(target_bundle).__name__}).",
                details={"expected": "RAGEvidenceBundle", "actual": type(target_bundle).__name__},
            )

        # 2. Strict Tenant Isolation
        if target_bundle.organization_id != request.organization_id:
            raise ResearchTenantIsolationError(
                f"Evidence bundle tenant '{target_bundle.organization_id}' does not match research tenant '{request.organization_id}'.",
                details={
                    "request_organization_id": request.organization_id,
                    "bundle_organization_id": target_bundle.organization_id,
                    "bundle_id": target_bundle.bundle_id,
                },
            )

        # 3. Citation integrity map
        citation_keys: Set[str] = {c.citation_key for c in target_bundle.citations}
        citation_ids: Set[str] = {c.citation_id for c in target_bundle.citations}

        valid_items: List[RAGEvidenceItem] = []
        quarantined_items: List[RAGEvidenceItem] = []

        # 4. Item-by-item inspection
        for idx, item in enumerate(target_bundle.evidence_items):
            # Tenant verification for each item
            if item.organization_id != request.organization_id:
                raise ResearchTenantIsolationError(
                    f"Evidence item '{item.evidence_id}' belongs to tenant '{item.organization_id}', expected '{request.organization_id}'.",
                    details={"item_id": item.evidence_id, "item_org": item.organization_id},
                )

            # Citation linkage verification
            if item.citation_key not in citation_keys and item.citation_id not in citation_ids:
                raise EvidenceIntegrityError(
                    f"Evidence item '{item.evidence_id}' has dangling citation key '{item.citation_key}' not found in bundle citations.",
                    details={"item_id": item.evidence_id, "citation_key": item.citation_key},
                )

            # Prompt injection & adversarial heuristic screening
            injection_markers = cls._scan_for_prompt_injection(item.excerpt)
            if injection_markers or not item.is_safe or len(item.prompt_injection_flags) > 0:
                quarantined_items.append(item)
                warnings.append(
                    f"Evidence item '{item.evidence_id}' quarantined: adversarial prompt injection indicator detected."
                )
                limitations.append(
                    AgentLimitation(
                        limitation_id=f"lim_quarantine_{item.evidence_id[:8]}",
                        category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                        description=f"Evidence item '{item.evidence_id}' was quarantined due to untrusted instruction content.",
                        affected_nodes=["research_agent"],
                        mitigation_or_impact="Excluded from factual findings to prevent prompt injection execution.",
                    )
                )
            else:
                valid_items.append(item)

        # 5. Grounding status checks
        if target_bundle.grounding_status == GroundingStatus.UNSAFE_SOURCE:
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_unsafe_bundle_{target_bundle.bundle_id[:8]}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description="Evidence bundle flagged as UNSAFE_SOURCE by Phase 8 RAG engine.",
                    affected_nodes=["research_agent"],
                    mitigation_or_impact="Findings restricted; all claims marked ungrounded or limitations recorded.",
                )
            )
        elif target_bundle.grounding_status == GroundingStatus.PARTIALLY_GROUNDED:
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_partial_bundle_{target_bundle.bundle_id[:8]}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description="Evidence bundle is PARTIALLY_GROUNDED; some queries lack conclusive coverage.",
                    affected_nodes=["research_agent"],
                )
            )

        # 6. Check if bundle is empty
        if not valid_items and require_evidence:
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_empty_bundle_{target_bundle.bundle_id[:8]}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description="No valid, safe evidence items available in bundle after safety filtering.",
                    affected_nodes=["research_agent"],
                )
            )

        return EvidenceValidationResult(
            is_valid=True,
            bundle=target_bundle,
            valid_items=valid_items,
            quarantined_items=quarantined_items,
            limitations=limitations,
            warnings=warnings,
        )

    @classmethod
    def _scan_for_prompt_injection(cls, text: str) -> List[str]:
        """Scan text against Phase 8 heuristic prompt injection patterns and adversarial triggers."""
        if not text:
            return []
        matches: List[str] = []
        for pattern in RESEARCH_PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                matches.append(pattern.pattern)
        return matches
