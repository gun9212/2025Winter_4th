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
    from app.models.event import Event

# Vertex AI text-embedding-004 dimension
EMBEDDING_DIMENSION = settings.VERTEX_AI_EMBEDDING_DIMENSION  # 768


class DocumentChunk(Base, TimestampMixin):
    """
    Document chunk with vector embedding for RAG.
    
    Implements Parent-Child chunking strategy:
        - Parent chunks: Entire agenda items with full context
        - Child chunks: Smaller segments for precise vector search
    
    Event Mapping (N:M Relationship):
        - Event is determined at CHUNK level, not document level
        - One document may contain multiple agenda items for different events
        - LLM infers event from chunk content during enrichment step
    
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

    # ⭐ NEW: Chunk-level Event mapping (N:M relationship support)
    # Event is determined per agenda item (chunk), not per document
    related_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    
    # LLM-inferred event title (before Event matching)
    # Used when exact Event record doesn't exist yet
    inferred_event_title: Mapped[str | None] = mapped_column(String(500))

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
    chunk_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

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
    
    # ⭐ NEW: Event relationship at chunk level
    related_event: Mapped["Event | None"] = relationship(
        "Event",
        back_populates="related_chunks",
        foreign_keys=[related_event_id],
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
        event_info = f", event={self.related_event_id}" if self.related_event_id else ""
        return f"<DocumentChunk(id={self.id}, doc_id={self.document_id}, type={chunk_type}{event_info})>"

