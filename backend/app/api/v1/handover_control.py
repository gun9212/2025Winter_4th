"""Handover document generation API endpoint."""

import structlog
from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.features_dto import (
    HandoverGenerationRequest,
    HandoverGenerationResponse,
)

logger = structlog.get_logger()

router = APIRouter()


@router.post(
    "/generate",
    response_model=HandoverGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate handover document",
    description="""
    Generate a comprehensive handover document for a specific year.
    
    **Processing (Async via Celery):**
    1. Query DB for all Events and Documents of target year
    2. Filter by department if specified
    3. Prioritize: 결과지 > 속기록 > 안건지
    4. Generate insights using Gemini
    5. Create Google Doc with insertText
    
    **Output Structure:**
    - 개요: 연간 학생회 활동 소개
    - 조직 구성: 주요 보직 및 담당 업무
    - 주요 사업 총괄: 타임라인 및 성과
    - 사업별 상세 기록: 기획 의도, 진행 과정, 결과, 피드백
    - 예산 운용 개요
    - 주요 결정사항 아카이브
    - 차기 학생회를 위한 제언 (optional)
    
    **Estimated Time:** 2-5 minutes depending on data volume
    """,
)
async def generate_handover(
    request: HandoverGenerationRequest,
    db: DbSession,
    api_key: ApiKey,
) -> HandoverGenerationResponse:
    """
    Queue a handover document generation task.
    """
    # Validate access level
    if request.user_level > 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Handover generation requires level 1 or 2 access",
        )
    
    try:
        from app.tasks.features import generate_handover as generate_handover_task
        
        logger.info(
            "Queueing handover generation",
            year=request.target_year,
            department=request.department,
        )
        
        # Generate doc title if not provided
        doc_title = request.doc_title
        if not doc_title:
            dept_text = f"{request.department} " if request.department else ""
            doc_title = f"제38대 {dept_text}학생회 인수인계서 ({request.target_year})"
        
        # Queue Celery task
        task = generate_handover_task.delay(
            target_year=request.target_year,
            department=request.department,
            target_folder_id=request.target_folder_id,
            doc_title=doc_title,
            include_event_summaries=request.include_event_summaries,
            include_insights=request.include_insights,
            include_statistics=request.include_statistics,
        )
        
        return HandoverGenerationResponse(
            task_id=task.id,
            status="PENDING",
            message=f"Handover generation for {request.target_year} queued successfully",
            estimated_time_minutes=5,
        )
        
    except Exception as e:
        logger.error("Failed to queue handover generation", error=str(e))
        # Fallback
       raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue task: {str(e)}"
        )


@router.get(
    "/{task_id}/status",
    summary="Get handover generation status",
    description="Check the status of a handover generation task.",
)
async def get_handover_status(
    task_id: str,
    api_key: ApiKey,
):
    """
    Get the status of a handover generation task.
    """
    from celery.result import AsyncResult
    from app.tasks.celery_app import celery_app
    
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        # Extract progress and result info
        progress = 0
        step = None
        output_doc_id = None
        output_doc_link = None
        error = None
        
        if result.state == "PROGRESS" and result.info:
            progress = result.info.get("progress", 0)
            step = result.info.get("step")
        elif result.state == "SUCCESS" and result.result:
            progress = 100
            output_doc_id = result.result.get("output_doc_id")
            output_doc_link = result.result.get("output_doc_link")
        elif result.state == "FAILURE":
            error = str(result.result) if result.result else "Unknown error"
        
        return {
            "task_id": task_id,
            "status": result.state,
            "progress": progress,
            "step": step,
            "output_doc_id": output_doc_id,
            "output_doc_link": output_doc_link,
            "error": error,
        }
        
    except Exception as e:
        logger.error("Failed to get task status", task_id=task_id, error=str(e))
        return {
            "task_id": task_id,
            "status": "UNKNOWN",
            "progress": 0,
            "error": str(e),
        }