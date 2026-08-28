import discord
import json
import sys
import asyncio
import uvicorn


# 🔒 SECURE SYSTEM CONFIGURATION
ALLOWED_USERS = [319548579163144192]  # Optional: Paste numeric Discord User ID here when using Discord
WEB_CHANNEL_ID = "local_web_dashboard"

# Client & Scheduler Initialization
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


from core.config import BASE_SYSTEM_PROMPT, DEFAULT_MODEL, OWNER_EXTENSIONS, DISCORD_VOICE_ENABLED



# ============================================================
# ARNIE AGENTIC OS MODEL PROVIDER
# ============================================================
AGENTICOS_ROOT = r"G:\AgenticOS"

if AGENTICOS_ROOT not in sys.path:
    sys.path.insert(0, AGENTICOS_ROOT)

from core.tools import (
    create_default_registry,
    ToolRegistry,
)

from core.harness import AgentHarness
from core.tasks import Task
from core.agent_runtime import AgentRuntime, ToolApprovalRequired
from core.intent import create_default_intent_router
from capabilities.voice import VoiceService
from capabilities.voice.http import VoiceHTTPAdapter


# Canonical AgenticOS tool registry.
# Tool execution is owned by the Harness/Policy/ToolRegistry boundary.
TOOL_REGISTRY: ToolRegistry = create_default_registry()

# Canonical AgenticOS Harness. The legacy bot remains an interface adapter;
# tool execution semantics belong to the Harness/ToolRegistry boundary.
TOOL_HARNESS = AgentHarness(
    tool_registry=TOOL_REGISTRY,
    voice_service=VoiceService(),
)

VOICE_API = VoiceHTTPAdapter(TOOL_HARNESS.voice)

# Canonical AgenticOS Agent Runtime.
# Conversational orchestration, deterministic intent routing, Tool execution,
# Policy handling, memory coordination, and model calls live outside bot.py.
AGENT_RUNTIME = AgentRuntime(
    harness=TOOL_HARNESS,
    tool_registry=TOOL_REGISTRY,
    intent_router=create_default_intent_router(),
    base_system_prompt=BASE_SYSTEM_PROMPT,
    owner_extensions=OWNER_EXTENSIONS,
    model=DEFAULT_MODEL,
)

# Configure the canonical AgenticOS VoiceService only after the canonical
# tool executor exists. This keeps voice orchestration outside bot.py while
# ensuring the service has all required AgenticOS dependencies at startup.
TOOL_HARNESS.configure_voice_agent(
    harness=TOOL_HARNESS,
    intent_router=AGENT_RUNTIME.intent_router,
    tool_registry=TOOL_REGISTRY,
    tool_executor=AGENT_RUNTIME.execute_intent_tool,
    channel_id=WEB_CHANNEL_ID,
    base_system_prompt=BASE_SYSTEM_PROMPT,
    owner_extensions=OWNER_EXTENSIONS,
    model=DEFAULT_MODEL,
)


print(
    "🧠 [Model Provider] Active provider: "
    + ", ".join(TOOL_HARNESS.models.list_providers())
)
print(
    "🛠️ [Tool Registry] Wave 1 active: "
    + ", ".join(TOOL_REGISTRY.names())
)


# AgenticOS Memory owns persistence. The bot supplies only the model callback
# required for LLM-assisted compaction.
from capabilities.memory import configure_memory_summarizer
configure_memory_summarizer(TOOL_HARNESS.chat)
TOOL_HARNESS.initialize_memory()
TOOL_HARNESS.initialize_tasks()



# ⏰ AGENTIC OS AUTONOMOUS SCHEDULER BOUNDARY
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.scheduler import (
    init_scheduler,
    scheduled_memory_compaction_job,
    scheduled_task_cleanup_job,
    scheduled_vault_summary_job,
)

scheduler = AsyncIOScheduler()

# 🧠 AGENT PROCESSING CENTRAL ROUTER
# 🤖 DISCORD BACKEND LOOP
class ToolApprovalView(discord.ui.View):
    """One-shot Discord approval control for privileged Tool execution."""

    def __init__(self, requester_id: int, tool_name: str, arguments: dict):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.tool_name = tool_name
        self.arguments = dict(arguments or {})
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This approval request belongs to another user.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return
        self.resolved = True
        for child in self.children:
            child.disabled = True

        try:
            result = await AGENT_RUNTIME.execute_intent_tool(
                self.tool_name,
                self.arguments,
                source="discord",
                user_approved=True,
            )
            await interaction.response.edit_message(
                content=f"✅ Approved and executed `{self.tool_name}`.\n\n{result}",
                view=self,
            )
        except Exception as exc:
            await interaction.response.edit_message(
                content=f"❌ Approved, but execution failed: {exc}",
                view=self,
            )

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return
        self.resolved = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"🛑 Denied `{self.tool_name}`.",
            view=self,
        )


@client.event
async def on_ready():
    print("🤖 Discord Bot Gateway Connected successfully.")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if isinstance(message.channel, discord.DMChannel) or client.user.mentioned_in(message):
        is_owner = (message.author.id in ALLOWED_USERS)

        print(
            f"🔐 [Auth] user={message.author.id} "
            f"owner={is_owner} allowed={ALLOWED_USERS}"
        )

        clean_content = message.content.replace(
            f"<@{client.user.id}>", ""
        ).strip()
        try:
            reply = await AGENT_RUNTIME.execute(
                message.channel.id,
                message.author.id,
                clean_content,
                is_owner,
                source="discord",
            )
            await message.reply(reply)

            # Speak the reply in the user's voice channel when enabled.
            # message.author is a plain User (no .voice attribute) unless
            # resolved against the guild's member cache. Without the
            # privileged Members intent that cache can miss, so fall back
            # to an explicit API fetch rather than trusting message.author.
            voice_member = None
            if message.guild:
                voice_member = message.guild.get_member(message.author.id)
                if voice_member is None:
                    try:
                        voice_member = await message.guild.fetch_member(
                            message.author.id
                        )
                    except discord.HTTPException:
                        voice_member = None
            if (
                DISCORD_VOICE_ENABLED
                and voice_member
                and voice_member.voice
                and voice_member.voice.channel
            ):
                from capabilities.voice.discord_voice import DiscordVoiceSpeaker
                asyncio.create_task(
                    DiscordVoiceSpeaker().speak(
                        voice_member.voice.channel,
                        reply,
                    )
                )
        except ToolApprovalRequired as approval:
            view = ToolApprovalView(
                message.author.id,
                approval.tool_name,
                approval.arguments,
            )
            await message.reply(
                f"⚠️ **Approval required**\n\n"
                f"Tool: `{approval.tool_name}`\n"
                f"Arguments: `{json.dumps(approval.arguments, ensure_ascii=False)}`\n\n"
                f"{approval.message}",
                view=view,
            )
        except Exception as exc:
            print(f"❌ [Discord Agent Error]: {exc}")
            await message.reply(f"Tool execution failed: {exc}")


# 🌐 FASTAPI HTTP INTERFACE
from api import create_app

app = create_app(
    agent_runtime=AGENT_RUNTIME,
    harness=TOOL_HARNESS,
    voice_api=VOICE_API,
    scheduler=scheduler,
    web_channel_id=WEB_CHANNEL_ID,
)


# 🔄 CONCURRENT RUNNER ENGINE (Standalone Capable)
async def run_scheduled_vault_summary():
    """Run the canonical daily summary Tool through the Harness boundary."""
    task = Task(
        title="Daily Master Brain Vault Summary",
        description=(
            "Run the canonical daily Master Brain vault summary "
            "operation on the scheduled system cycle."
        ),
        workspace="system",
        metadata={"agent": "Coordinator"},
    )

    return await TOOL_HARNESS.execute_tool_for_task_async(
        task,
        "get_daily_vault_summary",
        source="scheduler",
    )


async def main():
    init_scheduler(
        scheduler=scheduler,
        vault_summary_job=scheduled_vault_summary_job(
            execute_vault_summary=run_scheduled_vault_summary,
        ),
        memory_compaction_job=scheduled_memory_compaction_job(
            compact_memory=TOOL_HARNESS.compact_memory,
            channel_id=WEB_CHANNEL_ID,
        ),
        task_cleanup_job=scheduled_task_cleanup_job(
            prune_tasks=TOOL_HARNESS.prune_tasks,
        ),
    )

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    print(
        "\n🚀 [Agentic OS Core Initiated]"
        "\n🖥️  Web UI Chat Dashboard: http://127.0.0.1:8000"
    )

    DISCORD_BOT_TOKEN = ""  # Paste token here if using Discord, or leave empty!

    if DISCORD_BOT_TOKEN.strip():
        print("🤖 Connecting to Discord Gateway...")
        asyncio.create_task(client.start(DISCORD_BOT_TOKEN))
    else:
        print("⚡ LOCAL-ONLY MODE: Skipping Discord Gateway connection.")

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())