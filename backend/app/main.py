"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.redis import RedisClient

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan events.

    Startup:
    - Initialize database connection pool
    - Initialize Redis connection pool

    Shutdown:
    - Close Redis connections gracefully
    """
    # Startup
    logger.info("Starting Council-AI application...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize Redis
    try:
        await RedisClient.initialize()
        logger.info("Redis initialized")
    except Exception as e:
        logger.warning(
            "Redis initialization failed - chat history will not work",
            error=str(e),
        )

    yield

    # Shutdown
    logger.info("Shutting down Council-AI application...")

    # Close Redis connections
    try:
        await RedisClient.close()
        logger.info("Redis connections closed")
    except Exception as e:
        logger.error("Error closing Redis", error=str(e))

    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="학생회 업무 자동화 및 지식 관리 솔루션",
    version="0.1.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check() -> dict[str, str | dict]:
    """
    Health check endpoint.

    Returns application and dependency health status.
    """
    redis_health = await RedisClient.health_check()

    return {
        "status": "healthy",
        "dependencies": redis_health,
    }


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Council-AI API",
        "docs": "/docs",
        "health": "/health",
    }
