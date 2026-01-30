"""Meeting minutes automation API endpoints."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.minutes import (
    MinutesProcessRequest,
    MinutesProcessResponse,
    MinutesStatusResponse,
    ProcessingStatus,
)

router = APIRouter()


@router.post(
    "/process",
    response_model=MinutesProcessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Process meeting minutes",
    description="Submit an agenda document and transcript for automated minutes generation.",
)
async def process_minutes(
    request: MinutesProcessRequest,
    background_tasks: BackgroundTasks,
    db: DbSession,
    api_key: ApiKey,
) -> MinutesProcessResponse:
    """
    Process meeting minutes from agenda document and transcript.

    - **agenda_doc_id**: Google Docs ID of the agenda template
    - **transcript**: Meeting transcript or recording text
    - **meeting_date**: Optional meeting date
    - **attendees**: Optional list of attendees
    """
    # TODO: Implement actual processing logic
    # 1. Load agenda template from Google Docs
    # 2. Analyze transcript with LLM
    # 3. Extract decisions and action items
    # 4. Create result document

    task_id = "task-placeholder"  # Will be replaced with actual Celery task ID

    # background_tasks.add_task(process_minutes_task, request, task_id)

    return MinutesProcessResponse(
        task_id=task_id,
        status=ProcessingStatus.PENDING,
        message="Minutes processing started",
    )


@router.get(
    "/{doc_id}/status",
    response_model=MinutesStatusResponse,
    summary="Get processing status",
    description="Check the status of a minutes processing task.",
)
async def get_minutes_status(
    doc_id: str,
    db: DbSession,
    api_key: ApiKey,
) -> MinutesStatusResponse:
    """
    Get the status of a minutes processing task.

    - **doc_id**: The task ID or document ID to check
    """
    # TODO: Implement status checking logic
    # Query Celery task status or database

    return MinutesStatusResponse(
        task_id=doc_id,
        status=ProcessingStatus.PENDING,
        progress=0,
        result_doc_id=None,
        error=None,
    )
