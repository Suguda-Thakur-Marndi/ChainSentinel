"""Strongly typed domain contracts for the RiskWise Decision Agent (Phase 9 Step 8).

Defines DecisionRequest, DecisionCandidate, DecisionConstraint, DecisionRationale,
DecisionResult, DecisionType, DecisionStatus, DecisionCandidateStatus, DecisionBasis,
and deterministic UUIDv5 identity and SHA-256 fingerprinting helpers.

Architectural Invariants:
- ConfigDict(extra="forbid", validate_assignment=True) prevents arbitrary or injected fields.
- Decision is a SELECTION OF CANDIDATE RESPONSES; it is NOT human approval, operational execution, or mathematical optimization.
- Stops strictly before approval: never sets status to APPROVED; requires_human_approval is enforced.
- Deterministic ID generation (UUIDv5) and fingerprinting (SHA-256) over canonical inputs.
- Never fabricates decision probabilities, action probabilities, or ungrounded optimal claims.
- Strict multi-tenant isolation across all scenario, prediction, risk, and recommendation references.
- Scrubs credentials, sensitive tokens, and hidden chain-of-thought monologue.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents.contracts import (
    AgentLimitation,
    validate_no_forbidden_keys,
    validate_no_reasoning_content,
    validate_no_sensitive_values,
)
from app.agents.decision.errors import (
    DecisionAgentError,
    DecisionTenantIsolationError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
    UnsupportedDecisionTypeError,
)
from app.agents.errors import AgentGraphError
from app.rag.contracts import RAG_UUID_NAMESPACE


def _unwrap_domain_errors(exc: ValidationError) -> None:
    for err in exc.errors():
        ctx_err = err.get("ctx", {}).get("error")
        if isinstance(ctx_err, (DecisionAgentError, AgentGraphError)):
            raise ctx_err from exc
    raise exc


class DecisionBaseModel(BaseModel):
    """Base model for decision contracts with transparent domain exception propagation."""

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            _unwrap_domain_errors(exc)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *args: Any,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[Any] = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return super().model_validate(
                obj, *args, strict=strict, from_attributes=from_attributes, context=context, **kwargs
            )
        except ValidationError as exc:
            _unwrap_domain_errors(exc)


class DecisionType(str, Enum):
    """Supported decision taxonomy across Phase 9 and Phase 15."""

    # Phase 9 taxonomy
    OPERATIONAL_REVIEW = "OPERATIONAL_REVIEW"
    OPERATIONAL_RESPONSE = "OPERATIONAL_RESPONSE"
    DISRUPTION_MITIGATION = "DISRUPTION_MITIGATION"
    MONITORING = "MONITORING"
    ESCALATION = "ESCALATION"

    # Phase 15 operational response taxonomy
    REROUTE_SHIPMENT = "REROUTE_SHIPMENT"
    SELECT_ROUTE = "SELECT_ROUTE"
    REALLOCATE_CARRIER = "REALLOCATE_CARRIER"
    REALLOCATE_FACILITY = "REALLOCATE_FACILITY"
    EXPEDITE = "EXPEDITE"
    HOLD = "HOLD"
    MONITOR = "MONITOR"
    NO_ACTION = "NO_ACTION"


class DecisionStatus(str, Enum):
    """Lifecycle and execution status of a DecisionResult across Phase 9 and Phase 15."""

    # Phase 9 statuses
    READY = "READY"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED = "BLOCKED"
    INVALID = "INVALID"

    # Phase 15 statuses
    RECOMMENDED = "RECOMMENDED"
    CONDITIONAL = "CONDITIONAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_FEASIBLE_OPTION = "NO_FEASIBLE_OPTION"
    NO_ACTION_RECOMMENDED = "NO_ACTION_RECOMMENDED"
    FAILED = "FAILED"


class DecisionCandidateStatus(str, Enum):
    """Lifecycle status of an individual decision candidate."""

    PROPOSED = "PROPOSED"
    CANDIDATE = "CANDIDATE"
    PREFERRED = "PREFERRED"
    ALTERNATIVE = "ALTERNATIVE"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"


class DecisionBasis(str, Enum):
    """Authoritative foundation category for a decision candidate or rationale."""

    SCENARIO = "SCENARIO"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    PREDICTION = "PREDICTION"
    RECOMMENDATION = "RECOMMENDATION"
    CONSTRAINT = "CONSTRAINT"
    EVIDENCE = "EVIDENCE"
    OPTIMIZATION = "OPTIMIZATION"
    SIMULATION = "SIMULATION"
    POLICY = "POLICY"



# ==============================================================================
# Phase 15 Strongly Typed Domain Synthesis Models
# ==============================================================================

class AlternativeEvaluation(DecisionBaseModel):
    """Authoritative candidate alternative evaluated and compared by the Decision Agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    alternative_id: str = Field(..., min_length=1, max_length=128)
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field(..., min_length=1, max_length=64)
    is_selected: bool = Field(default=False)
    is_feasible: bool = Field(default=True)
    objective_value: Optional[float] = None
    cost: Optional[float] = None
    cost_estimate: Optional[float] = None
    delay_minutes: Optional[float] = None
    delay_hours: Optional[float] = None
    risk_score: Optional[float] = None
    metrics: Dict[str, float] = Field(default_factory=dict)
    rejection_reason: Optional[str] = Field(default=None, max_length=500)
    tradeoffs: Dict[str, Any] = Field(default_factory=dict)
    evidence_references: List[str] = Field(default_factory=list)


class DecisionOptimizationSummary(DecisionBaseModel):
    """Authoritative mathematical optimization outcome summary evaluated by the Decision Agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    optimization_id: str = Field(..., min_length=1, max_length=64)
    domain: str = Field(..., min_length=1, max_length=64)
    solver_status: str = Field(..., min_length=1, max_length=32)
    objective_type: str = Field(..., min_length=1, max_length=64)
    objective_value: Optional[float] = None
    selected_alternatives_count: int = Field(default=0, ge=0)
    solver_wall_time_ms: float = Field(default=0.0, ge=0.0)
    is_optimal: bool = Field(default=False)
    time_limit_reached: bool = Field(default=False)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class DecisionRiskSummary(DecisionBaseModel):
    """Authoritative risk engine summary evaluated by the Decision Agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    risk_assessment_id: Optional[str] = Field(default=None, max_length=64)
    risk_level: str = Field(default="LOW", max_length=32)
    risk_score: Optional[float] = None
    risk_drivers: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)


class DecisionPredictionSummary(DecisionBaseModel):
    """Authoritative ML delay prediction summary evaluated by the Decision Agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_id: Optional[str] = Field(default=None, max_length=64)
    status: str = Field(default="NOT_AVAILABLE", max_length=32)
    predicted_delay_minutes: Optional[float] = None
    confidence_lower: Optional[float] = None
    confidence_upper: Optional[float] = None
    model_name: Optional[str] = Field(default=None, max_length=64)


class DecisionScenarioSummary(DecisionBaseModel):
    """Authoritative simulation scenario summary evaluated by the Decision Agent."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    scenario_id: Optional[str] = Field(default=None, max_length=64)
    scenario_type: Optional[str] = Field(default=None, max_length=64)
    expected_delay_minutes: Optional[float] = None
    affected_nodes: List[str] = Field(default_factory=list)
    affected_edges: List[str] = Field(default_factory=list)


def generate_deterministic_decision_id(
    organization_id: Union[str, Any],
    scenario_id: Optional[str] = None,
    risk_assessment_id: Optional[str] = None,
    prediction_id: Optional[str] = None,
    recommendation_ids: Optional[List[str]] = None,
    decision_type: str = "OPERATIONAL_REVIEW",
    target_reference: str = "default_target",
    rule_version: str = "decision_rules_v1.0.0",
    candidate_fingerprint: str = "",
    upstream_scenario_id: Optional[str] = None,
    upstream_risk_id: Optional[str] = None,
    upstream_prediction_id: Optional[str] = None,
    optimization_id: Optional[str] = None,
) -> str:
    """Generate a reproducible UUIDv5 decision identifier from stable canonical inputs.

    Never incorporates volatile timestamps, request IDs, random UUIDs, or trace IDs.
    Supports either a DecisionRequest object or individual parameters.
    """
    if not isinstance(organization_id, str):
        req = organization_id
        organization_id = getattr(req, "organization_id", None)
        dec_type = getattr(req, "decision_type", decision_type)
        decision_type = getattr(dec_type, "value", str(dec_type))
        target_reference = (
            getattr(req, "target_reference", None)
            or getattr(req, "shipment_id", None)
            or "default_target"
        )
        scenario_id = getattr(req, "scenario_id", scenario_id)
        risk_assessment_id = getattr(req, "risk_assessment_id", risk_assessment_id)
        prediction_id = getattr(req, "prediction_id", prediction_id)
        optimization_id = getattr(req, "optimization_id", optimization_id)

    if not organization_id or not str(organization_id).strip():
        raise DecisionTenantIsolationError("organization_id must be non-empty to generate decision_id.")
    scen = (scenario_id or upstream_scenario_id or "").strip()
    risk = (risk_assessment_id or upstream_risk_id or "").strip()
    pred = (prediction_id or upstream_prediction_id or "").strip()
    recs = sorted(recommendation_ids or [])
    opt = (optimization_id or "").strip()
    opt_token = f":{opt}" if opt else ""
    token = (
        f"{str(organization_id).strip()}:{str(decision_type).strip()}:{str(target_reference).strip()}:"
        f"{str(rule_version).strip()}:{str(candidate_fingerprint).strip()}:{scen}:{risk}:{pred}:{','.join(recs)}"
        f"{opt_token}"
    )
    raw_uuid = str(uuid.uuid5(RAG_UUID_NAMESPACE, token))
    return f"dec_{raw_uuid}"


def compute_decision_fingerprint(
    organization_id: Any,
    decision_type: str = "OPERATIONAL_REVIEW",
    target_reference: str = "default_target",
    candidates: Optional[List[Dict[str, Any]]] = None,
    constraints: Optional[List[Dict[str, Any]]] = None,
    rationales: Optional[List[Dict[str, Any]]] = None,
    rule_version: str = "decision_rules_v1.0.0",
    scenario_id: Optional[str] = None,
    risk_reference: Optional[Dict[str, Any]] = None,
    prediction_reference: Optional[Dict[str, Any]] = None,
    evidence_references: Optional[List[str]] = None,
    upstream_references: Optional[Dict[str, Any]] = None,
    optimization_id: Optional[str] = None,
    alternatives: Optional[List[Dict[str, Any]]] = None,
    policy_version: Optional[str] = None,
) -> str:
    """Generate a deterministic SHA-256 fingerprint over canonicalized decision content.

    Supports either a DecisionRequest object or individual parameters.
    """
    if hasattr(organization_id, "organization_id"):
        req = organization_id
        organization_id = req.organization_id
        decision_type = req.decision_type.value if hasattr(req.decision_type, "value") else str(req.decision_type)
        target_reference = req.target_reference or req.shipment_id or "default_target"
        candidates = [c.model_dump() if hasattr(c, "model_dump") else c for c in req.candidate_alternatives]
        constraints = [c.model_dump() if hasattr(c, "model_dump") else c for c in req.constraints]
        scenario_id = req.scenario_id
        risk_reference = req.risk_assessment_reference
        prediction_reference = req.prediction_reference
        evidence_references = req.evidence_references
        optimization_id = req.optimization_id
        alternatives = req.candidate_alternatives
        policy_version = req.policy_version

    sorted_candidates = sorted(candidates or [], key=lambda c: str(c.get("candidate_id", "")))
    sorted_constraints = sorted(constraints or [], key=lambda c: str(c.get("name", "")))
    sorted_rationales = sorted(rationales or [], key=lambda r: str(r.get("rule_id", "")))
    sorted_evidence = sorted(evidence_references or [])

    payload: Dict[str, Any] = {
        "organization_id": str(organization_id).strip(),
        "decision_type": str(decision_type).strip(),
        "target_reference": str(target_reference).strip(),
        "rule_version": str(rule_version).strip(),
        "candidates": sorted_candidates,
        "constraints": sorted_constraints,
        "rationales": sorted_rationales,
        "scenario_id": scenario_id or "",
        "risk_reference": risk_reference or {},
        "prediction_reference": prediction_reference or {},
        "evidence_references": sorted_evidence,
        "upstream_references": upstream_references or {},
    }
    if optimization_id:
        payload["optimization_id"] = optimization_id.strip()
    if alternatives:
        payload["alternatives"] = sorted(alternatives, key=lambda a: str(a.get("alternative_id", "")))
    if policy_version:
        payload["policy_version"] = policy_version.strip()

    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()



class DecisionConstraint(DecisionBaseModel):
    """Operational or governance boundary condition applied to decision evaluation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    constraint_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    value: Union[float, int, str, bool]
    unit: Optional[str] = Field(default=None, max_length=32)

    @field_validator("value", mode="after")
    @classmethod
    def validate_constraint_value(cls, v: Union[float, int, str, bool], info: Any) -> Union[float, int, str, bool]:
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                raise InvalidDecisionRequestError(
                    f"DecisionConstraint '{info.data.get('name', 'unknown')}' has non-finite float value."
                )
        if isinstance(v, str):
            validate_no_sensitive_values(v, f"DecisionConstraint.{info.data.get('name', 'val')}")
            validate_no_reasoning_content(v, f"DecisionConstraint.{info.data.get('name', 'val')}")
        return v


class DecisionRationale(DecisionBaseModel):
    """Structured, auditable explanation basis for a decision candidate or recommendation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    basis_type: DecisionBasis = Field(default=DecisionBasis.SCENARIO)
    source_reference: Optional[str] = Field(default=None, max_length=128)
    evidence_references: List[str] = Field(default_factory=list)
    rule_id: str = Field(..., min_length=1, max_length=128)
    finding_ids: List[str] = Field(default_factory=list)
    explanation_code: str = Field(default="DETERMINISTIC_EVALUATION", min_length=1, max_length=128)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("rule_id", "explanation_code", mode="after")
    @classmethod
    def validate_text_safety(cls, v: str, info: Any) -> str:
        validate_no_sensitive_values(v, f"DecisionRationale.{info.field_name}")
        validate_no_reasoning_content(v, f"DecisionRationale.{info.field_name}")
        return v

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "DecisionRationale.provenance")
        return v


class DecisionCandidate(DecisionBaseModel):
    """Structured response option formulated under validated evidence and constraints.

    IMPORTANT: A candidate is an advisory review proposal, NOT an executed action.
    Autonomous execution or setting status=APPROVED is strictly forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    candidate_id: str = Field(..., min_length=1, max_length=64)
    action_type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(default="Decision Candidate", min_length=1, max_length=255)
    description: str = Field(..., min_length=1, max_length=2000)
    priority: Union[int, str] = Field(default="MEDIUM")

    @field_validator("candidate_id", mode="before")
    @classmethod
    def validate_candidate_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidDecisionCandidateError("candidate_id must be non-empty.")
        return v.strip()
    parameters: Dict[str, Any] = Field(default_factory=dict)
    prerequisites: List[str] = Field(default_factory=list)
    constraints: List[DecisionConstraint] = Field(default_factory=list)
    expected_effect: Optional[str] = Field(default=None, max_length=1000)
    evidence_references: List[str] = Field(default_factory=list)
    requires_human_approval: bool = Field(default=True)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default=DecisionCandidateStatus.REQUIRES_APPROVAL.value, min_length=1, max_length=32)

    @field_validator("title", "description", mode="after")
    @classmethod
    def validate_candidate_text(cls, v: str, info: Any) -> str:
        validate_no_sensitive_values(v, f"DecisionCandidate.{info.field_name}")
        validate_no_reasoning_content(v, f"DecisionCandidate.{info.field_name}")
        return v

    @field_validator("parameters", mode="after")
    @classmethod
    def validate_parameters_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "DecisionCandidate.parameters")
        for pk, pv in v.items():
            if isinstance(pv, float) and (math.isnan(pv) or math.isinf(pv)):
                raise InvalidDecisionCandidateError(f"Candidate parameter '{pk}' has non-finite value.")
            if isinstance(pv, str):
                validate_no_sensitive_values(pv, f"DecisionCandidate.parameters.{pk}")
                validate_no_reasoning_content(pv, f"DecisionCandidate.parameters.{pk}")
        return v

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "DecisionCandidate.provenance")
        return v

    @model_validator(mode="after")
    def validate_candidate_invariants(self) -> DecisionCandidate:
        # Prevent autonomous execution claims
        if self.status == "APPROVED" and self.requires_human_approval:
            raise InvalidDecisionCandidateError(
                "Decision candidate cannot be marked APPROVED autonomously; requires human authorization."
            )
        return self


class DecisionRequest(DecisionBaseModel):
    """Strongly typed input request dispatched to the Decision Agent / Rule Engine.

    Accepts validated references only. Extra arbitrary dictionaries are strictly forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: Optional[str] = Field(default=None, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    decision_type: DecisionType = Field(default=DecisionType.OPERATIONAL_REVIEW)
    target_reference: Optional[str] = Field(default=None, max_length=128)

    # Upstream scenario bindings
    scenario_id: Optional[str] = Field(default=None, max_length=64)
    scenario_reference: Optional[Dict[str, Any]] = None
    scenario_result: Optional[Dict[str, Any]] = None
    scenario_definition: Optional[Dict[str, Any]] = None

    # Upstream risk bindings
    risk_assessment_id: Optional[str] = Field(default=None, max_length=64)
    risk_assessment_reference: Optional[Dict[str, Any]] = None

    # Upstream prediction bindings
    prediction_id: Optional[str] = Field(default=None, max_length=64)
    prediction_reference: Optional[Dict[str, Any]] = None
    prediction_result: Optional[Dict[str, Any]] = None

    # Upstream optimization bindings (Phase 14)
    optimization_id: Optional[str] = Field(default=None, max_length=64)
    optimization_reference: Optional[Dict[str, Any]] = None
    optimization_result: Optional[Dict[str, Any]] = None

    # Upstream simulation bindings (Phase 13)
    simulation_id: Optional[str] = Field(default=None, max_length=64)
    simulation_reference: Optional[Dict[str, Any]] = None
    simulation_result: Optional[Dict[str, Any]] = None

    # Decision objectives & candidate options
    objective_type: Optional[str] = Field(default=None, max_length=64)
    candidate_alternatives: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)

    # Subject bindings
    shipment_id: Optional[str] = Field(default=None, max_length=64)
    shipment_ids: List[str] = Field(default_factory=list, max_length=50)
    supplier_id: Optional[str] = Field(default=None, max_length=64)
    supplier_ids: List[str] = Field(default_factory=list, max_length=50)

    # Upstream recommendations
    recommendation_references: List[str] = Field(default_factory=list, max_length=50)
    available_recommendations: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)

    # Grounding & constraints
    evidence_references: List[str] = Field(default_factory=list, max_length=100)
    constraints: List[DecisionConstraint] = Field(default_factory=list, max_length=50)
    planning_horizon_hours: Optional[float] = Field(default=None)

    # Policy & freshness
    freshness_timestamp: Optional[datetime] = None
    policy_version: Optional[str] = Field(default="1.0.0", max_length=32)

    # Telemetry correlation
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    trace_id: Optional[str] = Field(default=None, max_length=64)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidDecisionRequestError("DecisionRequest organization_id must be a non-empty string.")
        return v.strip()

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "DecisionRequest.provenance")
        return v

    @model_validator(mode="after")
    def validate_tenant_consistency(self) -> DecisionRequest:
        """Enforce strict multi-tenant isolation across all upstream references and payloads."""
        org = self.organization_id

        # 1. Scenario tenant check
        for scen_obj, label in [
            (self.scenario_reference, "scenario_reference"),
            (self.scenario_result, "scenario_result"),
            (self.scenario_definition, "scenario_definition"),
        ]:
            if scen_obj and isinstance(scen_obj, dict):
                ref_org = scen_obj.get("organization_id")
                if ref_org and ref_org != org:
                    raise DecisionTenantIsolationError(
                        f"{label} tenant '{ref_org}' does not match request organization_id '{org}'."
                    )

        # 2. Risk assessment reference tenant check
        if self.risk_assessment_reference and isinstance(self.risk_assessment_reference, dict):
            ref_org = self.risk_assessment_reference.get("organization_id")
            if ref_org and ref_org != org:
                raise DecisionTenantIsolationError(
                    f"Risk assessment reference tenant '{ref_org}' does not match request organization_id '{org}'."
                )

        # 3. Prediction reference / result tenant check
        for pred_obj, label in [
            (self.prediction_reference, "prediction_reference"),
            (self.prediction_result, "prediction_result"),
        ]:
            if pred_obj and isinstance(pred_obj, dict):
                ref_org = pred_obj.get("organization_id")
                if ref_org and ref_org != org:
                    raise DecisionTenantIsolationError(
                        f"{label} tenant '{ref_org}' does not match request organization_id '{org}'."
                    )

        # 4. Optimization reference / result tenant check
        for opt_obj, label in [
            (self.optimization_reference, "optimization_reference"),
            (self.optimization_result, "optimization_result"),
        ]:
            if opt_obj and isinstance(opt_obj, dict):
                ref_org = opt_obj.get("organization_id")
                if ref_org and ref_org != org:
                    raise DecisionTenantIsolationError(
                        f"{label} tenant '{ref_org}' does not match request organization_id '{org}'."
                    )

        # 5. Simulation reference / result tenant check
        for sim_obj, label in [
            (self.simulation_reference, "simulation_reference"),
            (self.simulation_result, "simulation_result"),
        ]:
            if sim_obj and isinstance(sim_obj, dict):
                ref_org = sim_obj.get("organization_id")
                if ref_org and ref_org != org:
                    raise DecisionTenantIsolationError(
                        f"{label} tenant '{ref_org}' does not match request organization_id '{org}'."
                    )

        # 6. Recommendation references tenant check
        for rec_obj in self.available_recommendations:
            if isinstance(rec_obj, dict):
                ref_org = rec_obj.get("organization_id")
                if ref_org and ref_org != org:
                    raise DecisionTenantIsolationError(
                        f"Recommendation tenant '{ref_org}' does not match request organization_id '{org}'."
                    )

        # 7. Prefixed evidence references tenant check
        for ref in self.evidence_references:
            if ":" in ref:
                prefix = ref.split(":", 1)[0]
                if prefix.startswith("org_") and prefix != org:
                    raise DecisionTenantIsolationError(
                        f"Evidence reference '{ref}' belongs to foreign tenant, expected '{org}'."
                    )

        return self


class DecisionResult(DecisionBaseModel):
    """Strongly typed output returned by the Decision Agent.

    Encapsulates candidate options, rationales, constraints, limitations, and auditable fingerprint.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    decision_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    decision_type: DecisionType = Field(default=DecisionType.OPERATIONAL_REVIEW)
    status: str = Field(default=DecisionStatus.REQUIRES_APPROVAL.value, min_length=1, max_length=64)
    candidates: List[DecisionCandidate] = Field(default_factory=list)
    preferred_candidate: Optional[DecisionCandidate] = None
    preferred_candidate_id: Optional[str] = Field(default=None, max_length=64)
    scenario_id: Optional[str] = Field(default=None, max_length=64)
    scenario_fingerprint: Optional[str] = Field(default=None, max_length=64)
    risk_assessment_id: Optional[str] = Field(default=None, max_length=64)
    prediction_id: Optional[str] = Field(default=None, max_length=64)
    planning_horizon_hours: Optional[float] = Field(default=None)
    rationales: List[DecisionRationale] = Field(default_factory=list)
    constraints: List[DecisionConstraint] = Field(default_factory=list)
    requires_human_approval: bool = Field(default=True)
    upstream_references: Dict[str, Any] = Field(default_factory=dict)
    evidence_references: List[str] = Field(default_factory=list)
    limitations: List[AgentLimitation] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: Optional[str] = Field(default=None, max_length=64)
    rule_version: str = Field(default="decision_rules_v1.0.0", min_length=1, max_length=64)
    created_by_node: str = Field(default="decision_agent", min_length=1, max_length=64)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Phase 15 Synthesis Extensions
    optimization_id: Optional[str] = Field(default=None, max_length=64)
    optimization_summary: Optional[DecisionOptimizationSummary] = None
    simulation_id: Optional[str] = Field(default=None, max_length=64)
    scenario_summary: Optional[DecisionScenarioSummary] = None
    risk_summary: Optional[DecisionRiskSummary] = None
    prediction_summary: Optional[DecisionPredictionSummary] = None
    alternatives_considered: List[AlternativeEvaluation] = Field(default_factory=list)
    selected_alternative_id: Optional[str] = Field(default=None, max_length=128)
    tradeoffs: Dict[str, Any] = Field(default_factory=dict)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    decision_policy_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    freshness_timestamp: Optional[datetime] = None
    expiry_timestamp: Optional[datetime] = None

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise DecisionTenantIsolationError("DecisionResult organization_id must be non-empty.")
        return v.strip()

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "DecisionResult.provenance")
        return v

    @model_validator(mode="after")
    def validate_status_and_candidate_consistency(self) -> DecisionResult:
        """Enforce that actionable statuses require valid candidates and fingerprint."""
        if self.status in (DecisionStatus.READY.value, DecisionStatus.REQUIRES_APPROVAL.value):
            if not self.candidates:
                raise InvalidDecisionRequestError(
                    f"DecisionResult with status '{self.status}' must contain at least one candidate."
                )
            if not self.fingerprint:
                raise InvalidDecisionRequestError(
                    f"DecisionResult with status '{self.status}' must contain a valid fingerprint."
                )
        if self.status in (DecisionStatus.RECOMMENDED.value, DecisionStatus.CONDITIONAL.value):
            if not self.candidates and not self.selected_alternative_id:
                raise InvalidDecisionRequestError(
                    f"DecisionResult with status '{self.status}' must contain at least one candidate or selected alternative."
                )
            if not self.fingerprint:
                raise InvalidDecisionRequestError(
                    f"DecisionResult with status '{self.status}' must contain a valid fingerprint."
                )
        return self

    @property
    def primary_rationale(self) -> str:
        """Convenience property extracting the primary rationale text or explanation code."""
        if self.rationales:
            return self.rationales[0].explanation_code or ""
        if self.candidates:
            return self.candidates[0].description or ""
        return ""

