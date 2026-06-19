"""Celery application instance for AutoFormFiller background tasks."""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "autoformfiller",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.form_parser",
        "app.tasks.prefill",
        "app.tasks.document_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_soft_time_limit=300,  # 5 min soft limit
    task_time_limit=600,       # 10 min hard limit
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # Fair task distribution
    task_routes={
        "app.tasks.form_parser.*": {"queue": "parsing"},
        "app.tasks.prefill.*": {"queue": "prefill"},
        "app.tasks.document_tasks.*": {"queue": "documents"},
    },
    beat_schedule={
        "cleanup-expired-otps": {
            "task": "app.tasks.document_tasks.cleanup_expired_otps",
            "schedule": 3600.0,  # Every hour
        },
    },
)
