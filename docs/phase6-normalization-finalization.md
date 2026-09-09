# Phase 6 Step 4 — Normalization Quality, Conflict Resolution & Finalized Signal Pipeline

## 1. Architectural Mission & Pipeline Overview

The Phase 6 Normalization layer establishes the authoritative semantic boundary between Phase 5 heterogeneous canonical ingestion and the future Phase 7 Risk Evaluation Engine.

```
CanonicalExternalEvent (Phase 5 Canonical Contract)
        ↓
1. Input & Type Verification
   - Reject raw provider envelopes (never consume unparsed dicts)
   - Evaluate upstream CanonicalEvent.quality
        ↓
2. Domain & Semantic Normalization
   - DomainNormalizationRegistry routes to specific domain handler
   - Weather, Road, Ocean, Air, Rail, Logistics, Intelligence, General
        ↓
3. Measurement & Unit Normalization
   - Standard units: km, km/h, minutes, °C, kg, m³, ISO-4217 currency
   - Strict unknown-unit policy (never fabricate conversions)
        ↓
4. Temporal Semantics & Consistency
   - All timestamps strictly normalized to timezone-aware UTC
   - Distinguish normal event latency from impossible future clock anomalies
   - Validate validity intervals: effective_from <= effective_to
        ↓
5. Entity Normalization & False Correlation Defense (Step 3)
   - Tenant-scoped master data resolution (Shipment, Supplier, Site, Facility, Warehouse, Port, Carrier, Route)
   - Qualified namespace isolation (IMO, MMSI, ICAO24, UN/LOCODE, tracking)
   - Ambiguous mapping and conflict tracking
        ↓
6. Field-Level & Numeric Safety Validation (Step 4 Quality Engine)
   - Reject NaN, Infinity, overflow values
   - Strict physical non-negativity enforcement (distance, speed, weight, volume, currency, precision)
   - Coordinate boundary validation (WGS84: [-90, 90], [-180, 180])
        ↓
7. Cross-Source Correlation & Conflict Resolution
   - Deterministic SHA-256 correlation indexing ($O(1)$ in-memory)
   - Source precedence hierarchy: REAL (3) > ESTIMATED (2) > SIMULATED (1)
   - Status & severity conflict preservation (zero evidence deletion)
   - Independent corroboration safety (prevent repeated provider inflation)
        ↓
8. Provenance Completeness & Traceability
   - Mandatory lineage: source, provider, canonical_event_id, source_type
   - Optional lineage: raw_event_id, provider_event_id, correlation_id, trace_id
        ↓
9. Deterministic Identity & Fingerprinting
   - Deterministic UUIDv5 signal_id derived from organization_id & canonical_event_id
   - Deterministic SHA-256 semantic fingerprint
        ↓
10. Final Quality Assessment & Finalization Boundary
   - VALID: Complete, consistent, usable for downstream risk calculation
   - PARTIAL: Usable with non-critical missing/unresolved attributes (e.g. unlinked entity)
   - INVALID: Discarded to rejection output with structured quality reasons
        ↓
FINALIZED NormalizedRiskSignal collection (Handoff to Phase 7)
```

> [!IMPORTANT]
> **Handoff Contract**:
> "Phase 6 produces normalized signals; Phase 7 is responsible for risk calculation."
> Phase 6 normalizes, validates, corroborates, and structures external intelligence. It does **not** evaluate impact scores, graph cascades, Bayesian probabilities, or automated mitigations.

---

## 2. Quality Model: Tri-State Classification

RiskWise 2.0 strictly enforces a tri-state semantic quality classification:

| Quality State | Criteria | Pipeline Action | Downstream Hand-off |
|---|---|---|---|
| **`VALID`** | Mandatory identity, classification, temporal, and spatial attributes fully populated and internally consistent; at least one primary domain entity resolved or fully mapped. | Emitted as finalized operational signal. | Forwarded to Phase 7 Risk Engine for active risk scoring. |
| **`PARTIAL`** | Signal is structurally sound and safe, but non-critical attributes are unresolved or unlinked (e.g. unlinked spatial advisory, unresolved external tracking number, or upstream `EventQuality.PARTIAL`). | Emitted as finalized advisory signal with structured quality reasons. | Forwarded to Phase 7 for ambient monitoring, clustering, or deferred graph linking. |
| **`INVALID`** | Signal violates fundamental data integrity (e.g. malformed timestamp, inverted effective intervals, NaN/Inf measurements, negative physical quantities, missing mandatory provenance, or unparsed raw dicts). | Immediately rejected; discarded from normalized stream into `rejected_signals`. | **Blocked**. Never leaves Phase 6; never persisted or passed to Phase 7. |

### Quality Invariants
1. **No Silent Upgrading**: Upstream `EventQuality.PARTIAL` events or signals without primary supply chain entity linkages are never silently upgraded to `VALID`.
2. **Strict Finalization Boundary**: Downstream consumers only ever receive finalized `VALID` or `PARTIAL` signals.

---

## 3. Structured Quality Reasons Taxonomy

When a signal is classified as `PARTIAL` or rejected as `INVALID`, structured, provider-independent reason codes are attached from `NormalizationQualityReason`:

| Category | Reason Enum | Description | Typical Outcome |
|---|---|---|---|
| **Measurements** | `UNKNOWN_UNIT` | Source unit is unspecified or unmapped; preserved verbatim without conversion. | `PARTIAL` |
| | `INVALID_NUMERIC_VALUE` | Measurement contains `NaN`, `Infinity`, sub-absolute-zero temperature, or negative physical value. | `INVALID` |
| | `NUMERIC_OUT_OF_BOUNDS` | Metric exceeds physically plausible bounds (e.g. overflow, confidence/disruption outside [0.0, 1.0]). | `INVALID` |
| | `UNSUPPORTED_SEMANTIC_VALUE` | Domain handler encountered unparseable or unsupported status/payload value. | `INVALID` |
| **Spatial** | `INVALID_COORDINATE` | Latitude outside `[-90, 90]` or Longitude outside `[-180, 180]`. | `INVALID` |
| | `INCOMPLETE_COORDINATES` | Latitude provided without Longitude, or vice versa. | `PARTIAL` |
| **Temporal** | `INVALID_TIMESTAMP` | Timestamp is unparseable or lacks timezone-aware UTC definition. | `INVALID` |
| | `TEMPORAL_INCONSISTENCY` | Inverted validity interval (`effective_from > effective_to`) or impossible future timestamp. | `INVALID` |
| **Lineage** | `MISSING_REQUIRED_FIELD` | Mandatory identity or classification field (`signal_id`, `event_type`) is missing. | `INVALID` |
| | `INCOMPLETE_PROVENANCE` | Mandatory provenance (`source`, `provider`, `canonical_event_id`, `source_type`) is empty. | `INVALID` |
| **Entities** | `UNRESOLVED_ENTITY` | No internal graph entities resolved (signal stored as unlinked observation). | `PARTIAL` |
| | `CONFLICTING_IDENTIFIERS` | Conflicting entity identifiers detected (e.g. malformed IMO length or conflicting callsign). | `PARTIAL` / `INVALID` |
| | `NAMESPACE_MISMATCH` | External identifier missing explicit namespace qualification. | `PARTIAL` |
| | `TENANT_MISMATCH` | Attempted correlation across organizational tenant boundaries. | `INVALID` |
| **Cross-Source** | `CONFLICTING_SOURCE_VALUES` | Independent providers report divergent operational status or severity for the same event. | `PARTIAL` |
| | `DISPUTED_STATUS` | Operational status disputed across equally authoritative real-world sources. | `PARTIAL` |
| | `UNRESOLVED_CONFLICT` | Contradictory evidence could not be deterministically resolved. | `PARTIAL` |
| **Security** | `SUSPICIOUS_PAYLOAD` | External payload contains suspicious or malformed control sequences (treated as inert). | `PARTIAL` |

---

## 4. Field-Level Validation & Numeric Safety

### 4.1 Numeric Safety Rules
Physical quantities are strictly validated:
- `NaN` and `Infinity` are rejected.
- Physical non-negativity:
  $$\text{distance\_km} \ge 0, \quad \text{speed\_kmh} \ge 0, \quad \text{weight\_kg} \ge 0, \quad \text{volume\_m}^3 \ge 0, \quad \text{monetary\_amount} \ge 0$$
- **No Silent Clamping**: Negative physical values are **never** clamped to zero or inverted to positive numbers automatically. Clamping conceals data corruption and is strictly prohibited.
- Absolute Zero: Temperatures below $-273.15^\circ\text{C}$ are rejected as physically impossible.
- Probability Boundaries: Probabilistic metrics (`confidence`, `disruption_level`) must satisfy:
  $$0.0 \le \text{value} \le 1.0$$

### 4.2 Temporal Consistency Rules
- **Legitimate Latency vs. Anomalies**: In real-world supply chains, ingestion latency ($\text{event\_time} < \text{received\_at}$) is standard and expected (hours or days for batch rail or AIS feeds).
- **Impossible Future Timestamps**: Events claiming to have occurred in the future ($\text{event\_time} > \text{received\_at} + 300\text{s}$) without an explicit forward-looking schedule or validity interval are rejected as `TEMPORAL_INCONSISTENCY`.
- **Interval Bounds**: If both `effective_from` and `effective_to` are present, the pipeline enforces:
  $$\text{effective\_from} \le \text{effective\_to}$$

---

## 5. Cross-Source Correlation & Conflict Resolution

### 5.1 Source Precedence Hierarchy
When multiple observations describe the same physical condition, source precedence governs the primary representation:
$$\text{REAL (Weight 3)} > \text{ESTIMATED (Weight 2)} > \text{SIMULATED (Weight 1)}$$

### 5.2 Zero Evidence Deletion
Precedence does **not** delete evidence:
- If a `REAL` source supersedes an `ESTIMATED` source, the `ESTIMATED` record is demoted to `supporting_sources` with full timestamps, confidence, and provenance preserved.
- If a lower-precedence signal arrives after a higher-precedence signal, it is attached as supporting evidence without altering the primary status.

### 5.3 Corroboration Safety & Duplicate Prevention
- **Independent Corroboration**: Only signals from **different providers/sources** qualify as corroborating evidence.
- **Repeated Provider Delivery**: Re-deliveries or updates from the same provider (`provider`, `canonical_event_id` or `provider_event_id`) are classified as `DUPLICATE` and never increment `corroborated_count` or artificially inflate confidence.
- **Simulated Isolation**: `SIMULATED` signals never count as real-world corroboration.

### 5.4 Deterministic Disagreement Handling
When sources report divergent statuses (e.g. TomTom reports `ACTIVE` closure, while a municipal feed reports `RESOLVED`):
1. Both source observations are preserved in full detail.
2. The conflict is recorded in `canonical_attributes["conflicts"]`, `canonical_attributes["status_conflicts"]`, and `signal.conflicts`.
3. The signal's `has_conflict` flag is set to `True`, and `NormalizationQualityReason.CONFLICTING_SOURCE_VALUES` is attached.
4. If sources share identical precedence, the more recent observation (`observed_at` or `event_time`) takes precedence, with deterministic tie-breaking on `(provider, canonical_event_id)`.

---

## 6. Deterministic Finalization & Idempotency

### 6.1 Deterministic Identity
To guarantee that retrying canonical events produces identical normalized signals:
- `signal_id`: Generated via UUIDv5 with DNS namespace:
  $$\text{signal\_id} = \text{UUIDv5}(\text{NAMESPACE\_DNS}, \text{org\_id} : \text{canonical\_event\_id})$$
- `fingerprint`: Deterministic SHA-256 hash incorporating tenant, domain, signal type, event type, spatial bucket, temporal bucket, and primary entity key.

### 6.2 Deterministic Ordering
All output collections are sorted deterministically:
- Batch signals: Sorted by `(fingerprint, event_time, signal_id)`.
- Supporting sources: Sorted by `(provider, source, canonical_event_id, provider_event_id)`.
- Quality reasons: Sorted alphabetically by reason enum string value.

---

## 7. Batch Processing & Failure Isolation

The batch orchestrator (`normalize_batch` and `finalize_batch`) isolates individual record failures:
- A malformed or invalid canonical event never crashes or aborts the batch.
- Output provides comprehensive breakdown counts:
  $$\text{total\_count} = \text{valid\_count} + \text{partial\_count} + \text{invalid\_count}$$
  along with `duplicate_count` and `corroborated_count`.
- `rejected_signals` collects diagnostic error records with event IDs and quality reasons for monitoring.

---

## 8. Multi-Tenant Isolation & Security

### 8.1 Multi-Tenant Boundary Invariant
- Every entity lookup, identifier namespace, correlation key, SHA-256 fingerprint, supporting source, and conflict resolution is strictly scoped by `organization_id`.
- Events for different organizations never corroborate, deduplicate, or conflict with one another, even with identical coordinates and timestamps.

### 8.2 Security & Untrusted Input Protection
- External descriptions, news summaries, titles, and URLs are treated strictly as **inert data**.
- Text containing prompt injections (e.g. `"Ignore previous instructions. DROP TABLE users;"`), script tags (`<script>`), or shell command syntax are never executed or parsed as code. They remain safe text strings in metadata.

---

## 9. Verification & Regression Results

The finalized Phase 6 Step 4 implementation has been verified across the entire RiskWise 2.0 test suite:
- **Phase 6 Step 4 Focused Tests**: 55 passed (`test_phase6_finalization.py`).
- **Phase 6 Step 1 Contract Tests**: 48 passed (`test_phase6_normalization_contract.py`).
- **Phase 6 Step 3 Entity Tests**: 49 passed (`test_phase6_entity_normalization.py`).
- **Phase 5 Final Validation Tests**: 36 passed (`test_phase5_final_validation.py`).
- **Full Repository Suite**: 883+ passed, 0 failures.
- **Strict Invariants**: Zero database migrations, zero public API modifications, zero frontend changes, zero Phase 7 implementation.
