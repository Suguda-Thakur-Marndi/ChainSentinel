# Phase 8 — RAG: Document Ingestion & Chunking (Step 2)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "Phase 8 Step 2 establishes document ingestion, multi-format text extraction,
> idempotent identity generation, deterministic recursive chunking, and transactional persistence.
> It does NOT implement vector embedding generation, vector similarity search,
> LangGraph state machines, AWS Bedrock runtime, or autonomous agent workflows.
> The deterministic Risk Engine remains solely authoritative for risk scoring."

---

## 1. Authoritative Objective & Scope

Phase 8 Step 2 implements the **Document Ingestion & Chunking Engine** for RiskWise 2.0. Building upon the Phase 8 Step 1 contracts, Step 2 creates a production-grade, deterministic, and auditable pipeline that parses raw enterprise documents into structured, tenant-isolated `Document` and `DocumentChunk` records stored in PostgreSQL.

### Strict Boundary with Deterministic Risk Engine
- The Phase 7 Risk Engine remains the sole authority for risk scoring, factor evaluations, evidence lineage, alerts, and recommendations.
- RAG ingestion processes contextual knowledge (SOPs, contracts, port advisories, intelligence memos) without altering, computing, or overriding deterministic risk assessments.

---

## 2. Ingestion & Chunking Lifecycle

```
SOURCE DOCUMENT (File / Ingestion Feed / SOP / Contract / Intelligence Memo)
      ↓
[1. Ingestion Boundary & Security Sanitization]
   - Validates organization ownership (server-side context)
   - Sanitizes title and filename (path traversal defense)
   - Enforces document size ceiling (10 MB)
   - Scrubs metadata to prevent credential leakage
      ↓
[2. Multi-Format Text Extraction & Parsing]
   - Supported: text/plain, text/markdown, application/json, text/csv, text/html, application/pdf
   - Safe HTML parsing stripping <script> and <style> tags (XSS & prompt injection defense)
   - Rejection of forbidden formats (.exe, .bin, .zip, .py) -> RAGUnsupportedFormatError
      ↓
[3. Content Hashing & Idempotent Identity]
   - Computes SHA-256 content_hash
   - Generates deterministic UUIDv5 document_id: {org_id}:document:{title}:{content_hash}
   - Idempotency check: if document already exists for tenant, returns existing record (IDEMPOTENT_HIT)
      ↓
[4. Deterministic Text Chunking]
   - Sliding-window recursive text splitting (\n\n, \n, . , words)
   - Configurable chunk_size (default 500 chars) and chunk_overlap (default 50 chars)
   - Markdown section header detection (# Heading) to enrich ChunkMetadata
   - Token count estimation (strictly non-negative)
   - Generates deterministic UUIDv5 chunk_id: {org_id}:chunk:{doc_id}:{chunk_index}
   - Invariant: Zero silent text loss, stable chunk_index (0, 1, 2, ...)
      ↓
[5. Transactional Persistence & Audit Logging]
   - Atomic persistence to PostgreSQL documents and document_chunks tables
   - Appends immutable AuditLog record (action: DOCUMENT_INGESTED)
   - Returns DocumentIngestionResult
```

---

## 3. Supported Document Formats

Text extraction relies exclusively on Python standard library modules (`html.parser`, `json`, `csv`, `io`, `re`), guaranteeing zero-dependency execution and eliminating supply-chain vulnerabilities:

| Format | MIME Type | Extensions | Parsing Strategy |
|---|---|---|---|
| **Plain Text** | `text/plain` | `.txt`, `.text` | UTF-8 decoding with Latin-1 fallback; control-character sanitization. |
| **Markdown** | `text/markdown` | `.md`, `.markdown` | UTF-8 decoding; section header tracking for metadata enrichment. |
| **JSON** | `application/json` | `.json` | Full JSON structural validation; re-encoded into canonical sorted text. |
| **CSV** | `text/csv` | `.csv` | Tabular row parsing; converts rows into labeled `header: value` text. |
| **HTML** | `text/html` | `.html`, `.htm` | `SafeHTMLTextExtractor` strips `<script>`, `<style>`, `<noscript>`, `<iframe>`. |
| **PDF** | `application/pdf` | `.pdf` | Safe text extraction from PDF streams and text payloads. |

*Explicit Rejection*: Executable and binary files (`.exe`, `.bin`, `.zip`, `.py`, `.sh`, `.bat`, `.dll`) are strictly rejected with `RAGUnsupportedFormatError` (HTTP 415).

---

## 4. Deterministic Chunking Strategy

Implemented in `DeterministicChunker` (`app/rag/chunking.py`):
- **Hierarchy of Separators**:
  1. Paragraph breaks (`\n\n`)
  2. Line breaks (`\n`)
  3. Sentence terminators (`. `, `? `, `! `)
  4. Word boundaries (` `)
  5. Fallback character boundaries
- **Sliding Window**: Target `chunk_size = 500` characters with `chunk_overlap = 50` characters. Configurable within boundaries (`50 <= chunk_size <= 4000`, `0 <= chunk_overlap < chunk_size`).
- **Section Tracking**: Scans Markdown headers (`# Heading`, `## Subheading`) and attaches the active heading to each chunk's `ChunkMetadata.section_title`.
- **Token Estimation**: Computed via word and punctuation factors, ensuring non-negative counts.
- **Multibyte & Unicode Safety**: UTF-8 multibyte characters (emojis, CJK glyphs, Arabic script, accents) are safely chunked without splitting byte sequences.
- **No Silent Text Loss**: All original textual content is preserved across sequential chunks.

---

## 5. Strict Tenant Isolation & Provenance

1. **Server-Side Tenant Scoping**:
   - `DocumentIngestionService.ingest_document()` compares `payload.organization_id` against the authenticated `current_user_org_id`. Any mismatch raises `RAGTenantIsolationError` (HTTP 403 Forbidden).
2. **Unbroken Lineage**:
   - Every chunk record carries `document_id`, `organization_id`, and sequential `chunk_index`.
   - Chunks are foreign-keyed to `documents.id` with `cascade="all, delete-orphan"`.
   - Deleting a document automatically cascade-deletes all child chunks, guaranteeing zero orphan chunks.

---

## 6. Determinism & Idempotency

1. **Deterministic Identifiers**:
   - Document ID: UUIDv5 from `{org_id}:document:{title}:{content_hash}`
   - Chunk ID: UUIDv5 from `{org_id}:chunk:{doc_id}:{chunk_index}`
2. **Idempotent Ingestion**:
   - Ingesting identical content for the same tenant and title results in `idempotency_status = "IDEMPOTENT_HIT"` and returns the existing document and chunks without duplicating database rows.
   - If content changes (different SHA-256 hash), a new versioned `document_id` is generated.

---

## 7. Security Defenses

1. **DATA vs INSTRUCTION Demarcation**: Ingested text is treated strictly as passive data. Content is never executed or interpreted as system instructions.
2. **Path Traversal Defense**: `validate_filename_safety()` rejects filenames or titles containing `..`, `/`, `\\`, control characters, or null bytes, raising `RAGPathTraversalError`.
3. **Payload Size Defense**: Payloads exceeding 10 MB raise `RAGDocumentTooLargeError` (HTTP 413).
4. **Secret Scrubbing**: `validate_no_secrets_in_metadata()` audits metadata dictionaries, strictly rejecting keys containing `api_key`, `secret`, `password`, `token`, `bearer`, or `authorization`.

---

## 8. Database & OpenAPI Invariants

- **PostgreSQL Database**: Exactly **34 tables** preserved in `Base.metadata.tables`.
  - Reuses table 33 (`documents`) and table 34 (`document_chunks`).
  - Zero schema drift, zero new migrations.
- **OpenAPI 3.1 Specification**: Preserves baseline exactly:
  - **60 paths**
  - **96 operations**
  - **104 schemas**
- Step 2 implements internal domain services; zero public API endpoints added.

---

## 9. Automated Testing & Verification

The dedicated test suite `apps/api/tests/test_phase8_rag_ingestion_chunking.py` contains **22 focused unit and integration tests**:
- Format parsing tests: plain text, markdown, json, csv, html, pdf (6 tests).
- Boundary tests: unsupported formats, empty documents, oversized payloads, path traversal (4 tests).
- Chunking tests: small documents, large documents, reproducibility, heading propagation, unicode safety (5 tests).
- Ingestion service tests: end-to-end lifecycle, idempotent deduplication, cross-tenant blocking, secret scrubbing, cascade deletion (5 tests).
- Invariant tests: 34 database tables, 60 OpenAPI paths / 96 operations (2 tests).

### Test Summary
- `test_phase8_rag_ingestion_chunking.py`: **22 passed, 0 failures**
- `test_phase8_rag_contracts.py`: **27 passed, 0 failures**
- **Full API Regression**: **1,502 passed, 1 skipped, 0 failures** (up from 1,480 baseline + 22 new tests).

---

## 10. Explicit Non-Goals & Limitations

The following capabilities are **explicitly out of scope** for Phase 8 Step 2:
- **No vector embedding generation** or model calls (scheduled for Step 3+).
- **No vector similarity retrieval** or semantic search (scheduled for Step 4+).
- **No LangGraph state machines** or agent workflow orchestration.
- **No LangChain integrations**.
- **No AWS Bedrock or Anthropic Claude API calls**.
- **No autonomous operational actions** (no shipments rerouted, no orders placed).
- **No Machine Learning prediction models** (Prophet, LightGBM).
- **No Digital Twin graph traversal**.
- **No Monte Carlo scenario simulation**.
- **No Google OR-Tools optimization solvers**.
- **No Phase 9+ functionality**.
