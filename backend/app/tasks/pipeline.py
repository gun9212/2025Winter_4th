"""Celery tasks for RAG data pipeline execution.

This module defines Celery tasks that orchestrate the 7-step
RAG data pipeline for processing student council documents.
"""

import asyncio
from typing import Any

from celery import shared_task
import structlog

from app.core.database import async_session_factory
from app.models.document import Document, DocumentStatus

logger = structlog.get_logger()


def run_async(coro):
    """Helper to run async code in sync Celery context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
        
        async with async_session_factory() as db:
            try:
                # Step 2: Classification
                classifier = ClassificationService()
                classification = await classifier.classify_document(
                    filename=filename,
                    folder_path=folder_path,
                )
                
                # Create document record
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
                preprocessor = PreprocessingService()
                is_meeting = classification.doc_category == DocumentCategory.MEETING_DOCUMENT
                
                preprocess_result = await preprocessor.preprocess_document(
                    content=parse_result.html_content,
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
                enricher = MetadataEnrichmentService(db)
                await enricher.enrich_document(
                    document=document,
                    classification_result={
                        "department": classification.department,
                        "event_name": classification.event_name,
                        "year": classification.year,
                    },
                    event_hints=event_hints,
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

        async with async_session_factory() as db:
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
            run_full_pipeline.delay(
                file_path=file_info["path"],
                filename=file_info["name"],
                drive_id=file_info.get("drive_id", file_info["name"]),
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
    from_step: int = 2,
) -> dict[str, Any]:
    """
    Reprocess an existing document from a specific step.
    
    Args:
        document_id: Database document ID
        from_step: Step to start from (2-7)
        
    Returns:
        Task result
    """
    async def _reprocess():
        from sqlalchemy import select
        
        async with async_session_factory() as db:
            result = await db.execute(
                select(Document).where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()
            
            if not document:
                return {"status": "error", "error": "Document not found"}
            
            # Delete existing chunks if reprocessing from chunking or earlier
            if from_step <= 5:
                await db.execute(
                    f"DELETE FROM document_chunks WHERE document_id = {document_id}"
                )
            
            # Re-run pipeline from specified step
            # (Implementation similar to run_full_pipeline but with step skipping)
            
            return {
                "status": "success",
                "document_id": document_id,
                "reprocessed_from_step": from_step,
            }

    try:
        return run_async(_reprocess())
    except Exception as e:
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
        
        async with async_session_factory() as db:
            embedder = EmbeddingService(db)
            status = await embedder.ensure_hnsw_index()
            return {"status": "success", "index_status": status}

    try:
        return run_async(_create_index())
    except Exception as e:
        return {"status": "error", "error": str(e)}
