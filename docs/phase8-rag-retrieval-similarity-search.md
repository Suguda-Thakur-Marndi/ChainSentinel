# Phase 8 — RAG: Retrieval & Similarity Search (Step 4)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "Phase 8 Step 4 establishes semantic retrieval, query vector embedding, tenant-isolated candidate search,
> deterministic ranking, threshold filtering, unbroken provenance tracking, untrusted data demarcation,
> and safe RAGContext assembly.
> It does NOT implement LLM generative answer synthesis, LangGraph state machines, or autonomous action agents.
> The deterministic Risk Engine remains solely authoritative for risk scoring."

---

## 1. Authoritative Objective & Scope

Phase 8 Step 4 implements the **Retrieval & Similarity Search Engine** for RiskWise 2.0. Building upon the Phase 8 Step 1 contracts, Step 2 ingestion pipeline, and Step 3 embedding/vector storage foundation, Step 4 creates a production-grade, deterministic, and tenant-isolated retrieval pipeline that converts a user/system `RetrievalQuery` into a 1536-dimensional query embedding, matches it against stored chunk vectors in PostgreSQL, filters candidates by similarity threshold and metadata criteria, ranks results deterministically, flags prompt-injection risks, and optionally assembles safe, cited `RAGContext` objects for downstream agents.

### Strict Boundary with Deterministic Risk Engine
- The Phase 7 Risk Engine remains the sole authority for risk scoring, factor evaluations, evidence lineage, alerts, and recommendations.
- RAG retrieval provides contextual knowledge (SOPs, contracts, port notices, intelligence memos) without altering, computing, or overriding deterministic risk assessments.
- Embeddings and similarity scores represent mathematical semantic relevance, never risk probabilities or scores.

---

## 2. Retrieval Architecture & Data Flow

```
RetrievalQuery (query_text, organization_id, top_k, similarity_threshold, filter, distance_metric)
      ↓
[1. Tenant Verification & Boundary Validation]
   - Validates organization_id against authenticated context (current_user_org_id)
   - Rejects cross-tenant queries with RAGTenantIsolationError (HTTP 403)
   - Validates query bounds (1 <= top_k <= 100, 0.0 <= threshold <= 1.0, non-empty query_text)
      ↓
[2. Query Embedding Generation]
   - Reuses BaseEmbeddingProvider from Step 3 (LocalMock, OpenAI, Bedrock)
   - Generates 1536-dimensional normalized query vector (or validates pre-computed embedding)
   - Rejects dimension mismatches with RAGEmbeddingDimensionError (HTTP 422)
      ↓
[3. Tenant-Scoped Database Candidate Fetch]
   - Queries document_chunks JOIN documents WHERE documents.org_id == organization_id
   - Applies optional filters: file_types, document_ids, tags, scope_entity_type/id
   - Filters out un-embedded chunks (embedding_json IS NOT NULL)
      ↓
[4. Mathematical Similarity Computation]
   - Computes metric distance/similarity for each chunk:
     * COSINE: cosine similarity clamped in [0.0, 1.0]
     * DOT_PRODUCT: dot product clamped in [0.0, 1.0]
     * EUCLIDEAN: similarity = 1.0 / (1.0 + l2_distance) in (0.0, 1.0]
   - Applies similarity_threshold: drops chunks below threshold
      ↓
[5. Deterministic Ranking & Tie-Breaking]
   - Deterministic sort key: (-similarity_score, chunk_index ASC, chunk_id ASC)
   - Slices top_k items
   - Re-assigns ranks 1..K
      ↓
[6. Provenance Packaging & Untrusted Data Demarcation]
   - Populates RetrievalProvenance (document_id, chunk_id, org_id, chunk_index, doc_title, score, rank)
   - Inspects chunk.content with detect_prompt_injection_indicators()
   - Strictly enforces is_untrusted_data=True on every RetrievedChunk
      ↓
[7. RetrievalResultSet & RAGContext Assembly]
   - Returns strongly typed RetrievalResultSet
   - Optional RAGContext.assemble() generates XML-enclosed, cited context with zero hallucinated sources
   - Appends append-only AuditLog entry (action: RAG_RETRIEVAL)
```

---

## 3. Query Contract & Parameters

Retrieval is governed by the strongly typed Pydantic V2 `RetrievalQuery` contract (`app/rag/contracts.py`):

| Parameter | Type | Validation / Constraints | Description |
| :--- | :--- | :--- | :--- |
| `query_id` | `str` | $1 \dots 64$ chars | Unique tracking identifier for this retrieval operation. |
| `organization_id` | `str` | Mandatory, non-empty | Tenant ownership coordinate. Server-side isolation enforced. |
| `query_text` | `str` | Mandatory, non-whitespace | Search query string. |
| `top_k` | `int` | $1 \le k \le 100$ (default: 10) | Maximum number of chunks to return. |
| `similarity_threshold` | `float` | $0.0 \le \theta \le 1.0$ (default: 0.0) | Minimum similarity score required for inclusion. |
| `distance_metric` | `DistanceMetric` | `COSINE`, `DOT_PRODUCT`, `EUCLIDEAN` | Metric used for vector comparison. |
| `filter` | `Optional[RetrievalFilter]` | Optional criteria | Scope filters: `file_types`, `document_ids`, `tags`, `scope_entity`. |
| `query_embedding` | `Optional[EmbeddingVector]` | Dimension strictly 1536 | Optional precomputed embedding vector. |

---

## 4. Query Embedding & Dimension Enforcement

- The query string is converted to a normalized 1536-dimensional vector using `self.embedding_provider.embed_text(query.query_text)`.
- Reuses the Step 3 provider abstraction (`BaseEmbeddingProvider`, `LocalMockEmbeddingProvider`, `OpenAIEmbeddingProvider`, `BedrockEmbeddingProvider`).
- If a pre-computed vector is passed via `query.query_embedding`, its dimension is strictly verified against `self.embedding_provider.dimension` (1536). Any mismatch deterministically raises `RAGEmbeddingDimensionError` (HTTP 422).

---

## 5. Similarity Metrics & Normalization

All similarity metrics produce normalized relevance scores in $[0.0, 1.0]$:
1. **`DistanceMetric.COSINE`**:
   $$\text{score} = \max\left(0.0, \min\left(1.0, \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\|_2 \|\mathbf{v}\|_2}\right)\right)$$
2. **`DistanceMetric.DOT_PRODUCT`**:
   $$\text{score} = \max\left(0.0, \min\left(1.0, \mathbf{u} \cdot \mathbf{v}\right)\right)$$
3. **`DistanceMetric.EUCLIDEAN`**:
   $$\text{score} = \frac{1.0}{1.0 + \|\mathbf{u} - \mathbf{v}\|_2} \in (0.0, 1.0]$$

---

## 6. Deterministic Ranking & Tie-Breaking

Retrieval ordering is strictly deterministic across repeated runs on identical corpus states:
- **Primary Sort**: `score DESC` (highest relevance first).
- **Secondary Sort (Tie-breaker 1)**: `chunk_index ASC` (earlier chunk in document takes precedence).
- **Tertiary Sort (Tie-breaker 2)**: `chunk_id ASC` (deterministic UUIDv5 alphabetical tie-breaker).
- Ranks are assigned sequentially ($1, 2, \dots, K$) after sorting.

---

## 7. Strict Server-Side Tenant Isolation

1. **Mandatory Tenant Scoping**:
   - `Document.org_id == query.organization_id` is enforced in SQL queries.
   - Organization A can never see, match, or retrieve chunks belonging to Organization B.
2. **Cross-Tenant Attack Rejection**:
   - If the caller's context `current_user_org_id` does not match `query.organization_id`, `RAGTenantIsolationError` (HTTP 403 Forbidden) is immediately raised before executing search.
3. **Result Set Validation**:
   - `RetrievalResultSet` model validator verifies that every chunk inside the result belongs to the query's `organization_id`.

---

## 8. Unbroken Provenance & Zero Hallucinated Citations

- Every `RetrievedChunk` carries a complete `RetrievalProvenance` envelope linking directly to the underlying `document_chunks` and `documents` database records:
  - `document_id`: Database primary key of parent document.
  - `chunk_id`: Database primary key of chunk.
  - `organization_id`: Tenant owner.
  - `chunk_index`: Zero-based index within document.
  - `document_title`: Title of parent document.
  - `file_type`: MIME type.
  - `similarity_score`: Computed similarity score (4 decimal precision).
  - `rank`: Rank $1 \dots K$.
- **Zero Hallucinated Citations**: In `RAGContext.assemble()`, all generated citations must map 1:1 to an actual `RetrievedChunk` present in `source_chunks`. Orphan citations raise `RAGProvenanceLineageError` (HTTP 422).

---

## 9. Untrusted Data Boundary & Prompt Injection Detection

- **Data vs Instruction**: Retrieved document content is external data, never executable instructions. Every `RetrievedChunk` strictly enforces `is_untrusted_data = True`.
- **Heuristic Detection**: `detect_prompt_injection_indicators(chunk.content)` scans for adversarial patterns (`ignore previous instructions`, `system prompt:`, `eval()`, `<script>`).
- Detected patterns are surfaced in `RetrievedChunk.prompt_injection_flags` and `trust_boundary.detected_risk_indicators`.
- Content is packaged inside XML CDATA envelopes:
  ```xml
  <retrieved_context chunk_ref="[CIT-1] Doc:Protocols#Chunk0" trust="UNTRUSTED_PASSIVE_DATA">
  <![CDATA[
  ... text content ...
  ]]>
  </retrieved_context>
  ```

---

## 10. Audit Logging & Observability

Every retrieval execution emits an append-only, immutable `AuditLog` record:
- `action`: `RAG_RETRIEVAL`
- `resource_type`: `RetrievalQuery`
- `resource_id`: `query_id`
- `status`: `SUCCESS`
- `after_json`:
  ```json
  {
    "query_id": "qry_001",
    "top_k": 5,
    "similarity_threshold": 0.5,
    "distance_metric": "COSINE",
    "total_retrieved": 3,
    "latency_ms": 14.2,
    "provider": "LOCAL_MOCK",
    "model_name": "mock-embedding-1536"
  }
  ```
- Sensitive query text and full document contents are never logged into the audit ledger.

---

## 11. Database & API Invariants

- **PostgreSQL Database Tables**: **Strictly 34 tables** preserved (`Base.metadata.tables`). Zero schema drift, zero migrations.
- **OpenAPI Schema**: **Strictly 60 paths, 96 operations, 104 schemas** preserved. Internal domain services used; zero public endpoints added in Step 4.

---

## 12. Automated Testing & Verification

A dedicated test suite was implemented in `apps/api/tests/test_phase8_rag_retrieval_similarity_search.py` containing **25 focused tests**:
1. `test_valid_retrieval_query_happy_path`: Valid semantic retrieval query happy path with relevance scoring.
2. `test_empty_query_rejected`: Empty or whitespace-only query rejection (`RAGInvalidQueryError`).
3. `test_top_k_boundaries_and_rejection`: Top-k boundary enforcement ($1 \le k \le 100$).
4. `test_similarity_threshold_filtering`: Chunks below threshold excluded.
5. `test_empty_corpus_returns_empty_result_set`: Querying empty tenant returns clean empty set.
6. `test_fewer_results_than_k`: Corpus with fewer chunks than $k$ returns all available matches.
7. `test_deterministic_ranking_and_tie_breaking`: Identical queries yield identical ranking and tie-breaking.
8. `test_similarity_calculation_identical_text_max_score`: Identical text achieves max score ($\approx 1.0$).
9. `test_distance_metrics_support`: Verifies `COSINE`, `DOT_PRODUCT`, `EUCLIDEAN` in $[0.0, 1.0]$.
10. `test_precomputed_query_embedding_dimension_mismatch_rejected`: Mismatched dimension fails.
11. `test_precomputed_query_embedding_used_directly`: Valid precomputed vector used directly.
12. `test_document_filtering_file_types`: Filters by MIME type.
13. `test_document_filtering_document_ids`: Filters by document ID.
14. `test_document_filtering_tags`: Filters by document tags.
15. `test_document_filtering_scope_entity`: Filters by entity scope.
16. `test_tenant_isolation_org_a_cannot_see_org_b`: Organization A never retrieves Organization B chunks.
17. `test_cross_tenant_attack_blocked`: Mismatched user tenant raises `RAGTenantIsolationError`.
18. `test_unbroken_provenance_preservation`: Provenance matches database entities.
19. `test_prompt_injection_flagged_and_passive`: Injection attempts flagged without execution.
20. `test_retrieve_context_assembly`: Context assembly with XML trust envelope and citations.
21. `test_retrieval_emits_audit_log`: Audit log created with safe telemetry.
22. `test_conflicting_sources_preserved_without_synthetic_rewriting`: Opposing sources both preserved.
23. `test_zero_hallucinated_citations_enforced`: All citations map to actual chunks.
24. `test_duplicate_chunks_handled_deterministically`: Verbatim duplicates ranked deterministically.
25. `test_system_invariants_database_and_openapi`: Exactly 34 database tables and 60 OpenAPI paths.

---

## 13. Explicit Non-Goals & Limitations

- **No LLM Generative Answer Synthesis**: Zero prompt execution or LLM reasoning calls.
- **No LangGraph or Autonomous Agents**: Agent workflows belong to future phases.
- **No Autonomous Action Execution**: No automated approval or execution of mitigation actions.
- **Zero Risk Engine Modifications**: Deterministic risk scoring is completely isolated.
