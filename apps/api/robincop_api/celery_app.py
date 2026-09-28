from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from .config import settings


celery_app = Celery(
    "robincop",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["robincop_api.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=30 * 60,
    worker_prefetch_multiplier=1,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    result_expires=3600,
    broker_transport_options={"visibility_timeout": 7200},
    timezone="UTC",
    task_routes={
        "robincop.analyze": {"queue": "analysis"},
        "robincop.analyze_serial": {"queue": "serial_analysis"},
        "robincop.discover": {"queue": "collection"},
        "robincop.discover_due": {"queue": "collection"},
        "robincop.refill_analysis_queue": {"queue": "collection"},
        "robincop.recover_stale_analysis": {"queue": "collection"},
        "robincop.recompute_due": {"queue": "collection"},
        "robincop.prune_history": {"queue": "collection"},
    },
    beat_schedule={
        "check-realtime-collection-due": {
            "task": "robincop.discover_due",
            "schedule": 60,
        },
        "recover-interrupted-analysis": {
            "task": "robincop.recover_stale_analysis",
            "schedule": 5 * 60,
        },
        "keep-analysis-queue-moving": {
            "task": "robincop.refill_analysis_queue",
            "schedule": 60,
        },
        "recompute-due-wallets-daily": {
            "task": "robincop.recompute_due",
            "schedule": crontab(hour=0, minute=15),
        },
        "prune-operational-history-daily": {
            "task": "robincop.prune_history",
            "schedule": crontab(hour=0, minute=45),
        },
    },
)
