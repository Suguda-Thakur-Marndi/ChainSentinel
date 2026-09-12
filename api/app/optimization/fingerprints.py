"""Deterministic SHA-256 canonical fingerprint and UUID generation for Phase 14 Optimization.

Enforces:
- Strict key-sorted canonical JSON serialization
- Timestamps excluded from semantic fingerprints to guarantee identical hashes for identical problem states
- Deterministic UUIDv5 identifiers in the RiskWise optimization namespace
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional

# Deterministic namespace for RiskWise Phase 14 Optimization
OPTIMIZATION_NAMESPACE = uuid.UUID("4c8a51d2-09b3-4f9e-a86d-62507851e29c")


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize object to canonical, deterministic UTF-8 JSON bytes."""

    def _default(val: Any) -> Any:
        if hasattr(val, "model_dump"):
            return val.model_dump(mode="json")
        if isinstance(val, (set, frozenset)):
            return sorted(list(val))
        raise TypeError(f"Object of type {type(val)} is not JSON serializable")

    serialized = json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_default,
    )
    return serialized.encode("utf-8")


def sha256_digest(data: bytes) -> str:
    """Compute 64-character lowercase SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def compute_request_fingerprint(
    organization_id: str,
    domain: str,
    objective_type: str,
    snapshot_fingerprint: Optional[str] = None,
    simulation_fingerprint: Optional[str] = None,
    target_entity_ids: Optional[List[str]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    solver_config: Optional[Dict[str, Any]] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> str:
    """Compute semantic fingerprint of an optimization request."""
    canonical_dict = {
        "organization_id": organization_id,
        "domain": domain,
        "objective_type": objective_type,
        "snapshot_fingerprint": snapshot_fingerprint or "",
        "simulation_fingerprint": simulation_fingerprint or "",
        "target_entity_ids": sorted(target_entity_ids or []),
        "candidates": sorted(
            [c.get("alternative_id", "") for c in (candidates or [])]
        ),
        "solver_config": solver_config or {},
        "parameters": parameters or {},
    }
    return sha256_digest(canonical_json_bytes(canonical_dict))


def compute_problem_fingerprint(
    organization_id: str,
    domain: str,
    variable_ids: List[str],
    constraint_ids: List[str],
    objective_dict: Dict[str, Any],
) -> str:
    """Compute semantic fingerprint of a canonicalized mathematical problem formulation."""
    canonical_dict = {
        "organization_id": organization_id,
        "domain": domain,
        "variable_ids": sorted(variable_ids),
        "constraint_ids": sorted(constraint_ids),
        "objective": objective_dict,
    }
    return sha256_digest(canonical_json_bytes(canonical_dict))


def compute_result_fingerprint(
    optimization_id: str,
    status: str,
    objective_value: Optional[float],
    variable_assignments: Dict[str, float],
    selected_alternative_ids: List[str],
) -> str:
    """Compute semantic fingerprint of an optimization solver result."""
    canonical_dict = {
        "optimization_id": optimization_id,
        "status": status,
        "objective_value": round(objective_value, 6) if objective_value is not None else None,
        "variable_assignments": {
            k: round(v, 6) for k, v in sorted(variable_assignments.items())
        },
        "selected_alternatives": sorted(selected_alternative_ids),
    }
    return sha256_digest(canonical_json_bytes(canonical_dict))


def generate_optimization_id(request_fingerprint: str) -> str:
    """Generate deterministic UUIDv5 identifier for an optimization run."""
    return str(uuid.uuid5(OPTIMIZATION_NAMESPACE, f"run:{request_fingerprint}"))


def generate_variable_id(domain: str, source_id: str, target_id: str) -> str:
    """Generate deterministic variable ID (e.g. var:reroute:shipment_1:route_A)."""
    return f"var:{domain.lower()}:{source_id}:{target_id}"


def generate_constraint_id(constraint_type: str, entity_id: str, suffix: str = "") -> str:
    """Generate deterministic constraint ID."""
    if suffix:
        return f"con:{constraint_type.lower()}:{entity_id}:{suffix}"
    return f"con:{constraint_type.lower()}:{entity_id}"
