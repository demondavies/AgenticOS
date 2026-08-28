import os

"""AgenticOS autonomous scheduler.

Owns recurring AgenticOS jobs so interface adapters do not own autonomous
system behaviour.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


def scheduled_vault_summary_job(
    *,
    sync_master_brain_vector_db,
    vault_dir: str,
    execute_swarm,
):
    async def job():
        print("⏰ [Cron Engine] Executing Daily Master Brain Vault Summary & Vector Sync Job...")
        try:
            sync_master_brain_vector_db()
            files = [f for f in os.listdir(vault_dir) if f.endswith(".md")]
            file_summary = (
                f"Total Markdown Files in Vault: {len(files)}\n"
                + "\n".join([f"- {f}" for f in files[:10]])
            )
            mission = (
                "Synthesize a daily executive summary report for Master Brain vault.\n"
                f"Vault Context:\n{file_summary}"
            )
            await execute_swarm(mission)
            print("✅ [Cron Engine] Daily Vault Summary Job completed and staged for approval!")
        except Exception as e:
            print(f"❌ [Cron Engine Error]: {str(e)}")

    return job


def scheduled_memory_compaction_job(*, compact_memory, channel_id: str):
    async def job():
        print("⏰ [Cron Engine] Running periodic memory compaction job...")
        await compact_memory(channel_id, keep_recent=5)

    return job


def init_scheduler(
    *,
    scheduler: AsyncIOScheduler,
    vault_summary_job,
    memory_compaction_job,
):
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
    scheduler.start()
    print("⏰ [Agentic OS] APScheduler Cron Core Active and Running!")
    return scheduler
