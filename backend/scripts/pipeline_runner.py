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

from app.core.database import async_session_factory as AsyncSessionLocal
from app.models.document import Document, DocumentStatus
from app.pipeline.step_01_ingest import IngestionService
from app.pipeline.step_02_classify import ClassificationService
from app.pipeline.step_03_parse import ParsingService
from app.pipeline.step_04_preprocess import PreprocessingService
from app.pipeline.step_05_chunk import ChunkingService
from app.pipeline.step_06_enrich import MetadataEnrichmentService
from app.pipeline.step_07_embed import EmbeddingService

logger = structlog.get_logger()


async def run_step_ingest(db: AsyncSession) -> int:
    """Step 1: Ingest files from Google Drive."""
    logger.info("Step 1: Starting ingestion...")
    service = IngestionService(db)
    result = await service.sync_from_drive()
    logger.info(
        "Step 1 Complete",
        files_synced=result.files_synced,
        files_failed=result.files_failed,
    )
    return result.files_synced


async def run_step_classify(db: AsyncSession) -> int:
    """Step 2: Classify documents."""
    logger.info("Step 2: Starting classification...")
    service = ClassificationService(db)

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
            await service.classify_document(doc)
            classified += 1
        except Exception as e:
            logger.error("Classification failed", doc_id=doc.id, error=str(e))

    await db.commit()
    logger.info("Step 2 Complete", classified=classified)
    return classified


async def run_step_parse(db: AsyncSession) -> int:
    """Step 3: Parse documents with Upstage."""
    logger.info("Step 3: Starting parsing...")
    service = ParsingService(db)

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
            await service.parse_document(doc)
            parsed += 1
        except Exception as e:
            logger.error("Parsing failed", doc_id=doc.id, error=str(e))

    await db.commit()
    logger.info("Step 3 Complete", parsed=parsed)
    return parsed


async def run_step_preprocess(db: AsyncSession) -> int:
    """Step 4: Preprocess parsed content."""
    logger.info("Step 4: Starting preprocessing...")
    service = PreprocessingService(db)

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
            await service.preprocess_document(doc)
            processed += 1
        except Exception as e:
            logger.error("Preprocessing failed", doc_id=doc.id, error=str(e))

    await db.commit()
    logger.info("Step 4 Complete", processed=processed)
    return processed


async def run_step_chunk(db: AsyncSession) -> int:
    """Step 5: Chunk documents."""
    logger.info("Step 5: Starting chunking...")
    service = ChunkingService(db)

    result = await db.execute(
        select(Document).where(Document.status == DocumentStatus.PREPROCESSING)
    )
    documents = result.scalars().all()

    if not documents:
        logger.info("No documents to chunk")
        return 0

    chunked = 0
    for doc in documents:
        try:
            await service.chunk_document(doc)
            chunked += 1
        except Exception as e:
            logger.error("Chunking failed", doc_id=doc.id, error=str(e))

    await db.commit()
    logger.info("Step 5 Complete", chunked=chunked)
    return chunked


async def run_step_enrich(db: AsyncSession) -> int:
    """Step 6: Enrich metadata."""
    logger.info("Step 6: Starting metadata enrichment...")
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
            enriched += 1
        except Exception as e:
            logger.error("Enrichment failed", doc_id=doc.id, error=str(e))

    await db.commit()
    logger.info("Step 6 Complete", enriched=enriched)
    return enriched


async def run_step_embed(db: AsyncSession) -> int:
    """Step 7: Generate embeddings."""
    logger.info("Step 7: Starting embedding generation...")
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

    from app.models.embedding import DocumentChunk

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
        except Exception as e:
            logger.error("Embedding failed", doc_id=doc.id, error=str(e))
            doc.status = DocumentStatus.FAILED

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
    result = await db.execute(text("SELECT COUNT(*) FROM document_chunks"))
    stats["total_chunks"] = result.scalar() or 0

    # Count embedded chunks
    result = await db.execute(
        text("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
    )
    stats["embedded_chunks"] = result.scalar() or 0

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
