# Phase 10 Step 6 — Claude Prediction Analysis & Explanation Layer

## Executive Summary

Phase 10 Step 6 introduces Claude as a controlled, strictly grounded explanation layer around the authoritative RiskWise 2.0 Prediction Agent and Prediction Services (`BasePredictionService`, `UnavailablePredictionService`, and `DeterministicMockPredictionService`).

> **CORE PRINCIPLE:**
> **"Claude explains authoritative PredictionResult values.**
> **Claude does not generate or modify predictions."**

The authoritative predictive model or heuristic service determines **WHAT** the prediction is (forecasted target, predicted delay value, unit, horizon, uncertainty intervals, model metadata, and status). Claude explains **WHAT THE PREDICTION MEANS** in human-comprehensible terms, contextualizing it with authoritative upstream RiskAssessments, ResearchResults, and validated RAG evidence.

---

## 1. Architectural Pipeline

```
ResearchResult (Phase 9/10 Step 3)
      ↓
RiskAssessment (Phase 9/10 Step 4)
      ↓
BasePredictionService / Model (Authoritative)
      ↓
AUTHORITATIVE PredictionResult (PredictionAgent)
      ↓
Claude Prediction Explanation Service (ClaudePredictionExplanationService)
      ↓
Validated PredictionExplanationResult (Stored in prediction_explanation)
      ↓
Downstream Scenario / Decision / Human Review (Phase 9/10 Step 5 & future)
```

The downstream pipeline consumes the authoritative `PredictionResult`, not the Claude explanation. Downstream scenario evaluation and decision logic retain direct mathematical dependency on the authoritative prediction.

---

## 2. Authority Boundary & Invariants

The Prediction Agent and `BasePredictionService` retain exclusive authority over:
- `prediction_id`: Unique deterministic identifier
- `prediction_reference`: Authoritative reference dict
- `prediction_type`: Domain prediction type (e.g., `SHIPMENT_DELAY`)
- `target`: Target variable (e.g., `delay_minutes`)
- `predicted_value`: Numeric prediction value
- `unit`: Measurement unit (e.g., `minutes`)
- `prediction_horizon_hours`: Forecast horizon
- `uncertainty`: Prediction and confidence intervals, standard errors, confidence scores
- `model_metadata`: Model name, version, type, and parameters
- `status`: Execution status (`COMPLETED`, `NOT_AVAILABLE`, `FAILED`)
- `fingerprint`: Cryptographic hash of prediction payload

Claude **MUST NOT**:
1. Recalculate, alter, or override any predicted value.
2. Synthesize or invent a prediction when the model status is `NOT_AVAILABLE` or `FAILED`.
3. Fabricate confidence intervals, probabilities, standard errors, or confidence scores if absent from the authoritative prediction.
4. Fabricate machine learning performance metrics (such as MAE, RMSE, precision, recall, or accuracy) unless explicitly provided in model metadata.
5. Fabricate feature importance scores or invent feature names not present in the model's feature input.
6. Trigger simulations, optimizations, approvals, or tool calls.

---

## 3. Production Model Availability & Unavailable Prediction Handling

In production environments where no shipment-delay machine learning model is deployed, `UnavailablePredictionService` returns:
- `status`: `NOT_AVAILABLE`
- `predicted_value`: `None`
- `limitations`: Category `PREDICTION_MODEL_UNAVAILABLE`

Claude **NEVER** turns `NOT_AVAILABLE` into a synthetic prediction.
- If Claude outputs a synthetic delay (e.g., *"Predicted delay is 18 hours."*), the consistency validator detects the contradiction against `NOT_AVAILABLE` and immediately rejects the explanation.
- Valid explanations for unavailable models explicitly state that the predictive model is currently unavailable, communicate model limitations, and explain what data would be required once a model is deployed.

---

## 4. Quantitative Hallucination & Consistency Protection

`ClaudePredictionExplanationService.validate_consistency` performs automated deterministic checks:

1. **Prediction Value Consistency:**
   - Evaluates whether Claude's narrative mentions a numeric delay contradictory to the authoritative value.
   - If authoritative `delay_minutes = 240.0` and Claude claims `30.0 minutes`, the explanation is immediately rejected (`PredictionValueContradictionError`).
2. **Status Consistency:**
   - Verifies that Claude does not assert successful completion when the authoritative status is `NOT_AVAILABLE` or `FAILED` (`PredictionStatusContradictionError`).
3. **Uncertainty Authority:**
   - If the authoritative prediction lacks uncertainty (`uncertainty is None`), regex validators scan Claude's response for fabricated numeric confidence scores (e.g., `confidence score of 0.97`) or fabricated confidence intervals. Any detected fabrication triggers `PredictionUncertaintyFabricationError`.
4. **Model Performance Metrics Protection:**
   - Scans for hallucinated ML evaluation metrics (MAE, RMSE, accuracy, ROC-AUC, precision, recall) when not supplied in authoritative `model_metadata.metrics`. Detected fabrications raise `PredictionModelMetricsFabricationError`.
5. **Feature Grounding:**
   - Validates that every feature referenced in `feature_explanations` was actually supplied in the authoritative prediction's input feature vector. Unknown features trigger `PredictionFeatureFabricationError`.

---

## 5. Grounding & Citation Validation

- **Evidence Integrity:** Every citation in Claude's explanation must match an evidence ID present in the authoritative `PredictionExplanationInput.available_evidence_ids` (harvested from upstream `risk_assessment`, `research_result`, and `evidence_references`).
- **Cross-Tenant Prevention:** Attempted citations to other tenant data or invented UUIDs raise `PredictionExplanationCitationIntegrityError`.
- **Factual Grounding:** All factual statements must link back to authoritative upstream artifacts.

---

## 6. Failure Isolation & Graceful Degradation

If Claude times out, is throttled, encounters an API error, or produces an invalid/contradictory explanation:
1. **The Authoritative Prediction Remains Intact:** `PredictionResult` is completely unaffected. Its `COMPLETED` or `NOT_AVAILABLE` status, numeric values, and metadata remain strictly preserved in `AgentGraphState`.
2. **Isolated Explanation State:** The explanation payload in state is assigned status `UNAVAILABLE` (on LLM timeout/error) or `INVALID` (on consistency rejection).
3. **Fail-Safe Orchestration:** In pipeline node execution, `fail_closed=False` ensures that an explanation failure logs an audit warning but never aborts the agent graph run.

---

## 7. State Ownership & Security

- **State Ownership:** In `AgentGraphState`, the field `prediction_explanation` is strictly owned by `AgentStage.PREDICTION`.
- **State Validation:** `validate_state_update` rejects attempts by Claude or the prediction node to mutate unauthorized fields such as `risk_assessment`, `scenario_result`, `decision_result`, or `approval_request`.
- **Tenant Isolation:** Rigorous verification ensures `organization_id` matches across all inputs (prediction, risk assessment, research result, evidence bundle). Any mismatch immediately raises `PredictionTenantIsolationError`.
- **No Direct Boto3 / No Tools:** The prediction layer accesses Claude exclusively through `ClaudeInvocationService` / `LLMProvider`. No direct `boto3` calls, tool executions, shell commands, or database access are permitted.

---

## 8. Observability & Audit Trail

Every explanation execution logs structured audit events via `AuditService`:
- `PREDICTION_LLM_EXPLANATION_STARTED`
- `PREDICTION_LLM_EXPLANATION_SUCCEEDED`
- `PREDICTION_LLM_EXPLANATION_FAILED` (on timeout, throttling, or API errors)
- `PREDICTION_LLM_EXPLANATION_REJECTED` (on value contradiction, invented uncertainty, or citation violations)

Audit events include tenant `organization_id`, `prediction_id`, status, trace identifiers (`trace_id`), and execution fingerprints.

---

## 9. Test Coverage & Verification

Phase 10 Step 6 is verified by **136 automated tests** in `apps/api/tests/test_phase10_step6_prediction_explanation_claude.py`, covering:
- Group A: Prediction Input Contract (Immutability, type safety)
- Group B: Immutable Snapshot Construction
- Group C: Value Authority & Anti-Tamper
- Group D: Status Authority
- Group E: Uncertainty Authority & Fabrication Defense
- Group F: Model Metadata & Metrics Fabrication Defense
- Group G: Prompt Generation & Delimitation
- Group H: Prompt Determinism
- Group I: Prompt Injection Defense
- Group J: Citation Integrity & Cross-Tenant Validation
- Group K: Grounding & Feature Verification
- Group L: Quantitative Hallucination Defense
- Group M: Unavailable Model Handling
- Group N: Invented Uncertainty Scenarios
- Group O: Invented Metrics Scenarios
- Group P: Upstream Risk Integration
- Group Q: Upstream Research Integration
- Group R: Downstream Scenario State Invariants
- Group S: Tenant Isolation
- Group T: State Ownership & Security
- Group U: Deterministic Mock Provider
- Group V: Timeout & Failure Isolation
- Group W: Retry & Resilience
- Group X: Observability & Deterministic Fingerprints
- Group Y: Audit Trail Logging
- Group Z: End-to-End Prediction Agent Node Execution
- Group AA: Mandatory Critical Tests (Sections 34–39)

---

## 10. Limitations

1. **Deterministic Mock Testing:** In local and CI test environments, tests run against `DeterministicMockLLMProvider` and `DeterministicMockPredictionService`. Real Bedrock invocation requires active AWS credentials with access to Anthropic Claude models.
2. **Text-Based Contradiction Parsing:** Value contradiction detection uses robust regex patterns to locate delay statements in Claude's unstructured narratives. While highly comprehensive, extreme paraphrasing (e.g. archaic units) could require future schema token matching.
3. **No Domain Model Deployment:** As established in Phase 9, production deployment of an ML delay model remains out-of-scope until domain training datasets are provisioned.
