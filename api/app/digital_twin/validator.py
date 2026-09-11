"""Graph validation engine for RiskWise Digital Twin.

Enforces:
- Structural reference integrity (no orphan edges, all endpoints exist in node set).
- Strict multi-tenant boundaries (cross-tenant edges and nodes are rejected).
- Attribute range validity (coordinates, health/risk scores, capacities).
- Cryptographic fingerprint and snapshot consistency.
- Detection of duplicate identities and reference errors.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Union

from app.digital_twin.contracts import (
    DigitalTwinSnapshot,
    TwinEdgeContract,
    TwinNodeContract,
    TwinValidationResult,
)
from app.digital_twin.errors import (
    TwinFingerprintError,
    TwinReferenceError,
    TwinTenantIsolationError,
    TwinValidationError,
)
from app.digital_twin.fingerprints import (
    compute_edge_fingerprint,
    compute_node_fingerprint,
    compute_twin_fingerprint,
)
from app.schemas.digital_twin import TwinEdgeType, TwinNodeType


class TwinGraphValidator:
    """Deterministic validation service for Digital Twin graph structures."""

    @classmethod
    def validate_node(
        cls,
        node: TwinNodeContract,
        expected_org_id: Optional[str] = None,
        verify_fingerprint: bool = True,
    ) -> List[str]:
        """Validate an individual twin node's invariants and attributes."""
        errors: List[str] = []

        # Tenant boundary check
        if expected_org_id and node.organization_id != expected_org_id:
            errors.append(
                f"Node '{node.node_id}' tenant mismatch: expected '{expected_org_id}', got '{node.organization_id}'"
            )

        # Node type check
        if not isinstance(node.node_type, TwinNodeType):
            errors.append(f"Node '{node.node_id}' has invalid node_type: {node.node_type}")

        # Coordinate bounds
        if node.latitude is not None and not (-90.0 <= node.latitude <= 90.0):
            errors.append(f"Node '{node.node_id}' latitude {node.latitude} out of bounds [-90, 90]")
        if node.longitude is not None and not (-180.0 <= node.longitude <= 180.0):
            errors.append(f"Node '{node.node_id}' longitude {node.longitude} out of bounds [-180, 180]")

        # Health score bounds
        if node.health_score is not None and not (0.0 <= node.health_score <= 100.0):
            errors.append(f"Node '{node.node_id}' health_score {node.health_score} out of bounds [0, 100]")

        # Fingerprint integrity
        if verify_fingerprint:
            computed_fp = compute_node_fingerprint(
                node_id=node.node_id,
                organization_id=node.organization_id,
                node_type=node.node_type.value,
                source_entity_type=node.source_entity_type,
                source_entity_id=node.source_entity_id,
                label=node.label,
                latitude=node.latitude,
                longitude=node.longitude,
                health_score=node.health_score,
                status=node.status,
                properties=node.properties,
            )
            if computed_fp != node.fingerprint:
                errors.append(
                    f"Node '{node.node_id}' fingerprint mismatch: expected '{computed_fp}', got '{node.fingerprint}'"
                )

        return errors

    @classmethod
    def validate_edge(
        cls,
        edge: TwinEdgeContract,
        known_node_ids: Set[str],
        expected_org_id: Optional[str] = None,
        verify_fingerprint: bool = True,
    ) -> List[str]:
        """Validate an individual twin edge's invariants, endpoints, and attributes."""
        errors: List[str] = []

        # Tenant boundary check
        if expected_org_id and edge.organization_id != expected_org_id:
            errors.append(
                f"Edge '{edge.edge_id}' tenant mismatch: expected '{expected_org_id}', got '{edge.organization_id}'"
            )

        # Edge type check
        if not isinstance(edge.edge_type, TwinEdgeType):
            errors.append(f"Edge '{edge.edge_id}' has invalid edge_type: {edge.edge_type}")

        # Endpoint existence checks (no orphan/dangling edges)
        if edge.from_node_id not in known_node_ids:
            errors.append(f"Edge '{edge.edge_id}' source node '{edge.from_node_id}' does not exist in graph")
        if edge.to_node_id not in known_node_ids:
            errors.append(f"Edge '{edge.edge_id}' target node '{edge.to_node_id}' does not exist in graph")

        # Range bounds
        if edge.risk_score is not None and not (0.0 <= edge.risk_score <= 100.0):
            errors.append(f"Edge '{edge.edge_id}' risk_score {edge.risk_score} out of bounds [0, 100]")
        if edge.flow_capacity is not None and edge.flow_capacity < 0.0:
            errors.append(f"Edge '{edge.edge_id}' flow_capacity {edge.flow_capacity} cannot be negative")
        if edge.current_flow is not None and edge.current_flow < 0.0:
            errors.append(f"Edge '{edge.edge_id}' current_flow {edge.current_flow} cannot be negative")

        # Fingerprint integrity
        if verify_fingerprint:
            computed_fp = compute_edge_fingerprint(
                edge_id=edge.edge_id,
                organization_id=edge.organization_id,
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                edge_type=edge.edge_type.value,
                status=edge.status,
                flow_capacity=edge.flow_capacity,
                current_flow=edge.current_flow,
                risk_score=edge.risk_score,
                properties=edge.properties,
                source_reference=edge.source_reference,
            )
            if computed_fp != edge.fingerprint:
                errors.append(
                    f"Edge '{edge.edge_id}' fingerprint mismatch: expected '{computed_fp}', got '{edge.fingerprint}'"
                )

        return errors

    @classmethod
    def validate_graph(
        cls,
        nodes: Union[Dict[str, TwinNodeContract], Sequence[TwinNodeContract]],
        edges: Union[Dict[str, TwinEdgeContract], Sequence[TwinEdgeContract]],
        expected_org_id: str,
        verify_fingerprints: bool = True,
    ) -> TwinValidationResult:
        """Validate full graph consistency, references, duplicates, and tenant containment."""
        errors: List[str] = []
        warnings: List[str] = []

        node_list: List[TwinNodeContract] = list(nodes.values()) if isinstance(nodes, dict) else list(nodes)
        edge_list: List[TwinEdgeContract] = list(edges.values()) if isinstance(edges, dict) else list(edges)

        # 1. Node uniqueness and validation
        seen_node_ids: Set[str] = set()
        for node in node_list:
            if node.node_id in seen_node_ids:
                errors.append(f"Duplicate node ID detected: '{node.node_id}'")
            seen_node_ids.add(node.node_id)

            node_errors = cls.validate_node(
                node, expected_org_id=expected_org_id, verify_fingerprint=verify_fingerprints
            )
            errors.extend(node_errors)

        # 2. Edge uniqueness and reference validation
        seen_edge_ids: Set[str] = set()
        for edge in edge_list:
            if edge.edge_id in seen_edge_ids:
                errors.append(f"Duplicate edge ID detected: '{edge.edge_id}'")
            seen_edge_ids.add(edge.edge_id)

            edge_errors = cls.validate_edge(
                edge,
                known_node_ids=seen_node_ids,
                expected_org_id=expected_org_id,
                verify_fingerprint=verify_fingerprints,
            )
            errors.extend(edge_errors)

        return TwinValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            warnings=warnings,
            node_count=len(node_list),
            edge_count=len(edge_list),
        )

    @classmethod
    def validate_snapshot(cls, snapshot: DigitalTwinSnapshot) -> TwinValidationResult:
        """Validate an immutable snapshot's internal consistency and cryptographic integrity."""
        errors: List[str] = []

        # Validate count alignments
        if snapshot.node_count != len(snapshot.nodes):
            errors.append(
                f"Snapshot node_count mismatch: header claims {snapshot.node_count}, but dictionary contains {len(snapshot.nodes)}"
            )
        if snapshot.edge_count != len(snapshot.edges):
            errors.append(
                f"Snapshot edge_count mismatch: header claims {snapshot.edge_count}, but dictionary contains {len(snapshot.edges)}"
            )

        # Validate graph content
        graph_result = cls.validate_graph(
            nodes=snapshot.nodes,
            edges=snapshot.edges,
            expected_org_id=snapshot.organization_id,
            verify_fingerprints=True,
        )
        errors.extend(graph_result.errors)

        # Validate aggregate snapshot fingerprint
        node_fps = [n.fingerprint for n in snapshot.nodes.values()]
        edge_fps = [e.fingerprint for e in snapshot.edges.values()]
        computed_twin_fp = compute_twin_fingerprint(
            twin_id=snapshot.twin_id,
            organization_id=snapshot.organization_id,
            version=snapshot.version,
            node_fingerprints=node_fps,
            edge_fingerprints=edge_fps,
        )
        if computed_twin_fp != snapshot.twin_fingerprint:
            errors.append(
                f"Snapshot twin_fingerprint mismatch: expected '{computed_twin_fp}', got '{snapshot.twin_fingerprint}'"
            )

        return TwinValidationResult(
            is_valid=(len(errors) == 0),
            errors=errors,
            warnings=graph_result.warnings,
            node_count=snapshot.node_count,
            edge_count=snapshot.edge_count,
        )

    @classmethod
    def assert_valid_graph(
        cls,
        nodes: Union[Dict[str, TwinNodeContract], Sequence[TwinNodeContract]],
        edges: Union[Dict[str, TwinEdgeContract], Sequence[TwinEdgeContract]],
        expected_org_id: str,
    ) -> None:
        """Raise appropriate typed exception if graph validation fails."""
        result = cls.validate_graph(nodes=nodes, edges=edges, expected_org_id=expected_org_id)
        if not result.is_valid:
            for err in result.errors:
                if "tenant mismatch" in err.lower():
                    raise TwinTenantIsolationError(err)
                if "does not exist in graph" in err.lower():
                    raise TwinReferenceError(err)
                if "fingerprint mismatch" in err.lower():
                    raise TwinFingerprintError(err)
            raise TwinValidationError("; ".join(result.errors))
