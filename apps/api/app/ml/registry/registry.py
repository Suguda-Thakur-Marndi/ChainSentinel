"""Lightweight, tenant-aware model registry.

Zero database changes: stores model metadata and references in memory and disk artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.ml.config import ml_config
from app.ml.contracts import MLModelMetadata, ModelArtifact, ModelFamily
from app.ml.errors import MLTenantIsolationError, ModelRegistryError
from app.ml.features.contracts import BaseFeaturePipeline
from app.ml.models.base import BasePredictionModel
from app.ml.observability import MLObservability
from app.ml.training.artifacts import ArtifactManager


class ModelRegistry:
    """Registry maintaining active and registered models with tenant isolation enforcement."""

    def __init__(self, artifact_dir: Optional[Path] = None) -> None:
        self._artifact_dir = Path(artifact_dir or ml_config.ARTIFACT_DIR).resolve()
        # In-memory registry mapping model_id -> (model, pipeline, metadata)
        self._models: Dict[str, Tuple[BasePredictionModel, BaseFeaturePipeline, MLModelMetadata]] = {}

    def clear(self) -> None:
        """Reset in-memory registry (used in test teardown)."""
        self._models.clear()

    def register_model(
        self,
        model: BasePredictionModel,
        pipeline: BaseFeaturePipeline,
        metadata: MLModelMetadata,
    ) -> str:
        """Register a model instance, pipeline, and its metadata."""
        if not metadata.model_id or not metadata.model_id.strip():
            raise ModelRegistryError("model_id must be non-empty for registration.")

        self._models[metadata.model_id] = (model, pipeline, metadata)
        MLObservability.emit_training_event(
            action="ML_MODEL_REGISTERED",
            organization_id=metadata.organization_id or "global",
            model_id=metadata.model_id,
            metrics=metadata.metrics.model_dump(),
            duration_ms=0.0,
        )
        return metadata.model_id

    def get_model(
        self,
        model_id: str,
        organization_id: Optional[str] = None,
    ) -> Optional[Tuple[BasePredictionModel, BaseFeaturePipeline, MLModelMetadata]]:
        """Retrieve a registered model with tenant isolation enforcement."""
        entry = self._models.get(model_id)
        if entry is None:
            # Try loading from artifact file if present on disk
            try:
                artifact_path = ml_config.get_artifact_path(model_id)
                if artifact_path.is_file():
                    loaded_model, loaded_pipe, loaded_meta = ArtifactManager.load_artifact(
                        artifact_path=artifact_path,
                        expected_model_id=model_id,
                        base_dir=self._artifact_dir,
                    )
                    entry = (loaded_model, loaded_pipe, loaded_meta)
                    self._models[model_id] = entry
            except Exception:
                entry = None

        if entry is None:
            return None

        _, _, meta = entry
        # Enforce tenant isolation
        if meta.organization_id and organization_id:
            if meta.organization_id != organization_id:
                raise MLTenantIsolationError(
                    f"Model '{model_id}' belongs to tenant '{meta.organization_id}', "
                    f"inaccessible to tenant '{organization_id}'."
                )

        return entry

    def get_active_model(
        self,
        family: ModelFamily = ModelFamily.SHIPMENT_DELAY,
        organization_id: Optional[str] = None,
    ) -> Optional[Tuple[BasePredictionModel, BaseFeaturePipeline, MLModelMetadata]]:
        """Get the active production model for a family and tenant."""
        # 1. Look for tenant-specific model first
        if organization_id:
            for m_id, entry in self._models.items():
                _, _, meta = entry
                if meta.model_family == family and meta.organization_id == organization_id and meta.is_production:
                    return entry

        # 2. Look for global model
        for m_id, entry in self._models.items():
            _, _, meta = entry
            if meta.model_family == family and meta.organization_id is None and meta.is_production:
                return entry

        # Fallback to any registered model for this family and tenant
        for m_id, entry in self._models.items():
            _, _, meta = entry
            if meta.model_family == family:
                if organization_id is None or meta.organization_id is None or meta.organization_id == organization_id:
                    return entry

        return None

    def list_models(
        self,
        family: Optional[ModelFamily] = None,
        organization_id: Optional[str] = None,
    ) -> List[MLModelMetadata]:
        """List registered models matching filters."""
        results: List[MLModelMetadata] = []
        for _, entry in self._models.items():
            _, _, meta = entry
            if family and meta.model_family != family:
                continue
            if organization_id and meta.organization_id and meta.organization_id != organization_id:
                continue
            results.append(meta)
        return results


default_model_registry = ModelRegistry()
