"""Vector embedding model for RAG with Parent-Child chunking support."""

from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.core.config import settings

if TYPE_CHECKING:
    from app.models.document import Document

# Vertex AI text-embedding-004 dimension
EMBEDDING_DIMENSION = settings.VERTEX_AI_EMBEDDING_DIMENSION  # 768


class DocumentChunk(Base, TimestampMixin):
    """
    Document chunk with vector embedding for RAG.
    
    Implements Parent-Child chunking strategy:
        - Parent chunks: Entire agenda items with full context
        - Child chunks: Smaller segments for precise vector search
    
    Search Flow:
        1. User query → embed → search child chunks (high precision)
        2. Retrieve matched children's parent_content (full context)
        3. Return parent_content to LLM for answer generation
    """

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Parent document
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )

    # Parent-Child relationship (Step 5)
    parent_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        index=True,
    )
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    
    # Chunk ordering and metadata
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(
        String(50), default="text"
    )  # text, table, image_caption, header

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Parent content for context retrieval (Step 5)
    # Stored on child chunks for efficient retrieval without additional joins
    parent_content: Mapped[str | None] = mapped_column(Text)
    
    # Section header for organization (e.g., "논의안건 1. 축제 가수 섭외")
    section_header: Mapped[str | None] = mapped_column(String(500))

    # Vector embedding (Vertex AI text-embedding-004: 768 dimensions)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION)
    )

    # Access level inherited from document
    # 1: 회장단만, 2: 국장단까지, 3: 모든 국원, 4: 일반 대중
    access_level: Mapped[int | None] = mapped_column(Integer, index=True)

    # Additional metadata
    metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Token count for context management
    token_count: Mapped[int | None] = mapped_column(Integer)
    
    # Original position in document (for ordering and reference)
    start_char: Mapped[int | None] = mapped_column(Integer)
    end_char: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="chunks",
    )
    
    # Self-referential relationship for parent-child
    parent_chunk: Mapped["DocumentChunk | None"] = relationship(
        "DocumentChunk",
        back_populates="child_chunks",
        remote_side="DocumentChunk.id",
    )
    
    child_chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="parent_chunk",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        chunk_type = "Parent" if self.is_parent else "Child"
        return f"<DocumentChunk(id={self.id}, doc_id={self.document_id}, type={chunk_type}, index={self.chunk_index})>"
