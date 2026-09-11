"""Production-oriented ML inference service implementing BasePredictionService.

Bridges the RiskWise ML subsystem with the Phase 9 Prediction Agent.
Guarantees tenant isolation, safe feature transformation, non-negative delay outputs,
unmanufactured uncertainty semantics, and fail-safe fallback to NOT_AVAILABLE.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import numpy as np

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.prediction.contract import (
    ModelMetadata as AgentModelMetadata,
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
    PredictionUncertainty,
)
from app.agents.prediction.service import BasePredictionService, UnavailablePredictionService
from app.ml.config import ml_config
from app.ml.contracts import ModelFamily
from app.ml.errors import (
    MLTenantIsolationError,
    ModelInferenceError,
    PredictionInputError,
    PredictionOutputValidationError,
)
from app.ml.observability import MLObservability
from app.ml.registry.registry import ModelRegistry, default_model_registry


class MLPredictionService(BasePredictionService):
    """Authoritative ML prediction service consumed by the Prediction Agent."""

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        family: ModelFamily = ModelFamily.SHIPMENT_DELAY,
        fallback_service: Optional[BasePredictionService] = None,
    ) -> None:
        self._registry = registry or default_model_registry
        self._family = family
        self._fallback_service = fallback_service or UnavailablePredictionService()

    def is_available(self) -> bool:
        """Check whether ML inference is enabled and at least one model is active in registry."""
        if not ml_config.ENABLED:
            return False
        model_entry = self._registry.get_active_model(self._family)
        return model_entry is not None

    def get_model_metadata(self) -> AgentModelMetadata:
        """Retrieve model metadata adapted for the Prediction Agent contract."""
        model_entry = self._registry.get_active_model(self._family)
        if model_entry is None:
            return self._fallback_service.get_model_metadata()

        _, _, meta = model_entry
        return AgentModelMetadata(
            model_name=meta.model_id,
            model_version=meta.model_version,
            model_type=meta.task_type.value,
            feature_version=meta.preprocessing_version,
            training_data_version=meta.training_dataset_fingerprint[:16],
            is_production=meta.is_production,
            metadata={
                "model_family": meta.model_family.value,
                "target": meta.target,
                "validation_status": meta.validation_status,
                "metrics": meta.metrics.model_dump(),
                "artifact_fingerprint": meta.artifact_fingerprint[:16],
            },
        )

    def predict(self, request: PredictionRequest) -> PredictionResult:
        """Execute ML model inference and return an authoritative PredictionResult."""
        start_time = time.perf_counter()
        org_id = request.organization_id

        # 1. Check model availability for requested tenant
        model_entry = self._registry.get_active_model(self._family, organization_id=org_id)
        if model_entry is None or not ml_config.ENABLED:
            return self._fallback_service.predict(request)

        model, pipeline, meta = model_entry

        # Tenant isolation check
        if meta.organization_id and meta.organization_id != org_id:
            raise MLTenantIsolationError(
                f"Model '{meta.model_id}' belongs to tenant '{meta.organization_id}' "
                f"and cannot serve requests for tenant '{org_id}'."
            )

        try:
            # 2. Extract feature dictionary from PredictionRequest.features
            feat_dict: Dict[str, Any] = {}
            ev_refs: List[str] = []
            for f in request.features:
                if f.organization_id != org_id:
                    raise MLTenantIsolationError(
                        f"Feature '{f.feature_name}' tenant '{f.organization_id}' "
                        f"does not match request tenant '{org_id}'."
                    )
                feat_dict[f.feature_name] = f.value
                ev_refs.extend(f.evidence_references)

            # 3. Transform features using the exact saved feature pipeline
            X_vec = pipeline.transform_single(feat_dict)

            # 4. Execute model prediction
            raw_prediction = model.predict_single(X_vec)

            # 5. Apply domain validation & physical constraints
            predicted_delay = model.validate_prediction(raw_prediction)
            predicted_delay = round(predicted_delay, 2)

            # 6. Uncertainty handling (NEVER fabricated!)
            uncertainty: Optional[PredictionUncertainty] = None
            if meta.metrics.is_calculated and meta.metrics.rmse is not None:
                rmse = meta.metrics.rmse
                uncertainty = PredictionUncertainty(
                    prediction_interval=(
                        max(0.0, round(predicted_delay - 1.96 * rmse, 2)),
                        round(predicted_delay + 1.96 * rmse, 2),
                    ),
                    confidence_interval=(
                        max(0.0, round(predicted_delay - rmse, 2)),
                        round(predicted_delay + rmse, 2),
                    ),
                    standard_error=round(rmse, 2),
                    confidence_score=None,  # Not calibrated as a probability!
                    method="EMPIRICAL_TEST_RMSE",
                )

            agent_metadata = self.get_model_metadata()
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            MLObservability.emit_inference_event(
                action="ML_PREDICTION_EXECUTED",
                organization_id=org_id,
                prediction_id=request.prediction_id,
                model_id=meta.model_id,
                latency_ms=latency_ms,
                status="COMPLETED",
                predicted_value=predicted_delay,
                correlation_id=request.correlation_id,
                trace_id=request.trace_id,
            )

            return PredictionResult(
                prediction_id=request.prediction_id,
                organization_id=org_id,
                prediction_type=request.prediction_type,
                target=request.target,
                predicted_value=predicted_delay,
                unit="minutes",
                uncertainty=uncertainty,
                model_metadata=agent_metadata,
                feature_references=sorted([f.feature_name for f in request.features]),
                evidence_references=sorted(list(set(ev_refs))),
                risk_assessment_reference=request.risk_assessment_id,
                limitations=[],
                provenance={
                    "service": "MLPredictionService",
                    "model_id": meta.model_id,
                    "model_family": meta.model_family.value,
                    "is_production": meta.is_production,
                },
                status=PredictionStatus.COMPLETED.value,
            )

        except (MLTenantIsolationError, PredictionInputError, PredictionOutputValidationError) as domain_err:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            MLObservability.emit_inference_event(
                action="ML_PREDICTION_FAILED",
                organization_id=org_id,
                prediction_id=request.prediction_id,
                model_id=meta.model_id,
                latency_ms=latency_ms,
                status="FAILED",
                error_category=type(domain_err).__name__,
            )
            raise

        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            MLObservability.emit_inference_event(
                action="ML_PREDICTION_FAILED",
                organization_id=org_id,
                prediction_id=request.prediction_id,
                model_id=meta.model_id,
                latency_ms=latency_ms,
                status="FAILED",
                error_category=type(exc).__name__,
            )
            # Fail-safe isolation: convert unexpected error into typed FAILED result with limitation
            limitation = AgentLimitation(
                limitation_id=f"lim-err-{request.prediction_id[:8]}",
                category=LimitationCategory.PREDICTION_EXECUTION_FAILED,
                description=f"ML model inference failed: {type(exc).__name__}",
                affected_nodes=["prediction_agent"],
                mitigation_or_impact="Model prediction failed safely; pipeline preserved.",
            )
            return PredictionResult(
                prediction_id=request.prediction_id,
                organization_id=org_id,
                prediction_type=request.prediction_type,
                target=request.target,
                predicted_value=None,
                unit="minutes",
                uncertainty=None,
                model_metadata=self.get_model_metadata(),
                feature_references=[f.feature_name for f in request.features],
                evidence_references=[],
                risk_assessment_reference=request.risk_assessment_id,
                limitations=[limitation],
                provenance={"service": "MLPredictionService", "error": type(exc).__name__},
                status=PredictionStatus.FAILED.value,
            )
