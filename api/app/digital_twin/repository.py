"""Transactional persistence repository for RiskWise Digital Twin.

Reuses existing twin_nodes and twin_edges database tables without schema modifications.
Guarantees:
- Strict tenant isolation for all reads and writes.
- Atomic, transactional persistence with full rollback on validation or database error.
- Idempotent graph persistence without dangling foreign keys or duplicate identities.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
)
from app.digital_twin.errors import TwinPersistenceError, TwinTenantIsolationError
from app.digital_twin.fingerprints import compute_twin_fingerprint
from app.digital_twin.validator import TwinGraphValidator
from app.models.digital_twin import TwinEdge, TwinNode
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


class DigitalTwinRepository:
    """Repository handling transactional database persistence and retrieval of twin graphs."""

    @staticmethod
    def persist_snapshot(db: Session, snapshot: DigitalTwinSnapshot) -> None:
        """Atomically persist a validated Digital Twin snapshot into twin_nodes and twin_edges.

        Guarantees:
        - If any constraint or operation fails, the entire transaction rolls back.
        - Previous state for the organization is replaced cleanly without orphaned edges.
        - Foreign key order is preserved: nodes inserted before edges; edges deleted before nodes.
        """
        # Validate snapshot invariants before touching database
        val_result = TwinGraphValidator.validate_snapshot(snapshot)
        if not val_result.is_valid:
            raise TwinPersistenceError(
                f"Cannot persist invalid snapshot: {'; '.join(val_result.errors)}"
            )

        org_id = snapshot.organization_id

        try:
            # 1. Remove existing edges for this tenant first to satisfy foreign key dependencies
            db.query(TwinEdge).filter(TwinEdge.org_id == org_id).delete(synchronize_session=False)

            # 2. Remove existing nodes for this tenant
            db.query(TwinNode).filter(TwinNode.org_id == org_id).delete(synchronize_session=False)

            # 3. Insert all twin nodes
            db_nodes: List[TwinNode] = []
            for node in snapshot.nodes.values():
                if node.organization_id != org_id:
                    raise TwinTenantIsolationError(
                        f"Cross-tenant node persistence attempt: {node.organization_id} != {org_id}"
                    )

                props = dict(node.properties)
                props["_source_entity_type"] = node.source_entity_type
                props["_fingerprint"] = node.fingerprint
                props["_status"] = node.status
                if node.source_timestamp:
                    props["_source_timestamp"] = node.source_timestamp.isoformat()

                db_node = TwinNode(
                    id=node.node_id,
                    org_id=org_id,
                    node_type=node.node_type.value,
                    entity_id=node.source_entity_id,
                    label=node.label,
                    latitude=node.latitude,
                    longitude=node.longitude,
                    health_score=node.health_score,
                    properties_json=props,
                )
                db_nodes.append(db_node)

            db.add_all(db_nodes)
            db.flush()  # Ensure nodes are flushed so foreign keys resolve

            # 4. Insert all twin edges
            db_edges: List[TwinEdge] = []
            for edge in snapshot.edges.values():
                if edge.organization_id != org_id:
                    raise TwinTenantIsolationError(
                        f"Cross-tenant edge persistence attempt: {edge.organization_id} != {org_id}"
                    )

                edge_props = dict(edge.properties)
                edge_props["_fingerprint"] = edge.fingerprint
                edge_props["_status"] = edge.status
                if edge.source_reference:
                    edge_props["_source_reference"] = edge.source_reference

                db_edge = TwinEdge(
                    id=edge.edge_id,
                    org_id=org_id,
                    from_node_id=edge.from_node_id,
                    to_node_id=edge.to_node_id,
                    edge_type=edge.edge_type.value,
                    flow_capacity=edge.flow_capacity,
                    current_flow=edge.current_flow,
                    risk_score=edge.risk_score,
                    properties_json=edge_props,
                )
                db_edges.append(db_edge)

            db.add_all(db_edges)
            db.commit()

        except Exception as e:
            db.rollback()
            raise TwinPersistenceError(f"Failed to persist digital twin snapshot: {str(e)}") from e

    @staticmethod
    def load_snapshot(
        db: Session, organization_id: str, twin_id: Optional[str] = None
    ) -> Optional[DigitalTwinSnapshot]:
        """Load the current persisted Digital Twin snapshot for a specific tenant."""
        if not organization_id:
            raise TwinTenantIsolationError("organization_id is required to load snapshot")

        db_nodes = db.query(TwinNode).filter(TwinNode.org_id == organization_id).all()
        if not db_nodes:
            return None

        db_edges = db.query(TwinEdge).filter(TwinEdge.org_id == organization_id).all()

        nodes: Dict[str, TwinNodeContract] = {}
        for dn in db_nodes:
            props = dict(dn.properties_json or {})
            source_entity_type = props.pop("_source_entity_type", dn.node_type)
            fingerprint = props.pop("_fingerprint", "")
            status = props.pop("_status", None)
            source_ts_str = props.pop("_source_timestamp", None)
            source_ts = (
                datetime.datetime.fromisoformat(source_ts_str) if source_ts_str else None
            )

            # Reconstruct node type safely
            try:
                node_type = TwinNodeType(dn.node_type)
            except ValueError:
                node_type = TwinNodeType.CUSTOM

            node = TwinNodeContract(
                node_id=dn.id,
                organization_id=dn.org_id or organization_id,
                node_type=node_type,
                source_entity_type=source_entity_type,
                source_entity_id=dn.entity_id or dn.id,
                label=dn.label,
                latitude=dn.latitude,
                longitude=dn.longitude,
                health_score=dn.health_score,
                status=status,
                properties=props,
                source_timestamp=source_ts,
                fingerprint=fingerprint or "0" * 64,
            )
            nodes[node.node_id] = node

        edges: Dict[str, TwinEdgeContract] = {}
        for de in db_edges:
            edge_props = dict(de.properties_json or {})
            fingerprint = edge_props.pop("_fingerprint", "")
            status = edge_props.pop("_status", None)
            source_ref = edge_props.pop("_source_reference", None)

            try:
                edge_type = TwinEdgeType(de.edge_type)
            except ValueError:
                edge_type = TwinEdgeType.FLOW

            edge = TwinEdgeContract(
                edge_id=de.id,
                organization_id=de.org_id or organization_id,
                from_node_id=de.from_node_id,
                to_node_id=de.to_node_id,
                edge_type=edge_type,
                status=status,
                flow_capacity=de.flow_capacity,
                current_flow=de.current_flow,
                risk_score=de.risk_score,
                properties=edge_props,
                source_reference=source_ref,
                fingerprint=fingerprint or "0" * 64,
            )
            edges[edge.edge_id] = edge

        node_fps = [n.fingerprint for n in nodes.values()]
        edge_fps = [e.fingerprint for e in edges.values()]
        effective_twin_id = twin_id or f"twin-{organization_id}"
        twin_fp = compute_twin_fingerprint(
            twin_id=effective_twin_id,
            organization_id=organization_id,
            version="1",
            node_fingerprints=node_fps,
            edge_fingerprints=edge_fps,
        )

        return DigitalTwinSnapshot(
            twin_id=effective_twin_id,
            organization_id=organization_id,
            version="1",
            node_count=len(nodes),
            edge_count=len(edges),
            nodes=nodes,
            edges=edges,
            source_fingerprint=twin_fp,
            twin_fingerprint=twin_fp,
            generated_at=datetime.datetime.now(datetime.timezone.utc),
            status="CURRENT",
        )
