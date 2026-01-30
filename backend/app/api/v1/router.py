"""API v1 router that combines all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.calendar import router as calendar_router
from app.api.v1.minutes import router as minutes_router
from app.api.v1.rag import router as rag_router

api_router = APIRouter()

api_router.include_router(
    minutes_router,
    prefix="/minutes",
    tags=["minutes"],
)

api_router.include_router(
    rag_router,
    prefix="/rag",
    tags=["rag"],
)

api_router.include_router(
    calendar_router,
    prefix="/calendar",
    tags=["calendar"],
)
