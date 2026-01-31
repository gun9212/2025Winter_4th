"""Embedding-related Celery tasks.

This module contains tasks for:
- Document embedding generation
- Batch embedding processing
- Embedding service health checks
"""

import time
from typing import Any

from celery import shared_task
import structlog

logger = structlog.get_logger()


@shared_task(bind=True, name="app.tasks.embedding.test_celery_task")
def test_celery_task(self, message: str = "Hello World") -> dict[str, Any]:
    """
    Test task to verify Celery worker is functioning correctly.

    This task simulates a long-running operation with a 5-second delay
    to demonstrate asynchronous task processing.

    Args:
        message: A test message to echo back.

    Returns:
        Dict containing task result and metadata.
    """
    logger.info(
        "Test task started",
        task_id=self.request.id,
        message=message,
    )

    # Simulate long-running operation
    time.sleep(5)

    result = {
        "status": "success",
        "message": message,
        "task_id": self.request.id,
        "worker": self.request.hostname,
    }

    logger.info(
        "Test task completed",
        task_id=self.request.id,
        result=result,
    )

    return result


@shared_task(bind=True, name="app.tasks.embedding.embed_documents")
def embed_documents_task(
    self,
    document_ids: list[int],
    batch_size: int = 50,
) -> dict[str, Any]:
    """
    Generate embeddings for documents and store in database.

    This task retrieves document chunks from the database,
    generates embeddings using the EmbeddingService,
    and stores the vectors back to PostgreSQL with pgvector.

    Args:
        document_ids: List of document IDs to process.
        batch_size: Number of chunks to embed in each batch.

    Returns:
        Dict containing processing statistics.
    """
    import asyncio
    from app.core.database import async_session_factory

    async def _process():
        from sqlalchemy import select
        from app.models.document import Document, DocumentStatus
        from app.models.embedding import DocumentChunk
        from app.services.ai.embeddings import EmbeddingService

        embedding_service = EmbeddingService()
        total_embedded = 0
        failed_chunks: list[int] = []

        async with async_session_factory() as db:
            # Get chunks for the specified documents
            result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id.in_(document_ids))
                .where(DocumentChunk.is_parent == False)  # noqa: E712
                .where(DocumentChunk.embedding == None)  # noqa: E711
            )
            chunks = result.scalars().all()

            if not chunks:
                return {
                    "status": "success",
                    "message": "No chunks to embed",
                    "documents_processed": len(document_ids),
                    "chunks_embedded": 0,
                }

            # Process in batches
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                texts = [chunk.content for chunk in batch]

                try:
                    # Generate embeddings (sync method for Celery)
                    embeddings = embedding_service.embed_documents(texts)

                    # Update chunks with embeddings
                    for chunk, embedding in zip(batch, embeddings):
                        chunk.embedding = embedding

                    await db.flush()
                    total_embedded += len(batch)

                    # Update progress
                    progress = int((i + len(batch)) / len(chunks) * 100)
                    self.update_state(
                        state="PROGRESS",
                        meta={"progress": progress, "chunks_embedded": total_embedded},
                    )

                except Exception as e:
                    logger.error(
                        "Batch embedding failed",
                        batch_start=i,
                        error=str(e),
                    )
                    failed_chunks.extend([c.id for c in batch])

            # Update document status
            for doc_id in document_ids:
                doc_result = await db.execute(
                    select(Document).where(Document.id == doc_id)
                )
                doc = doc_result.scalar_one_or_none()
                if doc:
                    doc.status = DocumentStatus.COMPLETED

            await db.commit()

        return {
            "status": "success",
            "documents_processed": len(document_ids),
            "chunks_embedded": total_embedded,
            "failed_chunks": failed_chunks,
        }

    # Run async code in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_process())
    except Exception as e:
        logger.exception("Embedding task failed", error=str(e))
        return {
            "status": "error",
            "error": str(e),
            "document_ids": document_ids,
        }
    finally:
        loop.close()
