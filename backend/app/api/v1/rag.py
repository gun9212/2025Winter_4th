"""RAG (Retrieval-Augmented Generation) API endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiKey, DbSession
from app.schemas.rag import (
    DocumentListResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)

router = APIRouter()


@router.post(
    "/ingest/folder",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest folder",
    description="""
    Ingest documents from a Google Drive folder for RAG indexing.
    
    **Important Notes:**
    - `event_id` is NOT required per Ground Truth
    - Event mapping happens at chunk level during enrichment step
    - LLM analyzes content and infers Event for each chunk (agenda item)
    
    **Options:**
    - `is_privacy_sensitive`: Store as reference only (no embedding)
    - `recursive`: Process subfolders
    - `file_types`: Filter by file type
    - `exclude_patterns`: Glob patterns to skip
    
    **Processing (Async via Celery):**
    1. List files in folder via Drive API
    2. Download/convert to processable format
    3. Parse with Upstage Document Parser
    4. Apply Parent-Child chunking
    5. Enrich with metadata (LLM infers Event per chunk)
    6. Embed with Vertex AI text-embedding-004
    7. Store in PostgreSQL with pgvector
    """,
)
async def ingest_folder(
    request: IngestRequest,
    db: DbSession,
    api_key: ApiKey,
) -> IngestResponse:
    """
    Ingest documents from a Google Drive folder.
    
    Triggers async Celery task for the 7-step RAG pipeline.
    Event mapping is determined at chunk level, not at ingestion request.
    """
    # TODO: Queue Celery task
    # from app.tasks.pipeline import ingest_folder as ingest_folder_task
    # task = ingest_folder_task.delay(
    #     folder_id=request.folder_id,
    #     options=request.options.model_dump(),
    # )
    
    task_id = f"ingest-{request.folder_id[:8]}-placeholder"

    return IngestResponse(
        task_id=task_id,
        message="Document ingestion started. Event mapping will be determined at chunk level.",
        documents_found=0,
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search documents",
    description="""
    Search indexed documents using hybrid vector search.
    
    **For multi-turn conversations, use `/api/v1/chat` instead.**
    This endpoint is for direct search without conversation context.
    
    **Search Strategy:**
    1. Embed query with Vertex AI
    2. Vector similarity search on child chunks
    3. Apply time decay weighting
    4. Filter by access_level
    5. Return parent content for context
    """,
)
async def search_documents(
    request: SearchRequest,
    db: DbSession,
    api_key: ApiKey,
) -> SearchResponse:
    """
    Search indexed documents using RAG.
    
    For conversational search with context, use /chat endpoint.
    """
    # TODO: Implement RAG search
    # 1. Embed query
    # 2. Vector similarity search with pgvector
    # 3. Apply hybrid scoring (semantic + time decay)
    # 4. Filter by access_level
    # 5. Generate LLM response with parent context

    return SearchResponse(
        query=request.query,
        results=[],
        answer=None,
        sources=[],
    )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List indexed documents",
    description="Get a paginated list of all indexed documents.",
)
async def list_documents(
    db: DbSession,
    api_key: ApiKey,
    skip: int = 0,
    limit: int = 20,
) -> DocumentListResponse:
    """
    List all indexed documents.
    
    Returns document metadata without chunk details.
    """
    # TODO: Query database for document list with chunk count

    return DocumentListResponse(
        total=0,
        documents=[],
        skip=skip,
        limit=limit,
    )

