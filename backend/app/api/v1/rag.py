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
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest documents",
    description="Ingest documents from Google Drive for RAG indexing.",
)
async def ingest_documents(
    request: IngestRequest,
    db: DbSession,
    api_key: ApiKey,
) -> IngestResponse:
    """
    Ingest documents from a Google Drive folder.

    - **folder_id**: Google Drive folder ID to ingest
    - **recursive**: Whether to process subfolders
    - **file_types**: Optional list of file types to process
    """
    # TODO: Implement document ingestion pipeline
    # 1. List files in folder
    # 2. Download and convert to processable format
    # 3. Parse with Upstage Document Parser
    # 4. Extract images and generate captions
    # 5. Chunk and embed text
    # 6. Store in PostgreSQL with pgvector

    task_id = "ingest-task-placeholder"

    return IngestResponse(
        task_id=task_id,
        message="Document ingestion started",
        documents_found=0,
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search documents",
    description="Search indexed documents using semantic similarity.",
)
async def search_documents(
    request: SearchRequest,
    db: DbSession,
    api_key: ApiKey,
) -> SearchResponse:
    """
    Search indexed documents using RAG.

    - **query**: Search query text
    - **top_k**: Number of results to return (default: 5)
    - **include_context**: Whether to include surrounding context
    """
    # TODO: Implement RAG search
    # 1. Embed query
    # 2. Vector similarity search
    # 3. Apply business logic (e.g., partner info for 간식/회식 keywords)
    # 4. Generate LLM response with context

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
    description="Get a list of all indexed documents.",
)
async def list_documents(
    db: DbSession,
    api_key: ApiKey,
    skip: int = 0,
    limit: int = 20,
) -> DocumentListResponse:
    """
    List all indexed documents.

    - **skip**: Number of documents to skip
    - **limit**: Maximum number of documents to return
    """
    # TODO: Query database for document list

    return DocumentListResponse(
        total=0,
        documents=[],
        skip=skip,
        limit=limit,
    )
