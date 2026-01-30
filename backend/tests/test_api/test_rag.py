"""Tests for RAG API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ingest_documents(client: AsyncClient):
    """Test document ingestion endpoint."""
    response = await client.post(
        "/api/v1/rag/ingest",
        json={
            "folder_id": "test_folder_id",
            "recursive": True,
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
    assert "message" in data
    assert "documents_found" in data


@pytest.mark.asyncio
async def test_search_documents(client: AsyncClient, sample_search_request):
    """Test document search endpoint."""
    response = await client.post(
        "/api/v1/rag/search",
        json=sample_search_request,
    )

    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert data["query"] == sample_search_request["query"]
    assert "results" in data
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_search_documents_minimal(client: AsyncClient):
    """Test search with minimal parameters."""
    response = await client.post(
        "/api/v1/rag/search",
        json={"query": "테스트 검색어"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "테스트 검색어"


@pytest.mark.asyncio
async def test_list_documents(client: AsyncClient):
    """Test document list endpoint."""
    response = await client.get("/api/v1/rag/documents")

    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "documents" in data
    assert "skip" in data
    assert "limit" in data


@pytest.mark.asyncio
async def test_list_documents_with_pagination(client: AsyncClient):
    """Test document list with pagination parameters."""
    response = await client.get(
        "/api/v1/rag/documents",
        params={"skip": 10, "limit": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["skip"] == 10
    assert data["limit"] == 5
