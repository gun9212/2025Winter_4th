"""Chat API endpoint for RAG-powered conversations."""

import re
import time
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import ApiKey, DbSession, RedisClient
from app.models.chat import ChatLog
from app.pipeline.step_07_embed import EmbeddingService
from app.schemas.chat_dto import (
    ChatHistoryItem,
    ChatMetadata,
    ChatRequest,
    ChatResponse,
    SourceReference,
)
from app.services.ai.gemini import GeminiService
from app.services.chat.history_service import HistoryService
from app.services.chat.rewriter_service import QueryRewriterService

logger = structlog.get_logger()

router = APIRouter()

# Google Drive ID pattern: alphanumeric with underscores/hyphens, typically 25-50 chars
# Relaxed pattern for Google Drive IDs (allow a bit more flexibility)
_DRIVE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{15,100}$")


def _build_drive_link(drive_id: str | None) -> str | None:
    """
    Build a Google Drive link if drive_id is valid.
    
    Handles 'local:' prefix if present.
    Returns None if drive_id is missing.
    """
    if not drive_id:
        return None

    # Handle 'local:' prefix (strip it)
    if drive_id.startswith("local:"):
        drive_id = drive_id.replace("local:", "")
        
    # Basic validation: must be reasonably long and alphanumeric
    if len(drive_id) < 15:
        return None
        
    # Try to match pattern, but don't be too strict if it looks like a valid ID string
    # Just checking for clearly invalid characters
    if any(c for c in drive_id if not (c.isalnum() or c in "_-")):
        return None

    return f"https://docs.google.com/document/d/{drive_id}/edit"


async def save_chat_to_db(
    db: Any,
    session_id: str,
    user_level: int,
    user_query: str,
    rewritten_query: str | None,
    ai_response: str,
    retrieved_chunks: list[dict],
    sources: list[dict],
    latency_ms: int,
    retrieval_latency_ms: int | None,
    generation_latency_ms: int | None,
    request_metadata: dict,
) -> None:
    """
    Background task to save chat log to PostgreSQL.

    This runs asynchronously after the response is sent to avoid
    blocking the user.
    """
    try:
        # Get next turn index for this session
        result = await db.execute(
            select(func.coalesce(func.max(ChatLog.turn_index), -1))
            .where(ChatLog.session_id == session_id)
        )
        last_turn = result.scalar()
        next_turn = (last_turn or -1) + 1

        chat_log = ChatLog(
            session_id=session_id,
            user_level=user_level,
            user_query=user_query,
            rewritten_query=rewritten_query,
            ai_response=ai_response,
            retrieved_chunks=retrieved_chunks,
            sources=sources,
            turn_index=next_turn,
            latency_ms=latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=generation_latency_ms,
            request_metadata=request_metadata,
        )

        db.add(chat_log)
        await db.commit()

        logger.info(
            "Chat log saved to DB",
            session_id=session_id[:8],
            turn_index=next_turn,
        )

    except Exception as e:
        logger.error(
            "Failed to save chat log to DB",
            session_id=session_id[:8],
            error=str(e),
        )
        # Don't raise - this is a background task


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="RAG Chat",
    description="""
    Multi-turn RAG chat endpoint with context-aware query rewriting.

    **Processing Flow:**
    1. Retrieve conversation history from Redis (session_id)
    2. Rewrite query using context (Gemini)
    3. Vector search with filters (access_level, year, department)
    4. Generate answer using Parent-Child chunks
    5. Save to Redis (short-term) and DB (long-term, async)

    **Access Levels:**
    - 1: 회장단만 (President/VP only)
    - 2: 국장단까지 (Department heads)
    - 3: 모든 국원 (All council members)
    - 4: 일반 대중 (Public)
    """,
)
async def chat(
    request: ChatRequest,
    db: DbSession,
    redis: RedisClient,
    api_key: ApiKey,
    background_tasks: BackgroundTasks,
) -> ChatResponse:
    """
    Process a RAG chat request.

    Implements the multi-turn conversation flow with:
    - Redis-based session history (TTL 1h)
    - Query rewriting for context
    - Hybrid vector search with time decay
    - Access level filtering
    """
    start_time = time.time()
    timings: dict[str, float] = {}

    logger.info(
        "Chat request received",
        session_id=request.session_id[:8],
        query=request.query[:50],
        user_level=request.user_level,
    )

    try:
        # === Step 1: Session Retrieval ===
        history_service = HistoryService(redis)
        history = await history_service.get_history(
            session_id=request.session_id,
            limit=10,  # Last 10 turns
        )
        formatted_history = history_service.format_for_prompt(history)
        timings["history_retrieval"] = time.time() - start_time

        logger.debug(
            "History retrieved",
            session_id=request.session_id[:8],
            history_turns=len(history) // 2,
        )

        # === Step 2: Query Rewriting ===
        rewrite_start = time.time()
        gemini_service = GeminiService()
        rewriter = QueryRewriterService(gemini_service)

        # Apply rewriting if there's any history (per Decision #2)
        rewritten_query = request.query
        if history:
            rewritten_query = await rewriter.rewrite_query(
                current_query=request.query,
                chat_history=formatted_history,
            )

        timings["query_rewrite"] = time.time() - rewrite_start

        logger.debug(
            "Query processing complete",
            original=request.query[:50],
            rewritten=rewritten_query[:50] if rewritten_query != request.query else "(unchanged)",
        )

        # === Step 3: Vector Search ===
        retrieval_start = time.time()
        embedding_service = EmbeddingService(db)

        # Generate query embedding
        query_embedding = await embedding_service.embed_single(rewritten_query)

        # Determine search parameters
        semantic_weight = request.options.semantic_weight
        time_weight = 1.0 - semantic_weight

        # Perform hybrid search with time decay and keyword matching
        search_results = await embedding_service.search_with_time_decay(
            query_embedding=query_embedding,
            limit=request.options.max_results,
            access_level=request.user_level,
            semantic_weight=request.options.semantic_weight,
            time_weight=(1.0 - request.options.semantic_weight) * 0.3,
            keyword_weight=(1.0 - request.options.semantic_weight) * 0.7,  # Higher keyword importance
            year_filter=request.options.year_filter,
            department_filter=request.options.department_filter,
            query_text=rewritten_query,  # For keyword matching
        )

        retrieval_latency_ms = int((time.time() - retrieval_start) * 1000)
        timings["retrieval"] = time.time() - retrieval_start

        logger.debug(
            "Vector search complete",
            results_count=len(search_results),
            retrieval_latency_ms=retrieval_latency_ms,
        )

        # === Step 4: Answer Generation ===
        generation_start = time.time()

        # Prepare context documents with document names for better attribution
        context_docs = []
        for result in search_results:
            doc_name = result.get('document_name', '알 수 없음')
            drive_name = result.get('drive_name', '')
            content = result.get('parent_content') or result.get('content', '')
            
            # Include both names if different (e.g., 별첨 files)
            if drive_name and drive_name != doc_name:
                header = f"[문서: {doc_name}] [파일: {drive_name}]"
            else:
                header = f"[문서: {doc_name}]"
            
            context_docs.append(f"{header}\n{content}")

        # Generate answer
        answer = gemini_service.generate_answer(
            query=request.query,  # Use original query for natural response
            context=context_docs,
            chat_history=formatted_history if history else None,
        )

        generation_latency_ms = int((time.time() - generation_start) * 1000)
        timings["generation"] = time.time() - generation_start

        logger.debug(
            "Answer generated",
            answer_length=len(answer),
            generation_latency_ms=generation_latency_ms,
        )

        # === Step 5: History Update ===
        # Save to Redis
        await history_service.add_turn(
            session_id=request.session_id,
            user_message=request.query,
            assistant_message=answer,
        )

        # Build source references
        sources: list[SourceReference] = []
        if request.options.include_sources and search_results:
            sources = [
                SourceReference(
                    document_id=result["document_id"],
                    document_title=result.get("document_name", "Unknown"),
                    chunk_id=result["id"],
                    section_header=result.get("section_header"),
                    relevance_score=round(result.get("final_score", result.get("semantic_score", 0)), 4),
                    drive_link=_build_drive_link(result.get("drive_id")),
                    event_title=result.get("inferred_event_title"),
                )
                for result in search_results
            ]

        # Prepare data for DB backup
        retrieved_chunks_for_db = [
            {
                "chunk_id": r["id"],
                "score": round(r.get("final_score", r.get("semantic_score", 0)), 4),
                "section": r.get("section_header"),
            }
            for r in search_results
        ]

        sources_for_db = [
            {
                "doc_id": r["document_id"],
                "title": r.get("document_name", "Unknown"),
                "drive_id": r.get("drive_id"),
            }
            for r in search_results
        ]

        request_metadata = {
            "user_level": request.user_level,
            "max_results": request.options.max_results,
            "semantic_weight": request.options.semantic_weight,
            "year_filter": request.options.year_filter,
            "department_filter": request.options.department_filter,
            "history_turns": len(history) // 2,
        }

        # Calculate total latency
        total_latency_ms = int((time.time() - start_time) * 1000)

        # Schedule DB backup (non-blocking) - Decision #3
        background_tasks.add_task(
            save_chat_to_db,
            db=db,
            session_id=request.session_id,
            user_level=request.user_level,
            user_query=request.query,
            rewritten_query=rewritten_query if rewritten_query != request.query else None,
            ai_response=answer,
            retrieved_chunks=retrieved_chunks_for_db,
            sources=sources_for_db,
            latency_ms=total_latency_ms,
            retrieval_latency_ms=retrieval_latency_ms,
            generation_latency_ms=generation_latency_ms,
            request_metadata=request_metadata,
        )

        logger.info(
            "Chat request completed",
            session_id=request.session_id[:8],
            total_latency_ms=total_latency_ms,
            sources_count=len(sources),
        )

        # === Build Response ===
        return ChatResponse(
            session_id=request.session_id,
            query=request.query,
            rewritten_query=rewritten_query if rewritten_query != request.query else None,
            answer=answer,
            sources=sources,
            metadata=ChatMetadata(
                total_chunks_searched=len(search_results),
                latency_ms=total_latency_ms,
                retrieval_latency_ms=retrieval_latency_ms,
                generation_latency_ms=generation_latency_ms,
                model_used="gemini-flash-latest",
            ),
        )

    except Exception as e:
        logger.error(
            "Chat request failed",
            session_id=request.session_id[:8],
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat processing failed. Please try again later.",
        )


@router.get(
    "/history/{session_id}",
    summary="Get chat history",
    description="Retrieve conversation history for a session from Redis.",
    response_model=dict,
)
async def get_chat_history(
    session_id: str,
    redis: RedisClient,
    api_key: ApiKey,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Get chat history for a session from Redis.

    Args:
        session_id: Unique session identifier.
        limit: Maximum number of turns to retrieve.

    Returns:
        Dictionary containing session info and message history.
    """
    history_service = HistoryService(redis)

    # Get session info
    session_info = await history_service.get_session_info(session_id)

    # Get messages
    messages = await history_service.get_history(session_id, limit=limit)

    return {
        "session_id": session_id,
        "exists": session_info.get("exists", False),
        "turn_count": session_info.get("turn_count", 0),
        "ttl_seconds": session_info.get("ttl_seconds"),
        "history": [
            ChatHistoryItem(
                role=msg.role,
                content=msg.content,
                timestamp=msg.timestamp,
            ).model_dump()
            for msg in messages
        ],
    }


@router.delete(
    "/history/{session_id}",
    summary="Clear chat history",
    description="Clear all conversation history for a session.",
)
async def clear_chat_history(
    session_id: str,
    redis: RedisClient,
    api_key: ApiKey,
) -> dict[str, str]:
    """
    Clear chat history for a session.

    Args:
        session_id: Unique session identifier.

    Returns:
        Confirmation message.
    """
    history_service = HistoryService(redis)
    success = await history_service.clear_history(session_id)

    if success:
        return {
            "status": "success",
            "message": f"History cleared for session {session_id[:8]}...",
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear history",
        )
