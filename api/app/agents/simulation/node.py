"""LangGraph Simulation node orchestrating Monte Carlo and deterministic what-if execution.

Consumes:
- Digital Twin topology (twin_nodes, twin_edges)
- Scenario definitions from scenario_agent
- Propagates delays, capacity loss, and disruption effects through the supply chain graph
- Computes P10, P50, P90, P95 delay percentiles
- Produces simulation_result and downstream_affected_nodes for decision & optimization
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
from app.agents.security import sanitize_sensitive_data
from app.digital_twin.contracts import DigitalTwinSnapshot
from app.digital_twin.service import DigitalTwinService
from app.simulation.contracts import (
    SimulationInput,
    SimulationResult,
    SimulationScenario,
)
from app.simulation.engine import SimulationEngine
from app.simulation.errors import (
    SimulationError,
    SimulationTenantIsolationError,
)
from app.simulation.scenario import SimulationScenarioBuilder

logger = logging.getLogger("riskwise.agents.simulation.node")


SIMULATION_NODE_CONTRACT = AgentNodeContract(
    node_id="simulation_node",
    name="Simulation Node",
    description=(
        "Orchestration node: executes deterministic Monte Carlo what-if scenario simulations "
        "against the authoritative Digital Twin topology, quantifying delay propagation and risk delta."
    ),
    stage=AgentStage.SIMULATION,
    is_side_effecting=False,
    side_effect_type=ToolSideEffectType.READ_ONLY,
    input_keys=[
        "organization_id",
        "actor_id",
        "run_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "scenario_id",
        "scenario_reference",
        "scenario_result",
        "digital_twin_snapshot",
    ],
    output_keys=[
        "simulation_id",
        "simulation_reference",
        "simulation_result",
        "simulation_results",
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


def simulation_node(state: AgentGraphStateDict) -> Dict[str, Any]:
    """Execute the simulation node within the LangGraph StateGraph pipeline.
    
    Loads or generates Digital Twin topology, builds/resolves what-if scenario,
    runs SimulationEngine, and populates simulation_result and percentiles into state.
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
            raise SimulationTenantIsolationError("simulation_node requires non-empty 'organization_id' in state.")
        org_id = org_id.strip()

        # 1. Resolve database session if not provided
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

        # Fallback in-memory minimal snapshot if db not available
        if snapshot is None:
            from app.digital_twin.contracts import DigitalTwinNode, DigitalTwinEdge, DigitalTwinGraphMeta
            import hashlib
            from datetime import datetime, timezone

            fp = hashlib.sha256(f"{org_id}:synthetic_fallback".encode("utf-8")).hexdigest()
            snapshot = DigitalTwinSnapshot(
                twin_id=f"twin_{org_id[:8]}",
                organization_id=org_id,
                version="1.0",
                nodes={},
                edges={},
                meta=DigitalTwinGraphMeta(
                    organization_id=org_id,
                    twin_id=f"twin_{org_id[:8]}",
                    node_count=0,
                    edge_count=0,
                    total_flow_capacity=0.0,
                    graph_density=0.0,
                    is_connected=True,
                    created_at=datetime.now(timezone.utc),
                ),
                twin_fingerprint=fp,
            )

        if snapshot.organization_id != org_id:
            raise SimulationTenantIsolationError(
                f"Digital Twin belongs to '{snapshot.organization_id}', state scoped to '{org_id}'"
            )

        # 3. Resolve or construct scenario
        scenario: Optional[SimulationScenario] = None
        scenario_id = state.get("scenario_id")
        scen_ref = state.get("scenario_reference")
        scen_res = state.get("scenario_result")

        # Try loading scenario from repository if db exists
        if scenario_id and db is not None:
            from app.simulation.repository import SimulationRepository
            repo = SimulationRepository(db, org_id)
            scenario = repo.get_scenario(scenario_id)

        if scenario is None:
            # Construct a what-if scenario from upstream scenario_result or default
            scenario_name = "Automated Disruption Scenario"
            builder = SimulationScenarioBuilder(org_id, scenario_name, snapshot.twin_fingerprint)

            # Check if upstream scenario_result defined parameters or disruptions
            if isinstance(scen_res, dict):
                target_ref = scen_res.get("target_reference") or scen_res.get("shipment_id")
                if target_ref:
                    builder.add_delay(str(target_ref), target_entity_type="SHIPMENT", delay_hours=12.0)
            elif snapshot.edges:
                # Add delay to first route edge in twin topology
                first_edge = next(iter(snapshot.edges.values()))
                builder.add_edge_outage(first_edge.edge_id, duration_hours=24.0)

            scenario = builder.build()
            if db is not None:
                try:
                    repo = SimulationRepository(db, org_id)
                    repo.save_scenario(scenario)
                except Exception as save_err:
                    logger.debug("Scenario save skipped: %s", save_err)

        # 4. Execute Simulation Engine
        sim_input = SimulationInput(scenario=scenario, evaluate_risk=True, evaluate_ml=False)
        sim_result: SimulationResult = SimulationEngine.execute_simulation(
            snapshot=snapshot,
            scenario=scenario,
            sim_input=sim_input,
            request_id=request_id,
        )

        # Persist simulation result if db available
        if db is not None:
            try:
                repo = SimulationRepository(db, org_id)
                repo.save_simulation_result(sim_result)
            except Exception as res_err:
                logger.debug("Simulation result save skipped: %s", res_err)

        sim_dict = sim_result.model_dump(mode="json")

        # 5. Build authoritative simulation reference
        outcome = sim_result.outcome
        sim_ref = {
            "simulation_id": sim_result.simulation_id,
            "scenario_id": sim_result.scenario_id,
            "organization_id": org_id,
            "status": sim_result.status.value,
            "severity": outcome.severity if outcome else "LOW",
            "total_added_delay_minutes": outcome.total_added_delay_minutes if outcome else 0.0,
            "p10_delay_minutes": outcome.p10_delay_minutes if outcome else None,
            "p50_delay_minutes": outcome.p50_delay_minutes if outcome else None,
            "p90_delay_minutes": outcome.p90_delay_minutes if outcome else None,
            "p95_delay_minutes": outcome.p95_delay_minutes if outcome else None,
            "downstream_affected_nodes": sim_result.propagation.downstream_affected_nodes if sim_result.propagation else [],
            "fingerprint": sim_result.simulation_fingerprint,
        }

        step_count = state.get("step_count", 0) + 1

        update_payload: Dict[str, Any] = {
            "simulation_id": sim_result.simulation_id,
            "simulation_reference": sim_ref,
            "simulation_result": sim_dict,
            "simulation_results": sim_dict,
            "current_stage": AgentStage.SIMULATION.value,
            "current_node": "simulation_node",
            "step_count": step_count,
        }

        # 6. Validate state update against authoritative field ownership
        validate_state_update(
            current_state=state,
            update_payload=update_payload,
            writer_node_id="simulation_node",
            writer_stage=AgentStage.SIMULATION,
        )

        return update_payload

    except Exception as exc:
        status = "FAILED"
        error_code = exc.__class__.__name__
        logger.error("Simulation node failed: %s", exc, exc_info=True)
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
                node_name="simulation_node",
                duration_ms=round(duration_ms, 2),
                status=status,
                error_code=error_code,
                step_count=state.get("step_count", 0),
            )
        )
