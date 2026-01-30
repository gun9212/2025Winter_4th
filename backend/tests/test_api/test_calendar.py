"""Tests for calendar API endpoints."""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.fixture
def sample_event_request() -> dict:
    """Sample calendar event request."""
    now = datetime.now()
    return {
        "title": "테스트 회의",
        "start_time": (now + timedelta(days=1)).isoformat(),
        "end_time": (now + timedelta(days=1, hours=1)).isoformat(),
        "description": "테스트 회의입니다.",
        "attendees": ["test@example.com"],
        "location": "회의실 A",
    }


@pytest.mark.asyncio
async def test_create_event(client: AsyncClient, sample_event_request):
    """Test event creation endpoint."""
    response = await client.post(
        "/api/v1/calendar/events",
        json=sample_event_request,
    )

    assert response.status_code == 201
    data = response.json()
    assert "event_id" in data
    assert data["title"] == sample_event_request["title"]


@pytest.mark.asyncio
async def test_create_event_missing_required(client: AsyncClient):
    """Test event creation with missing required fields."""
    response = await client.post(
        "/api/v1/calendar/events",
        json={"title": "Only title"},  # Missing start_time and end_time
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_event_invalid_time_range(client: AsyncClient):
    """Test event creation with end_time before start_time."""
    now = datetime.now()
    response = await client.post(
        "/api/v1/calendar/events",
        json={
            "title": "Invalid Event",
            "start_time": (now + timedelta(hours=2)).isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),  # Before start
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_events(client: AsyncClient):
    """Test event list endpoint."""
    response = await client.get("/api/v1/calendar/events")

    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "events" in data
    assert isinstance(data["events"], list)


@pytest.mark.asyncio
async def test_get_event_not_found(client: AsyncClient):
    """Test getting non-existent event."""
    response = await client.get("/api/v1/calendar/events/nonexistent_id")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_event_not_found(client: AsyncClient):
    """Test deleting non-existent event."""
    response = await client.delete("/api/v1/calendar/events/nonexistent_id")

    assert response.status_code == 404
