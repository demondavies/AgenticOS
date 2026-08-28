import discord
import json
import re
import os
import sys
import asyncio
import uvicorn
import uuid
import psutil
import random
import time
import io
import wave

from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import threading

# 🔒 SECURE SYSTEM CONFIGURATION
ALLOWED_USERS = [319548579163144192]  # Optional: Paste numeric Discord User ID here when using Discord
DB_PATH = r"G:\AgenticOS\data\memory.db"
VAULT_DIR = r"G:\Master_Brain\Master_Brain"
WEB_CHANNEL_ID = "local_web_dashboard"

# Client, Scheduler & Chroma Vector DB Initialization
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

scheduler = AsyncIOScheduler()


BASE_SYSTEM_PROMPT = """You are Arnie, an advanced agentic Discord bot powered by Hermes 3, but you speak, think, and act exactly like ARNOLD SCHWARZENEGGER. Maintain this persona at all times!
You have a persistent database memory on this machine. Help the user with their questions using your high-energy Austrian persona."""

OWNER_EXTENSIONS = """
You have access to privileged local agent tools. If a tool matches the user request, you are FORBIDDEN from explaining it or writing conversational filler. You must call it immediately.
- If the user asks about current events, call 'web_search'.
- If the user asks for the CURRENT TIME or TODAY'S DATE, call 'get_current_time'.
- If the user wants to save an idea or note, call 'write_obsidian_note'.
- If the user wants to read or look inside a note file, call 'read_obsidian_note'.
- If the user wants to search past notes, project contexts, or vault knowledge, call 'search_vault'.
- If the user wants to run a shell command, terminal command, or system command, call 'run_terminal_command'.
- If the user wants to launch a multi-agent swarm task or crew pipeline, call 'launch_swarm'.
- If the user wants to open or launch a local application, software, or shortcut (e.g., Obsidian, VS Code, Terminal, Chrome), call 'launch_app'.
- If the user asks for hardware telemetry, CPU, RAM, or system metrics, call 'get_system_metrics'.
- If the user asks for a daily vault summary, today's vault summary, a Master Brain summary, or asks what is important in the vault today, call 'get_daily_vault_summary'.


To call a tool, respond ONLY with an XML block matching this exact format:
<tool_call>
{"name": "get_system_metrics", "arguments": {}}
</tool_call>
Do not add conversational text before or after the block. Absolute silence except for the tag!"""



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
from core.agent_runtime import AgentRuntime, ToolApprovalRequired
from core.intent import create_default_intent_router
from capabilities.voice import VoiceService
from capabilities.voice.http import VoiceHTTPAdapter
from core.swarm import STAGED_ARTIFACTS

from capabilities.vault import (
    get_daily_vault_summary,
    get_vault_location,
    list_vault_notes,
    read_obsidian_note,
    read_vault_file,
    search_master_brain_vault,
    save_vault_file,
    sync_master_brain_vector_db,
    write_obsidian_note,
)

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
    model="hermes3:8b",
)

# Configure the canonical AgenticOS VoiceService only after the canonical
# tool executor exists. This keeps voice orchestration outside bot.py while
# ensuring the service has all required AgenticOS dependencies at startup.
TOOL_HARNESS.voice.configure_agent(
    harness=TOOL_HARNESS,
    intent_router=AGENT_RUNTIME.intent_router,
    tool_registry=TOOL_REGISTRY,
    tool_executor=AGENT_RUNTIME.execute_intent_tool,
    channel_id=WEB_CHANNEL_ID,
    base_system_prompt=BASE_SYSTEM_PROMPT,
    owner_extensions=OWNER_EXTENSIONS,
    model="hermes3:8b",
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
TOOL_HARNESS.memory.init_db()


# 🧠 CHROMADB VECTOR SEARCH RAG ENGINE
# NOTE: nomic-embed-text is an embedding workload, not LLM chat.
# It remains on the direct Ollama embedding path during this migration.







# ============================================================
# 📚 DAILY MASTER BRAIN VAULT SUMMARY
# ============================================================




# 🛠️ AGENT TOOL SUITE
def launch_swarm_task(mission: str) -> str:
    """Discord/interface compatibility adapter for Harness-owned Swarm."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(TOOL_HARNESS.execute_swarm(mission))

    raise RuntimeError(
        "launch_swarm_task cannot run synchronously inside an active event loop."
    )


# ⏰ AUTONOMOUS CRON SCHEDULER JOBS
async def scheduled_vault_summary_job():
    print("⏰ [Cron Engine] Executing Daily Master Brain Vault Summary & Vector Sync Job...")
    try:
        sync_master_brain_vector_db()
        files = [f for f in os.listdir(VAULT_DIR) if f.endswith(".md")]
        file_summary = f"Total Markdown Files in Vault: {len(files)}\n" + "\n".join([f"- {f}" for f in files[:10]])
        
        mission = f"Synthesize a daily executive summary report for Master Brain vault.\nVault Context:\n{file_summary}"
        await TOOL_HARNESS.execute_swarm(mission)
        print("✅ [Cron Engine] Daily Vault Summary Job completed and staged for approval!")
    except Exception as e:
        print(f"❌ [Cron Engine Error]: {str(e)}")


async def scheduled_memory_compaction_job():
    print("⏰ [Cron Engine] Running periodic memory compaction job...")
    await TOOL_HARNESS.compact_memory(WEB_CHANNEL_ID, keep_recent=5)


def init_cron_scheduler():
    scheduler.add_job(
        scheduled_vault_summary_job,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_vault_summary",
        replace_existing=True
    )
    scheduler.add_job(
        scheduled_memory_compaction_job,
        trigger="interval",
        minutes=30,
        id="periodic_memory_compaction",
        replace_existing=True
    )
    scheduler.start()
    print("⏰ [Agentic OS] APScheduler Cron Core Active and Running!")


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


# 🌐 FASTAPI WEB INFRASTRUCTURE
app = FastAPI()


class ChatPayload(BaseModel):
    message: str


class VoiceSpeakPayload(BaseModel):
    text: str


class GetNotePayload(BaseModel):
    filename: str


class SaveNotePayload(BaseModel):
    filename: str
    content: str


class ApprovalPayload(BaseModel):
    task_id: str
    target_filename: str | None = None


@app.get("/api/vault/files")
async def get_vault_files():
    return JSONResponse(
        content={
            "path": get_vault_location(),
            "files": list_vault_notes(),
        }
    )



@app.post("/api/chat")
async def api_chat(payload: ChatPayload):
    reply = await AGENT_RUNTIME.execute(
        WEB_CHANNEL_ID,
        "local_owner_web",
        payload.message,
        is_owner=True,
        source="ui",
    )
    
    latest_staged = None
    if STAGED_ARTIFACTS:
        t_id, data = list(STAGED_ARTIFACTS.items())[-1]
        latest_staged = {
            "task_id": t_id,
            "filename": data["default_filename"],
            "mission": data["mission"]
        }
        
    return JSONResponse(content={"reply": reply, "staged_artifact": latest_staged})


@app.post("/api/voice/transcribe")
async def api_voice_transcribe():
    return await VOICE_API.transcribe()


@app.post("/api/voice/stream")
async def api_voice_stream(payload: ChatPayload):
    return VOICE_API.stream_response(payload.message, is_owner=True)


@app.post("/api/voice/listen")
async def api_voice_listen():
    return await VOICE_API.listen()


@app.post("/api/voice/speak")
async def api_voice_speak(payload: VoiceSpeakPayload):
    return await VOICE_API.speak(payload.text)


@app.get("/api/cron/jobs")
async def get_cron_jobs():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time),
            "trigger": str(job.trigger)
        })
    return JSONResponse(content={"jobs": jobs})


@app.post("/api/memory/compact")
async def api_compact_memory():
    try:
        msg = await TOOL_HARNESS.compact_memory(WEB_CHANNEL_ID, keep_recent=5)
        return JSONResponse(content={"status": "success", "message": msg})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/vector/sync")
async def api_sync_vector_db():
    msg = sync_master_brain_vector_db()
    return JSONResponse(content={"status": "success", "message": msg})


@app.get("/api/swarm/staged")
async def get_staged_artifacts():
    return JSONResponse(content={"artifacts": STAGED_ARTIFACTS})


@app.post("/api/swarm/approve")
async def approve_staged_artifact(payload: ApprovalPayload):
    artifact = STAGED_ARTIFACTS.get(payload.task_id)
    if not artifact:
        return JSONResponse(status_code=404, content={"error": "Staged artifact not found or expired."})

    target_name = payload.target_filename or artifact["default_filename"]
    safe_name = re.sub(r'[\\/*?:"<>|]', "", target_name).strip()
    if not safe_name.endswith(".md") and not safe_name.endswith(".py"):
        safe_name += ".md"

    try:
        save_result = save_vault_file(safe_name, artifact["content"])
        if save_result.startswith("Failed to save file:"):
            return JSONResponse(status_code=500, content={"error": save_result})

        del STAGED_ARTIFACTS[payload.task_id]
        print(f"💾 [Swarm Approval] Written to Master_Brain: {safe_name}")
        return JSONResponse(content={
            "status": "success",
            "message": f"APPROVED! Saved swarm output to {safe_name}",
            "filename": safe_name
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed disk commit: {str(e)}"})


@app.delete("/api/swarm/reject/{task_id}")
async def reject_staged_artifact(task_id: str):
    if task_id in STAGED_ARTIFACTS:
        del STAGED_ARTIFACTS[task_id]
        return JSONResponse(content={"status": "success", "message": "Artifact discarded from staging memory!"})
    return JSONResponse(status_code=404, content={"error": "Artifact ID missing."})


@app.post("/api/get_note")
async def api_get_note(payload: GetNotePayload):
    try:
        result = read_vault_file(payload.filename)
        if result.startswith("Error: Note file ") and result.endswith(" missing."):
            return JSONResponse(status_code=404, content={"error": "File missing"})
        if result.startswith("Error: Note filename is empty"):
            return JSONResponse(status_code=400, content={"error": result})
        if result.startswith("Failed to read file:"):
            return JSONResponse(status_code=500, content={"error": result})

        return JSONResponse(content={"content": result})

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/save_note")
async def api_save_note(payload: SaveNotePayload):
    try:
        result = save_vault_file(payload.filename, payload.content)
        if result.startswith("Failed to save file:"):
            return JSONResponse(status_code=500, content={"error": result})

        return JSONResponse(
            content={
                "status": "success",
                "message": result,
            }
        )

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/", response_class=FileResponse)
async def dashboard():
    index_path = os.path.join(
        os.path.dirname(__file__),
        "web",
        "index.html",
    )

    if not os.path.exists(index_path):
        return JSONResponse(
            status_code=404,
            content={"error": "web/index.html file missing."},
        )

    return FileResponse(index_path)


# 🔄 CONCURRENT RUNNER ENGINE (Standalone Capable)
async def main():
    init_cron_scheduler()
    sync_master_brain_vector_db()

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