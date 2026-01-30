"""RAG (Retrieval-Augmented Generation) API endpoints."""

import uuid
import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import ApiKey, DbSession
from app.models.document import Document, DocumentStatus
from app.schemas.rag import (
    DocumentListResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.google.drive import GoogleDriveService

logger = structlog.get_logger()
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
    task_id = str(uuid.uuid4())

    try:
        # 1. List files in folder using Google Drive API
        drive_service = GoogleDriveService()
        files = drive_service.list_files_in_folder(
            folder_id=request.folder_id,
            recursive=request.recursive,
            supported_only=True,
        )

        logger.info("Files found in folder", folder_id=request.folder_id, count=len(files))

        # 2. Get existing drive_ids to avoid duplicates
        existing_ids_result = await db.execute(
            select(Document.drive_id)
        )
        existing_drive_ids = set(row[0] for row in existing_ids_result.fetchall())

        # 3. Insert new documents with PENDING status
        new_documents = []
        skipped_count = 0

        for file in files:
            drive_id = file["id"]

            # Skip if already exists
            if drive_id in existing_drive_ids:
                skipped_count += 1
                continue

            doc = Document(
                drive_id=drive_id,
                drive_name=file["name"],
                mime_type=file.get("mimeType"),
                doc_type=file["doc_type"],
                status=DocumentStatus.PENDING,
                doc_metadata={
                    "modified_time": file.get("modifiedTime"),
                    "size": file.get("size"),
                },
            )
            new_documents.append(doc)
            db.add(doc)

        await db.commit()

        logger.info(
            "Documents ingested",
            task_id=task_id,
            new_count=len(new_documents),
            skipped_count=skipped_count,
        )

        return IngestResponse(
            task_id=task_id,
            message=f"Ingestion complete. {len(new_documents)} new, {skipped_count} skipped (duplicates).",
            documents_found=len(files),
        )

    except Exception as e:
        logger.error("Ingestion failed", error=str(e), folder_id=request.folder_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest documents: {str(e)}",
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
    from sqlalchemy import func
    from app.schemas.rag import DocumentInfo

    # Get total count
    total_result = await db.execute(select(func.count(Document.id)))
    total = total_result.scalar() or 0

    # Get documents with pagination
    result = await db.execute(
        select(Document)
        .order_by(Document.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    documents = result.scalars().all()

    # Convert to response format
    doc_list = [
        DocumentInfo(
            id=doc.id,
            drive_id=doc.drive_id,
            name=doc.drive_name,
            doc_type=doc.doc_type.value,
            status=doc.status.value,
            chunk_count=len(doc.chunks) if doc.chunks else 0,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
        for doc in documents
    ]

    return DocumentListResponse(
        total=total,
        documents=doc_list,
        skip=skip,
        limit=limit,
    )
