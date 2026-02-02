#!/usr/bin/env python3
"""Pipeline Runner - Execute data processing pipeline steps.

Usage:
    python -m scripts.pipeline_runner --step all
    python -m scripts.pipeline_runner --step ingest
    python -m scripts.pipeline_runner --step classify
    python -m scripts.pipeline_runner --step parse
    python -m scripts.pipeline_runner --step preprocess
    python -m scripts.pipeline_runner --step chunk
    python -m scripts.pipeline_runner --step enrich
    python -m scripts.pipeline_runner --step embed
    python -m scripts.pipeline_runner --step stats
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import structlog

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory as AsyncSessionLocal
from app.models.document import Document, DocumentStatus, DocumentCategory
from app.models.embedding import DocumentChunk
from app.pipeline.step_01_ingest import IngestionService
from app.pipeline.step_02_classify import ClassificationService
from app.pipeline.step_03_parse import ParsingService
from app.pipeline.step_04_preprocess import PreprocessingService
from app.pipeline.step_05_chunk import ChunkingService
from app.pipeline.step_06_enrich import MetadataEnrichmentService
from app.pipeline.step_07_embed import EmbeddingService

logger = structlog.get_logger()


async def run_step_ingest(db: AsyncSession) -> int:
    """Step 1: Ingest files from Google Drive and register to DB."""
    logger.info("Step 1: Starting ingestion...")

    # Initialize service (no db in __init__)
    service = IngestionService()

    # Get Drive folder ID from environment
    drive_folder_id = settings.GOOGLE_DRIVE_FOLDER_ID

    if drive_folder_id:
        # Sync from Google Drive
        logger.info("Syncing from Google Drive...", folder_id=drive_folder_id[:10])
        try:
            result = await service.sync_from_drive(drive_folder_id)
            logger.info(
                "Drive sync complete",
                files_synced=result.files_synced,
                files_failed=result.files_failed,
            )
        except Exception as e:
            logger.warning("Drive sync failed, using local files", error=str(e))
    else:
        logger.info("No GOOGLE_DRIVE_FOLDER_ID set, scanning local files only")

    # Register files to DB (this method takes db)
    result = await service.register_files_to_db(db)

    logger.info(
        "Step 1 Complete",
        new_files=result.get("new", 0),
        skipped=result.get("skipped", 0),
        total=result.get("total", 0),
    )
    return result.get("new", 0)


async def run_step_classify(db: AsyncSession) -> int:
    """Step 2: Classify documents."""
    logger.info("Step 2: Starting classification...")

    # Initialize service (no db in __init__)
    service = ClassificationService()

    # Get pending documents
    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PENDING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to classify")
        return 0

    classified = 0
    for doc in documents:
        try:
            # Classify using filename and path
            classification = await service.classify_document(
                filename=doc.drive_name,
                folder_path=doc.drive_path or "",
            )

            # Update document with classification results
            doc.doc_category = classification.get("category", DocumentCategory.OTHER_DOCUMENT)
            doc.meeting_subtype = classification.get("meeting_subtype")
            doc.standardized_name = classification.get("standardized_name")
            doc.year = classification.get("year")
            doc.department = classification.get("department")
            doc.status = DocumentStatus.CLASSIFYING

            classified += 1
            logger.debug("Document classified", doc_id=doc.id, category=doc.doc_category)

        except Exception as e:
            logger.error("Classification failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)

    await db.commit()
    logger.info("Step 2 Complete", classified=classified)
    return classified


async def run_step_parse(db: AsyncSession) -> int:
    """Step 3: Parse documents with Upstage."""
    logger.info("Step 3: Starting parsing...")

    # Initialize service (no db in __init__)
    service = ParsingService()

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.CLASSIFYING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to parse")
        return 0

    parsed = 0
    for doc in documents:
        try:
            # Read file content
            file_path = Path(settings.DATA_RAW_PATH) / doc.drive_name
            if not file_path.exists():
                # Try alternate paths
                file_path = Path("/app/data/source_documents") / doc.drive_name

            if not file_path.exists():
                logger.warning("File not found", doc_id=doc.id, path=str(file_path))
                continue

            with open(file_path, "rb") as f:
                file_content = f.read()

            # Parse document
            parsed_result = await service.parse_document(
                file_content=file_content,
                filename=doc.drive_name,
            )

            # Update document
            doc.parsed_content = parsed_result.get("content", "")
            doc.status = DocumentStatus.PARSING

            parsed += 1
            logger.debug("Document parsed", doc_id=doc.id)

        except Exception as e:
            logger.error("Parsing failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)

    await db.commit()
    logger.info("Step 3 Complete", parsed=parsed)
    return parsed


async def run_step_preprocess(db: AsyncSession) -> int:
    """Step 4: Preprocess parsed content."""
    logger.info("Step 4: Starting preprocessing...")

    # Initialize service (no db in __init__)
    service = PreprocessingService()

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PARSING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to preprocess")
        return 0

    processed = 0
    for doc in documents:
        try:
            if not doc.parsed_content:
                logger.warning("No parsed content", doc_id=doc.id)
                continue

            # Preprocess content
            is_meeting = doc.doc_category == DocumentCategory.MEETING_DOCUMENT
            preprocessed = await service.preprocess_document(
                content=doc.parsed_content,
                is_meeting_document=is_meeting,
            )

            # Update document
            doc.preprocessed_content = preprocessed.get("content", doc.parsed_content)
            doc.status = DocumentStatus.PREPROCESSING

            processed += 1
            logger.debug("Document preprocessed", doc_id=doc.id)

        except Exception as e:
            logger.error("Preprocessing failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)

    await db.commit()
    logger.info("Step 4 Complete", processed=processed)
    return processed


async def run_step_chunk(db: AsyncSession) -> int:
    """Step 5: Chunk documents."""
    logger.info("Step 5: Starting chunking...")

    # Initialize service (no db in __init__, uses default chunk sizes)
    service = ChunkingService()

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PREPROCESSING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to chunk")
        return 0

    total_chunks = 0
    for doc in documents:
        try:
            content = doc.preprocessed_content or doc.parsed_content
            if not content:
                logger.warning("No content to chunk", doc_id=doc.id)
                continue

            # Chunk document (sync method)
            metadata = {
                "document_id": doc.id,
                "category": doc.doc_category.value if doc.doc_category else None,
                "year": doc.year,
                "department": doc.department,
            }

            chunk_data_list = service.chunk_document(
                content=content,
                document_metadata=metadata,
            )

            # Create DocumentChunk records
            for chunk_data in chunk_data_list:
                chunk = DocumentChunk(
                    document_id=doc.id,
                    content=chunk_data.content,
                    parent_content=chunk_data.parent_content,
                    chunk_index=chunk_data.chunk_index,
                    is_parent=chunk_data.is_parent,
                    section_header=chunk_data.section_header,
                    chunk_type=chunk_data.chunk_type,
                    access_level=doc.access_level,
                    metadata=chunk_data.metadata,
                )
                db.add(chunk)
                total_chunks += 1

            doc.status = DocumentStatus.CHUNKING
            logger.debug("Document chunked", doc_id=doc.id, chunks=len(chunk_data_list))

        except Exception as e:
            logger.error("Chunking failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)

    await db.commit()
    logger.info("Step 5 Complete", total_chunks=total_chunks)
    return total_chunks


async def run_step_enrich(db: AsyncSession) -> int:
    """Step 6: Enrich metadata."""
    logger.info("Step 6: Starting metadata enrichment...")

    # Initialize service (takes db in __init__)
    service = MetadataEnrichmentService(db)

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.CHUNKING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to enrich")
        return 0

    enriched = 0
    for doc in documents:
        try:
            await service.enrich_document(doc)
            doc.status = DocumentStatus.EMBEDDING
            enriched += 1
            logger.debug("Document enriched", doc_id=doc.id)

        except Exception as e:
            logger.error("Enrichment failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)

    await db.commit()
    logger.info("Step 6 Complete", enriched=enriched)
    return enriched


async def run_step_embed(db: AsyncSession) -> int:
    """Step 7: Generate embeddings."""
    logger.info("Step 7: Starting embedding generation...")

    # Initialize service (takes db in __init__)
    service = EmbeddingService(db)

    # Ensure HNSW index exists
    await service.ensure_hnsw_index()

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.EMBEDDING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to embed")
        return 0

    total_embedded = 0
    for doc in documents:
        try:
            # Get chunks for this document
            chunk_result = await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
            )
            chunks = chunk_result.scalars().all()

            if chunks:
                embed_result = await service.embed_chunks(list(chunks))
                total_embedded += embed_result.chunks_embedded

            doc.status = DocumentStatus.COMPLETED
            logger.debug("Document embedded", doc_id=doc.id, chunks=len(chunks))

        except Exception as e:
            logger.error("Embedding failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)

    await db.commit()
    logger.info("Step 7 Complete", total_embedded=total_embedded)
    return total_embedded


async def run_all_steps(db: AsyncSession) -> dict:
    """Run all pipeline steps in sequence."""
    results = {}

    steps = [
        ("ingest", run_step_ingest),
        ("classify", run_step_classify),
        ("parse", run_step_parse),
        ("preprocess", run_step_preprocess),
        ("chunk", run_step_chunk),
        ("enrich", run_step_enrich),
        ("embed", run_step_embed),
    ]

    for step_name, step_func in steps:
        try:
            results[step_name] = await step_func(db)
        except Exception as e:
            logger.error(f"Step {step_name} failed", error=str(e))
            results[step_name] = -1
            break

    return results


async def get_pipeline_stats(db: AsyncSession) -> dict:
    """Get current pipeline statistics."""
    stats = {}

    # Count documents by status
    for status in DocumentStatus:
        result = await db.execute(
            select(Document).where(Document.status == status)
        )
        stats[status.value] = len(result.scalars().all())

    # Count total chunks
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM document_chunks"))
        stats["total_chunks"] = result.scalar() or 0
    except Exception:
        stats["total_chunks"] = 0

    # Count embedded chunks
    try:
        result = await db.execute(
            text("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
        )
        stats["embedded_chunks"] = result.scalar() or 0
    except Exception:
        stats["embedded_chunks"] = 0

    return stats


async def main():
    parser = argparse.ArgumentParser(description="Run pipeline steps")
    parser.add_argument(
        "--step",
        choices=["all", "ingest", "classify", "parse", "preprocess", "chunk", "enrich", "embed", "stats"],
        default="all",
        help="Which step to run (default: all)",
    )
    args = parser.parse_args()

    step_map = {
        "ingest": run_step_ingest,
        "classify": run_step_classify,
        "parse": run_step_parse,
        "preprocess": run_step_preprocess,
        "chunk": run_step_chunk,
        "enrich": run_step_enrich,
        "embed": run_step_embed,
    }

    async with AsyncSessionLocal() as db:
        if args.step == "all":
            results = await run_all_steps(db)
            logger.info("Pipeline Complete", results=results)
        elif args.step == "stats":
            stats = await get_pipeline_stats(db)
            logger.info("Pipeline Stats", **stats)
        else:
            step_func = step_map[args.step]
            result = await step_func(db)
            logger.info(f"Step {args.step} complete", result=result)


if __name__ == "__main__":
    asyncio.run(main())
