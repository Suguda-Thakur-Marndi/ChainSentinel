"""Pydantic schemas for knowledge base documents and text chunks for RAG."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginatedResponse


# Enums
class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


# Document
class DocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    file_type: Optional[str] = Field(None, max_length=50)
    s3_uri: Optional[str] = Field(None, max_length=500)
    source_url: Optional[str] = Field(None, max_length=500)
    metadata_json: Optional[dict[str, Any]] = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: Optional[str] = None
    title: str
    file_type: Optional[str] = None
    s3_uri: Optional[str] = None
    source_url: Optional[str] = None
    status: str
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime


class DocumentListResponse(PaginatedResponse[DocumentResponse]):
    pass


# DocumentChunk
class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    chunk_index: int
    content: str
    token_count: int
    created_at: datetime


class DocumentChunkListResponse(PaginatedResponse[DocumentChunkResponse]):
    pass
