"""Prediction Agent execution layer.

Coordinates request validation, feature validation, prediction service invocation,
output validation, and structured findings generation.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.agents.contracts import AgentFinding, AgentLimitation, LimitationCategory
from app.agents.prediction.contract import (
    ModelMetadata,
    PredictionFeature,
    PredictionRequest,
    PredictionResult,
    PredictionStatus,
    PredictionType,
)
from app.agents.prediction.errors import (
    InvalidModelOutputError,
    InvalidPredictionRequestError,
    PredictionAgentError,
    PredictionTenantIsolationError,
)
from app.agents.prediction.service import BasePredictionService, UnavailablePredictionService


class PredictionAgent:
    """Orchestration agent for prediction inference."""

    def __init__(self, service: Optional[BasePredictionService] = None) -> None:
        self.service = service or UnavailablePredictionService()

    def execute(self, request: PredictionRequest) -> Tuple[PredictionResult, List[AgentFinding]]:
        """Execute prediction inference and produce structured agent findings.

        Returns:
            Tuple of (PredictionResult, List[AgentFinding])
        """
        if not request.organization_id or not request.organization_id.strip():
            raise InvalidPredictionRequestError("PredictionRequest organization_id must be non-empty.")

        # If no features provided and prediction type is SHIPMENT_DELAY
        if not request.features:
            metadata = self.service.get_model_metadata()
            limitation = AgentLimitation(
                limitation_id=f"lim-insuff-{request.prediction_id[:8]}",
                category=LimitationCategory.INSUFFICIENT_FEATURES,
                description="Prediction cannot proceed without extracted features.",
                affected_nodes=["prediction_agent"],
                mitigation_or_impact="Supply upstream risk assessment or research evidence before prediction.",
            )
            result = PredictionResult(
                prediction_id=request.prediction_id,
                organization_id=request.organization_id,
                prediction_type=request.prediction_type,
                target=request.target,
                predicted_value=None,
                unit="minutes",
                uncertainty=None,
                model_metadata=metadata,
                feature_references=[],
                evidence_references=[],
                risk_assessment_reference=request.risk_assessment_id,
                limitations=[limitation],
                provenance={"agent": "PredictionAgent", "status": "INSUFFICIENT_FEATURES"},
                status=PredictionStatus.INSUFFICIENT_FEATURES.value,
            )
            finding = AgentFinding(
                finding_id=f"find-pred-insuff-{request.prediction_id[:8]}",
                category="INSUFFICIENT_FEATURES",
                title="Shipment Delay Prediction: Insufficient Features",
                summary="Prediction could not be computed because no features were available in upstream graph state.",
                severity="LOW",
                confidence=1.0,
                evidence_ids=[],
                source_references=[],
                limitations=[limitation.description],
                created_by_node="prediction_agent",
            )
            return result, [finding]

        # Invoke prediction service
        result = self.service.predict(request)

        # Output validation
        if result.organization_id != request.organization_id:
            raise PredictionTenantIsolationError(
                f"PredictionResult organization '{result.organization_id}' does not match "
                f"request organization '{request.organization_id}'."
            )

        findings: List[AgentFinding] = []

        if result.status == PredictionStatus.COMPLETED.value:
            if result.predicted_value is None or math.isnan(result.predicted_value) or math.isinf(result.predicted_value):
                raise InvalidModelOutputError("Completed PredictionResult must contain a finite predicted_value.")
            if result.predicted_value < 0.0:
                raise InvalidModelOutputError(f"Predicted delay cannot be negative ({result.predicted_value}).")

            # Check uncertainty interval if present
            if result.uncertainty and result.uncertainty.prediction_interval:
                low, high = result.uncertainty.prediction_interval
                if high - low > result.predicted_value * 1.5:
                    result.limitations.append(
                        AgentLimitation(
                            limitation_id=f"lim-uncert-{result.prediction_id[:8]}",
                            category=LimitationCategory.HIGH_UNCERTAINTY,
                            description=f"Wide prediction interval [{low}, {high}] indicates substantial variance.",
                            affected_nodes=["prediction_agent"],
                            mitigation_or_impact="Collect additional real-time telemetry to narrow prediction interval.",
                        )
                    )

            finding_conf = 0.85
            if result.uncertainty and result.uncertainty.confidence_score is not None:
                finding_conf = result.uncertainty.confidence_score

            finding = AgentFinding(
                finding_id=f"find-pred-{result.prediction_id[:8]}",
                category="PREDICTED_DELAY",
                title=f"Predicted Shipment Delay: {result.predicted_value:.1f} {result.unit}",
                summary=(
                    f"Model '{result.model_metadata.model_name}:{result.model_metadata.model_version}' "
                    f"predicted an estimated delay of {result.predicted_value:.1f} {result.unit} "
                    f"based on {len(result.feature_references)} features."
                ),
                severity="MEDIUM" if result.predicted_value > 60.0 else "LOW",
                confidence=finding_conf,
                evidence_ids=result.evidence_references,
                source_references=[f"PredictionResult:{result.prediction_id}"],
                limitations=[lim.description for lim in result.limitations],
                created_by_node="prediction_agent",
            )
            findings.append(finding)

        elif result.status in (PredictionStatus.NOT_AVAILABLE.value, PredictionStatus.NOT_IMPLEMENTED.value):
            finding = AgentFinding(
                finding_id=f"find-pred-unavail-{result.prediction_id[:8]}",
                category="PREDICTION_UNAVAILABLE",
                title="Shipment Delay Prediction: Model Unavailable",
                summary=(
                    f"Prediction model '{result.model_metadata.model_name}' is not currently deployed. "
                    "No delay prediction was fabricated."
                ),
                severity="LOW",
                confidence=1.0,
                evidence_ids=[],
                source_references=[],
                limitations=[lim.description for lim in result.limitations],
                created_by_node="prediction_agent",
            )
            findings.append(finding)

        return result, findings
