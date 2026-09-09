"""Deterministic evidence analysis and structured finding synthesis for Research Agent.

Extracts factual findings, identifies inferences, generates unknown indicators for data gaps,
detects source conflicts, and compiles operational limitations without relying on LLM models.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.agents.contracts import (
    AgentConflict,
    AgentLimitation,
    ConflictResolutionStatus,
    LimitationCategory,
)
from app.agents.research.contract import (
    FindingType,
    ResearchFinding,
    ResearchRequest,
    generate_deterministic_finding_id,
)
from app.agents.research.evidence import EvidenceValidationResult
from app.rag.contracts import RAGEvidenceItem


# Domain disruption keywords and categories for deterministic classification
DISRUPTION_CATEGORIES: Dict[str, List[str]] = {
    "PORT_DISRUPTION": ["port", "terminal", "berth", "dock", "vessel", "congestion", "strike", "quay"],
    "SUPPLIER_INCIDENT": ["supplier", "factory", "plant", "facility", "fire", "insolvency", "shutdown", "production"],
    "WEATHER_EVENT": ["typhoon", "hurricane", "storm", "flood", "fog", "freeze", "weather", "snow"],
    "LOGISTICS_DELAY": ["delay", "reroute", "carrier", "rail", "customs", "freight", "transit", "embargo"],
}


class ResearchAnalysisEngine:
    """Deterministic analyzer extracting factual evidence, derived inferences, and detecting conflicts."""

    @classmethod
    def analyze(
        cls,
        request: ResearchRequest,
        validation_result: EvidenceValidationResult,
    ) -> Tuple[List[ResearchFinding], List[AgentConflict], List[AgentLimitation], Dict[str, Any], str]:
        """Perform comprehensive deterministic analysis over validated evidence items."""
        findings: List[ResearchFinding] = []
        conflicts: List[AgentConflict] = []
        limitations: List[AgentLimitation] = list(validation_result.limitations)

        valid_items = validation_result.valid_items

        # Case 1: Insufficient / No Evidence
        if not valid_items:
            # Generate explicit UNKNOWN finding
            unknown_finding = ResearchFinding(
                finding_id=generate_deterministic_finding_id(
                    organization_id=request.organization_id,
                    research_id=request.research_id,
                    index=0,
                    title="Insufficient Evidence for Objective",
                ),
                category="DATA_GAP",
                finding_type=FindingType.UNKNOWN,
                title="Insufficient Evidence Available",
                summary=(
                    f"No verified, safe evidence items were available to investigate objective: '{request.objective}'. "
                    "Status classified as INSUFFICIENT_EVIDENCE."
                ),
                evidence_ids=[],
                citation_ids=[],
                limitations=["No supporting evidence found in RAG knowledge boundary."],
                created_by_node="research_agent",
            )
            findings.append(unknown_finding)

            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_insufficient_{request.research_id[:8]}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description=f"Evidence boundary contained zero verified items for objective '{request.objective}'.",
                    affected_nodes=["research_agent"],
                    mitigation_or_impact="Downstream stages must treat risk state as undetermined / pending evidence.",
                )
            )

            summary = (
                f"Research execution '{request.research_id}' completed with INSUFFICIENT_EVIDENCE. "
                f"Zero valid RAG evidence items were available for objective: '{request.objective}'."
            )

            source_summary = {
                "total_valid_items": 0,
                "quarantined_items": len(validation_result.quarantined_items),
                "unique_sources": 0,
                "grounding_status": "UNGROUNDED",
            }

            return findings, conflicts, limitations, source_summary, summary

        # Case 2: Analyze Valid Evidence Items
        finding_idx = 0
        extracted_facts: List[ResearchFinding] = []

        for item in valid_items:
            category = cls._classify_category(item.excerpt)
            title = f"{category.replace('_', ' ').title()}: {item.document_title}"

            # Create FACT finding
            fact_finding = ResearchFinding(
                finding_id=generate_deterministic_finding_id(
                    organization_id=request.organization_id,
                    research_id=request.research_id,
                    index=finding_idx,
                    title=title,
                ),
                category=category,
                finding_type=FindingType.FACT,
                title=title,
                summary=item.excerpt.strip(),
                evidence_ids=[item.evidence_id],
                citation_ids=[item.citation_key or item.citation_id],
                source_type=getattr(item.provenance, "provider", None) or getattr(item.provenance, "file_type", None) or "RAG_DOCUMENT",
                confidence=item.confidence_score,
                limitations=[],
                conflict_references=[],
                created_by_node="research_agent",
            )
            findings.append(fact_finding)
            extracted_facts.append(fact_finding)
            finding_idx += 1

        # Case 3: Derive INFERENCE findings if multiple factual signals correlate
        if len(extracted_facts) >= 2:
            inference_finding = cls._derive_inference(
                request=request,
                facts=extracted_facts,
                index=finding_idx,
            )
            if inference_finding:
                findings.append(inference_finding)
                finding_idx += 1

        # Case 4: Detect Conflicts between evidence items
        detected_conflicts = cls._detect_conflicts(request, valid_items)
        conflicts.extend(detected_conflicts)

        # Case 5: Compile Source Summary
        unique_docs = len({item.document_id for item in valid_items})
        unique_sources = len({item.provenance.document_title for item in valid_items if item.provenance})
        source_summary = {
            "total_valid_items": len(valid_items),
            "quarantined_items": len(validation_result.quarantined_items),
            "unique_documents": unique_docs,
            "unique_sources": unique_sources,
            "grounding_status": (
                validation_result.bundle.grounding_status.value
                if validation_result.bundle
                else "GROUNDED"
            ),
        }

        # Case 6: Compile Deterministic Template Summary
        summary = cls._generate_summary(
            objective=request.objective,
            facts_count=len(extracted_facts),
            inferences_count=len(findings) - len(extracted_facts),
            conflicts_count=len(conflicts),
            limitations_count=len(limitations),
            findings=findings,
        )

        return findings, conflicts, limitations, source_summary, summary

    @classmethod
    def _classify_category(cls, text: str) -> str:
        """Classify excerpt into domain disruption category based on deterministic keywords."""
        lower_text = text.lower()
        for cat, keywords in DISRUPTION_CATEGORIES.items():
            if any(kw in lower_text for kw in keywords):
                return cat
        return "GENERAL_INTELLIGENCE"

    @classmethod
    def _derive_inference(
        cls,
        request: ResearchRequest,
        facts: List[ResearchFinding],
        index: int,
    ) -> Optional[ResearchFinding]:
        """Derive an operational inference from multiple supporting factual findings."""
        categories = {f.category for f in facts}
        supporting_evidence_ids = [eid for f in facts for eid in f.evidence_ids]
        supporting_citation_ids = [cid for f in facts for cid in f.citation_ids]

        # Port congestion + delay keywords = compound logistics disruption
        if "PORT_DISRUPTION" in categories or "LOGISTICS_DELAY" in categories:
            title = "Inferred Compounded Transit Disruption"
            summary = (
                f"Derived operational inference for objective '{request.objective}': "
                f"Observed port and logistics signals across {len(facts)} distinct evidence items "
                "indicate high likelihood of downstream shipment schedule slippage."
            )
            avg_conf = sum(f.confidence or 0.8 for f in facts) / len(facts)
            return ResearchFinding(
                finding_id=generate_deterministic_finding_id(
                    organization_id=request.organization_id,
                    research_id=request.research_id,
                    index=index,
                    title=title,
                ),
                category="COMPOUND_TRANSIT_IMPACT",
                finding_type=FindingType.INFERENCE,
                title=title,
                summary=summary,
                evidence_ids=supporting_evidence_ids,
                citation_ids=supporting_citation_ids,
                confidence=round(min(avg_conf, 0.85), 2),
                limitations=["Derived from correlative signals; real-time telemetry required for verification."],
                created_by_node="research_agent",
            )
        return None

    @classmethod
    def _detect_conflicts(
        cls,
        request: ResearchRequest,
        items: List[RAGEvidenceItem],
    ) -> List[AgentConflict]:
        """Detect direct contradictions or opposing claims across evidence items."""
        conflicts: List[AgentConflict] = []
        if len(items) < 2:
            return conflicts

        # Detect open vs closed status contradictions
        open_signals: List[RAGEvidenceItem] = []
        closed_signals: List[RAGEvidenceItem] = []

        for it in items:
            lower = it.excerpt.lower()
            if any(w in lower for w in ["resumed", "operational", "reopened", "normal operations", "cleared"]):
                open_signals.append(it)
            if any(w in lower for w in ["closed", "shut down", "halted", "suspended", "blocked", "strike"]):
                closed_signals.append(it)

        if open_signals and closed_signals:
            c_id = f"conf_status_{request.research_id[:8]}"
            conflicts.append(
                AgentConflict(
                    conflict_id=c_id,
                    category="OPERATIONAL_STATUS_CONTRADICTION",
                    affected_references=[it.evidence_id for it in open_signals + closed_signals],
                    source_evidence_ids=[it.evidence_id for it in open_signals + closed_signals],
                    description=(
                        f"Contradictory operational status detected across evidence sources for '{request.objective}': "
                        f"{len(open_signals)} source(s) report operations resumed/cleared, while "
                        f"{len(closed_signals)} source(s) report facility/route closed or halted."
                    ),
                    severity="MEDIUM",
                    resolution_status=ConflictResolutionStatus.UNRESOLVED,
                )
            )

        return conflicts

    @classmethod
    def _generate_summary(
        cls,
        objective: str,
        facts_count: int,
        inferences_count: int,
        conflicts_count: int,
        limitations_count: int,
        findings: List[ResearchFinding],
    ) -> str:
        """Generate a concise, deterministic research narrative without LLM text generation."""
        top_titles = [f.title for f in findings[:3]]
        titles_str = "; ".join(top_titles) if top_titles else "None"
        conflict_note = f" Detected {conflicts_count} source conflict(s)." if conflicts_count > 0 else ""
        limitation_note = f" Identified {limitations_count} limitation(s)." if limitations_count > 0 else ""

        return (
            f"Research conducted on objective: '{objective}'. "
            f"Extracted {facts_count} factual finding(s) and {inferences_count} derived inference(s). "
            f"Key findings include: {titles_str}.{conflict_note}{limitation_note}"
        )
