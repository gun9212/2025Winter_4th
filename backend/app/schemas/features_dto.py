"""Schemas for Council-AI Feature APIs.

Consolidated schemas for:
- Smart Minutes (결과지 자동 생성)
- Calendar Sync (캘린더 연동)
- Handover (인수인계서 생성)

Separated from individual *_dto.py files for feature-specific types.
"""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Smart Minutes (결과지 자동 생성)
# =============================================================================

class AgendaSummary(BaseModel):
    """Summary of a single agenda item extracted from transcript."""
    
    agenda_type: str = Field(
        ...,
        description="Type of agenda (report, discuss, decision, other)",
        examples=["report", "discuss"],
    )
    agenda_number: int | None = Field(
        default=None,
        description="Agenda item number if available",
    )
    title: str = Field(
        ...,
        description="Agenda item title",
        examples=["컴씨 장소 선정"],
    )
    summary: str = Field(
        ...,
        description="Summary of decisions or discussion progress",
        examples=["오크밸리로 결정. 7월 넷째주 사전답사 예정."],
    )
    has_decision: bool = Field(
        default=False,
        description="Whether a concrete decision was made",
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="List of action items extracted from this agenda",
    )


class MinutesGenerationRequest(BaseModel):
    """Request for Smart Minutes generation (결과지 자동 생성).
    
    Supports:
    1. DB Document ID (source_document_id) - PREFERRED: Uses preprocessed_content from RAG pipeline
    2. Google Doc ID (transcript_doc_id) - DEPRECATED: Server fetches via Docs API
    3. Direct text (transcript_text) - Fallback for flexibility
    """
    
    agenda_doc_id: str = Field(
        ...,
        description="Google Docs ID of the agenda template (안건지)",
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
    )
    source_document_id: int | None = Field(
        default=None,
        description="DB Document ID (속기록). PREFERRED: Uses preprocessed_content from RAG pipeline.",
    )
    transcript_doc_id: str | None = Field(
        default=None,
        description="[DEPRECATED] Google Docs ID of the transcript. Use source_document_id instead.",
    )
    transcript_text: str | None = Field(
        default=None,
        description="Direct transcript text. Fallback if neither source_document_id nor transcript_doc_id provided.",
        min_length=10,
    )
    template_doc_id: str | None = Field(
        default=None,
        description="Google Docs ID of result template. If None, copies agenda_doc_id.",
    )
    meeting_name: str = Field(
        ...,
        description="Meeting name for output document title",
        examples=["제5차 집행위원회 국장단 회의"],
    )
    meeting_date: date = Field(
        ...,
        description="Meeting date",
    )
    output_folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID for output document (requires quota)",
    )
    output_doc_id: str | None = Field(
        default=None,
        description="Pre-created Google Docs ID for result. If provided, skips document creation (recommended to avoid quota issues).",
    )
    user_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="User access level",
    )
    user_email: str | None = Field(
        default=None,
        description="User email to share the output document with (required for Service Account mode)",
        examples=["user@example.com"],
    )
    
    @field_validator("transcript_text")
    @classmethod
    def validate_transcript_source(cls, v, info):
        """Ensure at least one transcript source is provided."""
        source_doc_id = info.data.get("source_document_id")
        transcript_doc_id = info.data.get("transcript_doc_id")
        if not v and not transcript_doc_id and not source_doc_id:
            raise ValueError("Either source_document_id, transcript_doc_id, or transcript_text must be provided")
        return v


class MinutesGenerationResponse(BaseModel):
    """Response for Smart Minutes generation request."""
    
    task_id: str = Field(
        ...,
        description="Celery task ID for tracking progress",
    )
    status: str = Field(
        default="PENDING",
        description="Task status",
    )
    message: str = Field(
        ...,
        description="Status message",
    )


class MinutesGenerationResult(BaseModel):
    """Final result of Smart Minutes generation (returned by Celery task)."""
    
    status: str = Field(..., description="SUCCESS or FAILURE")
    output_doc_id: str | None = Field(
        default=None,
        description="Google Docs ID of generated result document",
    )
    output_doc_link: str | None = Field(
        default=None,
        description="Direct link to the generated document",
    )
    meeting_name: str = Field(..., description="Meeting name")
    agenda_summaries: list[AgendaSummary] = Field(
        default_factory=list,
        description="Summaries of each agenda item",
    )
    items_processed: int = Field(default=0, description="Number of agenda items processed")
    decisions_extracted: int = Field(default=0, description="Number of decisions found")
    action_items_extracted: int = Field(default=0, description="Number of action items found")
    error: str | None = Field(default=None, description="Error message if failed")


# =============================================================================
# Calendar Sync (캘린더 연동 - Human-in-the-Loop)
# =============================================================================

class TodoItem(BaseModel):
    """A single todo/action item extracted from document."""
    
    content: str = Field(
        ...,
        description="The task content",
        examples=["MT 장소 예약"],
    )
    context: str | None = Field(
        default=None,
        description="Context or source (e.g., which agenda item)",
        examples=["문화국 보고"],
    )
    assignee: str | None = Field(
        default=None,
        description="Assigned person or department",
        examples=["문화국", "김철수"],
    )
    suggested_date: str | None = Field(
        default=None,
        description="Suggested deadline from document (raw text)",
        examples=["4월 20일까지", "다음 주"],
    )
    parsed_date: date | None = Field(
        default=None,
        description="Parsed date if successfully extracted",
    )


class TodoExtractionRequest(BaseModel):
    """Request for extracting todos from a document."""
    
    result_doc_id: str = Field(
        ...,
        description="Google Docs ID of the result/minutes document",
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
    )
    include_context: bool = Field(
        default=True,
        description="Whether to include source context for each todo",
    )


class TodoExtractionResponse(BaseModel):
    """Response containing extracted todos from document.
    
    This is a synchronous endpoint - no Celery task needed.
    Frontend displays these to user for confirmation before calendar registration.
    """
    
    todos: list[TodoItem] = Field(
        ...,
        description="List of extracted todo items",
    )
    document_title: str | None = Field(
        default=None,
        description="Title of source document",
    )
    extracted_at: datetime = Field(
        default_factory=datetime.now,
        description="Extraction timestamp",
    )
    total_count: int = Field(
        default=0,
        description="Total number of todos extracted",
    )


class CalendarEventCreate(BaseModel):
    """Request to create a calendar event (after user confirmation)."""
    
    summary: str = Field(
        ...,
        description="Event title/summary",
        min_length=1,
        max_length=500,
        examples=["MT 장소 예약"],
    )
    dt_start: datetime = Field(
        ...,
        description="Event start datetime",
    )
    dt_end: datetime | None = Field(
        default=None,
        description="Event end datetime. If None, defaults to 1 hour after start.",
    )
    description: str | None = Field(
        default=None,
        description="Event description",
        max_length=5000,
    )
    assignee_email: str | None = Field(
        default=None,
        description="Email of assignee to add as attendee",
    )
    calendar_id: str = Field(
        default="primary",
        description="Target Google Calendar ID",
        examples=["primary", "shared@group.calendar.google.com"],
    )
    reminder_minutes: int = Field(
        default=60,
        ge=0,
        le=40320,
        description="Reminder before event in minutes",
    )
    source_doc_id: str | None = Field(
        default=None,
        description="Source document ID for reference",
    )
    
    @field_validator("dt_end")
    @classmethod
    def set_default_end(cls, v, info):
        """Set default end time to 1 hour after start if not provided."""
        if v is None:
            dt_start = info.data.get("dt_start")
            if dt_start:
                from datetime import timedelta
                return dt_start + timedelta(hours=1)
        return v


class CalendarEventCreateResponse(BaseModel):
    """Response after creating a calendar event."""
    
    event_id: str = Field(..., description="Google Calendar event ID")
    calendar_id: str = Field(..., description="Calendar ID where event was created")
    summary: str = Field(..., description="Event title")
    start_time: datetime = Field(..., description="Event start time")
    end_time: datetime = Field(..., description="Event end time")
    html_link: str | None = Field(
        default=None,
        description="Direct link to event in Google Calendar",
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Creation timestamp",
    )


# =============================================================================
# Handover (인수인계서 생성)
# =============================================================================

class EventSummary(BaseModel):
    """Summary of an event for handover document."""
    
    event_id: int = Field(..., description="Event ID from database")
    title: str = Field(..., description="Event title")
    year: int = Field(..., description="Event year")
    category: str | None = Field(default=None, description="Event category (문화국, 복지국, etc.)")
    event_date: date | None = Field(default=None, description="Main event date")
    status: str = Field(..., description="Event status")
    summary: str | None = Field(default=None, description="AI-generated summary")
    key_decisions: list[str] = Field(default_factory=list, description="Key decisions made")
    lessons_learned: str | None = Field(default=None, description="Lessons learned")
    documents_count: int = Field(default=0, description="Number of related documents")


class HandoverGenerationRequest(BaseModel):
    """Request for handover document generation."""
    
    target_year: int = Field(
        ...,
        description="Target year for handover",
        examples=[2025],
        ge=2020,
        le=2030,
    )
    department: str | None = Field(
        default=None,
        description="Department filter (None for all departments)",
        examples=["문화국", "복지국", "디자인홍보국"],
    )
    target_folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID for output document",
    )
    doc_title: str = Field(
        default="",
        description="Output document title. If empty, auto-generated.",
    )
    include_event_summaries: bool = Field(
        default=True,
        description="Include summary of each event",
    )
    include_insights: bool = Field(
        default=True,
        description="Include LLM-generated insights and recommendations",
    )
    include_statistics: bool = Field(
        default=True,
        description="Include statistics (event count, meeting count, etc.)",
    )
    user_level: int = Field(
        default=1,
        ge=1,
        le=4,
        description="User access level (handover typically requires level 1-2)",
    )
    
    @field_validator("doc_title")
    @classmethod
    def set_default_title(cls, v, info):
        """Generate default title if not provided."""
        if not v:
            year = info.data.get("target_year", 2025)
            dept = info.data.get("department")
            if dept:
                return f"제38대 {dept} 인수인계서 ({year})"
            return f"제38대 학생회 인수인계서 ({year})"
        return v


class HandoverGenerationResponse(BaseModel):
    """Response for handover generation request."""
    
    task_id: str = Field(..., description="Celery task ID for tracking")
    status: str = Field(default="PENDING", description="Task status")
    message: str = Field(..., description="Status message")
    estimated_time_minutes: int = Field(
        default=5,
        description="Estimated processing time",
    )


class HandoverStatistics(BaseModel):
    """Statistics included in handover document."""
    
    total_events: int = Field(default=0, description="Total events processed")
    total_meetings: int = Field(default=0, description="Total meetings held")
    total_documents: int = Field(default=0, description="Total documents analyzed")
    events_by_category: dict[str, int] = Field(
        default_factory=dict,
        description="Event count per category",
    )
    events_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Event count per status",
    )


class HandoverGenerationResult(BaseModel):
    """Final result of handover generation (returned by Celery task)."""
    
    status: str = Field(..., description="SUCCESS or FAILURE")
    output_doc_id: str | None = Field(
        default=None,
        description="Google Docs ID of generated handover document",
    )
    output_doc_link: str | None = Field(
        default=None,
        description="Direct link to the document",
    )
    doc_title: str = Field(..., description="Document title")
    target_year: int = Field(..., description="Target year")
    department: str | None = Field(default=None, description="Department filter used")
    statistics: HandoverStatistics = Field(
        default_factory=HandoverStatistics,
        description="Processing statistics",
    )
    event_summaries: list[EventSummary] = Field(
        default_factory=list,
        description="Summaries of each event",
    )
    error: str | None = Field(default=None, description="Error message if failed")
