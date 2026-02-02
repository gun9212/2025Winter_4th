"""API dependencies for dependency injection."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import google_auth

# Database session dependency
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Redis client dependency
RedisClient = Annotated[Redis, Depends(get_redis)]

# API Key header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Depends(api_key_header)]
) -> str:
    """
    Verify API key from request header.

    Args:
        api_key: API key from X-API-Key header.

    Returns:
        The validated API key.

    Raises:
        HTTPException: If API key is missing or invalid.
    """
    if settings.DEBUG:
        # Skip API key verification in debug mode
        return api_key or "debug"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key",
        )

    if api_key != settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key


ApiKey = Annotated[str, Depends(verify_api_key)]


def get_google_auth():
    """Get Google authentication handler."""
    return google_auth


GoogleAuth = Annotated[type(google_auth), Depends(get_google_auth)]
