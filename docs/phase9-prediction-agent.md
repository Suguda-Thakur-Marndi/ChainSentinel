# Phase 9 Step 6 — Prediction Agent Integration

## 1. Objective

The Prediction Agent serves as the typed orchestration boundary connecting upstream multi-agent analysis (`Research Agent` $\rightarrow$ `Risk Agent`) with ML prediction capabilities in RiskWise 2.0.

It coordinates:
1. Extraction of strongly typed, bounded features from authoritative `RiskAssessment` references, verified `AgentFinding` records, and operational context.
2. Construction and validation of a typed `PredictionRequest`.
3. Invocation of an abstract `BasePredictionService`.
4. Validation and boundary-checking of prediction outputs.
5. Updating exclusively `PREDICTION`-owned state fields in `AgentGraphState`.
6. Emission of structured observability and telemetry events without side effects or model hallucinations.

---

## 2. Architecture & Pipeline Position

The pipeline orchestration flow is:

$$\text{Research Agent} \longrightarrow \text{Risk Agent} \longrightarrow \text{Prediction Agent} \longrightarrow (\text{future Scenario Agent})$$

```
+-----------------------------------------------------------------------------------+
| LangGraph Pipeline                                                                |
|                                                                                   |
|  [ START ]                                                                        |
|      │                                                                            |
|      ▼                                                                            |
|  [ initialization_node ]                                                          |
|      │                                                                            |
|      ▼                                                                            |
|  [ research_node ] ───────► (Produces RAGEvidenceBundle, AgentFinding list)      |
|      │                                                                            |
|      ▼                                                                            |
|  [ risk_node ] ───────────► (Invokes Phase 7 BaselineRiskEngine, sets assessment) |
|      │                                                                            |
|      ▼                                                                            |
|  [ prediction_node ] ─────► (Extracts features, invokes BasePredictionService,    |
|      │                       writes prediction_id/reference/result)               |
|      ▼                                                                            |
|  [ termination_node ]                                                             |
|      │                                                                            |
|      ▼                                                                            |
|   [ END ]                                                                         |
+-----------------------------------------------------------------------------------+
```

### Architectural Principles
- **Orchestration Boundary Only**: The Prediction Agent is NOT an ML training platform, feature store, serving cluster, or inference engine.
- **Phase 7 Risk Engine Invariant**: The Prediction Agent consumes authoritative `RiskAssessment` references but NEVER recalculates, overrides, or alters risk scores, levels, or factors.
- **Phase 8 RAG Grounding Invariant**: The Prediction Agent consumes verified evidence references but NEVER converts raw prose into numeric ML features without explicit deterministic mappings.
- **Fail-Closed Default**: In the absence of a deployed production ML model, the Prediction Agent reports `status="NOT_AVAILABLE"` and records a `PREDICTION_MODEL_UNAVAILABLE` limitation. It NEVER invents fake predictions.

---

## 3. Supported Prediction Type

For Phase 9 Step 6, the single supported prediction type is:
- **`PredictionType.SHIPMENT_DELAY`**
  - **Primary target**: `delay_minutes`
  - **Unit**: `"minutes"`
  - **Value constraints**: Finite float $\ge 0.0$

Future extensibility may encompass supplier disruptions, demand surges, or stockouts, but these are strictly out of scope for Step 6.

---

## 4. PredictionRequest Contract

The `PredictionRequest` defines the typed boundary passed into any `BasePredictionService`:

```python
class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_id: str
    organization_id: str
    prediction_type: PredictionType = PredictionType.SHIPMENT_DELAY
    target: str = "delay_minutes"
    shipment_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    risk_assessment_reference: Optional[Dict[str, Any]] = None
    evidence_bundle_id: Optional[str] = None
    features: List[PredictionFeature] = Field(default_factory=list)
    prediction_horizon_hours: Optional[float] = None
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    correlation_id: Optional[str] = None
    trace_id: Optional[str] = None
```

### Invariants:
- `extra="forbid"`: strictly rejects client-injected `predicted_value`, arbitrary model output, probability estimates, or risk scores.
- `validate_tenant_consistency`: fails closed immediately if any feature or assessment reference belongs to a different `organization_id`.
- Finite horizon: non-finite (`NaN`, `inf`) or negative horizons are rejected.

---

## 5. PredictionResult Contract

The `PredictionResult` captures structured inference outputs:

```python
class PredictionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    prediction_id: str
    organization_id: str
    prediction_type: PredictionType = PredictionType.SHIPMENT_DELAY
    target: str = "delay_minutes"
    predicted_value: Optional[float] = None
    unit: str = "minutes"
    uncertainty: Optional[PredictionUncertainty] = None
    model_metadata: ModelMetadata
    feature_references: List[str] = Field(default_factory=list)
    evidence_references: List[str] = Field(default_factory=list)
    risk_assessment_reference: Optional[str] = None
    limitations: List[AgentLimitation] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    status: str = PredictionStatus.COMPLETED.value
    created_by_node: str = "prediction_agent"
    evaluated_at: datetime
```

### Invariants:
- If `status == "COMPLETED"`, `predicted_value` must be a finite float $\ge 0.0$.
- If `status in ("NOT_AVAILABLE", "INSUFFICIENT_FEATURES", "FAILED")`, `predicted_value` is `None`.
- Prohibits secrets or credentials in `provenance`.

---

## 6. Feature Contract (`PredictionFeature`)

```python
class PredictionFeature(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    feature_name: str
    value: Union[float, int, str, bool]
    unit: Optional[str] = None
    source: str
    source_type: str
    timestamp: Optional[datetime] = None
    evidence_references: List[str] = Field(default_factory=list)
    organization_id: str
    provenance: Dict[str, Any] = Field(default_factory=dict)
```

### Deterministic Feature Transformations:
| Upstream Source | Feature Name | Unit | Type | Transformation Rule |
| :--- | :--- | :--- | :--- | :--- |
| `RiskAssessment.risk_score` | `risk_composite_score` | score | float | Direct float conversion $[0.0, 100.0]$ |
| `RiskAssessment.risk_level` | `risk_level_severity` | rank | int | Map: `LOW` $\rightarrow 1$, `MEDIUM` $\rightarrow 2$, `HIGH` $\rightarrow 3$, `CRITICAL` $\rightarrow 4$ |
| `RiskAssessment.factor_count` | `risk_factor_count` | count | int | Direct integer count $\ge 0$ |
| Structured Finding: Port/Congestion | `port_disruption_detected` | binary | float | $1.0$ if category contains `PORT` or `CONGESTION`, else $0.0$ |
| Structured Finding: Logistics/Delay | `logistics_delay_detected` | binary | float | $1.0$ if category contains `LOGISTICS` or `DELAY`, else $0.0$ |
| Structured Finding: Weather/Storm | `weather_disruption_detected` | binary | float | $1.0$ if category contains `WEATHER` or `STORM`, else $0.0$ |
| Structured Finding: Confidence | `disruption_confidence_avg` | ratio | float | Arithmetic mean of finding confidence scores $[0.0, 1.0]$ |
| Operational Inputs | `scheduled_transit_hours` | hours | float | Validated positive transit duration |

---

## 7. Feature Validation

- Finite numeric checks: `math.isnan(v)` or `math.isinf(v)` immediately raises `FeatureValidationError`.
- Non-empty tenant identity: `organization_id` must be non-empty string.
- Provenance safety: secret key patterns (`api_key`, `token`, `password`, `bearer`, `private_key`) are rejected.
- Unit validation: units must be standard strings (`minutes`, `hours`, `score`, `rank`, `binary`, `ratio`).

---

## 8. Prediction Service Abstraction

```python
class BasePredictionService(ABC):
    @abstractmethod
    def predict(self, request: PredictionRequest) -> PredictionResult:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_model_metadata(self) -> ModelMetadata:
        raise NotImplementedError
```

### Implementations:
1. **`UnavailablePredictionService`**: Production default. Returns `is_available() = False`, `status="NOT_AVAILABLE"`, `predicted_value=None`, and registers `LimitationCategory.PREDICTION_MODEL_UNAVAILABLE`.
2. **`DeterministicMockPredictionService`**: Strictly for automated testing. Explicitly flagged as `is_production=False` (`NOT_PRODUCTION`). Produces deterministic, reproducible delays from input features with uncertainty intervals.

---

## 9. Production Model Status

- **Status**: `NOT_DEPLOYED` / `UNAVAILABLE`.
- **Handling**: As mandated by Sections 10 & 11, RiskWise 2.0 does not contain a pre-existing shipment delay ML model. Rather than fabricating fake values, the system safely reports `status="NOT_AVAILABLE"` and passes through downstream nodes.

---

## 10. Model Metadata & Provenance

```python
class ModelMetadata(BaseModel):
    model_name: str
    model_version: str
    model_type: Optional[str] = None
    feature_version: Optional[str] = None
    training_data_version: Optional[str] = None
    is_production: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

Every prediction result preserves full model metadata to ensure auditability across training cycles and environments.

---

## 11. Uncertainty Semantics

```python
class PredictionUncertainty(BaseModel):
    prediction_interval: Optional[Tuple[float, float]] = None
    confidence_interval: Optional[Tuple[float, float]] = None
    standard_error: Optional[float] = None
    confidence_score: Optional[float] = None
    method: str = "UNSPECIFIED"
```

### Semantic Rules:
- A `confidence_score` is an uncalibrated score in $[0.0, 1.0]$. It is **never** described as a statistical probability unless empirical calibration is verified.
- Prediction interval: bounds must satisfy $\text{lower} \le \text{upper}$, with finite values.
- If interval spread exceeds $1.5 \times \text{predicted\_value}$, an explicit `LimitationCategory.HIGH_UNCERTAINTY` is attached.

---

## 12. Research Agent Integration

- Preserves finding IDs, evidence IDs, and citation references.
- Transforms structured finding categories to binary indicator features.
- Strictly avoids arbitrary natural language processing or LLM text parsing into numeric values.

---

## 13. Risk Engine Boundary

- Consumes `RiskAssessment` as input for `risk_composite_score`, `risk_level_severity`, and `risk_factor_count`.
- Phase 7 Risk Engine remains the single source of truth for risk.
- Prediction Agent NEVER recalculates risk, changes weights, or updates risk scores.

---

## 14. State Ownership

The Prediction Agent is authorized to write ONLY `PREDICTION`-owned fields:
- `prediction_id`: Unique identifier of prediction result.
- `prediction_reference`: Compact dictionary summary (`prediction_id`, `status`, `target`, `predicted_value`, `unit`, `model_name`, `model_version`).
- `prediction_result`: Full serialized `PredictionResult`.
- Append-only operational fields: `structured_findings`, `limitations`, `findings`, `current_stage`, `current_node`, `step_count`.

Enforced authoritatively by `validate_state_update(..., writer_node_id="prediction_agent", writer_stage=AgentStage.PREDICTION)`.

---

## 15. Tenant Isolation

All components enforce multi-tenant separation:
$$\text{state.organization\_id} == \text{request.organization\_id} == \text{feature.organization\_id} == \text{assessment.organization\_id} == \text{result.organization\_id}$$

Any mismatch triggers an immediate `PredictionTenantIsolationError` (fail closed, non-retryable).

---

## 16. Security & Credential Scrubbing

- Rejection of secret keys: `api_key`, `private_key`, `token`, `password`, `secret`, `credentials`, `authorization`.
- Rejection of bearer tokens and secret values in metadata and provenance.
- Zero credential leakage into LangGraph state or logs.

---

## 17. Idempotency

Deterministic prediction IDs are generated via UUIDv5 using `RAG_UUID_NAMESPACE`:
```python
generate_deterministic_prediction_id(
    organization_id=org_id,
    prediction_type="SHIPMENT_DELAY",
    target_reference=shipment_id,
    feature_fingerprint=feature_fingerprint,
    model_name=model_name,
    model_version=model_version,
)
```
Volatile fields (timestamps, trace IDs, random UUIDs) are strictly excluded from the fingerprint.

---

## 18. Error Handling & Recovery

| Error Class | Classification | Cause | Behavior |
| :--- | :--- | :--- | :--- |
| `InvalidPredictionRequestError` | `NON_RETRYABLE` | Missing fields, bad types | Fail closed, no retry |
| `PredictionTenantIsolationError` | `NON_RETRYABLE` | Cross-tenant data detected | Fail closed, audit log |
| `FeatureValidationError` | `NON_RETRYABLE` | Non-finite values, bad units | Fail closed, no retry |
| `ModelUnavailableError` | `NON_RETRYABLE` | Model service unreachable | Report limitation |
| `ModelTimeoutError` | `RETRYABLE` | Transient inference timeout | Retryable by graph |
| `ModelExecutionError` | `RETRYABLE` | Infrastructure failure | Retryable by graph |
| `InvalidModelOutputError` | `NON_RETRYABLE` | Negative delay, NaN, Inf | Fail closed, reject update |

---

## 19. Observability & Telemetry

Every execution of `prediction_node` emits a structured `NodeExecutionTelemetry` payload in a guaranteed `finally` block:
- `node_name`: `"prediction_agent"`
- `status`: `"SUCCESS"` or `"FAILED"`
- `duration_ms`: High-precision monotonic execution time
- `error_code`: Populated on exception
- `step_count`: Graph progress tracker

---

## 20. LangGraph Node Registration

- Registered in `apps/api/app/agents/nodes.py`:
  - `PREDICTION_NODE_CONTRACT`
  - `prediction_node`
- Stage: `AgentStage.PREDICTION`
- Side effect: `ToolSideEffectType.READ_ONLY`
- Required roles: `["analyst", "admin"]`
- Requires evidence: `True`

---

## 21. Database Impact

- **Zero new tables**: 34 PostgreSQL tables remain completely unchanged.
- **Zero migrations**: 0 unauthorized migrations created.

---

## 22. API Impact

- **Zero public API changes**: 60 paths, 96 operations, 104 schemas preserved.
- The Prediction Agent is strictly an internal orchestration layer.

---

## 23. Test Coverage

Comprehensive test suite in `apps/api/tests/test_phase9_prediction_agent.py`:
- **108 tests** across 11 groups:
  1. PredictionRequest Contracts (10 tests)
  2. PredictionFeature Contracts (12 tests)
  3. ModelMetadata & Uncertainty (10 tests)
  4. PredictionResult Contracts (10 tests)
  5. Prediction Services & Default Unavailable (10 tests)
  6. Feature Extraction & Risk Integration (10 tests)
  7. PredictionAgent Orchestration (10 tests)
  8. State Ownership & Write Boundaries (10 tests)
  9. LangGraph Node & Pipeline Execution (10 tests)
  10. Security & Multi-Tenant Isolation (8 tests)
  11. Non-Action Safety & Risk Preservation (8 tests)

---

## 24. Explicit Non-Goals

- ❌ No Scenario Agent, Decision Agent, Action Agent, or Verification Agent.
- ❌ No approval workflow execution.
- ❌ No ML training platform, feature store, or model serving clusters.
- ❌ No Claude, Bedrock, or LLM text generation.
- ❌ No autonomous actions, shipment rerouting, carrier communications, or inventory mutations.
