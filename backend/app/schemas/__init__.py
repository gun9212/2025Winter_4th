"""Pydantic schemas for request/response validation."""

from app.schemas.calendar import (
    EventCreateRequest,
    EventListResponse,
    EventResponse,
)
from app.schemas.minutes import (
    MinutesProcessRequest,
    MinutesProcessResponse,
    MinutesStatusResponse,
    ProcessingStatus,
)
from app.schemas.rag import (
    DocumentListResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)

__all__ = [
    # Minutes
    "MinutesProcessRequest",
    "MinutesProcessResponse",
    "MinutesStatusResponse",
    "ProcessingStatus",
    # RAG
    "IngestRequest",
    "IngestResponse",
    "SearchRequest",
    "SearchResponse",
    "DocumentListResponse",
    # Calendar
    "EventCreateRequest",
    "EventResponse",
    "EventListResponse",
]
