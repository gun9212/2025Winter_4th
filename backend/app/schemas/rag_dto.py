"""Schemas for RAG (Retrieval-Augmented Generation) API."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FileType(str, Enum):
    """Supported file types for ingestion."""

    GOOGLE_DOC = "google_doc"
    GOOGLE_SHEET = "google_sheet"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"


class IngestOptions(BaseModel):
    """Options for folder ingestion."""

    is_privacy_sensitive: bool = Field(
        default=False,
        description="If true, files are stored as references only (no embedding)",
    )
    recursive: bool = Field(
        default=True,
        description="Whether to process subfolders recursively",
    )
    file_types: list[FileType] | None = Field(
        default=None,
        description="File types to process (None = all supported types)",
    )
    exclude_patterns: list[str] = Field(
        default=["*.tmp", "~*"],
        description="Glob patterns for files to exclude",
    )
    skip_sync: bool = Field(
        default=False,
        description="If true, skip rclone sync (use local files only)",
    )


class IngestRequest(BaseModel):
    """Request schema for document ingestion.
    
    Note: event_id is NOT included per Ground Truth requirement.
    Event mapping happens at chunk level during enrichment step,
    not at ingestion time.
    """

    folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID to ingest (uses env default if not provided)",
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
    )
    options: IngestOptions = Field(
        default_factory=IngestOptions,
        description="Ingestion options",
    )
    user_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="User access level for permission check",
    )


class IngestResponse(BaseModel):
    """Response schema for document ingestion."""

    task_id: str = Field(..., description="Task ID for tracking ingestion progress")
    message: str = Field(..., description="Status message")
    documents_found: int = Field(..., description="Number of documents found")


class SearchRequest(BaseModel):
    """Request schema for RAG search."""

    query: str = Field(
        ...,
        description="Search query text",
        min_length=1,
        max_length=2000,
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Number of results to return",
    )
    user_level: int = Field(
        default=4,
        ge=1,
        le=4,
        description="User access level (1: 회장단만, 2: 국장단까지, 3: 모든 국원, 4: 일반 대중)",
    )
    include_context: bool = Field(
        default=True,
        description="Whether to include surrounding context",
    )
    generate_answer: bool = Field(
        default=True,
        description="Whether to generate an LLM answer",
    )


class SearchResult(BaseModel):
    """Individual search result."""

    document_id: int = Field(..., description="Document ID")
    document_name: str = Field(..., description="Document name")
    chunk_content: str = Field(..., description="Matching chunk content")
    similarity_score: float = Field(..., description="Cosine similarity score")
    metadata: dict | None = Field(default=None, description="Additional metadata")


class SourceReference(BaseModel):
    """Source reference for answer generation."""

    document_id: int = Field(..., description="Document ID")
    document_name: str = Field(..., description="Document name")
    drive_id: str = Field(..., description="Google Drive file ID")
    url: str | None = Field(default=None, description="Direct URL to document")


class SearchResponse(BaseModel):
    """Response schema for RAG search."""

    query: str = Field(..., description="Original search query")
    results: list[SearchResult] = Field(..., description="Search results")
    answer: str | None = Field(
        default=None,
        description="LLM-generated answer based on context",
    )
    sources: list[SourceReference] = Field(
        default_factory=list,
        description="Source documents used for answer",
    )
    partner_info: dict | None = Field(
        default=None,
        description="Partner business info (for 간식/회식 queries)",
    )


class DocumentInfo(BaseModel):
    """Document information for list response."""

    id: int = Field(..., description="Document ID")
    drive_id: str = Field(..., description="Google Drive file ID")
    name: str = Field(..., description="Document name")
    doc_type: str = Field(..., description="Document type")
    status: str = Field(..., description="Processing status")
    chunk_count: int = Field(default=0, description="Number of chunks")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class DocumentListResponse(BaseModel):
    """Response schema for document list."""

    total: int = Field(..., description="Total number of documents")
    documents: list[DocumentInfo] = Field(..., description="Document list")
    skip: int = Field(..., description="Number of documents skipped")
    limit: int = Field(..., description="Maximum documents returned")
