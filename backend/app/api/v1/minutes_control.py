"""Meeting minutes automation API endpoints (Smart Minutes)."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.minutes_dto import (
    MinutesProcessRequest,
    MinutesProcessResponse,
    MinutesStatusResponse,
    ProcessingStatus,
)

router = APIRouter()


@router.post(
    "/generate",
    response_model=MinutesProcessResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate result document (Smart Minutes)",
    description="""
    Generate a result document from agenda template and meeting transcript.
    
    **Smart Minutes Feature:**
    Automatically converts meeting recording/transcript into a formatted
    result document following the agenda structure.
    
    **Processing (Async via Celery):**
    1. Read agenda template via Docs API
    2. Analyze transcript with Gemini
    3. Extract decisions and action items per agenda item
    4. Populate template with results
    5. Create new Google Doc with batchUpdate
    
    **Input:**
    - Agenda Doc ID (template structure)
    - Transcript text (meeting recording converted to text)
    - Result template Doc ID (optional)
    - Meeting info (name, date, attendees, department)
    
    **Output:**
    A formatted result document in Google Docs with:
    - Report items with results
    - Discussion items with decisions
    - Action items table (task, assignee, deadline)
    """,
)
async def generate_minutes(
    request: MinutesProcessRequest,
    db: DbSession,
    api_key: ApiKey,
) -> MinutesProcessResponse:
    """
    Generate result document from agenda and transcript.
    
    Triggers async Celery task for Smart Minutes processing.
    Uses Gemini to analyze transcript and populate agenda template.
    """
    # TODO: Queue Celery task
    # from app.tasks.features import generate_minutes as generate_minutes_task
    # task = generate_minutes_task.delay(
    #     agenda_doc_id=request.agenda_doc_id,
    #     transcript_text=request.transcript_text,
    #     result_template_doc_id=request.result_template_doc_id,
    #     meeting_info=request.meeting_info.model_dump(),
    #     output_config=request.output_config.model_dump(),
    # )
    
    task_id = f"minutes-{request.agenda_doc_id[:8]}-placeholder"

    return MinutesProcessResponse(
        task_id=task_id,
        status=ProcessingStatus.PENDING,
        message=f"Smart Minutes generation started for '{request.meeting_info.meeting_name}'",
    )


@router.get(
    "/{task_id}/status",
    response_model=MinutesStatusResponse,
    summary="Get processing status",
    description="Check the status of a minutes processing task.",
)
async def get_minutes_status(
    task_id: str,
    db: DbSession,
    api_key: ApiKey,
) -> MinutesStatusResponse:
    """
    Get the status of a minutes processing task.

    - **task_id**: The Celery task ID to check
    """
    # TODO: Implement status checking logic
    # from celery.result import AsyncResult
    # result = AsyncResult(task_id)

    return MinutesStatusResponse(
        task_id=task_id,
        status=ProcessingStatus.PENDING,
        progress=0,
        result_doc_id=None,
        error=None,
    )

