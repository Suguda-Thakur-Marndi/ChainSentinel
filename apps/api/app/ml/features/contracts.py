"""Contracts and interfaces for ML feature engineering pipelines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List
import numpy as np

from app.ml.contracts import FeatureSchema
from app.ml.datasets.contracts import DatasetRow


class BaseFeaturePipeline(ABC):
    """Abstract interface for deterministic feature engineering and transformation pipelines."""

    @abstractmethod
    def fit(self, rows: List[DatasetRow]) -> "BaseFeaturePipeline":
        """Fit preprocessing parameters (scalers, encoders) strictly on training rows."""
        raise NotImplementedError

    @abstractmethod
    def transform(self, rows: List[DatasetRow]) -> np.ndarray:
        """Transform dataset rows into an encoded 2D feature matrix."""
        raise NotImplementedError

    @abstractmethod
    def transform_single(self, features: Dict[str, Any]) -> np.ndarray:
        """Transform a single observation dictionary into a 2D feature vector (1, n_features)."""
        raise NotImplementedError

    @abstractmethod
    def get_feature_schema(self) -> FeatureSchema:
        """Retrieve the authoritative FeatureSchema definition."""
        raise NotImplementedError

    @abstractmethod
    def get_output_feature_names(self) -> List[str]:
        """Retrieve the list of encoded output feature names matching the transformed matrix."""
        raise NotImplementedError

    @property
    @abstractmethod
    def is_fitted(self) -> bool:
        """Whether the pipeline has been fitted."""
        raise NotImplementedError

