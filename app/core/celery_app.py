from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "kreis",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.task_routes = {
    "app.tasks.*": {"queue": "default"},
}

# Nightly rollup of the previous day's attendance into monthly aggregates.
celery_app.conf.beat_schedule = {
    "update-attendance-rollups": {
        "task": "app.tasks.update_attendance_rollups",
        "schedule": crontab(hour=1, minute=0),  # 1:00 AM every night
    }
}
