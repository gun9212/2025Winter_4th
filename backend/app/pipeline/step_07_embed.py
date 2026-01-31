"""Step 7: Embedding - Generate embeddings and store in pgvector.

This module handles:
1. Vertex AI text-embedding-004 for vector generation
2. Batch embedding for efficiency
3. pgvector storage with HNSW indexing
"""

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.config import settings
from app.models.embedding import DocumentChunk, EMBEDDING_DIMENSION

logger = structlog.get_logger()


@dataclass
class EmbeddingResult:
    """Result of embedding operation."""
    
    chunks_embedded: int
    total_tokens: int
    failed_chunks: list[int]
    index_status: str


class EmbeddingService:
    """
    Service for generating embeddings using Vertex AI text-embedding-004.
    
    Embeds child chunks for vector search while maintaining
    parent content for context retrieval.
    """

    def __init__(self, db: AsyncSession):
        """Initialize embedding service."""
        self.db = db
        self.model_name = settings.VERTEX_AI_EMBEDDING_MODEL
        self.dimension = EMBEDDING_DIMENSION
        self._client = None

    def _get_embedding_model(self):
        """Lazy initialization of Vertex AI embedding model."""
        if self._client is None:
            from google.cloud import aiplatform
            
            aiplatform.init(
                project=settings.GOOGLE_CLOUD_PROJECT,
                location=settings.VERTEX_AI_LOCATION,
            )
            
            from vertexai.language_models import TextEmbeddingModel
            self._client = TextEmbeddingModel.from_pretrained(self.model_name)
        
        return self._client

    async def embed_chunks(
        self,
        chunks: list[DocumentChunk],
        batch_size: int = 50,
        embed_parents: bool = False,
    ) -> EmbeddingResult:
        """
        Generate embeddings for chunks and store in database.
        
        By default, only child chunks are embedded for search.
        Parent chunks are stored but not embedded (used for context).
        
        Args:
            chunks: List of DocumentChunk objects to embed
            batch_size: Number of chunks to embed in each batch
            embed_parents: Whether to also embed parent chunks
            
        Returns:
            EmbeddingResult with statistics
        """
        # Filter chunks to embed
        chunks_to_embed = [
            c for c in chunks 
            if not c.is_parent or embed_parents
        ]
        
        if not chunks_to_embed:
            return EmbeddingResult(
                chunks_embedded=0,
                total_tokens=0,
                failed_chunks=[],
                index_status="no_chunks",
            )

        total_embedded = 0
        total_tokens = 0
        failed_chunks: list[int] = []

        # Process in batches
        for i in range(0, len(chunks_to_embed), batch_size):
            batch = chunks_to_embed[i:i + batch_size]
            
            try:
                embeddings, tokens = await self._embed_batch(
                    [c.content for c in batch]
                )
                
                # Update chunks with embeddings
                for chunk, embedding in zip(batch, embeddings):
                    chunk.embedding = embedding
                
                total_embedded += len(batch)
                total_tokens += tokens
                
                await self.db.flush()
                
                logger.debug(
                    "Batch embedded",
                    batch_start=i,
                    batch_size=len(batch),
                    tokens=tokens,
                )
                
            except Exception as e:
                logger.error("Batch embedding failed", batch_start=i, error=str(e))
                failed_chunks.extend([c.id for c in batch])

        # Commit all changes
        await self.db.commit()

        logger.info(
            "Embedding completed",
            total_embedded=total_embedded,
            total_tokens=total_tokens,
            failed=len(failed_chunks),
        )

        return EmbeddingResult(
            chunks_embedded=total_embedded,
            total_tokens=total_tokens,
            failed_chunks=failed_chunks,
            index_status="completed",
        )

    async def _embed_batch(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], int]:
        """
        Embed a batch of texts using Vertex AI.
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            Tuple of (embeddings list, total tokens)
        """
        import asyncio
        
        model = self._get_embedding_model()
        
        # Run in thread pool since Vertex AI SDK is sync
        def _embed():
            embeddings_response = model.get_embeddings(texts)
            embeddings = [e.values for e in embeddings_response]
            # Estimate tokens (Vertex AI doesn't always return token count)
            tokens = sum(len(t) // 4 for t in texts)  # Rough estimate
            return embeddings, tokens
        
        return await asyncio.to_thread(_embed)

    async def embed_single(self, text: str) -> list[float]:
        """
        Embed a single text for query purposes.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        embeddings, _ = await self._embed_batch([text])
        return embeddings[0]

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 10,
        access_level: int = 4,
        year_filter: int | None = None,
        include_parent_content: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search for similar chunks using vector similarity.
        
        Args:
            query_embedding: Query vector
            limit: Maximum results to return
            access_level: Filter by access level (user's level or lower)
            year_filter: Optional year filter
            include_parent_content: Whether to include parent content
            
        Returns:
            List of matching chunks with scores
        """
        # Build query with pgvector cosine distance
        query = """
            SELECT 
                c.id,
                c.content,
                c.parent_content,
                c.section_header,
                c.chunk_type,
                c.access_level,
                c.metadata,
                d.id as document_id,
                d.drive_name,
                d.drive_id,
                d.standardized_name,
                d.time_decay_date,
                d.meeting_subtype,
                1 - (c.embedding <=> :query_embedding) as similarity_score
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.embedding IS NOT NULL
                AND c.is_parent = FALSE
                AND c.access_level >= :access_level
        """
        
        params = {
            "query_embedding": str(query_embedding),
            "access_level": access_level,
            "limit": limit,
        }

        if year_filter:
            query += " AND d.year = :year_filter"
            params["year_filter"] = year_filter

        query += """
            ORDER BY c.embedding <=> :query_embedding
            LIMIT :limit
        """

        result = await self.db.execute(text(query), params)
        rows = result.fetchall()

        return [
            {
                "id": row.id,
                "content": row.content,
                "parent_content": row.parent_content if include_parent_content else None,
                "section_header": row.section_header,
                "chunk_type": row.chunk_type,
                "access_level": row.access_level,
                "metadata": row.metadata,
                "document_id": row.document_id,
                "document_name": row.standardized_name or row.drive_name,
                "drive_id": row.drive_id,
                "similarity_score": float(row.similarity_score),
                "reliability_score": self._get_reliability_score(row.meeting_subtype),
            }
            for row in rows
        ]

    def _get_reliability_score(self, meeting_subtype: str | None) -> int:
        """Get reliability score based on meeting subtype."""
        if meeting_subtype == "result":
            return 3  # Highest
        elif meeting_subtype == "minutes":
            return 2
        elif meeting_subtype == "agenda":
            return 1
        return 0

    async def ensure_hnsw_index(self) -> str:
        """
        Ensure HNSW index exists on chunks table.
        
        Creates the index if it doesn't exist.
        
        Returns:
            Status message
        """
        # Check if index exists
        check_query = """
            SELECT EXISTS (
                SELECT 1 FROM pg_indexes 
                WHERE indexname = 'idx_chunks_embedding_hnsw'
            )
        """
        result = await self.db.execute(text(check_query))
        exists = result.scalar()

        if exists:
            return "Index already exists"

        # Create HNSW index
        create_query = """
            CREATE INDEX idx_chunks_embedding_hnsw 
            ON document_chunks 
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """
        
        try:
            await self.db.execute(text(create_query))
            await self.db.commit()
            logger.info("HNSW index created")
            return "Index created successfully"
        except Exception as e:
            logger.error("Index creation failed", error=str(e))
            return f"Index creation failed: {e}"

    async def search_with_time_decay(
        self,
        query_embedding: list[float],
        limit: int = 10,
        access_level: int = 4,
        semantic_weight: float = 0.7,
        time_weight: float = 0.3,
    ) -> list[dict[str, Any]]:
        """
        Search with combined semantic and time decay scoring.
        
        Final Score = semantic_weight * similarity + time_weight * recency
        
        Args:
            query_embedding: Query vector
            limit: Maximum results
            access_level: Access level filter
            semantic_weight: Weight for semantic similarity (default 0.7)
            time_weight: Weight for recency (default 0.3)
            
        Returns:
            List of matching chunks with combined scores
        """
        query = """
            SELECT 
                c.id,
                c.content,
                c.parent_content,
                c.section_header,
                c.access_level,
                d.id as document_id,
                d.drive_name,
                d.drive_id,
                d.standardized_name,
                d.time_decay_date,
                1 - (c.embedding <=> :query_embedding) as semantic_score,
                EXP(-0.001 * EXTRACT(DAY FROM NOW() - d.time_decay_date)) as time_score,
                (
                    :semantic_weight * (1 - (c.embedding <=> :query_embedding)) + 
                    :time_weight * EXP(-0.001 * EXTRACT(DAY FROM NOW() - d.time_decay_date))
                ) as final_score
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.embedding IS NOT NULL
                AND c.is_parent = FALSE
                AND c.access_level >= :access_level
                AND d.time_decay_date IS NOT NULL
            ORDER BY final_score DESC
            LIMIT :limit
        """

        result = await self.db.execute(
            text(query),
            {
                "query_embedding": str(query_embedding),
                "access_level": access_level,
                "semantic_weight": semantic_weight,
                "time_weight": time_weight,
                "limit": limit,
            },
        )
        rows = result.fetchall()

        return [
            {
                "id": row.id,
                "content": row.content,
                "parent_content": row.parent_content,
                "section_header": row.section_header,
                "access_level": row.access_level,
                "document_id": row.document_id,
                "document_name": row.standardized_name or row.drive_name,
                "drive_id": row.drive_id,
                "semantic_score": float(row.semantic_score),
                "time_score": float(row.time_score),
                "final_score": float(row.final_score),
            }
            for row in rows
        ]
