#!/usr/bin/env python3
"""Pipeline Runner - Execute data processing pipeline steps with parallel processing.

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

# Semaphore for controlling concurrent document processing
MAX_CONCURRENT = 5


async def run_step_ingest(db: AsyncSession) -> int:
    """Step 1: Ingest files from Google Drive and register to DB."""
    logger.info("Step 1: Starting ingestion...")

    service = IngestionService()
    drive_folder_id = settings.GOOGLE_DRIVE_FOLDER_ID

    if drive_folder_id:
        logger.info("Syncing from Google Drive...", folder_id=drive_folder_id[:10] if drive_folder_id else "")
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

    result = await service.register_files_to_db(db)

    logger.info(
        "Step 1 Complete",
        new_files=result.get("new", 0),
        skipped=result.get("skipped", 0),
        total=result.get("total", 0),
    )
    return result.get("new", 0)


async def run_step_classify(db: AsyncSession) -> int:
    """Step 2: Classify documents with parallel processing."""
    logger.info("Step 2: Starting classification...")

    service = ClassificationService()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PENDING)
    )
    documents = list(result.scalars().all())

    if not documents:
        logger.info("No documents to classify")
        return 0

    async def classify_one(doc: Document) -> bool:
        async with semaphore:
            try:
                classification = await service.classify_document(
                    filename=doc.drive_name,
                    folder_path=doc.drive_path or "",
                )
                # ClassificationResult dataclass - use dot notation
                doc.doc_type = classification.doc_type
                doc.doc_category = classification.doc_category
                doc.meeting_subtype = classification.meeting_subtype
                doc.standardized_name = classification.standardized_name
                doc.year = classification.year
                doc.department = classification.department
                doc.status = DocumentStatus.CLASSIFYING
                logger.debug("Document classified", doc_id=doc.id)
                return True
            except Exception as e:
                logger.error("Classification failed", doc_id=doc.id, error=str(e))
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                return False

    results = await asyncio.gather(*[classify_one(doc) for doc in documents])
    await db.commit()

    classified = sum(1 for r in results if r)
    logger.info("Step 2 Complete", classified=classified, total=len(documents))
    return classified


async def run_step_parse(db: AsyncSession) -> int:
    """Step 3: Parse documents with parallel processing."""
    logger.info("Step 3: Starting parsing...")

    service = ParsingService()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.CLASSIFYING)
    )
    documents = list(result.scalars().all())

    if not documents:
        logger.info("No documents to parse")
        return 0

    async def parse_one(doc: Document) -> bool:
        async with semaphore:
            try:
                # Get file path from doc_metadata or construct it
                file_path_str = None
                if doc.doc_metadata:
                    file_path_str = doc.doc_metadata.get("full_path")
                if not file_path_str and doc.drive_path:
                    file_path_str = f"/app/data/raw/{doc.drive_path}"
                if not file_path_str:
                    file_path_str = f"/app/data/source_documents/{doc.drive_name}"

                file_path = Path(file_path_str)

                if not file_path.exists():
                    logger.warning("File not found", doc_id=doc.id, path=str(file_path))
                    return False

                with open(file_path, "rb") as f:
                    file_content = f.read()

                parsed_result = await service.parse_document(
                    file_content=file_content,
                    filename=doc.drive_name,
                )

                # ParsingResult dataclass - use dot notation
                doc.parsed_content = parsed_result.markdown_content or parsed_result.text_content
                doc.status = DocumentStatus.PARSING
                logger.debug("Document parsed", doc_id=doc.id)
                return True

            except Exception as e:
                logger.error("Parsing failed", doc_id=doc.id, error=str(e))
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                return False

    results = await asyncio.gather(*[parse_one(doc) for doc in documents])
    await db.commit()

    parsed = sum(1 for r in results if r)
    logger.info("Step 3 Complete", parsed=parsed, total=len(documents))
    return parsed


async def run_step_preprocess(db: AsyncSession) -> int:
    """Step 4: Preprocess parsed content with parallel processing."""
    logger.info("Step 4: Starting preprocessing...")

    service = PreprocessingService()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PARSING)
    )
    documents = list(result.scalars().all())

    if not documents:
        logger.info("No documents to preprocess")
        return 0

    async def preprocess_one(doc: Document) -> bool:
        async with semaphore:
            try:
                if not doc.parsed_content:
                    logger.warning("No parsed content", doc_id=doc.id)
                    return False

                is_meeting = doc.doc_category == DocumentCategory.MEETING_DOCUMENT
                preprocessed = await service.preprocess_document(
                    content=doc.parsed_content,
                    is_meeting_document=is_meeting,
                )

                # PreprocessingResult dataclass - use dot notation
                doc.preprocessed_content = preprocessed.processed_content or doc.parsed_content
                doc.status = DocumentStatus.PREPROCESSING
                logger.debug("Document preprocessed", doc_id=doc.id)
                return True

            except Exception as e:
                logger.error("Preprocessing failed", doc_id=doc.id, error=str(e))
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                return False

    results = await asyncio.gather(*[preprocess_one(doc) for doc in documents])
    await db.commit()

    processed = sum(1 for r in results if r)
    logger.info("Step 4 Complete", processed=processed, total=len(documents))
    return processed


async def run_step_chunk(db: AsyncSession) -> int:
    """Step 5: Chunk documents (sync operation, sequential)."""
    logger.info("Step 5: Starting chunking...")

    service = ChunkingService()

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PREPROCESSING)
    )
    documents = list(result.scalars().all())

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

            metadata = {
                "document_id": doc.id,
                "category": doc.doc_category.value if doc.doc_category else None,
                "year": doc.year,
                "department": doc.department,
            }

            # ChunkingService.chunk_document returns list[ChunkData]
            chunk_data_list = service.chunk_document(
                content=content,
                document_metadata=metadata,
            )

            # ChunkData dataclass - use dot notation
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
                    metadata=chunk_data.metadata if hasattr(chunk_data, 'metadata') else {},
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

    # MetadataEnrichmentService takes db in __init__
    service = MetadataEnrichmentService(db)

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.CHUNKING)
    )
    documents = list(result.scalars().all())

    if not documents:
        logger.info("No documents to enrich")
        return 0

    enriched = 0
    for doc in documents:
        try:
            # enrich_document modifies document in place, returns EnrichmentResult
            enrich_result = await service.enrich_document(doc)
            doc.status = DocumentStatus.EMBEDDING
            enriched += 1
            logger.debug(
                "Document enriched",
                doc_id=doc.id,
                chunks_enriched=enrich_result.chunks_enriched if enrich_result else 0,
            )
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

    # EmbeddingService takes db in __init__
    service = EmbeddingService(db)

    # Ensure HNSW index exists
    await service.ensure_hnsw_index()

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.EMBEDDING)
    )
    documents = list(result.scalars().all())

    if not documents:
        logger.info("No documents to embed")
        return 0

    total_embedded = 0
    for doc in documents:
        try:
            chunk_result = await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
            )
            chunks = list(chunk_result.scalars().all())

            if chunks:
                # EmbeddingResult dataclass - use dot notation
                embed_result = await service.embed_chunks(chunks)
                total_embedded += embed_result.chunks_embedded
                logger.debug(
                    "Chunks embedded",
                    doc_id=doc.id,
                    embedded=embed_result.chunks_embedded,
                    failed=len(embed_result.failed_chunks),
                )

            doc.status = DocumentStatus.COMPLETED

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
            logger.info(f"Running step: {step_name}")
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
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent document processing (default: 5)",
    )
    args = parser.parse_args()

    global MAX_CONCURRENT
    MAX_CONCURRENT = args.concurrency

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
