"""Celery tasks for Council-AI feature implementations.

This module contains tasks for:
- Smart Minutes: Generate result documents from agenda + transcript
- Calendar Sync: Extract events from documents and sync to Google Calendar
- Handover: Generate comprehensive handover documents

All tasks are designed to be long-running and are processed asynchronously.
"""

import asyncio
from datetime import datetime
from typing import Any

from celery import shared_task
import structlog

from app.core.database import async_session_factory

logger = structlog.get_logger()


def run_async(coro):
    """Helper to run async code in sync Celery context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(
    bind=True,
    name="app.tasks.features.generate_minutes",
    max_retries=3,
    default_retry_delay=60,
)
def generate_minutes(
    self,
    agenda_doc_id: str,
    transcript_doc_id: str | None = None,
    transcript_text: str | None = None,
    template_doc_id: str | None = None,
    meeting_name: str = "Untitled Meeting",
    meeting_date: str | None = None,
    output_folder_id: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    """
    Generate a result document from agenda template and meeting transcript.
    
    Smart Minutes Feature Implementation:
    1. Load transcript from Google Docs (if doc_id provided) or use text
    2. Split transcript by agenda headers using text_utils
    3. Summarize each section with Gemini
    4. Copy agenda template to create result document
    5. Replace placeholders with summaries
    
    Args:
        agenda_doc_id: Google Docs ID of agenda template (안건지)
        transcript_doc_id: Google Docs ID of transcript (속기록) - preferred
        transcript_text: Direct transcript text (fallback)
        template_doc_id: Optional template for result (if None, copies agenda)
        meeting_name: Meeting name for output document
        meeting_date: Meeting date (ISO format)
        output_folder_id: Google Drive folder ID for output
        user_email: Email to share the result document with (for Service Account mode)
        
    Returns:
        Task result with output_doc_id and status
    """
    try:
        self.update_state(state="PROGRESS", meta={"progress": 5, "step": "Initializing"})
        
        from app.services.google.docs import GoogleDocsService
        from app.services.ai.gemini import GeminiService
        from app.services.text_utils import split_by_headers, build_placeholder_map
        
        # Use OAuth credentials - files created in authenticated user's Drive
        # Requires oauth_client.json and oauth_token.json in credentials folder
        docs_service = GoogleDocsService(use_oauth=True)
        gemini = GeminiService()
        
        logger.info(
            "Starting Smart Minutes generation",
            meeting_name=meeting_name,
            agenda_doc_id=agenda_doc_id[:8],
            has_transcript_doc=bool(transcript_doc_id),
            user_email=user_email,
        )
        
        # Step 1: Load transcript content
        self.update_state(state="PROGRESS", meta={"progress": 10, "step": "Loading transcript"})
        
        if transcript_doc_id:
            transcript_content = docs_service.get_document_text(transcript_doc_id)
            logger.info("Loaded transcript from Google Docs", length=len(transcript_content))
        elif transcript_text:
            transcript_content = transcript_text
            logger.info("Using provided transcript text", length=len(transcript_content))
        else:
            raise ValueError("Either transcript_doc_id or transcript_text must be provided")
        
        # Step 2: Split transcript by headers
        self.update_state(state="PROGRESS", meta={"progress": 20, "step": "Splitting by agenda"})
        
        sections = split_by_headers(transcript_content, max_level=2)
        logger.info("Split transcript into sections", section_count=len(sections))
        
        # Step 3: Summarize each section with Gemini
        self.update_state(state="PROGRESS", meta={"progress": 30, "step": "Analyzing sections"})
        
        summaries = []
        agenda_summaries = []
        total_sections = len(sections)
        
        for i, section in enumerate(sections):
            progress = 30 + int((i / total_sections) * 40)  # 30-70%
            self.update_state(
                state="PROGRESS", 
                meta={"progress": progress, "step": f"Summarizing section {i+1}/{total_sections}"}
            )
            
            # Get agenda type and summarize
            agenda_type = section.agenda_type or "other"
            result = gemini.summarize_agenda_section(
                section_content=section.content,
                section_title=section.title,
                agenda_type=agenda_type,
            )
            
            summary_text = result.get("summary", "요약 없음")
            summaries.append(summary_text)
            
            agenda_summaries.append({
                "agenda_type": agenda_type,
                "agenda_number": section.agenda_number,
                "title": section.title,
                "summary": summary_text,
                "has_decision": result.get("has_decision", False),
                "action_items": result.get("action_items", []),
            })
        
        # Step 4: Copy agenda template to create result document
        self.update_state(state="PROGRESS", meta={"progress": 75, "step": "Creating result document"})
        
        source_doc_id = template_doc_id or agenda_doc_id
        result_doc_title = f"[결과지] {meeting_name}"
        
        # Use output_folder_id to place result in user's Drive folder
        # Share with user_email so they can access Service Account created files
        new_doc = docs_service.copy_document(
            source_doc_id, 
            result_doc_title,
            parent_folder_id=output_folder_id,
            share_with_email=user_email
        )
        new_doc_id = new_doc.get("id")
        
        logger.info("Created result document", doc_id=new_doc_id, folder_id=output_folder_id)
        
        # Step 5: Replace placeholders with summaries
        self.update_state(state="PROGRESS", meta={"progress": 85, "step": "Replacing placeholders"})
        
        replacements = build_placeholder_map(sections, summaries)
        
        if replacements:
            docs_service.replace_text(new_doc_id, replacements)
            logger.info("Replaced placeholders", count=len(replacements))
        
        self.update_state(state="PROGRESS", meta={"progress": 95, "step": "Finalizing"})
        
        # Count statistics
        decisions_count = sum(1 for s in agenda_summaries if s.get("has_decision"))
        action_items_count = sum(len(s.get("action_items", [])) for s in agenda_summaries)
        
        result = {
            "status": "SUCCESS",
            "output_doc_id": new_doc_id,
            "output_doc_link": f"https://docs.google.com/document/d/{new_doc_id}/edit",
            "meeting_name": meeting_name,
            "agenda_summaries": agenda_summaries,
            "items_processed": len(sections),
            "decisions_extracted": decisions_count,
            "action_items_extracted": action_items_count,
        }
        
        logger.info(
            "Smart Minutes generation completed",
            meeting_name=meeting_name,
            output_doc_id=new_doc_id,
            sections=len(sections),
            decisions=decisions_count,
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "Smart Minutes generation failed",
            error=str(e),
            agenda_doc_id=agenda_doc_id,
        )
        return {
            "status": "FAILURE",
            "error": str(e),
            "meeting_name": meeting_name,
        }


@shared_task(
    bind=True,
    name="app.tasks.features.sync_calendar",
    max_retries=3,
    default_retry_delay=30,
)
def sync_calendar(
    self,
    result_doc_id: str,
    calendar_id: str,
    options: dict | None = None,
    extraction_hints: dict | None = None,
) -> dict[str, Any]:
    """
    Extract action items from result document and create calendar events.
    
    Calendar Sync Feature Implementation:
    1. Read result document via Google Docs API
    2. Extract action items with dates and assignees using patterns
    3. Create calendar events via Google Calendar API
    4. Optionally notify assignees
    
    Args:
        result_doc_id: Google Docs ID of the result document
        calendar_id: Target Google Calendar ID (supports multiple calendars)
        options: Sync options (create_reminders, notify_assignees, etc.)
        extraction_hints: Patterns for extracting dates and assignees
        
    Returns:
        Task result with events_created count
    """
    async def _process():
        try:
            options = options or {}
            extraction_hints = extraction_hints or {}
            
            logger.info(
                "Starting calendar sync",
                result_doc_id=result_doc_id,
                calendar_id=calendar_id,
            )
            
            self.update_state(state="PROGRESS", meta={"progress": 20})
            
            # TODO: Implement actual processing
            # Step 1: Read result document
            # from app.services.google_docs import GoogleDocsService
            # docs_service = GoogleDocsService()
            # doc_content = await docs_service.get_document_text(result_doc_id)
            
            # Step 2: Extract action items
            # date_patterns = extraction_hints.get("date_patterns", ["~까지", "마감일:"])
            # assignee_patterns = extraction_hints.get("assignee_patterns", ["담당:"])
            # action_items = extract_action_items(doc_content, date_patterns, assignee_patterns)
            
            self.update_state(state="PROGRESS", meta={"progress": 50})
            
            # Step 3: Create calendar events
            # from app.services.google_calendar import GoogleCalendarService
            # calendar_service = GoogleCalendarService()
            # events_created = 0
            # for item in action_items:
            #     event = await calendar_service.create_event(
            #         calendar_id=calendar_id,
            #         title=item.task,
            #         start_time=item.deadline,
            #         duration_hours=options.get("default_duration_hours", 1),
            #         attendees=[item.assignee] if options.get("notify_assignees") else None,
            #         reminders=options.get("reminder_minutes"),
            #     )
            #     events_created += 1
            
            self.update_state(state="PROGRESS", meta={"progress": 90})
            
            result = {
                "status": "SUCCESS",
                "events_created": 0,  # Placeholder
                "calendar_id": calendar_id,
                "result_doc_id": result_doc_id,
            }
            
            logger.info(
                "Calendar sync completed",
                result=result,
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Calendar sync failed",
                error=str(e),
                result_doc_id=result_doc_id,
            )
            raise
    
    return run_async(_process())


@shared_task(
    bind=True,
    name="app.tasks.features.generate_handover",
    max_retries=2,
    default_retry_delay=120,
)
def generate_handover(
    self,
    target_year: int,
    department: str | None = None,
    target_folder_id: str | None = None,
    doc_title: str | None = None,
    include_event_summaries: bool = True,
    include_insights: bool = True,
    include_statistics: bool = True,
) -> dict[str, Any]:
    """
    Generate a comprehensive handover document for a specific year.
    
    Handover Feature Implementation:
    1. Query DB for all Events and Documents of target year
    2. Filter by department if specified
    3. Use Gemini to generate insights and recommendations
    4. Create Google Doc with insertText
    
    Args:
        target_year: Year to generate handover for
        department: Optional department filter
        target_folder_id: Google Drive folder ID for output
        doc_title: Document title
        include_event_summaries: Include per-event summaries
        include_insights: Include AI-generated insights
        include_statistics: Include statistics section
        
    Returns:
        Task result with output_doc_id and statistics
    """
    async def _process():
        try:
            from app.services.google.docs import GoogleDocsService
            from app.services.ai.gemini import GeminiService
            from app.models.event import Event
            from app.models.document import Document
            from sqlalchemy import select
            
            # Generate title if not provided
            _doc_title = doc_title
            if not _doc_title:
                dept_text = f"{department} " if department else ""
                _doc_title = f"제38대 {dept_text}학생회 인수인계서 ({target_year})"
            
            logger.info(
                "Starting handover generation",
                target_year=target_year,
                department=department,
                doc_title=_doc_title,
            )
            
            self.update_state(state="PROGRESS", meta={"progress": 5, "step": "Initializing"})
            
            docs_service = GoogleDocsService()
            gemini = GeminiService()
            
            # Step 1: Query events and documents from DB
            self.update_state(state="PROGRESS", meta={"progress": 10, "step": "Querying database"})
            
            events_data = []
            statistics = {
                "total_events": 0,
                "total_meetings": 0,
                "total_documents": 0,
                "events_by_category": {},
                "events_by_status": {},
            }
            
            async with async_session_factory() as db:
                # Query events for target year
                event_query = select(Event).where(Event.year == target_year)
                if department:
                    event_query = event_query.where(Event.category == department)
                
                result = await db.execute(event_query)
                events = result.scalars().all()
                statistics["total_events"] = len(events)
                
                logger.info(f"Found {len(events)} events for year {target_year}")
                
                # Process each event
                for event in events:
                    # Count by category
                    cat = event.category or "기타"
                    statistics["events_by_category"][cat] = statistics["events_by_category"].get(cat, 0) + 1
                    
                    # Count by status
                    stat = event.status or "unknown"
                    statistics["events_by_status"][stat] = statistics["events_by_status"].get(stat, 0) + 1
                    
                    # Get related documents (prioritize: 결과지 > 속기록 > 안건지)
                    doc_query = select(Document).where(Document.event_id == event.id)
                    doc_result = await db.execute(doc_query)
                    docs = doc_result.scalars().all()
                    statistics["total_documents"] += len(docs)
                    
                    # Find best document for summary
                    summary_doc = None
                    for doc in docs:
                        if doc.meeting_subtype == "result":
                            summary_doc = doc
                            break
                        elif doc.meeting_subtype == "transcript" and not summary_doc:
                            summary_doc = doc
                        elif doc.meeting_subtype == "agenda" and not summary_doc:
                            summary_doc = doc
                    
                    events_data.append({
                        "event_id": event.id,
                        "title": event.title,
                        "event_date": event.event_date.isoformat() if event.event_date else "미정",
                        "category": event.category,
                        "status": event.status,
                        "summary": summary_doc.summary if summary_doc and hasattr(summary_doc, 'summary') else "(요약 없음)",
                        "documents_count": len(docs),
                    })
                    
                    if event.category == "회의":
                        statistics["total_meetings"] += 1
            
            self.update_state(state="PROGRESS", meta={"progress": 40, "step": "Generating content"})
            
            # Step 2: Generate handover content with Gemini
            handover_content = gemini.generate_handover_content(
                events_data=events_data,
                year=target_year,
                department=department,
                include_insights=include_insights,
            )
            
            self.update_state(state="PROGRESS", meta={"progress": 70, "step": "Creating document"})
            
            # Step 3: Create Google Doc
            new_doc = docs_service.create_document(_doc_title)
            new_doc_id = new_doc.get("documentId")
            
            logger.info("Created handover document", doc_id=new_doc_id)
            
            # Step 4: Insert content
            self.update_state(state="PROGRESS", meta={"progress": 85, "step": "Writing content"})
            
            docs_service.insert_text(new_doc_id, handover_content)
            
            self.update_state(state="PROGRESS", meta={"progress": 95, "step": "Finalizing"})
            
            result = {
                "status": "SUCCESS",
                "output_doc_id": new_doc_id,
                "output_doc_link": f"https://docs.google.com/document/d/{new_doc_id}/edit",
                "doc_title": _doc_title,
                "target_year": target_year,
                "department": department,
                "statistics": statistics,
                "event_summaries": events_data if include_event_summaries else [],
            }
            
            logger.info(
                "Handover generation completed",
                target_year=target_year,
                output_doc_id=new_doc_id,
                events_processed=len(events_data),
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Handover generation failed",
                error=str(e),
                target_year=target_year,
            )
            return {
                "status": "FAILURE",
                "error": str(e),
                "target_year": target_year,
                "department": department,
            }
    
    return run_async(_process())
