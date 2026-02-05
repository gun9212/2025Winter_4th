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
    summary="Generate result document (Smart Minutes v2.1)",
    description="""
    Generate a result document from agenda template and meeting transcript.
    
    **v2.1 Smart Minutes Architecture:**
    - Uses transcript_doc_id (Google Drive ID) from Picker
    - Backend queries DB by drive_id to get preprocessed_content
    - If not found or not COMPLETED → returns error with Admin tab guidance
    
    **Required Input:**
    1. `agenda_doc_id`: Google Docs ID of agenda template (안건지)
    2. `transcript_doc_id`: Google Drive ID of transcript (속기록) - from Picker
    
    **Optional Input:**
    - `output_doc_id`: Pre-created result document ID
    - `output_folder_id`: Google Drive folder ID for output
    
    **Processing (Async via Celery - 4 Phases):**
    - Phase 0: DB Lookup by Drive ID + RAG Validation
    - Phase 1: Template Preparation (Placeholder Injection)
    - Phase 2: Summarization with Gemini
    - Phase 3: Replacement + Fallback
    
    **Error Handling:**
    - If document not found in DB: "Admin 탭에서 먼저 자료학습을 진행해주세요!"
    - If document not COMPLETED: "아직 학습 중입니다. Admin 탭에서 상태를 확인해주세요."
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
        
        logger.info(
            "Queueing Smart Minutes v2.1 generation",
            agenda_doc_id=request.agenda_doc_id[:8],
            transcript_doc_id=request.transcript_doc_id[:16] if request.transcript_doc_id else None,
            meeting_name=request.meeting_name,
        )
        
        # Queue Celery task with v2.1 parameters
        task = generate_minutes_task.delay(
            agenda_doc_id=request.agenda_doc_id,
            transcript_doc_id=request.transcript_doc_id,  # v2.1: Drive ID from Picker
            template_doc_id=request.template_doc_id,
            meeting_name=request.meeting_name,
            meeting_date=request.meeting_date.isoformat(),
            output_folder_id=request.output_folder_id,
            output_doc_id=request.output_doc_id,
            user_email=request.user_email,
        )
        
        return MinutesGenerationResponse(
            task_id=task.id,
            status="PENDING",
            message=f"Smart Minutes v2.0 generation started for '{request.meeting_name}'",
        )
        
    except Exception as e:
        logger.error("Failed to queue minutes generation", error=str(e))
        # Fallback: return placeholder task_id if Celery not available
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue task: {str(e)}"
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

