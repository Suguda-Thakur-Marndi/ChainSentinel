# Phase 9 Step 5: Risk Agent Integration

## 1. Overview

The **Risk Agent** is the second operational node in the RiskWise 2.0 LangGraph multi-agent pipeline. It serves as an **orchestration and integration layer** that connects the upstream **Research Agent** (Phase 9 Step 4) to the authoritative **Phase 7 Risk Engine** (`BaselineRiskEngine`).

> [!IMPORTANT]
> **Core Architectural Rule**: The Phase 7 deterministic Risk Engine remains the **single authoritative risk calculation system**. The Risk Agent does **NOT** compute risk scores, calculate probabilities or impacts, evaluate factor contributions, or duplicate alert/recommendation logic. It strictly orchestrates the handoff and writes authoritative risk references into the graph state.

---

## 2. Architecture & Pipeline Flow

```
                      AgentGraphState
                             │
                             ▼
                    research_node()           [Phase 9 Step 4]
                             │
            writes structured_findings & evidence refs
                             │
                             ▼
                      risk_node()             [Phase 9 Step 5]
                             │
                             ├─► _extract_research_result_from_state()
                             │       Reconstructs ResearchResult from graph state
                             │
                             ├─► RiskAgentRequest validation
                             │       Validates tenant, objective, and forbids user scores
                             │
                             ├─► ResearchRiskAdapter.translate()
                             │       Maps ResearchFinding categories to NormalizedRiskSignal
                             │       Records UNSUPPORTED_MAPPING limitations for unmapped categories
                             │
                             ├─► RiskEngineAdapter.evaluate()
                             │       Builds RiskEvaluationContext (allow_partial_signals=True)
                             │       Calls BaselineRiskEngine.evaluate_full()
                             │
                             ├─► Extract RiskAgentResult
                             │       Preserves exact score, risk_level, factors, alerts, recs
                             │
                             └─► validate_state_update()
                                     Guarantees RISK_ASSESSMENT stage write ownership
```

---

## 3. Package Structure

```
api/app/agents/risk/
├── __init__.py      # Exports: risk_node, RISK_NODE_CONTRACT, RiskAgent, RiskAgentRequest, RiskAgentResult
├── contract.py      # RiskAgentRequest, RiskAgentResult, generate_deterministic_risk_request_id()
├── adapter.py       # FINDING_TO_SIGNAL_MAP, ResearchRiskAdapter, RiskEngineAdapter
├── agent.py         # RiskAgent orchestrator
├── node.py          # risk_node() LangGraph node function + RISK_NODE_CONTRACT
└── errors.py        # Error taxonomy: RiskAgentError, RiskTenantIsolationError, etc.
```

---

## 4. Static Finding-to-Signal Translation

The `ResearchRiskAdapter` applies an explicit, static lookup table to translate `ResearchFinding` categories into `NormalizedRiskSignal` domain and type tuples. **No heuristics, ML models, or inference are permitted at this boundary.**

### Lookup Table (`FINDING_TO_SIGNAL_MAP`)

| Finding Category | SignalDomain | SignalType | Notes |
|---|---|---|---|
| `PORT_DISRUPTION` | `SignalDomain.OCEAN` | `SignalType.DISRUPTION` | Port delays, terminal closures |
| `SUPPLIER_INCIDENT` | `SignalDomain.LOGISTICS` | `SignalType.DISRUPTION` | Supplier disruptions, facility downtime |
| `WEATHER_EVENT` | `SignalDomain.WEATHER` | `SignalType.DISRUPTION` | Storms, typhoons, severe weather |
| `LOGISTICS_DELAY` | `SignalDomain.LOGISTICS` | `SignalType.DELAY` | Transit and customs delays |

### Translation & Limitation Rules:
1. **UNKNOWN findings excluded**: Findings of type `FindingType.UNKNOWN` represent data gaps and produce an `UNSUPPORTED_MAPPING` limitation.
2. **Explicitly unmappable categories**: `DATA_GAP` and `UNKNOWN` are excluded and produce limitations.
3. **Unmapped categories**: Any category not in `FINDING_TO_SIGNAL_MAP` produces a structured `AgentLimitation` with category `UNSUPPORTED_MAPPING` and is excluded from engine inputs.
4. **Signal Severity Derivation**:
   - `confidence >= 0.8` → `EventSeverity.HIGH`
   - `0.5 <= confidence < 0.8` → `EventSeverity.MEDIUM`
   - `confidence < 0.5` → `EventSeverity.LOW`
5. **Quality**: Fixed to `EventQuality.PARTIAL` (research findings are derived operational signals).
6. **Provider & Source**: Deterministically set to `"research_agent"` and `"research_agent:<finding_id[:8]>"`.
7. **Zero Mappable Signals**: If all findings are unmapped, the agent returns a `RiskAgentResult` with `status="INSUFFICIENT_EVIDENCE"` and `risk_score=None` without invoking the engine.

---

## 5. Authoritative Risk Engine Adapter

The `RiskEngineAdapter` wraps Phase 7 `BaselineRiskEngine.evaluate_full()` without copying or altering any scoring logic.

### Responsibilities:
- **Build `RiskEvaluationContext`**: Populates `organization_id`, `signals`, `allow_partial_signals=True`, `scope`, `scope_entity_id`, and tracking metadata.
- **Tenant Validation**: Pre-checks that all input signals belong to the request tenant.
- **Exception Wrapping**: Catches underlying engine runtime errors and wraps them in `RiskEngineAdapterError` with `classification=RETRYABLE`.
- **Result Preservation**: Returns the raw `RiskEvaluationResult` containing:
  - Authoritative `RiskAssessment`
  - Authoritative `List[RiskAlert]`
  - Authoritative `List[RiskRecommendation]`

---

## 6. State Ownership & Boundaries

In accordance with Section 16 of the LangGraph architectural rules, the Risk Agent writes strictly to `RISK_ASSESSMENT`-owned state fields:

| Field | Written by Risk Agent | Authoritative Owner |
|---|---|---|
| `risk_assessment_id` | ✅ Yes (UUID string) | `RISK_ASSESSMENT` |
| `risk_assessment_reference` | ✅ Yes (`RiskAssessmentReference`) | `RISK_ASSESSMENT` |
| `risk_assessment` | ✅ Yes (serialized dict) | `RISK_ASSESSMENT` |
| `risk_alert_references` | ✅ Yes (`List[str]` of alert IDs) | `RISK_ASSESSMENT` |
| `recommendation_references` | ❌ No (read-only reference in findings) | `DECISION` |
| `findings` | ✅ Yes (appends risk summary metadata) | Shared operational |
| `limitations` | ✅ Yes (appends new limitations) | Shared operational |
| `warnings` | ✅ Yes (appends warnings) | Shared operational |
| `step_count` | ✅ Yes (incremented by 1) | Lifecycle |
| `current_stage` | ✅ Yes (`RISK_ASSESSMENT`) | Lifecycle |
| `current_node` | ✅ Yes (`risk_agent`) | Lifecycle |
| `organization_id` | ❌ Prohibited (immutable) | Identity |
| `run_id` | ❌ Prohibited (immutable) | Identity |
| `actor_id` | ❌ Prohibited (immutable) | Identity |
| `evidence_bundle` | ❌ Prohibited (owned by `RESEARCH`) | `RESEARCH` |
| `approval_status` | ❌ Prohibited (owned by `APPROVAL`) | `APPROVAL` |

---

## 7. Multi-Tenant Isolation

Tenant isolation is strictly enforced at 5 distinct checkpoints:
1. **`RiskAgentRequest` Model Validator**: Fails closed if `research_result.organization_id != request.organization_id`.
2. **`ResearchRiskAdapter.translate()`**: Rejects cross-tenant `ResearchResult`.
3. **`RiskEngineAdapter.evaluate()`**: Validates all signal `organization_id` fields against `request.organization_id`.
4. **`risk_node()`**: Validates `organization_id` is present and non-whitespace.
5. **`validate_state_update()`**: Prevents mutating `organization_id` in state.

All tenant violations raise `RiskTenantIsolationError` with `ErrorClassification.NON_RETRYABLE`.

---

## 8. LangGraph Node Contract (`RISK_NODE_CONTRACT`)

```python
RISK_NODE_CONTRACT = AgentNodeContract(
    node_id="risk_agent",
    name="Risk Agent",
    description="Orchestration node: translates Research findings to NormalizedRiskSignal inputs, invokes Phase 7 BaselineRiskEngine, and writes authoritative risk references.",
    stage=AgentStage.RISK_ASSESSMENT,
    is_side_effecting=False,
    side_effect_type=ToolSideEffectType.READ_ONLY,
    required_roles=["analyst", "admin"],
    requires_evidence=True,
    retryable=True,
    max_retries=3,
    timeout_seconds=120.0,
    output_keys=[
        "risk_assessment_id",
        "risk_assessment_reference",
        "risk_assessment",
        "risk_alert_references",
        "structured_findings",
        "limitations",
        "warnings",
        "findings",
        "current_stage",
        "current_node",
        "step_count",
    ],
)
```

---

## 9. Observability & Telemetry

`risk_node()` wraps execution in a single `try/except/finally` block that guarantees `AgentObservability.emit_node_telemetry()` is called on every run:
- **Success**: `status="SUCCESS"`, `duration_ms`, `step_count`, `error_code=None`.
- **Failure**: `status="FAILED"`, `duration_ms`, `step_count`, `error_code=exc.__class__.__name__`.
- Preserves `correlation_id`, `trace_id`, `run_id`, and `organization_id`.

---

## 10. Database & API Invariants

- **PostgreSQL Tables**: Exactly **34 tables** (0 migrations added, 0 schema drift).
- **Public API / OpenAPI**: Exactly **60 paths / 96 operations / 104 schemas** (zero public endpoints added).
- **Phase 7 Risk Engine Code**: **0 lines modified** (`git diff api/app/risk_engine/` is completely empty).

---

## 11. Verification & Test Coverage

### Focused Test Suite: `api/tests/test_phase9_risk_agent.py`
- **Total Tests**: 95 focused unit and integration tests.
- **Pass Rate**: 100% (95/95 passed in 1.75s).
- **Distribution**:
  - Group 1: RiskAgentRequest validation (10 tests)
  - Group 2: RiskAgentResult & authoritative score preservation (8 tests)
  - Group 3: ResearchRiskAdapter translation rules (15 tests)
  - Group 4: RiskEngineAdapter context construction & evaluate_full (10 tests)
  - Group 5: Tenant isolation boundaries & cross-tenant rejection (10 tests)
  - Group 6: State ownership & write boundaries (12 tests)
  - Group 7: Idempotency & fingerprint stability (5 tests)
  - Group 8: Authoritative alert references preservation (5 tests)
  - Group 9: Authoritative recommendation references preservation (5 tests)
  - Group 10: Graph integration & node registration (5 tests)
  - Group 11: Observability & telemetry on success and failure (5 tests)
  - Group 12: Immutability & safety constraints (5 tests)

### Full Regression Suite:
- **Total Tests**: **2125 passed, 1 skipped, 0 failed** in 71.34s.
- Zero regressions across Phase 1 through Phase 9 Step 4.

---

## 12. Explicit Non-Goals & Strict Boundaries

The following capabilities remain strictly excluded:
- ❌ No independent risk scoring algorithms
- ❌ No prediction / ML forecasting (Prediction Agent)
- ❌ No scenario generation (Scenario Agent)
- ❌ No decision generation (Decision Agent)
- ❌ No action execution or carrier communication (Action Agent)
- ❌ No simulation or Digital Twin models
- ❌ No OR-Tools optimization
- ❌ No Claude, Bedrock, or LLM text generation
