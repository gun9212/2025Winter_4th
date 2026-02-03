"""Calendar API endpoints for event management.

Human-in-the-Loop Calendar Sync:
- Extract todos from result documents (POST /extract-todos)
- Create calendar events after user confirmation (POST /events/create)

Legacy endpoints are marked as deprecated.
"""

from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import ApiKey, DbSession
from app.schemas.calendar_dto import (
    CalendarSyncRequest,
    CalendarSyncResponse,
    EventCreateRequest,
    EventListResponse,
    EventResponse,
)
from app.schemas.features_dto import (
    CalendarEventCreate,
    CalendarEventCreateResponse,
    TodoExtractionRequest,
    TodoExtractionResponse,
    TodoItem,
)

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# Human-in-the-Loop Calendar Sync (Recommended)
# =============================================================================


@router.post(
    "/extract-todos",
    response_model=TodoExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract todos from document",
    description="""
    Extract action items/todos from a result document.
    
    **Human-in-the-Loop Flow:**
    1. This endpoint extracts todos and returns them immediately (synchronous)
    2. Frontend displays the todos to user for review/edit
    3. User confirms which items to add to calendar
    4. Frontend calls POST /calendar/events/create for each confirmed item
    
    **No automatic calendar sync** - user has full control.
    
    **Date Parsing:**
    - Server attempts to parse dates (e.g., "4월 20일까지", "다음 주")
    - If parsing fails, `parsed_date` will be null
    - Frontend can display `suggested_date` (raw text) for user to manually set
    """,
)
async def extract_todos(
    request: TodoExtractionRequest,
    db: DbSession,
    api_key: ApiKey,
) -> TodoExtractionResponse:
    """
    Extract todo items from a result document for user review.
    
    This is a synchronous endpoint - no Celery task needed.
    Results are returned immediately for user confirmation.
    """
    try:
        from app.services.google.docs import GoogleDocsService
        from app.services.ai.gemini import GeminiService
        
        # 1. Fetch document content from Google Docs
        docs_service = GoogleDocsService()
        doc = docs_service.get_document(request.result_doc_id)
        doc_title = doc.get("title", "Untitled")
        doc_text = docs_service.get_document_text(request.result_doc_id)
        
        logger.info(
            "Extracting todos from document",
            doc_id=request.result_doc_id[:8],
            doc_title=doc_title,
            content_length=len(doc_text),
        )
        
        # 2. Extract todos using Gemini
        gemini = GeminiService()
        extracted_items = gemini.extract_todos_from_document(
            content=doc_text,
            include_context=request.include_context,
        )
        
        # 3. Convert to response format with date parsing
        todos = []
        for item in extracted_items:
            # Server-side date parsing (best effort, null if failed)
            parsed_date = None
            if item.get("parsed_date"):
                try:
                    from datetime import date
                    parsed_date = date.fromisoformat(item["parsed_date"])
                except (ValueError, TypeError):
                    logger.debug(
                        "Date parsing failed",
                        raw_date=item.get("suggested_date"),
                    )
                    pass
            todos.append(TodoItem(
                content=item.get("content", ""),
                context=item.get("context") if request.include_context else None,
                assignee=item.get("assignee"),
                suggested_date=item.get("suggested_date"),
                parsed_date=parsed_date,
            ))
        
        logger.info(
            "Todos extracted successfully",
            doc_id=request.result_doc_id[:8],
            todos_count=len(todos),
        )
        
        return TodoExtractionResponse(
            todos=todos,
            document_title=doc_title,
            extracted_at=datetime.now(),
            total_count=len(todos),
        )
        
    except Exception as e:
        logger.error(
            "Failed to extract todos",
            doc_id=request.result_doc_id[:8],
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to extract todos: {str(e)}",
        )


@router.post(
    "/events/create",
    response_model=CalendarEventCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create calendar event (confirmed by user)",
    description="""
    Create a calendar event after user confirmation.
    
    This endpoint is called after user reviews and confirms todos
    extracted from POST /calendar/extract-todos.
    
    **Synchronous** - event is created immediately.
    """,
)
async def create_calendar_event(
    request: CalendarEventCreate,
    db: DbSession,
    api_key: ApiKey,
) -> CalendarEventCreateResponse:
    """
    Create a calendar event from user-confirmed todo item.
    """
    try:
        from app.services.google.calendar import GoogleCalendarService
        
        # Calculate end time if not provided
        dt_end = request.dt_end
        if dt_end is None:
            dt_end = request.dt_start + timedelta(hours=1)
        
        # Create calendar service with specified calendar
        calendar_service = GoogleCalendarService(calendar_id=request.calendar_id)
        
        # Create the event
        attendees = [request.assignee_email] if request.assignee_email else None
        
        event = calendar_service.create_event(
            title=request.summary,
            start_time=request.dt_start,
            end_time=dt_end,
            description=request.description,
            attendees=attendees,
            reminder_minutes=request.reminder_minutes,
        )
        
        logger.info(
            "Calendar event created",
            event_id=event.get("id"),
            summary=request.summary,
            calendar_id=request.calendar_id,
        )
        
        return CalendarEventCreateResponse(
            event_id=event.get("id", ""),
            calendar_id=request.calendar_id,
            summary=request.summary,
            start_time=request.dt_start,
            end_time=dt_end,
            html_link=event.get("htmlLink"),
            created_at=datetime.now(),
        )
        
    except Exception as e:
        logger.error(
            "Failed to create calendar event",
            summary=request.summary,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create calendar event: {str(e)}",
        )


# =============================================================================
# Legacy Calendar Endpoints (Deprecated - for backward compatibility)
# =============================================================================


@router.post(
    "/sync",
    response_model=CalendarSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="[Deprecated] Auto sync calendar from document",
    description="""
    **⚠️ DEPRECATED** - Use POST /calendar/extract-todos + POST /calendar/events/create instead.
    
    This endpoint automatically extracts and creates events without user confirmation.
    The new Human-in-the-Loop approach is recommended for better user control.
    """,
    deprecated=True,
)
async def sync_calendar_legacy(
    request: CalendarSyncRequest,
    db: DbSession,
    api_key: ApiKey,
) -> CalendarSyncResponse:
    """
    [Deprecated] Sync calendar events from a result document.
    
    Use the new Human-in-the-Loop approach instead:
    1. POST /calendar/extract-todos
    2. POST /calendar/events/create
    """
    logger.warning(
        "Deprecated endpoint called: /calendar/sync",
        doc_id=request.result_doc_id[:8] if request.result_doc_id else None,
    )
    
    # Return placeholder response - actual implementation removed
    task_id = f"calendar-sync-{request.result_doc_id[:8]}-deprecated"
    
    return CalendarSyncResponse(
        task_id=task_id,
        status="DEPRECATED",
        message="This endpoint is deprecated. Use /extract-todos + /events/create instead.",
        calendar_id=request.calendar_id,
    )


@router.post(
    "/events",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Deprecated] Create calendar event",
    description="**⚠️ DEPRECATED** - Use POST /calendar/events/create instead with CalendarEventCreate schema.",
    deprecated=True,
)
async def create_event_legacy(
    request: EventCreateRequest,
    db: DbSession,
    api_key: ApiKey,
) -> EventResponse:
    """
    [Deprecated] Create a calendar event using legacy schema.
    
    Use POST /calendar/events/create with CalendarEventCreate schema instead.
    """
    try:
        from app.services.google.calendar import GoogleCalendarService
        
        calendar_service = GoogleCalendarService()
        
        event = calendar_service.create_event(
            title=request.title,
            start_time=request.start_time,
            end_time=request.end_time,
            description=request.description,
            attendees=request.attendees,
            location=request.location,
            reminder_minutes=request.reminder_minutes,
        )
        
        return EventResponse(
            event_id=event.get("id", ""),
            title=request.title,
            start_time=request.start_time,
            end_time=request.end_time,
            description=request.description,
            attendees=request.attendees or [],
            location=request.location,
            calendar_link=event.get("htmlLink"),
            created_at=datetime.now(),
        )
    except Exception as e:
        logger.error("Failed to create event (legacy)", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create event: {str(e)}",
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

