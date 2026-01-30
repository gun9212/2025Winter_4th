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


class MinutesProcessRequest(BaseModel):
    """Request schema for processing meeting minutes."""

    agenda_doc_id: str = Field(
        ...,
        description="Google Docs ID of the agenda template",
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
    )
    transcript: str = Field(
        ...,
        description="Meeting transcript or recording text",
        min_length=10,
    )
    meeting_date: date | None = Field(
        default=None,
        description="Date of the meeting",
    )
    attendees: list[str] | None = Field(
        default=None,
        description="List of meeting attendees",
    )
    output_folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID for output document",
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
