"""RiskWise 2.0 Machine Learning Subsystem (Phase 11).

Provides safe, deterministic, provider-independent ML architecture:
- Reusable contracts, schemas, and metrics
- Temporal data leakage protection
- Deterministic feature engineering pipelines
- Shipment delay regression model
- Time-aware training pipeline & artifact management
- In-memory & artifact-backed model registry
- Production-oriented inference service integrated with PredictionAgent
"""

from app.ml.config import MLConfig, ml_config
from app.ml.contracts import (
    DatasetSplit,
    FeatureSchema,
    FeatureSpec,
    FeatureType,
    MLModelMetadata,
    ModelArtifact,
    ModelFamily,
    ModelMetrics,
    ModelStatus,
    TaskType,
    compute_artifact_fingerprint,
    compute_schema_fingerprint,
)
from app.ml.datasets import (
    DatasetRow,
    DatasetSplitData,
    DatasetValidator,
    ShipmentDatasetBuilder,
    ValidatedDataset,
    compute_dataset_fingerprint,
)
from app.ml.errors import (
    DataLeakageError,
    DatasetValidationError,
    FeatureEngineeringError,
    FeatureSchemaError,
    InsufficientTrainingDataError,
    MLError,
    MLTenantIsolationError,
    MLValidationError,
    ModelArtifactError,
    ModelInferenceError,
    ModelRegistryError,
    ModelTrainingError,
    ModelValidationError,
    PredictionInputError,
    PredictionOutputValidationError,
)
from app.ml.features import (
    BaseFeaturePipeline,
    SHIPMENT_DELAY_FEATURE_SPECS,
    SHIPMENT_DELAY_SCHEMA,
    SUPPORTED_TRANSPORT_MODES,
    ShipmentDelayFeaturePipeline,
)
from app.ml.inference import MLPredictionService
from app.ml.models import BasePredictionModel, ShipmentDelayModel
from app.ml.observability import MLObservability
from app.ml.registry import ModelRegistry, default_model_registry
from app.ml.training import ArtifactManager, ModelValidator, ShipmentDelayTrainingPipeline

__all__ = [
    # Config
    "MLConfig",
    "ml_config",
    # Contracts
    "TaskType",
    "ModelFamily",
    "DatasetSplit",
    "ModelStatus",
    "FeatureType",
    "FeatureSpec",
    "FeatureSchema",
    "ModelMetrics",
    "MLModelMetadata",
    "ModelArtifact",
    "compute_artifact_fingerprint",
    "compute_schema_fingerprint",
    # Datasets
    "DatasetRow",
    "DatasetSplitData",
    "ValidatedDataset",
    "compute_dataset_fingerprint",
    "DatasetValidator",
    "ShipmentDatasetBuilder",
    # Features
    "BaseFeaturePipeline",
    "ShipmentDelayFeaturePipeline",
    "SHIPMENT_DELAY_SCHEMA",
    "SHIPMENT_DELAY_FEATURE_SPECS",
    "SUPPORTED_TRANSPORT_MODES",
    # Models
    "BasePredictionModel",
    "ShipmentDelayModel",
    # Training & Artifacts
    "ArtifactManager",
    "ModelValidator",
    "ShipmentDelayTrainingPipeline",
    # Registry & Inference
    "ModelRegistry",
    "default_model_registry",
    "MLPredictionService",
    # Observability
    "MLObservability",
    # Errors
    "MLError",
    "MLValidationError",
    "DatasetValidationError",
    "InsufficientTrainingDataError",
    "FeatureSchemaError",
    "FeatureEngineeringError",
    "DataLeakageError",
    "ModelTrainingError",
    "ModelValidationError",
    "ModelArtifactError",
    "ModelRegistryError",
    "ModelInferenceError",
    "PredictionInputError",
    "PredictionOutputValidationError",
    "MLTenantIsolationError",
]
