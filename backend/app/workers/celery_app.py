"""
Celery Worker — Optional Async Task Queue
Uses Redis as broker/backend.
Falls back to in-process threading if Celery is disabled (USE_CELERY=false).

To run workers:
    celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

To monitor:
    celery -A app.workers.celery_app flower
"""
import logging
import os

logger = logging.getLogger(__name__)

# Lazy import — only initializes if USE_CELERY=true
_celery_app = None


def get_celery_app():
    global _celery_app
    if _celery_app is not None:
        return _celery_app

    try:
        from celery import Celery
        from app.core.config import settings

        _celery_app = Celery(
            "ytdl_worker",
            broker=settings.REDIS_URL,
            backend=settings.REDIS_URL,
        )
        _celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_soft_time_limit=settings.DOWNLOAD_TIMEOUT_SECONDS,
            task_time_limit=settings.DOWNLOAD_TIMEOUT_SECONDS + 30,
            worker_prefetch_multiplier=1,
            task_acks_late=True,
            task_reject_on_worker_lost=True,
            result_expires=3600,
        )

        logger.info("Celery initialized with broker: %s", settings.REDIS_URL)
        return _celery_app

    except ImportError:
        logger.warning("Celery not installed. USE_CELERY should be false.")
        return None


def register_tasks():
    """Register Celery tasks. Call this at worker startup."""
    app = get_celery_app()
    if not app:
        return

    from app.services.downloader import _download_sync
    from app.models.schemas import DownloadFormat

    @app.task(name="ytdl.download", bind=True, max_retries=2)
    def celery_download_task(
        self,
        job_id: str,
        url: str,
        fmt: str,
        mp3_bitrate,
        allowed_mp3_options: list,
        title: str = "audio",
    ):
        try:
            _download_sync(
                job_id=job_id,
                url=url,
                fmt=DownloadFormat(fmt),
                mp3_bitrate=mp3_bitrate,
                allowed_mp3_options=allowed_mp3_options,
                title=title,
            )
        except Exception as exc:
            logger.error("Celery task error: %s", exc, exc_info=True)
            raise self.retry(exc=exc, countdown=10)

    return celery_download_task
