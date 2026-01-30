"""Document model for storing ingested documents."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.embedding import DocumentChunk


class DocumentType(str, Enum):
    """Document type enumeration."""

    GOOGLE_DOC = "google_doc"
    GOOGLE_SHEET = "google_sheet"
    GOOGLE_FORM = "google_form"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    OTHER = "other"


class DocumentStatus(str, Enum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base, TimestampMixin):
    """Document model for storing ingested documents metadata."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Google Drive metadata
    drive_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    drive_name: Mapped[str] = mapped_column(String(500))
    drive_path: Mapped[str | None] = mapped_column(String(1000))
    mime_type: Mapped[str | None] = mapped_column(String(255))

    # Document classification
    doc_type: Mapped[DocumentType] = mapped_column(
        SQLEnum(DocumentType, name="document_type"),
        default=DocumentType.OTHER,
    )

    # Processing status
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus, name="document_status"),
        default=DocumentStatus.PENDING,
        index=True,
    )

    # Parsed content
    raw_content: Mapped[str | None] = mapped_column(Text)
    parsed_content: Mapped[str | None] = mapped_column(Text)

    # Metadata (JSON for flexibility)
    doc_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Processing info
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column()

    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, name='{self.drive_name}', status={self.status})>"
