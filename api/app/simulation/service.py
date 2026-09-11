"""Application-level service orchestrating what-if simulation workflows."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from sqlalchemy.orm import Session

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.digital_twin.service import DigitalTwinService
from app.simulation.contracts import (
    SimulationComparison,
    SimulationInput,
    SimulationRequest,
    SimulationResult,
    SimulationScenario,
)
from app.simulation.engine import SimulationEngine
from app.simulation.errors import (
    SimulationError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.repository import SimulationRepository


class SimulationService:
    """Orchestrates tenant validation, Digital Twin loading, simulation execution, and persistence."""

    @classmethod
    def create_scenario(
        cls,
        db: Session,
        organization_id: str,
        scenario: SimulationScenario,
        user_id: Optional[str] = None,
    ) -> SimulationScenario:
        """Validate and persist a new what-if scenario."""
        if scenario.organization_id != organization_id:
            raise SimulationTenantIsolationError("Scenario organization_id does not match authenticated tenant")

        repo = SimulationRepository(db, organization_id)
        repo.save_scenario(scenario, user_id=user_id)
        return scenario

    @classmethod
    def get_scenario(
        cls,
        db: Session,
        organization_id: str,
        scenario_id: str,
    ) -> Optional[SimulationScenario]:
        """Fetch scenario definition by ID."""
        repo = SimulationRepository(db, organization_id)
        return repo.get_scenario(scenario_id)

    @classmethod
    def list_scenarios(
        cls,
        db: Session,
        organization_id: str,
    ) -> List[SimulationScenario]:
        """List all scenarios for the authenticated organization."""
        repo = SimulationRepository(db, organization_id)
        return repo.list_scenarios()

    @classmethod
    def run_simulation(
        cls,
        db: Session,
        organization_id: str,
        scenario_id: str,
        sim_input: Optional[Union[SimulationInput, SimulationRequest]] = None,
        snapshot: Optional[DigitalTwinSnapshot] = None,
        request_id: Optional[str] = None,
    ) -> SimulationResult:
        """Execute a simulation for a stored or provided scenario against the Digital Twin."""
        repo = SimulationRepository(db, organization_id)

        # 1. Load scenario
        scenario = repo.get_scenario(scenario_id)
        if not scenario:
            raise SimulationValidationError(f"Scenario '{scenario_id}' not found for tenant '{organization_id}'")

        # 2. Load active Digital Twin snapshot if not explicitly provided
        if snapshot is None:
            snapshot = DigitalTwinService.retrieve_current_twin(db=db, organization_id=organization_id)

        # Verify tenant boundary on snapshot
        if snapshot.organization_id != organization_id:
            raise SimulationTenantIsolationError(
                f"Digital Twin snapshot belongs to organization '{snapshot.organization_id}', not '{organization_id}'"
            )

        # 3. Execute headless simulation engine
        result = SimulationEngine.execute_simulation(
            snapshot=snapshot,
            scenario=scenario,
            sim_input=sim_input,
            request_id=request_id,
        )

        # 4. Idempotently persist result
        repo.save_simulation_result(result)

        return result

    @classmethod
    def get_simulation_result(
        cls,
        db: Session,
        organization_id: str,
        simulation_id: str,
    ) -> Optional[SimulationResult]:
        """Retrieve historical simulation outcome."""
        repo = SimulationRepository(db, organization_id)
        return repo.get_simulation_result(simulation_id)

    @classmethod
    def compare_scenarios(
        cls,
        db: Session,
        organization_id: str,
        scenario_a_id: str,
        scenario_b_id: str,
        snapshot: Optional[DigitalTwinSnapshot] = None,
    ) -> SimulationComparison:
        """Deterministically compare outcomes between two scenarios."""
        # Execute or retrieve runs for both
        result_a = cls.run_simulation(db, organization_id, scenario_a_id, snapshot=snapshot)
        result_b = cls.run_simulation(db, organization_id, scenario_b_id, snapshot=snapshot)

        metric_comparisons: Dict[str, Dict[str, Any]] = {}
        findings: List[str] = []

        # Compare metrics
        all_metric_keys = sorted(set(result_a.metrics.keys()).union(set(result_b.metrics.keys())))
        for k in all_metric_keys:
            m_a = result_a.metrics.get(k)
            m_b = result_b.metrics.get(k)
            val_a = m_a.simulated_value if m_a else None
            val_b = m_b.simulated_value if m_b else None

            delta_between = None
            if val_a is not None and val_b is not None:
                delta_between = round(val_b - val_a, 2)

            metric_comparisons[k] = {
                "scenario_a": val_a,
                "scenario_b": val_b,
                "difference_b_minus_a": delta_between,
                "unit": m_a.unit if m_a else (m_b.unit if m_b else ""),
            }

        # Synthesize findings
        delay_diff = metric_comparisons.get("total_delay_minutes", {}).get("difference_b_minus_a")
        if delay_diff is not None:
            if delay_diff > 0:
                findings.append(f"Scenario B introduces {delay_diff:.1f} more minutes of total delay than Scenario A")
            elif delay_diff < 0:
                findings.append(f"Scenario A introduces {abs(delay_diff):.1f} more minutes of total delay than Scenario B")
            else:
                findings.append("Both scenarios produce identical delay impact")

        return SimulationComparison(
            organization_id=organization_id,
            scenario_a_id=scenario_a_id,
            scenario_b_id=scenario_b_id,
            metric_comparisons=metric_comparisons,
            summary_findings=findings,
        )
