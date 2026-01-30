"""Core module for application configuration and utilities."""

from app.core.config import settings
from app.core.database import get_db

__all__ = ["settings", "get_db"]
