"""Prediction service interfaces and implementations.

Defines BasePredictionService, UnavailablePredictionService (default production behavior),
and DeterministicMockPredictionService (strictly for automated testing).

CRITICAL RULE:
If no production ML model exists, the service returns NOT_AVAILABLE with an explicit
PREDICTION_MODEL_UNAVAILABLE limitation. It NEVER returns a fabricated prediction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.prediction.contract import (
    ModelMetadata,
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
    PredictionUncertainty,
)


class BasePredictionService(ABC):
    """Abstract interface for prediction services consumed by the Prediction Agent."""

    @abstractmethod
    def predict(self, request: PredictionRequest) -> PredictionResult:
        """Execute prediction inference against validated request and features."""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """Check if model service is available and ready for inference."""
        raise NotImplementedError

    @abstractmethod
    def get_model_metadata(self) -> ModelMetadata:
        """Retrieve model metadata."""
        raise NotImplementedError


class UnavailablePredictionService(BasePredictionService):
    """Production service used when no production ML model is deployed.

    Returns NOT_AVAILABLE status and PREDICTION_MODEL_UNAVAILABLE limitation.
    Never invents numeric predictions.
    """

    def __init__(
        self,
        model_name: str = "shipment_delay_production_model",
        model_version: str = "0.0.0-unconfigured",
    ) -> None:
        self._model_metadata = ModelMetadata(
            model_name=model_name,
            model_version=model_version,
            model_type="ML_SERVING",
            is_production=True,
            metadata={"status": "UNAVAILABLE", "reason": "No production ML model deployed"},
        )

    def is_available(self) -> bool:
        return False

    def get_model_metadata(self) -> ModelMetadata:
        return self._model_metadata

    def predict(self, request: PredictionRequest) -> PredictionResult:
        limitation = AgentLimitation(
            limitation_id=f"lim-unavail-{request.prediction_id[:8]}",
            category=LimitationCategory.PREDICTION_MODEL_UNAVAILABLE,
            description=(
                f"Prediction model '{self._model_metadata.model_name}:{self._model_metadata.model_version}' "
                "is currently unavailable or not deployed."
            ),
            affected_nodes=["prediction_agent"],
            mitigation_or_impact="Awaiting production ML model deployment; prediction skipped.",
        )
        return PredictionResult(
            prediction_id=request.prediction_id,
            organization_id=request.organization_id,
            prediction_type=request.prediction_type,
            target=request.target,
            predicted_value=None,
            unit="minutes",
            uncertainty=None,
            model_metadata=self._model_metadata,
            feature_references=[f.feature_name for f in request.features],
            evidence_references=[],
            risk_assessment_reference=request.risk_assessment_id,
            limitations=[limitation],
            provenance={"service": "UnavailablePredictionService", "is_production": True},
            status=PredictionStatus.NOT_AVAILABLE.value,
        )


class DeterministicMockPredictionService(BasePredictionService):
    """Deterministic mock service strictly for unit and integration testing.

    Explicitly flagged as NOT_PRODUCTION (is_production=False).
    Computes reproducible delay values from input features without real ML inference.
    """

    def __init__(
        self,
        model_name: str = "deterministic_mock_shipment_delay",
        model_version: str = "1.0.0-mock",
        base_delay_minutes: float = 15.0,
    ) -> None:
        self._base_delay_minutes = base_delay_minutes
        self._model_metadata = ModelMetadata(
            model_name=model_name,
            model_version=model_version,
            model_type="DETERMINISTIC_TEST_MOCK",
            is_production=False,
            metadata={
                "environment": "test",
                "purpose": "automated_integration_testing",
                "disclaimer": "NOT_FOR_PRODUCTION_USE",
            },
        )

    def is_available(self) -> bool:
        return True

    def get_model_metadata(self) -> ModelMetadata:
        return self._model_metadata

    def predict(self, request: PredictionRequest) -> PredictionResult:
        delay = self._base_delay_minutes
        feat_refs: List[str] = []
        ev_refs: List[str] = []

        for feat in request.features:
            feat_refs.append(feat.feature_name)
            ev_refs.extend(feat.evidence_references)

            if feat.feature_name == "risk_composite_score" and isinstance(feat.value, (int, float)):
                delay += float(feat.value) * 1.5
            elif feat.feature_name == "port_disruption_detected" and feat.value in (1.0, 1, True):
                delay += 120.0
            elif feat.feature_name == "logistics_delay_detected" and feat.value in (1.0, 1, True):
                delay += 60.0
            elif feat.feature_name == "weather_disruption_detected" and feat.value in (1.0, 1, True):
                delay += 90.0

        delay = round(delay, 2)
        uncertainty = PredictionUncertainty(
            prediction_interval=(max(0.0, round(delay * 0.8, 2)), round(delay * 1.25, 2)),
            confidence_interval=(max(0.0, round(delay * 0.85, 2)), round(delay * 1.15, 2)),
            standard_error=round(delay * 0.1, 2),
            confidence_score=0.85,
            method="DETERMINISTIC_HEURISTIC_INTERVAL",
        )

        return PredictionResult(
            prediction_id=request.prediction_id,
            organization_id=request.organization_id,
            prediction_type=request.prediction_type,
            target=request.target,
            predicted_value=delay,
            unit="minutes",
            uncertainty=uncertainty,
            model_metadata=self._model_metadata,
            feature_references=sorted(list(set(feat_refs))),
            evidence_references=sorted(list(set(ev_refs))),
            risk_assessment_reference=request.risk_assessment_id,
            limitations=[],
            provenance={"service": "DeterministicMockPredictionService", "is_production": False},
            status=PredictionStatus.COMPLETED.value,
        )
