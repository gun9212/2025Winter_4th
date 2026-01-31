"""Unit tests for Event model CRUD operations."""

import pytest
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event, EventStatus


@pytest.mark.asyncio
async def test_create_event(db_session: AsyncSession):
    """Test creating an Event."""
    event = Event(
        title="2025 새내기 배움터",
        year=2025,
        event_date=date(2025, 2, 25),
        category="복지국",
        status=EventStatus.PLANNED,
        description="2025학년도 새내기 배움터 행사",
    )
    db_session.add(event)
    await db_session.flush()
    
    assert event.id is not None
    assert event.title == "2025 새내기 배움터"
    assert event.year == 2025
    assert event.status == EventStatus.PLANNED


@pytest.mark.asyncio
async def test_event_chunk_timeline(db_session: AsyncSession):
    """Test Event's chunk timeline functionality."""
    event = Event(
        title="제38대 축제",
        year=2024,
    )
    db_session.add(event)
    await db_session.flush()
    
    # Add chunks to timeline
    event.add_chunk_to_timeline("2차 국장단 회의", 101)
    event.add_chunk_to_timeline("2차 국장단 회의", 102, "축제 가수 섭외 완료")
    event.add_chunk_to_timeline("3차 회의", 103)
    
    assert event.chunk_timeline == {
        "2차 국장단 회의": [101, 102],
        "3차 회의": [103],
    }
    assert event.decisions_summary == {
        "2차 국장단 회의": ["축제 가수 섭외 완료"],
    }


@pytest.mark.asyncio
async def test_event_status_transitions(db_session: AsyncSession):
    """Test Event status transitions."""
    event = Event(
        title="2024 간식행사",
        year=2024,
        status=EventStatus.PLANNED,
    )
    db_session.add(event)
    await db_session.flush()
    
    # Transition to in_progress
    event.status = EventStatus.IN_PROGRESS
    await db_session.flush()
    assert event.status == EventStatus.IN_PROGRESS
    
    # Transition to completed
    event.status = EventStatus.COMPLETED
    await db_session.flush()
    assert event.status == EventStatus.COMPLETED


@pytest.mark.asyncio
async def test_event_parent_chunk_ids(db_session: AsyncSession):
    """Test Event's parent_chunk_ids array."""
    event = Event(
        title="Test Event",
        year=2024,
        parent_chunk_ids=[1, 2, 3],
    )
    db_session.add(event)
    await db_session.flush()
    
    assert event.parent_chunk_ids == [1, 2, 3]
    
    # Add more chunk IDs
    event.parent_chunk_ids.extend([4, 5])
    event.parent_chunk_ids = list(set(event.parent_chunk_ids))  # Dedupe
    await db_session.flush()
    
    assert set(event.parent_chunk_ids) == {1, 2, 3, 4, 5}
