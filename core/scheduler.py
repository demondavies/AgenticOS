"""
ARNIE Agentic OS
Scheduler capability.

Owns APScheduler lifecycle and scheduled AgenticOS jobs.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


class AgentScheduler:
    """Owns AgenticOS scheduled jobs."""

    def __init__(self, vault_service, harness, vault_dir: str):
        self.scheduler = AsyncIOScheduler()
        self.vault_service = vault_service
        self.harness = harness
        self.vault_dir = vault_dir

    async def scheduled_vault_summary_job(self):
        print(
            "⏰ [Cron Engine] Executing Daily Master Brain "
            "Vault Summary & Vector Sync Job..."
        )
        try:
            self.vault_service.sync_master_brain_vector_db()

            import os

            files = [
                f
                for f in os.listdir(self.vault_dir)
                if f.endswith(".md")
            ]

            file_summary = (
                f"Total Markdown Files in Vault: {len(files)}\n"
                + "\n".join(f"- {f}" for f in files[:10])
            )

            mission = (
                "Synthesize a daily executive summary report for "
                "Master Brain vault.\n"
                f"Vault Context:\n{file_summary}"
            )

            await self.harness.swarm_orchestrator.execute_crew_pipeline(
                mission
            )

            print(
                "✅ [Cron Engine] Daily Vault Summary Job "
                "completed and staged for approval!"
            )

        except Exception as e:
            print(f"❌ [Cron Engine Error]: {str(e)}")

    async def scheduled_memory_compaction_job(self):
        print(
            "⏰ [Cron Engine] Running periodic memory compaction job..."
        )

        await self.harness.compact_memory(
            "local_web_dashboard",
            keep_recent=5,
        )

    def init(self):
        self.scheduler.add_job(
            self.scheduled_vault_summary_job,
            trigger=CronTrigger(hour=8, minute=0),
            id="daily_vault_summary",
            replace_existing=True,
        )

        self.scheduler.add_job(
            self.scheduled_memory_compaction_job,
            trigger="interval",
            minutes=30,
            id="periodic_memory_compaction",
            replace_existing=True,
        )

        self.scheduler.start()

        print(
            "⏰ [Agentic OS] APScheduler Cron Core Active and Running!"
        )

    def get_jobs(self):
        return [
            {
                "id": job.id,
                "next_run": str(job.next_run_time),
                "trigger": str(job.trigger),
            }
            for job in self.scheduler.get_jobs()
        ]