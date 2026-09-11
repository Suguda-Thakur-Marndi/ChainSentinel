"""Secure model artifact management with serialization, hashing, and path traversal defenses."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Tuple
import joblib

from app.ml.config import ml_config
from app.ml.contracts import (
    FeatureSchema,
    MLModelMetadata,
    ModelArtifact,
    compute_artifact_fingerprint,
)
from app.ml.errors import ModelArtifactError
from app.ml.features.contracts import BaseFeaturePipeline
from app.ml.models.base import BasePredictionModel


class ArtifactManager:
    """Manages secure serialization, fingerprint verification, and loading of model artifacts."""

    @staticmethod
    def save_artifact(
        model: BasePredictionModel,
        feature_pipeline: BaseFeaturePipeline,
        metadata: MLModelMetadata,
        artifact_dir: Optional[Path] = None,
    ) -> Tuple[ModelArtifact, Path]:
        """Serialize model and pipeline together into a validated artifact."""
        target_dir = Path(artifact_dir or ml_config.ARTIFACT_DIR).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        # Path traversal guard
        file_path = (target_dir / f"{metadata.model_id}.joblib").resolve()
        if not str(file_path).startswith(str(target_dir)):
            raise ModelArtifactError(f"Path traversal detected in model_id: {metadata.model_id}")

        # 1. Deterministically serialize model and pipeline weights
        weights_buf = io.BytesIO()
        joblib.dump({"model": model, "pipeline": feature_pipeline}, weights_buf)
        weights_bytes = weights_buf.getvalue()

        # 2. Compute cryptographic fingerprint
        computed_fingerprint = compute_artifact_fingerprint(
            model_id=metadata.model_id,
            model_version=metadata.model_version,
            dataset_fingerprint=metadata.training_dataset_fingerprint,
            feature_names=metadata.feature_names,
            serialized_weights_bytes=weights_bytes,
        )

        updated_metadata = metadata.model_copy(update={"artifact_fingerprint": computed_fingerprint})

        # 3. Create full artifact bundle with verified metadata
        bundle = {
            "model": model,
            "pipeline": feature_pipeline,
            "weights_bytes": weights_bytes,
            "metadata_dict": updated_metadata.model_dump(mode="json"),
            "schema_dict": feature_pipeline.get_feature_schema().model_dump(mode="json"),
        }
        final_buf = io.BytesIO()
        joblib.dump(bundle, final_buf)
        serialized_bytes = final_buf.getvalue()

        artifact = ModelArtifact(
            metadata=updated_metadata,
            feature_schema=feature_pipeline.get_feature_schema(),
            serialized_pipeline=serialized_bytes,
            artifact_fingerprint=computed_fingerprint,
        )

        # Write to disk
        with open(file_path, "wb") as f:
            f.write(serialized_bytes)

        return artifact, file_path

    @staticmethod
    def load_artifact(
        artifact_path: Path,
        expected_model_id: Optional[str] = None,
        base_dir: Optional[Path] = None,
    ) -> Tuple[BasePredictionModel, BaseFeaturePipeline, MLModelMetadata]:
        """Safely load and verify an artifact, checking path security and fingerprint integrity."""
        resolved_path = Path(artifact_path).resolve()
        expected_base = Path(base_dir or ml_config.ARTIFACT_DIR).resolve()

        if not resolved_path.is_file():
            raise ModelArtifactError(f"Artifact file not found at path: {resolved_path}")

        # Path traversal check
        if not str(resolved_path).startswith(str(expected_base)):
            raise ModelArtifactError(f"Path traversal detected: {resolved_path} outside {expected_base}")

        try:
            with open(resolved_path, "rb") as f:
                raw_bytes = f.read()
        except Exception as exc:
            raise ModelArtifactError(f"Failed to read artifact file {resolved_path}: {exc}") from exc

        try:
            bio = io.BytesIO(raw_bytes)
            bundle = joblib.load(bio)
            if bio.tell() != len(raw_bytes):
                raise ModelArtifactError(
                    f"Artifact integrity violation: extraneous bytes detected at end of {resolved_path}. Possible file tampering."
                )
        except ModelArtifactError:
            raise
        except Exception as exc:
            raise ModelArtifactError(f"Corrupted or invalid joblib artifact at {resolved_path}: {exc}") from exc


        if not isinstance(bundle, dict) or "model" not in bundle or "pipeline" not in bundle or "metadata_dict" not in bundle:
            raise ModelArtifactError("Artifact bundle missing required 'model', 'pipeline', or 'metadata_dict' keys.")

        meta_dict = bundle["metadata_dict"]
        metadata = MLModelMetadata.model_validate(meta_dict)

        if expected_model_id and metadata.model_id != expected_model_id:
            raise ModelArtifactError(
                f"Model ID mismatch: expected '{expected_model_id}' but found '{metadata.model_id}'."
            )

        weights_bytes = bundle.get("weights_bytes")
        if not weights_bytes:
            w_buf = io.BytesIO()
            joblib.dump({"model": bundle["model"], "pipeline": bundle["pipeline"]}, w_buf)
            weights_bytes = w_buf.getvalue()

        # Verify cryptographic fingerprint
        computed_fp = compute_artifact_fingerprint(
            model_id=metadata.model_id,
            model_version=metadata.model_version,
            dataset_fingerprint=metadata.training_dataset_fingerprint,
            feature_names=metadata.feature_names,
            serialized_weights_bytes=weights_bytes,
        )

        if computed_fp != metadata.artifact_fingerprint:
            raise ModelArtifactError(
                f"Artifact integrity violation: computed fingerprint {computed_fp} "
                f"does not match metadata fingerprint {metadata.artifact_fingerprint}. Possible file tampering."
            )

        model: BasePredictionModel = bundle["model"]
        pipeline: BaseFeaturePipeline = bundle["pipeline"]
        return model, pipeline, metadata

