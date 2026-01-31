"""Celery tasks for background processing."""

from app.tasks.celery_app import celery_app
from app.tasks.features import (
    generate_handover,
    generate_minutes,
    sync_calendar,
)
from app.tasks.pipeline import (
    ingest_folder,
    run_full_pipeline,
)

__all__ = [
    "celery_app",
    # Pipeline tasks
    "run_full_pipeline",
    "ingest_folder",
    # Feature tasks
    "generate_minutes",
    "sync_calendar",
    "generate_handover",
]

