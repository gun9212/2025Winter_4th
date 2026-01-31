"""API v1 router that combines all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.calendar_control import router as calendar_router
from app.api.v1.chat_control import router as chat_router
from app.api.v1.handover_control import router as handover_router
from app.api.v1.minutes_control import router as minutes_router
from app.api.v1.rag_control import router as rag_router
from app.api.v1.tasks_control import router as tasks_router

api_router = APIRouter()

# Chat endpoint (RAG with multi-turn conversation)
api_router.include_router(
    chat_router,
    prefix="/chat",
    tags=["chat"],
)

# Minutes (Smart Minutes - result document generation)
api_router.include_router(
    minutes_router,
    prefix="/minutes",
    tags=["minutes"],
)

# RAG (document ingestion and search)
api_router.include_router(
    rag_router,
    prefix="/rag",
    tags=["rag"],
)

# Calendar (event management and sync)
api_router.include_router(
    calendar_router,
    prefix="/calendar",
    tags=["calendar"],
)

# Handover (handover document generation)
api_router.include_router(
    handover_router,
    prefix="/handover",
    tags=["handover"],
)

# Tasks (Celery task status tracking)
api_router.include_router(
    tasks_router,
    prefix="/tasks",
    tags=["tasks"],
)

