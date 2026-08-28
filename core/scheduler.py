"""AgenticOS autonomous scheduler.

The scheduler owns timing only. Scheduled AgenticOS behaviour is supplied as
callbacks by the application composition root; business logic remains owned by
the Harness, Tools, and capabilities.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


AsyncJob = Callable[[], Awaitable[object]]


def scheduled_vault_summary_job(
    *,
    execute_vault_summary: AsyncJob,
) -> AsyncJob:
    """Create the daily vault-summary trigger.

    The scheduler deliberately knows nothing about Vault, ChromaDB, Markdown
    files, or Swarm orchestration. The supplied callback owns execution.
    """

    async def job() -> object:
        print("⏰ [Cron Engine] Executing Daily Master Brain Vault Summary Job...")
        try:
            result = await execute_vault_summary()
            print("✅ [Cron Engine] Daily Vault Summary Job completed.")
            return result
        except Exception as exc:
            print(f"❌ [Cron Engine Error]: {exc}")
            raise

    return job


def scheduled_memory_compaction_job(
    *,
    compact_memory,
    channel_id: str,
):
    """Create the periodic memory-compaction trigger."""

    async def job():
        print("⏰ [Cron Engine] Running periodic memory compaction job...")
        return await compact_memory(channel_id, keep_recent=5)

    return job


def scheduled_task_cleanup_job(
    *,
    prune_tasks,
    days: int = 30,
):
    """Create the periodic Task-cleanup trigger.

    `prune_tasks` is the Harness-owned, synchronous SQLite operation; it is
    run off the event loop thread so the cron tick never blocks it.
    """

    async def job():
        print("⏰ [Cron Engine] Running periodic Task cleanup job...")
        deleted = await asyncio.to_thread(prune_tasks, days)
        print(f"🧹 [Cron Engine] Task cleanup removed {deleted} terminal Task(s).")
        return deleted

    return job


def init_scheduler(
    *,
    scheduler: AsyncIOScheduler,
    vault_summary_job,
    memory_compaction_job,
    task_cleanup_job,
):
    """Register recurring jobs and start the scheduler."""

    scheduler.add_job(
        vault_summary_job,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_vault_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        memory_compaction_job,
        trigger="interval",
        minutes=30,
        id="periodic_memory_compaction",
        replace_existing=True,
    )
    scheduler.add_job(
        task_cleanup_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="periodic_task_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    print("⏰ [Agentic OS] APScheduler Cron Core Active and Running!")
    return scheduler
