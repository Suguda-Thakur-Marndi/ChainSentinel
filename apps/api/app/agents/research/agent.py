"""Core domain service for the RiskWise Research Agent.

Orchestrates request validation, evidence boundary screening, deterministic finding extraction,
conflict detection, and result synthesis with strict tenant isolation and unbroken provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agents.contracts import (
    AgentConflict,
    AgentLimitation,
)
from app.agents.research.analysis import ResearchAnalysisEngine
from app.agents.research.contract import (
    FindingType,
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
    compute_research_fingerprint,
)
from app.agents.research.errors import (
    InvalidResearchRequestError,
    ResearchTenantIsolationError,
)
from app.agents.research.evidence import EvidenceValidator, EvidenceValidationResult
from app.rag.contracts import RAGEvidenceBundle


class ResearchAgent:
    """Read-only research agent conducting deterministic investigation over validated RAG evidence."""

    def __init__(self) -> None:
        self.validator = EvidenceValidator()
        self.analyzer = ResearchAnalysisEngine()

    def execute(
        self,
        request: ResearchRequest,
        bundle: Optional[RAGEvidenceBundle] = None,
        require_evidence: bool = True,
    ) -> ResearchResult:
        """Execute a full research cycle against the provided request and evidence bundle.
        
        Raises:
            ResearchTenantIsolationError: If cross-tenant access is attempted.
            MissingEvidenceError: If evidence is strictly required but absent.
            InvalidEvidenceError: If evidence schema or format is malformed.
            EvidenceIntegrityError: If citation linkage or provenance is broken.
        """
        # 1. Validate request
        if not isinstance(request, ResearchRequest):
            raise InvalidResearchRequestError(
                f"Expected ResearchRequest instance, received {type(request).__name__}."
            )

        # 2. Validate Evidence Boundary
        validation_result: EvidenceValidationResult = self.validator.validate_bundle(
            request=request,
            bundle=bundle,
            require_evidence=require_evidence,
        )

        # 3. Deterministic Analysis
        findings, conflicts, limitations, source_summary, summary = self.analyzer.analyze(
            request=request,
            validation_result=validation_result,
        )

        # 4. Status determination
        has_facts = any(f.finding_type == FindingType.FACT for f in findings)
        status = "COMPLETED" if has_facts else "INSUFFICIENT_EVIDENCE"

        # 5. Compile Evidence & Citation ID lists
        evidence_ids = [
            it.evidence_id
            for it in validation_result.valid_items
        ]
        citation_ids = [
            c.citation_key or c.citation_id
            for c in (validation_result.bundle.citations if validation_result.bundle else [])
        ]

        # 6. Overall deterministic confidence
        confidences = [f.confidence for f in findings if f.confidence is not None]
        overall_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None

        # 7. Compile Provenance
        provenance: Dict[str, Any] = {
            "research_id": request.research_id,
            "organization_id": request.organization_id,
            "bundle_id": validation_result.bundle.bundle_id if validation_result.bundle else None,
            "context_id": validation_result.bundle.context_id if validation_result.bundle else None,
            "retrieval_id": validation_result.bundle.retrieval_id if validation_result.bundle else None,
            "grounding_status": (
                validation_result.bundle.grounding_status.value
                if validation_result.bundle
                else "UNGROUNDED"
            ),
            "total_evidence_units": len(validation_result.valid_items),
            "quarantined_units": len(validation_result.quarantined_items),
        }

        # 8. Deterministic Fingerprint
        fingerprint = compute_research_fingerprint(
            organization_id=request.organization_id,
            objective=request.objective,
            evidence_bundle_id=validation_result.bundle.bundle_id if validation_result.bundle else None,
            evidence_ids=evidence_ids,
        )

        return ResearchResult(
            research_id=request.research_id,
            organization_id=request.organization_id,
            status=status,
            summary=summary,
            findings=findings,
            evidence_ids=evidence_ids,
            citation_ids=citation_ids,
            conflicts=conflicts,
            limitations=limitations,
            source_summary=source_summary,
            confidence=overall_confidence,
            provenance=provenance,
            fingerprint=fingerprint,
            created_by_node="research_agent",
            created_at=datetime.now(timezone.utc),
        )
