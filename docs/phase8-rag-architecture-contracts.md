# Phase 8 — RAG: Architecture & Contracts (Step 1)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "Phase 8 Step 1 establishes the RAG architecture and strongly typed domain contracts.
> It does NOT implement LLM reasoning, LangGraph state machines, AWS Bedrock runtime,
> vector indexing pipelines, or autonomous agent workflows.
> The deterministic Risk Engine remains the single source of truth for risk scoring."

---

## 1. Objective & Authoritative Scope

In RiskWise 2.0, **Phase 8** establishes the **Retrieval-Augmented Generation (RAG)** foundation. The purpose of this layer is to supply grounded, traceable, organization-isolated contextual knowledge to downstream AI investigation and research agents (such as the Research Agent defined in §8.1 of the Technical Project Specification).

### Strict Boundary with Deterministic Risk Engine
- **Risk Engine Invariant**: The existing deterministic Risk Engine (Phase 7 Steps 1–8) remains solely authoritative for:
  - Numerical risk scoring (0.0 to 100.0)
  - Risk levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
  - Factor evaluation & contribution
  - Evidence lineage and signal correlation
  - Anomaly alerting and escalation
  - Decision recommendations and approval gating
  - Rule-based explainability
- **RAG Role**: RAG provides **retrieved contextual knowledge** (e.g., standard operating procedures, supplier contracts, historical port disruption memos, geopolitical intelligence reports).
- **RAG must NOT replace, compute, or override deterministic risk scoring.**

---

## 2. Architecture & Data Flow

The RAG architecture enforces a clean, unidirectional separation across all data lifecycle boundaries:

```
SOURCE DOCUMENT (File / Feed / PDF / Web)
      ↓
   DOCUMENT (Title, S3 URI, Tenancy, Metadata, Status)
      ↓
DOCUMENT CHUNK (Content, Token Count, Chunk Index)
      ↓
EMBEDDING / VECTOR (1536-dim vector, Model & Provider Metadata)
      ↓
   RETRIEVAL (Tenant-scoped Query, Similarity Threshold, Top-K)
      ↓
  RAG CONTEXT (Encapsulated Data, Citations, Passive Trust Boundary)
      ↓
FUTURE AGENT LAYER (Phase 8+ Downstream AI Investigation)
```

---

## 3. Strongly Typed Domain Contracts

All contracts are defined in `app/rag/contracts.py` using **Pydantic V2** with strict validation (`extra="forbid"`), preventing malformed data, schema creep, or unexpected attributes.

### 3.1 Document Contracts
- **`DocumentStatus`** (`PENDING`, `INDEXING`, `INDEXED`, `FAILED`, `ARCHIVED`): Tracks document ingestion and indexing status.
- **`DocumentMetadata`**: Strongly typed metadata container capturing `source_uri`, `content_hash` (SHA-256), `author_or_source`, `classification` (`INTERNAL`, `CONFIDENTIAL`, `PUBLIC`), `tags`, and validated `extra_attributes`.
- **`DocumentIdentity`**: Immutable identity tracking `document_id` (deterministic UUIDv5), `organization_id` (mandatory, validated non-empty), `title`, `file_type`, `s3_uri`, `source_url`, and `created_at`.
- **`DocumentContract`**: Authoritative domain model providing bidirectional mapping to/from the PostgreSQL `documents` table via `from_orm_model()` and `to_orm_kwargs()`.

### 3.2 Chunk & Embedding Contracts
- **`ChunkMetadata`**: Tracks `section_title`, character byte offsets (`start_char_idx`, `end_char_idx`), `language`, and `content_type`.
- **`ChunkIdentity`**: Immutable coordinate tracking `chunk_id` (deterministic UUIDv5 derived from `org_id:chunk:doc_id:chunk_index`), `document_id`, `organization_id`, `chunk_index` ($\ge 0$), `token_count` ($\ge 0$), and `created_at`.
- **`DocumentChunkContract`**: Authoritative domain model providing bidirectional mapping to/from the PostgreSQL `document_chunks` table via `from_orm_model()` and `to_orm_kwargs()`.
- **`EmbeddingVector`**: Strictly validated vector array with dimension verification (`len(values) == dimension`), normalization flags, and built-in vector operations (`cosine_similarity`, `l2_distance`, `dot_product`). Supports 1536-dimensional embeddings natively aligned with `pgvector` specifications.
- **`EmbeddingMetadata`**: Describes the embedding generator (`model_name`, `provider`, `dimension`, `generated_at`).

### 3.3 Retrieval Contracts
- **`RetrievalFilter`**: Scoped query predicates for `file_types`, `document_ids`, `tags`, `scope_entity_type`, and `scope_entity_id`.
- **`RetrievalQuery`**: Validated search query carrying mandatory `organization_id`, `query_text` (non-empty), `top_k` ($1 \le k \le 100$), `similarity_threshold` ($0.0 \le \theta \le 1.0$), `distance_metric` (`COSINE`, `DOT_PRODUCT`, `EUCLIDEAN`), optional filters, and optional precomputed `EmbeddingVector`.
- **`RetrievalProvenance`**: Complete lineage envelope recording `document_id`, `chunk_id`, `organization_id`, `chunk_index`, `document_title`, `file_type`, `s3_uri`, `source_url`, `retrieval_id`, `similarity_score`, `rank`, and timestamp.
- **`RetrievedChunk`**: Retrieved text passage coupled with its similarity score, rank, token count, provenance, and mandatory `is_untrusted_data=True` marker.
- **`RetrievalResultSet`**: Collection of retrieved chunks sorted deterministically by `(score DESC, chunk_index ASC, chunk_id ASC)` with server-side tenant isolation enforcement.

### 3.4 Context Assembly & Security Contracts
- **`RAGContextCitation`**: Grounded citation linking directly to a retrieved chunk (`citation_key`, `document_id`, `chunk_id`, `document_title`, `chunk_index`, `excerpt`).
- **`DataTrustBoundary`**: Security boundary enforcing `is_untrusted_data=True`, `contains_instructions=False`, injection risk indicators, and `<retrieved_context>` XML demarcation.
- **`RAGContext`**: Assembled contextual bundle ready for downstream agents containing `context_id`, `organization_id`, `query_text`, `assembled_text` (wrapped in trust envelope), `citations`, `source_chunks`, `total_tokens`, and optional grounding IDs (`grounding_signal_id`, `grounding_assessment_id`).

---

## 4. Strict Tenant Isolation

RAG operations are strictly organization-scoped to prevent cross-tenant information leakage:
1. **Server-Side Enforcement**: Every contract (`DocumentIdentity`, `ChunkIdentity`, `RetrievalQuery`, `RetrievalProvenance`, `RetrievedChunk`, `RetrievalResultSet`, `RAGContext`) enforces a non-empty `organization_id`.
2. **Result Set Isolation**: `RetrievalResultSet` validates that every chunk within the set belongs to the query's `organization_id`. Any cross-tenant chunk immediately raises `RAGTenantIsolationError` (HTTP 403 Forbidden).
3. **Context Assembly Isolation**: `RAGContext.assemble()` rejects mismatched organization IDs between query, result set, and target context.
4. **Deterministic Identity Scoping**: UUIDv5 identifiers incorporate `organization_id` into their namespace tokens, ensuring documents and chunks across tenants never share identifiers.

---

## 5. Unbroken Provenance & Zero Hallucinated Sources

1. **Lineage Invariant**: Every retrieved chunk retains complete lineage to its parent chunk, document, organization, and retrieval execution.
2. **Zero Hallucinated Sources Guarantee**:
   - The RAG foundation never invents document IDs, chunk IDs, citations, source URLs, or retrieval scores.
   - Unavailable metadata fields are explicitly represented as `None` or empty collections.
   - `RAGContext` validates that every citation in its `citations` list maps 1:1 to an actual `RetrievedChunk` in its `source_chunks`. Any orphan citation raises `RAGProvenanceLineageError` (HTTP 422).

---

## 6. Security & Data Trust Boundaries (DATA vs INSTRUCTION)

### Core Rule: Retrieved Text is DATA
Retrieved document content is untrusted external data. It must never automatically become an instruction to the system or hijack LLM execution:
1. **Passive Data Demarcation**:
   - `RetrievedChunk.is_untrusted_data` is strictly invariant (`True`). Attempting to set `False` raises `RAGSecurityPolicyViolationError`.
   - `DataTrustBoundary.contains_instructions` is strictly invariant (`False`).
2. **XML Demarcation Envelope**:
   - `format_rag_data_envelope()` encloses retrieved passages in XML CDATA containers:
     ```xml
     <retrieved_context chunk_ref="[CIT-1] Doc:SOP#Chunk0" trust="UNTRUSTED_PASSIVE_DATA">
     <![CDATA[
     ... text content ...
     ]]>
     </retrieved_context>
     ```
   - CDATA closing tags (`]]>`) inside content are safely escaped to `]]&gt;` to prevent prompt boundary escape.
3. **Heuristic Prompt-Injection Detection**:
   - `detect_prompt_injection_indicators()` inspects retrieved text for adversarial patterns (e.g., `ignore previous instructions`, `system prompt:`, `disregard prior rules`, `eval()`, `<script>`).
   - Detected indicators are flagged in `prompt_injection_flags` and `trust_boundary.detected_risk_indicators`.
4. **Secret Scrubbing & Metadata Leakage Prevention**:
   - `validate_no_secrets_in_metadata()` audits all document and chunk metadata dictionaries.
   - Keys matching sensitive tokens (`api_key`, `secret`, `password`, `token`, `authorization`, `bearer`, `private_key`) are rejected, raising `RAGSecurityPolicyViolationError`.

---

## 7. Determinism & Stability

1. **Deterministic Identifiers**:
   - Document ID: UUIDv5 from `{org}:document:{title}:{content_hash}`
   - Chunk ID: UUIDv5 from `{org}:chunk:{doc_id}:{chunk_index}`
   - Retrieval ID: UUIDv5 from `{org}:retrieval:{query_text}:{hour_bucket}`
   - Context ID: UUIDv5 from `{org}:rag_context:{retrieval_id}:{sorted_chunk_ids}`
2. **Deterministic Ordering**:
   - `RetrievalResultSet` enforces stable sorting: `(score DESC, chunk_index ASC, chunk_id ASC)`. Equal scores are stably tie-broken by document chunk index, followed by chunk UUID.
3. **Deterministic Serialization**:
   - `RAGContext` supports round-trip serialization and deserialization via Pydantic V2 JSON models without data drift.

---

## 8. Database Interaction & Invariants

- **PostgreSQL Tables Reused**:
  - `documents` (table 33): mapped via `DocumentContract`
  - `document_chunks` (table 34): mapped via `DocumentChunkContract`
- **Zero Schema Drift**: Exactly 34 tables registered in `Base.metadata.tables`.
- **Zero Migrations**: No DDL alterations, no new tables, no alembic revisions.
- **1536-Dimensional Embeddings**: `document_chunks.embedding_json` stores vector representations compatible with `pgvector` specifications.

---

## 9. API / OpenAPI Impact

- **OpenAPI Invariant Preserved**: Exactly 60 paths, 96 operations, and 104 schemas.
- **Zero Public Endpoints Added**: Step 1 defines internal domain architecture and contracts. No new endpoints were added to `api/app/api/v1/router.py`, preserving the existing baseline.

---

## 10. Automated Testing & Verification

A dedicated test suite was implemented in `api/tests/test_phase8_rag_contracts.py` containing **27 focused unit and contract tests**:
1. `test_document_identity_and_metadata_creation`: Validates document identity and metadata instantiation.
2. `test_chunk_identity_and_contract_creation`: Validates chunk identity and contract instantiation.
3. `test_embedding_vector_mathematical_operations`: Validates cosine similarity, L2 distance, and dot product.
4. `test_1536_dimension_embedding_vector`: Validates 1536-dimensional vector embedding.
5. `test_extra_fields_strictly_forbidden`: Verifies `extra="forbid"` across all contracts.
6. `test_embedding_vector_dimension_mismatch_rejected`: Validates rejection of mismatched vector dimensions.
7. `test_invalid_retrieval_query_boundaries`: Validates query validation boundaries.
8. `test_tenant_isolation_mandatory_org_id`: Validates non-empty `organization_id` enforcement.
9. `test_cross_tenant_chunk_in_result_set_rejected`: Validates cross-tenant rejection in result sets.
10. `test_cross_tenant_rag_context_assembly_rejected`: Validates cross-tenant rejection in context assembly.
11. `test_provenance_consistency_enforced_on_retrieved_chunk`: Validates internal provenance consistency.
12. `test_zero_hallucinated_citations_in_rag_context`: Validates rejection of hallucinated citations.
13. `test_deterministic_identifier_generation`: Validates UUIDv5 reproducibility.
14. `test_deterministic_ordering_in_retrieval_result_set`: Validates deterministic tie-breaking.
15. `test_retrieved_text_strictly_demarcated_as_passive_data`: Validates DATA vs INSTRUCTION demarcation.
16. `test_prompt_injection_detection_and_flagging`: Validates heuristic prompt injection flagging.
17. `test_xml_data_envelope_demarcation`: Validates XML CDATA envelope structure.
18. `test_secret_scrubbing_and_metadata_leakage_protection`: Validates sensitive key detection and scrubbing.
19. `test_database_table_count_invariant_34_tables`: Validates 34 database table count.
20. `test_document_and_chunk_orm_model_bidirectional_mapping`: Validates SQLAlchemy ORM bidirectional conversion.
21. `test_rag_context_accepts_phase6_and_phase7_grounding_anchors`: Validates grounding signal/assessment links.
22. `test_risk_engine_remains_strictly_isolated_from_rag`: Validates zero future-phase symbols in Risk Engine.
23. `test_openapi_schema_strictly_invariant`: Validates 60 paths / 96 operations / 104 schemas baseline.
24. `test_empty_retrieval_result_and_context_assembly`: Validates empty query assembly.
25. `test_exception_hierarchy_and_status_codes`: Validates HTTP status code mapping for all RAG exceptions.
26. `test_xml_envelope_escaping_cdata_closing_tag`: Validates safe CDATA closing tag escaping.
27. `test_rag_context_json_serialization_roundtrip`: Validates JSON round-trip serialization.

### Regression Test Results
- **Phase 8 Step 1 Tests**: 27 passed, 0 failures.
- **Full API Regression**: **1,480 passed, 1 skipped, 0 failures** (up from 1,453 baseline + 27 new tests).

---

## 11. Limitations & Explicit Non-Goals

The following capabilities are **explicitly out of scope** and have **NOT** been implemented in Phase 8 Step 1:
- **No LangGraph state machines** or agent workflow orchestration.
- **No LangChain** integrations.
- **No AWS Bedrock or Anthropic Claude API calls** (no runtime LLM generation).
- **No vector index creation** or background chunking workers (scheduled for Step 2+).
- **No Decision Agent, Action Agent, or Verification Agent**.
- **No autonomous actions or automated approval execution**.
- **No Machine Learning prediction models** (Prophet, LightGBM).
- **No Digital Twin graph traversal**.
- **No Monte Carlo scenario simulation**.
- **No Google OR-Tools optimization solvers**.
- **No Phase 9+ functionality**.
