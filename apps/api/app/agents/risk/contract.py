"""Strongly typed contracts for the RiskWise Risk Agent.

Defines RiskAgentRequest and RiskAgentResult — the typed boundary between the
LangGraph orchestration layer and the authoritative Phase 7 Risk Engine.

Security invariants:
- User-supplied risk_score / risk_level fields are REJECTED on input.
- Output fields are populated exclusively from the authoritative RiskAssessment.
- organization_id is immutable throughout.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.contracts import (
    AgentLimitation,
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.research.contract import ResearchResult
from app.agents.risk.errors import InvalidRiskRequestError, RiskTenantIsolationError
from app.rag.contracts import RAG_UUID_NAMESPACE


def generate_deterministic_risk_request_id(
    organization_id: str,
    research_id: str,
    objective: str,
) -> str:
    """Generate a reproducible UUIDv5 risk request identifier from tenant, research, and objective."""
    if not organization_id or not organization_id.strip():
        raise RiskTenantIsolationError("organization_id must be non-empty to generate risk_request_id")
    token = f"{organization_id.strip()}:risk:{research_id.strip()}:{objective.strip().lower()}"
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


class RiskAgentRequest(BaseModel):
    """Strongly typed input for the Risk Agent.

    Receives validated research output and identity fields.
    Explicitly rejects any user-supplied risk scores or levels.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    risk_request_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    objective: str = Field(..., min_length=1, max_length=4096)
    actor_id: Optional[str] = Field(default=None, max_length=64)
    research_id: Optional[str] = Field(default=None, max_length=64)
    research_result: Optional[ResearchResult] = None
    evidence_bundle_id: Optional[str] = Field(default=None, max_length=64)
    evidence_references: List[str] = Field(default_factory=list)
    citation_references: List[str] = Field(default_factory=list)
    scope: str = Field(default="GLOBAL", max_length=64)
    scope_entity_id: Optional[str] = Field(default=None, max_length=64)
    scope_entity_type: Optional[str] = Field(default=None, max_length=64)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    trace_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("organization_id", "objective", mode="before")
    @classmethod
    def validate_non_empty(cls, v: Any, info: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidRiskRequestError(
                f"Field '{info.field_name}' must be a non-empty string in RiskAgentRequest."
            )
        return v.strip()

    @field_validator("objective", mode="after")
    @classmethod
    def validate_objective_safety(cls, v: str) -> str:
        validate_no_forbidden_keys({"objective": v}, "RiskAgentRequest.objective")
        validate_no_sensitive_values(v, "RiskAgentRequest.objective")
        validate_no_reasoning_content(v, "RiskAgentRequest.objective")
        return v

    @model_validator(mode="after")
    def validate_tenant_isolation(self) -> "RiskAgentRequest":
        """Fail closed if research result belongs to a different tenant."""
        if self.research_result and self.research_result.organization_id != self.organization_id:
            raise RiskTenantIsolationError(
                f"ResearchResult tenant '{self.research_result.organization_id}' does not match "
                f"RiskAgentRequest tenant '{self.organization_id}'."
            )
        return self


class RiskAgentResult(BaseModel):
    """Structured output of the Risk Agent after authoritative Risk Engine evaluation.

    All risk_score, risk_level, factor_ids, fingerprint values come exclusively
    from the Phase 7 RiskAssessment. They are never user-supplied or invented.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    risk_request_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    status: str = Field(default="COMPLETED", min_length=1, max_length=64)

    # Authoritative assessment references (sourced from RiskAssessment)
    assessment_id: str = Field(..., min_length=1, max_length=64)
    assessment_fingerprint: Optional[str] = Field(default=None, max_length=128)
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    risk_level: Optional[str] = Field(default=None, max_length=32)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    factor_count: int = Field(default=0, ge=0)
    factor_ids: List[str] = Field(default_factory=list)
    evidence_count: int = Field(default=0, ge=0)
    evidence_ids: List[str] = Field(default_factory=list)

    # Alert and recommendation references (IDs only — no duplication)
    alert_ids: List[str] = Field(default_factory=list)
    recommendation_ids: List[str] = Field(default_factory=list)

    # Structured limitations from translation or engine
    limitations: List[AgentLimitation] = Field(default_factory=list)

    # Provenance and traceability
    assessment: Optional[Any] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("risk_level", mode="after")
    @classmethod
    def validate_risk_level_enum(cls, v: Optional[str]) -> Optional[str]:
        """Ensure risk_level is a valid Phase 7 RiskLevel value if provided."""
        if v is None:
            return v
        allowed = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        if v.upper() not in allowed:
            raise InvalidRiskRequestError(
                f"Invalid risk_level '{v}'; must be one of {sorted(allowed)}."
            )
        return v.upper()
