"""LangGraph Prediction Agent node for Phase 9 Step 6.

Provides the prediction_node() function and PREDICTION_NODE_CONTRACT for registration
with the LangGraph NodeRegistry. Mirrors research_node() and risk_node() pattern:
single try/except/finally ensures telemetry is always emitted.

State ownership: writes only PREDICTION-owned fields.
Side effects: READ_ONLY (prediction inference has zero operational side effects).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agents.contracts import (
    AgentGraphState,
    AgentGraphStateDict,
    AgentStage,
    validate_state_update,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.agents.prediction.adapter import PredictionFeatureExtractor
from app.agents.prediction.agent import PredictionAgent
from app.agents.prediction.contract import (
    PredictionRequest,
    PredictionResult,
    PredictionType,
    generate_deterministic_prediction_id,
)
from app.agents.prediction.errors import InvalidPredictionRequestError, PredictionTenantIsolationError
from app.agents.prediction.service import BasePredictionService, UnavailablePredictionService

try:
    from app.agents.contracts import AgentNodeContract
    _HAS_NODE_CONTRACT = True
except ImportError:
    from app.agents.contracts import NodeContract as AgentNodeContract  # type: ignore
    _HAS_NODE_CONTRACT = False


PREDICTION_NODE_CONTRACT = AgentNodeContract(
    node_id="prediction_agent",
    name="Prediction Agent",
    description=(
        "Orchestration node: extracts features from authoritative upstream risk assessment "
        "and structured findings, invokes typed BasePredictionService, and writes validated "
        "prediction results into AgentGraphState."
    ),
    stage=AgentStage.PREDICTION,
    is_side_effecting=False,
    input_keys=[
        "organization_id",
        "actor_id",
        "run_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "objective",
        "structured_findings",
        "risk_assessment_id",
        "risk_assessment_reference",
        "risk_assessment",
        "evidence_references",
    ],
    output_keys=[
        "prediction_id",
        "prediction_reference",
        "prediction_result",
        "structured_findings",
        "limitations",
        "warnings",
        "findings",
        "current_stage",
        "current_node",
        "step_count",
    ],
    required_roles=["analyst", "admin"],
    requires_evidence=True,
    retryable=True,
    max_retries=3,
    timeout_seconds=120.0,
)


def prediction_node(
    state: AgentGraphStateDict,
    service: Optional[BasePredictionService] = None,
) -> Dict[str, Any]:
    """Execute the Prediction Agent node within a LangGraph StateGraph pipeline.

    Extracts features from upstream RiskAssessment and structured findings,
    dispatches a typed PredictionRequest to BasePredictionService,
    validates output, and updates only PREDICTION-owned fields.
    """
    start_time = time.perf_counter()
    status = "SUCCESS"
    error_code: Optional[str] = None

    # Extract required identity from state
    org_id = state.get("organization_id", "")
    run_id = state.get("run_id", "")
    actor_id = state.get("actor_id", "")
    request_id = state.get("request_id", "")
    correlation_id = state.get("correlation_id", "")
    trace_id = state.get("trace_id", "")
    objective = state.get("objective", "")

    prediction_svc = service or UnavailablePredictionService()

    try:
        if not org_id or not org_id.strip():
            raise PredictionTenantIsolationError(
                "prediction_node requires non-empty 'organization_id' in state."
            )

        # 1. Deterministic feature extraction
        features, feature_limitations = PredictionFeatureExtractor.extract_features(state, org_id)

        # 2. Risk assessment reference
        risk_ref = state.get("risk_assessment_reference") or state.get("risk_assessment") or {}
        risk_assessment_id = state.get("risk_assessment_id") or (risk_ref.get("assessment_id") if isinstance(risk_ref, dict) else None)

        # 3. Model metadata for deterministic ID computation
        meta = prediction_svc.get_model_metadata()
        target_ref = state.get("input_reference") or risk_assessment_id or objective[:32]
        feature_fp = f"feat_count_{len(features)}:" + ":".join(sorted(f.feature_name for f in features))

        prediction_id = generate_deterministic_prediction_id(
            organization_id=org_id,
            prediction_type=PredictionType.SHIPMENT_DELAY.value,
            target_reference=target_ref,
            feature_fingerprint=feature_fp,
            model_name=meta.model_name,
            model_version=meta.model_version,
        )

        # 4. Build PredictionRequest
        request = PredictionRequest(
            prediction_id=prediction_id,
            organization_id=org_id,
            prediction_type=PredictionType.SHIPMENT_DELAY,
            target="delay_minutes",
            shipment_id=state.get("input_reference"),
            risk_assessment_id=risk_assessment_id,
            risk_assessment_reference=risk_ref if isinstance(risk_ref, dict) else None,
            evidence_bundle_id=state.get("evidence_bundle_id"),
            features=features,
            prediction_horizon_hours=24.0,
            model_name=meta.model_name,
            model_version=meta.model_version,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # 5. Execute PredictionAgent
        agent = PredictionAgent(service=prediction_svc)
        result, findings = agent.execute(request)

        # 6. Assemble state update
        existing_findings = list(state.get("structured_findings", []))
        findings_serialized = [f.model_dump(mode="json") for f in findings]
        updated_structured_findings = existing_findings + findings_serialized

        existing_limitations = list(state.get("limitations", []))
        new_limitations = [lim.model_dump(mode="json") for lim in (feature_limitations + result.limitations)]
        updated_limitations = existing_limitations + new_limitations

        current_findings = dict(state.get("findings", {}))
        current_findings["prediction"] = {
            "prediction_id": result.prediction_id,
            "status": result.status,
            "target": result.target,
            "predicted_value": result.predicted_value,
            "unit": result.unit,
            "model_name": result.model_metadata.model_name,
            "model_version": result.model_metadata.model_version,
        }

        prediction_reference = {
            "prediction_id": result.prediction_id,
            "status": result.status,
            "target": result.target,
            "predicted_value": result.predicted_value,
            "unit": result.unit,
            "model_name": result.model_metadata.model_name,
            "model_version": result.model_metadata.model_version,
        }

        step_count = state.get("step_count", 0) + 1

        update_payload: Dict[str, Any] = {
            "prediction_id": result.prediction_id,
            "prediction_reference": prediction_reference,
            "prediction_result": result.model_dump(mode="json"),
            "structured_findings": updated_structured_findings,
            "limitations": updated_limitations,
            "findings": current_findings,
            "current_stage": AgentStage.PREDICTION.value,
            "current_node": "prediction_agent",
            "step_count": step_count,
        }

        # 7. Validate state update against authoritative ownership
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="prediction_agent",
            writer_stage=AgentStage.PREDICTION,
        )

        return update_payload

    except Exception as exc:
        status = "FAILED"
        error_code = exc.__class__.__name__
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        AgentObservability.emit_node_telemetry(
            NodeExecutionTelemetry(
                run_id=run_id or "unknown_run",
                organization_id=org_id or "unknown_org",
                actor_id=actor_id or "unknown_actor",
                request_id=request_id or "unknown_req",
                correlation_id=correlation_id or "unknown_corr",
                trace_id=trace_id or "unknown_trace",
                node_name="prediction_agent",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )
