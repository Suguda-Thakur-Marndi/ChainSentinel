"""Central orchestration service for RiskWise Optimization Subsystem (Phase 14).

Coordinates:
- Input validation and tenant boundaries
- Digital Twin topology extraction
- Simulation effect integration
- Mathematical model formulation
- Google OR-Tools execution
- Result assembly and baseline metric comparisons
- Transactional persistence in optimization_runs
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.digital_twin.contracts import DigitalTwinSnapshot
from app.digital_twin.service import DigitalTwinService
from app.optimization.config import (
    DEFAULT_SOLVER_TIMEOUT_SECONDS,
    OPTIMIZATION_ENGINE_VERSION,
)
from app.optimization.contracts import (
    OptimizationAlternative,
    OptimizationDomain,
    OptimizationObjectiveType,
    OptimizationProvenance,
    OptimizationRequest,
    OptimizationResult,
    OptimizationSolverConfig,
    OptimizationStatus,
)
from app.optimization.constraints import ConstraintBuilder
from app.optimization.errors import (
    OptimizationDataMissingError,
    OptimizationError,
    OptimizationInfeasibleError,
    OptimizationResourceLimitError,
    OptimizationSolverUnavailableError,
    OptimizationTenantIsolationError,
    OptimizationValidationError,
)
from app.optimization.fingerprints import compute_request_fingerprint
from app.optimization.integration import (
    DigitalTwinOptimizationIntegration,
    RiskEngineOptimizationIntegration,
    SimulationOptimizationIntegration,
)
from app.optimization.model import ModelBuilder
from app.optimization.objectives import ObjectiveBuilder
from app.optimization.persistence import OptimizationRepository
from app.optimization.result import ResultBuilder
from app.optimization.solver import OrToolsSolver
from app.optimization.validators import OptimizationValidator
from app.optimization.variables import VariableBuilder

logger = logging.getLogger("riskwise.optimization.service")


class OptimizationService:
    """Service providing end-to-end mathematical supply chain optimization."""

    @classmethod
    def run_optimization(
        cls,
        db: Session,
        request: OptimizationRequest,
        expected_organization_id: Optional[str] = None,
    ) -> OptimizationResult:
        """Formulate and solve mathematical optimization problem."""
        start_time = time.perf_counter()

        # 1. Validate request and tenant isolation
        OptimizationValidator.validate_request(
            request, expected_organization_id=expected_organization_id
        )

        # 2. Extract or resolve candidate alternatives
        candidates = list(request.candidate_alternatives)
        snapshot_fingerprint = "0" * 64
        snapshot_id = request.digital_twin_snapshot_id

        if not candidates:
            # Load from Digital Twin snapshot if candidates not explicitly provided
            snapshot = DigitalTwinService.get_twin_snapshot(
                db=db, organization_id=request.organization_id
            )
            if snapshot:
                snapshot_fingerprint = snapshot.twin_fingerprint
                snapshot_id = snapshot.twin_id
                candidates = DigitalTwinOptimizationIntegration.extract_candidate_routes(
                    snapshot=snapshot, organization_id=request.organization_id
                )

        # 3. Apply simulation effects if simulation_id provided
        sim_fingerprint = None
        if request.simulation_id:
            from app.simulation.service import SimulationService
            sim_res = SimulationService.get_simulation_result(
                db=db,
                organization_id=request.organization_id,
                simulation_id=request.simulation_id,
            )
            if sim_res:
                sim_fingerprint = sim_res.simulation_fingerprint
                candidates = SimulationOptimizationIntegration.apply_simulation_effects_to_candidates(
                    candidates=candidates,
                    simulation_result=sim_res,
                )

        # 4. Compute request fingerprint
        req_fp = compute_request_fingerprint(
            organization_id=request.organization_id,
            domain=request.domain.value,
            objective_type=request.objective_type.value,
            snapshot_fingerprint=snapshot_fingerprint,
            simulation_fingerprint=sim_fingerprint,
            target_entity_ids=request.target_entity_ids,
            candidates=[c.model_dump(mode="json") for c in candidates],
            solver_config=request.solver_config.model_dump(mode="json") if request.solver_config else None,
            parameters=request.parameters,
        )

        # Check for zero candidates
        if not candidates:
            # Cannot formulate problem without candidates
            solver_meta = {"reason": "No candidate alternatives available"}
            provenance = OptimizationProvenance(
                organization_id=request.organization_id,
                digital_twin_snapshot_fingerprint=snapshot_fingerprint,
                digital_twin_snapshot_id=snapshot_id,
                scenario_id=request.scenario_id,
                simulation_id=request.simulation_id,
                simulation_fingerprint=sim_fingerprint,
                engine_version=OPTIMIZATION_ENGINE_VERSION,
            )
            # Create a dummy objective for representation
            obj = ObjectiveBuilder.build_objective(
                objective_type=request.objective_type,
                variables={},
                candidates=[],
            )
            problem = ModelBuilder.create_problem(
                organization_id=request.organization_id,
                domain=request.domain,
                variables={},
                constraints={},
                objective=obj,
                candidates=[],
                solver_config=request.solver_config,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            result = ResultBuilder.build_result(
                problem=problem,
                status=OptimizationStatus.INFEASIBLE,
                objective_value=None,
                variable_assignments={},
                solver_metadata=solver_meta,
                provenance=provenance,
                request_fingerprint=req_fp,
                duration_ms=duration_ms,
                failure_reason="No candidate alternatives available for optimization domain",
            )
            OptimizationRepository.save_optimization_run(db, result)
            return result

        # 5. Build decision variables
        shipment_ids = request.target_entity_ids or ["shipment_default"]
        variables = VariableBuilder.build_shipment_reroute_variables(
            shipment_ids=shipment_ids,
            candidates=candidates,
        )

        # 6. Build constraints
        constraints = {}
        # Assignment constraints
        constraints.update(
            ConstraintBuilder.build_shipment_assignment_constraints(
                shipment_ids=shipment_ids, variables=variables
            )
        )
        # Availability constraints
        constraints.update(
            ConstraintBuilder.build_availability_constraints(
                candidates=candidates, variables=variables
            )
        )
        # Capacity constraints
        constraints.update(
            ConstraintBuilder.build_capacity_constraints(
                candidates=candidates, variables=variables
            )
        )

        # 7. Build objective
        objective = ObjectiveBuilder.build_objective(
            objective_type=request.objective_type,
            variables=variables,
            candidates=candidates,
        )

        # 8. Assemble OptimizationProblem
        problem = ModelBuilder.create_problem(
            organization_id=request.organization_id,
            domain=request.domain,
            variables=variables,
            constraints=constraints,
            objective=objective,
            candidates=candidates,
            solver_config=request.solver_config,
        )

        # 9. Solve using Google OR-Tools
        status, obj_val, assignments, solver_meta = OrToolsSolver.solve(problem)

        # 10. Compute baseline metrics
        baseline_metrics: Dict[str, float] = {}
        if request.parameters.get("baseline_delay_hours") is not None:
            baseline_metrics["baseline_delay_hours"] = float(request.parameters["baseline_delay_hours"])
        if request.parameters.get("baseline_cost") is not None:
            baseline_metrics["baseline_cost"] = float(request.parameters["baseline_cost"])
        if request.parameters.get("baseline_risk") is not None:
            baseline_metrics["baseline_risk"] = float(request.parameters["baseline_risk"])

        # 11. Assemble OptimizationResult
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        provenance = OptimizationProvenance(
            organization_id=request.organization_id,
            digital_twin_snapshot_fingerprint=snapshot_fingerprint,
            digital_twin_snapshot_id=snapshot_id,
            scenario_id=request.scenario_id,
            simulation_id=request.simulation_id,
            simulation_fingerprint=sim_fingerprint,
            engine_version=OPTIMIZATION_ENGINE_VERSION,
        )

        result = ResultBuilder.build_result(
            problem=problem,
            status=status,
            objective_value=obj_val,
            variable_assignments=assignments,
            solver_metadata=solver_meta,
            provenance=provenance,
            request_fingerprint=req_fp,
            duration_ms=duration_ms,
            baseline_metrics=baseline_metrics,
            failure_reason=None if status in (OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE) else f"Solver outcome: {status.value}",
        )

        # 12. Transactional persistence
        OptimizationRepository.save_optimization_run(
            db=db,
            result=result,
            candidate_actions=[c.model_dump(mode="json") for c in candidates],
        )

        return result

    @classmethod
    def get_optimization_result(
        cls,
        db: Session,
        organization_id: str,
        optimization_id: str,
    ) -> Optional[OptimizationResult]:
        """Retrieve stored optimization result enforcing tenant boundary."""
        record = OptimizationRepository.get_by_id(
            db=db, organization_id=organization_id, optimization_id=optimization_id
        )
        if not record:
            return None
        if isinstance(record.recommended_plan, dict) and "optimization_id" in record.recommended_plan:
            return OptimizationResult.model_validate(record.recommended_plan)
        return None

    @classmethod
    def list_optimization_runs(
        cls,
        db: Session,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[OptimizationResult]:
        """List past optimization run outcomes for tenant."""
        records = OptimizationRepository.list_by_organization(
            db=db, organization_id=organization_id, limit=limit, offset=offset
        )
        results: List[OptimizationResult] = []
        for r in records:
            if isinstance(r.recommended_plan, dict) and "optimization_id" in r.recommended_plan:
                try:
                    results.append(OptimizationResult.model_validate(r.recommended_plan))
                except Exception:
                    continue
        return results
