"""Configuration and resource bounding limits for RiskWise Optimization Subsystem (Phase 14).

Enforces hard safety boundaries to prevent solver resource exhaustion, runaway computations,
and out-of-memory errors.
"""
from __future__ import annotations

from typing import Final

OPTIMIZATION_ENGINE_VERSION: Final[str] = "2.0.0"

# Hard limits for mathematical model formulation
HARD_MAX_VARIABLES: Final[int] = 1000
HARD_MAX_CANDIDATES: Final[int] = 500
HARD_MAX_CONSTRAINTS: Final[int] = 2000
HARD_MAX_OBJECTIVE_TERMS: Final[int] = 500

# Solver execution limits
HARD_MAX_SOLVER_TIME_SECONDS: Final[float] = 30.0
DEFAULT_SOLVER_TIMEOUT_SECONDS: Final[float] = 10.0

# Result limits
MAX_RESULT_ALTERNATIVES: Final[int] = 500
MAX_RESULT_METRICS: Final[int] = 50

# Tolerances
DEFAULT_INTEGER_TOLERANCE: Final[float] = 1e-6
DEFAULT_MIP_GAP_TOLERANCE: Final[float] = 1e-4
