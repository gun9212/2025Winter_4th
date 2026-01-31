"""Document model for storing ingested documents."""

from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.embedding import DocumentChunk
    from app.models.event import Event


class DocumentType(str, Enum):
    """Document file type enumeration."""

    GOOGLE_DOC = "google_doc"
    GOOGLE_SHEET = "google_sheet"
    GOOGLE_FORM = "google_form"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    HWP = "hwp"
    OTHER = "other"


class DocumentCategory(str, Enum):
    """Document category based on Step 2 classification."""

    MEETING_DOCUMENT = "meeting_document"  # 회의 서류 (안건지, 속기록, 결과지)
    WORK_DOCUMENT = "work_document"  # 실제 업무 서류 (Sheet, PPT 등)
    OTHER_DOCUMENT = "other_document"  # 기타 파일


class MeetingSubtype(str, Enum):
    """Meeting document subtypes for reliability weighting."""

    AGENDA = "agenda"  # 안건지 - lowest reliability
    MINUTES = "minutes"  # 속기록 - medium reliability
    RESULT = "result"  # 결과지 - highest reliability (Ground Truth)
    OTHER = "other"


class DocumentStatus(str, Enum):
    """Document processing status."""

    PENDING = "pending"
    CLASSIFYING = "classifying"
    PARSING = "parsing"
    PREPROCESSING = "preprocessing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base, TimestampMixin):
    """
    Document model for storing ingested documents metadata.
    
    Authority Level (access_level) determines who can access the document:
        1: 회장단만 접근 가능 (President/VP only)
        2: 국장단까지 접근 가능 (Department heads)
        3: 모든 국원 접근 가능 (All council members)
        4: 일반 대중 접근 가능 (Public)
    
    Reliability is determined by meeting_subtype:
        result > minutes > agenda
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Event association - NULLABLE: Event is determined at Chunk level, not Document level
    # Per domain requirement: "1 file ≠ 1 event" 
    # Document may contain multiple agenda items for different events
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"),
        index=True,
        nullable=True,  # Explicitly nullable - event mapping happens at chunk level
    )

    # Google Drive metadata
    drive_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    drive_name: Mapped[str] = mapped_column(String(500))
    drive_path: Mapped[str | None] = mapped_column(String(1000))  # Full folder path for classification
    mime_type: Mapped[str | None] = mapped_column(String(255))
    gcs_url: Mapped[str | None] = mapped_column(Text)  # GCS backup location

    # Document classification (Step 2)
    doc_type: Mapped[DocumentType] = mapped_column(
        SQLEnum(DocumentType, name="document_type"),
        default=DocumentType.OTHER,
    )
    doc_category: Mapped[DocumentCategory] = mapped_column(
        SQLEnum(DocumentCategory, name="document_category"),
        default=DocumentCategory.OTHER_DOCUMENT,
        index=True,
    )
    meeting_subtype: Mapped[MeetingSubtype | None] = mapped_column(
        SQLEnum(MeetingSubtype, name="meeting_subtype"),
    )

    # Step 6: Metadata injection
    # Access level (NOT reliability - reliability is based on meeting_subtype)
    # 1: 회장단만, 2: 국장단까지, 3: 모든 국원, 4: 일반 대중
    access_level: Mapped[int] = mapped_column(Integer, default=3, index=True)
    
    # LLM-standardized filename (Step 2)
    standardized_name: Mapped[str | None] = mapped_column(String(500))
    
    # Time decay date for search weighting (Step 6)
    time_decay_date: Mapped[date | None] = mapped_column(Date, index=True)
    
    # Department/organization info
    department: Mapped[str | None] = mapped_column(String(100))  # 담당 국서
    year: Mapped[int | None] = mapped_column(Integer, index=True)  # Document year

    # Processing status
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus, name="document_status"),
        default=DocumentStatus.PENDING,
        index=True,
    )

    # Parsed content (Step 3)
    raw_content: Mapped[str | None] = mapped_column(Text)
    parsed_content: Mapped[str | None] = mapped_column(Text)  # HTML from Upstage
    preprocessed_content: Mapped[str | None] = mapped_column(Text)  # Step 4: LLM-processed

    # Metadata (JSON for flexibility)
    doc_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Processing info
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column()
    
    # Step tracking
    current_step: Mapped[int | None] = mapped_column(Integer, default=1)  # 1-7

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="documents")
    
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    @property
    def reliability_score(self) -> int:
        """
        Get reliability score based on meeting_subtype.
        
        Returns:
            3 for result (highest), 2 for minutes, 1 for agenda (lowest), 0 for non-meeting
        """
        if self.meeting_subtype == MeetingSubtype.RESULT:
            return 3
        elif self.meeting_subtype == MeetingSubtype.MINUTES:
            return 2
        elif self.meeting_subtype == MeetingSubtype.AGENDA:
            return 1
        return 0

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, name='{self.drive_name}', status={self.status})>"
