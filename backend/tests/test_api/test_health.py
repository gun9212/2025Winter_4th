"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health check endpoint returns healthy status."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test root endpoint returns API info."""
    response = await client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "Council-AI" in data["message"]
    assert "docs" in data
    assert "health" in data


def test_health_check_sync(sync_client):
    """Test health check with synchronous client."""
    response = sync_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
