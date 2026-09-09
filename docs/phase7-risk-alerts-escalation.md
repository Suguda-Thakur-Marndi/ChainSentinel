# Phase 7 Step 6 — Risk Alerts, Thresholds & Escalation

## 1. Objective

Implement deterministic, explainable risk alert evaluation, threshold monitoring, and escalation on top of the completed Risk Engine (Phase 7 Steps 1–5). The system detects when a newly evaluated `RiskAssessment` requires operational attention, evaluates transition and condition rules against previous assessment states without ML or generative models, generates deterministic `RiskAlert` domain objects, and transactionally persists them as tenant-isolated `Notification` records and append-only `AuditLog` events in the authoritative 34-table PostgreSQL schema.

---

## 2. Alert Architecture

The alerting pipeline executes cleanly downstream of assessment scoring, preserving pipeline immutability and transactional safety:

```
RiskAssessment (Evaluated Score, Level, Factors, Evidence, Conflicts, Limitations)
      ↓
Alert Evaluation Rules (RiskAlertEvaluator.evaluate_alerts)
  ├── Threshold Crossing Rules (HIGH, CRITICAL)
  ├── Categorical Level Transition Rules (Escalation / De-escalation)
  ├── Material Score Jump Rules (Delta >= 15.0 pts)
  ├── Trend Direction Rules (INCREASING trajectory with elevated score)
  ├── Critical Factor Detection (Factor severity == CRITICAL)
  ├── Conflict Emergence Rules (New multi-source signal disagreement)
  ├── Evidence Quality Degradation Rules (Transitions to DEGRADED)
  └── Primary Risk Driver Change Rules (Shift in dominant contributor)
      ↓
RiskAlert Domain Objects (Deterministic Semantic Hash IDs, AlertSeverity, Rule Explanations)
      ↓
RiskAlertNotificationAdapter (Maps RiskAlert to existing Notification model: category="RISK_ALERT")
      ↓
Transactional Persistence (UnitOfWork: Assessment + Factors + Notifications + Audit Logs)
      ↓
API Endpoints & Client Notifications
```

---

## 3. Alert Contract

The domain contract is formalized in `apps/api/app/risk_engine/alerts.py`:

```python
class RiskAlert(BaseModel):
    alert_id: str                      # Deterministic semantic hash (alt_<hash>)
    organization_id: str               # Tenant identifier
    assessment_id: str                 # Triggering assessment
    risk_id: Optional[str]             # Optional associated risk entity
    scope: Optional[str]               # Entity scope (PORT, SHIPMENT, SUPPLIER, NETWORK)
    scope_entity_id: Optional[str]     # Scoped entity identifier
    alert_type: RiskAlertType          # Deterministic enum classification
    severity: AlertSeverity            # Operational priority: INFO, WARNING, CRITICAL
    status: AlertStatus                # State: OPEN, ACKNOWLEDGED, RESOLVED, DISMISSED
    previous_score: Optional[float]    # Prior score (if historical comparison)
    current_score: float               # Current assessment score
    score_delta: Optional[float]       # Delta (current - previous)
    previous_risk_level: Optional[str] # Prior categorical level
    current_risk_level: str            # Current categorical level
    trigger_reason: str                # Deterministic rule explanation
    factor_id: Optional[str]           # Associated factor identifier (if factor-triggered)
    evidence_ids: List[str]            # Linked evidence identifiers (traceability)
    created_at: datetime               # Evaluation timestamp (UTC)
    acknowledged_at: Optional[datetime]# Acknowledgement timestamp (UTC)
    acknowledged_by: Optional[str]     # User ID who acknowledged
    metadata: Dict[str, Any]           # Structured telemetry and context
```

---

## 4. Alert Types

All alert types are defined as deterministic enums in `RiskAlertType`:

| Alert Type | Description | Trigger Condition |
| :--- | :--- | :--- |
| `HIGH_RISK_REACHED` | Assessment crossed into HIGH threshold | `current_score >= 60.0` and (`previous_score is None` or `previous_score < 60.0`) |
| `CRITICAL_RISK_REACHED` | Assessment crossed into CRITICAL threshold | `current_score >= 85.0` and (`previous_score is None` or `previous_score < 85.0`) |
| `RISK_LEVEL_INCREASED` | Categorical risk rank increased | `rank(current_level) > rank(previous_level)` |
| `RISK_LEVEL_DECREASED` | Categorical risk rank decreased | `rank(current_level) < rank(previous_level)` |
| `RISK_SCORE_INCREASED` | Material score jump | `score_delta >= 15.0` points |
| `RISK_TREND_INCREASING` | Trajectory is INCREASING with elevated risk | `trend == INCREASING` and `current_score >= 60.0` |
| `CRITICAL_FACTOR_DETECTED` | Newly appeared factor with CRITICAL severity | Factor `severity == CRITICAL` not in previous assessment |
| `NEW_CONFLICT` | Signal conflict emerged | `len(current.conflicts) > len(previous.conflicts)` |
| `QUALITY_DEGRADED` | Evidence quality degraded | Limitations appeared or signal quality downgraded |
| `PRIMARY_DRIVER_CHANGED` | Dominant risk factor shifted | `primary_factor_id` changed and `current_score >= 30.0` |

---

## 5. Threshold Rules

Authoritative risk thresholds established in Phase 7 Step 2 remain strictly unchanged:
- **LOW:** `[0.0, 30.0)` — Routine operations, zero operational alerts generated.
- **MEDIUM:** `[30.0, 60.0)` — Informational and operational monitoring alerts only when specific triggers occur.
- **HIGH:** `[60.0, 85.0)` — Operational attention required, WARNING severity.
- **CRITICAL:** `[85.0, 100.0]` — Urgent operational priority, CRITICAL severity.

Threshold crossings are strictly **transition-based** to prevent alert storms:
- An assessment remaining in HIGH (`65.0 -> 70.0`) does NOT re-trigger `HIGH_RISK_REACHED`.
- An assessment remaining in CRITICAL (`88.0 -> 92.0`) does NOT re-trigger `CRITICAL_RISK_REACHED`.
- Transitions across boundaries (`55.0 -> 65.0`) generate `HIGH_RISK_REACHED` and `RISK_LEVEL_INCREASED`.

---

## 6. Escalation Rules

Escalation strictly governs **notification urgency and priority levels**, never executing autonomous real-world operations:

- **CRITICAL Escalation:**
  - `CRITICAL_RISK_REACHED`
  - `RISK_LEVEL_INCREASED` transitioning into CRITICAL
  - `CRITICAL_FACTOR_DETECTED`
  - `RISK_SCORE_INCREASED` with `current_score >= 85.0`
  - `RISK_TREND_INCREASING` with `current_score >= 85.0`
- **WARNING Escalation:**
  - `HIGH_RISK_REACHED`
  - `RISK_LEVEL_INCREASED` transitioning into HIGH
  - `NEW_CONFLICT` (multi-source disagreement requires operational review)
  - `QUALITY_DEGRADED` (evidence reliability degraded)
  - `PRIMARY_DRIVER_CHANGED` when risk score is HIGH (`>= 60.0`)
- **INFO De-escalation / Operational:**
  - `RISK_LEVEL_DECREASED` (de-escalation notification)
  - `PRIMARY_DRIVER_CHANGED` when risk score is MEDIUM (`< 60.0`)
  - `RISK_SCORE_INCREASED` when score remains below HIGH (`< 60.0`)

---

## 7. Severity Mapping

Severity is deterministically calculated without probabilistic or speculative guessing:

$$\text{RiskLevel} \neq \text{AlertSeverity}$$

A MEDIUM risk level undergoing an abrupt material jump (+20.0 points) or a driver change triggers an alert with INFO or WARNING severity, while a transition into CRITICAL risk elevates to CRITICAL severity.

---

## 8. Deduplication & Semantic Alert Identity

Alert identity is generated via deterministic SHA-256 semantic hashing over non-volatile domain fields:

$$\text{alert\_id} = \text{"alt\_"} + \text{SHA256}(\text{org\_id} \mathbin{\Vert} \text{assessment\_id} \mathbin{\Vert} \text{alert\_type} \mathbin{\Vert} \text{entity\_key})[:24]$$

- **Excluded from identity:** Nonce tokens, random UUIDs, request IDs, trace IDs, timestamps.
- **Included in identity:** Organization ID, Assessment ID, Alert Type, and Entity Key (e.g. `factor_id` for critical factor detection).
- **Idempotency Guarantee:** Reprocessing the same assessment or receiving the same input payload repeatedly resolves to the exact same `alert_id`. In `RiskEvaluationService.evaluate_and_persist`, notifications are checked for existing records prior to insert, ensuring zero duplicate notifications on retries or replay.

---

## 9. Historical Triggers

Reuses `HistoricalRiskComparator.compare(current, previous)` from Phase 7 Step 5:
- Score deltas and direction (`INCREASING`, `DECREASING`, `STABLE`).
- Level transitions (`LOW -> MEDIUM -> HIGH -> CRITICAL`).
- Factor delta tracking.
- Source conflict emergence.
- Evidence quality transitions.

---

## 10. Factor Triggers

When an individual contributor has `severity == RiskLevel.CRITICAL`:
- Evaluated against previous assessment's critical factors to suppress repeat alerts for unchanged persistent factors.
- Newly emerging critical factors generate `CRITICAL_FACTOR_DETECTED`.
- Factor ID and factor-level evidence IDs are preserved on the alert.

---

## 11. Conflict Triggers

When conflicting signals from different sources or providers are detected:
- Evaluates `conflicts` array in `RiskAssessment`.
- If conflict count increases from previous assessment, `NEW_CONFLICT` is generated with `WARNING` severity.
- Details such as conflicting factors, providers, and reasons are preserved in alert metadata without automated deletion or suppression of conflicting signals.

---

## 12. Quality Triggers

When assessment reliability degrades:
- Detects transitions in `limitations` (e.g. uncorroborated single source, stale evidence, or missing fields).
- Triggers `QUALITY_DEGRADED` alert with `WARNING` severity.
- Explains exactly which quality limitations emerged.

---

## 13. Evidence Traceability

Every `RiskAlert` is fully traceable:
- `assessment_id` links to the authoritative assessment record.
- `factor_id` specifies the exact contributing factor (for factor-level alerts).
- `evidence_ids` links up to 5 deterministic evidence identifiers (`evi_<hash>`).
- Metadata captures threshold values, previous scores, driver names, and conflict details.

---

## 14. Notification Integration

The system adheres strictly to the existing schema by mapping `RiskAlert` objects into the existing `Notification` model:
- `id`: Deterministic alert ID (`alt_<hash>`).
- `org_id`: Tenant organization ID.
- `user_id`: None (broadcast/tenant-wide operational alert for the organization).
- `category`: `"RISK_ALERT"`.
- `title`: Deterministic summary header (e.g. `"[CRITICAL] Risk score reached CRITICAL threshold at 88.5"`).
- `summary`: Factual trigger explanation with score delta and level transitions.
- `severity`: Alert severity string (`"INFO"`, `"WARNING"`, `"CRITICAL"`).
- `data_json`: Complete serializable `RiskAlert` domain object for full fidelity reconstruction via `RiskAlertNotificationAdapter.from_notification_model()`.

---

## 15. Transaction Behavior

Alerts and notifications are persisted within the exact same database transaction as the risk assessment:

$$\text{BEGIN} \to \text{Persist Assessment} \to \text{Persist Factors} \to \text{Evaluate Alert Rules} \to \text{Persist Notifications} \to \text{Persist Audit Logs} \to \text{COMMIT}$$

- If any step fails (e.g. foreign key error or constraint violation), the entire transaction rolls back cleanly via `UnitOfWork`.
- Zero orphaned notifications or audit logs exist without their triggering assessment.

---

## 16. Tenant Isolation

Tenant boundaries are strictly enforced:
- Alerts are partitioned by `org_id`.
- The API enforces `context.organization_id` on all alert queries.
- Client-supplied organization parameters can never override authenticated tenant session context.
- Cross-tenant retrieval, listing, or acknowledgement returns `404 Not Found`.

---

## 17. Security & Secret Scrubbing

- Alert titles, summaries, and trigger reasons are generated strictly from sanitized domain data.
- API keys, authorization bearer tokens, passwords, and private secrets are scrubbed before alert creation.
- Raw external provider payloads are rejected at the service boundary (`NormalizedRiskSignal` is required).

---

## 18. Observability

Structured logging and audit entries capture:
- Evaluation requests and completion.
- Alert generation events (`action="ALERT_TRIGGERED"`) in `AuditLog`.
- Alert acknowledgement events (`action="ALERT_ACKNOWLEDGED"`) in `AuditLog`.
- Correlation IDs (`request_id`, `org_id`, `assessment_id`, `alert_id`) preserved across logs.

---

## 19. Alert Retrieval API

Integrated into existing endpoints with backward compatibility:
- `GET /api/v1/risk-assessments/alerts` — Paginated list of tenant alerts with optional filtering by `status`, `severity`, `alert_type`, and `assessment_id`.
- `GET /api/v1/risk-assessments/alerts/{alert_id}` — Retrieve specific alert by ID (tenant isolated).
- `PATCH /api/v1/risk-assessments/alerts/{alert_id}/acknowledge` — Acknowledge an open alert (updates notification `is_read = True`, logs audit record).
- `GET /api/v1/risk-assessments/{id}/alerts` — List alerts generated by a specific assessment.

---

## 20. Acknowledgement Behavior

- Marking an alert as acknowledged updates `is_read = True` on the underlying `Notification` record and sets `acknowledged_at` and `acknowledged_by` in `data_json`.
- Logs an immutable `AuditLog` entry with action `"ALERT_ACKNOWLEDGED"`.
- Immutability guarantee: The historical `RiskAssessment` is never mutated when alerts are acknowledged or resolved.

---

## 21. Alert Storm Protection

- **Semantic Alert Fingerprinting:** Identical evaluations yield identical alert IDs, preventing duplicate inserts.
- **State-Transition Gating:** Alerts trigger on threshold crossing, not on sustained elevated states.
- **Critical Factor Deduplication:** Unchanged critical factors from the prior assessment are filtered out.
- **Threshold Gating for Driver Changes:** Primary driver changes only trigger alerts when overall risk is at or above MEDIUM (`>= 30.0`).

---

## 22. Testing Summary

- **Phase 7 Step 6 Focused Suite:** 76 tests (`apps/api/tests/test_phase7_risk_alerts_escalation.py`) — 100% passing.
- **Phase 7 Cumulative Suite:** 390 tests (Steps 1–6) — 100% passing.
- **Full Test Suite:** 1,328 passed, 1 skipped, 0 failures across the entire application.

---

## 23. Explicit Non-Goals

The following capabilities are strictly forbidden in Phase 7 Step 6 and are reserved for later roadmap phases:
- **No Machine Learning (ML) or predictive forecasting.**
- **No Large Language Models (LLM), RAG, LangGraph, or Bedrock.**
- **No Bayesian inference or probabilistic black-box modeling.**
- **No Autonomous Operational Actions:**
  - Zero shipment rerouting.
  - Zero order or shipment cancellation.
  - Zero automated supplier switching.
  - Zero automated carrier dispatching.
  - Zero automated execution of mitigation recommendations.
