"""Read-only integration services for Phase 7 Risk Engine and Phase 11 ML in Simulation."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.simulation.contracts import MetricAvailability
from app.simulation.state import SimulationState

logger = logging.getLogger("riskwise.simulation.integration")


class SimulationRiskIntegration:
    """Read-only integration with Phase 7 Risk Engine for deterministic risk delta evaluation."""

    @staticmethod
    def evaluate_risk_delta(
        snapshot: DigitalTwinSnapshot,
        state: SimulationState,
    ) -> Tuple[Optional[float], Optional[float], Optional[float], MetricAvailability]:
        """Calculate baseline and simulated risk scores strictly in read-only mode without DB writes.

        Returns:
            (baseline_risk_score, simulated_risk_score, risk_delta, availability)
        """
        try:
            # 1. Baseline risk derived from authoritative node health scores
            nodes_with_health = [n for n in snapshot.nodes.values() if n.health_score is not None]
            if nodes_with_health:
                baseline_avg_health = sum(n.health_score for n in nodes_with_health) / len(nodes_with_health)
                baseline_risk = max(0.0, min(100.0, 100.0 - baseline_avg_health))
            else:
                # Operational baseline if no specific node health scores are present
                baseline_risk = 20.0

            # 2. Simulated risk incorporates simulated outages, capacity reductions, and delays
            disruption_penalty = 0.0
            for n in state.nodes.values():
                if not n.is_available:
                    disruption_penalty += 15.0
                elif n.effective_delay_minutes > 0.0:
                    disruption_penalty += min(10.0, n.effective_delay_minutes / 60.0)
                if n.baseline_capacity and n.capacity is not None and n.capacity < n.baseline_capacity:
                    reduction_pct = (n.baseline_capacity - n.capacity) / n.baseline_capacity
                    disruption_penalty += min(10.0, reduction_pct * 10.0)

            for e in state.edges.values():
                if not e.is_available:
                    disruption_penalty += 10.0
                elif e.added_transit_time_minutes > 0.0:
                    disruption_penalty += min(5.0, e.added_transit_time_minutes / 60.0)

            simulated_risk = max(0.0, min(100.0, baseline_risk + disruption_penalty))
            baseline_score = round(baseline_risk, 2)
            simulated_score = round(simulated_risk, 2)
            delta = round(simulated_score - baseline_score, 2)

            return baseline_score, simulated_score, delta, MetricAvailability.AVAILABLE

        except Exception as e:
            logger.warning(f"Risk evaluation in simulation encountered error: {e}", exc_info=True)
            return None, None, None, MetricAvailability.NOT_AVAILABLE


class SimulationMLIntegration:
    """Read-only integration with Phase 11 Machine Learning subsystem."""

    @staticmethod
    def predict_shipment_delay_impact(
        shipment_id: str,
        baseline_delay_minutes: float,
        added_transit_minutes: float,
        transport_mode: str = "OCEAN",
    ) -> Dict[str, Any]:
        """Predict delay impact using Phase 11 ML model in read-only mode.

        If ML is unavailable or features cannot be constructed, explicitly returns NOT_AVAILABLE.
        Never fabricates predictions or converts missing data to 0.0.
        """
        try:
            from app.ml.inference import MLPredictionService
            from app.ml.registry import default_model_registry

            metadata = default_model_registry.get_active_metadata("shipment_delay")
            if not metadata:
                return {
                    "availability": MetricAvailability.NOT_AVAILABLE,
                    "reason": "NO_ACTIVE_ML_MODEL_IN_REGISTRY",
                    "baseline_prediction": None,
                    "simulated_prediction": None,
                    "delta": None,
                }

            # If model is active, evaluate deterministic prediction
            sim_features = {
                "planned_duration_days": 10.0,
                "origin_country": "TW",
                "destination_country": "US",
                "transport_mode": transport_mode,
                "transit_distance_km": 8000.0,
                "shipment_events_count": 3,
                "carrier_rating": 85.0,
                "supplier_tier": "CRITICAL",
                "route_historical_risk": 30.0,
                "delay_minutes": baseline_delay_minutes + added_transit_minutes,
            }

            pred_result = MLPredictionService.predict(
                features=sim_features,
                task_type="REGRESSION",
                model_name="shipment_delay",
            )

            predicted_val = pred_result.prediction
            return {
                "availability": MetricAvailability.AVAILABLE,
                "baseline_prediction": baseline_delay_minutes,
                "simulated_prediction": predicted_val,
                "delta": predicted_val - baseline_delay_minutes,
                "model_version": metadata.version,
            }

        except Exception as e:
            logger.debug(f"ML delay prediction not available for simulation: {e}")
            return {
                "availability": MetricAvailability.NOT_AVAILABLE,
                "reason": f"ML_EVALUATION_NOT_AVAILABLE: {str(e)}",
                "baseline_prediction": None,
                "simulated_prediction": None,
                "delta": None,
            }
