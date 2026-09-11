"""Structured observability, logging, and audit emission for Simulation Engine."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("riskwise.simulation")

# List of sensitive keys that must never appear in simulation logs
REDACTED_KEYS = {"password", "secret", "token", "key", "authorization", "cookie"}


def sanitize_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Scrub sensitive keys from telemetry payloads."""
    sanitized = {}
    for k, v in d.items():
        if any(sec in k.lower() for sec in REDACTED_KEYS):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_dict(v)
        else:
            sanitized[k] = v
    return sanitized


class SimulationObservability:
    """Telemetry collector and logger for simulation lifecycle events."""

    @staticmethod
    def log_simulation_started(
        organization_id: str,
        scenario_id: str,
        simulation_id: str,
        base_snapshot_fingerprint: str,
        request_id: Optional[str] = None,
    ) -> None:
        payload = {
            "event": "SIMULATION_STARTED",
            "organization_id": organization_id,
            "scenario_id": scenario_id,
            "simulation_id": simulation_id,
            "base_snapshot_fingerprint": base_snapshot_fingerprint[:16] + "...",
            "request_id": request_id,
            "timestamp": time.time(),
        }
        logger.info(f"Simulation started: {scenario_id} for org {organization_id}", extra=sanitize_dict(payload))

    @staticmethod
    def log_simulation_completed(
        organization_id: str,
        scenario_id: str,
        simulation_id: str,
        simulation_fingerprint: str,
        duration_ms: float,
        effects_count: int,
        nodes_visited: int,
        edges_traversed: int,
        severity: str,
        request_id: Optional[str] = None,
    ) -> None:
        payload = {
            "event": "SIMULATION_COMPLETED",
            "organization_id": organization_id,
            "scenario_id": scenario_id,
            "simulation_id": simulation_id,
            "simulation_fingerprint": simulation_fingerprint[:16] + "...",
            "duration_ms": duration_ms,
            "effects_count": effects_count,
            "nodes_visited": nodes_visited,
            "edges_traversed": edges_traversed,
            "severity": severity,
            "request_id": request_id,
        }
        logger.info(
            f"Simulation completed: {simulation_id} in {duration_ms:.2f}ms (Severity: {severity})",
            extra=sanitize_dict(payload),
        )

    @staticmethod
    def log_simulation_failed(
        organization_id: str,
        scenario_id: str,
        simulation_id: str,
        error_category: str,
        error_message: str,
        request_id: Optional[str] = None,
    ) -> None:
        payload = {
            "event": "SIMULATION_FAILED",
            "organization_id": organization_id,
            "scenario_id": scenario_id,
            "simulation_id": simulation_id,
            "error_category": error_category,
            "error_message": error_message,
            "request_id": request_id,
        }
        logger.error(
            f"Simulation failed: {simulation_id} - {error_category}: {error_message}",
            extra=sanitize_dict(payload),
        )
