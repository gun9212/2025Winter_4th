"""Redis client management for session storage and caching."""

from typing import AsyncGenerator

import structlog
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = structlog.get_logger()


class RedisClient:
    """
    Redis client manager with connection pooling.

    Provides async Redis connections for:
    - Chat session history (TTL-based)
    - Caching (future use)

    Usage:
        # In FastAPI lifespan
        await RedisClient.initialize()

        # In endpoint via dependency injection
        redis = await get_redis()
        await redis.set("key", "value")

        # On shutdown
        await RedisClient.close()
    """

    _pool: ConnectionPool | None = None
    _client: Redis | None = None

    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize Redis connection pool.

        Should be called during application startup.
        """
        if cls._pool is not None:
            logger.warning("Redis pool already initialized")
            return

        try:
            cls._pool = ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=20,
                decode_responses=True,  # Auto-decode bytes to str
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )

            # Create a shared client instance
            cls._client = Redis(connection_pool=cls._pool)

            # Test connection
            await cls._client.ping()

            logger.info(
                "Redis connection pool initialized",
                url=settings.REDIS_URL.split("@")[-1],  # Hide credentials
                max_connections=20,
            )
        except Exception as e:
            logger.error("Failed to initialize Redis", error=str(e))
            raise

    @classmethod
    async def get_client(cls) -> Redis:
        """
        Get Redis client instance.

        Returns:
            Async Redis client.

        Raises:
            RuntimeError: If Redis is not initialized.
        """
        if cls._client is None:
            raise RuntimeError(
                "Redis not initialized. Call RedisClient.initialize() first."
            )
        return cls._client

    @classmethod
    async def close(cls) -> None:
        """
        Close Redis connections gracefully.

        Should be called during application shutdown.
        """
        if cls._client is not None:
            await cls._client.close()
            cls._client = None
            logger.info("Redis client closed")

        if cls._pool is not None:
            await cls._pool.disconnect()
            cls._pool = None
            logger.info("Redis connection pool closed")

    @classmethod
    async def health_check(cls) -> dict[str, str]:
        """
        Check Redis connection health.

        Returns:
            Health status dictionary.
        """
        try:
            if cls._client is None:
                return {"redis": "not_initialized"}

            await cls._client.ping()
            info = await cls._client.info("server")
            return {
                "redis": "healthy",
                "version": info.get("redis_version", "unknown"),
            }
        except Exception as e:
            return {"redis": "unhealthy", "error": str(e)}


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    FastAPI dependency for Redis client.

    Yields:
        Async Redis client instance.

    Example:
        @router.get("/")
        async def endpoint(redis: Redis = Depends(get_redis)):
            await redis.get("key")
    """
    client = await RedisClient.get_client()
    yield client
