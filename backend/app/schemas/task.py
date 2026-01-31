"""Schemas for Celery task status API."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Celery task status enumeration."""

    PENDING = "PENDING"
    STARTED = "STARTED"
    PROGRESS = "PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    REVOKED = "REVOKED"


class TaskResult(BaseModel):
    """Result data for completed tasks."""

    output_doc_id: str | None = Field(
        default=None,
        description="Google Doc ID of generated document",
    )
    output_doc_link: str | None = Field(
        default=None,
        description="Direct link to output document",
    )
    items_processed: int = Field(
        default=0,
        description="Number of items processed",
    )
    events_created: int | None = Field(
        default=None,
        description="Number of calendar events created (for calendar sync)",
    )
    # Additional fields for ingestion
    documents_processed: int | None = Field(
        default=None,
        description="Number of documents processed (for ingestion)",
    )
    chunks_created: int | None = Field(
        default=None,
        description="Number of chunks created (for ingestion)",
    )


class TaskStatusResponse(BaseModel):
    """Response schema for task status query."""

    task_id: str = Field(..., description="Celery task ID")
    status: TaskStatus = Field(..., description="Current task status")
    progress: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Progress percentage (0-100)",
    )
    result: TaskResult | None = Field(
        default=None,
        description="Task result (available when SUCCESS)",
    )
    error: str | None = Field(
        default=None,
        description="Error message (available when FAILURE)",
    )
    started_at: datetime | None = Field(
        default=None,
        description="Task start timestamp",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Task completion timestamp",
    )
    task_name: str | None = Field(
        default=None,
        description="Task function name",
    )


class TaskQueueResponse(BaseModel):
    """Response when a task is queued."""

    task_id: str = Field(..., description="Celery task ID for tracking")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Initial task status",
    )
    message: str = Field(..., description="Status message")
