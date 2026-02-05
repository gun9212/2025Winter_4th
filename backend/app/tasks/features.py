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
    transcript_doc_id: str,  # v2.1: Google Drive ID from Picker
    template_doc_id: str | None = None,
    meeting_name: str = "Untitled Meeting",
    meeting_date: str | None = None,
    output_folder_id: str | None = None,
    output_doc_id: str | None = None,
    user_email: str | None = None,
    user_level: int = 2,
) -> dict[str, Any]:
    """
    Generate a result document from agenda template and meeting transcript.
    
    v2.1 Smart Minutes Architecture (4-Phase):
    
    Phase 0: DB Lookup by Drive ID
        - Query DB by drive_id (transcript_doc_id from Picker)
        - Validate COMPLETED status
        - If not found → Return error with Admin tab guidance
        
    Phase 1: Template Preparation
        - Copy agenda to create result document
        - Inject placeholders ({report_1_result}, {discuss_1_result}, etc.)
        
    Phase 2: Summarization
        - Split transcript by headers
        - Summarize each section with Gemini
        
    Phase 3: Replacement + Fallback
        - Replace placeholders with summaries
        - Append to document end if placeholder not found
    
    Args:
        agenda_doc_id: Google Docs ID of agenda template (안건지)
        transcript_doc_id: Google Drive ID of transcript (속기록) - from Picker
        template_doc_id: Optional template for result (if None, copies agenda)
        meeting_name: Meeting name for output document
        meeting_date: Meeting date (ISO format)
        output_folder_id: Google Drive folder ID for output
        output_doc_id: Pre-created Google Docs ID for result
        user_email: Email to share the result document with
        
    Returns:
        Task result with output_doc_id and status
    """
    try:
        self.update_state(state="PROGRESS", meta={"progress": 5, "step": "Initializing"})
        
        from app.services.google.docs import GoogleDocsService
        from app.services.ai.gemini import GeminiService
        from app.services.text_utils import split_by_headers, clean_summary_for_docs
        from sqlalchemy import select
        from app.models.document import Document, DocumentStatus
        
        docs_service = GoogleDocsService(use_oauth=True)
        gemini = GeminiService()
        
        logger.info(
            "🚀 [v2.1] Starting Smart Minutes generation",
            meeting_name=meeting_name,
            agenda_doc_id=agenda_doc_id[:8] if agenda_doc_id else None,
            transcript_doc_id=transcript_doc_id[:16] if transcript_doc_id else None,
            user_email=user_email,
        )
        
        # =====================================================================
        # Phase 0: DB Lookup by Drive ID (v2.1)
        # =====================================================================
        self.update_state(state="PROGRESS", meta={"progress": 10, "step": "Phase 0: DB 조회"})
        
        async def _fetch_document_by_drive_id(drive_id: str) -> tuple[str, str, int]:
            """Fetch preprocessed_content from DB by drive_id.
            
            Args:
                drive_id: Google Drive file ID (from Picker)
                
            Returns:
                Tuple of (preprocessed_content, drive_name, document_id)
                
            Raises:
                ValueError: If document not found or not COMPLETED
            """
            async with async_session_factory() as db:
                result = await db.execute(
                    select(Document).where(Document.drive_id == drive_id)
                )
                doc = result.scalar_one_or_none()
                
                if not doc:
                    raise ValueError(
                        f"📛 해당 문서가 RAG 자료학습 되지 않았습니다.\n\n"
                        f"Admin 탭에서 먼저 자료학습을 진행해주세요!"
                    )
                if doc.status != DocumentStatus.COMPLETED:
                    raise ValueError(
                        f"📛 문서 '{doc.drive_name or 'Untitled'}'이(가) 아직 학습 중입니다.\n\n"
                        f"현재 상태: {doc.status.value}\n"
                        f"잠시 후 다시 시도하거나, Admin 탭에서 상태를 확인해주세요."
                    )
                if not doc.preprocessed_content:
                    raise ValueError(
                        f"📛 문서 '{doc.drive_name or 'Untitled'}'의 전처리 내용이 비어있습니다.\n\n"
                        f"Admin 탭에서 재학습을 진행해주세요."
                    )
                    
                logger.info(
                    "✅ Fetched transcript from DB by drive_id",
                    document_id=doc.id,
                    drive_name=doc.drive_name,
                    content_length=len(doc.preprocessed_content),
                )
                return doc.preprocessed_content, doc.drive_name or "Untitled", doc.id
        
        # v2.1: Fetch transcript by drive_id (from Picker)
        transcript_content, transcript_name, transcript_db_id = run_async(
            _fetch_document_by_drive_id(transcript_doc_id)
        )
        
        # Agenda uses Google Docs API directly (not from DB)
        agenda_preprocessed = None
        
        # =====================================================================
        # Phase 1: Template Preparation (Placeholder Injection)
        # =====================================================================
        self.update_state(state="PROGRESS", meta={"progress": 20, "step": "Phase 1: 결과지 생성"})
        
        # Step 1.1: Create result document (copy agenda or use provided output_doc_id)
        source_doc_id = template_doc_id or agenda_doc_id
        result_doc_title = f"[결과지] {meeting_name}"
        
        if output_doc_id:
            # Use pre-created document
            new_doc_id = output_doc_id
            logger.info("Using pre-created result document", doc_id=new_doc_id)
        else:
            # Copy agenda to create new result document
            new_doc = docs_service.copy_document(
                source_doc_id,
                result_doc_title,
                parent_folder_id=output_folder_id,
                share_with_email=user_email
            )
            new_doc_id = new_doc.get("id")
            logger.info("Created result document", doc_id=new_doc_id, folder_id=output_folder_id)
        
        # Step 1.2: Parse agenda to extract placeholder positions
        self.update_state(state="PROGRESS", meta={"progress": 25, "step": "Phase 1: Placeholder 분석"})
        
        # Use agenda preprocessed_content if available, otherwise get from Docs API
        if agenda_preprocessed:
            agenda_sections = split_by_headers(agenda_preprocessed, max_level=2)
        else:
            # Fallback: Get agenda text from Google Docs API
            agenda_text = docs_service.get_document_text(agenda_doc_id)
            agenda_sections = split_by_headers(agenda_text, max_level=2)
        
        # Step 1.3: Inject placeholders into result document
        placeholders_to_inject = []
        for section in agenda_sections:
            if section.header_level == 2 and section.placeholder_key:
                placeholders_to_inject.append({
                    "title": section.title,
                    "placeholder": section.placeholder_key,
                })
        
        logger.info(
            "Analyzed agenda structure",
            total_sections=len(agenda_sections),
            h2_sections=len(placeholders_to_inject),
            placeholders=[p["placeholder"] for p in placeholders_to_inject],
        )
        
        # Inject placeholders after each section title
        for item in placeholders_to_inject:
            result = docs_service.find_text_and_insert_after(
                new_doc_id,
                item["title"],
                f"\n{item['placeholder']}\n"
            )
            if result:
                logger.debug(f"Injected placeholder after '{item['title']}'")
            else:
                logger.warning(f"Could not find title in doc: '{item['title']}'")
        
        # =====================================================================
        # Phase 2: Summarization
        # =====================================================================
        self.update_state(state="PROGRESS", meta={"progress": 35, "step": "Phase 2: 속기록 분석"})
        
        # Split transcript by headers
        transcript_sections = split_by_headers(transcript_content, max_level=2)
        
        logger.info(
            "Split transcript into sections",
            section_count=len(transcript_sections),
            h2_count=len([s for s in transcript_sections if s.header_level == 2]),
        )
        
        # Summarize each H2 section
        summaries = []
        agenda_summaries = []
        h2_sections = [s for s in transcript_sections if s.header_level == 2]
        total_h2 = len(h2_sections)
        
        for i, section in enumerate(h2_sections):
            progress = 35 + int((i / max(total_h2, 1)) * 35)  # 35-70%
            self.update_state(
                state="PROGRESS",
                meta={"progress": progress, "step": f"Phase 2: 요약 중 ({i+1}/{total_h2})"}
            )
            
            agenda_type = section.agenda_type or "other"
            placeholder_key = section.placeholder_key
            
            result = gemini.summarize_agenda_section(
                section_content=section.content,
                section_title=section.title,
                agenda_type=agenda_type,
            )
            
            # Apply markdown cleaning for Google Docs insertion
            summary_text = clean_summary_for_docs(result)
            
            summaries.append({
                "placeholder_key": placeholder_key,
                "title": section.title,
                "summary": summary_text,
            })
            
            agenda_summaries.append({
                "agenda_type": agenda_type,
                "agenda_number": section.agenda_number,
                "title": section.title,
                "summary": summary_text,
                "has_decision": result.get("has_decision", False),
                "action_items": result.get("action_items", []),
            })
            
            logger.debug(
                "Summarized section",
                title=section.title[:30],
                placeholder=placeholder_key,
                summary_preview=summary_text[:50],
            )
        
        # =====================================================================
        # Phase 3: Replacement + Fallback
        # =====================================================================
        self.update_state(state="PROGRESS", meta={"progress": 75, "step": "Phase 3: 결과지 작성"})
        
        # Build replacement map
        replacements = {}
        for item in summaries:
            if item["placeholder_key"]:
                replacements[item["placeholder_key"]] = item["summary"]
        
        logger.info(
            "Prepared replacements",
            count=len(replacements),
            keys=list(replacements.keys()),
        )
        
        # Execute replacements with count tracking
        if replacements:
            response, counts = docs_service.replace_text_with_count(new_doc_id, replacements)
            
            # Check for failed replacements (0 occurrences changed)
            failed_placeholders = []
            for placeholder, count in counts.items():
                if count == 0:
                    failed_placeholders.append(placeholder)
            
            if failed_placeholders:
                logger.warning(
                    "Some placeholders not found, applying fallback",
                    failed=failed_placeholders,
                )
                
                # Fallback: Append to document end
                self.update_state(state="PROGRESS", meta={"progress": 85, "step": "Phase 3: Fallback 처리"})
                
                fallback_text = "\n\n---\n## 📋 누락된 요약\n"
                for placeholder in failed_placeholders:
                    summary = replacements.get(placeholder, "")
                    # Find title from summaries
                    title = "Unknown"
                    for item in summaries:
                        if item["placeholder_key"] == placeholder:
                            title = item["title"]
                            break
                    fallback_text += f"\n### {title}\n{summary}\n"
                
                docs_service.append_text(new_doc_id, fallback_text)
                logger.info("Appended fallback content to document end")
            
            logger.info(
                "Replacement complete",
                successful=len(replacements) - len(failed_placeholders),
                fallback=len(failed_placeholders),
            )
        
        # =====================================================================
        # Finalize
        # =====================================================================
        self.update_state(state="PROGRESS", meta={"progress": 95, "step": "완료 처리"})
        
        decisions_count = sum(1 for s in agenda_summaries if s.get("has_decision"))
        action_items_count = sum(len(s.get("action_items", [])) for s in agenda_summaries)
        
        result = {
            "status": "SUCCESS",
            "output_doc_id": new_doc_id,
            "output_doc_link": f"https://docs.google.com/document/d/{new_doc_id}/edit",
            "meeting_name": meeting_name,
            "agenda_summaries": agenda_summaries,
            "items_processed": len(h2_sections),
            "decisions_extracted": decisions_count,
            "action_items_extracted": action_items_count,
            "placeholders_injected": len(placeholders_to_inject),
            "fallback_applied": len(failed_placeholders) if 'failed_placeholders' in dir() else 0,
        }
        
        logger.info(
            "🎉 Smart Minutes v2.0 generation completed",
            meeting_name=meeting_name,
            output_doc_id=new_doc_id,
            sections=len(h2_sections),
            decisions=decisions_count,
        )
        
        return result
        
    except ValueError as e:
        # User-friendly errors (RAG validation failures)
        logger.warning(
            "Smart Minutes validation failed",
            error=str(e),
        )
        return {
            "status": "FAILURE",
            "error": str(e),
            "meeting_name": meeting_name,
            "error_type": "VALIDATION",
        }
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
            "error_type": "SYSTEM",
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
    department: str | None = None,  # Deprecated, kept for API compatibility
    target_folder_id: str | None = None,
    doc_title: str | None = None,
    include_event_summaries: bool = True,
    include_insights: bool = True,
    include_statistics: bool = True,
) -> dict[str, Any]:
    """
    Generate a comprehensive handover document for a specific year.
    
    v2.0 Refactored Logic:
    1. Query ALL Events for target_year (no department filter)
    2. For each Event, aggregate preprocessed_content from related Documents
    3. Use Gemini to generate deep insights per event
    4. Compile into final handover document
    
    Args:
        target_year: Year to generate handover for
        department: DEPRECATED - Ignored for backward compatibility
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
            
            # Generate title (ignore department)
            _doc_title = doc_title or f"제38대 학생회 인수인계서 ({target_year})"
            
            logger.info(
                "🚀 Starting handover generation (v2.0 - Event-Centric)",
                target_year=target_year,
                doc_title=_doc_title,
            )
            
            self.update_state(state="PROGRESS", meta={"progress": 5, "step": "초기화"})
            
            docs_service = GoogleDocsService()
            gemini = GeminiService()
            
            # =====================================================================
            # Step 1: Query Events by year only (no department filter)
            # =====================================================================
            self.update_state(state="PROGRESS", meta={"progress": 10, "step": "이벤트 조회"})
            
            events_data = []
            statistics = {
                "total_events": 0,
                "total_documents": 0,
                "events_by_category": {},
                "events_by_status": {},
            }
            
            async with async_session_factory() as db:
                # Query all events for target year
                event_query = select(Event).where(Event.year == target_year)
                result = await db.execute(event_query)
                events = result.scalars().all()
                statistics["total_events"] = len(events)
                
                logger.info(f"Found {len(events)} events for year {target_year}")
                
                if not events:
                    logger.warning("No events found for target year")
                
                # =====================================================================
                # Step 2: For each Event, aggregate Document content
                # =====================================================================
                total_events = len(events)
                for i, event in enumerate(events):
                    progress = 10 + int((i / max(total_events, 1)) * 50)  # 10-60%
                    self.update_state(
                        state="PROGRESS",
                        meta={"progress": progress, "step": f"문서 분석 ({i+1}/{total_events})"}
                    )
                    
                    # Count by category
                    cat = event.category or "기타"
                    statistics["events_by_category"][cat] = statistics["events_by_category"].get(cat, 0) + 1
                    
                    # Count by status
                    stat = str(event.status.value) if event.status else "unknown"
                    statistics["events_by_status"][stat] = statistics["events_by_status"].get(stat, 0) + 1
                    
                    # Query related documents
                    doc_query = select(Document).where(Document.event_id == event.id)
                    doc_result = await db.execute(doc_query)
                    docs = doc_result.scalars().all()
                    statistics["total_documents"] += len(docs)
                    
                    # Aggregate preprocessed_content (limit per doc to prevent overflow)
                    context_parts = []
                    for doc in docs:
                        if doc.preprocessed_content:
                            # Limit each document to 4000 chars to prevent context overflow
                            context_parts.append(doc.preprocessed_content[:4000])
                    
                    event_context = "\n\n---\n\n".join(context_parts) if context_parts else ""
                    
                    # =====================================================================
                    # Step 3: Generate insight per event
                    # =====================================================================
                    insight = {}
                    if include_insights and event_context:
                        insight = gemini.generate_handover_insight(
                            event_title=event.title,
                            event_content=event_context,
                        )
                        logger.debug(
                            "Generated insight for event",
                            event_id=event.id,
                            event_title=event.title[:30],
                        )
                    
                    events_data.append({
                        "event_id": event.id,
                        "title": event.title,
                        "event_date": event.event_date.isoformat() if event.event_date else "미정",
                        "category": event.category,
                        "status": stat,
                        "documents_count": len(docs),
                        # Deep analysis results
                        "overview": insight.get("overview", "(분석 없음)"),
                        "key_decisions": insight.get("key_decisions", []),
                        "success_points": insight.get("success_points", []),
                        "improvement_points": insight.get("improvement_points", []),
                        "next_year_advice": insight.get("next_year_advice", ""),
                    })
            
            # =====================================================================
            # Step 4: Generate final handover document
            # =====================================================================
            self.update_state(state="PROGRESS", meta={"progress": 65, "step": "인수인계서 생성"})
            
            handover_content = gemini.generate_handover_content(
                events_data=events_data,
                year=target_year,
                department=None,  # Ignore department
                include_insights=include_insights,
            )
            
            self.update_state(state="PROGRESS", meta={"progress": 80, "step": "문서 작성"})
            
            # Create Google Doc
            new_doc = docs_service.create_document(_doc_title)
            new_doc_id = new_doc.get("documentId")
            
            logger.info("Created handover document", doc_id=new_doc_id)
            
            # Insert content
            self.update_state(state="PROGRESS", meta={"progress": 90, "step": "내용 삽입"})
            
            docs_service.insert_text(new_doc_id, handover_content)
            
            self.update_state(state="PROGRESS", meta={"progress": 95, "step": "완료"})
            
            result = {
                "status": "SUCCESS",
                "output_doc_id": new_doc_id,
                "output_doc_link": f"https://docs.google.com/document/d/{new_doc_id}/edit",
                "doc_title": _doc_title,
                "target_year": target_year,
                "department": None,  # Deprecated
                "statistics": statistics,
                "event_summaries": events_data if include_event_summaries else [],
            }
            
            logger.info(
                "🎉 Handover generation completed (v2.0)",
                target_year=target_year,
                output_doc_id=new_doc_id,
                events_processed=len(events_data),
                total_docs_analyzed=statistics["total_documents"],
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
                "department": None,
            }
    
    return run_async(_process())

