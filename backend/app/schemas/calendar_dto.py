"""Schemas for Calendar API."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class EventCreateRequest(BaseModel):
    """Request schema for creating a calendar event."""

    title: str = Field(
        ...,
        description="Event title",
        min_length=1,
        max_length=500,
    )
    start_time: datetime = Field(
        ...,
        description="Event start datetime",
    )
    end_time: datetime = Field(
        ...,
        description="Event end datetime",
    )
    description: str | None = Field(
        default=None,
        description="Event description",
        max_length=5000,
    )
    attendees: list[str] | None = Field(
        default=None,
        description="List of attendee email addresses",
    )
    location: str | None = Field(
        default=None,
        description="Event location",
        max_length=500,
    )
    reminder_minutes: int | None = Field(
        default=30,
        ge=0,
        le=40320,  # Max 4 weeks
        description="Reminder before event in minutes",
    )

    @field_validator("end_time")
    @classmethod
    def end_time_after_start(cls, v: datetime, info) -> datetime:
        """Validate that end_time is after start_time."""
        start_time = info.data.get("start_time")
        if start_time and v <= start_time:
            raise ValueError("end_time must be after start_time")
        return v


class EventResponse(BaseModel):
    """Response schema for calendar event."""

    event_id: str = Field(..., description="Google Calendar event ID")
    title: str = Field(..., description="Event title")
    start_time: datetime = Field(..., description="Event start datetime")
    end_time: datetime = Field(..., description="Event end datetime")
    description: str | None = Field(default=None, description="Event description")
    attendees: list[str] = Field(default_factory=list, description="Attendee emails")
    location: str | None = Field(default=None, description="Event location")
    calendar_link: str | None = Field(
        default=None,
        description="Direct link to event in Google Calendar",
    )
    created_at: datetime = Field(..., description="Event creation timestamp")


class EventListResponse(BaseModel):
    """Response schema for event list."""

    total: int = Field(..., description="Total number of events")
    events: list[EventResponse] = Field(..., description="List of events")


# ================================
# Calendar Sync from Result Document
# ================================


class CalendarSyncOptions(BaseModel):
    """Options for calendar sync from result document."""

    create_reminders: bool = Field(
        default=True,
        description="Create reminders for extracted events",
    )
    notify_assignees: bool = Field(
        default=False,
        description="Send notifications to assignees",
    )
    default_duration_hours: int = Field(
        default=1,
        ge=1,
        le=24,
        description="Default event duration if not specified",
    )
    reminder_minutes: list[int] = Field(
        default=[60, 1440],  # 1 hour, 1 day before
        description="Reminder times in minutes before event",
    )


class ExtractionHints(BaseModel):
    """Hints for extracting calendar events from documents."""

    date_patterns: list[str] = Field(
        default=["~까지", "마감일:", "D-day", "마감:"],
        description="Patterns to identify dates",
    )
    assignee_patterns: list[str] = Field(
        default=["담당:", "담당자:", "책임:"],
        description="Patterns to identify assignees",
    )


class CalendarSyncRequest(BaseModel):
    """Request schema for syncing calendar from result document."""

    result_doc_id: str = Field(
        ...,
        description="Google Docs ID of the result/minutes document",
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
    )
    calendar_id: str = Field(
        ...,
        description="Google Calendar ID to sync events to",
        examples=["primary", "shared-calendar@group.calendar.google.com"],
    )
    options: CalendarSyncOptions = Field(
        default_factory=CalendarSyncOptions,
        description="Sync options",
    )
    extraction_hints: ExtractionHints = Field(
        default_factory=ExtractionHints,
        description="Hints for event extraction",
    )
    user_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="User access level",
    )


class CalendarSyncResponse(BaseModel):
    """Response schema for calendar sync request."""

    task_id: str = Field(..., description="Celery task ID for tracking")
    status: str = Field(default="PENDING", description="Initial task status")
    message: str = Field(..., description="Status message")
    calendar_id: str = Field(..., description="Target calendar ID")

