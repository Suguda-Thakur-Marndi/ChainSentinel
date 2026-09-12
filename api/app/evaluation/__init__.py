"""RiskWise 2.0 — Phase 20: Evaluation & Quality Assurance Framework.

Provides deterministic, reproducible, tenant-safe evaluation suites,
metric computation engines, versioned golden datasets, and evaluation persistence.
"""
from app.evaluation.contracts import (
    DatasetCategory,
    EvaluationArtifact,
    EvaluationCase,
    EvaluationDomain,
    EvaluationFailure,
    EvaluationMetric,
    EvaluationReport,
    EvaluationResult,
    EvaluationRun,
    EvaluationScore,
    EvaluationStatus,
    EvaluationSuiteType,
)
from app.evaluation.errors import (
    ContaminationError,
    EvaluationError,
    EvaluationSecurityViolation,
    InsufficientDataError,
    MetricCalculationError,
    SuiteExecutionError,
)
from app.evaluation.metrics import MetricEngine
from app.evaluation.runner import EvaluationRunner

__all__ = [
    "EvaluationStatus",
    "EvaluationSuiteType",
    "DatasetCategory",
    "EvaluationDomain",
    "EvaluationCase",
    "EvaluationResult",
    "EvaluationMetric",
    "EvaluationScore",
    "EvaluationFailure",
    "EvaluationArtifact",
    "EvaluationReport",
    "EvaluationRun",
    "MetricEngine",
    "EvaluationRunner",
    "EvaluationError",
    "ContaminationError",
    "InsufficientDataError",
    "MetricCalculationError",
    "SuiteExecutionError",
    "EvaluationSecurityViolation",
]
