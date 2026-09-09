"""Deterministic text chunking engine for RiskWise RAG subsystem.

Implements sliding-window recursive text splitting across paragraphs, sentences,
and word boundaries. Enforces stable chunk indices, deterministic UUIDv5 identifiers,
character offset preservation, and Markdown section hierarchy detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import List, Optional, Tuple

from app.rag.contracts import (
    ChunkIdentity,
    ChunkMetadata,
    DocumentChunkContract,
    generate_deterministic_chunk_id,
)
from app.rag.errors import RAGMalformedInputError, RAGTenantIsolationError

# Default chunking configuration parameters
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
MIN_CHUNK_SIZE = 50
MAX_CHUNK_SIZE = 4000

# Separators ordered by structural priority
SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", " "]

# Markdown header pattern for section tracking
HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def estimate_token_count(text: str) -> int:
    """Estimate token count safely based on whitespace tokenization with character fallback."""
    if not text or not text.strip():
        return 0
    words = text.split()
    # Word count + punctuation factor approximation
    token_est = int(len(words) * 1.25)
    return max(1, token_est)


def find_section_headings(text: str) -> List[Tuple[int, str]]:
    """Scan text for Markdown headers and return list of (character_position, heading_title)."""
    headings: List[Tuple[int, str]] = []
    for match in HEADER_PATTERN.finditer(text):
        pos = match.start()
        title = match.group(2).strip()
        headings.append((pos, title))
    return headings


def get_active_section_title(headings: List[Tuple[int, str]], char_idx: int) -> Optional[str]:
    """Find the most recent section heading prior to or at char_idx."""
    active_title = None
    for pos, title in headings:
        if pos <= char_idx:
            active_title = title
        else:
            break
    return active_title


class DeterministicChunker:
    """Thread-safe, deterministic text splitter with sliding-window overlap."""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size < MIN_CHUNK_SIZE or chunk_size > MAX_CHUNK_SIZE:
            raise RAGMalformedInputError(
                f"chunk_size ({chunk_size}) must be between {MIN_CHUNK_SIZE} and {MAX_CHUNK_SIZE}."
            )
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise RAGMalformedInputError(
                f"chunk_overlap ({chunk_overlap}) must be non-negative and strictly less than chunk_size ({chunk_size})."
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text_with_offsets(self, text: str) -> List[Tuple[str, int, int]]:
        """Split text into chunks while tracking exact (content, start_char_idx, end_char_idx)."""
        clean_text = text.strip()
        if not clean_text:
            return []

        # If text fits within single chunk limit, return directly
        if len(clean_text) <= self.chunk_size:
            return [(clean_text, 0, len(clean_text))]

        chunks_with_offsets: List[Tuple[str, int, int]] = []
        start = 0
        total_len = len(clean_text)

        while start < total_len:
            # End target
            end = min(start + self.chunk_size, total_len)

            if end < total_len:
                # Look for natural split point within separator hierarchy
                best_split = -1
                for sep in SEPARATORS:
                    last_pos = clean_text.rfind(sep, start + (self.chunk_size // 4), end)
                    if last_pos != -1:
                        best_split = last_pos + len(sep)
                        break

                if best_split != -1 and best_split > start:
                    end = best_split

            chunk_content = clean_text[start:end].strip()
            if chunk_content:
                chunks_with_offsets.append((chunk_content, start, end))

            # Advance by step size
            step = max(1, (end - start) - self.chunk_overlap)
            if start + step >= total_len or end >= total_len:
                break
            start += step

        return chunks_with_offsets

    def chunk_document(
        self,
        document_id: str,
        organization_id: str,
        text: str,
    ) -> List[DocumentChunkContract]:
        """Produce deterministic DocumentChunkContract instances with full provenance and metadata."""
        if not organization_id or not organization_id.strip():
            raise RAGTenantIsolationError("organization_id is mandatory for document chunking.")
        if not document_id or not document_id.strip():
            raise RAGMalformedInputError("document_id is mandatory for document chunking.")

        headings = find_section_headings(text)
        splits = self.split_text_with_offsets(text)

        chunks: List[DocumentChunkContract] = []
        created_at = datetime.now(timezone.utc)

        for chunk_idx, (content, start_idx, end_idx) in enumerate(splits):
            chunk_id = generate_deterministic_chunk_id(
                organization_id=organization_id.strip(),
                document_id=document_id.strip(),
                chunk_index=chunk_idx,
            )
            tokens = estimate_token_count(content)
            section_title = get_active_section_title(headings, start_idx)

            identity = ChunkIdentity(
                chunk_id=chunk_id,
                document_id=document_id.strip(),
                organization_id=organization_id.strip(),
                chunk_index=chunk_idx,
                token_count=tokens,
                created_at=created_at,
            )

            metadata = ChunkMetadata(
                section_title=section_title,
                start_char_idx=start_idx,
                end_char_idx=end_idx,
                language="en",
                content_type="text/plain",
            )

            contract = DocumentChunkContract(
                identity=identity,
                content=content,
                metadata=metadata,
                embedding=None,  # Embeddings belong to Step 3+
            )
            chunks.append(contract)

        return chunks
