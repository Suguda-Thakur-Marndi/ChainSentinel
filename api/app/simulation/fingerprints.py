"""Deterministic SHA-256 fingerprinting and UUIDv5 identity generation for Simulation Engine."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Sequence

from app.simulation.contracts import SimulationChange

# Dedicated UUIDv5 namespaces for deterministic simulation entity IDs
SCENARIO_NAMESPACE = uuid.UUID("7a3e9c12-4f6b-4e89-a215-0d62c38f9b41")
SIMULATION_NAMESPACE = uuid.UUID("8b4f0d23-5a7c-4f9a-b326-1e73d49a0c52")
CHANGE_NAMESPACE = uuid.UUID("9c5a1e34-6b8d-5a0b-c437-2f84e50b1d63")
EFFECT_NAMESPACE = uuid.UUID("ad6b2f45-7c9e-6b1c-d548-3a95f61c2e74")


def canonical_json(data: Any) -> str:
    """Serialize data structures to canonical JSON with sorted keys and stable separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_sha256(content: str) -> str:
    """Compute 64-character SHA-256 hexadecimal digest."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_scenario_id(organization_id: str, name: str, base_snapshot_fingerprint: str) -> str:
    """Generate deterministic UUIDv5 identifier for a scenario."""
    canonical_key = f"{organization_id.strip()}:{name.strip()}:{base_snapshot_fingerprint.strip()}"
    return str(uuid.uuid5(SCENARIO_NAMESPACE, canonical_key))


def compute_change_id(
    scenario_id: str,
    target_entity_id: str,
    change_type: str,
    magnitude: float,
) -> str:
    """Generate deterministic UUIDv5 identifier for a hypothetical change."""
    canonical_key = f"{scenario_id.strip()}:{target_entity_id.strip()}:{change_type.strip()}:{magnitude}"
    return str(uuid.uuid5(CHANGE_NAMESPACE, canonical_key))


def compute_effect_id(
    simulation_id: str,
    originating_change_id: str,
    affected_entity_id: str,
    effect_type: str,
) -> str:
    """Generate deterministic UUIDv5 identifier for a propagated effect."""
    canonical_key = f"{simulation_id.strip()}:{originating_change_id.strip()}:{affected_entity_id.strip()}:{effect_type.strip()}"
    return str(uuid.uuid5(EFFECT_NAMESPACE, canonical_key))


def compute_simulation_id(scenario_id: str, base_snapshot_fingerprint: str, configuration_hash: str) -> str:
    """Generate deterministic UUIDv5 identifier for a simulation run."""
    canonical_key = f"{scenario_id.strip()}:{base_snapshot_fingerprint.strip()}:{configuration_hash.strip()}"
    return str(uuid.uuid5(SIMULATION_NAMESPACE, canonical_key))


def compute_change_fingerprint(change: SimulationChange) -> str:
    """Compute deterministic fingerprint for a single hypothetical change."""
    canonical_repr = {
        "change_type": change.change_type.value,
        "target_entity_type": change.target_entity_type,
        "target_entity_id": change.target_entity_id,
        "magnitude": change.magnitude,
        "unit": change.unit.value,
        "duration_minutes": change.duration_minutes,
        "reason": change.reason,
        "source_type": change.source_type,
    }
    return compute_sha256(canonical_json(canonical_repr))


def compute_scenario_fingerprint(
    organization_id: str,
    name: str,
    base_snapshot_fingerprint: str,
    changes: Sequence[SimulationChange],
    parameters: Dict[str, Any],
) -> str:
    """Compute deterministic fingerprint for a scenario definition."""
    sorted_change_hashes = sorted([compute_change_fingerprint(c) for c in changes])
    payload = {
        "organization_id": organization_id.strip(),
        "name": name.strip(),
        "base_snapshot_fingerprint": base_snapshot_fingerprint.strip(),
        "changes": sorted_change_hashes,
        "parameters": parameters,
    }
    return compute_sha256(canonical_json(payload))


def compute_simulation_fingerprint(
    base_snapshot_fingerprint: str,
    scenario_fingerprint: str,
    max_depth: int,
    max_nodes: int,
    max_edges: int,
    max_effects: int,
) -> str:
    """Compute deterministic fingerprint for a simulation execution."""
    payload = {
        "base_snapshot_fingerprint": base_snapshot_fingerprint.strip(),
        "scenario_fingerprint": scenario_fingerprint.strip(),
        "max_depth": max_depth,
        "max_nodes": max_nodes,
        "max_edges": max_edges,
        "max_effects": max_effects,
    }
    return compute_sha256(canonical_json(payload))
