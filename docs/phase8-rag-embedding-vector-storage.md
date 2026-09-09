# Phase 8 — RAG: Embedding Generation & Vector Storage (Step 3)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "Phase 8 Step 3 establishes provider-independent embedding generation, strictly enforced
> 1536-dimensional vector validation, deterministic fingerprinting, batch processing, and transactional
> persistence into PostgreSQL `document_chunks.embedding_json`.
> It does NOT implement vector similarity search, retrieval algorithms (Step 4),
> generative LLM synthesis, LangGraph state machines, or autonomous action agents.
> The deterministic Risk Engine remains solely authoritative for risk scoring."

---

## 1. Authoritative Objective & Scope

Phase 8 Step 3 implements the **Embedding Generation & Vector Storage Subsystem** for RiskWise 2.0. Building directly upon the Step 1 contracts (`EmbeddingVector`, `EmbeddingMetadata`, `DocumentChunkContract`) and the Step 2 ingestion pipeline, Step 3 provides an enterprise-grade, deterministic, and provider-agnostic vector generation engine that maps chunked textual content into 1536-dimensional vector embeddings and persists them transactionally into existing database structures.

### Strict Boundary with Deterministic Risk Engine
- The Phase 7 Risk Engine remains the sole authority for risk scoring, factor evaluations, evidence lineage, alerts, and recommendations.
- Embeddings represent mathematical coordinates of knowledge content, not risk scores or risk predictions.
- No risk scoring logic, threshold matrices, or recommendation evaluators were touched.

---

## 2. Embedding Generation & Vector Storage Architecture

The subsystem enforces clean unidirectional separation:

```
DocumentChunk (From Step 2 Ingestion)
      ↓
[1. Tenant Verification & Lineage Resolution]
   - Validates organization_id against authenticated user context (HTTP 403 on mismatch)
   - Verifies chunk -> document -> organization parentage
      ↓
[2. Idempotency & Re-Embedding Deduplication]
   - Computes deterministic SHA-256 fingerprint: {model}:{dimension}:{text_sha256}
   - Checks if chunk already has matching embedding fingerprint
   - Returns IDEMPOTENT_HIT if all chunks are up to date (zero redundant API calls)
      ↓
[3. Provider-Independent Generation]
   - BaseEmbeddingProvider abstract interface
   - LocalMockEmbeddingProvider: deterministic 1536-dim L2-normalized generator (SHA-256 seeded)
   - OpenAIEmbeddingProvider: text-embedding-3-small (1536 dims)
   - BedrockEmbeddingProvider: amazon.titan-embed-text-v2 (1536 dims)
   - Enforces strict 1536-dimensional vector boundary (RAGEmbeddingDimensionError on mismatch)
      ↓
[4. Deterministic Batch Processing & Partial Failure Guard]
   - Sequential batching (default batch_size = 16)
   - Preserves chunk_index ordering
   - Atomic transaction rollback: provider errors roll back session without partial vector loss
      ↓
[5. Transactional Vector Persistence & Audit Logging]
   - Persists vector values and metadata into document_chunks.embedding_json
   - Appends append-only AuditLog record (action: CHUNKS_EMBEDDED)
   - Returns ChunkEmbeddingResult
```

---

## 3. Provider Abstraction

The `BaseEmbeddingProvider` abstract class decouples the application from any single commercial AI vendor:

| Provider | Model Identifier | Dimensions | Normalization | Description |
| :--- | :--- | :--- | :--- | :--- |
| `LOCAL_MOCK` | `mock-embedding-1536` | 1536 | L2 ($\|v\| = 1.0$) | Deterministic PRNG seeded by text SHA-256 digest. Identical text produces identical vectors (cosine similarity = 1.0). Zero external dependencies, air-gapped capable. |
| `OPENAI` | `text-embedding-3-small` | 1536 | Native L2 | High-performance embedding model with dimension validation and credential redaction. |
| `BEDROCK` | `amazon.titan-embed-text-v2` | 1536 | Native L2 | AWS Bedrock enterprise embedding model. |

---

## 4. Vector Storage Schema & Provenance

### Zero Schema Drift Invariant (34 PostgreSQL Tables Preserved)
No new tables were added. The subsystem leverages PostgreSQL `document_chunks` table:

```sql
-- Existing Column in document_chunks
embedding_json JSON NULL
```

The payload stored in `document_chunks.embedding_json` conforms to:
```json
{
  "values": [0.0124, -0.0452, 0.0891, ...],
  "dimension": 1536,
  "is_normalized": true,
  "model_name": "mock-embedding-1536",
  "provider": "LOCAL_MOCK",
  "fingerprint": "9f83c07e8...",
  "embedded_at": "2026-09-09T18:30:00+00:00"
}
```

### Cascade Deletion & Zero Orphan Vectors
Foreign-key relationship `document_chunks.document_id -> documents.id` with `cascade="all, delete-orphan"` guarantees that deleting a document automatically removes all associated chunks and their vector embeddings. No orphan vectors can exist.

---

## 5. Idempotency & Batching

1. **Deterministic Fingerprint Calculation**:
   - `compute_embedding_fingerprint(text, model, dimension)` hashes the canonical text content, model name, and target dimension.
   - If repeated embedding is requested on the same document without changes, `ChunkEmbeddingService` detects matching fingerprints and returns `is_idempotent_duplicate = True` (`idempotency_status = "IDEMPOTENT_HIT"`).
2. **Forced Re-embedding**:
   - Passing `force_reembed = True` bypasses the fingerprint check and recomputes embeddings when model configurations change.
3. **Sequential Batching**:
   - Batches chunks in chunks of `batch_size` (default: 16).
   - Ordering strictly follows `chunk_index ASC`.

---

## 6. Tenant Isolation & Security

1. **Strict Server-Side Isolation**:
   - Tenant boundaries are verified against authenticated context (`current_user_org_id`).
   - Organization A cannot embed or access chunks belonging to Organization B (`RAGTenantIsolationError`, HTTP 403).
2. **Credential Protection**:
   - Provider API keys are resolved securely from server configuration or environment variables.
   - API keys and tokens are automatically redacted from error logs (`[REDACTED_API_KEY]`).
   - `validate_no_secrets_in_metadata()` prohibits sensitive keys in database payloads.
3. **Passive Data Treatment**:
   - Ingested document content is strictly passive data. Text containing prompt-injection payloads ("Ignore previous instructions...") is embedded purely as numerical vectors without execution.

---

## 7. Audit Logging & Observability

Every successful embedding generation emits an append-only, immutable `AuditLog` entry:
- `action`: `CHUNKS_EMBEDDED`
- `resource_type`: `Document`
- `resource_id`: `document_id`
- `status`: `SUCCESS`
- `after_json`:
  ```json
  {
    "document_id": "...",
    "chunks_embedded": 4,
    "total_chunks": 4,
    "dimension": 1536,
    "provider": "LOCAL_MOCK",
    "model_name": "mock-embedding-1536"
  }
  ```

---

## 8. Failure Handling & Atomic Rollback

- **Provider Failure / Timeout**: Raises `RAGEmbeddingError` (HTTP 502 Bad Gateway / 500).
- **Dimension Mismatch**: If a provider returns a vector with dimension $\neq 1536$, raises `RAGEmbeddingDimensionError`.
- **Atomic Rollback**: Any exception during batch generation triggers `session.rollback()`. No chunks remain in a corrupt or partially embedded state.

---

## 9. Explicit Non-Goals & Limitations

- **Vector Retrieval / Similarity Search**: Belongs to Phase 8 Step 4. Vector cosine search, top-k ranking, and retriever interfaces are not implemented here.
- **LLM Synthesis & Reasoning**: Zero LangGraph, LangChain, Claude, or Bedrock prompt execution.
- **Autonomous Actions**: No automated execution of recommended actions.
- **Public Endpoints**: Zero new public API endpoints added in Step 3. All operations occur via internal domain services.
