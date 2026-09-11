"""Digital Twin API endpoints for RiskWise 2.0 (Phase 12).

Provides deterministic, read-only operational network topology queries,
snapshot retrieval, and authorized graph rebuild triggers.
"""
from __future__ import annotations

from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow
from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
    TwinPathResult,
    TwinQuery,
    TwinSubgraph,
)
from app.digital_twin.errors import (
    TwinQueryError,
    TwinTenantIsolationError,
    TwinValidationError,
)
from app.digital_twin.service import DigitalTwinService
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("OpsManager", "RiskManager", "Admin")


class DigitalTwinSummaryResponse(BaseModel):
    """Concise operational summary of the active Digital Twin topology."""

    model_config = ConfigDict(extra="forbid")

    twin_id: str
    organization_id: str
    version: str
    node_count: int
    edge_count: int
    source_fingerprint: str
    twin_fingerprint: str
    generated_at: str
    status: str


class DigitalTwinPathRequest(BaseModel):
    """Request payload for deterministic BFS path reachability search."""

    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(..., min_length=1, max_length=64)
    target_node_id: str = Field(..., min_length=1, max_length=64)
    max_depth: int = Field(default=5, ge=1, le=10)


@router.get(
    "/current",
    response_model=DigitalTwinSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current Digital Twin overview",
    description="Retrieve high-level summary metrics and fingerprints for the tenant's current Digital Twin.",
)
def get_current_twin(
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> DigitalTwinSummaryResponse:
    """Return concise overview of the tenant's active digital twin."""
    snapshot = DigitalTwinService.retrieve_current_twin(
        db=db, organization_id=context.organization_id
    )
    return DigitalTwinSummaryResponse(
        twin_id=snapshot.twin_id,
        organization_id=snapshot.organization_id,
        version=snapshot.version,
        node_count=snapshot.node_count,
        edge_count=snapshot.edge_count,
        source_fingerprint=snapshot.source_fingerprint,
        twin_fingerprint=snapshot.twin_fingerprint,
        generated_at=snapshot.generated_at.isoformat(),
        status=snapshot.status,
    )


@router.get(
    "/snapshot",
    response_model=DigitalTwinSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Get complete Digital Twin snapshot",
    description="Retrieve the full immutable graph snapshot including all nodes, edges, and cryptographic fingerprints.",
)
def get_full_snapshot(
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> DigitalTwinSnapshot:
    """Return the complete active DigitalTwinSnapshot."""
    return DigitalTwinService.retrieve_current_twin(
        db=db, organization_id=context.organization_id
    )


@router.get(
    "/nodes",
    response_model=List[TwinNodeContract],
    status_code=status.HTTP_200_OK,
    summary="List Digital Twin nodes",
    description="Retrieve all operational nodes in the Digital Twin, with optional node_type filtering.",
)
def list_nodes(
    node_type: Optional[TwinNodeType] = Query(None, description="Filter nodes by type (e.g. SUPPLIER, FACTORY, PORT)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> List[TwinNodeContract]:
    """List twin nodes with optional node_type filtering."""
    return DigitalTwinService.retrieve_nodes(
        db=db, organization_id=context.organization_id, node_type=node_type
    )


@router.get(
    "/nodes/{node_id}",
    response_model=TwinNodeContract,
    status_code=status.HTTP_200_OK,
    summary="Get Digital Twin node by ID",
    description="Retrieve a single twin node by its deterministic UUIDv5 identifier.",
)
def get_node_by_id(
    node_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> TwinNodeContract:
    """Fetch single node by deterministic node_id."""
    query_svc = DigitalTwinService.get_query_service(
        db=db, organization_id=context.organization_id
    )
    try:
        return query_svc.get_node(node_id)
    except TwinTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Node belongs to a different tenant",
        )
    except TwinQueryError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found in Digital Twin",
        )


@router.get(
    "/edges",
    response_model=List[TwinEdgeContract],
    status_code=status.HTTP_200_OK,
    summary="List Digital Twin edges",
    description="Retrieve all operational relationship edges in the Digital Twin, with optional edge_type filtering.",
)
def list_edges(
    edge_type: Optional[TwinEdgeType] = Query(None, description="Filter edges by type (e.g. FLOW, TRANSPORT, DEPENDENCY)"),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> List[TwinEdgeContract]:
    """List twin edges with optional edge_type filtering."""
    return DigitalTwinService.retrieve_edges(
        db=db, organization_id=context.organization_id, edge_type=edge_type
    )


@router.post(
    "/refresh",
    response_model=DigitalTwinSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Rebuild and refresh Digital Twin",
    description="Re-read authoritative database state, synthesize a refreshed topology graph, validate invariants, and persist.",
)
def refresh_twin(
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> DigitalTwinSnapshot:
    """Trigger an authorized Digital Twin rebuild and persistence."""
    try:
        snapshot = DigitalTwinService.refresh_current_twin(
            db=uow.session,
            organization_id=context.organization_id,
            request_id=getattr(context, "request_id", None),
            uow=uow,
        )
        uow.commit()
        return snapshot
    except TwinValidationError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Graph validation failed during refresh: {str(e)}",
        )
    except Exception as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Digital Twin refresh failed: {str(e)}",
        )


@router.post(
    "/query",
    status_code=status.HTTP_200_OK,
    summary="Execute bounded graph query",
    description="Execute a bounded subgraph traversal or filtered node search against the tenant's Digital Twin.",
)
def query_graph(
    query: TwinQuery,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> Any:
    """Execute bounded query against active Digital Twin."""
    try:
        return DigitalTwinService.query_graph(
            db=db, organization_id=context.organization_id, query=query
        )
    except TwinTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Query targets a different tenant",
        )
    except TwinQueryError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/path",
    response_model=TwinPathResult,
    status_code=status.HTTP_200_OK,
    summary="Find deterministic path",
    description="Perform deterministic BFS reachability search between two nodes within the tenant's network.",
)
def find_path(
    payload: DigitalTwinPathRequest,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> TwinPathResult:
    """Find deterministic reachability path between two nodes."""
    query_svc = DigitalTwinService.get_query_service(
        db=db, organization_id=context.organization_id
    )
    try:
        return query_svc.find_path(
            source_node_id=payload.source_node_id,
            target_node_id=payload.target_node_id,
            max_depth=payload.max_depth,
            request_id=getattr(context, "request_id", None),
        )
    except TwinTenantIsolationError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Path endpoints belong to a different tenant",
        )
    except TwinQueryError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
