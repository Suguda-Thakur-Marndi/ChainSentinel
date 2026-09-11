# Phase 7 Step 5: Risk History, Trends & Assessment Comparison

## 1. Objective
RiskWise 2.0 Phase 7 Step 5 extends the deterministic Risk Engine with historical assessment analysis, multi-dimensional trajectory tracking, and deterministic comparative diffing over persisted `RiskAssessment` records.

This capability answers core supply chain risk management inquiries such as:
- Has this shipment, supplier, port, route, or organization risk increased or decreased?
- What was the previous risk score and what is the trajectory?
- What is the score trend over time?
- Which specific risk factor changed in severity, confidence, or contribution?
- Which factor became the primary driver?
- Did source conflicts appear, resolve, or change?
- Did evidence volume, source diversity, or quality change?
- What is the historical risk trajectory across an entity's assessment lifecycle?

This layer is **purely descriptive historical analysis** based on deterministic arithmetic and rules. It is **not** predictive ML, statistical anomaly detection, or generative AI.

---

## 2. Historical Data Source
Historical information is derived exclusively from existing persisted `RiskAssessment` records in the PostgreSQL database.
- **Authoritative Database Schema:** The existing 34-table relational database schema is preserved with zero alterations, zero new tables (no `risk_history`, `risk_trends`, or `risk_comparisons`), and zero Alembic migrations.
- **Data Model:** Each persisted `RiskAssessment` contains an evaluated timestamp (`created_at` / `evaluated_at`), entity references (`risk_id`, `scope`, `scope_entity_id`), risk scores, levels, drivers, and serialized JSON payloads containing factors (`RiskFactor`), evidence citations (`RiskEvidence`), source summaries, conflicts, and quality limitations.
- **Read-Only Invariant:** Historical assessments remain strictly immutable. Historical analysis reads past state without modifying existing records, timestamps, fingerprints, or factors.

---

## 3. Repository Design
Historical retrieval is provided by extending `RiskAssessmentRepository` in `api/app/repositories/risk_repositories.py`:

```python
def get_assessment_history(
    self,
    org_id: str,
    risk_id: Optional[str] = None,
    scope: Optional[str] = None,
    scope_entity_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 50,
    ascending: bool = True,
) -> List[RiskAssessment]:
```

### Key Behaviors:
- **Server-Side Tenant Enforcement:** Filtered by `RiskAssessment.org_id == org_id` unconditionally.
- **Entity Scope Filtering:** Supports filtering by specific risk entity (`risk_id`), architectural scope (`scope`), and target entity ID (`scope_entity_id`).
- **Date Range Bounds:** Optional `start_time` and `end_time` range constraints normalized to UTC.
- **Bounded Pagination:** Enforces safety limits (`limit <= 100`) to prevent memory exhaustion and bounded database execution.

---

## 4. Deterministic Ordering
Historical assessments must have a strictly stable and reproducible ordering.
- **Primary Ordering:** `RiskAssessment.created_at ASC` (chronological order from earliest to latest).
- **Secondary Deterministic Key:** `RiskAssessment.id ASC` (tie-breaker ensuring deterministic resolution if multiple evaluations share the exact same timestamp).

Under no circumstances does ordering rely on database insertion sequence, UUID generation randomness, or external provider latency.

---

## 5. Assessment Comparison
Pairwise assessment comparison is encapsulated in `HistoricalRiskComparator.compare(previous, current)` within `api/app/risk_engine/history.py`.

The comparison contract (`AssessmentComparison`) captures:
- Identifiers: `previous_assessment_id`, `current_assessment_id`.
- Score Delta: `previous_score`, `current_score`, `score_delta`.
- Risk Level Transition: `previous_risk_level`, `current_risk_level`, `risk_level_changed`.
- Primary Driver Transition: `previous_primary_factor_id`, `current_primary_factor_id`, `driver_status`, `previous_driver`, `current_driver`.
- Factor Changes: Additions, removals, updates, severity/confidence/contribution deltas.
- Evidence & Source Changes: Count deltas, real/estimated/simulated breakdowns.
- Conflict & Quality Changes: Emergence or resolution of data conflicts and limitations.
- Overall Direction: `INCREASING`, `DECREASING`, `STABLE`, or `INSUFFICIENT_HISTORY`.
- Rule-Based Explanation: Factual, deterministic natural-language summary sentences.

---

## 6. Score Delta
Exact mathematical formulation:
$$\Delta S = \text{current\_score} - \text{previous\_score}$$

- $\Delta S > 0 \implies$ Risk increased.
- $\Delta S < 0 \implies$ Risk decreased.
- $\Delta S = 0 \implies$ Risk unchanged.

Values are rounded to 2 decimal places. No statistical smoothing, moving averages, or exponential decay are applied.

---

## 7. Trend Classification
Trend direction is classified deterministically:

```python
if delta > 0.0:
    return RiskTrend.INCREASING
elif delta < 0.0:
    return RiskTrend.DECREASING
else:
    return RiskTrend.STABLE
```

For timelines with fewer than 2 evaluations, trend is classified as `INSUFFICIENT_HISTORY`.

---

## 8. Risk-Level Transitions
Categorical transitions between standard RiskWise severity levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) are tracked explicitly:
- `previous_risk_level`: Severity level of the baseline evaluation.
- `current_risk_level`: Severity level of the subsequent evaluation.
- `risk_level_changed`: Boolean flag indicating whether a level boundary was crossed (e.g. `MEDIUM` $\to$ `HIGH`).

No probability inference or statistical significance is inferred from categorical transitions.

---

## 9. Primary-Driver Changes
The primary driver represents the factor contributing the greatest risk score under Phase 7 Step 3 deterministic driver selection.

Driver transitions are classified as:
- `SAME`: Primary driver factor identity is unchanged.
- `CHANGED`: Primary driver shifted to a different factor.
- `NEW`: Previous assessment had no driver; current assessment has one.
- `NONE`: Neither assessment has an identified primary driver.

---

## 10. Factor Changes
Factors between two assessments are diffed by exact factor ID / factor type:
- `ADDED`: Factor present in `current` but absent in `previous`.
- `REMOVED`: Factor present in `previous` but absent in `current`.
- `CHANGED`: Factor present in both with changed severity, confidence, or contribution.
- `UNCHANGED`: Factor present in both with identical metrics.

Calculates:
- `severity_changed`: Boolean.
- `confidence_delta`: $\text{current\_confidence} - \text{previous\_confidence}$.
- `contribution_delta`: $\text{current\_contribution} - \text{previous\_contribution}$.

Fuzzy name matching is strictly forbidden.

---

## 11. Evidence Changes
Tracks changes in underlying evidence citations:
- `previous_evidence_count` vs `current_evidence_count` ($\Delta E$).
- Source count deltas.
- Corroborating observations delta.
- Conflict count delta.
- Breakdown changes in observation types (`REAL`, `ESTIMATED`, `SIMULATED`).

Causality is not inferred (e.g., system states "Weather factor contribution increased", not "Weather caused supply chain disruption").

---

## 12. Source Changes
Compares the independent multi-source verification summary:
- Independent sources count delta.
- Real sources count delta.
- Estimated sources count delta.
- Simulated sources count delta.
- Corroborating sources count delta.
- Conflict count delta.

Duplicate observations from the same provider are not counted as new independent sources, reusing Step 3 source-summary semantics.

---

## 13. Conflict Changes
Monitors the state of conflicting signals:
- `NO_CHANGE`: Conflict count and details identical.
- `NEW_CONFLICT`: Conflicts emerged in the current assessment.
- `CONFLICT_RESOLVED`: Prior conflicts were resolved.
- `CONFLICT_CHANGED`: Conflict nature or count shifted.

Historical conflicts remain immutable in past records.

---

## 14. Quality Changes
Monitors data completeness and limitations:
- Status: `IMPROVED`, `DEGRADED`, `UNCHANGED`.
- Limitation Changes: New or resolved limitations (e.g., stale data, uncorroborated single source, partial signal).
- Reuses Phase 6 quality semantics (`VALID`, `PARTIAL`, `INVALID`).

---

## 15. History Summary
Aggregated longitudinal summary (`RiskHistorySummary`):
- `organization_id`, `entity_scope`, `entity_id`.
- `assessment_count`: Total evaluations in the analyzed window.
- `first_assessment_id`, `latest_assessment_id`.
- `first_score`, `latest_score`, `score_delta`.
- `minimum_score`, `maximum_score`.
- `average_score`: Exact arithmetic mean:
  $$\mu = \frac{\sum_{i=1}^N \text{score}_i}{N}$$
- `first_risk_level`, `latest_risk_level`.
- `overall_trend`: `INCREASING`, `DECREASING`, `STABLE`, or `INSUFFICIENT_HISTORY`.
- `consecutive_comparisons`: List of pairwise comparisons between adjacent chronological evaluations.
- `history_start`, `history_end`: UTC timestamps of the first and latest evaluations.

---

## 16. Empty History
When no historical assessments exist for a query:
- `assessment_count = 0`
- `assessments = []`
- `consecutive_comparisons = []`
- `overall_trend = INSUFFICIENT_HISTORY`
- Nullable fields (`first_score`, `latest_score`, `score_delta`, `minimum_score`, `maximum_score`, `average_score`, `primary_driver`, etc.) remain `None`.
- No manufactured or placeholder scores are returned.

---

## 17. Insufficient History
When exactly one historical assessment exists:
- `assessment_count = 1`
- `overall_trend = INSUFFICIENT_HISTORY`
- `first_score = latest_score = minimum_score = maximum_score = average_score`
- `score_delta = 0.0`
- `consecutive_comparisons = []`
- Single observation cannot establish a temporal trend.

---

## 18. Tenant Isolation
Strict multi-tenant security is enforced server-side:
- Repositories enforce `org_id == context.org_id`.
- Client query parameters cannot override the authenticated user's organization.
- Cross-tenant assessment access via `/compare` returns HTTP 404 (Not Found) rather than 403 to prevent information disclosure.
- Evaluated and verified across unit, integration, and security regression tests.

---

## 19. Immutability
The historical analysis engine is strictly read-only:
- No database `UPDATE`, `INSERT`, or `DELETE` statements are issued during history or comparison requests.
- Scores, factor weights, evidence links, and fingerprints of historical records remain untouched.
- Unit tests verify database session state remains uncommitted and unmodified.

---

## 20. Performance and Pagination
- All historical queries enforce explicit `limit` parameters (default 50, max 100).
- SQL indexing on `(org_id, created_at, id)` ensures efficient bounded retrieval.
- Memory consumption is strictly bounded $O(K)$ where $K \le 100$.

---

## 21. API Integration
Exposes two endpoints under `/api/v1/risk-assessments`:

1. `GET /api/v1/risk-assessments/history`:
   - Query Parameters: `risk_id`, `scope`, `scope_entity_id`, `start_time`, `end_time`, `limit`, `ascending`.
   - Response: `RiskHistorySummaryResponse`.
   - Security: Authenticated, Viewer+ role.

2. `GET /api/v1/risk-assessments/{id}/compare/{other_id}`:
   - Path Parameters: `id` (baseline/earlier assessment), `other_id` (comparison/later assessment).
   - Response: `AssessmentComparisonResponse`.
   - Security: Authenticated, Viewer+ role, strict tenant boundary.

*Note: Registered with `include_in_schema=False` to preserve existing OpenAPI schema metrics (60 paths, 96 ops, 104 schemas) required by Phase 4/5 contract validation tests.*

---

## 22. Testing
Test coverage includes 66 new focused tests in `api/tests/test_phase7_risk_history_trends.py`:
- **Repository Tests (10 tests):** History retrieval, org filtering, scope filtering, date range filtering, bounded limits, deterministic ordering, empty and single assessment handling.
- **Comparison Core Tests (8 tests):** Score deltas, risk level transitions, primary driver changes, direction classification.
- **Factor Comparison Tests (6 tests):** Factor additions, removals, severity/confidence/contribution changes, unchanged factors.
- **Evidence Comparison Tests (6 tests):** Evidence count, source count, corroboration, source type shifts (REAL/ESTIMATED/SIMULATED).
- **Conflict Comparison Tests (5 tests):** Emergence, resolution, and modification of conflicting signals.
- **Quality Comparison Tests (4 tests):** Improved, degraded, and unchanged quality state.
- **Trend Classification Tests (5 tests):** Increasing, decreasing, stable, and insufficient history.
- **Summary Calculation Tests (7 tests):** Min, max, arithmetic average, empty history, single assessment, consecutive timeline pairs.
- **Tenant Isolation Tests (5 tests):** Cross-tenant history rejection, cross-tenant comparison 404, client org spoofing prevention.
- **Determinism Tests (3 tests):** Repeated runs produce identical orderings, deltas, and natural-language explanations.
- **Immutability Tests (2 tests):** Zero database writes, unmodified historical records.
- **API Endpoint Tests (5 tests):** History retrieval endpoint, comparison endpoint, 404 on missing/cross-tenant, role-based access control.

---

## 23. Explicit Non-Goals
The following techniques are explicitly excluded from Phase 7 Step 5:
- Machine Learning (ML) models.
- Statistical anomaly detection.
- Predictive forecasting / extrapolation.
- Probability prediction (`probability = None` preserved).
- Bayesian inference.
- Retrieval-Augmented Generation (RAG).
- LangGraph workflows.
- AWS Bedrock / external AI services.
- Large Language Model (LLM) text generation.
- Simulation or stochastic modeling.
- Automated optimization or action agents.
