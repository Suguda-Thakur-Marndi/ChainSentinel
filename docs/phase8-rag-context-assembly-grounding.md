# Phase 8 — RAG: Context Assembly, Grounding & Citation Integrity (Step 5)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "Phase 8 Step 5 establishes deterministic context assembly, domain entity grounding anchors,
> authentic citation integrity certification, context token budgeting with synchronized pruning,
> untrusted data demarcation, and audit logging.
> It does NOT implement LLM generative answer synthesis, LangGraph state machines, or autonomous action agents.
> The deterministic Phase 7 Risk Engine remains solely authoritative for risk scoring."

---

## 1. Authoritative Objective & Scope

Phase 8 Step 5 implements **RAG Context Assembly, Grounding & Citation Integrity** for RiskWise 2.0.
Building directly upon Step 1 (contracts & trust boundaries), Step 2 (ingestion & chunking), Step 3 (embeddings & vector store), and Step 4 (retrieval & similarity search), Step 5 provides the authoritative bridge connecting retrieved knowledge chunks to RiskWise enterprise entities (`RiskAssessment`, `Supplier`, `Shipment`, `Warehouse`, `Factory`, `Port`, `Route`), guaranteeing 100% authentic citations with zero hallucinated quotes, enforcing token budgets, preserving deterministic rankings, and keeping retrieved data passive and safe.

### Strict Invariants
1. **Source Trust**: Assembled context is permitted ONLY from sources compliant with the `DataTrustBoundary`.
2. **Provenance Preservation**: Every chunk carries unbroken provenance (`document_id`, `chunk_id`, `chunk_index`, `retrieval_id`, `similarity_score`, `rank`).
3. **Citation Integrity**: Every citation maps deterministically to an authentic retrieved chunk (`citation.chunk_id == chunk.chunk_id`, `citation.document_id == chunk.document_id`, `citation.organization_id == context.organization_id`).
4. **Tenant Isolation**: Strict isolation across queries, results, context, citations, and grounded items.
5. **Prompt Injection Quarantine**: Flagged injection content is explicitly marked as `UNSAFE_CONTENT` and quarantined inside XML CDATA envelopes; it is never treated as instructions.
6. **Deterministic Assembly**: Identical inputs yield identical context IDs, citation IDs, and ordered items.
7. **Grounding Status**: Strict 4-state deterministic classification (`GROUNDED`, `PARTIALLY_GROUNDED`, `UNGROUNDED`, `UNSAFE_SOURCE`).
8. **Explicit Limitations**: Budget-truncated evidence is explicitly recorded under `context.limitations`.

### Strict Boundary with Deterministic Risk Engine
- **RAG provides contextual knowledge; Phase 7 Risk Engine provides deterministic risk scoring.**
- RAG never overwrites, computes, or modifies `RiskAssessment` composite scores, risk levels, factor weights, or confidence scores.
- RAG provides auditable, cited background information (port operating protocols, supplier contingency manuals, shipping advisories) that downstream human analysts or future AI reasoning layers can inspect alongside deterministic risk scores.

---

## 2. Architectural Data Flow & Provenance Chain

```
Document (Ingested & Parsed)
    ↓
Document Chunk (Chunked & Fingerprinted)
    ↓
Embedding (1536-dim Vector with Deterministic Hash)
    ↓
Retrieved Chunk (Ranked, Scored, Provenance-Tagged)
    ↓
[Context Assembly Pipeline]
  1. Tenant Isolation Verification (query.org == result_set.org == chunk.org)
  2. Grounding Anchor Verification (RiskAssessment, Supplier, Shipment, Facility)
  3. Token Budgeting & Chunk Pruning (ContextBudgetConfig)
  4. Prompt Injection Detection & Quarantine (detect_prompt_injection_indicators)
  5. Deterministic Citation Generation (generate_deterministic_citation_id)
  6. Grounded Items Classification (RETRIEVED_FACT vs UNSAFE_CONTENT)
  7. Grounding Status Computation (GROUNDED / PARTIALLY_GROUNDED / UNGROUNDED / UNSAFE_SOURCE)
  8. Limitations Recording (budget / token pruning disclosures)
  9. Citation Integrity Certification (validate_citation_integrity)
 10. Immutable Audit Logging (action="RAG_CONTEXT_ASSEMBLED")
    ↓
Grounded Context Items + Citations (LLM-Ready RAGContext)
```

---

## 3. Core Models & Contracts

### `GroundingStatus` (`api/app/rag/contracts.py`)
Deterministic 4-state evaluation:
- `GROUNDED`: All retrieved chunks are verified safe and fully cite authentic evidence.
- `PARTIALLY_GROUNDED`: Some evidence was retrieved safely, but certain items are truncated by budget or mixed with hostile chunks.
- `UNGROUNDED`: Zero chunks retrieved or evidence missing.
- `UNSAFE_SOURCE`: All retrieved evidence contains detected prompt injection or instructional patterns.

### `GroundedContextItem` (`api/app/rag/contracts.py`)
Structured evidence items categorizing retrieved data:
- `item_id`: Stable identifier.
- `item_type`: `GroundedItemType` (`RETRIEVED_FACT`, `SOURCE_METADATA`, `CITATION`, `LIMITATION`, `UNSAFE_CONTENT`).
- `content`: Text passage.
- `chunk_id`, `document_id`, `organization_id`: Explicit identity linkage.
- `citation_id`, `citation_key`: Deterministic citation binding.
- `provenance`: Full `RetrievalProvenance` object.
- `is_safe`: Boolean flag (`False` if injection detected).

### `generate_deterministic_citation_id` (`api/app/rag/contracts.py`)
Generates UUIDv5 using namespace `6ba7b810-9dad-11d1-80b4-00c04fd430c8` and format:
`"{organization_id}:citation:{document_id}:{chunk_id}:{retrieval_id}"`
Never includes timestamps, random UUIDs, or model outputs.

### `validate_citation_integrity` (`api/app/rag/grounding.py`)
Strict citation verification function:
```python
validate_citation_integrity(
    context: RAGContext,
    retrieved_result_set: RetrievalResultSet,
    strict: bool = True,
) -> CitationVerificationResult
```
Rejects:
- Unknown chunk IDs or document IDs.
- Mismatched document/chunk relationships.
- Cross-tenant citations or chunks.
- Missing provenance metadata.
- Citations to filtered-out chunks.
- Citations with fabricated excerpt text.

### `GroundingAnchor` (`api/app/rag/grounding.py`)
Encapsulates domain entity coordinates to tie contextual knowledge to authoritative RiskWise business entities:
- `organization_id`: Tenant boundary identifier (mandatory).
- `signal_id`: Associated `NormalizedRiskSignal` ID (optional).
- `assessment_id`: Associated `RiskAssessment` ID (optional).
- `entity_type`: Entity domain type (`"SUPPLIER"`, `"SHIPMENT"`, `"FACILITY"`, `"WAREHOUSE"`, `"FACTORY"`, `"PORT"`, `"ROUTE"`).
- `entity_id`: Entity database primary key.
- `extra_anchors`: Additional structured anchors (scrubbed against credential leakage).

### `ContextBudgetConfig` (`api/app/rag/grounding.py`)
Governs token limits, chunk counts, and truncation rules:
- `max_context_tokens`: Token budget ceiling (default: 4000, bounds: 10..32000).
- `max_chunks`: Maximum chunks to include (default: 10, bounds: 1..50).
- `preserve_minimum_chunks`: Guarantee of minimum high-ranked chunks (default: 1).
- `truncation_strategy`: Pruning priority (`"RANK_PRIORITY"`).

---

## 4. Prompt Injection & Trust Boundary Handling

- **Data, Not Instructions**: Retrieved text is always demarcated inside `<retrieved_context>` envelopes with `trust="UNTRUSTED_PASSIVE_DATA"` and XML CDATA blocks.
- **Pattern Detection**: `detect_prompt_injection_indicators()` checks for:
  - `ignore previous instructions`
  - `disregard prior rules/prompts/instructions/policy`
  - `system prompt:` / `system message:`
  - `you are now an unrestricted`
  - `override instructions`
  - `call the ... tool` / tool invocation patterns
  - `<script>`, `eval(`, `exec(`
- **Quarantine, Not Deletion**: Flagged chunks are preserved with provenance, tagged with `prompt_injection_flags`, classified as `GroundedItemType.UNSAFE_CONTENT`, and assigned `is_safe=False`.

---

## 5. Audit Logging & Observability

Context assembly automatically records an append-only audit log entry:
- **`action`**: `"RAG_CONTEXT_ASSEMBLED"`
- **`resource_type`**: `"RAGContext"`
- **`resource_id`**: Deterministic context UUID
- **`after_json`**: Safe telemetry containing:
  - `context_id`
  - `retrieval_id`
  - `query_id`
  - `grounding_status`
  - `citation_count`
  - `chunk_count`
  - `context_units` (token count)
  - `grounding_signal_id`
  - `grounding_assessment_id`
  - `injection_risk_detected`

All metadata is validated through `validate_no_secrets_in_metadata()` to guarantee zero leakage of API keys, bearer tokens, or provider credentials.

---

## 6. System Invariants & Schema Compliance

- **Database Tables**: Exactly **34 tables** preserved in `Base.metadata.tables`. Zero migrations, zero schema drift.
- **OpenAPI Surface**: Exactly **60 paths**, **96 operations**, **104 schemas**. No unauthorized public endpoints added.
- **Risk Engine Invariance**: Phase 7 scoring rules, factor evaluations, and recommendation matrix remain 100% intact and untouched.

---

## 7. Verification & Test Suite

The Phase 8 Step 5 test suite is implemented in:
`api/tests/test_phase8_rag_context_assembly_grounding.py`

Total Tests: **58 passed**, covering 11 groups:
- **Group A**: Context Assembly (happy path, empty retrieval, single result, deterministic ranking preservation, metadata preservation)
- **Group B**: Citation Integrity Certification (direct valid, unknown chunk, unknown document, doc-chunk mismatch, cross-tenant citation, filtered-out chunk, malformed citation, missing provenance, chunk index mismatch, non-strict verification reporting)
- **Group C**: Grounding Status Evaluation (`GROUNDED`, `UNGROUNDED`, `UNSAFE_SOURCE`, `PARTIALLY_GROUNDED` via mixed/truncated chunks)
- **Group D**: Provenance Chain Survivability (unbroken document → chunk → embedding → retrieved chunk → citation/grounded item)
- **Group E**: Prompt Injection & Untrusted Data Boundaries (tool invocation patterns, system messages, policy disregard, CDATA enclosure)
- **Group F**: Tenant Isolation (cross-tenant chunks, citations, grounded items, queries, and users rejected)
- **Group G**: Determinism (multi-run context ID, citation ID, and ordering stability)
- **Group H**: Context Budget & Limitation Reporting (chunk ceiling truncation, token exhaustion, explicit limitation strings)
- **Group I**: Fail-Closed Behavior & Error Handling (tampered chunk reference, empty excerpt, typed exceptions)
- **Domain Anchors**: RiskAssessment, Supplier, Shipment, Warehouse, Factory, Port, Route grounding anchors
- **System Invariants**: 34 DB tables, 60 OpenAPI paths, 96 operations

---

## 8. Full Regression Results

- **Phase 8 Step 5 Suite**: 58 passed, 0 failed
- **Phase 8 Steps 1–5 Suite**: 155 passed, 0 failed
- **Phase 7 Risk Engine Suite**: 541 passed, 0 failed
- **Phase 6 Normalization Suite**: 152 passed, 0 failed
- **Phase 5 Ingestion Suite**: 138 passed, 0 failed
- **Full Backend Test Suite**: 1,608 passed, 1 skipped, 0 failed
- **Database Tables**: 34 (0 drift, 0 migrations)
- **OpenAPI Surface**: 60 paths, 96 operations, 104 schemas

---

## 9. Explicit Non-Goals

The following areas are intentionally NOT implemented in Phase 8 Step 5:
- **NO LLM Generative Answer Synthesis**: No Claude, Bedrock text generation, or prompt execution.
- **NO LangGraph State Machines**: Multi-agent graph orchestrations belong to Phase 9.
- **NO Autonomous Action Agents**: Automated physical or transactional actions belong to Phase 10+.
- **NO Risk Engine Overwrites**: RAG context provides knowledge, never overwrites deterministic risk assessments.
- **NO Database Schema Modifications**: Reuses the 34 authoritative PostgreSQL tables without modifications.
