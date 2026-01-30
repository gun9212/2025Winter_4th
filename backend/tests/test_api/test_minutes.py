"""Tests for minutes API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_process_minutes(client: AsyncClient, sample_minutes_request):
    """Test minutes processing endpoint."""
    response = await client.post(
        "/api/v1/minutes/process",
        json=sample_minutes_request,
    )

    assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"
    assert "message" in data


@pytest.mark.asyncio
async def test_process_minutes_missing_required_fields(client: AsyncClient):
    """Test minutes processing with missing required fields."""
    response = await client.post(
        "/api/v1/minutes/process",
        json={"agenda_doc_id": "test_id"},  # Missing transcript
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_minutes_status(client: AsyncClient):
    """Test getting minutes processing status."""
    response = await client.get("/api/v1/minutes/test_doc_id/status")

    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert "status" in data
    assert "progress" in data
