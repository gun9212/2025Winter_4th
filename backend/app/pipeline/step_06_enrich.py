"""Step 6: Metadata Enrichment - Inject metadata into documents and chunks.

This module handles metadata injection:
1. Event association (event_id FK)
2. Access level (1-4 permission levels)
3. Time decay date for search weighting
4. Department and organization info
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.document import Document, DocumentCategory, MeetingSubtype
from app.models.event import Event
from app.models.embedding import DocumentChunk
from app.pipeline.step_05_chunk import ChunkData

logger = structlog.get_logger()


@dataclass
class EnrichmentResult:
    """Result of metadata enrichment."""
    
    document_id: int
    event_id: int | None
    access_level: int
    time_decay_date: date | None
    department: str | None
    chunks_enriched: int


class MetadataEnrichmentService:
    """
    Service for enriching documents and chunks with metadata.
    
    Access Levels:
        1: 회장단만 접근 가능 (President/VP only)
        2: 국장단까지 접근 가능 (Department heads)
        3: 모든 국원 접근 가능 (All council members)
        4: 일반 대중 접근 가능 (Public)
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def enrich_document(
        self,
        document: Document,
        classification_result: dict | None = None,
        event_hints: dict | None = None,
    ) -> EnrichmentResult:
        """
        Enrich a document with metadata.
        
        Args:
            document: Document to enrich
            classification_result: Result from classification step
            event_hints: Hints for event association (title, year, etc.)
            
        Returns:
            EnrichmentResult with enrichment details
        """
        classification = classification_result or {}
        hints = event_hints or {}

        # Step 1: Determine access level based on document type
        access_level = self._determine_access_level(document, classification)
        document.access_level = access_level

        # Step 2: Set time decay date
        time_decay_date = self._determine_time_decay_date(document, classification)
        document.time_decay_date = time_decay_date

        # Step 3: Set department
        department = classification.get("department") or hints.get("department")
        if department:
            document.department = department

        # Step 4: Associate with event
        event_id = await self._associate_with_event(
            document,
            hints.get("event_title") or classification.get("event_name"),
            hints.get("year") or classification.get("year"),
            hints.get("category"),
        )
        if event_id:
            document.event_id = event_id

        # Step 5: Set year
        year = classification.get("year") or hints.get("year")
        if year:
            document.year = year

        # Commit document changes
        await self.db.flush()

        return EnrichmentResult(
            document_id=document.id,
            event_id=event_id,
            access_level=access_level,
            time_decay_date=time_decay_date,
            department=department,
            chunks_enriched=0,  # Updated after chunk enrichment
        )

    async def enrich_chunks(
        self,
        document: Document,
        chunks: list[ChunkData],
    ) -> list[DocumentChunk]:
        """
        Create and enrich DatabaseChunk objects from ChunkData.
        
        Inherits access_level from parent document.
        
        Args:
            document: Parent document
            chunks: List of ChunkData from chunking step
            
        Returns:
            List of enriched DocumentChunk objects (not yet embedded)
        """
        db_chunks: list[DocumentChunk] = []
        parent_id_mapping: dict[int, int] = {}  # chunk_index -> db id

        # First pass: create parent chunks
        for chunk_data in chunks:
            if chunk_data.is_parent:
                db_chunk = DocumentChunk(
                    document_id=document.id,
                    is_parent=True,
                    parent_chunk_id=None,
                    chunk_index=chunk_data.chunk_index,
                    chunk_type=chunk_data.chunk_type,
                    content=chunk_data.content,
                    parent_content=None,
                    section_header=chunk_data.section_header,
                    access_level=document.access_level,
                    metadata=chunk_data.metadata,
                    token_count=chunk_data.token_count,
                    start_char=chunk_data.start_char,
                    end_char=chunk_data.end_char,
                )
                self.db.add(db_chunk)
                await self.db.flush()  # Get the ID
                
                parent_id_mapping[chunk_data.chunk_index] = db_chunk.id
                db_chunks.append(db_chunk)

        # Second pass: create child chunks with parent references
        for chunk_data in chunks:
            if not chunk_data.is_parent:
                parent_db_id = None
                if chunk_data.parent_index is not None:
                    parent_db_id = parent_id_mapping.get(chunk_data.parent_index)

                db_chunk = DocumentChunk(
                    document_id=document.id,
                    is_parent=False,
                    parent_chunk_id=parent_db_id,
                    chunk_index=chunk_data.chunk_index,
                    chunk_type=chunk_data.chunk_type,
                    content=chunk_data.content,
                    parent_content=chunk_data.parent_content,
                    section_header=chunk_data.section_header,
                    access_level=document.access_level,
                    metadata=chunk_data.metadata,
                    token_count=chunk_data.token_count,
                    start_char=chunk_data.start_char,
                    end_char=chunk_data.end_char,
                )
                self.db.add(db_chunk)
                db_chunks.append(db_chunk)

        await self.db.flush()
        
        logger.info(
            "Chunks enriched",
            document_id=document.id,
            total_chunks=len(db_chunks),
            parent_chunks=len(parent_id_mapping),
        )

        return db_chunks

    def _determine_access_level(
        self,
        document: Document,
        classification: dict,
    ) -> int:
        """
        Determine access level based on document characteristics.
        
        Default rules:
            - 결과지 (result): Public (4) - final decisions are transparent
            - 속기록 (minutes): Council members (3) - internal discussions
            - 안건지 (agenda): Council members (3)
            - Work documents: Department heads (2) - operational details
            - Sensitive documents: President/VP only (1)
        """
        # Check for explicit sensitive markers in metadata
        if classification.get("is_sensitive"):
            return 1  # President/VP only

        # Check document category
        if document.doc_category == DocumentCategory.MEETING_DOCUMENT:
            if document.meeting_subtype == MeetingSubtype.RESULT:
                return 4  # Public - final decisions
            return 3  # Council members - discussions

        if document.doc_category == DocumentCategory.WORK_DOCUMENT:
            # Work documents default to department level
            return 2

        # Default: council members
        return 3

    def _determine_time_decay_date(
        self,
        document: Document,
        classification: dict,
    ) -> date | None:
        """
        Determine the date to use for time decay scoring.
        
        Priority:
            1. Explicit date from classification
            2. Document's processed_at date
            3. Current date
        """
        # Check classification for date
        class_date = classification.get("date")
        if class_date:
            if isinstance(class_date, date):
                return class_date
            if isinstance(class_date, str):
                try:
                    return datetime.strptime(class_date, "%Y-%m-%d").date()
                except ValueError:
                    pass

        # Use processed timestamp
        if document.processed_at:
            return document.processed_at.date()

        # Fallback to today
        return date.today()

    async def _associate_with_event(
        self,
        document: Document,
        event_title: str | None,
        year: int | None,
        category: str | None,
    ) -> int | None:
        """
        Find or create an event to associate with the document.
        
        Args:
            document: Document to associate
            event_title: Event title hint
            year: Event year
            category: Event category (department)
            
        Returns:
            Event ID if found/created, None otherwise
        """
        if not event_title and not year:
            return None

        # Try to find existing event
        query = select(Event)
        if event_title:
            query = query.where(Event.title.ilike(f"%{event_title}%"))
        if year:
            query = query.where(Event.year == year)
        
        result = await self.db.execute(query.limit(1))
        event = result.scalar_one_or_none()

        if event:
            return event.id

        # Create new event if we have enough info
        if event_title and year:
            new_event = Event(
                title=event_title,
                year=year,
                category=category,
            )
            self.db.add(new_event)
            await self.db.flush()
            
            logger.info("Created new event", title=event_title, year=year)
            return new_event.id

        return None

    async def update_event_chunk_timeline(
        self,
        event_id: int,
        meeting_name: str,
        parent_chunk_ids: list[int],
        decision_summaries: list[str] | None = None,
    ) -> None:
        """
        Update event's chunk timeline with new meeting data.
        
        Args:
            event_id: Event to update
            meeting_name: Name of the meeting (e.g., "2차 국장단 회의")
            parent_chunk_ids: List of parent chunk IDs for this meeting
            decision_summaries: Optional list of decision summaries
        """
        result = await self.db.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one_or_none()
        
        if not event:
            logger.warning("Event not found for timeline update", event_id=event_id)
            return

        for chunk_id in parent_chunk_ids:
            event.add_chunk_to_timeline(meeting_name, chunk_id)
        
        if decision_summaries:
            for summary in decision_summaries:
                event.add_chunk_to_timeline(meeting_name, -1, summary)

        # Update parent_chunk_ids array
        if event.parent_chunk_ids is None:
            event.parent_chunk_ids = []
        event.parent_chunk_ids.extend(parent_chunk_ids)
        event.parent_chunk_ids = list(set(event.parent_chunk_ids))  # Dedupe

        await self.db.flush()
