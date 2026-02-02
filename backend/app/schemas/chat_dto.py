"""Schemas for RAG Chat API with multi-turn conversation support."""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return str(uuid4())


class ChatOptions(BaseModel):
    """Options for RAG chat request."""

    include_sources: bool = Field(
        default=True,
        description="Whether to include source document references",
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of chunks to retrieve",
    )
    year_filter: list[int] | None = Field(
        default=None,
        description="Filter by years (e.g., [2024, 2025])",
    )
    department_filter: str | None = Field(
        default=None,
        description="Filter by department (e.g., '문화국', '복지국')",
    )
    semantic_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Weight for semantic similarity (remainder is time decay)",
    )


class ChatRequest(BaseModel):
    """Request schema for RAG chat."""

    session_id: str = Field(
        default_factory=generate_session_id,
        description="Session ID for multi-turn conversation context",
    )
    query: str = Field(
        ...,
        description="User's question",
        min_length=1,
        max_length=2000,
        examples=["간식행사 예산 얼마야?", "축제 가수 섭외 담당자는 누구야?"],
    )
    user_level: int = Field(
        default=4,
        ge=1,
        le=4,
        description="User access level (1: 회장단, 2: 국장단, 3: 국원, 4: 일반)",
    )
    options: ChatOptions = Field(
        default_factory=ChatOptions,
        description="Chat options",
    )


class SourceReference(BaseModel):
    """Source document reference in chat response."""

    document_id: int = Field(..., description="Document database ID")
    document_title: str = Field(..., description="Document title")
    chunk_id: int = Field(..., description="Chunk database ID")
    section_header: str | None = Field(
        default=None,
        description="Section header (e.g., '논의안건 2. 간식행사 예산')",
    )
    relevance_score: float = Field(..., description="Relevance score (0-1)")
    drive_link: str | None = Field(
        default=None,
        description="Google Drive document link",
    )
    event_title: str | None = Field(
        default=None,
        description="Associated event title",
    )


class ChatMetadata(BaseModel):
    """Metadata about the chat response."""

    total_chunks_searched: int = Field(
        default=0,
        description="Total chunks in search scope",
    )
    latency_ms: int = Field(..., description="Total response latency in milliseconds")
    retrieval_latency_ms: int | None = Field(
        default=None,
        description="Vector search latency in milliseconds",
    )
    generation_latency_ms: int | None = Field(
        default=None,
        description="LLM generation latency in milliseconds",
    )
    model_used: str = Field(
        default="gemini-2.0-flash",
        description="LLM model used for generation",
    )


class ChatResponse(BaseModel):
    """Response schema for RAG chat."""

    session_id: str = Field(..., description="Session ID for follow-up questions")
    query: str = Field(..., description="Original user query")
    rewritten_query: str | None = Field(
        default=None,
        description="Query after context-aware rewriting",
    )
    answer: str = Field(..., description="AI-generated answer")
    sources: list[SourceReference] = Field(
        default_factory=list,
        description="Source documents used for answer",
    )
    metadata: ChatMetadata = Field(..., description="Response metadata")


class ChatHistoryItem(BaseModel):
    """Single turn in chat history."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: str | datetime = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="Message timestamp (ISO format string or datetime)",
    )
