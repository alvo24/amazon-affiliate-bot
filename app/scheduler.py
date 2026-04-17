"""Background scheduler that triggers posting runs on a cron schedule."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_effective_settings
from app.service import run_once

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _job() -> None:
    try:
        await run_once()
    except Exception:
        logger.exception("Scheduled run failed")


def start_scheduler() -> AsyncIOScheduler:
    """Start the scheduler using the cron expression from settings."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    settings = get_effective_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    try:
        trigger = CronTrigger.from_crontab(settings.post_schedule_cron, timezone=settings.timezone)
    except ValueError as exc:
        raise ValueError(
            f"Invalid POST_SCHEDULE_CRON: {settings.post_schedule_cron!r} ({exc})"
        ) from exc

    scheduler.add_job(
        _job,
        trigger=trigger,
        id="auto_post",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started with cron %r (%s)",
        settings.post_schedule_cron,
        settings.timezone,
    )
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
