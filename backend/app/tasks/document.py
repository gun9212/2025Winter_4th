"""Document processing Celery tasks."""

import asyncio
from typing import Any

from celery import shared_task

from app.core.database import async_session_factory
from app.services.rag.pipeline import RAGPipeline


def run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@shared_task(bind=True, name="app.tasks.document.ingest_folder")
def ingest_folder(
    self,
    folder_id: str,
    recursive: bool = True,
) -> dict[str, Any]:
    """
    Ingest documents from a Google Drive folder.

    Args:
        folder_id: Google Drive folder ID.
        recursive: Whether to process subfolders.

    Returns:
        Task result with document IDs.
    """

    async def _ingest():
        async with async_session_factory() as db:
            pipeline = RAGPipeline(db)
            document_ids = await pipeline.ingest_folder(folder_id, recursive)
            return document_ids

    try:
        document_ids = run_async(_ingest())
        return {
            "status": "success",
            "folder_id": folder_id,
            "documents_processed": len(document_ids),
            "document_ids": document_ids,
        }
    except Exception as e:
        return {
            "status": "error",
            "folder_id": folder_id,
            "error": str(e),
        }


@shared_task(bind=True, name="app.tasks.document.process_document")
def process_document(
    self,
    drive_id: str,
    drive_name: str,
    mime_type: str | None = None,
) -> dict[str, Any]:
    """
    Process a single document.

    Args:
        drive_id: Google Drive file ID.
        drive_name: File name.
        mime_type: File MIME type.

    Returns:
        Task result with document ID.
    """

    async def _process():
        async with async_session_factory() as db:
            pipeline = RAGPipeline(db)
            doc_id = await pipeline.ingest_document(drive_id, drive_name, mime_type)
            return doc_id

    try:
        document_id = run_async(_process())
        return {
            "status": "success",
            "drive_id": drive_id,
            "document_id": document_id,
        }
    except Exception as e:
        return {
            "status": "error",
            "drive_id": drive_id,
            "error": str(e),
        }


@shared_task(bind=True, name="app.tasks.document.process_minutes")
def process_minutes(
    self,
    agenda_doc_id: str,
    transcript: str,
    output_folder_id: str | None = None,
) -> dict[str, Any]:
    """
    Process meeting minutes from agenda and transcript.

    Args:
        agenda_doc_id: Google Docs ID of agenda template.
        transcript: Meeting transcript text.
        output_folder_id: Optional folder for output document.

    Returns:
        Task result with result document ID.
    """
    from app.services.ai.gemini import GeminiService
    from app.services.google.docs import GoogleDocsService

    try:
        docs_service = GoogleDocsService()
        gemini_service = GeminiService()

        # Get agenda content
        agenda_text = docs_service.get_document_text(agenda_doc_id)

        # Analyze transcript
        analysis = gemini_service.analyze_transcript(transcript, agenda_text)

        # Create result document from template copy
        result_doc = docs_service.copy_document(
            agenda_doc_id,
            f"회의 결과 - {analysis.get('summary', '')[:30]}",
        )
        result_doc_id = result_doc["id"]

        # Replace placeholders
        replacements = {
            "{요약}": analysis.get("summary", ""),
            "{결정사항}": "\n".join(
                f"- {d['topic']}: {d['decision']}"
                for d in analysis.get("decisions", [])
            ),
            "{액션아이템}": "\n".join(
                f"- {a['task']} (담당: {a.get('assignee', '미정')})"
                for a in analysis.get("action_items", [])
            ),
        }
        docs_service.replace_text(result_doc_id, replacements)

        return {
            "status": "success",
            "result_doc_id": result_doc_id,
            "result_url": f"https://docs.google.com/document/d/{result_doc_id}/edit",
            "summary": analysis.get("summary"),
            "decisions_count": len(analysis.get("decisions", [])),
            "action_items_count": len(analysis.get("action_items", [])),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }
