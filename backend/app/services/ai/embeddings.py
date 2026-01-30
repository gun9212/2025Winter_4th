"""Embedding service for vector operations."""

import google.generativeai as genai

from app.core.config import settings

# Gemini embedding model dimension
EMBEDDING_DIMENSION = 768


class EmbeddingService:
    """Service for generating text embeddings."""

    def __init__(self) -> None:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model_name = "models/embedding-001"

    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.
        """
        result = genai.embed_content(
            model=self.model_name,
            content=text,
            task_type="retrieval_document",
        )

        return result["embedding"]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        embeddings = []
        for text in texts:
            embedding = self.embed_text(text)
            embeddings.append(embedding)
        return embeddings

    def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.

        Uses a different task type optimized for queries.

        Args:
            query: Search query text.

        Returns:
            Query embedding vector.
        """
        result = genai.embed_content(
            model=self.model_name,
            content=query,
            task_type="retrieval_query",
        )

        return result["embedding"]

    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Cosine similarity score (-1 to 1).
        """
        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)
