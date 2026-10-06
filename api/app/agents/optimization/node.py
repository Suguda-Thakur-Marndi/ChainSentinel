"""LangGraph Optimization node orchestrating Google OR-Tools mathematical optimization.

Consumes:
- Digital Twin candidate routes via CandidateRouteGenerator
- Simulation effects & disruptions
- Formulates mixed-integer linear programming (MIP) problems
- Solves via Google OR-Tools pywraplp
- Emits optimization_result and optimization_plan for Decision Agent
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.agents.contracts import (
    AgentGraphStateDict,
    AgentNodeContract,
    AgentStage,
    ToolSideEffectType,
    validate_state_update,
)
from app.agents.observability import AgentObservability, NodeExecutionTelemetry
from app.digital_twin.contracts import DigitalTwinSnapshot
from app.digital_twin.service import DigitalTwinService
from app.optimization.candidates import CandidateRouteGenerator
from app.optimization.contracts import (
    OptimizationDomain,
    OptimizationObjectiveType,
    OptimizationRequest,
    OptimizationResult,
    OptimizationStatus,
)
from app.optimization.errors import (
    OptimizationError,
    OptimizationTenantIsolationError,
)
from app.optimization.service import OptimizationService

logger = logging.getLogger("riskwise.agents.optimization.node")


OPTIMIZATION_NODE_CONTRACT = AgentNodeContract(
    node_id="optimization_node",
    name="Optimization Node",
    description=(
        "Orchestration node: formulates and solves mathematical optimization models via Google OR-Tools, "
        "generating optimal alternative routes, allocations, and trade-offs under simulation constraints."
    ),
    stage=AgentStage.OPTIMIZATION,
    is_side_effecting=False,
    side_effect_type=ToolSideEffectType.READ_ONLY,
    input_keys=[
        "organization_id",
        "actor_id",
        "run_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "simulation_id",
        "simulation_reference",
        "simulation_result",
        "digital_twin_snapshot",
    ],
    output_keys=[
        "optimization_id",
        "optimization_reference",
        "optimization_result",
        "optimization_plan",
        "current_stage",
        "current_node",
        "step_count",
    ],
    required_roles=["analyst", "admin", "system"],
    requires_evidence=False,
    retryable=False,
    max_retries=0,
    timeout_seconds=30.0,
)


def optimization_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """Execute the optimization node within the LangGraph StateGraph pipeline.
    
    Generates candidate routes from Digital Twin and database, incorporates simulation impacts,
    solves with Google OR-Tools, and populates optimization_result and optimization_plan.
    """
    start_time = time.perf_counter()
    status = "SUCCESS"
    error_code: Optional[str] = None

    org_id = state.get("organization_id", "")
    run_id = state.get("run_id", "")
    actor_id = state.get("actor_id", "")
    request_id = state.get("request_id", "")
    correlation_id = state.get("correlation_id", "")
    trace_id = state.get("trace_id", "")

    db_created = False
    db = state.get("db")

    try:
        if not org_id or not str(org_id).strip():
            raise OptimizationTenantIsolationError("optimization_node requires non-empty 'organization_id' in state.")
        org_id = org_id.strip()

        # 1. Resolve database session
        if db is None:
            try:
                from app.db.session import SessionLocal
                db = SessionLocal()
                db_created = True
            except Exception as e:
                logger.debug("Local db session not available: %s", e)

        # 2. Retrieve Digital Twin snapshot
        snapshot: Optional[DigitalTwinSnapshot] = None
        raw_twin = state.get("digital_twin_snapshot")
        if raw_twin is not None:
            if isinstance(raw_twin, DigitalTwinSnapshot):
                snapshot = raw_twin
            elif isinstance(raw_twin, dict):
                snapshot = DigitalTwinSnapshot.model_validate(raw_twin)

        if snapshot is None and db is not None:
            try:
                snapshot = DigitalTwinService.retrieve_current_twin(db=db, organization_id=org_id)
            except Exception as dt_err:
                logger.warning(f"Could not retrieve twin from db: {dt_err}")

        # 3. Extract simulation result and candidates
        sim_id = state.get("simulation_id")
        sim_result = state.get("simulation_result")

        candidates = CandidateRouteGenerator.generate_candidates(
            organization_id=org_id,
            snapshot=snapshot,
            db=db,
            simulation_result=sim_result,
        )

        # 4. Formulate Optimization Request
        opt_request = OptimizationRequest(
            organization_id=org_id,
            domain=OptimizationDomain.ROUTE_SELECTION,
            objective_type=OptimizationObjectiveType.MINIMIZE_COST,
            target_entity_ids=[sim_id] if sim_id else [],
            candidate_alternatives=candidates,
            simulation_id=sim_id,
            digital_twin_snapshot_id=snapshot.twin_id if snapshot else None,
            scenario_id=state.get("scenario_id"),
        )

        # 5. Execute Optimization Service (OR-Tools)
        opt_result: OptimizationResult
        if db is not None:
            opt_result = OptimizationService.run_optimization(
                db=db,
                request=opt_request,
                expected_organization_id=org_id,
            )
        else:
            # Headless solving without db persistence
            from app.optimization.model import ModelBuilder
            from app.optimization.objectives import ObjectiveBuilder
            from app.optimization.result import ResultBuilder
            from app.optimization.solver import OrToolsSolver
            from app.optimization.variables import VariableBuilder

            vars_dict = VariableBuilder.build_variables(opt_request.domain, candidates)
            obj = ObjectiveBuilder.build_objective(
                opt_request.objective_type, vars_dict, candidates
            )
            prob = ModelBuilder.create_problem(
                organization_id=org_id,
                domain=opt_request.domain,
                variables=vars_dict,
                constraints={},
                objective=obj,
                candidates=candidates,
                solver_config=opt_request.solver_config,
            )
            sol_status, obj_val, var_assignments, solver_meta = OrToolsSolver.solve(prob)
            opt_result = ResultBuilder.build_result(
                problem=prob,
                status=sol_status,
                objective_value=obj_val,
                variable_assignments=var_assignments,
                solver_metadata=solver_meta,
                digital_twin_snapshot_id=snapshot.twin_id if snapshot else None,
                digital_twin_snapshot_fingerprint=snapshot.twin_fingerprint if snapshot else ("0" * 64),
                scenario_id=state.get("scenario_id"),
                simulation_id=sim_id,
                simulation_fingerprint=state.get("simulation_reference", {}).get("fingerprint") if isinstance(state.get("simulation_reference"), dict) else None,
            )

        opt_dict = opt_result.model_dump(mode="json")

        # 6. Formulate structured Optimization Plan
        selected_candidates = [
            c.model_dump(mode="json")
            for c in opt_result.selected_alternatives
        ]
        plan = {
            "optimization_id": opt_result.optimization_id,
            "organization_id": org_id,
            "status": opt_result.status.value,
            "objective_value": opt_result.objective_value,
            "selected_alternatives": selected_candidates,
            "metrics": {
                k: m.model_dump(mode="json") for k, m in opt_result.metrics.items()
            },
            "recommendation_summary": (
                f"Selected {len(selected_candidates)} alternative routes with objective value {opt_result.objective_value:.2f}"
                if opt_result.objective_value is not None
                else f"Optimization concluded with status {opt_result.status.value}"
            ),
        }

        opt_ref = {
            "optimization_id": opt_result.optimization_id,
            "organization_id": org_id,
            "status": opt_result.status.value,
            "objective_value": opt_result.objective_value,
            "selected_count": len(selected_candidates),
            "fingerprint": opt_result.result_fingerprint,
        }

        step_count = state.get("step_count", 0) + 1

        update_payload: Dict[str, Any] = {
            "optimization_id": opt_result.optimization_id,
            "optimization_reference": opt_ref,
            "optimization_result": opt_dict,
            "optimization_plan": plan,
            "current_stage": AgentStage.OPTIMIZATION.value,
            "current_node": "optimization_node",
            "step_count": step_count,
        }

        # 7. Validate state update against authoritative field ownership
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="optimization_node",
            writer_stage=AgentStage.OPTIMIZATION,
        )

        return update_payload

    except Exception as exc:
        status = "FAILED"
        error_code = exc.__class__.__name__
        logger.error("Optimization node failed: %s", exc, exc_info=True)
        raise
    finally:
        if db_created and db is not None:
            try:
                db.close()
            except Exception:
                pass
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        AgentObservability.emit_node_telemetry(
            NodeExecutionTelemetry(
                run_id=run_id or "unknown_run",
                organization_id=org_id or "unknown_org",
                actor_id=actor_id or "unknown_actor",
                request_id=request_id or "unknown_req",
                correlation_id=correlation_id or "unknown_corr",
                trace_id=trace_id or "unknown_trace",
                node_name="optimization_node",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )
