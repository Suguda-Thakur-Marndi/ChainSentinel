"""Headless, API-independent simulation engine for what-if scenario execution."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional, Tuple

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.simulation.contracts import (
    SimulationInput,
    SimulationOutcome,
    SimulationProvenance,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.errors import (
    SimulationError,
    SimulationResourceLimitError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.fingerprints import (
    compute_simulation_fingerprint,
    compute_simulation_id,
)
from app.simulation.metrics import SimulationMetricsCalculator
from app.simulation.observability import SimulationObservability
from app.simulation.propagation import SimulationPropagationEngine
from app.simulation.state import SimulationState
from app.simulation.validation import SimulationValidator


class SimulationEngine:
    """Core execution engine for what-if scenarios against Digital Twin snapshots."""

    @staticmethod
    def execute_simulation(
        snapshot: DigitalTwinSnapshot,
        scenario: SimulationScenario,
        sim_input: Optional[SimulationInput] = None,
        request_id: Optional[str] = None,
    ) -> SimulationResult:
        """Execute a complete, deterministic, and isolated scenario simulation."""
        start_time = time.perf_counter()

        # 1. Default execution parameters if not provided
        if sim_input is None:
            sim_input = SimulationInput(scenario=scenario)

        # 2. Strict Input & Tenant Validation
        SimulationValidator.validate_scenario(scenario, snapshot)
        SimulationValidator.validate_simulation_input(sim_input)

        # 3. Compute deterministic simulation fingerprint and ID
        sim_fingerprint = compute_simulation_fingerprint(
            base_snapshot_fingerprint=snapshot.twin_fingerprint,
            scenario_fingerprint=scenario.fingerprint,
            max_depth=sim_input.max_depth,
            max_nodes=sim_input.max_nodes,
            max_edges=sim_input.max_edges,
            max_effects=sim_input.max_effects,
        )
        sim_id = compute_simulation_id(
            scenario_id=scenario.scenario_id,
            base_snapshot_fingerprint=snapshot.twin_fingerprint,
            configuration_hash=sim_fingerprint[:16],
        )

        SimulationObservability.log_simulation_started(
            organization_id=scenario.organization_id,
            scenario_id=scenario.scenario_id,
            simulation_id=sim_id,
            base_snapshot_fingerprint=snapshot.twin_fingerprint,
            request_id=request_id,
        )

        try:
            # 4. Deep-clone snapshot into isolated in-memory SimulationState
            state = SimulationState.from_digital_twin_snapshot(snapshot)

            # 5. Apply hypothetical changes strictly in-memory
            for change in scenario.changes:
                state.apply_change(change)

            # 6. Execute bounded, deterministic graph propagation
            prop_engine = SimulationPropagationEngine(
                simulation_id=sim_id,
                max_depth=sim_input.max_depth,
                max_nodes=sim_input.max_nodes,
                max_edges=sim_input.max_edges,
                max_effects=sim_input.max_effects,
            )
            effects, nodes_visited, edges_traversed = prop_engine.propagate(state)

            # 7. Evaluate baseline vs simulated risk read-only if requested
            baseline_risk, simulated_risk = None, None
            if sim_input.evaluate_risk:
                baseline_risk, simulated_risk = SimulationEngine._evaluate_risk_scores(snapshot, state)

            # 8. Compute standardized metrics & outcome
            metrics_dict, outcome = SimulationMetricsCalculator.calculate_metrics(
                state=state,
                effects=effects,
                baseline_risk_score=baseline_risk,
                simulated_risk_score=simulated_risk,
            )

            # 9. Build execution provenance
            provenance = SimulationProvenance(
                base_snapshot_fingerprint=snapshot.twin_fingerprint,
                base_snapshot_id=snapshot.twin_id,
                organization_id=scenario.organization_id,
                source_system="DIGITAL_TWIN_SNAPSHOT",
                created_at=datetime.utcnow(),
                metadata={
                    "nodes_visited": nodes_visited,
                    "edges_traversed": edges_traversed,
                    "effects_count": len(effects),
                    "changes_count": len(scenario.changes),
                },
            )

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            result = SimulationResult(
                simulation_id=sim_id,
                scenario_id=scenario.scenario_id,
                organization_id=scenario.organization_id,
                base_snapshot_fingerprint=snapshot.twin_fingerprint,
                simulation_fingerprint=sim_fingerprint,
                status=SimulationStatus.COMPLETED,
                outcome=outcome,
                changes=list(scenario.changes),
                effects=effects,
                metrics=metrics_dict,
                provenance=provenance,
                executed_at=datetime.utcnow(),
                execution_duration_ms=round(duration_ms, 2),
            )

            SimulationObservability.log_simulation_completed(
                organization_id=scenario.organization_id,
                scenario_id=scenario.scenario_id,
                simulation_id=sim_id,
                simulation_fingerprint=sim_fingerprint,
                duration_ms=duration_ms,
                effects_count=len(effects),
                nodes_visited=nodes_visited,
                edges_traversed=edges_traversed,
                severity=outcome.severity,
                request_id=request_id,
            )

            return result

        except (SimulationValidationError, SimulationTenantIsolationError, SimulationResourceLimitError) as e:
            SimulationObservability.log_simulation_failed(
                organization_id=scenario.organization_id,
                scenario_id=scenario.scenario_id,
                simulation_id=sim_id,
                error_category=type(e).__name__,
                error_message=str(e),
                request_id=request_id,
            )
            raise

        except Exception as e:
            SimulationObservability.log_simulation_failed(
                organization_id=scenario.organization_id,
                scenario_id=scenario.scenario_id,
                simulation_id=sim_id,
                error_category="UNEXPECTED_ENGINE_ERROR",
                error_message=str(e),
                request_id=request_id,
            )
            raise SimulationError(f"Simulation execution failed: {str(e)}")

    @staticmethod
    def _evaluate_risk_scores(
        snapshot: DigitalTwinSnapshot,
        state: SimulationState,
    ) -> Tuple[Optional[float], Optional[float]]:
        """Calculate read-only baseline and simulated risk scores without DB mutation."""
        # Baseline risk derived from node health scores
        nodes_with_health = [n for n in snapshot.nodes.values() if n.health_score is not None]
        if nodes_with_health:
            baseline_avg_health = sum(n.health_score for n in nodes_with_health) / len(nodes_with_health)
            baseline_risk = max(0.0, min(100.0, 100.0 - baseline_avg_health))
        else:
            baseline_risk = 20.0  # Operational baseline

        # Simulated risk incorporates disruptions, outages, and delays
        disruption_penalty = 0.0
        for n in state.nodes.values():
            if not n.is_available:
                disruption_penalty += 15.0
            elif n.effective_delay_minutes > 0.0:
                disruption_penalty += min(10.0, n.effective_delay_minutes / 60.0)

        for e in state.edges.values():
            if not e.is_available:
                disruption_penalty += 10.0
            elif e.added_transit_time_minutes > 0.0:
                disruption_penalty += min(5.0, e.added_transit_time_minutes / 60.0)

        simulated_risk = max(0.0, min(100.0, baseline_risk + disruption_penalty))
        return round(baseline_risk, 2), round(simulated_risk, 2)
