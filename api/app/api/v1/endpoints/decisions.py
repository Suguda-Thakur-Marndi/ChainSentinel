"""FastAPI endpoints for RiskWise Decision Agent (Phase 15).

Provides authenticated REST APIs for:
- Formulating deterministic decision recommendations (POST /api/v1/decisions)
- Listing historical decision results for authenticated tenant (GET /api/v1/decisions)
- Retrieving specific decision result by ID (GET /api/v1/decisions/{decision_id})

Enforces:
- RBAC: generation requires Analyst, OpsManager, RiskManager, or Admin role; Viewers are read-only
- Strict multi-tenant isolation on all queries and operations
- Transactional persistence via UnitOfWork
- Fail-closed error handling
"""

from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agents.decision.agent import DecisionAgent
from app.agents.decision.contract import DecisionRequest, DecisionResult
from app.agents.decision.errors import (
    DecisionAgentError,
    DecisionFreshnessError,
    DecisionInfeasibleError,
    DecisionInputValidationError,
    DecisionPolicyError,
    DecisionTenantIsolationError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
)
from app.agents.decision.persistence import DecisionRepository
from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow

logger = logging.getLogger("riskwise.api.decisions")

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")


@router.post(
    "/decisions",
    response_model=DecisionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Formulate decision recommendation",
    description=(
        "Synthesize authoritative risk, prediction, scenario, and optimization results "
        "to formulate a deterministic decision recommendation. Does NOT execute or approve action."
    ),
)
def create_decision(
    request: DecisionRequest,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> DecisionResult:
    """Execute deterministic Decision Agent policy and persist recommendation."""
    # Enforce request tenant matches authenticated context
    if request.organization_id != context.organization_id:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Tenant violation: request organization '{request.organization_id}' "
                f"does not match authenticated context '{context.organization_id}'."
            ),
        )

    try:
        agent = DecisionAgent()
        result, findings = agent.execute(request)

        # Persist decision to recommendations table
        DecisionRepository.save_decision(
            db=uow.session,
            result=result,
            request_id=getattr(context, "request_id", None),
            actor_id=context.user_id,
        )
        uow.commit()
        return result

    except DecisionTenantIsolationError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except (InvalidDecisionRequestError, DecisionInputValidationError) as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except (InvalidDecisionCandidateError, DecisionFreshnessError) as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        uow.rollback()
        raise
    except Exception as e:
        uow.rollback()
        logger.exception("Decision formulation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Decision formulation failed: {str(e)}",
        )


@router.get(
    "/decisions",
    response_model=List[DecisionResult],
    status_code=status.HTTP_200_OK,
    summary="List decision recommendations",
    description="List historical decision recommendations formulated for the authenticated tenant.",
)
def list_decisions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> List[DecisionResult]:
    """List decision recommendations belonging to the authenticated tenant."""
    org_id = context.organization_id or ""
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization context required",
        )
    try:
        records = DecisionRepository.list_by_organization(
            db=db,
            organization_id=org_id,
            limit=limit,
            offset=offset,
        )
        results: List[DecisionResult] = []
        for rec in records:
            if rec.expected_benefit_json and isinstance(rec.expected_benefit_json, dict):
                try:
                    res = DecisionResult.model_validate(rec.expected_benefit_json)
                    results.append(res)
                except Exception as parse_err:
                    logger.warning("Could not deserialize decision record '%s': %s", rec.id, parse_err)
        return results
    except DecisionTenantIsolationError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except Exception as e:
        logger.exception("Failed to list decisions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list decisions: {str(e)}",
        )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionResult,
    status_code=status.HTTP_200_OK,
    summary="Get decision recommendation by ID",
    description="Retrieve specific decision recommendation result by ID enforcing tenant isolation.",
)
def get_decision(
    decision_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> DecisionResult:
    """Retrieve a decision recommendation by ID."""
    org_id = context.organization_id or ""
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization context required",
        )
    try:
        rec = DecisionRepository.get_by_id(
            db=db,
            organization_id=org_id,
            decision_id=decision_id,
        )
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision '{decision_id}' not found.",
            )

        if not rec.expected_benefit_json or not isinstance(rec.expected_benefit_json, dict):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision payload for '{decision_id}' is empty or corrupt.",
            )

        return DecisionResult.model_validate(rec.expected_benefit_json)

    except DecisionTenantIsolationError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get decision '%s': %s", decision_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get decision: {str(e)}",
        )
