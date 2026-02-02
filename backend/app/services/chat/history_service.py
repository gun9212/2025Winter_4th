"""Chat history management service using Redis."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()


# Constants
TTL_SECONDS = 3600  # 1 hour session timeout
MAX_HISTORY_LENGTH = 50  # Maximum turns (50 user + 50 assistant = 100 messages)
KEY_PREFIX = "chat:history:"


@dataclass
class ChatMessage:
    """Single message in chat history."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: str  # ISO format string for JSON serialization

    @classmethod
    def create(cls, role: str, content: str) -> "ChatMessage":
        """Factory method to create a message with current timestamp."""
        return cls(
            role=role,
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def to_json(self) -> str:
        """Serialize message to JSON string."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "ChatMessage":
        """Deserialize message from JSON string."""
        data = json.loads(json_str)
        return cls(**data)


class HistoryService:
    """
    Service for managing chat conversation history in Redis.

    Features:
    - Session-based history storage (Redis List)
    - Automatic TTL management (1 hour)
    - History size limiting (max 50 turns)
    - LLM prompt formatting

    Key Design: chat:history:{session_id}
    Data Structure: Redis List of JSON-encoded ChatMessage objects
    """

    def __init__(self, redis: Redis) -> None:
        """
        Initialize history service.

        Args:
            redis: Async Redis client instance.
        """
        self.redis = redis

    def _get_key(self, session_id: str) -> str:
        """Generate Redis key for session."""
        return f"{KEY_PREFIX}{session_id}"

    async def get_history(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[ChatMessage]:
        """
        Retrieve recent conversation history.

        Args:
            session_id: Unique session identifier.
            limit: Maximum number of turns to retrieve (each turn = 2 messages).

        Returns:
            List of ChatMessage objects in chronological order.
        """
        key = self._get_key(session_id)

        try:
            # Get last N*2 messages (user + assistant pairs)
            messages_json = await self.redis.lrange(key, -(limit * 2), -1)

            if not messages_json:
                return []

            messages = [ChatMessage.from_json(m) for m in messages_json]

            logger.debug(
                "Retrieved chat history",
                session_id=session_id[:8],
                message_count=len(messages),
            )

            return messages

        except Exception as e:
            logger.error(
                "Failed to retrieve chat history",
                session_id=session_id[:8],
                error=str(e),
            )
            return []

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> bool:
        """
        Add a message to conversation history.

        Also refreshes TTL and trims history to max length.

        Args:
            session_id: Unique session identifier.
            role: Message role ("user" or "assistant").
            content: Message content.

        Returns:
            True if successful, False otherwise.
        """
        key = self._get_key(session_id)
        message = ChatMessage.create(role=role, content=content)

        try:
            # Use pipeline for atomic operations
            async with self.redis.pipeline(transaction=True) as pipe:
                # Add message to list
                pipe.rpush(key, message.to_json())

                # Trim to max length (keep last MAX_HISTORY_LENGTH * 2 messages)
                pipe.ltrim(key, -(MAX_HISTORY_LENGTH * 2), -1)

                # Refresh TTL
                pipe.expire(key, TTL_SECONDS)

                await pipe.execute()

            logger.debug(
                "Added message to history",
                session_id=session_id[:8],
                role=role,
                content_length=len(content),
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to add message to history",
                session_id=session_id[:8],
                error=str(e),
            )
            return False

    async def add_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> bool:
        """
        Add a complete conversation turn (user + assistant).

        More efficient than calling add_message twice.

        Args:
            session_id: Unique session identifier.
            user_message: User's query.
            assistant_message: AI's response.

        Returns:
            True if successful, False otherwise.
        """
        key = self._get_key(session_id)
        user_msg = ChatMessage.create(role="user", content=user_message)
        assistant_msg = ChatMessage.create(role="assistant", content=assistant_message)

        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.rpush(key, user_msg.to_json(), assistant_msg.to_json())
                pipe.ltrim(key, -(MAX_HISTORY_LENGTH * 2), -1)
                pipe.expire(key, TTL_SECONDS)
                await pipe.execute()

            logger.debug(
                "Added turn to history",
                session_id=session_id[:8],
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to add turn to history",
                session_id=session_id[:8],
                error=str(e),
            )
            return False

    async def clear_history(self, session_id: str) -> bool:
        """
        Clear all history for a session.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if successful, False otherwise.
        """
        key = self._get_key(session_id)

        try:
            await self.redis.delete(key)
            logger.info("Cleared chat history", session_id=session_id[:8])
            return True

        except Exception as e:
            logger.error(
                "Failed to clear history",
                session_id=session_id[:8],
                error=str(e),
            )
            return False

    async def get_turn_count(self, session_id: str) -> int:
        """
        Get the number of turns in the conversation.

        Args:
            session_id: Unique session identifier.

        Returns:
            Number of turns (message pairs).
        """
        key = self._get_key(session_id)

        try:
            length = await self.redis.llen(key)
            return length // 2  # Each turn = 2 messages

        except Exception as e:
            logger.error(
                "Failed to get turn count",
                session_id=session_id[:8],
                error=str(e),
            )
            return 0

    def format_for_prompt(
        self,
        history: list[ChatMessage],
        max_chars: int = 4000,
    ) -> str:
        """
        Format chat history for LLM prompt injection.

        Args:
            history: List of ChatMessage objects.
            max_chars: Maximum character limit for formatted output.

        Returns:
            Formatted string for LLM prompt, or "(이전 대화 없음)" if empty.
        """
        if not history:
            return "(이전 대화 없음)"

        lines: list[str] = []
        total_chars = 0

        # Process in chronological order
        for msg in history:
            role_label = "사용자" if msg.role == "user" else "AI"
            line = f"{role_label}: {msg.content}"

            # Check character limit
            if total_chars + len(line) > max_chars:
                # Add truncation notice
                lines.insert(0, "... (이전 대화 생략)")
                break

            lines.append(line)
            total_chars += len(line) + 1  # +1 for newline

        return "\n".join(lines)

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """
        Get session metadata.

        Args:
            session_id: Unique session identifier.

        Returns:
            Dictionary with session info (turn_count, ttl_seconds, exists).
        """
        key = self._get_key(session_id)

        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.llen(key)
                pipe.ttl(key)
                pipe.exists(key)
                results = await pipe.execute()

            length, ttl, exists = results

            return {
                "session_id": session_id,
                "exists": bool(exists),
                "turn_count": length // 2 if length else 0,
                "message_count": length or 0,
                "ttl_seconds": ttl if ttl > 0 else None,
            }

        except Exception as e:
            logger.error(
                "Failed to get session info",
                session_id=session_id[:8],
                error=str(e),
            )
            return {
                "session_id": session_id,
                "exists": False,
                "error": str(e),
            }
