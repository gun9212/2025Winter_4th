"""Schemas for meeting minutes API."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    """Processing status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class MeetingInfo(BaseModel):
    """Meeting information for minutes generation."""

    meeting_name: str = Field(
        ...,
        description="Meeting name (e.g., '제7차 국장단회의')",
        examples=["제7차 국장단회의", "제2차 정기총회"],
    )
    meeting_date: date = Field(
        ...,
        description="Date of the meeting",
    )
    attendees: list[str] = Field(
        default_factory=list,
        description="List of meeting attendees",
        examples=[["회장 홍길동", "부회장 임태빈", "문화국장 김철수"]],
    )
    department: str | None = Field(
        default=None,
        description="Department (e.g., '집행위원회', '문화국')",
    )


class OutputConfig(BaseModel):
    """Output configuration for generated document."""

    output_folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID for output document",
    )
    naming_format: str = Field(
        default="[결과지] {meeting_name}",
        description="Naming format for output document",
    )


class MinutesProcessRequest(BaseModel):
    """Request schema for processing meeting minutes (Smart Minutes)."""

    agenda_doc_id: str = Field(
        ...,
        description="Google Docs ID of the agenda template",
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
    )
    transcript_text: str = Field(
        ...,
        description="Meeting transcript or recording text",
        min_length=10,
        alias="transcript",  # Backward compatibility
    )
    result_template_doc_id: str | None = Field(
        default=None,
        description="Google Docs ID of the result template (optional)",
    )
    meeting_info: MeetingInfo = Field(
        ...,
        description="Meeting information",
    )
    output_config: OutputConfig = Field(
        default_factory=OutputConfig,
        description="Output configuration",
    )
    user_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="User access level",
    )


class MinutesProcessResponse(BaseModel):
    """Response schema for minutes processing request."""

    task_id: str = Field(
        ...,
        description="Task ID for tracking processing status",
    )
    status: ProcessingStatus = Field(
        ...,
        description="Current processing status",
    )
    message: str = Field(
        ...,
        description="Status message",
    )


class ActionItem(BaseModel):
    """Action item extracted from meeting."""

    task: str = Field(..., description="Task description")
    assignee: str | None = Field(default=None, description="Person responsible")
    due_date: date | None = Field(default=None, description="Due date")


class DecisionItem(BaseModel):
    """Decision made during meeting."""

    topic: str = Field(..., description="Topic of discussion")
    decision: str = Field(..., description="Decision made")


class MinutesStatusResponse(BaseModel):
    """Response schema for minutes processing status."""

    task_id: str = Field(..., description="Task ID")
    status: ProcessingStatus = Field(..., description="Current processing status")
    progress: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Processing progress percentage",
    )
    result_doc_id: str | None = Field(
        default=None,
        description="Google Docs ID of the generated minutes document",
    )
    result_doc_url: str | None = Field(
        default=None,
        description="URL to the generated minutes document",
    )
    decisions: list[DecisionItem] | None = Field(
        default=None,
        description="Extracted decisions",
    )
    action_items: list[ActionItem] | None = Field(
        default=None,
        description="Extracted action items",
    )
    error: str | None = Field(
        default=None,
        description="Error message if processing failed",
    )
    created_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
