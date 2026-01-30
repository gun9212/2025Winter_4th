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


class GoogleFormsResponse(BaseModel):
    """Response schema for Google Forms collection."""
    task_id: str
    success: bool
    message: str
    forms_found: int
    forms_new: int
    forms_skipped: int


@router.post(
    "/collect-forms",
    response_model=GoogleFormsResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Collect Google Forms links",
    description="Collect Google Forms from Drive folder and store their URLs (no download).",
)
async def collect_google_forms(
    db: DbSession,
    api_key: ApiKey,
    folder_id: str | None = None,
) -> GoogleFormsResponse:
    """
    Collect Google Forms links from a Google Drive folder.

    Google Forms cannot be downloaded, so this endpoint only collects
    their webViewLink URLs and stores them in the database.

    - **folder_id**: Google Drive folder ID (uses env default if not provided)
    """
    from app.services.ingestion import IngestionService

    task_id = str(uuid.uuid4())

    # Use provided folder_id or fall back to env default
    target_folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
    if not target_folder_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder_id is required (either in request or GOOGLE_DRIVE_FOLDER_ID env)",
        )

    try:
        # 1. List Google Forms using Google Drive API
        drive_service = GoogleDriveService()
        forms = drive_service.list_google_forms(
            folder_id=target_folder_id,
            recursive=True,
        )

        logger.info(
            "Google Forms found in folder",
            folder_id=target_folder_id,
            count=len(forms),
        )

        # 2. Register forms to database
        ingestion = IngestionService()
        register_result = await ingestion.register_google_forms_to_db(db, forms)

        return GoogleFormsResponse(
            task_id=task_id,
            success=True,
            message=f"Google Forms collection complete. {register_result['new']} new, {register_result['skipped']} skipped.",
            forms_found=len(forms),
            forms_new=register_result.get("new", 0),
            forms_skipped=register_result.get("skipped", 0),
        )

    except Exception as e:
        logger.error("Google Forms collection failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to collect Google Forms: {str(e)}",
        )


class HybridIngestionRequest(BaseModel):
    """Request schema for hybrid ingestion."""
    folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID (uses env default if not provided)",
    )
    skip_sync: bool = Field(
        default=False,
        description="Skip rclone sync step",
    )
    parse_documents: bool = Field(
        default=True,
        description="Parse documents with Upstage after registration",
    )
    parse_limit: int = Field(
        default=50,
        description="Maximum number of documents to parse",
    )


class HybridIngestionResponse(BaseModel):
    """Response schema for hybrid ingestion."""
    task_id: str
    success: bool
    folder_id: str | None
    sync: dict | None = None
    forms: dict | None = None
    files: dict | None = None
    parsing: dict | None = None
    error: str | None = None


@router.post(
    "/hybrid-ingest",
    response_model=HybridIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run hybrid ingestion pipeline",
    description="Full pipeline: rclone sync + Google Forms API + Upstage parsing.",
)
async def hybrid_ingestion(
    request: HybridIngestionRequest,
    db: DbSession,
    api_key: ApiKey,
) -> HybridIngestionResponse:
    """
    Run full hybrid ingestion pipeline.

    1. **rclone sync**: Download files from Google Drive (docx, xlsx, pdf, etc.)
    2. **Google Forms API**: Collect URLs for Google Forms (no download)
    3. **Local scan**: Register all files to database
    4. **Upstage parsing**: Convert documents to Markdown

    - **folder_id**: Google Drive folder ID
    - **skip_sync**: Skip rclone sync (use existing local files)
    - **parse_documents**: Whether to parse with Upstage
    - **parse_limit**: Max documents to parse in this request
    """
    from app.services.ingestion import IngestionService

    task_id = str(uuid.uuid4())

    try:
        ingestion = IngestionService(
            data_path="/app/data/raw",
            processed_path="/app/data/processed",
            log_path="/app/logs",
        )

        result = await ingestion.hybrid_ingestion(
            db=db,
            folder_id=request.folder_id,
            skip_sync=request.skip_sync,
            parse_documents=request.parse_documents,
            parse_limit=request.parse_limit,
        )

        return HybridIngestionResponse(
            task_id=task_id,
            success=result.get("success", False),
            folder_id=result.get("folder_id"),
            sync=result.get("sync"),
            forms=result.get("forms"),
            files=result.get("files"),
            parsing=result.get("parsing"),
        )

    except Exception as e:
        logger.error("Hybrid ingestion failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hybrid ingestion failed: {str(e)}",
        )


class ParseDocumentsRequest(BaseModel):
    """Request schema for document parsing."""
    limit: int = Field(
        default=50,
        description="Maximum number of documents to parse",
    )


class ParseDocumentsResponse(BaseModel):
    """Response schema for document parsing."""
    task_id: str
    success: bool
    total: int
    parsed: int
    failed: int
    details: dict | None = None


@router.post(
    "/parse",
    response_model=ParseDocumentsResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Parse pending documents",
    description="Parse pending documents using Upstage Document Parser.",
)
async def parse_documents(
    request: ParseDocumentsRequest,
    db: DbSession,
    api_key: ApiKey,
) -> ParseDocumentsResponse:
    """
    Parse pending documents using Upstage Document Parser.

    Processes documents with status='pending' and converts them to Markdown.
    Parsed content is saved to data/processed and stored in DB.

    - **limit**: Maximum number of documents to parse
    """
    from app.services.ingestion import IngestionService

    task_id = str(uuid.uuid4())

    try:
        ingestion = IngestionService(
            data_path="/app/data/raw",
            processed_path="/app/data/processed",
        )

        result = await ingestion.parse_pending_documents(db, limit=request.limit)

        return ParseDocumentsResponse(
            task_id=task_id,
            success=True,
            total=result.get("total", 0),
            parsed=len(result.get("success", [])),
            failed=len(result.get("failed", [])),
            details={
                "success": result.get("success", []),
                "failed": result.get("failed", []),
            },
        )

    except Exception as e:
        logger.error("Document parsing failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Parsing failed: {str(e)}",
        )
