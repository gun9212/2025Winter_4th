"""Pydantic schemas for request/response validation."""

from app.schemas.calendar import (
    CalendarSyncOptions,
    CalendarSyncRequest,
    CalendarSyncResponse,
    EventCreateRequest,
    EventListResponse,
    EventResponse,
    ExtractionHints,
)
from app.schemas.chat import (
    ChatHistoryItem,
    ChatMetadata,
    ChatOptions,
    ChatRequest,
    ChatResponse,
    SourceReference,
)
from app.schemas.handover import (
    HandoverContentOptions,
    HandoverGenerateRequest,
    HandoverGenerateResponse,
    HandoverOutputConfig,
    HandoverSourceFilters,
)
from app.schemas.minutes import (
    ActionItem,
    DecisionItem,
    MeetingInfo,
    MinutesProcessRequest,
    MinutesProcessResponse,
    MinutesStatusResponse,
    OutputConfig,
    ProcessingStatus,
)
from app.schemas.rag import (
    DocumentInfo,
    DocumentListResponse,
    FileType,
    IngestOptions,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.schemas.task import (
    TaskQueueResponse,
    TaskResult,
    TaskStatus,
    TaskStatusResponse,
)

__all__ = [
    # Chat
    "ChatRequest",
    "ChatResponse",
    "ChatOptions",
    "ChatMetadata",
    "ChatHistoryItem",
    "SourceReference",
    # Task
    "TaskStatus",
    "TaskResult",
    "TaskStatusResponse",
    "TaskQueueResponse",
    # Handover
    "HandoverGenerateRequest",
    "HandoverGenerateResponse",
    "HandoverContentOptions",
    "HandoverOutputConfig",
    "HandoverSourceFilters",
    # Minutes
    "MinutesProcessRequest",
    "MinutesProcessResponse",
    "MinutesStatusResponse",
    "ProcessingStatus",
    "MeetingInfo",
    "OutputConfig",
    "ActionItem",
    "DecisionItem",
    # RAG
    "IngestRequest",
    "IngestResponse",
    "IngestOptions",
    "FileType",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "DocumentListResponse",
    "DocumentInfo",
    # Calendar
    "EventCreateRequest",
    "EventResponse",
    "EventListResponse",
    "CalendarSyncRequest",
    "CalendarSyncResponse",
    "CalendarSyncOptions",
    "ExtractionHints",
]

