"""Complete reproducible training pipeline for shipment delay prediction."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np

from app.ml.config import ml_config
from app.ml.contracts import (
    MLModelMetadata,
    ModelArtifact,
    ModelFamily,
    TaskType,
)
from app.ml.datasets.builder import ShipmentDatasetBuilder
from app.ml.datasets.contracts import DatasetRow, DatasetSplitData, ValidatedDataset
from app.ml.datasets.validation import DatasetValidator
from app.ml.errors import InsufficientTrainingDataError
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.models.shipment_delay import ShipmentDelayModel

from app.ml.observability import MLObservability
from app.ml.training.artifacts import ArtifactManager
from app.ml.training.validation import ModelValidator


class ShipmentDelayTrainingPipeline:
    """Orchestrates time-aware dataset validation, feature preprocessing, model training, evaluation, and artifact generation."""

    def __init__(
        self,
        config: Optional[MLConfig] = None,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        alpha: float = 1.0,
        random_seed: Optional[int] = None,
        artifact_dir: Optional[Path] = None,
    ) -> None:
        cfg = config or ml_config
        self._config = cfg
        self._model_name = model_name or cfg.MODEL_NAME
        self._model_version = model_version or cfg.MODEL_VERSION
        self._alpha = alpha
        self._random_seed = random_seed if random_seed is not None else cfg.RANDOM_SEED
        self._artifact_dir = artifact_dir or Path(cfg.ARTIFACT_DIR)
        self._min_training_rows = cfg.MIN_TRAINING_ROWS


    def train_from_split(
        self,
        split: DatasetSplitData,
        model_id: Optional[str] = None,
        model_family: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> Tuple[ShipmentDelayModel, ShipmentDelayFeaturePipeline, ModelArtifact, Path]:
        """Train directly from pre-split dataset."""
        train_rows = split.train.rows
        test_rows = split.test.rows
        organization_id = split.train.organization_id

        if len(train_rows) < self._min_training_rows:
            raise InsufficientTrainingDataError(
                f"Insufficient training data: {len(train_rows)} rows (minimum: {self._min_training_rows})."
            )

        start_time = time.perf_counter()
        v = model_version or self._model_version
        mid = model_id or f"{self._model_name}_{v}_{organization_id}"

        # 1. Preprocessing
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(train_rows)

        X_train = pipeline.transform(train_rows)
        y_train = np.array([r.target for r in train_rows], dtype=np.float64)

        X_test = pipeline.transform(test_rows)
        y_test = np.array([r.target for r in test_rows], dtype=np.float64)

        # 2. Fit model
        model = ShipmentDelayModel(
            model_id=mid,
            model_version=v,
            alpha=self._alpha,
            random_seed=self._random_seed,
            organization_id=organization_id,
        )
        model.fit(X_train, y_train)

        # 3. Evaluate
        metrics = model.evaluate(X_test, y_test)

        # 4. Validate model
        ModelValidator.validate_model(model=model, X_test=X_test, y_test=y_test, metrics=metrics)

        # 5. Build metadata
        metadata = MLModelMetadata(
            model_id=mid,
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version=v,
            task_type=TaskType.REGRESSION,
            target=SHIPMENT_DELAY_SCHEMA.target_name,
            feature_names=pipeline.get_feature_schema().feature_names,
            feature_schema_fingerprint=pipeline.get_feature_schema().schema_fingerprint,
            training_dataset_fingerprint=split.train.dataset_fingerprint,
            training_timestamp=datetime.now(timezone.utc),

            preprocessing_version=pipeline.get_feature_schema().version,
            hyperparameters={"alpha": self._alpha, "random_seed": self._random_seed},
            validation_status="VALIDATED",
            metrics=metrics,
            artifact_fingerprint="temporary_placeholder",
            organization_id=organization_id,
            is_production=True,
        )
        model.set_metadata(metadata)

        # 6. Save artifact
        artifact, saved_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=self._artifact_dir,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        MLObservability.emit_training_event(
            action="ML_MODEL_TRAINED",
            organization_id=organization_id,
            model_id=mid,
            metrics=metrics.model_dump(),
            duration_ms=duration_ms,
        )

        return model, pipeline, artifact, saved_path

    def run(
        self,
        split: DatasetSplitData,
        model_id: Optional[str] = None,
        model_family: Optional[str] = None,
        model_version: Optional[str] = None,
    ) -> ModelArtifact:
        """Convenience execution returning only the validated ModelArtifact."""
        _, _, artifact, _ = self.train_from_split(
            split=split,
            model_id=model_id,
            model_family=model_family,
            model_version=model_version,
        )
        return artifact


    def train_from_rows(
        self,
        rows: List[DatasetRow],
        organization_id: str,
        dataset_id: str = "shipment_training_dataset",
        test_ratio: float = ml_config.TEST_SPLIT_RATIO,
        val_ratio: float = ml_config.VAL_SPLIT_RATIO,
        min_train_rows: int = ml_config.MIN_TRAINING_ROWS,
        min_test_rows: int = 3,
    ) -> Tuple[ShipmentDelayModel, ShipmentDelayFeaturePipeline, ModelArtifact, Path]:
        """Execute the end-to-end training pipeline.

        Returns:
            Tuple of (fitted_model, fitted_pipeline, validated_artifact, saved_path)
        """
        start_time = time.perf_counter()
        model_id = f"{self._model_name}_{self._model_version}_{organization_id}"

        # 1. Time-aware dataset splitting
        split_data: DatasetSplitData = ShipmentDatasetBuilder.time_aware_split(
            rows=rows,
            schema=SHIPMENT_DELAY_SCHEMA,
            organization_id=organization_id,
            dataset_id=dataset_id,
            test_ratio=test_ratio,
            val_ratio=val_ratio,
            min_train_rows=min_train_rows,
            min_test_rows=min_test_rows,
        )

        train_rows = split_data.train.rows
        test_rows = split_data.test.rows

        # 2. Fit feature preprocessor strictly on train rows (leakage prevention!)
        pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
        pipeline.fit(train_rows)

        # 3. Transform train and test matrices
        X_train = pipeline.transform(train_rows)
        y_train = np.array([r.target for r in train_rows], dtype=np.float64)

        X_test = pipeline.transform(test_rows)
        y_test = np.array([r.target for r in test_rows], dtype=np.float64)

        # 4. Fit model
        model = ShipmentDelayModel(
            model_id=model_id,
            model_version=self._model_version,
            alpha=self._alpha,
            random_seed=self._random_seed,
            organization_id=organization_id,
        )
        model.fit(X_train, y_train)

        # 5. Evaluate on test set
        metrics = model.evaluate(X_test, y_test)

        # 6. Validate model
        ModelValidator.validate_model(model=model, X_test=X_test, y_test=y_test, metrics=metrics)

        # 7. Build metadata
        metadata = MLModelMetadata(
            model_id=model_id,
            model_family=ModelFamily.SHIPMENT_DELAY,
            model_version=self._model_version,
            task_type=TaskType.REGRESSION,
            target=SHIPMENT_DELAY_SCHEMA.target_name,
            feature_names=pipeline.get_feature_schema().feature_names,
            feature_schema_fingerprint=pipeline.get_feature_schema().schema_fingerprint,
            training_dataset_fingerprint=split_data.train.dataset_fingerprint,
            training_timestamp=datetime.now(timezone.utc),

            preprocessing_version=pipeline.get_feature_schema().version,
            hyperparameters={"alpha": self._alpha, "random_seed": self._random_seed},
            validation_status="VALIDATED",
            metrics=metrics,
            artifact_fingerprint="temporary_placeholder",
            organization_id=organization_id,
            is_production=True,
        )
        model.set_metadata(metadata)

        # 8. Save artifact
        artifact, saved_path = ArtifactManager.save_artifact(
            model=model,
            feature_pipeline=pipeline,
            metadata=metadata,
            artifact_dir=self._artifact_dir,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        MLObservability.emit_training_event(
            action="ML_MODEL_TRAINED",
            organization_id=organization_id,
            model_id=model_id,
            metrics=metrics.model_dump(),
            duration_ms=duration_ms,
        )

        return model, pipeline, artifact, saved_path
