"""Chat log model for conversation history and audit."""

from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChatLog(Base, TimestampMixin):
    """
    Chat conversation log for long-term storage and audit.
    
    Short-term context (multi-turn) is stored in Redis with TTL=1 hour.
    This table stores completed conversations for:
        - Audit trail
        - Analytics
        - Quality improvement
    
    Access Level determines document filtering during search:
        1: 회장단만 접근 가능 (President/VP only)
        2: 국장단까지 접근 가능 (Department heads)
        3: 모든 국원 접근 가능 (All council members)
        4: 일반 대중 접근 가능 (Public)
    """

    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Session identification
    session_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    user_level: Mapped[int] = mapped_column(Integer, default=4, index=True)  # 1-4

    # Conversation content
    user_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)  # Query after rewriting with context
    ai_response: Mapped[str] = mapped_column(Text, nullable=False)

    # Retrieved context metadata
    # Format: [{"chunk_id": 123, "score": 0.95, "section": "..."}, ...]
    retrieved_chunks: Mapped[list | None] = mapped_column(JSONB, default=list)
    
    # Source documents used for answer
    # Format: [{"doc_id": 1, "title": "...", "drive_link": "..."}, ...]
    sources: Mapped[list | None] = mapped_column(JSONB, default=list)

    # Conversation ordering within session
    turn_index: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Performance metrics
    latency_ms: Mapped[int | None] = mapped_column(Integer)  # Total response time
    retrieval_latency_ms: Mapped[int | None] = mapped_column(Integer)  # Vector search time
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer)  # LLM generation time

    # Additional metadata for debugging and analytics
    # Can include: model_version, temperature, top_k, year_filter, etc.
    request_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    def __repr__(self) -> str:
        return f"<ChatLog(id={self.id}, session={self.session_id[:8]}..., turn={self.turn_index})>"
