"""Deterministic Scenario Generator for the RiskWise Scenario Agent.

Converts validated upstream prediction results, risk assessment context, and structured
evidence references into immutable, reproducible ScenarioDefinition instances.

Architectural Invariants:
- Pure deterministic transformation: same validated inputs produce identical scenario IDs and fingerprints.
- Zero LLM generation, zero heuristic guessing, zero random numbers.
- Never fabricates delay, disruption severity, port closures, or scenario probabilities.
- Never converts prediction confidence or risk score into scenario probability.
- If upstream prediction is unavailable or incomplete, returns INSUFFICIENT_EVIDENCE.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.scenario.contract import (
    ScenarioConstraint,
    ScenarioDefinition,
    ScenarioParameter,
    ScenarioRequest,
    ScenarioResult,
    ScenarioStatus,
    ScenarioTrigger,
    ScenarioType,
    compute_scenario_fingerprint,
    generate_deterministic_scenario_id,
)
from app.agents.scenario.errors import (
    InvalidScenarioParameterError,
    ScenarioTenantIsolationError,
    UnsupportedScenarioTypeError,
)


class ScenarioGenerator:
    """Deterministic generator for strongly typed What-If Scenario Definitions."""

    @classmethod
    def generate(cls, request: ScenarioRequest) -> Tuple[ScenarioResult, List[AgentLimitation]]:
        """Generate a deterministic ScenarioResult from a validated ScenarioRequest.

        Returns:
            Tuple of (ScenarioResult, List[AgentLimitation])
        """
        org_id = request.organization_id.strip()
        target_ref = (request.target_reference or request.shipment_id or "default_target").strip()
        scenario_type = request.scenario_type

        # 1. Validate scenario type support
        if not isinstance(scenario_type, ScenarioType) and scenario_type not in [s.value for s in ScenarioType]:
            raise UnsupportedScenarioTypeError(f"Scenario type '{scenario_type}' is not supported by the scenario taxonomy.")

        limitations: List[AgentLimitation] = []
        parameters: List[ScenarioParameter] = list(request.parameters)
        evidence_refs: List[str] = list(request.evidence_references)
        upstream_refs: Dict[str, Any] = {}

        if request.risk_assessment_id:
            upstream_refs["risk_assessment_id"] = request.risk_assessment_id
        if request.prediction_id:
            upstream_refs["prediction_id"] = request.prediction_id

        # 2. Extract and incorporate authoritative PredictionResult if available
        pred_res = request.prediction_result or request.prediction_reference
        if pred_res and isinstance(pred_res, dict):
            # Check tenant isolation on prediction payload
            pred_org = pred_res.get("organization_id")
            if pred_org and pred_org.strip() != org_id:
                raise ScenarioTenantIsolationError(
                    f"Prediction result tenant '{pred_org}' does not match request tenant '{org_id}'."
                )

            pred_status = pred_res.get("status", "")
            pred_id = pred_res.get("prediction_id", request.prediction_id or "unknown_pred")
            upstream_refs["prediction_id"] = pred_id
            upstream_refs["prediction_status"] = pred_status

            # Gather prediction evidence references
            for ev in pred_res.get("evidence_references", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)

            # If prediction status is NOT_AVAILABLE, INSUFFICIENT_FEATURES, or FAILED
            if pred_status in ("NOT_AVAILABLE", "INSUFFICIENT_FEATURES", "FAILED", "NOT_IMPLEMENTED"):
                limitations.append(
                    AgentLimitation(
                        limitation_id=f"lim-pred-{pred_id[:8]}",
                        category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                        description=f"Upstream prediction status is '{pred_status}'; cannot derive empirical delay parameter.",
                        affected_nodes=["scenario_agent"],
                        mitigation_or_impact="Scenario will require explicit parameters or completed prediction inference.",
                    )
                )
            elif pred_status == "COMPLETED":
                predicted_val = pred_res.get("predicted_value")
                unit = pred_res.get("unit", "minutes")
                target_name = pred_res.get("target", "delay_minutes")

                if predicted_val is not None:
                    if math.isnan(predicted_val) or math.isinf(predicted_val):
                        raise InvalidScenarioParameterError("Upstream predicted_value is non-finite.")

                    # Add delay parameter derived deterministically from prediction
                    param_name = "delay_minutes" if scenario_type == ScenarioType.SHIPMENT_DELAY else target_name
                    # Avoid duplicate parameter if user already provided one explicitly
                    if not any(p.name == param_name for p in parameters):
                        parameters.append(
                            ScenarioParameter(
                                name=param_name,
                                value=float(predicted_val),
                                unit=unit,
                                source=f"PredictionAgent:{pred_id}",
                                source_type="PREDICTION",
                                evidence_references=pred_res.get("evidence_references", []),
                                provenance={
                                    "model_name": pred_res.get("model_metadata", {}).get("model_name")
                                    if isinstance(pred_res.get("model_metadata"), dict)
                                    else None,
                                    "target": target_name,
                                    "prediction_id": pred_id,
                                },
                            )
                        )

        # 3. Contextualize from RiskAssessment if present
        risk_ref = request.risk_assessment_reference
        if risk_ref and isinstance(risk_ref, dict):
            risk_org = risk_ref.get("organization_id")
            if risk_org and risk_org.strip() != org_id:
                raise ScenarioTenantIsolationError(
                    f"Risk assessment reference tenant '{risk_org}' does not match request tenant '{org_id}'."
                )
            risk_id = risk_ref.get("assessment_id", request.risk_assessment_id or "unknown_risk")
            upstream_refs["risk_assessment_id"] = risk_id
            for ev in risk_ref.get("evidence_ids", []):
                if ev not in evidence_refs:
                    evidence_refs.append(ev)

        # 4. Check evidence sufficiency
        # A scenario requires at least one parameter supported by upstream prediction, risk, or explicit inputs
        if not parameters:
            limitation = AgentLimitation(
                limitation_id=f"lim-insuff-scen-{target_ref[:8]}",
                category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                description="Insufficient evidence to construct scenario: no prediction value or explicit parameters available.",
                affected_nodes=["scenario_agent"],
                mitigation_or_impact="Provide completed prediction results or explicit scenario parameters with evidence references.",
            )
            limitations.append(limitation)

            # Generate deterministic ID for tracking even when insufficient
            scenario_id = generate_deterministic_scenario_id(
                organization_id=org_id,
                scenario_type=scenario_type.value if hasattr(scenario_type, "value") else str(scenario_type),
                target_reference=target_ref,
                parameter_fingerprint="empty_parameters",
                upstream_prediction_id=request.prediction_id,
                upstream_risk_id=request.risk_assessment_id,
            )

            result = ScenarioResult(
                scenario_id=scenario_id,
                organization_id=org_id,
                scenario_definition=None,
                status=ScenarioStatus.INSUFFICIENT_EVIDENCE.value,
                upstream_references=upstream_refs,
                evidence_references=evidence_refs,
                limitations=limitations,
                provenance={"agent": "ScenarioAgent", "status": "INSUFFICIENT_EVIDENCE"},
                fingerprint=None,
            )
            return result, limitations

        # 5. Compute deterministic parameter fingerprint
        param_dicts = [p.model_dump(mode="json") for p in parameters]
        constraint_dicts = [c.model_dump(mode="json") for c in request.constraints]
        trigger_dict = request.trigger.model_dump(mode="json") if request.trigger else None

        param_fp_str = ":".join(sorted(f"{p.name}={p.value}{p.unit or ''}" for p in parameters))
        scenario_id = generate_deterministic_scenario_id(
            organization_id=org_id,
            scenario_type=scenario_type.value if hasattr(scenario_type, "value") else str(scenario_type),
            target_reference=target_ref,
            parameter_fingerprint=param_fp_str,
            upstream_prediction_id=request.prediction_id,
            upstream_risk_id=request.risk_assessment_id,
        )

        # 6. Compute SHA-256 fingerprint over canonicalized definition
        fingerprint = compute_scenario_fingerprint(
            organization_id=org_id,
            scenario_type=scenario_type.value if hasattr(scenario_type, "value") else str(scenario_type),
            target_reference=target_ref,
            parameters=param_dicts,
            constraints=constraint_dicts,
            trigger=trigger_dict,
            upstream_references=upstream_refs,
        )

        # 7. Construct ScenarioDefinition
        now_utc = datetime.now(timezone.utc)
        effective_until = None
        if request.horizon_hours:
            from datetime import timedelta
            effective_until = now_utc + timedelta(hours=request.horizon_hours)

        definition = ScenarioDefinition(
            scenario_id=scenario_id,
            organization_id=org_id,
            scenario_type=scenario_type,
            target_reference=target_ref,
            parameters=parameters,
            trigger=request.trigger,
            constraints=request.constraints,
            horizon_hours=request.horizon_hours,
            effective_from=now_utc,
            effective_until=effective_until,
            fingerprint=fingerprint,
            provenance={
                "generator": "ScenarioGenerator",
                "upstream_references": upstream_refs,
                "evidence_count": len(evidence_refs),
            },
        )

        result = ScenarioResult(
            scenario_id=scenario_id,
            organization_id=org_id,
            scenario_definition=definition,
            status=ScenarioStatus.READY.value,
            upstream_references=upstream_refs,
            evidence_references=evidence_refs,
            limitations=limitations,
            provenance={
                "generator": "ScenarioGenerator",
                "scenario_id": scenario_id,
                "fingerprint": fingerprint,
            },
            fingerprint=fingerprint,
        )

        return result, limitations
