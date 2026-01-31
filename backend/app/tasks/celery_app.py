"""Celery application configuration."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "council_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.document", "app.tasks.pipeline"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result settings
    result_expires=3600,  # 1 hour
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    # Task routing
    task_routes={
        "app.tasks.document.*": {"queue": "document"},
        "app.tasks.pipeline.*": {"queue": "pipeline"},
    },
    # Task annotations
    task_annotations={
        "app.tasks.document.process_document": {
            "rate_limit": "10/m",  # Max 10 documents per minute
        },
        "app.tasks.pipeline.run_full_pipeline": {
            "rate_limit": "5/m",  # Max 5 pipeline runs per minute (API limits)
        },
    },
)

