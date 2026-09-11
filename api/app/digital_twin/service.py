"""Unified domain service coordinating RiskWise Digital Twin operations.

Encapsulates:
- Full build and atomic persistence workflow (Builder -> Validator -> Repository).
- Reading authoritative Digital Twin snapshots.
- Instantiating bounded, read-only DigitalTwinQueryService instances.
"""

from __future__ import annotations

from typing import Any, Optional
from sqlalchemy.orm import Session

from app.digital_twin.builder import DigitalTwinBuilder
from app.digital_twin.contracts import DigitalTwinSnapshot
from app.digital_twin.query import DigitalTwinQueryService
from app.digital_twin.repository import DigitalTwinRepository


class DigitalTwinService:
    """Domain service coordinating Digital Twin generation, persistence, and queries."""

    @classmethod
    def build_and_persist(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
        version: str = "1",
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> DigitalTwinSnapshot:
        """Execute full build workflow: read authoritative state, validate graph, and persist atomically."""
        builder = DigitalTwinBuilder(
            organization_id=organization_id, twin_id=twin_id, version=version
        )
        snapshot = builder.build_from_database(
            db=db,
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )
        DigitalTwinRepository.persist_snapshot(db=db, snapshot=snapshot)
        return snapshot

    @classmethod
    def get_twin_snapshot(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
    ) -> Optional[DigitalTwinSnapshot]:
        """Fetch current persisted Digital Twin snapshot for a tenant."""
        return DigitalTwinRepository.load_snapshot(
            db=db, organization_id=organization_id, twin_id=twin_id
        )

    @classmethod
    def get_query_service(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
    ) -> DigitalTwinQueryService:
        """Load persisted snapshot and return an initialized, read-only query service."""
        snapshot = cls.get_twin_snapshot(db=db, organization_id=organization_id, twin_id=twin_id)
        if not snapshot:
            # If no snapshot has been persisted yet, build an initial snapshot on-the-fly
            snapshot = cls.build_and_persist(
                db=db, organization_id=organization_id, twin_id=twin_id
            )
        return DigitalTwinQueryService(snapshot)

    @classmethod
    def build_current_twin(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
        version: str = "1",
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> DigitalTwinSnapshot:
        """Build and persist current Digital Twin snapshot for tenant."""
        return cls.build_and_persist(
            db=db,
            organization_id=organization_id,
            twin_id=twin_id,
            version=version,
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )

    @classmethod
    def refresh_current_twin(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
        version: str = "1",
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> DigitalTwinSnapshot:
        """Re-read authoritative database state and refresh Digital Twin representation."""
        return cls.build_and_persist(
            db=db,
            organization_id=organization_id,
            twin_id=twin_id,
            version=version,
            correlation_id=correlation_id,
            request_id=request_id,
            uow=uow,
        )

    @classmethod
    def retrieve_current_twin(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
    ) -> DigitalTwinSnapshot:
        """Retrieve current Digital Twin snapshot, synthesizing one if not yet persisted."""
        snapshot = cls.get_twin_snapshot(db=db, organization_id=organization_id, twin_id=twin_id)
        if not snapshot:
            snapshot = cls.build_and_persist(db=db, organization_id=organization_id, twin_id=twin_id)
        return snapshot

    @classmethod
    def retrieve_snapshot(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
    ) -> Optional[DigitalTwinSnapshot]:
        """Retrieve persisted snapshot for tenant."""
        return cls.get_twin_snapshot(db=db, organization_id=organization_id, twin_id=twin_id)

    @classmethod
    def retrieve_nodes(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
        node_type: Optional[Any] = None,
    ) -> list[Any]:
        """Retrieve twin nodes with optional node_type filtering."""
        snapshot = cls.retrieve_current_twin(db=db, organization_id=organization_id, twin_id=twin_id)
        nodes = list(snapshot.nodes.values())
        if node_type:
            nodes = [n for n in nodes if n.node_type == node_type]
        return nodes

    @classmethod
    def retrieve_edges(
        cls,
        db: Session,
        organization_id: str,
        twin_id: Optional[str] = None,
        edge_type: Optional[Any] = None,
    ) -> list[Any]:
        """Retrieve twin edges with optional edge_type filtering."""
        snapshot = cls.retrieve_current_twin(db=db, organization_id=organization_id, twin_id=twin_id)
        edges = list(snapshot.edges.values())
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    @classmethod
    def query_graph(
        cls,
        db: Session,
        organization_id: str,
        query: Any,
        twin_id: Optional[str] = None,
    ) -> Any:
        """Execute bounded query against current twin graph."""
        query_service = cls.get_query_service(db=db, organization_id=organization_id, twin_id=twin_id)
        return query_service.query(query)

