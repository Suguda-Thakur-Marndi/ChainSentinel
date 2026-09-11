"""Typed configuration settings for the RiskWise ML subsystem.

Enforces configurable minimum row thresholds, artifact directories, random seeds,
and inference timeouts while avoiding hard-coded deployment paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MLConfig(BaseSettings):
    """Configuration for ML model training, evaluation, artifacts, and inference."""

    model_config = SettingsConfigDict(
        env_prefix="ML_",
        extra="ignore",
        case_sensitive=False,
    )

    ENABLED: bool = Field(default=True, description="Whether ML inference services are enabled")
    MODEL_NAME: str = Field(default="shipment_delay_ridge", description="Default model name for shipment delay")
    MODEL_VERSION: str = Field(default="1.0.0", description="Semantic version of model")
    FEATURE_SCHEMA_VERSION: str = Field(default="shipment_delay_v1", description="Feature schema version")
    MIN_TRAINING_ROWS: int = Field(default=20, ge=5, description="Minimum rows required to train a valid model")
    ARTIFACT_DIR: str = Field(
        default="storage/ml_artifacts",
        description="Local directory or root storage path for serialized model artifacts",
    )
    RANDOM_SEED: int = Field(default=42, description="Fixed random seed for deterministic training & splits")
    TEST_SPLIT_RATIO: float = Field(default=0.2, ge=0.05, le=0.5, description="Test split proportion")
    VAL_SPLIT_RATIO: float = Field(default=0.1, ge=0.0, le=0.4, description="Validation split proportion")
    INFERENCE_TIMEOUT_SECONDS: float = Field(default=5.0, ge=0.1, description="Timeout limit for single prediction inference")

    def get_artifact_path(self, model_id: str) -> Path:
        """Resolve absolute path for a model artifact ensuring no path traversal."""
        from app.ml.errors import ModelArtifactError
        if ".." in model_id or "/" in model_id or "\\" in model_id or Path(model_id).name != model_id:
            raise ModelArtifactError(f"Path traversal detected for model_id: {model_id}")
        base_path = Path(self.ARTIFACT_DIR).resolve()
        resolved = (base_path / f"{model_id}.joblib").resolve()
        if not str(resolved).startswith(str(base_path)):
            raise ModelArtifactError(f"Path traversal detected for model_id: {model_id}")
        return resolved


ml_config = MLConfig()
