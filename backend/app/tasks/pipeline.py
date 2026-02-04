"""Celery tasks for RAG data pipeline execution.

This module defines Celery tasks that orchestrate the 7-step
RAG data pipeline for processing student council documents.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from celery import shared_task
import structlog
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.models.document import Document, DocumentStatus

logger = structlog.get_logger()

# Flag to track if nest_asyncio has been applied (for Celery worker only)
_nest_asyncio_applied = False


def run_async(coro):
    """Helper to run async code in sync Celery context.
    
    Uses nest_asyncio to allow nested event loops, preventing
    'Event loop is closed' errors with Gemini SDK.
    """
    global _nest_asyncio_applied
    
    # Apply nest_asyncio only once, only in Celery context
    if not _nest_asyncio_applied:
        try:
            import nest_asyncio
            nest_asyncio.apply()
            _nest_asyncio_applied = True
        except ValueError:
            # uvloop doesn't support nesting - skip (FastAPI context)
            pass
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)



@asynccontextmanager
async def get_celery_session():
    """
    Create a fresh database session for Celery tasks.
    
    Each Celery task gets its own engine and session to avoid
    event loop conflicts with the main FastAPI application.
    """
    # Create a new engine for this task
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
    
    await engine.dispose()



@shared_task(bind=True, name="app.tasks.pipeline.run_full_pipeline")
def run_full_pipeline(
    self,
    file_path: str,
    filename: str,
    drive_id: str,
    folder_path: str = "",
) -> dict[str, Any]:
    """
    Run the complete 7-step RAG pipeline for a single document.
    
    Per Ground Truth: Event mapping is NOT determined at pipeline invocation.
    During Step 6 (Enrichment), the LLM analyzes chunk content and infers
    the associated Event at the chunk (agenda item) level.
    
    Args:
        file_path: Local path to the file
        filename: Original filename
        drive_id: Google Drive file ID
        folder_path: Full folder path for classification context
        
    Returns:
        Task result with processing status
    """
    async def _process():
        from app.pipeline.step_02_classify import ClassificationService
        from app.pipeline.step_03_parse import ParsingService
        from app.pipeline.step_04_preprocess import PreprocessingService
        from app.pipeline.step_05_chunk import ChunkingService
        from app.pipeline.step_06_enrich import MetadataEnrichmentService
        from app.pipeline.step_07_embed import EmbeddingService
        from app.models.document import DocumentCategory
        
        async with get_celery_session() as db:
            try:
                # Check if document already exists
                # Normalize drive_id by removing 'local:' prefix for comparison
                normalized_id = drive_id.removeprefix("local:")
                existing_doc = await db.execute(
                    select(Document).where(
                        or_(
                            Document.drive_id == drive_id,
                            Document.drive_id == normalized_id,
                            Document.drive_id == f"local:{normalized_id}",
                        )
                    )
                )
                existing = existing_doc.scalar_one_or_none()

                if existing:
                    # If already COMPLETED, skip processing
                    if existing.status == DocumentStatus.COMPLETED:
                        logger.info("Document already completed, skipping", drive_id=drive_id)
                        return {
                            "status": "skipped",
                            "reason": "Document already completed",
                            "document_id": existing.id,
                        }
                    # If FAILED, also skip (needs manual reprocessing)
                    elif existing.status == DocumentStatus.FAILED:
                        logger.info("Document previously failed, skipping", drive_id=drive_id)
                        return {
                            "status": "skipped",
                            "reason": "Document previously failed - use reprocess endpoint",
                            "document_id": existing.id,
                        }
                    # If PENDING or in-progress, continue processing (reuse existing record)
                    else:
                        logger.info(
                            "Continuing processing of existing document",
                            drive_id=drive_id,
                            current_status=existing.status.value,
                        )

                # Step 2: Classification
                classifier = ClassificationService()
                classification = await classifier.classify_document(
                    filename=filename,
                    folder_path=folder_path,
                )

                # Create or update document record
                if existing:
                    # Reuse existing PENDING document
                    document = existing
                    document.drive_name = filename
                    document.drive_path = folder_path
                    document.doc_type = classification.doc_type
                    document.doc_category = classification.doc_category
                    document.meeting_subtype = classification.meeting_subtype
                    document.standardized_name = classification.standardized_name
                    document.year = classification.year
                    document.status = DocumentStatus.PARSING
                    logger.info("Updated existing document", document_id=document.id)
                else:
                    # Create new document
                    document = Document(
                        drive_id=drive_id,
                        drive_name=filename,
                        drive_path=folder_path,
                        doc_type=classification.doc_type,
                        doc_category=classification.doc_category,
                        meeting_subtype=classification.meeting_subtype,
                        standardized_name=classification.standardized_name,
                        year=classification.year,
                        status=DocumentStatus.PARSING,
                    )
                    db.add(document)
                await db.flush()
                
                # Step 3: Parsing
                parser = ParsingService()
                with open(file_path, "rb") as f:
                    file_content = f.read()
                
                parse_result = await parser.parse_document(
                    file_content=file_content,
                    filename=filename,
                    caption_images=True,
                )
                
                document.parsed_content = parse_result.html_content
                document.status = DocumentStatus.PREPROCESSING
                await db.flush()
                
                # Step 4: Preprocessing
                # BUGFIX: Use markdown_content (with image captions) instead of html_content
                # markdown_content contains Gemini-generated captions injected in Step 3
                preprocessor = PreprocessingService()
                is_meeting = classification.doc_category == DocumentCategory.MEETING_DOCUMENT
                
                preprocess_result = await preprocessor.preprocess_document(
                    content=parse_result.markdown_content,
                    is_meeting_document=is_meeting,
                )
                
                document.preprocessed_content = preprocess_result.processed_content
                document.status = DocumentStatus.CHUNKING
                await db.flush()
                
                # Step 5: Chunking
                chunker = ChunkingService()
                chunks = chunker.chunk_document(
                    content=preprocess_result.processed_content,
                    document_metadata={"document_id": document.id},
                )
                
                document.status = DocumentStatus.EMBEDDING
                await db.flush()
                
                # Step 6: Metadata Enrichment
                # Note: event_hints removed per Ground Truth - Event mapping
                # is determined at chunk level during enrichment, not at invocation
                enricher = MetadataEnrichmentService(db)
                await enricher.enrich_document(
                    document=document,
                    classification_result={
                        "department": classification.department,
                        "event_name": classification.event_name,
                        "year": classification.year,
                    },
                )
                
                db_chunks = await enricher.enrich_chunks(document, chunks)
                
                # Step 7: Embedding
                embedder = EmbeddingService(db)
                embed_result = await embedder.embed_chunks(db_chunks)
                
                document.status = DocumentStatus.COMPLETED
                await db.commit()
                
                return {
                    "status": "success",
                    "document_id": document.id,
                    "chunks_created": len(db_chunks),
                    "chunks_embedded": embed_result.chunks_embedded,
                    "classification": {
                        "category": classification.doc_category.value,
                        "subtype": classification.meeting_subtype.value if classification.meeting_subtype else None,
                        "standardized_name": classification.standardized_name,
                    },
                }
                
            except Exception as e:
                logger.exception("Pipeline failed", error=str(e))
                if 'document' in locals():
                    document.status = DocumentStatus.FAILED
                    document.error_message = str(e)
                    await db.commit()
                raise

    try:
        return run_async(_process())
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "file_path": file_path,
        }


@shared_task(bind=True, name="app.tasks.pipeline.ingest_folder")
def ingest_folder(
    self,
    drive_folder_id: str,
    options: dict | None = None,
) -> dict[str, Any]:
    """
    Ingest all documents from a Google Drive folder.

    Per Ground Truth: event_id is NOT provided at ingestion time.
    Event mapping happens at chunk level during enrichment step.

    This task uses the integrated Step 1 pipeline which:
    1. Syncs files from Google Drive using rclone
    2. Collects Google Forms URLs via Drive API
    3. Registers all files to the database

    Args:
        drive_folder_id: Google Drive folder ID
        options: Ingestion options dict with:
            - is_privacy_sensitive: Store as reference only (no embedding)
            - recursive: Process subfolders (default: True)
            - file_types: Filter by file type (default: all)
            - exclude_patterns: Glob patterns to skip
            - skip_sync: Skip rclone sync step (default: False)

    Returns:
        Task result with ingestion statistics
    """
    options = options or {}
    is_privacy_sensitive = options.get("is_privacy_sensitive", False)
    skip_sync = options.get("skip_sync", False)

    async def _ingest():
        from app.pipeline.step_01_ingest import IngestionService

        ingester = IngestionService()

        async with get_celery_session() as db:
            # Use the integrated run_step1 method for full Step 1 pipeline
            step1_result = await ingester.run_step1(
                db=db,
                folder_id=drive_folder_id,
                skip_sync=skip_sync,
            )

            # Get list of synced files for triggering subsequent pipelines
            files = await ingester.list_synced_files()

            return {
                "step1_result": step1_result,
                "files": files,
            }

    try:
        result = run_async(_ingest())
        step1 = result["step1_result"]

        # Extract counts from step1 result
        files_synced = step1.get("sync", {}).get("files_synced", 0) if isinstance(step1.get("sync"), dict) else 0
        forms_new = step1.get("forms", {}).get("new", 0) if isinstance(step1.get("forms"), dict) else 0
        files_new = step1.get("files", {}).get("new", 0) if isinstance(step1.get("files"), dict) else 0

        if is_privacy_sensitive:
            # Store as reference only, skip embedding
            logger.info(
                "Privacy sensitive folder - storing as references only",
                folder_id=drive_folder_id,
                files_registered=files_new,
            )

            return {
                "status": "success",
                "folder_id": drive_folder_id,
                "files_synced": files_synced,
                "files_registered": files_new,
                "forms_registered": forms_new,
                "is_privacy_sensitive": True,
            }

        # Normal processing - trigger pipeline for each file
        processed = 0
        for file_info in result["files"]:
            # Note: event_hints removed per Ground Truth
            # Event is determined at chunk level during enrichment
            # IMPORTANT: Use relative_path for drive_id to match register_files_to_db()
            relative_path = file_info.get("relative_path", file_info["path"])
            run_full_pipeline.delay(
                file_path=file_info["path"],  # Absolute path for file reading
                filename=file_info["name"],
                drive_id=file_info.get("drive_id") or f"local:{relative_path}",
                folder_path=file_info.get("full_folder_path", ""),
            )
            processed += 1

        return {
            "status": "success",
            "folder_id": drive_folder_id,
            "files_synced": files_synced,
            "files_registered": files_new,
            "forms_registered": forms_new,
            "pipelines_triggered": processed,
        }

    except Exception as e:
        logger.exception("Folder ingestion failed", error=str(e))
        return {
            "status": "error",
            "folder_id": drive_folder_id,
            "error": str(e),
        }


@shared_task(bind=True, name="app.tasks.pipeline.reprocess_document")
def reprocess_document(
    self,
    document_id: int,
    from_step: int = 3,
) -> dict[str, Any]:
    """
    Reprocess an existing document from a specific step.
    
    Args:
        document_id: Database document ID
        from_step: Step to start from (2=classify, 3=parse, 4=preprocess, 5=chunk)
        
    Returns:
        Task result
    """
    async def _reprocess():
        from pathlib import Path
        from sqlalchemy import select, delete
        from app.pipeline.step_03_parse import ParsingService
        from app.pipeline.step_04_preprocess import PreprocessingService
        from app.pipeline.step_05_chunk import ChunkingService
        from app.pipeline.step_06_enrich import MetadataEnrichmentService
        from app.pipeline.step_07_embed import EmbeddingService
        from app.models.document import DocumentCategory
        from app.models.embedding import DocumentChunk
        
        async with get_celery_session() as db:
            result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            
            if not document:
                return {"status": "error", "error": "Document not found"}
            
            logger.info(
                "Starting document reprocess",
                document_id=document_id,
                from_step=from_step,
                drive_name=document.drive_name,
            )
            
            # Delete existing chunks using SQLAlchemy ORM
            if from_step <= 5:
                await db.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                await db.flush()
                logger.info("Deleted existing chunks", document_id=document_id)
            
            try:
                # Find file on disk
                file_path = None
                base_path = Path("/app/data/raw")
                
                if document.drive_path:
                    potential_path = base_path / document.drive_path / document.drive_name
                    if potential_path.exists():
                        file_path = str(potential_path)
                
                if not file_path:
                    potential_path = base_path / document.drive_name
                    if potential_path.exists():
                        file_path = str(potential_path)
                
                if not file_path or not Path(file_path).exists():
                    return {
                        "status": "error",
                        "document_id": document_id,
                        "error": f"File not found: {document.drive_name}",
                    }
                
                # Step 3: Parsing
                if from_step <= 3:
                    logger.info("Step 3: Parsing", document_id=document_id)
                    parser = ParsingService()
                    with open(file_path, "rb") as f:
                        file_content = f.read()
                    
                    parse_result = await parser.parse_document(
                        file_content=file_content,
                        filename=document.drive_name,
                        caption_images=True,
                    )
                    
                    document.parsed_content = parse_result.markdown_content
                    document.status = DocumentStatus.PREPROCESSING
                    await db.flush()
                    logger.info(
                        "Parsing complete",
                        document_id=document_id,
                        parsed_length=len(parse_result.markdown_content),
                    )
                
                # Step 4: Preprocessing
                if from_step <= 4:
                    logger.info("Step 4: Preprocessing", document_id=document_id)
                    preprocessor = PreprocessingService()
                    is_meeting = document.doc_category == DocumentCategory.MEETING_DOCUMENT
                    
                    preprocess_result = await preprocessor.preprocess_document(
                        content=document.parsed_content or "",
                        is_meeting_document=is_meeting,
                    )
                    
                    document.preprocessed_content = preprocess_result.processed_content
                    document.status = DocumentStatus.CHUNKING
                    await db.flush()
                    logger.info(
                        "Preprocessing complete",
                        document_id=document_id,
                        preprocessed_length=len(preprocess_result.processed_content),
                    )
                
                # Step 5: Chunking
                if from_step <= 5:
                    logger.info("Step 5: Chunking", document_id=document_id)
                    chunker = ChunkingService()
                    chunks = chunker.chunk_document(
                        content=document.preprocessed_content or "",
                        document_metadata={"document_id": document.id},
                    )
                    
                    document.status = DocumentStatus.EMBEDDING
                    await db.flush()
                
                    # Step 6: Enrichment
                    logger.info("Step 6: Enrichment", document_id=document_id)
                    enricher = MetadataEnrichmentService(db)
                    await enricher.enrich_document(
                        document=document,
                        classification_result={
                            "department": document.department,
                            "year": document.year,
                        },
                    )
                    # Enrich chunks separately
                    db_chunks = await enricher.enrich_chunks(
                        document=document,
                        chunks=chunks,
                    )
                    await db.flush()
                    logger.info("Enrichment complete", document_id=document_id, chunks_enriched=len(db_chunks))
                
                    # Step 7: Embedding
                    logger.info("Step 7: Embedding", document_id=document_id)
                    embedder = EmbeddingService(db)
                    await embedder.embed_chunks(document.id)
                
                document.status = DocumentStatus.COMPLETED
                await db.commit()
                
                logger.info("Reprocess completed", document_id=document_id)
                
                return {
                    "status": "success",
                    "document_id": document_id,
                    "reprocessed_from_step": from_step,
                    "parsed_length": len(document.parsed_content or ""),
                    "preprocessed_length": len(document.preprocessed_content or ""),
                }
                
            except Exception as e:
                document.status = DocumentStatus.FAILED
                document.error_message = str(e)
                await db.commit()
                raise

    try:
        return run_async(_reprocess())
    except Exception as e:
        logger.exception("Reprocess failed", document_id=document_id, error=str(e))
        return {
            "status": "error",
            "document_id": document_id,
            "error": str(e),
        }


@shared_task(bind=True, name="app.tasks.pipeline.create_hnsw_index")
def create_hnsw_index(self) -> dict[str, Any]:
    """
    Create HNSW index for vector search optimization.
    
    Should be run after initial data load.
    """
    async def _create_index():
        from app.pipeline.step_07_embed import EmbeddingService
        
        async with get_celery_session() as db:
            embedder = EmbeddingService(db)
            status = await embedder.ensure_hnsw_index()
            return {"status": "success", "index_status": status}

    try:
        return run_async(_create_index())
    except Exception as e:
        return {"status": "error", "error": str(e)}
