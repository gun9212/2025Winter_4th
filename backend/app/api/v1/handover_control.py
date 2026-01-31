"""Handover document generation API endpoint."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.handover_dto import (
    HandoverGenerateRequest,
    HandoverGenerateResponse,
)

router = APIRouter()


@router.post(
    "/generate",
    response_model=HandoverGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate handover document",
    description="""
    Generate a comprehensive handover document for a specific year and department.
    
    **Processing (Async via Celery):**
    1. Query DB for all Events and Result Documents of target year
    2. Filter by department and access level
    3. Synthesize insights using Gemini
    4. Generate long-form document in Google Docs
    
    **Estimated Time:** 2-5 minutes depending on data volume
    
    **Required Access:** Typically level 1-2 (executive level)
    """,
)
async def generate_handover(
    request: HandoverGenerateRequest,
    db: DbSession,
    api_key: ApiKey,
) -> HandoverGenerateResponse:
    """
    Queue a handover document generation task.
    
    This is a long-running operation that:
    - Processes all events and documents for the target year
    - Uses LLM to generate insights and recommendations
    - Creates a formatted Google Doc
    """
    # Validate access level (handover typically requires executive access)
    if request.user_level > 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Handover generation requires level 1 or 2 access",
        )
    
    # TODO: Queue Celery task
    # from app.tasks.features import generate_handover as generate_handover_task
    # task = generate_handover_task.delay(
    #     target_year=request.target_year,
    #     department=request.department,
    #     output_config=request.output_config.model_dump(),
    #     content_options=request.content_options.model_dump(),
    #     source_filters=request.source_filters.model_dump(),
    # )
    
    # Placeholder task ID
    task_id = f"handover-{request.target_year}-placeholder"
    
    return HandoverGenerateResponse(
        task_id=task_id,
        status="PENDING",
        message=f"Handover generation for {request.target_year} queued successfully",
        estimated_time_minutes=5,
    )
