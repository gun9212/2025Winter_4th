"""Schemas for Handover document generation API."""

from pydantic import BaseModel, Field


class HandoverContentOptions(BaseModel):
    """Options for handover document content."""

    include_event_summaries: bool = Field(
        default=True,
        description="Include summary of each event",
    )
    include_decision_history: bool = Field(
        default=True,
        description="Include decision history from meetings",
    )
    include_statistics: bool = Field(
        default=True,
        description="Include statistics (budget, events count, etc.)",
    )
    include_insights: bool = Field(
        default=True,
        description="Include LLM-generated insights and recommendations",
    )
    include_recommendations: bool = Field(
        default=True,
        description="Include recommendations for next term",
    )


class HandoverSourceFilters(BaseModel):
    """Filters for source documents in handover generation."""

    doc_categories: list[str] | None = Field(
        default=["meeting_document", "work_document"],
        description="Document categories to include",
    )
    min_authority_level: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Minimum authority level for source documents",
    )
    event_status: list[str] | None = Field(
        default=["completed"],
        description="Event status filter (planned, in_progress, completed)",
    )


class HandoverOutputConfig(BaseModel):
    """Output configuration for handover document."""

    doc_title: str = Field(
        ...,
        description="Title of the handover document",
        examples=["제38대 문화국 인수인계서"],
    )
    output_folder_id: str | None = Field(
        default=None,
        description="Google Drive folder ID for output (optional)",
    )


class HandoverGenerateRequest(BaseModel):
    """Request schema for handover document generation."""

    target_year: int = Field(
        ...,
        description="Target year for handover",
        examples=[2025],
    )
    department: str | None = Field(
        default=None,
        description="Department filter (None for all departments)",
        examples=["문화국", "복지국", "기획국"],
    )
    output_config: HandoverOutputConfig = Field(
        ...,
        description="Output document configuration",
    )
    content_options: HandoverContentOptions = Field(
        default_factory=HandoverContentOptions,
        description="Content generation options",
    )
    source_filters: HandoverSourceFilters = Field(
        default_factory=HandoverSourceFilters,
        description="Source document filters",
    )
    user_level: int = Field(
        default=1,
        ge=1,
        le=4,
        description="User access level (handover typically requires level 1-2)",
    )


class HandoverGenerateResponse(BaseModel):
    """Response schema for handover generation request."""

    task_id: str = Field(..., description="Celery task ID for tracking")
    status: str = Field(default="PENDING", description="Initial task status")
    message: str = Field(..., description="Status message")
    estimated_time_minutes: int = Field(
        default=5,
        description="Estimated completion time in minutes",
    )
