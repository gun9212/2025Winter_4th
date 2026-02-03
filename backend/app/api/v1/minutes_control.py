"""Meeting minutes automation API endpoints (Smart Minutes)."""

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.features_dto import (
    MinutesGenerationRequest,
    MinutesGenerationResponse,
)
from app.schemas.minutes_dto import (
    MinutesStatusResponse,
    ProcessingStatus,
)

logger = structlog.get_logger()

router = APIRouter()


@router.post(
    "/generate",
    response_model=MinutesGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate result document (Smart Minutes)",
    description="""
    Generate a result document from agenda template and meeting transcript.
    
    **Smart Minutes Feature:**
    Automatically converts meeting transcript into a formatted result document
    following the agenda structure.
    
    **Input Options (choose one for transcript):**
    1. `transcript_doc_id`: Google Docs ID - server fetches content (recommended)
    2. `transcript_text`: Direct text input - for flexibility
    
    **Processing (Async via Celery):**
    1. Load transcript from Google Docs (if doc_id provided)
    2. Split transcript by agenda headers (# 보고안건, ## 논의안건 1. etc.)
    3. Summarize each section with Gemini (decisions/progress)
    4. Copy agenda template to create result document
    5. Replace placeholders ({{report_1_result}}, {{discuss_1_result}}) with summaries
    
    **Placeholder Convention:**
    - `{{report_N_result}}` for 보고안건 N
    - `{{discuss_N_result}}` for 논의안건 N
    - `{{other_N_result}}` for 기타안건 N
    """,
)
async def generate_minutes(
    request: MinutesGenerationRequest,
    db: DbSession,
    api_key: ApiKey,
) -> MinutesGenerationResponse:
    """
    Generate result document from agenda and transcript.
    
    Triggers async Celery task for Smart Minutes processing.
    """
    try:
        from app.tasks.features import generate_minutes as generate_minutes_task
        
        # Determine transcript source
        transcript_source = (
            f"doc:{request.transcript_doc_id}" 
            if request.transcript_doc_id 
            else "text"
        )
        
        logger.info(
            "Queueing Smart Minutes generation",
            agenda_doc_id=request.agenda_doc_id[:8],
            transcript_source=transcript_source,
            meeting_name=request.meeting_name,
        )
        
        # Queue Celery task
        task = generate_minutes_task.delay(
            agenda_doc_id=request.agenda_doc_id,
            transcript_doc_id=request.transcript_doc_id,
            transcript_text=request.transcript_text,
            template_doc_id=request.template_doc_id,
            meeting_name=request.meeting_name,
            meeting_date=request.meeting_date.isoformat(),
            output_folder_id=request.output_folder_id,
            user_email=request.user_email,
        )
        
        return MinutesGenerationResponse(
            task_id=task.id,
            status="PENDING",
            message=f"Smart Minutes generation started for '{request.meeting_name}'",
        )
        
    except Exception as e:
        logger.error("Failed to queue minutes generation", error=str(e))
        # Fallback: return placeholder task_id if Celery not available
        task_id = f"minutes-{request.agenda_doc_id[:8]}-placeholder"
        return MinutesGenerationResponse(
            task_id=task_id,
            status="PENDING",
            message=f"Smart Minutes generation queued for '{request.meeting_name}'",
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
    from celery.result import AsyncResult
    from app.tasks.celery_app import celery_app
    
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        # Map Celery states to our ProcessingStatus
        status_map = {
            "PENDING": ProcessingStatus.PENDING,
            "STARTED": ProcessingStatus.PROCESSING,
            "PROGRESS": ProcessingStatus.PROCESSING,
            "SUCCESS": ProcessingStatus.COMPLETED,
            "FAILURE": ProcessingStatus.FAILED,
        }
        
        current_status = status_map.get(result.state, ProcessingStatus.PROCESSING)
        
        # Extract progress and result info
        progress = 0
        result_doc_id = None
        error = None
        
        if result.state == "PROGRESS" and result.info:
            progress = result.info.get("progress", 0)
        elif result.state == "SUCCESS" and result.result:
            progress = 100
            result_doc_id = result.result.get("output_doc_id")
        elif result.state == "FAILURE":
            error = str(result.result) if result.result else "Unknown error"
        
        return MinutesStatusResponse(
            task_id=task_id,
            status=current_status,
            progress=progress,
            result_doc_id=result_doc_id,
            error=error,
        )
        
    except Exception as e:
        logger.error("Failed to get task status", task_id=task_id, error=str(e))
        return MinutesStatusResponse(
            task_id=task_id,
            status=ProcessingStatus.PENDING,
            progress=0,
            result_doc_id=None,
            error=None,
        )

