"""SQLAlchemy models for knowledge base documents, chunks, and semantic embeddings."""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, generate_uuid


class Document(Base):
    """Ingested knowledge document (compliance, SOP, contract, intelligence feed)."""
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    s3_uri: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="INDEXED")
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    """Text chunk and vector embedding for RAG semantic search."""
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
