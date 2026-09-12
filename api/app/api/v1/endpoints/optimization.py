"""FastAPI endpoints for RiskWise Optimization Subsystem (Phase 14).

Provides authenticated REST APIs for:
- Triggering deterministic mathematical optimization runs via Google OR-Tools
- Listing historical optimization runs for tenant
- Retrieving specific optimization run results
"""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.optimization.contracts import (
    OptimizationRequest,
    OptimizationResult,
    OptimizationStatus,
)
from app.optimization.errors import (
    OptimizationDataMissingError,
    OptimizationError,
    OptimizationResourceLimitError,
    OptimizationTenantIsolationError,
    OptimizationValidationError,
)
from app.optimization.service import OptimizationService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")


@router.post(
    "/optimization-runs",
    response_model=OptimizationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger mathematical optimization run",
    description="Execute deterministic mathematical optimization using Google OR-Tools under authoritative constraints.",
)
def create_optimization_run(
    request: OptimizationRequest,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> OptimizationResult:
    """Execute mathematical optimization run and persist results."""
    try:
        result = OptimizationService.run_optimization(
            db=uow.session,
            request=request,
            expected_organization_id=context.organization_id,
        )
        uow.commit()
        return result
    except OptimizationTenantIsolationError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except (OptimizationValidationError, OptimizationDataMissingError) as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except OptimizationResourceLimitError as e:
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Optimization execution failed: {str(e)}",
        )


@router.get(
    "/optimization-runs",
    response_model=List[OptimizationResult],
    status_code=status.HTTP_200_OK,
    summary="List optimization runs",
    description="List historical optimization runs for the authenticated tenant.",
)
def list_optimization_runs(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> List[OptimizationResult]:
    """List optimization runs belonging to the tenant."""
    org_id = context.organization_id or ""
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization context required",
        )
    return OptimizationService.list_optimization_runs(
        db=db,
        organization_id=org_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/optimization-runs/{optimization_id}",
    response_model=OptimizationResult,
    status_code=status.HTTP_200_OK,
    summary="Get optimization run result",
    description="Retrieve a specific optimization run result by ID, including variables, selected alternatives, and metrics.",
)
def get_optimization_run(
    optimization_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> OptimizationResult:
    """Retrieve optimization run result by ID."""
    org_id = context.organization_id or ""
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization context required",
        )
    try:
        result = OptimizationService.get_optimization_result(
            db=db,
            organization_id=org_id,
            optimization_id=optimization_id,
        )
    except OptimizationTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Optimization run belongs to another tenant",
        )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization run '{optimization_id}' not found",
        )
    return result
