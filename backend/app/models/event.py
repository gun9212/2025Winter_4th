"""Event model for organizing documents by event/activity."""

from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.reference import Reference


class EventStatus(str, Enum):
    """Event status enumeration."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Event(Base, TimestampMixin):
    """
    Event model for organizing documents by academic/student council activities.
    
    Events serve as the top-level logical unit for knowledge organization,
    grouping related documents, chunks, and references together.
    
    Examples:
        - "2025 새내기 배움터"
        - "제38대 축제"
        - "2024학년도 2학기 간식행사"
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Event identification
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    # Event dates
    event_date: Mapped[date | None] = mapped_column(Date)  # Main event date
    start_date: Mapped[date | None] = mapped_column(Date)  # For multi-day events
    end_date: Mapped[date | None] = mapped_column(Date)
    
    # Organization
    category: Mapped[str | None] = mapped_column(String(100), index=True)  # 문화국, 복지국, 기획국
    department: Mapped[str | None] = mapped_column(String(100))  # Specific department
    
    # Status tracking
    status: Mapped[EventStatus] = mapped_column(
        default=EventStatus.PLANNED,
        index=True
    )
    
    # Description and notes
    description: Mapped[str | None] = mapped_column(Text)
    
    # Chunk relationship tracking for event timeline organization
    # Stores parent chunk IDs organized by meeting/agenda for easy retrieval
    # Format: {"meeting_name": [parent_chunk_id1, parent_chunk_id2, ...], ...}
    # Example: {
    #   "2차 국장단 회의": [101, 102],  # 사업 장소 확정, 후원 기업 컨택 리스트
    #   "3차 회의": [103, 104, 105],     # 후원 기업 컨택 상황, 예산안, 타임라인
    #   "4차 회의": [106]                # 담당 국서 전달 결정
    # }
    chunk_timeline: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    
    # Summary of key decisions per meeting
    # Format: {"meeting_name": ["결정사항1", "결정사항2", ...], ...}
    decisions_summary: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    
    # Task/action item tracking
    # Format: [{"task": "...", "assignee": "...", "deadline": "...", "status": "..."}, ...]
    action_items: Mapped[list | None] = mapped_column(JSONB, default=list)
    
    # Related chunk IDs for quick access (all parent chunks for this event)
    parent_chunk_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), default=list)
    child_chunk_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), default=list)
    
    # Additional metadata
    meta_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    
    references: Mapped[list["Reference"]] = relationship(
        "Reference", 
        back_populates="event",
        cascade="all, delete-orphan",
    )

    def add_chunk_to_timeline(
        self,
        meeting_name: str,
        chunk_id: int,
        decision_summary: str | None = None,
    ) -> None:
        """
        Add a chunk to the event timeline for a specific meeting.
        
        Args:
            meeting_name: Name of the meeting (e.g., "2차 국장단 회의")
            chunk_id: Parent chunk ID to add
            decision_summary: Optional summary of the decision made
        """
        if self.chunk_timeline is None:
            self.chunk_timeline = {}
        
        if meeting_name not in self.chunk_timeline:
            self.chunk_timeline[meeting_name] = []
        
        if chunk_id not in self.chunk_timeline[meeting_name]:
            self.chunk_timeline[meeting_name].append(chunk_id)
        
        if decision_summary:
            if self.decisions_summary is None:
                self.decisions_summary = {}
            if meeting_name not in self.decisions_summary:
                self.decisions_summary[meeting_name] = []
            self.decisions_summary[meeting_name].append(decision_summary)

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, title='{self.title}', year={self.year}, status={self.status})>"
