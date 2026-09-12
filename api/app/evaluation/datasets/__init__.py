"""Evaluation datasets package for RiskWise 2.0."""

from app.evaluation.datasets.contracts import EvaluationDataset
from app.evaluation.datasets.registry import DatasetRegistry, DEFAULT_DATASET_VERSION

__all__ = [
    "EvaluationDataset",
    "DatasetRegistry",
    "DEFAULT_DATASET_VERSION",
]
