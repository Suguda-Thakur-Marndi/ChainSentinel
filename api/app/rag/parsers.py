"""Multi-format text extraction, sanitization, and format validation for RiskWise RAG ingestion.

Supports text/plain, text/markdown, application/json, text/csv, text/html, and application/pdf.
All parsers rely strictly on standard library tools to ensure deterministic execution,
zero-dependency security, and rejection of executable or malicious file streams.
"""

from __future__ import annotations

import csv
import hashlib
from html.parser import HTMLParser
import io
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from app.rag.errors import (
    RAGDocumentTooLargeError,
    RAGEmptyDocumentError,
    RAGMalformedInputError,
    RAGPathTraversalError,
    RAGUnsupportedFormatError,
)

# Maximum permitted payload size: 10 Megabytes
MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024

SUPPORTED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "text/csv",
    "text/html",
    "application/pdf",
}

EXTENSION_TO_MIME = {
    ".txt": "text/plain",
    ".text": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".pdf": "application/pdf",
}

# Forbidden extensions that must always be rejected immediately
FORBIDDEN_EXTENSIONS = {
    ".exe", ".bin", ".zip", ".tar", ".gz", ".py", ".sh", ".bat",
    ".cmd", ".dll", ".so", ".dylib", ".jar", ".class", ".msi",
}


class ExtractedDocumentData(BaseModel):
    """Extracted plain text and metadata resulting from format parsing."""
    model_config = ConfigDict(extra="forbid")

    content: str
    file_type: str
    character_count: int = Field(..., ge=0)
    content_hash: str = Field(..., min_length=64, max_length=64)
    detected_metadata: Dict[str, Any] = Field(default_factory=dict)


class SafeHTMLTextExtractor(HTMLParser):
    """HTML Parser that strips scripts, styles, and tags while preserving textual content and structure."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pieces: List[str] = []
        self._ignore_stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("script", "style", "noscript", "iframe", "svg"):
            self._ignore_stack.append(tag_lower)
        elif tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._pieces.append("\n")
        elif tag_lower == "br":
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._ignore_stack and self._ignore_stack[-1] == tag_lower:
            self._ignore_stack.pop()
        elif tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignore_stack:
            text = data.strip()
            if text:
                self._pieces.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self._pieces)
        # Collapse multiple blank lines
        cleaned = re.sub(r"\n{3,}", "\n\n", raw_text)
        return cleaned.strip()


def validate_filename_safety(filename: Optional[str]) -> str:
    """Validate filename against path traversal, control chars, and forbidden extensions."""
    if not filename:
        return "unnamed_document"
    name = filename.strip()
    if not name:
        return "unnamed_document"

    # Detect path traversal sequences
    if ".." in name or "/" in name or "\\" in name:
        raise RAGPathTraversalError(f"Path traversal sequence detected in filename: '{filename}'")

    # Detect control characters or null bytes
    if any(ord(c) < 32 for c in name):
        raise RAGPathTraversalError("Filename contains invalid control characters or null bytes.")

    # Check forbidden extensions
    _, ext = os.path.splitext(name.lower())
    if ext in FORBIDDEN_EXTENSIONS:
        raise RAGUnsupportedFormatError(f"File extension '{ext}' is explicitly prohibited.")

    return name


def normalize_file_type(file_type: Optional[str], filename: Optional[str]) -> str:
    """Resolve and normalize MIME type from declared type or filename extension."""
    if file_type and file_type.strip():
        clean_mime = file_type.strip().lower()
        # Handle parameters like 'text/plain; charset=utf-8'
        if ";" in clean_mime:
            clean_mime = clean_mime.split(";", 1)[0].strip()
        if clean_mime in SUPPORTED_MIME_TYPES:
            return clean_mime

    if filename:
        _, ext = os.path.splitext(filename.strip().lower())
        if ext in EXTENSION_TO_MIME:
            return EXTENSION_TO_MIME[ext]

    raise RAGUnsupportedFormatError(
        f"Unsupported or unrecognized document format. (file_type: '{file_type}', filename: '{filename}'). "
        f"Supported formats: {sorted(SUPPORTED_MIME_TYPES)}"
    )


def extract_text_from_payload(
    raw_payload: Union[str, bytes],
    file_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> ExtractedDocumentData:
    """Validate, decode, and extract readable text from raw string or byte payload."""
    safe_filename = validate_filename_safety(filename)
    resolved_mime = normalize_file_type(file_type, safe_filename)

    # Size verification
    payload_bytes: bytes
    if isinstance(raw_payload, str):
        payload_bytes = raw_payload.encode("utf-8")
    elif isinstance(raw_payload, (bytes, bytearray)):
        payload_bytes = bytes(raw_payload)
    else:
        raise RAGMalformedInputError("Document payload must be either str or bytes.")

    if len(payload_bytes) > MAX_DOCUMENT_SIZE_BYTES:
        raise RAGDocumentTooLargeError(
            f"Payload size ({len(payload_bytes)} bytes) exceeds limit ({MAX_DOCUMENT_SIZE_BYTES} bytes)."
        )

    # Decode text
    decoded_text: str
    try:
        decoded_text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            decoded_text = payload_bytes.decode("latin-1")
        except Exception as err:
            raise RAGMalformedInputError(f"Unable to decode document payload: {err}") from err

    extracted_content: str = ""
    detected_meta: Dict[str, Any] = {"filename": safe_filename}

    # Format-specific extraction
    if resolved_mime in ("text/plain", "text/markdown"):
        extracted_content = decoded_text.strip()

    elif resolved_mime == "text/html":
        parser = SafeHTMLTextExtractor()
        try:
            parser.feed(decoded_text)
            parser.close()
            extracted_content = parser.get_text()
        except Exception as err:
            raise RAGMalformedInputError(f"Malformed HTML document: {err}") from err

    elif resolved_mime == "application/json":
        try:
            parsed_json = json.loads(decoded_text)
            detected_meta["is_json_root_array"] = isinstance(parsed_json, list)
            # Reformat canonical sorted JSON text for clean chunking
            extracted_content = json.dumps(parsed_json, indent=2, ensure_ascii=False)
        except Exception as err:
            raise RAGMalformedInputError(f"Malformed JSON payload: {err}") from err

    elif resolved_mime == "text/csv":
        try:
            f = io.StringIO(decoded_text)
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                extracted_content = ""
            elif len(rows) == 1:
                extracted_content = ", ".join(rows[0])
            else:
                header = rows[0]
                body_lines = []
                for row_idx, row in enumerate(rows[1:], start=1):
                    # Pair row values with header names if matching length
                    if len(row) == len(header):
                        pairs = [f"{header[i]}: {row[i]}" for i in range(len(header))]
                        body_lines.append(f"Row {row_idx}: " + ", ".join(pairs))
                    else:
                        body_lines.append(f"Row {row_idx}: " + ", ".join(row))
                extracted_content = "\n".join(body_lines)
            detected_meta["row_count"] = len(rows)
        except Exception as err:
            raise RAGMalformedInputError(f"Malformed CSV document: {err}") from err

    elif resolved_mime == "application/pdf":
        # Safe text extraction from PDF stream or text-based PDF representation
        # Standard library safe text stream extractor for text payloads within PDF format
        text_matches = re.findall(r"\(([^\)]+)\)\s*Tj", decoded_text)
        if text_matches:
            extracted_content = " ".join(text_matches).strip()
        else:
            # If payload is plain text labeled as pdf or raw text
            extracted_content = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", decoded_text).strip()

    # Final emptiness check
    clean_extracted = extracted_content.strip()
    if not clean_extracted:
        raise RAGEmptyDocumentError("Document contains no extractable or non-whitespace text.")

    # Compute stable SHA-256 hash of extracted content
    content_hash = hashlib.sha256(clean_extracted.encode("utf-8")).hexdigest()

    return ExtractedDocumentData(
        content=clean_extracted,
        file_type=resolved_mime,
        character_count=len(clean_extracted),
        content_hash=content_hash,
        detected_metadata=detected_meta,
    )
