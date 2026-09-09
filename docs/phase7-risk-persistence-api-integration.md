# RiskWise 2.0 — Phase 7 Step 4: Risk Persistence & API Integration

## 1. Architecture

Phase 7 Step 4 bridges the pure domain layer of the Phase 7 deterministic Risk Engine with the PostgreSQL persistence layer and FastAPI REST presentation tier.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        HTTP Client / API Consumer                      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP Request (Cookie Session)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                  Authentication & Tenant Context Layer                 │
│         (AuthenticatedContext: org_id, user_id, roles, RBAC)           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Validated Server Tenant
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      RiskEvaluationService                             │
│  - Strict input boundary: Rejects raw payloads                         │
│  - Creates RiskEvaluationContext (Server Org ID enforced)               │
│  - Executes BaselineRiskEngine (9 registered domain evaluators)        │
│  - Assembles RiskAssessment & deterministic rule-based explanation     │
│  - Checks idempotency cache by SHA-256 semantic fingerprint            │
│  - Orchestrates transactional persistence via UnitOfWork               │
└───────────────────┬────────────────────────────────▲───────────────────┘
                    │                                │
                    ▼                                │
┌───────────────────────────────────────┐            │
│         BaselineRiskEngine            │            │
│  - Registered Evaluators (Domain)     │            │
│  - BaselineRiskScoreAggregator        │            │
│  - FactorContributions & Explanations │            │
└───────────────────┬───────────────────┘            │
                    │ Pure Domain Models             │
                    ▼                                │
┌────────────────────────────────────────────────────┴───────────────────┐
│               RiskAssessmentPersistenceAdapter (Boundary)              │
│  - to_orm(assessment, risk_id) -> ORMRiskAssessment, ORMRiskFactors    │
│  - from_orm(orm_assessment, orm_factors) -> RiskAssessment             │
│  - to_detail_dict(orm_assessment) -> Flat presentation dictionary      │
│  - scrub_secrets(data) -> Redacts keys, tokens, auth headers           │
└───────────────────┬────────────────────────────────────────────────────┘
                    │ SQLAlchemy ORM Models
                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                Repositories & UnitOfWork (PostgreSQL)                  │
│  - RiskAssessmentRepository (Tenant-partitioned queries & inserts)     │
│  - RiskFactorRepository (Batch factor persistence & lineage)           │
│  - RiskRepository (Parent risk entity score & severity updates)        │
│  - AuditLogRepository (Structured audit logging)                       │
│  - UnitOfWork (Atomic BEGIN / COMMIT / ROLLBACK)                       │
└────────────────────────────────────────────────────────────────────────┘
```

The runtime flow guarantees that:
1. Domain contracts (`RiskAssessment`, `RiskFactor`, `RiskEvidence`, `RiskScore`) remain 100% decoupled from SQLAlchemy ORM, database sessions, and engine drivers.
2. The REST API exposes structured, typed responses without leaking ORM internals, database IDs, connection strings, or credentials.
3. Every step in the assessment remains fully traceable:
   $$\text{RiskAssessment} \longrightarrow \text{RiskScore} \longrightarrow \text{RiskFactor} \longrightarrow \text{RiskEvidence} \longrightarrow \text{NormalizedRiskSignal}$$

---

## 2. Persistence Boundary

The persistence boundary is strictly maintained by `RiskAssessmentPersistenceAdapter` (`apps/api/app/risk_engine/persistence.py`).

- **Domain Independence**: Domain classes in `apps/api/app/risk_engine/contract.py`, `evidence.py`, `scoring.py`, and `explainability.py` do not import SQLAlchemy or depend on database sessions.
- **Bi-directional Mapping**:
  - `to_orm(assessment: RiskAssessment, risk_id: str)`: Transforms the in-memory domain assessment into database ORM entities (`app.models.risk.RiskAssessment` and `app.models.risk.RiskFactor`), serializing structured findings (contributions, primary driver, evidence, limitations, source summary, fingerprint).
  - `from_orm(orm_assessment: ORMRiskAssessment, orm_factors: List[ORMRiskFactor])`: Fully reconstructs the immutable domain `RiskAssessment` object with original identities, scores, factors, and evidence items.
  - `to_detail_dict(orm_assessment)`: Prepares the flat JSON-serializable dictionary matching `RiskAssessmentDetailResponse` for client presentation.
- **Secret Redaction**: Embedded `scrub_secrets` traverses all payload trees and redacts sensitive tokens, credentials, and Authorization headers.

---

## 3. Repository and Service Responsibilities

Responsibilities are clean and non-overlapping:

| Layer / Component | Primary Responsibilities | Strict Disallowed Actions |
|---|---|---|
| **`RiskEvaluationService`** | Coordinates evaluation workflow: input validation, context assembly, engine invocation, idempotency checks, transactional unit of work orchestration, domain/detail retrieval. | Does NOT perform manual scoring mathematics, signal normalization, or direct database DDL. |
| **`RiskAssessmentPersistenceAdapter`** | Encapsulates mapping logic between pure Pydantic domain models and SQLAlchemy ORM models. Sanitizes secrets. | Does NOT manage database sessions, execute SQL queries, or initiate commits/rollbacks. |
| **`RiskAssessmentRepository`** | Executes database queries strictly partitioned by `org_id`. Provides `get_assessment`, `find_by_fingerprint`, `get_latest_for_risk`, `get_latest_for_entity`, `get_latest_for_org`, `list_assessments_for_org`. | Does NOT bypass tenant filtering; never queries solely by unpartitioned ID. |
| **`UnitOfWork`** | Guarantees atomic transaction lifecycle (session management, commit on success, rollback on exception). | Does NOT contain domain business logic. |

---

## 4. Assessment Persistence

Persisted risk assessments adapt to the authoritative existing `risk_assessments` table schema without requiring any schema changes or migrations.

- **Table**: `risk_assessments`
- **Columns Mapped**:
  - `id`: Deterministic assessment UUIDv5 or supplied assessment ID.
  - `org_id`: Authoritative server-side organization ID.
  - `risk_id`: Target risk entity ID.
  - `assessor_type`: `"DETERMINISTIC_ENGINE"` (or platform assessor type enum).
  - `assessor_id`: Evaluator version identifier (`"baseline-engine-v1.0"`).
  - `methodology`: Scoring methodology (`"DETERMINISTIC_BASELINE"`).
  - `score`: Composite bounded risk score $[0.0, 100.0]$.
  - `confidence`: Certainty score $[0.0, 1.0]$.
  - `created_at`: UTC evaluation timestamp.
  - `findings`: JSONB structured envelope preserving:
    - `assessment_id`
    - `score` & `risk_level`
    - `primary_driver` & `primary_factor_id`
    - `fingerprint` (SHA-256 semantic fingerprint)
    - `factor_contributions`
    - `source_summary`
    - `limitations` & `conflicts`
    - `source_signals`
    - `explanation`
    - `evidence` (canonical signal trace references)

---

## 5. Factor Persistence

Each factor evaluated by the registered evaluators is persisted to the existing `risk_factors` table.

- **Table**: `risk_factors`
- **Columns Mapped**:
  - `id`: Deterministic factor UUIDv5 (`f"factor:{org}:{evaluator}:{signal_id}"`).
  - `org_id`: Tenant organization ID.
  - `risk_id`: Associated risk entity ID.
  - `factor_type`: Evaluation factor type (`WEATHER_DISRUPTION`, `TRAFFIC_CONGESTION`, `AIS_VESSEL_ANOMALY`, etc.).
  - `name`: Human-readable descriptive name.
  - `weight`: Aggregator weight applied ($w_k$).
  - `severity`: Standard severity level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - `source`: Domain evaluator identifier.
  - `confidence`: Factor confidence $[0.0, 1.0]$.
  - `description`: Evaluator description.
  - `evidence_json`: JSONB column preserving:
    - `raw_contribution`
    - `weighted_contribution`
    - `rank`
    - `evidence_ids`
    - `signal_fingerprint`
    - `domain`
    - `evidence` references

---

## 6. Evidence Persistence

Evidence linkage is fully preserved without duplicating raw vendor payloads.

- `RiskEvidence` items are linked bi-directionally to their evaluating `RiskFactor` via `evidence_ids`.
- Retained evidence metadata includes:
  - `evidence_id`: Deterministic UUIDv5 (`f"evidence:{org}:{signal_id}"`).
  - `signal_id`: Phase 6 `NormalizedRiskSignal` ID.
  - `relevance`: Score $[0.0, 1.0]$ and classification (`PRIMARY_DRIVER`, `CORROBORATING`, `BACKGROUND`).
  - `source` & `source_type`: Data provider (`OPENWEATHER`, `TOMTOM`, etc.) and observation type (`REAL`, `ESTIMATED`, `SIMULATED`).
  - `quality`: Canonical quality level (`VALID`, `PARTIAL`, `INVALID`).
  - `location`: Structured coordinates and location name.
  - `observed_at`: Source timestamp in UTC.
  - `limitations`: Explanatory caveats.
- Secrets, credentials, API tokens, and Authorization headers are actively scrubbed and prevented from entering persistence.

---

## 7. Normalized Signal References

The persistence and service layers enforce Phase 6 `NormalizedRiskSignal` as the canonical risk engine input.

- **Rejected Inputs**: Raw provider dictionaries, raw external responses (OpenWeather, TomTom, AISStream, OpenSky, GTFS-RT, Karrio, Tavily), unvalidated payloads, and non-canonical objects are rejected with HTTP 422.
- **Reference Preservation**: Signals are referenced through their `signal_id`, `fingerprint`, `domain`, and canonical metadata.

---

## 8. Transaction Behavior

Assessment writes are strictly atomic. The evaluation workflow executes inside a `UnitOfWork` context manager:

```python
with self.uow:
    # 1. Resolve or create parent Risk entity
    # 2. Update parent Risk metrics (score, severity, updated_at)
    # 3. Persist RiskAssessment
    # 4. Persist RiskFactors
    # 5. Record AuditLog
    self.uow.commit()
```

- **Atomic Failure Handling**: If an error occurs during factor persistence, evidence serialization, parent risk update, or audit logging, `uow.rollback()` is executed immediately.
- **No Partial Records**: An incomplete or partial assessment is never committed or visible to queries.

---

## 9. Idempotency

Idempotency is achieved using the deterministic SHA-256 assessment fingerprint computed from the semantic core of the evaluation (tenant ID, score, severity, sorted factors, and sorted signal fingerprints).

- **Cache Check**: Before persisting, `RiskEvaluationService` queries `RiskAssessmentRepository.find_by_fingerprint(org_id, fingerprint)`.
- **Match Hit**: If an identical assessment exists for the tenant:
  - The write is skipped.
  - The existing persisted assessment is retrieved.
  - The API returns HTTP 200 OK (rather than HTTP 201 Created).
  - No duplicate database rows are created.
- **Independence**: The idempotency key does not depend on request IDs, trace IDs, random UUIDs, or transient clock ticks.

---

## 10. Temporal Semantics

- **Point-in-Time Evaluations**: Each assessment represents an immutable snapshot of risk at a specific point in time.
- **Historical Immutability**: New assessments for the same entity do not overwrite previous records; both remain queryable with their original `created_at` timestamps.
- **Latest Querying**: Clients can retrieve the most recent assessment for a scope, entity, or risk via `GET /api/v1/risk-assessments/latest` or via sorted listing queries (`sort=-created_at`).

---

## 11. API Integration

Endpoints are integrated into the existing `/api/v1/risk-assessments` router (`apps/api/app/api/v1/endpoints/risk_assessments.py`):

1. **`POST /api/v1/risk-assessments/evaluate`**:
   - Evaluates a list of `NormalizedRiskSignal`s with the deterministic engine and persists the result.
   - Requires `Analyst` role or higher.
   - Returns HTTP 201 Created on new assessment, HTTP 200 OK on idempotent cache hit.
2. **`GET /api/v1/risk-assessments/latest`**:
   - Retrieves the most recent assessment within the tenant partition, optionally filtered by `scope`, `scope_entity_id`, or `risk_id`.
   - Requires `Viewer` role or higher.
3. **`GET /api/v1/risk-assessments/{id}/detail`**:
   - Retrieves full assessment detail including factor contributions, evidence traces, and source summaries.
   - Requires `Viewer` role or higher.
4. **Existing Endpoints Maintained**:
   - `GET /api/v1/risk-assessments`: Paginated listing with tenant filtering.
   - `POST /api/v1/risk-assessments`: Direct assessment creation.
   - `GET /api/v1/risk-assessments/{id}`: Single assessment retrieval by ID.

---

## 12. Authentication

- **Session Authentication**: All endpoints require a valid `riskwise_session` HttpOnly cookie.
- **Unauthenticated Handling**: Requests without a valid session cookie receive HTTP 401 Unauthorized (`MISSING_SESSION_COOKIE` or `INVALID_SESSION`).
- **Context Injection**: Authentication dependency resolves `AuthenticatedContext` (user ID, organization ID, user role) from the database session store.

---

## 13. Authorization

- **RBAC Enforcement**:
  - `POST /api/v1/risk-assessments/evaluate`: Restricted to `Analyst`, `OpsManager`, `RiskManager`, and `Admin`. `Viewer` role receives HTTP 403 Forbidden.
  - `GET` endpoints: Accessible to all authorized roles (`Viewer`, `Analyst`, `OpsManager`, `RiskManager`, `Admin`).

---

## 14. Tenant Isolation

- **Server-Side Authority**: The organization ID is extracted exclusively from the authenticated session context (`context.org_id`).
- **Client Org Override Disallowed**: Any `organization_id` or `org_id` supplied in request payloads or query parameters by untrusted clients is ignored or validated against the server session.
- **Cross-Tenant Masking**:
  - Attempts to retrieve another organization's assessment return HTTP 404 Not Found (masking existence).
  - List queries strictly partition rows by `WHERE org_id = :authenticated_org_id`.
  - Signal evaluation validates that signals belong to the tenant or global partition; cross-tenant signal evaluation is rejected.

---

## 15. Auditability

Every deterministic evaluation and persistence operation records an immutable audit trail:
- **Table**: `audit_logs`
- **Fields Logged**:
  - `org_id`: Tenant organization ID.
  - `user_id`: Authenticated user ID.
  - `action`: `"RISK_ASSESSMENT_EVALUATED"`.
  - `entity_type`: `"RISK_ASSESSMENT"`.
  - `entity_id`: Assessment ID.
  - `after_json`: Assessment metrics, score, primary driver, and signal count.
  - `created_at`: UTC timestamp.

---

## 16. Observability

- **Correlation Tracing**: Captures `request_id` and `trace_id` when present in context.
- **Audit Logging**: Detailed audit records track every evaluation event.
- **Error Categories**: Typed exceptions (`NotFoundError`, `AuthorizationError`, `InvalidInputError`, `DuplicateAssessmentError`, `PersistenceError`) map cleanly to standardized error envelopes.

---

## 17. Error Handling

Standardized error response envelopes ensure consistency across the API:

| Error Type | HTTP Status | Error Code | Description |
|---|---|---|---|
| Missing Auth | 401 | `MISSING_SESSION_COOKIE` | No valid session cookie found |
| Insufficient Role | 403 | `INSUFFICIENT_PERMISSIONS` | Viewer role attempted evaluation |
| Cross-Tenant / Non-existent | 404 | `ASSESSMENT_NOT_FOUND` | Assessment not found in tenant partition |
| Invalid Signal Format | 422 | `UNPROCESSABLE_ENTITY` | Unvalidated or malformed signal payload |
| Cross-Tenant Signal | 422 | `TENANT_MISMATCH` | Signal tenant conflicts with server context |
| Idempotent Duplicate | 200 | `OK` | Returns existing assessment seamlessly |

Database internal errors and credentials are never leaked in error messages.

---

## 18. Response Contract

`RiskAssessmentDetailResponse` provides complete transparency:

```json
{
  "id": "asmt_550e8400-e29b-41d4-a716-446655440000",
  "assessment_id": "asmt_550e8400-e29b-41d4-a716-446655440000",
  "org_id": "org_alpha",
  "risk_id": "risk_123",
  "assessor_type": "DETERMINISTIC_ENGINE",
  "assessor_id": "baseline-engine-v1.0",
  "methodology": "DETERMINISTIC_BASELINE",
  "score": 67.5,
  "risk_level": "HIGH",
  "probability": null,
  "impact": null,
  "confidence": 0.85,
  "primary_factor_id": "factor_weather_storm_001",
  "primary_driver": {
    "factor_id": "factor_weather_storm_001",
    "name": "Severe Weather Disruption",
    "severity": "HIGH",
    "contribution": 35.0
  },
  "factor_contributions": [
    {
      "factor_id": "factor_weather_storm_001",
      "raw_contribution": 40.0,
      "weighted_contribution": 35.0,
      "rank": 1
    }
  ],
  "factors": [ ... ],
  "evidence": [ ... ],
  "source_summary": {
    "total_sources": 2,
    "real_count": 2,
    "estimated_count": 0,
    "simulated_count": 0,
    "providers": ["OPENWEATHER", "TOMTOM"]
  },
  "limitations": [],
  "conflicts": [],
  "source_signals": ["sig_weather_001"],
  "explanation": {
    "summary": "High risk driven primarily by Severe Weather Disruption.",
    "key_drivers": ["Severe Weather Disruption"],
    "conflicts": [],
    "limitations": []
  },
  "fingerprint": "a3f5b8...",
  "findings": { ... },
  "created_at": "2026-09-09T12:00:00Z"
}
```

*Note: `probability` and `impact` are strictly `null` in Phase 7.*

---

## 19. Testing & Verification

Step 4 implementation is backed by a comprehensive automated test suite:

- **Step 4 Focused Tests (`apps/api/tests/test_phase7_risk_persistence_api.py`)**:
  - **64 tests passed** (0 failures).
  - Covers: Repository methods, Adapter mapping, Bi-directional linkage, Secret scrubbing, Transaction rollback on failure, UnitOfWork safety, Idempotent deduplication, Cross-tenant isolation matrix, RBAC permissions, API evaluation, API retrieval, Bounded scoring, Determinism, and Security.
- **Phase 7 Step 3 Tests (`apps/api/tests/test_phase7_risk_evidence_assessment.py`)**: 61 passed.
- **Phase 7 Step 2 Tests (`apps/api/tests/test_phase7_baseline_scoring.py`)**: 65 passed.
- **Phase 7 Step 1 Tests (`apps/api/tests/test_phase7_risk_engine_contracts.py`)**: 58 passed.
- **Phase 6 Tests (`test_phase6_*.py`)**: 152 passed.
- **Phase 5 Tests (`test_phase5_final_validation.py`, `test_canonical_external_events.py`)**: 63 passed.
- **Phase 4 API Regression Tests (`test_risk_api.py`)**: 26 passed.
- **Phase 4 Final Validation (`test_phase4_final_validation.py`)**: 12 passed.
- **Database Model Validation (`test_database_validation.py`)**: 31 passed, 1 skipped.
- **Full Backend Pytest Suite**: **1186 passed, 1 skipped** (0 failures).

---

## 20. Explicit Non-Goals

The following technologies and paradigms are strictly out of scope for Phase 7 Step 4:
- **No Machine Learning (ML)** models or heuristic training.
- **No Bayesian inference** or probabilistic graph updates.
- **No Retrieval-Augmented Generation (RAG)** or vector store lookups for risk scoring.
- **No LangGraph** multi-agent state machines (reserved for Phase 9).
- **No Amazon Bedrock** or cloud LLM APIs.
- **No LLM-based risk scoring** or non-deterministic prompt evaluations.
- **No live external provider network calls** from within the risk engine.
- **No frontend UI development** or web application changes.
- **No database schema redesign** or Alembic migrations (the existing 34 tables remain authoritative).
- **No Phase 8 initiation** (Phase 8 remains strictly unstarted).
