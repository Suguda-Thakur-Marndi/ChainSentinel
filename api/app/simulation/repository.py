"""Repository abstraction for tenant-scoped scenario and simulation persistence."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.models.simulation import Scenario, Simulation
from app.simulation.contracts import (
    MetricAvailability,
    SimulationChange,
    SimulationEffect,
    SimulationMetric,
    SimulationOutcome,
    SimulationProvenance,
    SimulationResult,
    SimulationScenario,
    SimulationStatus,
)
from app.simulation.errors import (
    SimulationPersistenceError,
    SimulationTenantIsolationError,
)


class SimulationRepository:
    """Provides safe, tenant-isolated transactional access to scenarios and simulation runs."""

    def __init__(self, db: Session, organization_id: str):
        if not organization_id or not organization_id.strip():
            raise SimulationTenantIsolationError("organization_id must be provided")
        self.db = db
        self.organization_id = organization_id.strip()

    def save_scenario(self, scenario: SimulationScenario, user_id: Optional[str] = None) -> Scenario:
        """Idempotently create or update a scenario record."""
        if scenario.organization_id != self.organization_id:
            raise SimulationTenantIsolationError(
                f"Cannot persist scenario for organization '{scenario.organization_id}' "
                f"under repository organization '{self.organization_id}'"
            )

        existing = self.db.query(Scenario).filter(
            Scenario.id == scenario.scenario_id,
            Scenario.org_id == self.organization_id,
        ).first()

        variables = {
            "base_snapshot_fingerprint": scenario.base_snapshot_fingerprint,
            "fingerprint": scenario.fingerprint,
            "parameters": scenario.parameters,
            "changes": [c.model_dump(mode="json") for c in scenario.changes],
        }

        if existing:
            existing.name = scenario.name
            existing.description = scenario.description
            existing.variables_json = variables
            self.db.flush()
            return existing

        new_scenario = Scenario(
            id=scenario.scenario_id,
            org_id=self.organization_id,
            name=scenario.name,
            description=scenario.description,
            variables_json=variables,
            created_by_user_id=user_id,
        )
        self.db.add(new_scenario)
        self.db.flush()
        return new_scenario

    def get_scenario(self, scenario_id: str) -> Optional[SimulationScenario]:
        """Retrieve a scenario contract by ID, enforcing tenant isolation."""
        record = self.db.query(Scenario).filter(
            Scenario.id == scenario_id,
        ).first()

        if not record:
            return None

        if record.org_id != self.organization_id:
            raise SimulationTenantIsolationError(
                f"Access denied: Scenario '{scenario_id}' belongs to another tenant"
            )

        variables = record.variables_json or {}
        raw_changes = variables.get("changes", [])
        changes = [SimulationChange.model_validate(c) for c in raw_changes]

        return SimulationScenario(
            scenario_id=record.id,
            organization_id=record.org_id,
            name=record.name,
            description=record.description,
            base_snapshot_fingerprint=variables.get("base_snapshot_fingerprint", ""),
            changes=changes,
            parameters=variables.get("parameters", {}),
            created_at=record.created_at,
            fingerprint=variables.get("fingerprint", ""),
        )

    def list_scenarios(self) -> List[SimulationScenario]:
        """List all scenarios belonging to the authenticated tenant."""
        records = self.db.query(Scenario).filter(
            Scenario.org_id == self.organization_id,
        ).order_by(Scenario.created_at.desc()).all()

        results = []
        for r in records:
            v = r.variables_json or {}
            raw_changes = v.get("changes", [])
            changes = [SimulationChange.model_validate(c) for c in raw_changes]
            results.append(
                SimulationScenario(
                    scenario_id=r.id,
                    organization_id=r.org_id,
                    name=r.name,
                    description=r.description,
                    base_snapshot_fingerprint=v.get("base_snapshot_fingerprint", ""),
                    changes=changes,
                    parameters=v.get("parameters", {}),
                    created_at=r.created_at,
                    fingerprint=v.get("fingerprint", ""),
                )
            )
        return results

    def save_simulation_result(self, result: SimulationResult) -> Simulation:
        """Idempotently persist an executed simulation run."""
        if result.organization_id != self.organization_id:
            raise SimulationTenantIsolationError(
                f"Cannot persist simulation for organization '{result.organization_id}' "
                f"under repository organization '{self.organization_id}'"
            )

        # Verify parent scenario belongs to tenant
        scenario = self.db.query(Scenario).filter(
            Scenario.id == result.scenario_id,
            Scenario.org_id == self.organization_id,
        ).first()
        if not scenario:
            raise SimulationPersistenceError(
                f"Parent scenario '{result.scenario_id}' does not exist for tenant '{self.organization_id}'"
            )

        existing = self.db.query(Simulation).filter(
            Simulation.id == result.simulation_id,
        ).first()

        baseline_data = {
            k: v.model_dump(mode="json") for k, v in result.metrics.items()
        }
        projected_data = {
            "simulation_fingerprint": result.simulation_fingerprint,
            "base_snapshot_fingerprint": result.base_snapshot_fingerprint,
            "execution_duration_ms": result.execution_duration_ms,
            "outcome": result.outcome.model_dump(mode="json"),
            "changes": [c.model_dump(mode="json") for c in result.changes],
            "effects": [e.model_dump(mode="json") for e in result.effects],
            "provenance": result.provenance.model_dump(mode="json"),
        }

        if existing:
            existing.status = result.status.value
            existing.baseline_metrics = baseline_data
            existing.projected_metrics = projected_data
            self.db.flush()
            return existing

        new_sim = Simulation(
            id=result.simulation_id,
            scenario_id=result.scenario_id,
            mode="DETERMINISTIC",
            status=result.status.value,
            baseline_metrics=baseline_data,
            projected_metrics=projected_data,
        )
        self.db.add(new_sim)
        self.db.flush()
        return new_sim

    def get_simulation_result(self, simulation_id: str) -> Optional[SimulationResult]:
        """Retrieve full SimulationResult by simulation_id enforcing tenant boundary."""
        sim = self.db.query(Simulation).filter(Simulation.id == simulation_id).first()
        if not sim:
            return None

        # Verify scenario ownership
        scenario = self.db.query(Scenario).filter(Scenario.id == sim.scenario_id).first()
        if not scenario or scenario.org_id != self.organization_id:
            raise SimulationTenantIsolationError(
                f"Access denied: Simulation '{simulation_id}' belongs to another tenant"
            )

        proj = sim.projected_metrics or {}
        base = sim.baseline_metrics or {}

        metrics = {
            k: SimulationMetric.model_validate(v) for k, v in base.items()
        }
        effects = [
            SimulationEffect.model_validate(e) for e in proj.get("effects", [])
        ]
        changes = [
            SimulationChange.model_validate(c) for c in proj.get("changes", [])
        ]
        outcome = SimulationOutcome.model_validate(proj.get("outcome", {}))
        provenance = SimulationProvenance.model_validate(proj.get("provenance", {
            "base_snapshot_fingerprint": proj.get("base_snapshot_fingerprint", ""),
            "organization_id": self.organization_id,
        }))

        return SimulationResult(
            simulation_id=sim.id,
            scenario_id=sim.scenario_id,
            organization_id=self.organization_id,
            base_snapshot_fingerprint=proj.get("base_snapshot_fingerprint", ""),
            simulation_fingerprint=proj.get("simulation_fingerprint", ""),
            status=SimulationStatus(sim.status),
            outcome=outcome,
            changes=changes,
            effects=effects,
            metrics=metrics,
            provenance=provenance,
            executed_at=sim.executed_at,
            execution_duration_ms=float(proj.get("execution_duration_ms", 0.0)),
        )
