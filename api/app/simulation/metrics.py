"""Metric calculation and scenario comparison logic for RiskWise Simulation Engine."""
from __future__ import annotations

from typing import Dict, List, Optional

from app.simulation.contracts import (
    MetricAvailability,
    SimulationEffect,
    SimulationMetric,
    SimulationOutcome,
)
from app.simulation.state import SimulationState


class SimulationMetricsCalculator:
    """Calculates deterministic comparative metrics between baseline and simulated states."""

    @staticmethod
    def calculate_metrics(
        state: SimulationState,
        effects: List[SimulationEffect],
        baseline_risk_score: Optional[float] = None,
        simulated_risk_score: Optional[float] = None,
    ) -> Tuple[Dict[str, SimulationMetric], SimulationOutcome]:
        """Compute all standardized metrics and high-level outcome summary."""
        # 1. Delay Metrics
        baseline_delay = sum(
            float(n.properties.get("delay_minutes") or 0.0) for n in state.nodes.values()
        )
        simulated_delay = sum(n.effective_delay_minutes for n in state.nodes.values())
        delay_delta = simulated_delay - baseline_delay

        delay_metric = SimulationMetric(
            metric_name="total_delay_minutes",
            baseline_value=round(baseline_delay, 2),
            simulated_value=round(simulated_delay, 2),
            delta=round(delay_delta, 2),
            unit="MINUTES",
            availability=MetricAvailability.AVAILABLE,
        )

        # 2. Affected Nodes & Edges
        affected_nodes = [
            n for n in state.nodes.values()
            if not n.is_available or n.effective_delay_minutes > float(n.properties.get("delay_minutes") or 0.0)
            or len(n.simulated_tags) > 0
        ]
        affected_edges = [
            e for e in state.edges.values()
            if not e.is_available or e.added_transit_time_minutes > 0.0 or len(e.simulated_tags) > 0
        ]
        affected_shipments = [
            n for n in affected_nodes if n.node_type == "SHIPMENT"
        ]

        nodes_metric = SimulationMetric(
            metric_name="affected_nodes_count",
            baseline_value=0.0,
            simulated_value=float(len(affected_nodes)),
            delta=float(len(affected_nodes)),
            unit="NODES",
            availability=MetricAvailability.AVAILABLE,
        )

        edges_metric = SimulationMetric(
            metric_name="affected_edges_count",
            baseline_value=0.0,
            simulated_value=float(len(affected_edges)),
            delta=float(len(affected_edges)),
            unit="EDGES",
            availability=MetricAvailability.AVAILABLE,
        )

        shipments_metric = SimulationMetric(
            metric_name="affected_shipments_count",
            baseline_value=0.0,
            simulated_value=float(len(affected_shipments)),
            delta=float(len(affected_shipments)),
            unit="SHIPMENTS",
            availability=MetricAvailability.AVAILABLE,
        )

        # 3. Capacity Impact
        baseline_capacity_total = 0.0
        simulated_capacity_total = 0.0
        has_capacity_data = False

        for n in state.nodes.values():
            if n.baseline_capacity is not None:
                has_capacity_data = True
                baseline_capacity_total += n.baseline_capacity
                simulated_capacity_total += (n.capacity if n.capacity is not None else n.baseline_capacity)

        if has_capacity_data:
            capacity_metric = SimulationMetric(
                metric_name="total_capacity_units",
                baseline_value=round(baseline_capacity_total, 2),
                simulated_value=round(simulated_capacity_total, 2),
                delta=round(simulated_capacity_total - baseline_capacity_total, 2),
                unit="UNITS",
                availability=MetricAvailability.AVAILABLE,
            )
        else:
            capacity_metric = SimulationMetric(
                metric_name="total_capacity_units",
                baseline_value=None,
                simulated_value=None,
                delta=None,
                unit="UNITS",
                availability=MetricAvailability.NOT_AVAILABLE,
            )

        # 4. Inventory Exposure
        inventory_exposure = 0.0
        has_inventory_data = False
        for n in affected_nodes:
            if n.node_type in ("WAREHOUSE", "FACTORY"):
                cap = n.baseline_capacity or n.capacity
                if cap is not None:
                    has_inventory_data = True
                    inventory_exposure += cap

        if has_inventory_data:
            inventory_metric = SimulationMetric(
                metric_name="inventory_exposure_units",
                baseline_value=0.0,
                simulated_value=round(inventory_exposure, 2),
                delta=round(inventory_exposure, 2),
                unit="UNITS",
                availability=MetricAvailability.ESTIMATED,
            )
        else:
            inventory_metric = SimulationMetric(
                metric_name="inventory_exposure_units",
                baseline_value=None,
                simulated_value=None,
                delta=None,
                unit="UNITS",
                availability=MetricAvailability.NOT_AVAILABLE,
            )

        # 5. Risk Metric
        if baseline_risk_score is not None and simulated_risk_score is not None:
            risk_delta = round(simulated_risk_score - baseline_risk_score, 2)
            risk_metric = SimulationMetric(
                metric_name="overall_risk_score",
                baseline_value=round(baseline_risk_score, 2),
                simulated_value=round(simulated_risk_score, 2),
                delta=risk_delta,
                unit="SCORE_0_100",
                availability=MetricAvailability.AVAILABLE,
            )
        else:
            risk_delta = None
            risk_metric = SimulationMetric(
                metric_name="overall_risk_score",
                baseline_value=None,
                simulated_value=None,
                delta=None,
                unit="SCORE_0_100",
                availability=MetricAvailability.NOT_AVAILABLE,
            )

        metrics_dict: Dict[str, SimulationMetric] = {
            "total_delay_minutes": delay_metric,
            "affected_nodes_count": nodes_metric,
            "affected_edges_count": edges_metric,
            "affected_shipments_count": shipments_metric,
            "total_capacity_units": capacity_metric,
            "inventory_exposure_units": inventory_metric,
            "overall_risk_score": risk_metric,
        }

        # Severity determination
        if delay_delta > 1440.0 or len(affected_nodes) > 10 or (risk_delta and risk_delta > 25.0):
            severity = "CRITICAL"
        elif delay_delta > 360.0 or len(affected_nodes) > 3 or (risk_delta and risk_delta > 10.0):
            severity = "HIGH"
        elif delay_delta > 0.0 or len(affected_nodes) > 0:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        outcome = SimulationOutcome(
            affected_nodes_count=len(affected_nodes),
            affected_edges_count=len(affected_edges),
            affected_shipments_count=len(affected_shipments),
            total_added_delay_minutes=max(0.0, delay_delta),
            inventory_exposure_units=inventory_exposure if has_inventory_data else None,
            baseline_risk_score=baseline_risk_score,
            simulated_risk_score=simulated_risk_score,
            risk_delta=risk_delta,
            severity=severity,
        )

        return metrics_dict, outcome
