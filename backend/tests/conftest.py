"""Pytest fixtures for testing."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base


# Test database URL (use a separate test database)
TEST_DATABASE_URL = settings.DATABASE_URL.replace(
    "/council_ai", "/council_ai_test"
)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        poolclass=NullPool,
        echo=False,
    )

    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create tables
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        # Drop all tables after tests
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for each test."""
    async_session = sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        # Rollback any changes made during the test
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client with database override."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sync_client() -> Generator[TestClient, None, None]:
    """Create synchronous test client for simple tests."""
    with TestClient(app) as c:
        yield c


# Mock fixtures for external services


@pytest.fixture
def mock_google_credentials(mocker):
    """Mock Google credentials."""
    mock_creds = mocker.MagicMock()
    mock_creds.expired = False
    mock_creds.token = "mock_token"

    mocker.patch(
        "app.core.security.get_google_credentials",
        return_value=mock_creds,
    )
    return mock_creds


@pytest.fixture
def mock_gemini_service(mocker):
    """Mock Gemini AI service."""
    mock = mocker.patch("app.services.ai.gemini.GeminiService")
    instance = mock.return_value
    instance.generate_text.return_value = "Mock response"
    instance.caption_image.return_value = "Mock image caption"
    instance.analyze_transcript.return_value = {
        "summary": "Mock summary",
        "decisions": [],
        "action_items": [],
    }
    return instance


@pytest.fixture
def mock_embedding_service(mocker):
    """Mock embedding service."""
    mock = mocker.patch("app.services.ai.embeddings.EmbeddingService")
    instance = mock.return_value
    # Return a 768-dimensional zero vector
    instance.embed_text.return_value = [0.0] * 768
    instance.embed_query.return_value = [0.0] * 768
    return instance


@pytest.fixture
def mock_drive_service(mocker):
    """Mock Google Drive service."""
    mock = mocker.patch("app.services.google.drive.GoogleDriveService")
    instance = mock.return_value
    instance.list_files.return_value = []
    instance.download_file.return_value = b"mock content"
    return instance


@pytest.fixture
def sample_document_data() -> dict[str, Any]:
    """Sample document data for testing."""
    return {
        "drive_id": "test_drive_id_123",
        "drive_name": "Test Document.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


@pytest.fixture
def sample_minutes_request() -> dict[str, Any]:
    """Sample minutes processing request."""
    return {
        "agenda_doc_id": "test_agenda_doc_id",
        "transcript": "회의 시작합니다. 첫 번째 안건은 예산 승인입니다. 100만원 예산을 승인합니다.",
        "meeting_date": "2024-01-15",
        "attendees": ["홍길동", "김철수", "이영희"],
    }


@pytest.fixture
def sample_search_request() -> dict[str, Any]:
    """Sample RAG search request."""
    return {
        "query": "학생회 예산 승인 절차는?",
        "top_k": 5,
        "include_context": True,
        "generate_answer": True,
    }
