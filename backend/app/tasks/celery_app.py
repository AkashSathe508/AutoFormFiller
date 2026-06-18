"""Celery application configuration."""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "autoformfiller",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.form_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_soft_time_limit=300,  # 5 min soft limit
    task_time_limit=600,       # 10 min hard limit
    task_acks_late=True,       # Don't ack until task completes
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # One task at a time per worker
    task_routes={
        "app.tasks.document_tasks.*": {"queue": "documents"},
        "app.tasks.form_tasks.*": {"queue": "forms"},
    },
    beat_schedule={
        "cleanup-expired-otps": {
            "task": "app.tasks.document_tasks.cleanup_expired_otps",
            "schedule": 3600.0,  # Every hour
        },
    },
)
