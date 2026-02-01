"""Vector retriever for semantic search."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.step_07_embed import EmbeddingService


class VectorRetriever:
    """Service for vector similarity search using pgvector."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.embedding_service = EmbeddingService(db)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Search for similar documents using vector similarity.

        Args:
            query: Search query text.
            top_k: Number of results to return.
            similarity_threshold: Minimum similarity score.

        Returns:
            List of search results with similarity scores.
        """
        # Generate query embedding (using Vertex AI text-embedding-004)
        query_embedding = await self.embedding_service.embed_single(query)

        # pgvector cosine distance search
        sql = text("""
            SELECT
                dc.id,
                dc.document_id,
                dc.content,
                dc.chunk_type,
                dc.metadata,
                d.drive_id,
                d.drive_name,
                1 - (dc.embedding <=> :embedding) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> :embedding
            LIMIT :limit
        """)

        result = await self.db.execute(
            sql,
            {
                "embedding": str(query_embedding),
                "limit": top_k,
            },
        )

        rows = result.fetchall()

        results = []
        for row in rows:
            if row.similarity >= similarity_threshold:
                results.append(
                    {
                        "chunk_id": row.id,
                        "document_id": row.document_id,
                        "content": row.content,
                        "chunk_type": row.chunk_type,
                        "metadata": row.metadata,
                        "drive_id": row.drive_id,
                        "document_name": row.drive_name,
                        "similarity": float(row.similarity),
                    }
                )

        return results

    async def search_with_filter(
        self,
        query: str,
        document_ids: list[int] | None = None,
        chunk_types: list[str] | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search with additional filters.

        Args:
            query: Search query text.
            document_ids: Optional list of document IDs to search within.
            chunk_types: Optional list of chunk types to include.
            top_k: Number of results to return.

        Returns:
            Filtered search results.
        """
        query_embedding = await self.embedding_service.embed_single(query)

        # Build dynamic query with filters
        conditions = ["dc.embedding IS NOT NULL"]
        params: dict[str, Any] = {
            "embedding": str(query_embedding),
            "limit": top_k,
        }

        if document_ids:
            conditions.append("dc.document_id = ANY(:doc_ids)")
            params["doc_ids"] = document_ids

        if chunk_types:
            conditions.append("dc.chunk_type = ANY(:chunk_types)")
            params["chunk_types"] = chunk_types

        where_clause = " AND ".join(conditions)

        sql = text(f"""
            SELECT
                dc.id,
                dc.document_id,
                dc.content,
                dc.chunk_type,
                dc.metadata,
                d.drive_id,
                d.drive_name,
                1 - (dc.embedding <=> :embedding) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE {where_clause}
            ORDER BY dc.embedding <=> :embedding
            LIMIT :limit
        """)

        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        return [
            {
                "chunk_id": row.id,
                "document_id": row.document_id,
                "content": row.content,
                "chunk_type": row.chunk_type,
                "metadata": row.metadata,
                "drive_id": row.drive_id,
                "document_name": row.drive_name,
                "similarity": float(row.similarity),
            }
            for row in rows
        ]

    async def get_context_window(
        self,
        chunk_id: int,
        window_size: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Get surrounding chunks for context.

        Args:
            chunk_id: The central chunk ID.
            window_size: Number of chunks before and after.

        Returns:
            List of chunks in context window.
        """
        sql = text("""
            WITH target AS (
                SELECT document_id, chunk_index
                FROM document_chunks
                WHERE id = :chunk_id
            )
            SELECT
                dc.id,
                dc.content,
                dc.chunk_index,
                dc.chunk_type
            FROM document_chunks dc
            JOIN target t ON dc.document_id = t.document_id
            WHERE dc.chunk_index BETWEEN (t.chunk_index - :window) AND (t.chunk_index + :window)
            ORDER BY dc.chunk_index
        """)

        result = await self.db.execute(
            sql,
            {"chunk_id": chunk_id, "window": window_size},
        )

        return [
            {
                "id": row.id,
                "content": row.content,
                "chunk_index": row.chunk_index,
                "chunk_type": row.chunk_type,
            }
            for row in result.fetchall()
        ]
