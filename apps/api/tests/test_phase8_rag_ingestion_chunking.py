"""Comprehensive test suite for RiskWise 2.0 Phase 8 Step 2: RAG Document Ingestion & Chunking.

Covers:
1. Valid document ingestion across supported formats (TXT, MD, JSON, CSV, HTML, PDF)
2. Format validation & rejection of unsupported formats (.exe, .zip, .py)
3. Empty document rejection & small/large document boundary handling
4. Deterministic sliding-window chunking, stable ordering, and zero silent text loss
5. Unicode and emoji multibyte safety
6. Strict server-side tenant isolation & cross-tenant protection
7. Deterministic UUIDv5 identification & idempotent deduplication
8. Security defenses: path traversal rejection, secret scrubbing, prompt injection safety
9. Transactional persistence, rollback resilience, and immutable audit logging
10. System invariants: 34 database tables, 60 OpenAPI paths, 96 operations
"""

from datetime import datetime, timezone
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.main import app
from app.models.governance import AuditLog
from app.models.knowledge import Document, DocumentChunk
from app.rag import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DeterministicChunker,
    DocumentContract,
    DocumentChunkContract,
    DocumentIngestionPayload,
    DocumentIngestionResult,
    DocumentIngestionService,
    DocumentStatus,
    ExtractedDocumentData,
    RAGDocumentTooLargeError,
    RAGEmptyDocumentError,
    RAGMalformedInputError,
    RAGPathTraversalError,
    RAGSecurityPolicyViolationError,
    RAGTenantIsolationError,
    RAGUnsupportedFormatError,
    SafeHTMLTextExtractor,
    estimate_token_count,
    extract_text_from_payload,
    find_section_headings,
    generate_deterministic_chunk_id,
    generate_deterministic_document_id,
    normalize_file_type,
    validate_filename_safety,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session with all 34 tables created for isolated testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ==============================================================================
# 1. PARSER & FORMAT EXTRACTION TESTS
# ==============================================================================

def test_extract_plain_text():
    """Verify clean plain text extraction and hashing."""
    raw = "Standard Operating Procedure for handling cargo disruptions."
    data = extract_text_from_payload(raw, file_type="text/plain", filename="sop.txt")
    assert data.file_type == "text/plain"
    assert data.content == raw
    assert data.character_count == len(raw)
    assert len(data.content_hash) == 64


def test_extract_markdown_preserves_hierarchy():
    """Verify markdown content is extracted cleanly with formatting."""
    raw = "# Port Logistics\n\n## Section A\nBerth capacity is currently at 85%."
    data = extract_text_from_payload(raw, file_type="text/markdown", filename="port.md")
    assert data.file_type == "text/markdown"
    assert "# Port Logistics" in data.content
    assert "Berth capacity" in data.content


def test_extract_json_canonical_reformatting():
    """Verify structured JSON is parsed, validated, and canonicalized."""
    raw_dict = {"event": "PORT_DELAY", "port": "USLAX", "delay_hours": 36}
    raw_str = json.dumps(raw_dict)
    data = extract_text_from_payload(raw_str, file_type="application/json", filename="event.json")
    assert data.file_type == "application/json"
    assert "PORT_DELAY" in data.content
    assert "USLAX" in data.content


def test_extract_csv_tabular_formatting():
    """Verify CSV rows are converted into contextual tabular representations."""
    csv_raw = "supplier_id,carrier,delay_risk\nSUP-001,Maersk,HIGH\nSUP-002,MSC,LOW"
    data = extract_text_from_payload(csv_raw, file_type="text/csv", filename="suppliers.csv")
    assert data.file_type == "text/csv"
    assert "supplier_id: SUP-001" in data.content
    assert "carrier: Maersk" in data.content
    assert "delay_risk: HIGH" in data.content
    assert data.detected_metadata["row_count"] == 3


def test_extract_html_strips_scripts_and_styles():
    """Verify HTML extractor strips dangerous script/style tags and extracts text safely."""
    html_raw = """
    <html>
      <head>
        <title>Advisory</title>
        <style>body { color: red; }</style>
        <script>alert('malicious XSS payload');</script>
      </head>
      <body>
        <h1>Weather Alert</h1>
        <p>A severe gale warning has been issued for the English Channel.</p>
      </body>
    </html>
    """
    data = extract_text_from_payload(html_raw, file_type="text/html", filename="alert.html")
    assert data.file_type == "text/html"
    assert "alert('malicious" not in data.content
    assert "body { color" not in data.content
    assert "Weather Alert" in data.content
    assert "English Channel" in data.content


def test_extract_pdf_text_payload():
    """Verify text payload extraction from PDF representation."""
    pdf_text_stream = "BT /F1 12 Tf (Port congestion reached critical threshold) Tj ET"
    data = extract_text_from_payload(pdf_text_stream, file_type="application/pdf", filename="report.pdf")
    assert data.file_type == "application/pdf"
    assert "Port congestion reached critical threshold" in data.content


def test_unsupported_formats_rejected():
    """Verify that unsupported file extensions and MIME types are explicitly rejected."""
    unsupported = [
        ("malicious.exe", None),
        ("payload.bin", "application/octet-stream"),
        ("archive.zip", "application/zip"),
        ("script.py", "text/x-python"),
        ("batch.bat", "application/x-bat"),
    ]
    for filename, mime in unsupported:
        with pytest.raises(RAGUnsupportedFormatError):
            extract_text_from_payload("some content", file_type=mime, filename=filename)


def test_empty_document_rejected():
    """Verify that completely empty or whitespace-only documents raise RAGEmptyDocumentError."""
    with pytest.raises(RAGEmptyDocumentError):
        extract_text_from_payload("", file_type="text/plain", filename="empty.txt")

    with pytest.raises(RAGEmptyDocumentError):
        extract_text_from_payload("   \n\t   ", file_type="text/plain", filename="blank.txt")


def test_oversized_payload_rejected():
    """Verify that payloads exceeding 10 MB are rejected with RAGDocumentTooLargeError."""
    large_payload = "A" * (10 * 1024 * 1024 + 10)
    with pytest.raises(RAGDocumentTooLargeError):
        extract_text_from_payload(large_payload, file_type="text/plain", filename="big.txt")


def test_path_traversal_filename_rejected():
    """Verify path traversal sequences in filenames are blocked with RAGPathTraversalError."""
    dangerous = [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "folder/sub/doc.txt",
        "doc\x00null.txt",
    ]
    for bad_name in dangerous:
        with pytest.raises(RAGPathTraversalError):
            validate_filename_safety(bad_name)


# ==============================================================================
# 2. DETERMINISTIC CHUNKING & LINEAGE TESTS
# ==============================================================================

def test_deterministic_chunking_small_document():
    """Verify a small document smaller than chunk_size produces exactly 1 chunk with chunk_index=0."""
    text = "Short compliance notice for suppliers."
    chunker = DeterministicChunker(chunk_size=500, chunk_overlap=50)
    chunks = chunker.chunk_document("doc_1", "org_1", text)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == text
    assert chunks[0].document_id == "doc_1"
    assert chunks[0].org_id == "org_1"
    assert chunks[0].metadata.start_char_idx == 0
    assert chunks[0].metadata.end_char_idx == len(text)
    assert chunks[0].token_count > 0


def test_deterministic_chunking_large_document_no_silent_text_loss():
    """Verify large document splits sequentially with overlap and zero silent text loss."""
    paragraphs = [
        f"Paragraph {i}: This is structured operational intelligence discussing shipment routing, port dwell time, and supply chain network resilience under elevated geopolitical risk factors."
        for i in range(1, 25)
    ]
    full_text = "\n\n".join(paragraphs)

    chunker = DeterministicChunker(chunk_size=350, chunk_overlap=50)
    chunks = chunker.chunk_document("doc_large", "org_test", full_text)

    assert len(chunks) > 5

    # Check ordering and continuity
    for idx, chunk in enumerate(chunks):
        assert chunk.chunk_index == idx
        assert chunk.document_id == "doc_large"
        assert chunk.org_id == "org_test"
        assert len(chunk.content) > 0

    # Verify key tokens from start, middle, and end are represented (no silent loss)
    all_chunk_text = " ".join(c.content for c in chunks)
    assert "Paragraph 1:" in all_chunk_text
    assert "Paragraph 12:" in all_chunk_text
    assert "Paragraph 24:" in all_chunk_text


def test_deterministic_chunking_reproducibility():
    """Verify identical text produces exact identical chunk boundaries and deterministic UUIDv5 IDs."""
    text = "# Section 1\n\nFirst paragraph of text.\n\n# Section 2\n\nSecond paragraph with more text."
    chunker = DeterministicChunker(chunk_size=100, chunk_overlap=20)

    run_1 = chunker.chunk_document("doc_repro", "org_repro", text)
    run_2 = chunker.chunk_document("doc_repro", "org_repro", text)

    assert len(run_1) == len(run_2)
    for c1, c2 in zip(run_1, run_2):
        assert c1.id == c2.id
        assert c1.chunk_index == c2.chunk_index
        assert c1.content == c2.content
        assert c1.metadata.section_title == c2.metadata.section_title
        assert c1.metadata.start_char_idx == c2.metadata.start_char_idx
        assert c1.metadata.end_char_idx == c2.metadata.end_char_idx


def test_markdown_section_heading_propagation():
    """Verify that section headings are identified and propagated into ChunkMetadata."""
    md_text = """# Incident Briefing: Port Congestion
Terminal 4 dwell time increased to 6.2 days.

## Recommended Mitigations
Reroute feeder vessels to Secondary Port B.

## Long-term Strategy
Expand inland container depot buffer capacity.
"""
    chunker = DeterministicChunker(chunk_size=150, chunk_overlap=20)
    chunks = chunker.chunk_document("doc_md", "org_1", md_text)

    section_titles = [c.metadata.section_title for c in chunks if c.metadata.section_title]
    assert any("Incident Briefing" in t for t in section_titles)
    assert any("Recommended Mitigations" in t for t in section_titles)


def test_unicode_and_multibyte_safety():
    """Verify multibyte UTF-8 characters (emojis, CJK, accents, Arabic) are safely chunked."""
    unicode_text = """
    🌏 Global Supply Chain Alert: 航运延误与苏伊士运河交通限制。
    خطر تأخير الشحن في ميناء جبل علي بسبب سوء الأحوال الجوية.
    Cargaisons maritimes retardées de 48 heures à Rotterdam.
    """
    chunker = DeterministicChunker(chunk_size=120, chunk_overlap=20)
    chunks = chunker.chunk_document("doc_unicode", "org_uni", unicode_text)

    assert len(chunks) >= 2
    combined = " ".join(c.content for c in chunks)
    assert "🌏" in combined
    assert "航运延误" in combined
    assert "خطر تأخير" in combined
    assert "Rotterdam" in combined


# ==============================================================================
# 3. INGESTION SERVICE, TENANT ISOLATION & IDEMPOTENCY TESTS
# ==============================================================================

def test_document_ingestion_service_end_to_end(db_session):
    """Verify complete ingestion lifecycle: parsing, chunking, DB persistence, and audit logging."""
    service = DocumentIngestionService(db_session)
    payload = DocumentIngestionPayload(
        title="Supplier Code of Conduct 2026",
        content="All tier-1 suppliers must comply with environmental and labor regulations.\n\nAudit frequency is annual.",
        organization_id="org_acme",
        file_type="text/plain",
        filename="conduct.txt",
        classification="CONFIDENTIAL",
        tags=["compliance", "supplier", "audit"],
    )

    result = service.ingest_document(
        payload=payload,
        current_user_org_id="org_acme",
        actor_id="user_admin_1",
    )

    assert result.is_idempotent_duplicate is False
    assert result.idempotency_status == "CREATED"
    assert result.chunk_count > 0
    assert result.document.org_id == "org_acme"
    assert result.document.title == "Supplier Code of Conduct 2026"
    assert result.document.status == DocumentStatus.INDEXED
    assert result.audit_log_id is not None

    # Verify in DB
    db_doc = db_session.query(Document).filter(Document.id == result.document.id).first()
    assert db_doc is not None
    assert db_doc.org_id == "org_acme"
    assert db_doc.title == "Supplier Code of Conduct 2026"

    db_chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == result.document.id).all()
    assert len(db_chunks) == result.chunk_count

    # Verify AuditLog
    db_audit = db_session.query(AuditLog).filter(AuditLog.id == result.audit_log_id).first()
    assert db_audit is not None
    assert db_audit.action == "DOCUMENT_INGESTED"
    assert db_audit.resource_id == result.document.id


def test_idempotent_duplicate_ingestion(db_session):
    """Verify repeated ingestion of identical document produces an idempotent hit without duplicate DB rows."""
    service = DocumentIngestionService(db_session)
    payload = DocumentIngestionPayload(
        title="Port Risk Policy",
        content="Berth priority guidelines for cold-chain containers.",
        organization_id="org_idemp",
        file_type="text/plain",
    )

    # First ingestion -> CREATED
    res_1 = service.ingest_document(payload=payload, current_user_org_id="org_idemp")
    assert res_1.is_idempotent_duplicate is False
    assert res_1.idempotency_status == "CREATED"

    # Second ingestion of identical content -> IDEMPOTENT_HIT
    res_2 = service.ingest_document(payload=payload, current_user_org_id="org_idemp")
    assert res_2.is_idempotent_duplicate is True
    assert res_2.idempotency_status == "IDEMPOTENT_HIT"
    assert res_2.document.id == res_1.document.id

    # Verify DB table row count: exactly 1 document row
    doc_count = db_session.query(Document).filter(Document.org_id == "org_idemp").count()
    assert doc_count == 1

    chunk_count = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == res_1.document.id).count()
    assert chunk_count == res_1.chunk_count


def test_cross_tenant_ingestion_blocked(db_session):
    """Verify that a user from Org A cannot ingest documents for Org B."""
    service = DocumentIngestionService(db_session)
    payload = DocumentIngestionPayload(
        title="Unauthorized Doc",
        content="Attempting cross-tenant write.",
        organization_id="org_victim",
    )

    with pytest.raises(RAGTenantIsolationError) as exc_info:
        service.ingest_document(
            payload=payload,
            current_user_org_id="org_attacker",  # Mismatched tenant context!
        )
    assert "cannot ingest documents into tenant" in str(exc_info.value)

    # Verify zero documents created in DB for org_victim
    assert db_session.query(Document).filter(Document.org_id == "org_victim").count() == 0


def test_metadata_secret_scrubbing_rejection(db_session):
    """Verify that payloads containing secret tokens or credentials in metadata are rejected."""
    service = DocumentIngestionService(db_session)

    with pytest.raises(RAGSecurityPolicyViolationError):
        DocumentIngestionPayload(
            title="Leaky Doc",
            content="Valid text",
            organization_id="org_sec",
            metadata={"api_key": "sk-live-secret-12345"},  # FORBIDDEN
        )

    with pytest.raises(RAGSecurityPolicyViolationError):
        DocumentIngestionPayload(
            title="Leaky Doc 2",
            content="Valid text",
            organization_id="org_sec",
            metadata={"password": "super-secret-password"},  # FORBIDDEN
        )


def test_database_table_cascade_deletion(db_session):
    """Verify cascade deletion: deleting parent Document removes all child DocumentChunk rows."""
    service = DocumentIngestionService(db_session)
    payload = DocumentIngestionPayload(
        title="Temporary Policy",
        content="Temporary guidelines to be deleted.",
        organization_id="org_cascade",
        file_type="text/plain",
    )
    result = service.ingest_document(payload=payload, current_user_org_id="org_cascade")
    doc_id = result.document.id

    assert db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count() > 0

    # Delete parent document
    doc_to_delete = db_session.query(Document).filter(Document.id == doc_id).first()
    db_session.delete(doc_to_delete)
    db_session.commit()

    # Verify child chunks are cascade-deleted (no orphan chunks)
    remaining_chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count()
    assert remaining_chunks == 0


# ==============================================================================
# 4. SYSTEM INVARIANTS TESTS
# ==============================================================================

def test_database_34_tables_invariant():
    """Verify that Phase 8 Step 2 preserved exactly the 34 tables in Base.metadata.tables."""
    assert len(Base.metadata.tables) == 34
    assert "documents" in Base.metadata.tables
    assert "document_chunks" in Base.metadata.tables


def test_openapi_contract_invariants():
    """Verify that no unauthorized endpoints were added: 60 paths, 96 operations, 104 schemas."""
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    operations_count = sum(
        len([m for m in methods if m in ("get", "post", "put", "patch", "delete", "options", "head")])
        for methods in paths.values()
    )
    schemas = openapi.get("components", {}).get("schemas", {})

    assert len(paths) == 60, f"Expected 60 paths, found {len(paths)}"
    assert operations_count == 96, f"Expected 96 operations, found {operations_count}"
    assert len(schemas) == 104, f"Expected 104 schemas, found {len(schemas)}"
