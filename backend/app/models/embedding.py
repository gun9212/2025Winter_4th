"""Vector embedding model for RAG."""

from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document

# Gemini embedding dimension
EMBEDDING_DIMENSION = 768


class DocumentChunk(Base, TimestampMixin):
    """Document chunk with vector embedding for RAG."""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Parent document
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
    )

    # Chunk metadata
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(
        String(50), default="text"
    )  # text, table, image_caption

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Vector embedding (Gemini embedding dimension: 768)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION)
    )

    # Additional metadata
    chunk_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Token count for context management
    token_count: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="chunks",
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk(id={self.id}, doc_id={self.document_id}, index={self.chunk_index})>"
