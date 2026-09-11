"""Deterministic identity generators and canonical SHA-256 fingerprinting for Digital Twin.

Enforces:
- Deterministic UUIDv5 node and edge IDs based on canonical source entity metadata.
- Canonical JSON serialization for order-invariant, reproducible fingerprints.
- Separation of operational semantics from runtime clock time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, Sequence


TWIN_NAMESPACE = uuid.UUID("a7e1f4b8-3d2c-4f9e-8b1a-5c6d7e8f9a0b")


def compute_node_id(organization_id: str, source_entity_type: str, source_entity_id: str) -> str:
    """Generate a deterministic, tenant-isolated node identifier.

    Guarantees:
    - Same (org, entity_type, entity_id) always yields the exact same ID.
    - Different tenants produce distinct, isolated IDs even for identical entity IDs.
    - Different entity types produce distinct IDs.
    """
    clean_org = (organization_id or "global").strip().lower()
    clean_type = source_entity_type.strip().lower()
    clean_id = source_entity_id.strip()
    key = f"riskwise:node:{clean_org}:{clean_type}:{clean_id}"
    return str(uuid.uuid5(TWIN_NAMESPACE, key))


def compute_edge_id(
    organization_id: str,
    from_node_id: str,
    to_node_id: str,
    edge_type: str,
    relationship_id: str = "",
) -> str:
    """Generate a deterministic, tenant-isolated edge identifier.

    Guarantees:
    - Same (org, from_node, to_node, edge_type, relationship_id) yields identical ID.
    - Different tenants produce distinct IDs.
    - Multiple parallel edges between identical endpoints can be disambiguated via relationship_id.
    """
    clean_org = (organization_id or "global").strip().lower()
    clean_from = from_node_id.strip()
    clean_to = to_node_id.strip()
    clean_type = edge_type.strip().upper()
    clean_rel = relationship_id.strip()
    key = f"riskwise:edge:{clean_org}:{clean_from}:{clean_to}:{clean_type}:{clean_rel}"
    return str(uuid.uuid5(TWIN_NAMESPACE, key))


def compute_node_fingerprint(
    node_id: str,
    organization_id: str,
    node_type: str,
    source_entity_type: str,
    source_entity_id: str,
    label: str,
    latitude: float | None = None,
    longitude: float | None = None,
    health_score: float | None = None,
    status: str | None = None,
    properties: Dict[str, Any] | None = None,
) -> str:
    """Compute deterministic SHA-256 fingerprint for a single twin node."""
    payload = {
        "node_id": node_id,
        "organization_id": organization_id,
        "node_type": node_type,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "label": label,
        "latitude": round(latitude, 6) if latitude is not None else None,
        "longitude": round(longitude, 6) if longitude is not None else None,
        "health_score": round(health_score, 2) if health_score is not None else None,
        "status": status,
        "properties": properties or {},
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_edge_fingerprint(
    edge_id: str,
    organization_id: str,
    from_node_id: str,
    to_node_id: str,
    edge_type: str,
    status: str | None = None,
    flow_capacity: float | None = None,
    current_flow: float | None = None,
    risk_score: float | None = None,
    properties: Dict[str, Any] | None = None,
    source_reference: str | None = None,
) -> str:
    """Compute deterministic SHA-256 fingerprint for a single twin edge."""
    payload = {
        "edge_id": edge_id,
        "organization_id": organization_id,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "edge_type": edge_type,
        "status": status,
        "flow_capacity": round(flow_capacity, 2) if flow_capacity is not None else None,
        "current_flow": round(current_flow, 2) if current_flow is not None else None,
        "risk_score": round(risk_score, 2) if risk_score is not None else None,
        "properties": properties or {},
        "source_reference": source_reference,
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_source_fingerprint(entity_digests: Sequence[str]) -> str:
    """Compute aggregate SHA-256 fingerprint of authoritative source state."""
    hasher = hashlib.sha256()
    for digest in sorted(entity_digests):
        hasher.update(digest.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def compute_twin_fingerprint(
    twin_id: str,
    organization_id: str,
    version: str,
    node_fingerprints: Sequence[str],
    edge_fingerprints: Sequence[str],
) -> str:
    """Compute canonical SHA-256 fingerprint for an entire Digital Twin snapshot."""
    hasher = hashlib.sha256()
    header = f"{twin_id}:{organization_id}:{version}:{len(node_fingerprints)}:{len(edge_fingerprints)}:\n"
    hasher.update(header.encode("utf-8"))
    for n_fp in sorted(node_fingerprints):
        hasher.update(f"N:{n_fp}\n".encode("utf-8"))
    for e_fp in sorted(edge_fingerprints):
        hasher.update(f"E:{e_fp}\n".encode("utf-8"))
    return hasher.hexdigest()
