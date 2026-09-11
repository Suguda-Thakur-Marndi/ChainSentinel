"""Persistence module re-export for RiskWise Simulation Engine."""
from __future__ import annotations

from app.simulation.repository import SimulationRepository

__all__ = [
    "SimulationRepository",
]
