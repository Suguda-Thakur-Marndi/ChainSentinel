"""FastAPI endpoints for RiskWise Simulation Engine (Phase 13).

Provides typed REST APIs for scenario creation, what-if execution,
result retrieval, and scenario comparison.
"""
from __future__ import annotations

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.simulation.contracts import (
    SimulationComparison,
    SimulationInput,
    SimulationResult,
    SimulationScenario,
)
from app.simulation.errors import (
    SimulationError,
    SimulationResourceLimitError,
    SimulationTenantIsolationError,
    SimulationValidationError,
)
from app.simulation.service import SimulationService

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")


class ScenarioCompareRequest(BaseModel):
    """Payload for comparing two scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenario_a_id: str = Field(..., min_length=1, max_length=64)
    scenario_b_id: str = Field(..., min_length=1, max_length=64)


@router.post(
    "/scenarios",
    response_model=SimulationScenario,
    status_code=status.HTTP_201_CREATED,
    summary="Create what-if scenario",
    description="Register a new what-if scenario definition against a Digital Twin snapshot.",
)
def create_scenario(
    scenario: SimulationScenario,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> SimulationScenario:
    """Create a new scenario definition."""
    try:
        saved = SimulationService.create_scenario(
            db=uow.session,
            organization_id=context.organization_id,
            scenario=scenario,
            user_id=context.user_id,
        )
        uow.commit()
        return saved
    except SimulationTenantIsolationError:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Scenario organization mismatch",
        )
    except SimulationValidationError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )


@router.get(
    "/scenarios",
    response_model=List[SimulationScenario],
    status_code=status.HTTP_200_OK,
    summary="List what-if scenarios",
    description="List all what-if scenarios configured for the authenticated tenant.",
)
def list_scenarios(
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> List[SimulationScenario]:
    """List scenarios belonging to the tenant."""
    return SimulationService.list_scenarios(
        db=db, organization_id=context.organization_id
    )


@router.get(
    "/scenarios/{scenario_id}",
    response_model=SimulationScenario,
    status_code=status.HTTP_200_OK,
    summary="Get scenario by ID",
    description="Retrieve scenario definition and configured changes by ID.",
)
def get_scenario(
    scenario_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> SimulationScenario:
    """Retrieve single scenario by ID."""
    try:
        scenario = SimulationService.get_scenario(
            db=db, organization_id=context.organization_id, scenario_id=scenario_id
        )
    except SimulationTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Scenario belongs to another tenant",
        )

    if not scenario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_id}' not found",
        )
    return scenario


@router.post(
    "/scenarios/{scenario_id}/simulate",
    response_model=SimulationResult,
    status_code=status.HTTP_200_OK,
    summary="Run what-if scenario simulation",
    description="Execute deterministic what-if simulation for the specified scenario against the active Digital Twin.",
)
def run_simulation(
    scenario_id: str,
    sim_input: Optional[SimulationInput] = None,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> SimulationResult:
    """Execute what-if simulation and persist results."""
    try:
        result = SimulationService.run_simulation(
            db=uow.session,
            organization_id=context.organization_id,
            scenario_id=scenario_id,
            sim_input=sim_input,
            request_id=getattr(context, "request_id", None),
        )
        uow.commit()
        return result
    except SimulationTenantIsolationError:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Multi-tenant boundary violation",
        )
    except SimulationValidationError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except SimulationResourceLimitError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(e),
        )
    except Exception as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation execution failed: {str(e)}",
        )


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationResult,
    status_code=status.HTTP_200_OK,
    summary="Get simulation run result",
    description="Retrieve historical simulation result, including effects, metrics, and provenance.",
)
def get_simulation_result(
    simulation_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> SimulationResult:
    """Retrieve executed simulation run outcome."""
    try:
        result = SimulationService.get_simulation_result(
            db=db, organization_id=context.organization_id, simulation_id=simulation_id
        )
    except SimulationTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Simulation result belongs to another tenant",
        )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation result '{simulation_id}' not found",
        )
    return result


@router.post(
    "/simulations/compare",
    response_model=SimulationComparison,
    status_code=status.HTTP_200_OK,
    summary="Compare two scenario outcomes",
    description="Deterministically compare metrics and delay impacts between two scenarios.",
)
def compare_scenarios(
    payload: ScenarioCompareRequest,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> SimulationComparison:
    """Compare two scenario outcomes."""
    try:
        return SimulationService.compare_scenarios(
            db=db,
            organization_id=context.organization_id,
            scenario_a_id=payload.scenario_a_id,
            scenario_b_id=payload.scenario_b_id,
        )
    except SimulationTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Scenario belongs to another organization",
        )
    except SimulationValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
