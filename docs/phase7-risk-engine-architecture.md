# Phase 7 — Risk Engine: Architecture & Contracts (Step 1)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "Phase 7 Step 1 establishes contracts and architecture.
> It does not implement the risk-scoring algorithm."

---

## 1. Overview & Phase 6 → Phase 7 Boundary

RiskWise 2.0 establishes a strict unidirectional progression for external signals entering the intelligence and decisioning system:

```
Provider Ingestion (Phase 5)
          ↓
  CanonicalExternalEvent
          ↓
Semantic Normalization (Phase 6)
          ↓
   NormalizedRiskSignal
          ↓
Risk Engine (Phase 7)
          ↓
   RiskAssessment
```

### Strict Input Boundary
The Risk Engine accepts **only** strongly typed `NormalizedRiskSignal` instances as external input.
The engine boundary strictly rejects:
- Raw provider dictionaries or unstructured JSON
- Unvalidated external text
- Phase 5 `RawEvent` payloads
- Phase 5 `CanonicalExternalEvent` instances

This boundary is enforced at both the Pydantic model validator and runtime ingestion layers, raising typed `RiskEngineInputError` (HTTP 422) if unnormalized payloads attempt to enter the evaluation context.

---

## 2. Core Contracts Architecture

### 2.1 RiskEvaluationContext
Execution context representing an evaluation run across a designated scope:
- **Tenant Scope**: Mandatory `organization_id`. Any cross-tenant signal raises `TenantMismatchError` (HTTP 403). Never silently filters cross-tenant data.
- **Identity & Tracing**: Deterministic `evaluation_id`, optional `correlation_id`, `trace_id`.
- **Temporal Context**: UTC-normalized `evaluation_time`.
- **Scope**: Scope indicator (e.g. `GLOBAL`, `SHIPMENT`, `SUPPLIER`, `PORT`, `ROUTE`), optional `scope_entity_id`, and `scope_entity_type`.
- **Signals**: Tenant-isolated list of `NormalizedRiskSignal` instances. Deduplicated at context ingestion based on Phase 6 semantic fingerprints.
- **Operational & Network Context**: Operational parameters for network nodes (shipments, suppliers, ports, routes, inventory, carriers).

### 2.2 RiskFactor
Represents a discrete contributor to composite risk evaluated by a domain factor evaluator:
- `factor_id`: Deterministic UUIDv5 identifier based on tenant, factor type, and sorted evidence identifiers.
- `factor_type`: Semantic categorization (e.g., `WEATHER_HAZARD`, `PORT_CONGESTION`).
- `domain`: Aligned with Phase 6 `SignalDomain` (`WEATHER`, `ROAD`, `OCEAN`, `AIR`, `RAIL`, `LOGISTICS`, `INTELLIGENCE`, `GENERAL`).
- `name` & `description`: Structured human-readable summary.
- `contribution`: Bounded float placeholder `[0.0, 1.0]` representing relative normalized weight (without committing to numerical formulas).
- `severity`: Standardized `RiskLevel` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- `confidence`: Certainty score `[0.0, 1.0]`.
- `evidence`: Lineage list of supporting `RiskEvidence` traces.
- `metadata`: Preserved diagnostic attributes.

### 2.3 RiskScore
Strongly typed score representation with strict mathematical boundaries:
- `score`: Composite risk score `[0.0, 100.0]` (`None` in Step 1).
- `risk_level`: Categorical `RiskLevel` (`None` in Step 1).
- `probability`: Bounded disruption probability `[0.0, 1.0]` (`None` in Step 1).
- `impact`: Bounded severity impact `[0.0, 100.0]` (`None` in Step 1).
- `confidence`: Composite certainty score `[0.0, 1.0]`.
- `factors`: Evaluated `RiskFactor` contributors.
- `evidence`: Consolidated evidence references.
- `timestamp`: UTC datetime of the evaluation.

*Note: In Phase 7 Step 1, `DefaultRiskScoreAggregator` provides an explicit stub where `score`, `risk_level`, `probability`, and `impact` remain `None`, preventing premature scoring mathematics.*

### 2.4 RiskAssessment
Authoritative output contract of the Risk Engine:
- `assessment_id`: Deterministic UUIDv5 based on tenant, scope, sorted signal IDs, and evaluation hour.
- `organization_id`: Tenant boundary.
- `evaluated_at`: UTC evaluation instant.
- `scope`, `scope_entity_id`, `scope_entity_type`: Evaluation boundary.
- `overall_score`: Typed `RiskScore`.
- `factors`: List of evaluated `RiskFactor` objects.
- `evidence`: Consolidated list of `RiskEvidence` objects.
- `explanation`: Structured deterministic `RiskExplanation`.
- `source_signals`: List of source `NormalizedRiskSignal` IDs.
- `metadata`: Audit, timing, conflict, and trace metadata.

### 2.5 RiskEvidence & Lineage
Every risk factor traces directly back to underlying evidence:
```
RiskAssessment
      ↓
RiskFactor
      ↓
RiskEvidence
      ↓
NormalizedRiskSignal
      ↓
CanonicalExternalEvent
      ↓
RawEvent
      ↓
External Provider
```
Attributes:
- `evidence_id`: Deterministic UUIDv5 identifier (`{org}:evidence:{signal_id}:{provider}`).
- `normalized_signal_id`: Upstream signal ID link.
- `source` & `provider`: Origin services (e.g. `noaa`, `tomtom`, `aisstream`, `karrio`).
- `source_type`: Observation nature (`REAL`, `ESTIMATED`, `SIMULATED`).
- `provenance`: Full metadata chain (`canonical_event_id`, `raw_event_id`, `provider_event_id`, `fingerprint`).
- `supporting_sources`: Corroborating multi-source observations from Phase 6 correlation.

---

## 3. Explainability Contract (Deterministic, Zero LLM)

Explainability in RiskWise is completely deterministic, auditable, and free of runtime generative AI dependencies:
- **`FactorExplanation`**: Provides discrete deterministic summaries, source citations, evidence counts, and severity per factor.
- **`RiskExplanation`**:
  - `summary`: Rule-based deterministic overview (e.g. highlighting elevated severity factors and evidence counts).
  - `factor_explanations`: Granular factor breakdowns.
  - `evidence_references`: Traceable evidence IDs.
  - `limitations`: Discloses synthetic data warnings (e.g. simulated signals) or partial data caveats.
  - `unresolved_conflicts`: Highlights disagreements detected across normalization sources.

---

## 4. Evaluator Interface & Registry

### 4.1 BaseRiskFactorEvaluator (Extension Protocol)
Abstract protocol defining how future domain-specific factor evaluators plug into the engine:
```python
class BaseRiskFactorEvaluator(abc.ABC):
    @property
    def evaluator_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def target_domains(self) -> List[SignalDomain]: ...
    @property
    def supported_signal_types(self) -> List[SignalType]: ...
    
    def can_evaluate(self, signal: NormalizedRiskSignal, context: RiskEvaluationContext) -> bool: ...
    
    @abc.abstractmethod
    def evaluate(self, signal: NormalizedRiskSignal, context: RiskEvaluationContext) -> Optional[RiskFactor]: ...
```

**Constraints on Evaluators**:
- Strictly typed input and output.
- Organization-aware.
- Completely deterministic and side-effect free.
- Zero network or database calls.

### 4.2 RiskFactorRegistry
Provider-independent registry mapping normalized signals to factor evaluators:
- Indexed by `SignalDomain` and `SignalType`.
- Duplicate registration protection (raises `EvaluatorRegistrationError`).
- Deterministic sorted evaluator resolution.

---

## 5. Risk Engine Pipeline Orchestrator

The `RiskEngine` orchestrates deterministic evaluation runs in 7 discrete stages:

```
RiskEngine.evaluate(context)
        ↓
1. Validate Context & Input Boundary
        ↓
2. Validate & Deduplicate Normalized Signals (Fingerprint Reuse)
        ↓
3. Route Signals to Registered Factor Evaluators
        ↓
4. Collect Risk Factors & Link Traceable Evidence
        ↓
5. Aggregate Composite RiskScore (Step 1 Uncommitted Stub)
        ↓
6. Generate Deterministic RiskExplanation
        ↓
7. Assemble & Return Authoritative RiskAssessment
```

### Future Scoring Extension Point
The aggregation stage is decoupled via `RiskScoreAggregatorProtocol`. In Step 2, mathematical scoring aggregators (e.g., weighted multi-factor scoring, confidence-weighted aggregation) plug directly into `RiskEngine(aggregator=...)` without changing the upstream validation, evaluator, or downstream explanation architecture.

---

## 6. Safety, Quality & Governance

### Quality Gating
- `EventQuality.VALID`: Evaluated normally.
- `EventQuality.PARTIAL`: Permitted only if `allow_partial_signals=True` on context; otherwise rejected with `InvalidSignalQualityError`.
- `EventQuality.INVALID`: Strictly rejected with `InvalidSignalQualityError`.

### Conflict Handling
Signals containing `has_conflict=True` from Phase 6 cross-source normalization are preserved. Conflicts are tracked in assessment metadata and exposed under `explanation.unresolved_conflicts`.

### Source Types
Signals with `source_type=SIMULATED` are preserved, counted in metadata, and explicitly flagged in `explanation.limitations`. They are never treated as real-world observations.

### Security
External descriptions, URLs, and tracking notes are treated strictly as inert data. No dynamic code evaluation, prompt injection parsing, or shell execution is possible.

---

## 7. Database & API Zero-Impact Verification
- **Database**: 0 new migrations, 0 modified tables, 0 column changes.
- **FastAPI / REST**: 0 route changes, 0 modified schemas.
- **Frontend**: 0 modifications.
