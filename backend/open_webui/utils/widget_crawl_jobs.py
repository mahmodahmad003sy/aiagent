"""In-process registry for widget crawl / extend background jobs. The database stays the source of truth."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from open_webui.models.chat_widget_crawl import ChatWidgetCrawlRuns
from open_webui.utils.widget_crawl_urls import HEARTBEAT_INTERVAL_SECONDS

log = logging.getLogger(__name__)


@dataclass
class WidgetJob:
    widget_id: str
    run_id: str
    kind: str  # crawl | extend
    cancel_event: asyncio.Event
    task: Optional[asyncio.Task] = None


_jobs: dict[str, WidgetJob] = {}

# Serialises "is a job active?" + "start job" inside this process.
job_start_lock = asyncio.Lock()


async def _heartbeat(run_id: str) -> None:
    while True:
        try:
            await ChatWidgetCrawlRuns.touch_heartbeat(run_id)
        except Exception as e:
            log.warning('Widget crawl heartbeat failed for %s: %s', run_id, e)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


def start_job(
    widget_id: str,
    run_id: str,
    kind: str,
    runner: Callable[[asyncio.Event], Awaitable[None]],
) -> WidgetJob:
    job = WidgetJob(widget_id=widget_id, run_id=run_id, kind=kind, cancel_event=asyncio.Event())

    async def wrapper() -> None:
        heartbeat = asyncio.create_task(_heartbeat(run_id))
        try:
            await runner(job.cancel_event)
        finally:
            heartbeat.cancel()
            if _jobs.get(widget_id) is job:
                _jobs.pop(widget_id, None)

    _jobs[widget_id] = job
    job.task = asyncio.create_task(wrapper())
    return job


def request_cancel(widget_id: str) -> None:
    job = _jobs.get(widget_id)
    if job:
        job.cancel_event.set()
