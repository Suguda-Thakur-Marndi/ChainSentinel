# RiskWise 2.0 — Phase 11 Machine Learning Architecture & Shipment Delay Prediction

## 1. Executive Summary & Objective

Phase 11 introduces a safe, deterministic, provider-independent Machine Learning (ML) layer into RiskWise 2.0. The system establishes a reusable ML architecture capable of supporting multiple predictive capabilities across supply chain risk management while delivering the first production-oriented ML capability: **Shipment Delay Prediction**.

The architecture enforces strict invariants:
- **Prediction Authority Invariant**: ML models generate predictions. The existing `PredictionAgent` and `PredictionService` (`PredictionResult`) remain solely authoritative for exposing predictions to the LangGraph multi-agent decision graph.
- **Downstream Explanations**: Anthropic Claude (via AWS Bedrock from Phase 10) remains strictly downstream and explanatory. Claude explains authoritative ML prediction results, but is never permitted to calculate, fabricate, or override predictions.
- **Zero Fabrication Policy**: When operational data is insufficient, the system fails safely, yielding `PredictionStatus.NOT_AVAILABLE` via `UnavailablePredictionService`. The system never invents fake training rows, synthetic test metrics, calibrated probabilities, or ungrounded confidence scores.
- **Strict Temporal Data Leakage Defense**: The feature pipeline and dataset validator explicitly prohibit and reject post-outcome features that would only be known after shipment outcome.
- **Tenant Isolation**: Multi-tenancy is enforced end-to-end across datasets, feature engineering, model artifacts, model registry, and inference services.

---

## 2. End-to-End System Architecture

The authoritative prediction lifecycle flows deterministically through the following layers:

```
Historical Operational Data (Shipments, Events, Routes, Incidents)
                          ↓
          ShipmentDatasetBuilder & DatasetValidator
          (Data Quality, Integrity, Non-Leakage & Tenant Checks)
                          ↓
              Time-Aware Train / Val / Test Split
                 (max(t_train) <= min(t_test))
                          ↓
           ShipmentDelayFeaturePipeline (Fit on Train)
         (Categorical Encoding, Imputation, MinMax Scaling)
                          ↓
            ShipmentDelayModel (Ridge Regularization)
                          ↓
         ModelValidator (Non-finite Checks, MAE / RMSE)
                          ↓
        ArtifactManager (SHA-256 Fingerprint, Tamper Defense)
                          ↓
        ModelRegistry (Tenant Isolation & Active Versioning)
                          ↓
                    MLPredictionService
             (Empirical RMSE Uncertainty Intervals)
                          ↓
            AUTHORITATIVE PredictionResult (Phase 9)
                          ↓
               LangGraph Prediction Agent Node
                          ↓
       Claude Prediction Explanation Service (Phase 10)
```

---

## 3. Shipment Delay Prediction Model

### 3.1 Domain Context
Shipment delays in modern supply chains propagate through downstream manufacturing, inventory holding, and customer service level agreements. Estimating transit delays early in a shipment's lifecycle allows risk mitigation, supplier alerts, and contingency planning.

### 3.2 Target Definition
- **Target Variable**: `delay_minutes` (continuous numeric, units: minutes).
- **Physical Boundary**: `delay_minutes >= 0.0`. Shipments arriving on schedule or early have a recorded delay of `0.0`. Negative delays represent invalid or corrupted operational records and are rejected during dataset validation.
- **Deterministic Derivation**: `delay_minutes = max(0.0, (actual_delivery_timestamp - planned_delivery_timestamp) / 60)`. In historical training datasets, this value is extracted from completed milestone events.

### 3.3 Feature Family & Preprocessing
The feature pipeline utilizes 12 operational features known prior to shipment departure or milestone cut-off:

| Feature Name | Type | Source Entity | Transformation / Encoding | Leakage Defense |
|---|---|---|---|---|
| `transport_mode` | Categorical | Shipment | One-hot encoded (`AIR`, `OCEAN`, `ROAD`, `RAIL`) | Known at booking |
| `carrier_id` | Categorical | Shipment / Carrier | Frequency / Hash encoding | Known at dispatch |
| `origin_country` | Categorical | Route / Location | Categorical mapping | Static attribute |
| `destination_country` | Categorical | Route / Location | Categorical mapping | Static attribute |
| `planned_duration_hours` | Numeric | Shipment Schedule | MinMax normalized | Planned transit schedule |
| `route_distance_km` | Numeric | Route | MinMax normalized | Static route distance |
| `delay_events_count` | Numeric | Milestone Events | Count of pre-departure exception events | Counted strictly before cutoff |
| `origin_weather_severity`| Numeric | External Weather | Severity level (0.0 to 5.0) | Weather at departure |
| `port_congestion_index` | Numeric | Port Logistics | Congestion index (0.0 to 10.0) | Port status at dispatch |
| `carrier_disruption_count`| Numeric | Incidents | Active disruptions for carrier | Recorded before dispatch |
| `is_weekend_departure` | Numeric | Schedule | Binary indicator (0.0 or 1.0) | Derived from dispatch timestamp |
| `departure_hour` | Numeric | Schedule | Hour of day (0.0 to 23.0) | Known at dispatch |

### 3.4 Temporal Data Leakage Defense
Post-outcome fields that occur after shipment arrival are strictly prohibited from features. Prohibited columns include:
- `actual_delivery_time` / `delivery_timestamp`
- `actual_arrival_time` / `final_arrival_time`
- `final_delivery_delay` / `post_outcome_delay`
- `delivered_status` / `delivered`
- `post_delivery_corrective_action`
- `carrier_penalty_applied`

The `DatasetValidator` inspects both the `FeatureSchema` definitions and the raw dataset dictionary keys. Any occurrence of these fields immediately raises a `DataLeakageError`, aborting model training.

---

## 4. Dataset Architecture & Quality Validation

### 4.1 Dataset Contract (`ValidatedDataset`)
Datasets are represented by strongly-typed, immutable Pydantic models with `extra="forbid"`:
- `dataset_id`: Unique dataset identifier.
- `organization_id`: Tenant identifier guaranteeing isolation.
- `feature_names`: Canonical list of feature names.
- `target_name`: Target variable name (`delay_minutes`).
- `row_count`: Number of valid observations.
- `dataset_version`: Semantic version string.
- `dataset_fingerprint`: SHA-256 hash computed over canonical, timestamp-sorted records.

### 4.2 Data Quality Validation Checks
Before any dataset can be used for training, the `DatasetValidator` verifies:
1. **Minimum Row Threshold**: Datasets must contain at least `min_training_rows` (default: 20 rows). Smaller datasets raise `InsufficientTrainingDataError`.
2. **Tenant Isolation**: Every observation row must match the specified `organization_id`. Mixed tenants raise `MLTenantIsolationError`.
3. **Target Validity**: Training observations must have non-null, finite targets (`target >= 0.0` for `delay_minutes`).
4. **Duplicate Record Detection**: Duplicate `record_id` values within the dataset raise `DatasetValidationError`.
5. **Feature Completeness & Type Checking**: Numeric features must be finite numbers; categorical features must be strings; boolean indicators must be valid binary values.

### 4.3 Time-Aware Partitioning (`ShipmentDatasetBuilder`)
Random k-fold splitting violates temporal causality in time-series operational data. `ShipmentDatasetBuilder.time_aware_split` sorts records chronologically by timestamp and partitions:
- **Train Split**: Chronologically earlier records (e.g., first 70-80%).
- **Validation Split**: Intermediate records (e.g., 10-15%).
- **Test Split**: Chronologically latest records (e.g., 15-20%).

Invariant: `max(t_train) <= min(t_val) <= min(t_test)`.

---

## 5. Model Architecture & Training Pipeline

### 5.1 Provider-Independent Model Abstraction (`BasePredictionModel`)
To prevent the domain from coupling directly to specific scikit-learn classes, `BasePredictionModel` defines the abstract interface:
- `fit(X: np.ndarray, y: np.ndarray) -> BasePredictionModel`
- `predict(X: np.ndarray) -> np.ndarray`
- `predict_single(x: np.ndarray) -> float`
- `evaluate(X: np.ndarray, y: np.ndarray) -> ModelMetrics`
- `validate_prediction(raw_value: float) -> float`

### 5.2 Baseline Model: `ShipmentDelayModel`
The baseline implementation utilizes L2-regularized Ridge Regression (`sklearn.linear_model.Ridge`):
- **Deterministic**: Controlled by fixed `random_seed` (default: 42).
- **Physical Non-Negative Delay Constraint**: `validate_prediction` clamps any negative regression output to `0.0`, reflecting that negative transit delay is physically invalid in this context.
- **Lightweight & Stable**: Trains in milliseconds on standard CPU environments without heavy deep learning or GPU dependencies.

### 5.3 Model Metrics
Evaluations compute standard, non-fabricated regression metrics:
- **MAE** (Mean Absolute Error): Average absolute error in minutes.
- **RMSE** (Root Mean Squared Error): Square root of mean squared error in minutes.
- **Metric Integrity**: If evaluation data is unavailable, `ModelMetrics(is_calculated=False)` is returned. Negative metrics or fabricated accuracy figures are explicitly rejected.

---

## 6. Model Artifacts, Security & Model Registry

### 6.1 Safe Artifact Persistence (`ArtifactManager`)
Serialized artifacts bundle:
1. Fitted prediction model.
2. Fitted feature transformation pipeline.
3. Strongly-typed `MLModelMetadata`.
4. Artifact SHA-256 fingerprint.

Security Defenses:
- **SHA-256 Integrity Verification**: Before deserialization, the raw byte stream is hashed and verified against the expected fingerprint.
- **Trailing Byte Tampering Defense**: Prevents malicious executable payloads appended to serialized streams. The deserializer reads via `io.BytesIO` and verifies `bio.tell() == len(raw_bytes)`.
- **Path Traversal Defense**: All artifact resolution verifies that destination paths remain strictly within the configured storage directory. Model IDs containing directory separators (`/`, `\`, `..`) are rejected with `ModelArtifactError`.
- **Trusted Source Requirement**: Serialized artifacts are only loaded from the configured local registry path.

### 6.2 Model Registry (`ModelRegistry`)
`ModelRegistry` provides in-memory caching and persistent artifact loading with tenant isolation:
- `register_model(model, pipeline, metadata) -> str`
- `get_model(model_id, organization_id) -> Tuple[Model, Pipeline, Metadata]`
- `get_active_model(family, organization_id) -> Tuple[Model, Pipeline, Metadata]`
- `list_models(family, organization_id) -> List[MLModelMetadata]`

If Organization A attempts to load Organization B's registered model, `MLTenantIsolationError` is raised.

---

## 7. Inference Service & Prediction Integration

### 7.1 `MLPredictionService`
`MLPredictionService` implements the existing `BasePredictionService` interface:
1. **Model Discovery**: Queries `ModelRegistry` for the active model for the request's `organization_id`.
2. **Safe Fallback**: If no active model exists for the tenant, returns `PredictionResult(status=PredictionStatus.NOT_AVAILABLE)` with explanatory limitation records.
3. **Feature Transformation**: Converts input `PredictionFeature` objects into the model's feature vector using the fitted pipeline. Missing features are imputed with pre-fit training medians.
4. **Model Execution**: Runs model inference and validates that output is finite and non-negative.
5. **Empirical Uncertainty Grounding**: Computes prediction intervals `[prediction - 1.96 * RMSE, prediction + 1.96 * RMSE]` derived directly from the test set RMSE. `confidence_score` is explicitly set to `None` because linear regression outputs are not calibrated probabilities.
6. **Authoritative Return**: Returns typed `PredictionResult` adhering strictly to the Phase 9 contract.

### 7.2 Integration with LangGraph & Claude Explanation
In `api/app/agents/prediction/node.py`:
- The LangGraph prediction node dynamically instantiates `MLPredictionService(registry=global_registry)`.
- If ML prediction succeeds, `PredictionResult` is placed into the agent state.
- Downstream in `prediction_explanation_node`, `ClaudePredictionExplanationService` takes the authoritative `PredictionResult` and generates contextual explanations for supply chain analysts. Claude never calculates or alters predictions.

---

## 8. Database, API, and Frontend Boundaries

- **Database Invariant**: Exactly **34 tables** remain in `Base.metadata.tables`. **0 migrations** and **0 schema changes** were made in Phase 11. Model artifacts and registry metadata are persisted in the configured storage layer without requiring unnecessary database tables.
- **API Invariant**: Exactly **60 OpenAPI routes** remain. No public administrative endpoints (`/ml/train`, `/ml/artifacts`) were exposed. Training and model registration remain internal services.
- **Frontend Invariant**: `web` was not modified (0 changes).

---

## 9. Future Model Families on Roadmap

Phase 11 establishes the reusable foundation. Future phases will extend the registry to:
1. **Supplier Risk Model**: Classifying supplier default and ESG risk.
2. **Disruption Prediction Model**: Multimodal event impact likelihood.
3. **Shipment Delay Model**: Implemented in Phase 11 (`ShipmentDelayModel`).
4. **Demand Forecasting Model**: Predicting order volume surges.
5. **Stockout Prediction Model**: Inventory depletion probability.

---

## 10. Operational Readiness & Real Data Notice

> **IMPORTANT NOTICE REGARDING PRODUCTION TRAINING**:
> Phase 11 implements full model training readiness, dataset validation, and inference pipelines. In testing and continuous integration, deterministic synthetic fixtures are used to test contracts, leakage defense, and mathematical algorithms.
>
> Production model training requires a sufficient volume of validated historical shipment milestone data (minimum 20 records per tenant). When operational data is not yet available for a tenant, the system operates in its valid, verified fallback state: returning `PredictionStatus.NOT_AVAILABLE` without fabricating predictions.
