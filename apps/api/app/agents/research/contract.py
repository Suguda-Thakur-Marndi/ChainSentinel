"""Strongly typed contracts for the RiskWise Research Agent.

Defines the request, finding, and result contracts governing evidence-grounded
research operations. Enforces tenant isolation, unambiguous distinction between
FACT, INFERENCE, and UNKNOWN, and zero-leakage of private reasoning or credentials.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import (
    AgentConflict,
    AgentFinding,
    AgentLimitation,
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.research.errors import (
    InvalidResearchRequestError,
    ResearchTenantIsolationError,
)
from app.rag.contracts import RAGEvidenceBundle, RAG_UUID_NAMESPACE


class FindingType(str, Enum):
    """Epistemic classification of research findings.
    
    FACT: Directly supported by concrete, verified evidence from RAG knowledge.
    INFERENCE: Derived or synthesized from supporting facts, explicitly identified as non-primitive.
    UNKNOWN: Information gap or missing evidence, explicitly identified without speculation.
    """

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


def generate_deterministic_research_id(
    organization_id: str,
    objective: str,
    evidence_bundle_id: Optional[str] = None,
) -> str:
    """Generate a reproducible UUIDv5 research identifier from tenant, objective, and evidence bundle."""
    if not organization_id or not organization_id.strip():
        raise ResearchTenantIsolationError("organization_id must be non-empty to generate research_id")
    token = f"{organization_id.strip()}:research:{objective.strip().lower()}:{evidence_bundle_id or 'none'}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def generate_deterministic_finding_id(
    organization_id: str,
    research_id: str,
    index: int,
    title: str,
) -> str:
    """Generate a reproducible UUIDv5 finding identifier."""
    if not organization_id or not organization_id.strip():
        raise ResearchTenantIsolationError("organization_id must be non-empty to generate finding_id")
    token = f"{organization_id.strip()}:finding:{research_id.strip()}:{index}:{title.strip().lower()}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def compute_research_fingerprint(
    organization_id: str,
    objective: str,
    evidence_bundle_id: Optional[str] = None,
    evidence_ids: Optional[List[str]] = None,
) -> str:
    """Compute a deterministic cryptographic fingerprint representing stable research inputs."""
    sorted_ev = ":".join(sorted(evidence_ids)) if evidence_ids else "empty"
    raw = f"{organization_id.strip()}|{objective.strip().lower()}|{evidence_bundle_id or 'none'}|{sorted_ev}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResearchFinding(BaseModel):
    """Structured, evidence-grounded research finding.
    
    Distinguishes FACTS from INFERENCES and UNKNOWNS, preserving unbroken
    citations and evidence linkage.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    finding_id: str = Field(..., min_length=1, max_length=64)
    category: str = Field(..., min_length=1, max_length=64)
    finding_type: FindingType = Field(default=FindingType.FACT)
    title: str = Field(..., min_length=1, max_length=256)
    summary: str = Field(..., min_length=1, max_length=4096)
    evidence_ids: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)
    source_type: Optional[str] = Field(default=None, max_length=64)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    limitations: List[str] = Field(default_factory=list)
    conflict_references: List[str] = Field(default_factory=list)
    created_by_node: str = Field(default="research_agent", min_length=1, max_length=64)

    @field_validator("title", "summary", mode="after")
    @classmethod
    def validate_safety(cls, v: str, info: Any) -> str:
        validate_no_forbidden_keys({info.field_name: v}, f"ResearchFinding.{info.field_name}")
        validate_no_sensitive_values(v, f"ResearchFinding.{info.field_name}")
        return v

    @model_validator(mode="after")
    def validate_epistemic_invariants(self) -> ResearchFinding:
        """Enforce strict evidence rules based on finding_type."""
        if self.finding_type == FindingType.FACT:
            if not self.evidence_ids:
                raise InvalidResearchRequestError(
                    f"Finding '{self.finding_id}' of type FACT must have at least one supporting evidence_id.",
                    details={"finding_id": self.finding_id, "title": self.title},
                )
        return self

    def to_agent_finding(self) -> AgentFinding:
        """Convert into the generic Phase 9 AgentFinding format for graph state storage."""
        return AgentFinding(
            finding_id=self.finding_id,
            category=f"{self.category}:{self.finding_type.value}",
            title=self.title,
            summary=self.summary,
            confidence=self.confidence,
            evidence_ids=list(self.evidence_ids),
            source_references=list(self.citation_ids),
            limitations=list(self.limitations),
            created_by_node=self.created_by_node,
        )


class ResearchRequest(BaseModel):
    """Strongly typed input specification for initiating a research cycle."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    research_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    objective: str = Field(..., min_length=1, max_length=4096)
    actor_id: Optional[str] = Field(default=None, max_length=64)
    entity_references: List[str] = Field(default_factory=list)
    evidence_bundle_id: Optional[str] = Field(default=None, max_length=64)
    evidence_bundle: Optional[RAGEvidenceBundle] = None
    evidence_references: List[str] = Field(default_factory=list)
    requested_scope: Optional[str] = Field(default=None, max_length=256)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: Optional[str] = Field(default=None, max_length=64)

    @field_validator("organization_id", "objective", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidResearchRequestError(
                f"Field '{info.field_name}' must be a non-empty string in ResearchRequest."
            )
        return v.strip()

    @field_validator("objective", mode="after")
    @classmethod
    def validate_objective_safety(cls, v: str) -> str:
        validate_no_forbidden_keys({"objective": v}, "ResearchRequest.objective")
        validate_no_sensitive_values(v, "ResearchRequest.objective")
        return v

    @model_validator(mode="after")
    def validate_tenancy_and_fingerprint(self) -> ResearchRequest:
        if self.evidence_bundle and self.evidence_bundle.organization_id != self.organization_id:
            raise ResearchTenantIsolationError(
                f"Evidence bundle tenant '{self.evidence_bundle.organization_id}' does not match request tenant '{self.organization_id}'."
            )
        if not self.fingerprint:
            self.fingerprint = compute_research_fingerprint(
                organization_id=self.organization_id,
                objective=self.objective,
                evidence_bundle_id=self.evidence_bundle_id,
                evidence_ids=self.evidence_references,
            )
        return self


class ResearchResult(BaseModel):
    """Structured research output delivered to the agent state and downstream pipeline."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    research_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    status: str = Field(default="COMPLETED", min_length=1, max_length=64)
    summary: str = Field(..., min_length=1, max_length=8192)
    findings: List[ResearchFinding] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    citation_ids: List[str] = Field(default_factory=list)
    conflicts: List[AgentConflict] = Field(default_factory=list)
    limitations: List[AgentLimitation] = Field(default_factory=list)
    source_summary: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = Field(..., min_length=1, max_length=64)
    created_by_node: str = Field(default="research_agent", min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("summary", mode="after")
    @classmethod
    def validate_summary_safety(cls, v: str) -> str:
        validate_no_forbidden_keys({"summary": v}, "ResearchResult.summary")
        validate_no_sensitive_values(v, "ResearchResult.summary")
        validate_no_reasoning_content(v, "ResearchResult.summary")
        return v
