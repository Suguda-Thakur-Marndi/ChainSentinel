"""Strongly typed domain contracts for the RiskWise Scenario Agent.

Defines ScenarioRequest, ScenarioDefinition, ScenarioParameter, ScenarioTrigger,
ScenarioConstraint, ScenarioResult, ScenarioType, ScenarioStatus, and deterministic
identity and fingerprinting helpers.

Architectural Invariants:
- ConfigDict(extra="forbid", validate_assignment=True) prevents client-injected or arbitrary fields.
- A Scenario is a DEFINITION of a possible future state; it is NOT a prediction, simulation, or optimization.
- Deterministic ID generation (UUIDv5) and fingerprinting (SHA-256) over canonicalized inputs.
- Never fabricates probability, delay, disruption severity, or port/supplier closures.
- Enforces strict tenant isolation across all references, parameters, and definitions.
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
from app.agents.errors import AgentGraphError
from app.agents.scenario.errors import (
    InvalidScenarioParameterError,
    InvalidScenarioRequestError,
    ScenarioAgentError,
    ScenarioTenantIsolationError,
    UnsupportedScenarioTypeError,
)
from app.rag.contracts import RAG_UUID_NAMESPACE


def _unwrap_domain_errors(exc: ValidationError) -> None:
    for err in exc.errors():
        ctx_err = err.get("ctx", {}).get("error")
        if isinstance(ctx_err, (ScenarioAgentError, AgentGraphError)):
            raise ctx_err from exc
    raise exc


class ScenarioBaseModel(BaseModel):
    """Base model for scenario contracts with transparent domain exception propagation."""

    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            _unwrap_domain_errors(exc)

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[Any] = None,
    ) -> Any:
        try:
            return super().model_validate(
                obj, strict=strict, from_attributes=from_attributes, context=context
            )
        except ValidationError as exc:
            _unwrap_domain_errors(exc)



class ScenarioType(str, Enum):
    """Supported scenario taxonomy."""

    SHIPMENT_DELAY = "SHIPMENT_DELAY"
    PORT_DISRUPTION = "PORT_DISRUPTION"
    WEATHER_DISRUPTION = "WEATHER_DISRUPTION"
    SUPPLIER_DISRUPTION = "SUPPLIER_DISRUPTION"
    ROUTE_DISRUPTION = "ROUTE_DISRUPTION"


class ScenarioStatus(str, Enum):
    """Lifecycle and execution status of a ScenarioDefinition."""

    DRAFT = "DRAFT"
    READY = "READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVALID = "INVALID"


def generate_deterministic_scenario_id(
    organization_id: str,
    scenario_type: str,
    target_reference: str,
    parameter_fingerprint: str,
    upstream_prediction_id: Optional[str] = None,
    upstream_risk_id: Optional[str] = None,
) -> str:
    """Generate a reproducible UUIDv5 scenario identifier from stable canonical inputs.

    Never incorporates volatile timestamps, request IDs, random UUIDs, or trace IDs.
    """
    if not organization_id or not organization_id.strip():
        raise ScenarioTenantIsolationError("organization_id must be non-empty to generate scenario_id.")
    pred_part = (upstream_prediction_id or "").strip()
    risk_part = (upstream_risk_id or "").strip()
    token = (
        f"{organization_id.strip()}:{scenario_type.strip()}:{target_reference.strip()}:"
        f"{parameter_fingerprint.strip()}:{pred_part}:{risk_part}"
    )
    return str(uuid.uuid5(RAG_UUID_NAMESPACE, token))


def compute_scenario_fingerprint(
    organization_id: str,
    scenario_type: str,
    target_reference: str,
    parameters: List[Dict[str, Any]],
    constraints: Optional[List[Dict[str, Any]]] = None,
    trigger: Optional[Dict[str, Any]] = None,
    upstream_references: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate a deterministic SHA-256 fingerprint over canonicalized scenario content.

    Ensures stable key ordering and representation.
    """
    sorted_params = sorted(parameters, key=lambda p: str(p.get("name", "")))
    sorted_constraints = sorted(constraints or [], key=lambda c: str(c.get("name", "")))

    payload = {
        "organization_id": organization_id.strip(),
        "scenario_type": scenario_type.strip(),
        "target_reference": target_reference.strip(),
        "parameters": sorted_params,
        "constraints": sorted_constraints,
        "trigger": trigger or {},
        "upstream_references": upstream_references or {},
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ScenarioParameter(ScenarioBaseModel):
    """Strongly typed parameter defining an explicit what-if scenario perturbation.

    Arbitrary unvalidated dictionaries and fabricated numbers are strictly forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(..., min_length=1, max_length=128)
    value: Union[float, int, str, bool]
    unit: Optional[str] = Field(default=None, max_length=32)
    source: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., min_length=1, max_length=64)
    evidence_references: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("value", mode="after")
    @classmethod
    def validate_parameter_value(cls, v: Union[float, int, str, bool], info: Any) -> Union[float, int, str, bool]:
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                raise InvalidScenarioParameterError(
                    f"Parameter '{info.data.get('name', 'unknown')}' has non-finite float value."
                )
        if isinstance(v, str):
            validate_no_sensitive_values(v, f"ScenarioParameter.{info.data.get('name', 'val')}")
            validate_no_reasoning_content(v, f"ScenarioParameter.{info.data.get('name', 'val')}")
        return v

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "ScenarioParameter.provenance")
        for val in v.values():
            if isinstance(val, str):
                validate_no_sensitive_values(val, "ScenarioParameter.provenance")
        return v


class ScenarioTrigger(ScenarioBaseModel):
    """Strongly typed condition under which the what-if scenario is posited to occur.

    Rejects arbitrary code execution, strings intended for eval(), or dynamic syntax.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    trigger_type: str = Field(..., min_length=1, max_length=64)
    source_reference: Optional[str] = Field(default=None, max_length=128)
    condition: str = Field(default="EQUALS", min_length=1, max_length=32)
    threshold: Optional[float] = None
    evidence_references: List[str] = Field(default_factory=list)

    @field_validator("condition", mode="after")
    @classmethod
    def validate_condition_syntax(cls, v: str) -> str:
        # Strictly forbid dynamic code injection attempts
        forbidden_tokens = ["eval", "exec", "__import__", "lambda", ";", "os.", "sys."]
        for token in forbidden_tokens:
            if token in v.lower():
                raise InvalidScenarioParameterError(f"Dynamic code or expression token '{token}' in trigger condition is strictly forbidden.")
        return v.strip().upper()

    @field_validator("threshold", mode="after")
    @classmethod
    def validate_threshold_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise InvalidScenarioParameterError("Trigger threshold must be a finite number.")
        return v


class ScenarioConstraint(ScenarioBaseModel):
    """Strongly typed operational boundary condition for the scenario."""

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
                raise InvalidScenarioParameterError(f"Constraint '{info.data.get('name', 'unknown')}' has non-finite float value.")
        return v


class ScenarioDefinition(ScenarioBaseModel):
    """Complete, immutable definition of a what-if scenario ready for downstream consumption.

    Contains no simulation metrics, no optimization solutions, and no operational changes.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    scenario_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    scenario_type: ScenarioType = Field(default=ScenarioType.SHIPMENT_DELAY)
    target_reference: str = Field(..., min_length=1, max_length=128)
    parameters: List[ScenarioParameter] = Field(..., min_length=1)
    trigger: Optional[ScenarioTrigger] = None
    constraints: List[ScenarioConstraint] = Field(default_factory=list)
    horizon_hours: Optional[float] = None
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    fingerprint: str = Field(..., min_length=1, max_length=64)
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ScenarioTenantIsolationError("ScenarioDefinition organization_id must be non-empty.")
        return v.strip()

    @field_validator("horizon_hours", mode="before")
    @classmethod
    def validate_horizon(cls, v: Any) -> Optional[float]:
        if v is not None:
            try:
                val = float(v)
            except (ValueError, TypeError):
                raise InvalidScenarioParameterError("horizon_hours must be a valid float.")
            if math.isnan(val) or math.isinf(val):
                raise InvalidScenarioParameterError("horizon_hours must be a finite number.")
            if val <= 0.0:
                raise InvalidScenarioParameterError("horizon_hours must be strictly positive.")
            return val
        return None

    @model_validator(mode="after")
    def validate_effective_timestamps(self) -> ScenarioDefinition:
        if self.effective_from and self.effective_until:
            if self.effective_from > self.effective_until:
                raise InvalidScenarioParameterError(
                    f"effective_from ({self.effective_from.isoformat()}) cannot be after effective_until ({self.effective_until.isoformat()})."
                )
        return self

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "ScenarioDefinition.provenance")
        return v


class ScenarioRequest(ScenarioBaseModel):
    """Strongly typed input request dispatched to the Scenario Agent/Generator.

    Accepts validated references only. Extra or arbitrary dictionaries are strictly forbidden.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    scenario_id: Optional[str] = Field(default=None, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    shipment_id: Optional[str] = Field(default=None, max_length=64)
    scenario_type: ScenarioType = Field(default=ScenarioType.SHIPMENT_DELAY)
    target_reference: Optional[str] = Field(default=None, max_length=128)
    risk_assessment_id: Optional[str] = Field(default=None, max_length=64)
    risk_assessment_reference: Optional[Dict[str, Any]] = None
    prediction_id: Optional[str] = Field(default=None, max_length=64)
    prediction_reference: Optional[Dict[str, Any]] = None
    prediction_result: Optional[Dict[str, Any]] = None
    evidence_references: List[str] = Field(default_factory=list)
    parameters: List[ScenarioParameter] = Field(default_factory=list)
    trigger: Optional[ScenarioTrigger] = None
    constraints: List[ScenarioConstraint] = Field(default_factory=list)
    horizon_hours: Optional[float] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = Field(default=None, max_length=64)
    trace_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise InvalidScenarioRequestError("ScenarioRequest organization_id must be a non-empty string.")
        return v.strip()

    @field_validator("horizon_hours", mode="before")
    @classmethod
    def validate_horizon(cls, v: Any) -> Optional[float]:
        if v is not None:
            try:
                val = float(v)
            except (ValueError, TypeError):
                raise InvalidScenarioRequestError("horizon_hours must be a valid float.")
            if math.isnan(val) or math.isinf(val):
                raise InvalidScenarioRequestError("horizon_hours must be a finite number.")
            if val <= 0.0:
                raise InvalidScenarioRequestError("horizon_hours must be strictly positive.")
            return val
        return None

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "ScenarioRequest.provenance")
        return v

    @model_validator(mode="after")
    def validate_tenant_consistency(self) -> ScenarioRequest:
        """Enforce strict multi-tenant isolation across all upstream references and parameters."""
        org = self.organization_id

        # 1. Validate risk assessment reference tenant
        if self.risk_assessment_reference and isinstance(self.risk_assessment_reference, dict):
            ref_org = self.risk_assessment_reference.get("organization_id")
            if ref_org and ref_org != org:
                raise ScenarioTenantIsolationError(
                    f"Risk assessment reference tenant '{ref_org}' does not match request organization_id '{org}'."
                )

        # 2. Validate prediction reference / result tenant
        for pred_obj, label in [
            (self.prediction_reference, "prediction_reference"),
            (self.prediction_result, "prediction_result"),
        ]:
            if pred_obj and isinstance(pred_obj, dict):
                ref_org = pred_obj.get("organization_id")
                if ref_org and ref_org != org:
                    raise ScenarioTenantIsolationError(
                        f"{label} tenant '{ref_org}' does not match request organization_id '{org}'."
                    )

        # 3. Validate prefixed references in evidence_references
        for ref in self.evidence_references:
            if ":" in ref:
                prefix = ref.split(":", 1)[0]
                if prefix.startswith("org_") and prefix != org:
                    raise ScenarioTenantIsolationError(
                        f"Evidence reference '{ref}' belongs to foreign tenant, expected '{org}'."
                    )

        return self


class ScenarioResult(ScenarioBaseModel):
    """Strongly typed output returned by the Scenario Agent.

    Encapsulates the generated ScenarioDefinition (if READY), status, limitations,
    and auditable provenance.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    scenario_id: str = Field(..., min_length=1, max_length=64)
    organization_id: str = Field(..., min_length=1, max_length=64)
    scenario_definition: Optional[ScenarioDefinition] = None
    status: str = Field(default=ScenarioStatus.READY.value, min_length=1, max_length=64)
    upstream_references: Dict[str, Any] = Field(default_factory=dict)
    evidence_references: List[str] = Field(default_factory=list)
    limitations: List[AgentLimitation] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: Optional[str] = Field(default=None, max_length=64)
    created_by_node: str = Field(default="scenario_agent", min_length=1, max_length=64)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("organization_id", mode="before")
    @classmethod
    def validate_org_id(cls, v: Any) -> str:
        if not v or not isinstance(v, str) or not v.strip():
            raise ScenarioTenantIsolationError("ScenarioResult organization_id must be non-empty.")
        return v.strip()

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_provenance_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        validate_no_forbidden_keys(v, "ScenarioResult.provenance")
        return v

    @model_validator(mode="after")
    def validate_status_and_definition_consistency(self) -> ScenarioResult:
        """Enforce that a READY status requires a valid scenario_definition and fingerprint."""
        if self.status == ScenarioStatus.READY.value:
            if self.scenario_definition is None:
                raise InvalidScenarioRequestError("ScenarioResult with status READY must contain a valid scenario_definition.")
            if not self.fingerprint:
                raise InvalidScenarioRequestError("ScenarioResult with status READY must contain a fingerprint.")
            if self.scenario_definition.organization_id != self.organization_id:
                raise ScenarioTenantIsolationError(
                    f"ScenarioDefinition organization '{self.scenario_definition.organization_id}' "
                    f"does not match ScenarioResult organization '{self.organization_id}'."
                )
        return self
