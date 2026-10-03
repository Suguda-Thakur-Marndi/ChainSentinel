"""FastAPI endpoints for RiskWise Multi-Agent LangGraph Execution (Phase 24 & 25).

Provides REST APIs for:
- Triggering full LangGraph execution (POST /api/v1/agents/graph/run)
- Resuming execution after human authorization (POST /api/v1/agents/graph/approve)
- Inspecting graph topology nodes (GET /api/v1/agents/graph/nodes)
- Inspecting graph topology edges (GET /api/v1/agents/graph/edges)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.contracts import AgentLifecycleStatus, AgentStage
from app.agents.graph import AgentGraphBuilder, execute_agent_graph
from app.agents.observability import global_metrics_collector
from app.api.deps import get_authenticated_context, get_session_data
from app.core.config import settings
from app.core.context import AuthenticatedContext
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.models.tenancy import Organization, User

logger = logging.getLogger("riskwise.api.agents")

router = APIRouter()


class GraphRunRequest(BaseModel):
    objective: str = Field(..., description="High-level operational objective")
    organization_id: Optional[str] = Field(None, description="Tenant organization ID")
    actor_id: Optional[str] = Field(None, description="Requesting actor ID")
    input_reference: Optional[str] = Field(None, description="Primary shipment or entity ID")
    input_references: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Entity reference dictionary")
    requires_human_approval: Optional[bool] = Field(None, description="Explicit approval gate override")
    enable_action: bool = Field(False, description="Whether to execute action if approved")
    enable_verification: bool = Field(False, description="Whether to execute verification after action")
    action_mode: str = Field("SIMULATED", description="Action execution mode: SIMULATED or LIVE")
    thread_id: Optional[str] = Field(None, description="LangGraph thread ID")


class GraphApproveRequest(BaseModel):
    run_id: str = Field(..., description="Execution Run ID to resume")
    decision: str = Field("APPROVE", description="Decision: APPROVE or REJECT")
    comments: Optional[str] = Field("Approved via API", description="Auditable approval comments")
    decision_id: Optional[str] = Field(None, description="Bound decision ID")
    decision_result: Optional[Dict[str, Any]] = Field(None, description="Upstream decision result dictionary")
    enable_action: bool = Field(True, description="Execute action upon approval")
    enable_verification: bool = Field(True, description="Execute outcome verification")


def resolve_calling_context(
    request: Request,
    db: Session,
) -> tuple[str, str]:
    """Helper to resolve organization_id and actor_id from session or default dev fallback."""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        try:
            from app.services.session_service import get_session_service
            svc = get_session_service()
            sdata = svc.get_session(session_id)
            if sdata and sdata.user_id:
                user = db.get(User, sdata.user_id)
                if user and user.org_id:
                    return user.org_id, user.id
        except Exception as e:
            logger.debug("Session resolution failed, using fallback: %s", e)

    # In dev/testing, find first org in DB or fallback
    first_org = db.query(Organization).first()
    org_id = first_org.id if first_org else "org_default"
    return org_id, "usr_api_analyst"


@router.post(
    "/graph/run",
    status_code=status.HTTP_200_OK,
    summary="Execute LangGraph multi-agent pipeline",
    description="Executes the full RiskWise LangGraph multi-agent pipeline end-to-end.",
)
def run_agent_graph(
    payload: GraphRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    uow: UnitOfWork = Depends(get_uow),
) -> Dict[str, Any]:
    default_org, default_actor = resolve_calling_context(request, db)
    org_id = payload.organization_id or default_org
    actor_id = payload.actor_id or default_actor
    run_id = f"run_rw_api_{uuid.uuid4().hex[:12]}"
    correlation_id = f"corr_rw_{uuid.uuid4().hex[:12]}"
    trace_id = f"trace_rw_{uuid.uuid4().hex[:12]}"

    initial_state: Dict[str, Any] = {
        "run_id": run_id,
        "organization_id": org_id,
        "actor_id": actor_id,
        "request_id": f"req_rw_{uuid.uuid4().hex[:12]}",
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "objective": payload.objective,
        "input_reference": payload.input_reference,
        "input_references": payload.input_references or {},
        "status": AgentLifecycleStatus.INITIALIZING.value,
        "current_stage": AgentStage.INITIALIZATION.value,
        "step_count": 0,
        "enable_action": payload.enable_action,
        "enable_verification": payload.enable_verification,
        "action_mode": payload.action_mode,
    }
    if payload.requires_human_approval is not None:
        initial_state["requires_human_approval"] = payload.requires_human_approval

    thread_id = payload.thread_id or run_id
    config = {"configurable": {"thread_id": thread_id}}

    t0 = time.perf_counter()
    try:
        builder = AgentGraphBuilder()
        compiled_app = builder.build(validate_graph=False)
        final_state = compiled_app.invoke(initial_state, config=config)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "execution_id": final_state.get("run_id"),
            "status": final_state.get("status"),
            "stage": final_state.get("current_stage"),
            "current_node": final_state.get("current_node"),
            "duration_ms": round(duration_ms, 2),
            "step_count": final_state.get("step_count", 0),
            "route_history": final_state.get("route_history", []),
            "research_findings_count": len(final_state.get("research_findings", []) or []),
            "risk_score": final_state.get("risk_score"),
            "prediction_status": (final_state.get("prediction_result") or {}).get("status", "NOT_AVAILABLE"),
            "scenario_id": (final_state.get("scenario_result") or {}).get("scenario_id"),
            "decision_id": (final_state.get("decision_result") or {}).get("decision_id"),
            "requires_human_approval": final_state.get("requires_human_approval"),
            "approval_status": final_state.get("approval_status"),
            "action_status": final_state.get("action_status"),
            "verification_status": final_state.get("verification_status"),
            "errors": final_state.get("errors", []),
        }
    except Exception as e:
        logger.error("LangGraph execution failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LangGraph execution error: {str(e)}",
        )


@router.get(
    "/graph/nodes",
    status_code=status.HTTP_200_OK,
    summary="List registered LangGraph agent nodes",
)
def list_graph_nodes() -> Dict[str, Any]:
    builder = AgentGraphBuilder()
    nodes = [
        {
            "node_id": n.node_id,
            "stage": n.stage.value,
            "is_side_effecting": n.is_side_effecting,
            "timeout_seconds": n.timeout_seconds,
            "retry_max_attempts": n.max_retries,
        }
        for n in sorted(builder.registry.list_nodes(), key=lambda x: x.node_id)
    ]
    return {"total": len(nodes), "nodes": nodes}


@router.get(
    "/graph/edges",
    status_code=status.HTTP_200_OK,
    summary="List registered LangGraph agent edges",
)
def list_graph_edges() -> Dict[str, Any]:
    builder = AgentGraphBuilder()
    edges = [
        {
            "edge_id": e.edge_id,
            "from_node": e.from_node,
            "to_node": e.to_node,
            "edge_type": e.edge_type.value,
        }
        for e in sorted(builder.edge_registry.list_edges(), key=lambda x: x.edge_id)
    ]
    return {"total": len(edges), "edges": edges}


@router.post(
    "/graph/approve",
    status_code=status.HTTP_200_OK,
    summary="Resume LangGraph execution after human authorization",
    description="Resumes execution from the approval boundary with an approval or rejection decision.",
)
def approve_agent_graph(
    payload: GraphApproveRequest,
    request: Request,
    db: Session = Depends(get_db),
    uow: UnitOfWork = Depends(get_uow),
) -> Dict[str, Any]:
    from datetime import datetime, timezone
    from app.agents.approval.node import human_approval_node
    from app.agents.action.node import action_node
    from app.agents.verification.node import verification_node
    from app.agents.nodes import termination_node

    default_org, default_actor = resolve_calling_context(request, db)
    actor_id = default_actor

    dec_id = (
        payload.decision_id
        or (payload.decision_result.get("decision_id") if payload.decision_result else None)
        or f"dec_{uuid.uuid4().hex[:12]}"
    )
    dec_result = payload.decision_result or {
        "decision_id": dec_id,
        "decision_type": "SHIPMENT_REROUTE",
        "organization_id": default_org,
        "requires_human_approval": True,
        "preferred_candidate": {
            "candidate_id": "cand_approved_corridor",
            "action_type": "SHIPMENT_REROUTE",
            "target_entity_type": "SHIPMENT",
            "target_entity_id": "ship_test_rw_01",
            "requires_human_approval": True,
            "parameters": {"new_route_id": "route_alt_corridor"},
        },
    }

    resumed_state: Dict[str, Any] = {
        "run_id": payload.run_id,
        "organization_id": default_org,
        "actor_id": actor_id,
        "decision_id": dec_id,
        "decision_result": dec_result,
        "human_approval_decision": {
            "decision": payload.decision.upper(),
            "actor": {
                "actor_id": actor_id,
                "role": "RiskManager",
                "organization_id": default_org,
            },
            "comments": payload.comments or "Authorization decision submitted via API.",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
        "enable_action": payload.enable_action and (payload.decision.upper() == "APPROVE"),
        "enable_verification": payload.enable_verification,
        "action_mode": "SIMULATED",
        "current_node": "human_approval",
        "current_stage": AgentStage.APPROVAL.value,
        "step_count": 8,
    }

    t0 = time.perf_counter()
    try:
        # Step 1: Human Approval Node
        appr_update = human_approval_node(resumed_state)
        resumed_state.update(appr_update)

        # Step 2: Action Node (if approved and action enabled)
        if resumed_state.get("enable_action") and resumed_state.get("approval_status") == "APPROVED":
            resumed_state["current_node"] = "action_agent"
            resumed_state["current_stage"] = AgentStage.ACTION.value
            action_update = action_node(resumed_state, uow=uow)
            resumed_state.update(action_update)

            # Step 3: Verification Node
            if resumed_state.get("enable_verification"):
                resumed_state["current_node"] = "verification_agent"
                resumed_state["current_stage"] = AgentStage.VERIFICATION.value
                verif_update = verification_node(resumed_state, uow=uow)
                resumed_state.update(verif_update)

        # Step 4: Termination
        resumed_state["current_node"] = "termination"
        resumed_state["current_stage"] = AgentStage.TERMINATION.value
        term_update = termination_node(resumed_state)
        resumed_state.update(term_update)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "execution_id": resumed_state.get("run_id"),
            "status": resumed_state.get("status"),
            "stage": resumed_state.get("current_stage"),
            "current_node": resumed_state.get("current_node"),
            "approval_status": resumed_state.get("approval_status"),
            "action_status": resumed_state.get("action_status"),
            "verification_status": resumed_state.get("verification_status"),
            "duration_ms": round(duration_ms, 2),
            "step_count": resumed_state.get("step_count"),
            "errors": resumed_state.get("errors", []),
        }
    except Exception as e:
        logger.error("Human approval resume failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Human approval resume error: {str(e)}",
        )

