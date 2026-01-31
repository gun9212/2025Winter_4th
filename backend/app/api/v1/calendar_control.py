"""Calendar API endpoints for event management."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.calendar_dto import (
    CalendarSyncRequest,
    CalendarSyncResponse,
    EventCreateRequest,
    EventListResponse,
    EventResponse,
)

router = APIRouter()


@router.post(
    "/sync",
    response_model=CalendarSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync calendar from document",
    description="""
    Extract action items from a result document and create calendar events.
    
    **Calendar ID Parameter:**
    Supports multiple calendars per user's request. Pass the target
    Google Calendar ID to sync events to.
    
    **Processing (Async via Celery):**
    1. Read result document via Docs API
    2. Extract action items with dates and assignees
    3. Create calendar events via Calendar API
    4. Optionally send notifications to assignees
    
    **Extraction Patterns:**
    - Date: "~까지", "마감일:", "D-day"
    - Assignee: "담당:", "담당자:", "책임:"
    """,
)
async def sync_calendar(
    request: CalendarSyncRequest,
    db: DbSession,
    api_key: ApiKey,
) -> CalendarSyncResponse:
    """
    Sync calendar events from a result document.
    
    Extracts action items and deadlines from the document
    and creates corresponding Google Calendar events.
    """
    # TODO: Queue Celery task
    # from app.tasks.features import sync_calendar as sync_calendar_task
    # task = sync_calendar_task.delay(
    #     result_doc_id=request.result_doc_id,
    #     calendar_id=request.calendar_id,
    #     options=request.options.model_dump(),
    #     extraction_hints=request.extraction_hints.model_dump(),
    # )
    
    task_id = f"calendar-sync-{request.result_doc_id[:8]}-placeholder"
    
    return CalendarSyncResponse(
        task_id=task_id,
        status="PENDING",
        message="Calendar sync task queued successfully",
        calendar_id=request.calendar_id,
    )


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create calendar event",
    description="Create a new event in the shared Google Calendar.",
)
async def create_event(
    request: EventCreateRequest,
    db: DbSession,
    api_key: ApiKey,
) -> EventResponse:
    """
    Create a calendar event.

    - **title**: Event title
    - **start_time**: Event start datetime
    - **end_time**: Event end datetime
    - **description**: Optional event description
    - **attendees**: Optional list of attendee emails
    - **location**: Optional event location
    """
    # TODO: Implement Google Calendar API integration
    # 1. Validate request
    # 2. Create event using Calendar API
    # 3. Store reference in database

    return EventResponse(
        event_id="event-placeholder",
        title=request.title,
        start_time=request.start_time,
        end_time=request.end_time,
        description=request.description,
        attendees=request.attendees or [],
        location=request.location,
        calendar_link=None,
        created_at=datetime.now(),
    )


@router.get(
    "/events",
    response_model=EventListResponse,
    summary="List calendar events",
    description="Get a list of calendar events within a date range.",
)
async def list_events(
    db: DbSession,
    api_key: ApiKey,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 50,
) -> EventListResponse:
    """
    List calendar events.

    - **start_date**: Filter events starting from this date
    - **end_date**: Filter events ending before this date
    - **limit**: Maximum number of events to return
    """
    # TODO: Query Google Calendar API
    # 1. Build time range filter
    # 2. Fetch events from Calendar API
    # 3. Return formatted response

    return EventListResponse(
        total=0,
        events=[],
    )


@router.get(
    "/events/{event_id}",
    response_model=EventResponse,
    summary="Get calendar event",
    description="Get details of a specific calendar event.",
)
async def get_event(
    event_id: str,
    db: DbSession,
    api_key: ApiKey,
) -> EventResponse:
    """
    Get a specific calendar event by ID.

    - **event_id**: The Google Calendar event ID
    """
    # TODO: Fetch event from Google Calendar API

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Event {event_id} not found",
    )


@router.delete(
    "/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete calendar event",
    description="Delete a calendar event.",
)
async def delete_event(
    event_id: str,
    db: DbSession,
    api_key: ApiKey,
) -> None:
    """
    Delete a calendar event.

    - **event_id**: The Google Calendar event ID to delete
    """
    # TODO: Delete event from Google Calendar API

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Event {event_id} not found",
    )

