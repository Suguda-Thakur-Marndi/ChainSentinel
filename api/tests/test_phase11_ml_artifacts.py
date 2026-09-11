"""Unit tests for ML model artifact management, integrity verification, and security defenses."""

from __future__ import annotations

import io
from pathlib import Path
import joblib
import numpy as np
import pytest

from app.ml.contracts import (
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
    compute_artifact_fingerprint,
)
from app.ml.errors import ModelArtifactError
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.training.artifacts import ArtifactManager
from tests.test_phase11_ml_dataset import make_sample_rows


@pytest.fixture
def trained_components(tmp_path: Path):
    rows = make_sample_rows(25)
    pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
    pipeline.fit(rows)

    X = pipeline.transform(rows)
    y = np.array([r.target for r in rows], dtype=np.float64)

    model = ShipmentDelayModel(model_id="test_art_model", model_version="1.0.0", random_seed=42)
    model.fit(X, y)
    metrics = model.evaluate(X, y)

    metadata = MLModelMetadata(
        model_id="test_art_model",
        model_family=ModelFamily.SHIPMENT_DELAY,
        model_version="1.0.0",
        task_type=TaskType.REGRESSION,
        target="delay_minutes",
        feature_names=pipeline.get_feature_schema().feature_names,
        training_dataset_fingerprint="ds_fp_12345",
        preprocessing_version=pipeline.get_feature_schema().version,
        hyperparameters={"alpha": 1.0},
        validation_status="VALIDATED",
        metrics=metrics,
        artifact_fingerprint="placeholder",
        organization_id="org_acme",
    )
    return model, pipeline, metadata, tmp_path


class TestArtifactManager:
    def test_save_and_load_artifact_roundtrip(self, trained_components) -> None:
        model, pipeline, metadata, tmp_path = trained_components

        artifact, file_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=tmp_path,
        )

        assert file_path.exists()
        assert len(artifact.artifact_fingerprint) == 64

        loaded_model, loaded_pipe, loaded_meta = ArtifactManager.load_artifact(
            artifact_path=file_path,
            expected_model_id="test_art_model",
            base_dir=tmp_path,
        )

        assert loaded_model.is_fitted is True
        assert loaded_pipe.is_fitted is True
        assert loaded_meta.model_id == "test_art_model"
        assert loaded_meta.artifact_fingerprint == artifact.artifact_fingerprint

        # Test inference equivalence
        test_feat = {"planned_duration_hours": 12.0, "transport_mode": "OCEAN"}
        vec1 = pipeline.transform_single(test_feat)
        vec2 = loaded_pipe.transform_single(test_feat)
        assert np.array_equal(vec1, vec2)

        pred1 = model.predict_single(vec1)
        pred2 = loaded_model.predict_single(vec2)
        assert pred1 == pred2

    def test_load_non_existent_artifact_raises_error(self, tmp_path: Path) -> None:
        non_existent = tmp_path / "ghost.joblib"
        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(non_existent, base_dir=tmp_path)
        assert "Artifact file not found" in str(exc_info.value)

    def test_load_tampered_artifact_fails_fingerprint_check(self, trained_components) -> None:
        model, pipeline, metadata, tmp_path = trained_components

        _, file_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=tmp_path,
        )

        # Tamper with file content by appending rogue bytes
        with open(file_path, "ab") as f:
            f.write(b"\x00\x00\x00ROGUE_BYTES")

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(
                artifact_path=file_path,
                expected_model_id="test_art_model",
                base_dir=tmp_path,
            )
        assert "Artifact integrity violation" in str(exc_info.value) or "Corrupted" in str(exc_info.value)

    def test_load_corrupted_artifact_raises_error(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupt.joblib"
        with open(bad_file, "wb") as f:
            f.write(b"NOT_A_VALID_JOBLIB_OR_PICKLE_STREAM")

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(bad_file, base_dir=tmp_path)
        assert "Corrupted or invalid joblib artifact" in str(exc_info.value)

    def test_load_artifact_model_id_mismatch_raises_error(self, trained_components) -> None:
        model, pipeline, metadata, tmp_path = trained_components

        _, file_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=tmp_path,
        )

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(
                artifact_path=file_path,
                expected_model_id="wrong_model_id",
                base_dir=tmp_path,
            )
        assert "Model ID mismatch" in str(exc_info.value)

    def test_path_traversal_save_rejected(self, trained_components) -> None:
        model, pipeline, metadata, tmp_path = trained_components

        traversal_metadata = metadata.model_copy(update={"model_id": "../../etc/passwd"})
        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.save_artifact(
                model=model,
                feature_pipeline=pipeline,
                metadata=traversal_metadata,
                artifact_dir=tmp_path,
            )
        assert "Path traversal detected" in str(exc_info.value)

    def test_path_traversal_load_rejected(self, tmp_path: Path) -> None:
        outside_path = tmp_path.parent / "outside.joblib"
        outside_path.touch()

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(
                artifact_path=outside_path,
                base_dir=tmp_path,
            )
        assert "Path traversal detected" in str(exc_info.value)

    def test_modified_weights_fails_fingerprint_check(self, trained_components) -> None:
        model, pipeline, metadata, tmp_path = trained_components

        artifact, file_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=tmp_path,
        )

        with open(file_path, "rb") as f:
            bundle = joblib.load(f)

        # Tamper with the weights_bytes inside the bundle while keeping metadata untouched
        bundle["weights_bytes"] = b"tampered_weights_bytes_different_hash"
        with open(file_path, "wb") as f:
            joblib.dump(bundle, f)

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(file_path, base_dir=tmp_path)
        assert "Artifact integrity violation" in str(exc_info.value)

    def test_modified_metadata_fails_fingerprint_check(self, trained_components) -> None:
        model, pipeline, metadata, tmp_path = trained_components

        artifact, file_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=tmp_path,
        )

        with open(file_path, "rb") as f:
            bundle = joblib.load(f)

        # Alter metadata field (e.g. claim a different training dataset fingerprint)
        meta_dict = dict(bundle["metadata_dict"])
        meta_dict["training_dataset_fingerprint"] = "fake_altered_dataset_fp"
        bundle["metadata_dict"] = meta_dict
        with open(file_path, "wb") as f:
            joblib.dump(bundle, f)

        with pytest.raises(ModelArtifactError) as exc_info:
            ArtifactManager.load_artifact(file_path, base_dir=tmp_path)
        assert "Artifact integrity violation" in str(exc_info.value)

