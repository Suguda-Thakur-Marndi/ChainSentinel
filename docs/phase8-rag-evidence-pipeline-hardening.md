# RiskWise 2.0 — Phase 8 Step 6: RAG Research Evidence Pipeline, End-to-End Hardening & Downstream Integration

## 1. Step 6 Objective
Phase 8 Step 6 provides the authoritative research evidence packaging and end-to-end hardening pipeline for the RiskWise 2.0 Retrieval-Augmented Generation (RAG) subsystem. It bridges certified contextual knowledge and citation integrity (from Step 5) into structured, immutable, and tamper-evident evidence packages (`RAGEvidenceBundle` and `RAGEvidenceItem`) tailored for downstream AI investigation and operational reasoning (targeted for Phase 9 LangGraph Research Agents) while strictly preserving the Phase 7 Risk Engine as the authoritative source of risk truth.

Crucially, Step 6 does **NOT** implement LLM answer generation, autonomous agent execution, or tool calling. Instead, it provides the deterministic, tamper-evident contract boundary that delivers certified, unhallucinated evidence to future reasoning layers.

---

## 2. Architecture & Data Flow
The RAG pipeline strictly preserves the unidirectional enterprise trust boundary:

```
Enterprise Documents (.pdf, .docx, .txt, .json, .html)
        ↓
Document Ingestion Service (Step 2: Safe parsing, deduplication, identity)
        ↓
Deterministic Chunking (Step 2: Token-aware chunking, headings preservation)
        ↓
Vector Embeddings & Storage (Step 3: Normalized vectors, metadata, cosine similarity)
        ↓
Retrieval & Similarity Search (Step 4: Top-K search, multi-tenant isolation, provenance)
        ↓
Context Assembly & Grounding (Step 5: Token budgeting, domain anchors, citation certification)
        ↓
Research Evidence Packaging (Step 6: RAGEvidencePipelineService, 1:1 mapping, tamper-evident bundle)
        ↓
[Future Phase 9 AI Research Agent / Decision Support (No LLMs in Phase 8)]
```

### Data Pipeline Flow
1. **Query & Authentication Ingestion**: Validates query text, tenant context (`current_user_org_id == query.organization_id`), and scans for leaked credentials or secrets.
2. **Semantic & Keyword Retrieval (Step 4)**: Executes `RAGRetrievalService.retrieve()`, returning ranked chunks with unbroken provenance.
3. **Context Assembly & Grounding Certification (Step 5)**: Applies token budgeting (`ContextBudgetConfig`), resolves domain entity anchors (`GroundingAnchor`), and validates citation integrity (`validate_citation_integrity`).
4. **Evidence Item Packaging (Step 6)**: Transforms each grounded context citation into an immutable `RAGEvidenceItem` with a deterministic UUIDv5 identifier, bounded confidence scoring, and CDATA enclosure.
5. **Bundle Synthesis & Integrity Certification**: Bundles items into `RAGEvidenceBundle`, computes SHA-256 `bundle_fingerprint`, and executes strict 1:1 correspondence verification.
6. **Immutable Audit Emission**: Logs `RAG_EVIDENCE_PIPELINE_EXECUTED` to append-only `AuditLog` repository with safe, non-sensitive telemetry.

---

## 3. Input & Output Contracts

### Input Contracts
- `RetrievalQuery`:
  - `query_id: str`: Unique identifier for the query request.
  - `organization_id: str`: Mandatory tenant identifier.
  - `query_text: str`: Search query string (scanned for credential patterns).
  - `top_k: int = 10`: Number of chunks to retrieve (1–100).
  - `similarity_threshold: float = 0.0`: Minimum cosine similarity score.
  - `filter: Optional[RetrievalFilter]`: Optional metadata filters.
- `GroundingAnchor`:
  - `organization_id: str`: Mandatory tenant identifier.
  - `entity_type: Optional[str]`: Domain entity type (`"SUPPLIER"`, `"SHIPMENT"`, `"FACILITY"`, `"PORT"`, `"ROUTE"`).
  - `entity_id: Optional[str]`: Domain entity primary key.
  - `assessment_id: Optional[str]`: Risk assessment primary key.
  - `extra_anchors: Dict[str, Any]`: Additional metadata (validated against secret leakage).
- `ContextBudgetConfig`:
  - `max_context_tokens: int = 4000`: Hard token ceiling for assembled context.
  - `max_chunks: int = 10`: Maximum allowed chunks.
  - `preserve_minimum_chunks: int = 1`: Floor chunks preserved during pruning.

### Output Contracts
- `RAGEvidenceItem`:
  - `evidence_id: str`: Deterministic UUIDv5 identifier (`token: {org_id}:evidence:{doc_id}:{chunk_id}:{retrieval_id}:{context_id}`).
  - `citation_id: str`: Stable citation ID matching context citation.
  - `citation_key: str`: Human-readable key (e.g., `"[1]"`).
  - `document_id: str`: Lineage source document ID.
  - `chunk_id: str`: Lineage source chunk ID.
  - `organization_id: str`: Scoped tenant identifier.
  - `document_title: str`: Document title.
  - `excerpt: str`: Exact excerpt text matching citation.
  - `confidence_score: float`: Calibrated similarity score [0.0, 1.0] (discounted by 50% if hostile injection detected).
  - `item_type: GroundedItemType`: Item taxonomy (`RETRIEVED_FACT`, `UNSAFE_CONTENT`, etc.).
  - `is_safe: bool`: Flag indicating whether chunk is safe from prompt injection.
  - `provenance: RetrievalProvenance`: Unbroken retrieval lineage metadata.
  - `data_envelope: str`: Passive XML CDATA payload.
- `RAGEvidenceBundle`:
  - `bundle_id: str`: Deterministic UUIDv5 identifier (`token: {org_id}:evidence_bundle:{retrieval_id}:{context_id}:{sorted_evidence_ids}`).
  - `organization_id: str`: Tenant identifier.
  - `query_text: str`: Original query string.
  - `context_id: str`: Source RAG context identifier.
  - `retrieval_id: str`: Source retrieval identifier.
  - `grounding_status: GroundingStatus`: Overall grounding status (`GROUNDED`, `PARTIALLY_GROUNDED`, `UNGROUNDED`).
  - `evidence_items: List[RAGEvidenceItem]`: Ordered evidence items.
  - `citations: List[RAGContextCitation]`: 1:1 corresponding citations.
  - `total_evidence_units: int`: Count of evidence items.
  - `bundle_fingerprint: str`: 64-character SHA-256 cryptographic digest.
  - `trust_boundary: DataTrustBoundary`: Security boundary flags.
  - `limitations: List[str]`: Recorded constraints or budget truncation notes.

---

## 4. Trust Boundary & Demarcation
All retrieved text remains strictly **passive DATA** and must never be interpreted as instructions, authorizations, or policies:
- **XML CDATA Demarcation**: All evidence content is encapsulated in `format_rag_data_envelope` with `<![CDATA[ ... ]]>` containers.
- **Instruction Quarantine**: Content attempting instruction injection (e.g., `"SYSTEM OVERRIDE"`, `"ignore previous instructions"`, SQL injection fragments, bash commands) is cataloged as inert text. It is flagged with `is_safe=False` and typed as `GroundedItemType.UNSAFE_CONTENT`.
- **Confidence Penalty**: Hostile content receives a deterministic 50% confidence penalty (`score * 0.5`) to signal degraded trust to downstream consumers while preserving evidentiary traceability.

---

## 5. Tenant Isolation
Tenant isolation is enforced across every layer with fail-closed mechanics:
1. **Server-Side Validation**: `current_user_org_id` must match `query.organization_id`, `result_set.organization_id`, `context.organization_id`, and `anchor.organization_id`.
2. **Cross-Tenant Document & Chunk Prevention**: Database queries filter strictly on `Document.org_id` and `DocumentChunk.org_id`.
3. **Contract Invariant Checks**: `RAGEvidenceItem` and `RAGEvidenceBundle` Pydantic validators reject cross-tenant items or citations with `RAGTenantIsolationError`.
4. **Lineage Line-Item Verification**: Provenance metadata must match the item's organization ID.

---

## 6. Complete Provenance Lineage
Step 6 maintains an unbroken 7-hop provenance chain:
$$\text{Document} \longrightarrow \text{Chunk} \longrightarrow \text{Retrieval} \longrightarrow \text{Provenance} \longrightarrow \text{Grounded Context} \longrightarrow \text{Citation} \longrightarrow \text{Evidence Item} \longrightarrow \text{Evidence Bundle}$$

- Every evidence item references its exact `document_id`, `chunk_id`, `citation_id`, and `retrieval_id`.
- Any tampering with document IDs, chunk IDs, or citation excerpts causes immediate integrity validation failure (`RAGProvenanceLineageError` or `RAGCitationIntegrityError`).

---

## 7. Deterministic Behavior & Fingerprinting
All identifiers and metadata are computed deterministically:
- **Evidence Item ID**: Derived via UUIDv5 from `(org_id, doc_id, chunk_id, retrieval_id, context_id)`.
- **Evidence Bundle ID**: Derived via UUIDv5 from `(org_id, retrieval_id, context_id, sorted_evidence_ids)`.
- **Bundle Fingerprint**: SHA-256 hash computed over `bundle_id`, `organization_id`, `retrieval_id`, `context_id`, `grounding_status`, sorted evidence IDs, and sorted citation keys.
- **Ordering**: Evidence items follow deterministic retrieval rank ordering.

---

## 8. Security & Secret Protection
- **Query & Anchor Sanitization**: Queries and anchor metadata are scanned using `SENSITIVE_STRING_REGEX` and `PROHIBITED_METADATA_KEYS`. Detection of API keys, bearer tokens, passwords, or credentials triggers `RAGSecurityPolicyViolationError`.
- **Zero-Secret Audit Logging**: Audit payloads are passed through `validate_no_secrets_in_metadata()` before insertion into the `audit_logs` table.

---

## 9. Error Handling
Domain-specific exceptions inheriting from `RAGError` (HTTP 400–422) provide fail-closed behavior:
- `RAGTenantIsolationError`: Cross-tenant boundary violations.
- `RAGSecurityPolicyViolationError`: Secret leakage or security policy breaches.
- `RAGProvenanceLineageError`: Lineage breaks, tampered chunk IDs, or orphaned citations.
- `RAGCitationIntegrityError`: Excerpt mismatch or unresolvable citations.
- `RAGEvidencePipelineError`: Pipeline orchestration failures or 1:1 correspondence violations.

---

## 10. Test Suite Validation
A comprehensive test suite in `api/tests/test_phase8_rag_evidence_pipeline.py` covers 66 test cases across 9 functional categories:

| Test Group | Test Focus | Tests | Status |
|---|---|---|---|
| Group A | Evidence Contracts & Deterministic Generation | 10 | PASSED |
| Group B | Pipeline End-to-End Execution & Audit Trail | 10 | PASSED |
| Group C | Strict Tenant Isolation & Cross-Tenant Boundary Tests | 8 | PASSED |
| Group D | Provenance Chain & Lineage Preservation | 8 | PASSED |
| Group E | Security, Trust Boundary & Prompt Injection Quarantine | 8 | PASSED |
| Group F | Determinism, Fingerprinting & Repeatability | 6 | PASSED |
| Group G | Integrity Verification & Fail-Closed Behavior | 6 | PASSED |
| Group H | Domain Anchors & Token Budgeting | 6 | PASSED |
| Group I | Architectural Invariants & Database Schema Safety | 4 | PASSED |
| **Total** | **Phase 8 Step 6 Dedicated Suite** | **66** | **PASSED** |

### Full Test Regressions:
- **Phase 8 (Steps 1–6)**: **221 passed** in 11.61s (100% pass rate).
- **Phase 7 (Risk Engine)**: **541 passed** in 10.91s (100% pass rate).
- **Phase 6 (Normalization)**: **152 passed** in 0.82s (100% pass rate).
- **Phase 5 (Ingestion)**: **138 passed** in 5.38s (100% pass rate).
- **Full Backend Suite**: **1,674 passed**, 1 skipped, 0 failures in 53.47s.

---

## 11. Database Impact
- **Table Count**: Exactly **34 tables** in `Base.metadata.tables`.
- **Schema Drift**: **0**.
- **Migrations**: **0** unauthorized migrations created.
- Existing tables (`documents`, `document_chunks`, `audit_logs`) were leveraged without altering columns or enums.

---

## 12. API Impact
- **OpenAPI Surface**: Preserved exactly at **60 paths**, **96 operations**, and **104 schemas**.
- No unauthorized public endpoints added; `RAGEvidencePipelineService` operates as an internal domain orchestrator.

---

## 13. Explicit Non-Goals
The following were explicitly excluded from Phase 8 Step 6:
- No LLM answer generation.
- No Claude or Bedrock generative models.
- No LangGraph agent graphs or state machines.
- No autonomous tool calling or actions.
- No modifications to the deterministic Phase 7 Risk Engine.
- No frontend / UI changes.

---

## 14. Confirmation: Phase 9 is NOT Implemented
Phase 9 (LangGraph Multi-Agent Orchestration) has **NOT** been started or implemented. The codebase contains zero imports from `langgraph` or `app.agents.graph`. Phase 8 Step 6 concludes Phase 8 RAG development by establishing the hardened evidence boundary required before agentic reasoning begins.
