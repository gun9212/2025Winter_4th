"""RAG (Retrieval-Augmented Generation) API endpoints."""

import uuid
import structlog
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
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
from app.core.config import settings
from app.services.google.drive import GoogleDriveService

logger = structlog.get_logger()
router = APIRouter()


class RcloneSyncRequest(BaseModel):
    """Request schema for rclone-based sync."""
    folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID (uses env default if not provided)",
    )
    skip_sync: bool = Field(
        default=False,
        description="Skip rclone sync and only scan/register local files",
    )


class RcloneSyncResponse(BaseModel):
    """Response schema for rclone-based sync."""
    task_id: str
    success: bool
    message: str
    files_scanned: int
    files_new: int
    files_skipped: int


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

    # Use provided folder_id or fall back to env default
    folder_id = request.folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not folder_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder_id is required (either in request or GOOGLE_DRIVE_FOLDER_ID env)",
        )

    try:
        # 1. List files in folder using Google Drive API
        drive_service = GoogleDriveService()
        files = drive_service.list_files_in_folder(
            folder_id=folder_id,
            recursive=request.recursive,
            supported_only=True,
        )

        logger.info("Files found in folder", folder_id=folder_id, count=len(files))

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
        logger.error("Ingestion failed", error=str(e), folder_id=folder_id)
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
    from sqlalchemy.orm import selectinload
    from app.schemas.rag import DocumentInfo

    # Get total count
    total_result = await db.execute(select(func.count(Document.id)))
    total = total_result.scalar() or 0

    # Get documents with pagination (eager load chunks)
    result = await db.execute(
        select(Document)
        .options(selectinload(Document.chunks))
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


@router.post(
    "/sync",
    response_model=RcloneSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync documents via rclone",
    description="Sync documents from Google Drive using rclone and register to database.",
)
async def sync_documents_rclone(
    request: RcloneSyncRequest,
    db: DbSession,
    api_key: ApiKey,
) -> RcloneSyncResponse:
    """
    Sync documents from Google Drive using rclone.

    This endpoint uses rclone to sync files from Google Drive to local storage,
    then scans and registers the files to the database.

    - **folder_id**: Google Drive folder ID to sync
    - **skip_sync**: If true, skip rclone sync and only scan existing local files
    """
    from app.services.ingestion import IngestionService

    task_id = str(uuid.uuid4())

    try:
        # Initialize ingestion service with appropriate paths
        ingestion = IngestionService(
            sync_script_path="/app/scripts/sync_drive.sh",
            data_path="/app/data/raw",
            log_path="/app/logs",
        )

        # Run full ingestion pipeline
        result = await ingestion.full_ingestion(
            db=db,
            folder_id=request.folder_id,
            skip_sync=request.skip_sync,
        )

        register_info = result.get("register", {})

        return RcloneSyncResponse(
            task_id=task_id,
            success=True,
            message="Sync and registration completed successfully",
            files_scanned=register_info.get("total", 0),
            files_new=register_info.get("new", 0),
            files_skipped=register_info.get("skipped", 0),
        )

    except Exception as e:
        logger.error("Rclone sync failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {str(e)}",
        )


@router.post(
    "/scan-local",
    response_model=RcloneSyncResponse,
    summary="Scan local files only",
    description="Scan already synced local files and register to database (no rclone sync).",
)
async def scan_local_files(
    db: DbSession,
    api_key: ApiKey,
) -> RcloneSyncResponse:
    """
    Scan local files without running rclone sync.

    Useful when files are already synced via cron job or manual rclone command.
    """
    from app.services.ingestion import IngestionService

    task_id = str(uuid.uuid4())

    try:
        ingestion = IngestionService(
            data_path="/app/data/raw",
        )

        # Scan and register only
        files = ingestion.scan_local_files()
        register_result = await ingestion.register_files_to_db(db, files)

        return RcloneSyncResponse(
            task_id=task_id,
            success=True,
            message="Local file scan and registration completed",
            files_scanned=register_result.get("total", 0),
            files_new=register_result.get("new", 0),
            files_skipped=register_result.get("skipped", 0),
        )

    except Exception as e:
        logger.error("Local scan failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scan failed: {str(e)}",
        )
