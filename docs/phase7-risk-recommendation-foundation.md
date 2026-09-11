# Phase 7 Step 7 — Risk Decision & Recommendation Foundation

## 1. Objective

Phase 7 Step 7 establishes the deterministic decision and recommendation foundation for the RiskWise 2.0 Risk Engine. It defines an explainable, auditable, and strictly rule-based mechanism that translates evaluated `RiskAssessment` records and their associated `RiskAlert` events into prioritized operational recommendations (`RiskRecommendation`).

The output of this layer is exclusively advisory operational guidance. It establishes the prerequisite context and structure for human review in later roadmap stages, without autonomously executing any actions or modifying physical supply chain entities.

---

## 2. Architecture

The decision and recommendation flow is strictly unidirectional and downstream of risk evaluation and alerting:

```
+-------------------------------------------------------------+
|                      RiskAssessment                         |
|  (score 0-100, risk_level, confidence, factors, evidence)   |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                        RiskAlerts                           |
|       (threshold breaches, escalations, notifications)      |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|               RecommendationRuleRegistry                    |
|  - Deterministic evaluation rules                           |
|  - Severity and domain triggers (Route, Carrier, Supplier)  |
|  - Idempotent ID generation (SHA-256 semantic hash)         |
|  - Generic MONITOR suppression at high/critical risk       |
|  - Multi-key deterministic ordering                         |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                   RiskRecommendation[]                      |
|  - Type, Priority, Status (PROPOSED / PENDING_REVIEW)       |
|  - Factor and evidence lineage (IDs only, no raw payloads)  |
|  - Factual, deterministic rationale                         |
|  - Operational objectives, constraints, assumptions         |
|  - Limitations (propagated quality/degradation notes)       |
|  - requires_human_approval = True                           |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                    PostgreSQL Persistence                   |
|  - Authoritative 34-table schema (recommendations table)   |
|  - Transactional atomicity (UnitOfWork)                     |
|  - Audit logging (action = RECOMMENDATION_PROPOSED)         |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                 Later Human Approval Phase                  |
|      (No autonomous execution / No shipment mutation)       |
+-------------------------------------------------------------+
```

---

## 3. Recommendation Contract

The core domain entity is `RiskRecommendation` (defined in `app.risk_engine.recommendations`):

```python
class RiskRecommendation(BaseModel):
    recommendation_id: str             # Deterministic: rec_<sha256[:24]> (28 chars)
    organization_id: str               # Tenant context boundary
    assessment_id: str                 # Triggering assessment ID
    risk_id: Optional[str] = None      # Optional parent risk entity ID
    scope: Optional[str] = None        # Scope dimension (PORT, CORRIDOR, SHIPMENT, etc.)
    scope_entity_id: Optional[str]     # Identifier of entity under assessment
    recommendation_type: RecommendationType
    priority: RecommendationPriority   # LOW, MEDIUM, HIGH, CRITICAL
    status: RecommendationStatus       # PROPOSED, PENDING_REVIEW
    title: str                         # Human-readable summary
    rationale: str                     # Factual, non-speculative justification
    factor_ids: List[str]              # Triggering factor IDs
    evidence_ids: List[str]            # Lineage to supporting signals (top 5 max)
    expected_objective: str            # Operational objective
    constraints: List[str]             # Known operational/data constraints
    assumptions: List[str]             # Factual baseline assumptions
    limitations: List[str]             # Propagated quality & uncertainty notes
    requires_human_approval: bool      # Advisory approval flag (True for actionable recs)
    confidence: Optional[float]        # Confidence score [0.0, 1.0]
    fingerprint: Optional[str]         # Semantic hash for idempotency checking
    created_at: datetime               # Normalized UTC timestamp
    metadata: Dict[str, Any]           # Structured, secret-scrubbed context
```

---

## 4. Recommendation Types

The recommendation taxonomy consists of eight explicit, deterministic types justified strictly from available assessment data:

1. **`MONITOR`**: Default baseline observation for low-risk states or stable operations without active disruptions.
2. **`INVESTIGATE`**: Triggered by conflicting source signals, low confidence, or new anomalies requiring data verification.
3. **`EXPEDITE_REVIEW`**: Triggered by critical overall risk scores ($\ge 85.0$) or individual critical factors requiring expedited analysis.
4. **`REVIEW_ALTERNATE_ROUTE`**: Triggered by severe corridor, port, road, maritime, or weather disruptions impacting transport paths.
5. **`REVIEW_ALTERNATE_SUPPLIER`**: Triggered by high/critical supplier solvency, factory shutdown, or site disruption factors.
6. **`REVIEW_INVENTORY`**: Triggered by warehouse, storage, cold-chain spoilage, or safety-stock vulnerability factors.
7. **`REVIEW_CARRIER`**: Triggered by carrier capacity, air freight cancellation, rail stoppage, or logistics booking disruption factors.
8. **`ESCALATE_OPERATIONAL_ATTENTION`**: Triggered by high overall risk ($\ge 60.0$), critical alert escalation, or upward risk trajectory (+10.0 pts).

---

## 5. Decision Rules

Rules are purely deterministic, evaluated against normalized signals, risk factors, scores, alerts, and trend comparisons:

| Rule Name | Trigger Condition | Recommendation Type | Priority | Expected Objective |
| :--- | :--- | :--- | :--- | :--- |
| **Low Risk Baseline** | Score < 30.0 | `MONITOR` | `LOW` | `IMPROVE_VISIBILITY` |
| **Medium Risk Review** | 30.0 $\le$ Score < 60.0 | `INVESTIGATE` | `MEDIUM` | `IMPROVE_VISIBILITY` |
| **High Risk Escalation** | 60.0 $\le$ Score < 85.0 | `ESCALATE_OPERATIONAL_ATTENTION` | `HIGH` | `REDUCE_DISRUPTION_EXPOSURE` |
| **Critical Risk Escalation** | 85.0 $\le$ Score $\le$ 100.0 | `ESCALATE_OPERATIONAL_ATTENTION` & `EXPEDITE_REVIEW` | `CRITICAL` | `REDUCE_DISRUPTION_EXPOSURE` & `PROTECT_SERVICE_LEVEL` |
| **Critical Factor Trigger** | Any factor with severity `CRITICAL` | `EXPEDITE_REVIEW` | `CRITICAL` | `PROTECT_SERVICE_LEVEL` |
| **Routing Disruption** | Port, road, ocean, typhoon factors & Score $\ge$ 30.0 | `REVIEW_ALTERNATE_ROUTE` | Maps to factor severity | `REDUCE_DELAY_RISK` |
| **Carrier Disruption** | Air, rail, carrier booking factors & Score $\ge$ 30.0 | `REVIEW_CARRIER` | Maps to factor severity | `REDUCE_DELAY_RISK` |
| **Supplier Disruption** | Supplier insolvency or factory disruption | `REVIEW_ALTERNATE_SUPPLIER` | Maps to factor severity | `REVIEW_SUPPLY_CONTINUITY` |
| **Inventory Disruption** | Warehouse, storage, spoilage factors & Score $\ge$ 30.0 | `REVIEW_INVENTORY` | Maps to factor severity | `PROTECT_SERVICE_LEVEL` |
| **Signal Conflict Trigger** | Unresolved signal conflicts present | `INVESTIGATE` | `MEDIUM` | `IMPROVE_VISIBILITY` |
| **Increasing Trend Trigger**| Trend `INCREASING` (+10 pts) & Score $\ge$ 60.0 | `ESCALATE_OPERATIONAL_ATTENTION` | `HIGH` or `CRITICAL` | `REDUCE_DISRUPTION_EXPOSURE` |
| **Alert Escalation Trigger**| Active `CRITICAL` or `HIGH` alert | `EXPEDITE_REVIEW` or `ESCALATE_OPERATIONAL_ATTENTION` | Matches alert severity | `PROTECT_SERVICE_LEVEL` |

---

## 6. Priority

Recommendation priority is an explicit, deterministic operational urgency rating:

- **`CRITICAL`**: Requires immediate same-shift briefing; triggered by overall risk $\ge 85.0$, critical factors, or critical alert escalation.
- **`HIGH`**: Requires prompt operational review; triggered by overall risk $\ge 60.0$, high-severity factors, or increasing trends.
- **`MEDIUM`**: Requires standard workflow investigation; triggered by moderate disruptions or signal conflicts.
- **`LOW`**: Routine monitoring; triggered by low risk and baseline stability.

Priority is strictly decoupled from raw risk level enumerations, though mapped via documented monotonic rules.

---

## 7. Status

Lifecycle status adheres to governance constraints:

- Newly generated recommendations are assigned **`PROPOSED`** (or **`PENDING_REVIEW`**).
- Statuses **`APPROVED`**, **`REJECTED`**, **`EXPIRED`**, and **`COMPLETED`** are strictly reserved for downstream human-in-the-loop workflows in the later Human Approval phase.
- Step 7 never auto-approves or auto-completes recommendations.

---

## 8. Human Approval Boundary

Every actionable recommendation enforces:

```python
requires_human_approval = True
```

Recommendations that propose route reviews, carrier evaluations, supplier assessments, inventory adjustments, or operational escalation explicitly signal that no automated execution may take place without verified human operator authorization.

---

## 9. Factor Traceability

Every recommendation records the exact factor IDs (`factor_ids: List[str]`) that triggered it. Factor IDs originate deterministically from Phase 7 Step 1 and Step 3 contracts (`fac_<sha256[:16]>`). No factor IDs are fabricated or synthesized.

---

## 10. Evidence Traceability

Recommendations preserve lineage down to the underlying `RiskEvidence` items via `evidence_ids: List[str]`. Each evidence ID maps back to a normalized signal (`sig_<sha256[:16]>`) and canonical external event. Raw provider payloads, API tokens, and confidential fields are excluded from lineage references.

---

## 11. Rationale

Recommendation rationales are generated deterministically using templated rule logic based strictly on verified assessment facts:

- "Risk score reached HIGH threshold (72.0/100) driven by primary factor 'Port Congestion'. Operational attention escalation required."
- "Corridor disruption factor 'Highway Flooding' detected with HIGH severity. Recommend evaluating alternate transport corridors or rerouting options."

Speculative causality, probabilistic assertions, and generative LLM fabrications are strictly prohibited.

---

## 12. Objectives

Each recommendation declares its intended operational objective:

- `REDUCE_DELAY_RISK`
- `REDUCE_DISRUPTION_EXPOSURE`
- `IMPROVE_VISIBILITY`
- `PROTECT_SERVICE_LEVEL`
- `REVIEW_SUPPLY_CONTINUITY`

Objectives reflect intended operational aims; they are never represented as guaranteed outcomes.

---

## 13. Assumptions

Assumptions capture baseline evaluation conditions:

- "Current recommendation is derived deterministically from evaluated normalized risk signals."
- "Operational impacts remain active until verified or mitigated."
- "Alternative supplier capacity and contract terms have not been verified."

---

## 14. Constraints

Known operational boundaries and data gaps are recorded:

- "Route and scheduling alternatives have not yet been evaluated by mathematical optimization."
- "Alternative carrier capacity has not been validated against active service-level agreements."

---

## 15. Limitations

Uncertainties and signal quality degradations from the assessment are propagated:

- If evidence quality is `PARTIAL` or `ESTIMATED`, the recommendation carries explicit notes:
  - "Recommendation is derived from PARTIAL/degraded evidence; field verification advised."
- Conflicting signals and unresolved corroborations are surfaced in limitation notes.

---

## 16. Deduplication & Idempotency

Recommendation generation is strictly idempotent:

- **Deterministic ID / Fingerprint**:
  $$\text{ID} = \text{rec\_} + \text{SHA256}(org\_id : assessment\_id : rec\_type : entity\_key)[:24]$$
  Total length: 28 characters (comfortably within `VARCHAR(64)`).
- Timestamps, random UUIDs, request IDs, and trace IDs are strictly excluded from ID calculation.
- Repeated evaluation of the same assessment yields identical IDs, preventing duplicate recommendation records in the database.

---

## 17. Deterministic Ordering

When an assessment produces multiple recommendations, they are sorted using a deterministic multi-key sort:

1. **Priority Rank Descending**: `CRITICAL` (3) > `HIGH` (2) > `MEDIUM` (1) > `LOW` (0)
2. **Recommendation Type Ascending**: Alphabetical by type name
3. **Recommendation ID Ascending**: Lexicographical tie-breaker

---

## 18. Alert Relationship

Alerts and recommendations are distinct:
- **`RiskAlert`**: An operational signal indicating *"Pay attention to this threshold breach."*
- **`RiskRecommendation`**: Actionable guidance indicating *"Consider this investigation or mitigation step."*

When critical alerts are present, the recommendation evaluator consumes them to elevate priorities or trigger expedited reviews, but maintains separate lifecycle and persistence records.

---

## 19. Historical Relationship

Historical trend comparisons from Phase 7 Step 5 (`HistoricalRiskComparator`) feed into recommendation evaluation:
- An `INCREASING` risk trajectory (+10.0 points) at or above the high threshold triggers proactive `ESCALATE_OPERATIONAL_ATTENTION`.
- Historical trends inform escalation urgency without making extrapolative predictive claims.

---

## 20. Persistence

Step 7 reuses the existing `recommendations` table in PostgreSQL without any schema modifications:

- **`id`**: Mapped to deterministic `recommendation_id` (`rec_<hash>`).
- **`org_id`**: Mapped to `organization_id`.
- **`incident_id`**: Associated incident or `None`.
- **`title`**: Recommendation summary title.
- **`rationale`**: Rule-based explanatory justification.
- **`status`**: Governance status (`PROPOSED`).
- **`confidence`**: Assessment confidence score.
- **`expected_benefit_json`**: Complete domain model envelope containing `assessment_id`, `risk_id`, `scope`, `scope_entity_id`, `recommendation_type`, `priority`, `factor_ids`, `evidence_ids`, `expected_objective`, `constraints`, `assumptions`, `limitations`, `requires_human_approval`, `fingerprint`, and `metadata`.

The bidirectional `RiskRecommendationAdapter` allows seamless serialization and zero-loss reconstruction from ORM records.

---

## 21. Transaction Behavior

Recommendation persistence is transactional and atomic within `RiskEvaluationService.evaluate_and_persist`:

```
BEGIN TRANSACTION
  Persist RiskAssessment (if not idempotent hit)
  Persist RiskFactors
  Persist RiskEvidence
  Persist RiskAlerts (Notifications)
  Persist RiskRecommendations
  Persist AuditLog (action = "RECOMMENDATION_PROPOSED")
COMMIT
```

If any step fails, the entire transaction is rolled back, preventing orphaned or incomplete recommendation states.

---

## 22. API Integration

Exposed through `api/app/api/v1/endpoints/risk_assessments.py`:

- `GET /api/v1/risk-assessments/recommendations`: List recommendations with tenant bounding, filtering by priority, type, and pagination.
- `GET /api/v1/risk-assessments/recommendations/{recommendation_id}`: Retrieve a single recommendation with strict tenant isolation (returns 404 for cross-tenant access).
- `GET /api/v1/risk-assessments/{id}/recommendations`: Retrieve all recommendations associated with a specific assessment.

To maintain strict OpenAPI contract stability (preserving exactly 60 paths, 96 operations, 104 schemas), these convenience query endpoints are configured with `include_in_schema=False`. Recommendation payloads are also returned directly inside `detail_dict["recommendations"]` of the primary `/evaluate` endpoint.

---

## 23. Tenant Isolation

Multi-tenancy is enforced at all levels:
- All database queries filter strictly on `org_id == context.org_id`.
- Deterministic recommendation IDs incorporate `org_id` in their hash seed.
- Cross-tenant lookups return HTTP 404.
- Cross-tenant evidence or assessment linkages are rejected at the service boundary.

---

## 24. Auditability

Every recommendation creation writes an `AuditLog` entry:
- **`action`**: `"RECOMMENDATION_PROPOSED"`
- **`entity_type`**: `"RECOMMENDATION"`
- **`entity_id`**: `rec_<hash>`
- **`user_id`**: Requesting user ID
- **`org_id`**: Tenant ID
- **`payload`**: Sanitized audit metadata (recommendation type, priority, assessment ID, factor count).

---

## 25. Security

- **Secret Scrubbing**: Rationale, limitations, constraints, assumptions, and metadata are sanitized with `scrub_sensitive_data` to redact API keys, tokens, and credentials (`[REDACTED]`).
- **No Raw Payloads**: Raw vendor responses and external credentials are strictly barred from recommendation entities.
- **Input Sanitization**: Injection strings and script tags remain inert data within text fields.

---

## 26. Testing

An extensive test suite validates Step 7 with 84 focused tests in `api/tests/test_phase7_risk_recommendation_foundation.py`:

- **Contract Tests (12 tests)**: Model construction, enum boundaries, field validation, and deterministic hashing.
- **Rule Tests (16 tests)**: Low, Medium, High, and Critical thresholds; critical factors, port, road, weather, rail, air, carrier, supplier, inventory disruptions; increasing trends; signal conflicts; and evidence quality degradation.
- **Recommendation Type Tests (8 tests)**: Representation of all 8 taxonomy types.
- **Priority Tests (6 tests)**: Deterministic severity mapping and ordering.
- **Traceability Tests (6 tests)**: Linkage from recommendation to assessment, factors, and evidence.
- **Explanation Tests (6 tests)**: Factual rationale, absence of speculative claims, assumptions, constraints, and objectives.
- **Deduplication Tests (6 tests)**: Repeated evaluation idempotency, distinct assessment separation, and sort tie-breakers.
- **Conflict & Suppression Tests (4 tests)**: Suppression of generic `MONITOR` at high/critical risk and coexistence of operational reviews.
- **Persistence Tests (6 tests)**: Adapter serialization/deserialization, transactional persistence, rollback safety, and idempotency.
- **Tenant Isolation Tests (6 tests)**: Cross-tenant prevention on list, get, and context validation.
- **API Tests (6 tests)**: Authentication, unauthenticated rejection, pagination, and assessment filtering.
- **Security Tests (3 tests)**: Secret scrubbing, credential redaction, and raw payload rejection.
- **No-Action Boundary Tests (5 tests)**: Proof of zero shipment rerouting, zero cancellations, zero carrier calls, zero auto-approvals, and strict advisory scoping.

**Full Application Suite Results**: 1,412 passed, 1 skipped, 0 failures.

---

## 27. Explicit Non-Goals

The following capabilities are strictly out of scope for Phase 7 Step 7:
- Machine Learning (ML), neural networks, or LLM-based reasoning.
- RAG, LangGraph, AWS Bedrock, or LangChain agents.
- Bayesian networks or probabilistic risk models (`probability = None`, `impact = None`).
- Operations Research / Mathematical Optimization (OR-Tools, MILP).
- Digital Twin state mutation or what-if simulations.
- Autonomous action execution (no carrier contact, PO creation, supplier switching, or rerouting).
- Automated recommendation approval.
