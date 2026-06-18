"""Celery application instance for AutoFormFiller background tasks."""

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "autoformfiller",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.ocr",
        "app.tasks.form_parser",
        "app.tasks.prefill",
        "app.tasks.submit",
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
    worker_prefetch_multiplier=1,  # Fair task distribution
    task_routes={
        "app.tasks.ocr.*": {"queue": "ocr"},
        "app.tasks.form_parser.*": {"queue": "parsing"},
        "app.tasks.prefill.*": {"queue": "prefill"},
        "app.tasks.submit.*": {"queue": "submit"},
    },
    beat_schedule={},
)
